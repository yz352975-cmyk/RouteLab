"""Offline service-capacity exercise. Each request is one unit in a local FIFO."""
from collections import Counter, deque
from copy import deepcopy
from dataclasses import dataclass
import random

from carriers import OWNER


@dataclass(frozen=True)
class Incident:
    id: str
    prerequisite: str
    title: str
    brief: str
    onset: int
    windows: int
    actions: tuple
    hints: tuple
    debrief: str


S1 = Incident('S1', '十次跨网调度完成', '新服上线 · 为什么玩家开始排队？',
              '三家运营商把玩家接入游戏服 F。比较开服与稍后几个窗口的请求、重复访问和排队，再写策略保护正常登录。',
              4, 16, ('limits', 'repeat_limits'),
              ('先比较不同窗口：什么先增加，什么随后增加？哪个入口的重复访问比例与开服时不同？',
               '带宽决定可入站数量，服务器容量决定每窗能完成多少请求。正常玩家也会重试；对整个入口一刀切可能误伤。',
               'ctx["sources"][站名] 提供 requests 与 repeats。返回 {"repeat_limits": {站名: 上限}} 或 limits 总配额。两者可并用；配额每窗重置。'),
              '多个入口的重复负载挤占了共享处理槽。单源耗尽服务称 DoS，多源协同可形成 DDoS；入口数或访问量本身不能证明恶意。')
S2 = Incident('S2', 'S1 服务恢复', '活动开场 · 谁被挡在门外？',
              '活动门票开始发放，客服收到正常玩家无法登录的反馈。先用上一轮的策略跑一次，再比较各入口重试与活跃会话的变化。',
              4, 16, S1.actions,
              ('点地图上的入口，拖动时间线。两处都出现大量重试时，各有多少活跃会话？过几个窗口再看一次。',
               '很多人各重试一次，与少数会话反复访问，可能产生相似的访问量。误封率衡量正常请求被策略拦下的比例。',
               'sources 的 sessions 是窗内去重会话数。试着同时考虑 repeats 和 sessions；history 保留前三窗的入口统计。'),
              '同样的重试量可以来自不同数量的玩家。结合多个信号可以减少误封；单个会话也不能证明访问者的身份。')
INCIDENTS = {incident.id: incident for incident in (S1, S2)}
SOURCES = ('B', 'C', 'D')
CAPACITY, BANDWIDTH, BUFFER = 18, 28, 36


