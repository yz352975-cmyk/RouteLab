"""Run trusted player Python in a timed child process, NOT a security sandbox.

Filesystem, imports and network access are not restricted. The simulation itself
uses no network. Use only code you wrote or trust.
"""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import traceback
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import World, POSITIONS, SOURCE, DESTINATION, ctx_for, validate_global, validate_local_hop
from distance_vector import DistanceVectorNetwork, ProtocolError


class LimitedOutput(io.TextIOBase):
    """Keep print() from corrupting the JSON protocol or exhausting log memory."""
    def __init__(self):
        self.text = ''

    def write(self, value):
        value = str(value)
        self.text = (self.text + value)[-6000:]
        return len(value)

    def flush(self):
        pass


def _program(program):
    namespace = {'__name__': '__routelab_user__'}
    exec(compile(program, 'routing.py', 'exec'), namespace, namespace)
    solve = namespace.get('solve')
    if not callable(solve):
        raise ProtocolError('没有找到 def solve(ctx): 函数。')
    return solve


def player_line(exc):
    if isinstance(exc, SyntaxError) and exc.filename == 'routing.py':
        return exc.lineno
    return next((f.lineno for f in reversed(traceback.extract_tb(exc.__traceback__))
                 if f.filename == 'routing.py'), None)


def evaluate(program: str, world: World, checkpoint=None) -> dict:
    output = LimitedOutput()
    with redirect_stdout(output), redirect_stderr(output):
        result = _evaluate(program, world, checkpoint)
    if output.text:
        result['log'].append('玩家输出（末 6000 字符）：\n' + output.text)
    result['seed'] = world.seed
    return result


def _evaluate(program, world, checkpoint):
    log, route, cost = [], [], 0
    sim = None
    current = SOURCE
    location = ''

    def finish(ok, message):
        result = dict(ok=ok, message=message, route=list(route), cost=cost, log=log)
        if sim is not None:
            sim.record_frame()
            if not ok:
                entry = sim.routers[current]['table'].get(DESTINATION, {})
                log.append(f"t={sim.time} 包停在 {current}；到 F 的本地表项："
                           f"下一跳 {entry.get('next_hop') or '无'}，距离 {entry.get('metric', 16)}。")
            result.update(checkpoint=sim.checkpoint(), frames=sim.frames,
                          events=sim.events, convergence=sim.destination_convergence(),
                          context=sim.context(current, 'forward'),
                          update_contexts=sim.last_contexts, time=sim.time)
        return result

    try:
        if world.protocol != 'dv':
            solve = _program(program)
            if world.protocol == 'service':
                from service_incident import INCIDENTS, evaluate_service
                return evaluate_service(world.seed, solve, INCIDENTS[world.title])
            if world.protocol == 'carrier':
                from carriers import validate
                data = ctx_for(world)
                ok, msg, route, cost = validate(data, solve(deepcopy(data)))
                return finish(ok, msg)
            if world.mode == 'global':
                ok, msg, path, total = validate_global(world, solve(ctx_for(world)))
                route, cost = path, total
                log.append('全局拓扑已提供，正在计算完整路径。')
                return finish(ok, msg)
            # v0.2 custom World/ctx compatibility; never used by new DV worlds.
            route, visited = [SOURCE], []
            for _ in range(12):
                if current == DESTINATION:
                    return finish(True, f'送达！总成本 {cost}。')
                chosen = solve(ctx_for(world, current, visited))
                ok, why, hop_cost = validate_local_hop(world, current, chosen, visited)
                if not ok:
                    return finish(False, why)
                visited.append(current)
                current = chosen
                route.append(current)
                cost += hop_cost
            return finish(False, '经过太多跳，疑似路由环路。')

        sim = DistanceVectorNetwork.for_world(world, checkpoint)
        # Separate globals as well as explicit state: no hidden inter-router channel.
        solvers = {node: _program(program) for node in sim.nodes}
        route = [SOURCE]
        ttl = 12
        loop_seen = False
        wait_count = 0

        def update(node, ctx):
            nonlocal location
            location = f't={sim.time} 路由器 {node} / update'
            return solvers[node](ctx)

        log.append(f'事件种子 {world.seed}；消息延迟 {world.delay_min}～{world.delay_max} 时隙。')
        log.append('从上次成功后的表与在途消息继续。' if checkpoint else '冷启动：每个路由器只知道自己和本地链路。')
        for _ in range(world.pre_ticks):
            sim.step(update)
        for _ in range(world.run_ticks):
            sim.step(update)
            location = f't={sim.time} 路由器 {current} / forward'
            ctx = sim.context(current, 'forward', ttl=ttl)
            chosen = solvers[current](ctx)
            if not isinstance(ctx['state'], dict):
                raise ProtocolError('ctx[state] 必须保留为字典；其中可存放 JSON 数据。')
            sim.routers[current]['state'] = deepcopy(ctx['state'])
            if chosen is None:
                wait_count += 1
                if wait_count == 1 or wait_count % 16 == 0:
                    log.append(f't={sim.time} {current} 暂缓转发；消息交换继续。')
                continue
            if not isinstance(chosen, str):
                raise ProtocolError('forward 阶段返回下一跳字符串，或 None 等待；不要返回整条路线/路由表。')
            n = next((n for n in sim.neighbors(current) if n['to'] == chosen), None)
            if n is None:
                return finish(False, f'{current} 无法直接到 {chosen!r}；请查看本地邻居。')
            if not n['up']:
                return finish(False, f't={sim.time} 线路 {current}—{chosen} 已断开；本地表尚未撤销旧下一跳。')
            if not n['allowed']:
                return finish(False, f't={sim.time} 策略禁止经过 {chosen}；检查策略是否进入了路由表计算。')
            previous = current
            current = chosen
            route.append(current)
            cost += n['cost']
            ttl -= 1
            log.append(f't={sim.time} 数据包 {previous} → {current}；TTL={ttl}')
            sim.event('packet', sender=previous, receiver=current, ttl=ttl)
            if current in route[:-1]:
                loop_seen = True
                sim.event('loop', node=current, route=list(route))
                log.append(f'  环路：再次经过 {current}，旧距离通告可能互相依赖。')
            sim.record_frame(packet=dict(sender=previous, receiver=current, ttl=ttl))
            if current in sim.spoofed:
                return finish(False, f'{current} 发布虚假通告后丢弃数据包（黑洞）；消息来源与低距离不是同一回事。')
            if current == DESTINATION:
                conv = sim.destination_convergence()
                log.append(f"观察器：到 F 的路由表{'已正确' if conv['correct'] else '仍在收敛'}；"
                           f"表连续稳定 {conv['stable_for']} 时隙。")
                if not conv['correct'] or conv['stable_for'] < 2 * world.delay_max + 4 or sim.schedule:
                    return finish(False, '数据包已送达，但路由表尚未收敛或观察时间不足。'
                                  + (f"检查到 F 的表项：{', '.join(conv['unsettled'])}。" if conv['unsettled'] else '')
                                  + '继续完善 update，并在 forward 中留出传播时间后重试。')
                return finish(True, f'送达！成本 {cost}，{len(route)-1} 跳，t={sim.time}。'
                              + ('途中出现瞬态环路；查看时间线诊断。' if loop_seen else ''))
            if ttl == 0:
                return finish(False, 'TTL 耗尽：数据包在路由环路中反复转发。'
                              if loop_seen else 'TTL 耗尽：转发超过 12 跳。')
        return finish(False, f'观察窗口结束（{world.run_ticks} 时隙）仍未送达。'
                      '请观察不可达是否传播、路由是否恢复，以及 forward 是否一直返回 None。')
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
            raise
        log.append((location + '\n' if location else '') + traceback.format_exc(limit=4))
        result = finish(False, f'Python 代码异常：{type(exc).__name__}: {exc}'
                        + (f'（{location}）' if location else ''))
        result['error_line'] = player_line(exc)
        return result


INPUT_LIMIT = 2 * 1024 * 1024
OUTPUT_LIMIT = 32 * 1024 * 1024