def windows(seed, incident=S1):
    rng = random.Random(seed)
    busy = rng.sample(SOURCES, 2)
    for tick in range(incident.windows):
        offers = []
        for source in SOURCES:
            count = rng.randint(3, 5) if incident == S1 else rng.randint(2, 3)
            for i in range(count):
                offers.append((source, rng.random() < .12, True, i))
            if tick < incident.onset:
                continue
            if incident == S1 and source in busy:
                offers.extend((source, True, False, -1) for _ in range(rng.randint(13, 17)))
            elif incident == S2:
                # The activity moves between entrances halfway through the incident.
                event_gate, other_gate = busy if tick < 10 else reversed(busy)
                if source == event_gate:
                    offers.extend((source, True, True, count+i//2) for i in range(rng.randint(9, 11)))
                elif source == other_gate:
                    offers.extend((source, True, False, -1) for _ in range(rng.randint(13, 17)))
        rng.shuffle(offers)
        yield offers


def observe(tick, offers, queue_size, history, incident=S1):
    sources = {s: dict(requests=0, repeats=0, operator=OWNER[s]) for s in SOURCES}
    sessions = {s: set() for s in SOURCES}
    for source, repeat, _, session in offers:
        sources[source]['requests'] += 1
        sources[source]['repeats'] += int(repeat)
        sessions[source].add(session)
    if incident == S2:
        for source in SOURCES:
            sources[source]['sessions'] = len(sessions[source])
    return dict(mode='service', incident=incident.id, time=tick, capacity=20 if incident == S2 else CAPACITY, bandwidth=BANDWIDTH,
                buffer=BUFFER, queue=queue_size, sources=sources, history=deepcopy(history[-3:]))


def check_policy(value):
    if type(value) is not dict or set(value) - set(S1.actions):
        raise ValueError('请返回配额字典，仅支持 limits（总请求）和 repeat_limits（重复请求）。')
    for quotas in value.values():
        if type(quotas) is not dict or any(s not in SOURCES or type(n) is not int or not 0 <= n <= 100
                                            for s, n in quotas.items()):
            raise ValueError('配额按入口 B/C/D 设置，每项必须是 0 到 100 的整数。')
    return deepcopy(value)


def simulate(seed, solve, incident=S1):
    frames, history = [], []
    queue = deque()
    offered, served = Counter(), Counter()
    queued = 0
    blocked = Counter()
    for tick, batch in enumerate(windows(seed, incident)):
        ctx = observe(tick, batch, len(queue), history, incident)
        policy = check_policy(solve(deepcopy(ctx)))
        admitted, repeats = Counter(), Counter()
        filtered = dropped = received = 0
        for src, repeat, normal, _ in batch:
            if tick >= incident.onset:
                offered[normal] += 1
            if (admitted[src] >= policy.get('limits', {}).get(src, 100)
                    or repeat and repeats[src] >= policy.get('repeat_limits', {}).get(src, 100)):
                filtered += 1
                if tick >= incident.onset:
                    blocked[normal] += 1
                continue
            admitted[src] += 1
            repeats[src] += int(repeat)
            if received >= BANDWIDTH or len(queue) >= BUFFER:
                dropped += 1
                continue
            received += 1
            queue.append((tick, normal, src))
        processed = min(len(queue), ctx['capacity'])
        wait = 0
        for _ in range(processed):
            arrival, normal, _ = queue.popleft()
            wait += tick - arrival
            if arrival >= incident.onset:
                served[normal] += 1
        snapshot = dict(time=tick, offered=len(batch), received=received, filtered=filtered,
                        dropped=dropped, processed=processed, queue=len(queue),
                        wait=round(wait / max(1, processed), 2))
        history.append(dict(snapshot, sources=deepcopy(ctx['sources'])))
        backlog = Counter(src for _, _, src in queue)
        frames.append(dict(time=tick, service=snapshot, observation=ctx, policy=policy,
                           backlog={s: backlog[s] for s in SOURCES}))
        if tick >= incident.onset:
            queued += len(queue)
    metrics = dict(availability=served[True] / offered[True], unwanted=served[False] / offered[False],
                   mean_queue=queued / (incident.windows - incident.onset),
                   false_positive=blocked[True] / offered[True],
                   false_negative=1 - blocked[False] / offered[False])
    return frames, metrics


def evaluate_service(seed, solve, incident=S1):
    _, before = simulate(seed, lambda ctx: {}, incident)
    frames, after = simulate(seed, solve, incident)
    ok = after['availability'] >= .85 and after['unwanted'] <= .30 and after['mean_queue'] <= 4
    if incident == S2 and (after['false_positive'] > .10 or after['false_negative'] > .30):
        ok = False
        why = ('误封了过多正常请求。请比较重试次数和活跃会话数。' if after['false_positive'] > .10
               else '超过 30% 的异常请求穿过了过滤规则。请检查低会话数入口。')
    elif after['availability'] < .85:
        why = '正常登录完成率未达 85%。检查限额是否误伤正常玩家，或重复负载是否挤占处理槽。'
    elif after['unwanted'] > .30:
        why = '异常负载完成比例超过 30%；仍占用过多服务容量。'
    elif after['mean_queue'] > 4:
        why = '异常窗口的平均积压超过 4 个请求。'
    else:
        why = incident.debrief
    def summary(m):
        text = f"正常完成 {m['availability']:.0%}，异常完成 {m['unwanted']:.0%}，平均积压 {m['mean_queue']:.1f}"
        if incident == S2:
            text += f"，误封 {m['false_positive']:.0%}，漏放 {m['false_negative']:.0%}"
        return text
    return dict(ok=ok, message=why, log=['同种子无策略：' + summary(before), '本次策略：' + summary(after)],
                route=[], cost=0, frames=frames, before=before, after=after)