def read_result(raw):
    def invalid_number(value):
        raise ValueError('执行器返回非有限数值：' + value)
    result = json.loads(raw, parse_constant=invalid_number)
    if (not isinstance(result, dict) or type(result.get('ok')) is not bool
            or not isinstance(result.get('message'), str) or type(result.get('cost')) is not int
            or not isinstance(result.get('route'), list) or not all(isinstance(n, str) and n in POSITIONS for n in result['route'])
            or not isinstance(result.get('log'), list) or not all(isinstance(s, str) for s in result['log'])):
        raise ValueError('执行器返回格式错误。')
    for name in ('frames', 'events'):
        entries = result.get(name, [])
        if not isinstance(entries, list) or not all(isinstance(e, dict) and type(e.get('time')) is int for e in entries):
            raise ValueError(f'执行器返回的 {name} 格式错误。')
    if result.get('checkpoint') is not None and not isinstance(result['checkpoint'], dict):
        raise ValueError('无效 checkpoint。')
    if result.get('error_line') is not None and type(result['error_line']) is not int:
        raise ValueError('无效代码行号。')
    for event in result.get('events', []):
        if not isinstance(event.get('kind'), str):
            raise ValueError('事件缺少类型。')
    for frame in result.get('frames', []):
        if 'service' in frame:
            from service_incident import SOURCES, check_policy
            observation, metrics = frame['observation'], frame['service']
            if (not isinstance(metrics, dict) or not isinstance(observation, dict)
                    or set(observation['sources']) != set(SOURCES)
                    or not isinstance(frame.get('backlog'), dict) or set(frame['backlog']) != set(SOURCES)
                    or not all(type(q) is int and q >= 0 for q in frame['backlog'].values())
                    or not all(type(metrics.get(k)) is int for k in
                               ('time','received','processed','queue','offered','dropped','filtered'))
                    or type(metrics.get('wait')) not in (float, int)
                    or not all(type(observation.get(k)) is int for k in ('capacity','bandwidth'))
                    or not all(type(row[k]) is int for row in observation['sources'].values()
                               for k in ('requests','repeats'))):
                raise ValueError('无效监测帧。')
            check_policy(frame['policy'])
        elif not (isinstance(frame.get('tables'), dict) and isinstance(frame.get('changes'), list)
                  and isinstance(frame.get('failed'), list) and type(frame.get('in_flight')) is int):
            raise ValueError('无效路由帧。')
    return result


def local_exchange(request, timeout):
    """Drain both OS pipes concurrently and kill the trusted worker on overflow."""
    with subprocess.Popen([sys.executable, '-I', str(Path(__file__).resolve())],
                          cwd=str(Path(__file__).resolve().parent), stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0) as proc:
        deadline = time.monotonic() + timeout
        overflow = threading.Event()
        out, err = bytearray(), bytearray()

        def drain(stream, dest, limit):
            while chunk := stream.read(65536):
                if len(dest) + len(chunk) > limit:
                    overflow.set()
                    proc.kill()
                    return
                dest.extend(chunk)

        def send():
            try:
                pending = memoryview(request)
                while pending:
                    pending = pending[proc.stdin.write(pending):]
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    proc.stdin.close()
                except OSError:
                    pass

        workers = [threading.Thread(target=drain, args=(proc.stdout, out, OUTPUT_LIMIT)),
                   threading.Thread(target=drain, args=(proc.stderr, err, 65536)),
                   threading.Thread(target=send)]
        for thread in workers:
            thread.daemon = True
            thread.start()
        try:
            proc.wait(timeout=timeout)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            for thread in workers:
                thread.join(max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in workers):
            raise subprocess.TimeoutExpired(proc.args, timeout)
        if overflow.is_set():
            raise ValueError('执行器输出超过长度限制。')
        if proc.returncode:
            raise ValueError('Python 执行器退出：' + err[-600:].decode('utf-8', 'replace'))
        return read_result(bytes(out))


def run_isolated(payload, timeout=6, backend='trusted'):
    """Backend selection at the transport boundary. Never downgrade isolation."""
    try:
        if backend != 'trusted':
            raise ValueError('隔离后端未部署或未通过审阅，已拒绝执行。')
        request = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(request) > INPUT_LIMIT:
            raise ValueError('执行载荷超过 2 MiB。')
        return local_exchange(request, timeout)
    except subprocess.TimeoutExpired:
        message = f'运行超过 {timeout:g} 秒，已停止；请检查死循环或过量计算。'
    except Exception as exc:
        message = f'执行器错误：{type(exc).__name__}: {exc}'
    return dict(ok=False, message=message, route=[], cost=0, log=[])


def main():
    # Windows pipe encoding must match the GUI's explicit UTF-8 decoder.
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        payload = json.load(sys.stdin)
        if 'tutorial_step' in payload:
            from tutorial import check
            with redirect_stdout(LimitedOutput()), redirect_stderr(LimitedOutput()):
                result = check(payload['code'], payload['tutorial_step'])
            result['tutorial'] = True
        else:
            result = evaluate(payload['code'], World(**payload['world']), payload.get('checkpoint'))
        data = json.dumps(result, ensure_ascii=False, allow_nan=False)
    except Exception as exc:
        data = json.dumps(dict(ok=False, message=f'执行器错误：{type(exc).__name__}: {exc}',
                               error_line=player_line(exc), route=[], cost=0, log=[]), ensure_ascii=False)
    print(data)


if __name__ == '__main__':
    main()
