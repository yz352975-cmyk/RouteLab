"""Deterministic, local, discrete-event distance-vector laboratory.

The engine transports messages and validates the *shape* of player output. It
never computes a neighbor's distance for the player. Each node owns its table,
inbox and explicit Python state. Routing policy belongs to solve(ctx).
"""
from __future__ import annotations

from copy import deepcopy
import heapq
import math
import random

INFINITY = 16
PERIOD = 4


class ProtocolError(ValueError):
    """An actionable error in a player's update result."""


def key(a, b):
    return tuple(sorted((a, b)))


def metric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError("metric 必须是 0～16 的有限数字，16 表示不可达。")
    if not math.isfinite(value) or not 0 <= value <= INFINITY:
        raise ProtocolError("metric 超出 0～16；无穷大请用 ctx['infinity']，不要用 float('inf')。")
    return value


class DistanceVectorNetwork:
    def __init__(self, edges, *, seed=0, delay=(1, 2), nodes=None,
                 blocked=(), spoofed=(), authenticated_attack=False):
        if not 1 <= delay[0] <= delay[1] <= 12:
            raise ValueError("message delay must be between 1 and 12 ticks")
        names = set(nodes or ())
        self.links = {}
        for a, b, cost in edges:
            if a == b or not 0 < cost < INFINITY:
                raise ValueError("links need distinct endpoints and positive costs below 16")
            names.update((a, b))
            self.links[key(a, b)] = dict(cost=cost, up=True, epoch=0)
        self.nodes = sorted(names)
        self.routers = {n: {"table": {n: {"metric": 0, "next_hop": n}},
                            "state": {}, "heard": {}, "last_change": 0, "seq": 0}
                        for n in self.nodes}
        self.seed = seed
        self.delay = tuple(delay)
        self.blocked = set(blocked)
        self.spoofed = set(spoofed)
        self.authenticated_attack = authenticated_attack
        self.time = self.started_at = 0
        self.next_id = 0
        self.queue = []
        self.schedule = []
        self.events = []
        self.frames = []
        self.inboxes = {n: [] for n in self.nodes}
        self.last_contexts = {}

    @classmethod
    def for_world(cls, world, checkpoint=None):
        edges = [(e['a'], e['b'], e['cost']) for e in world.graph()]
        sim = cls(edges, seed=world.seed, delay=(world.delay_min, world.delay_max),
                  nodes=list("ABCDEFG"), blocked=world.blocked, spoofed=world.spoofed)
        if checkpoint:
            sim.time = checkpoint["time"]
            sim.next_id = checkpoint["next_id"]
            for n in sim.nodes:
                if n in checkpoint["routers"]:
                    sim.routers[n] = deepcopy(checkpoint["routers"][n])
            old = {tuple(link['ends']): link for link in checkpoint["links"]}
            for ends, link in sim.links.items():
                if ends in old:
                    link['epoch'] = old[ends]['epoch']
                    link['up'] = old[ends]['up']
                    if link['cost'] != old[ends]['cost']:
                        link['epoch'] += 1
            for msg in checkpoint["pending"]:
                if key(msg['sender'], msg['receiver']) in sim.links:
                    heapq.heappush(sim.queue, (msg['deliver_at'], msg['id'], deepcopy(msg)))
        sim.started_at = sim.time
        failed = {key(*e) for e in world.failed}
        for ends in sim.links:
            sim.set_link(*ends, up=ends not in failed)
        sim.schedule = [dict(time=sim.time + change['after'], a=change['a'],
                             b=change['b'], up=change['up']) for change in world.changes]
        sim.record_frame()
        return sim

    def event(self, kind, **data):
        item = dict(time=self.time, kind=kind, **deepcopy(data))
        self.events.append(item)
        return item

    def set_link(self, a, b, *, up):
        link = self.links[key(a, b)]
        if link['up'] != up:
            link['up'] = up
            link['epoch'] += 1
            self.event('link', sender=a, receiver=b, up=up)

    def neighbors(self, node):
        result = []
        for (a, b), link in sorted(self.links.items()):
            if node not in (a, b):
                continue
            other = b if a == node else a
            result.append(dict(to=other, cost=link['cost'], up=link['up'],
                               allowed=other not in self.blocked,
                               authenticated=(other not in self.spoofed or self.authenticated_attack)))
        return result

    def context(self, node, phase='update', *, destination='F', ttl=12):
        router = self.routers[node]
        neighbors = self.neighbors(node)
        # Compatibility field: raw last-arriving local message, never an oracle.
        # Do not assume any particular schema in the player's arbitrary state.
        for neighbor in neighbors:
            cached = router.get('heard', {}).get(neighbor['to'], {})
            neighbor['estimate'] = cached.get('vector', {}).get(destination, INFINITY)
            neighbor['estimate_age'] = self.time - cached['deliver_at'] if cached else None
        return dict(mode='local', phase=phase, current=node, destination=destination,
                    time=self.time, elapsed=self.time - self.started_at,
                    infinity=INFINITY, period=PERIOD, max_delay=self.delay[1],
                    route_timeout=PERIOD * 3 + self.delay[1] * 2,
                    stable_for=self.time - router['last_change'],
                    neighbors=neighbors, table=deepcopy(router['table']),
                    inbox=deepcopy(self.inboxes[node]) if phase == 'update' else [],
                    state=deepcopy(router['state']), ttl=ttl)

    def send(self, sender, receiver, vector, *, delay=None, authenticated=None, seq=None):
        """Enqueue, never deliver synchronously. Explicit delays support experiments."""
        ends = key(sender, receiver)
        if ends not in self.links or not self.links[ends]['up']:
            return None
        if delay is None:
            delay = random.Random(f'{self.seed}:{self.next_id}:{sender}:{receiver}').randint(*self.delay)
        if delay < 1:
            raise ValueError("a message cannot arrive in the sending tick")
        if authenticated is None:
            authenticated = sender not in self.spoofed or self.authenticated_attack
        msg = dict(id=self.next_id, sender=sender, receiver=receiver,
                   vector=deepcopy(vector), sent_at=self.time, deliver_at=self.time + delay,
                   seq=self.routers[sender]['seq'] if seq is None else seq,
                   authenticated=authenticated, epoch=self.links[ends]['epoch'])
        self.next_id += 1
        heapq.heappush(self.queue, (msg['deliver_at'], msg['id'], msg))
        self.event('send', **msg)
        return msg['id']

    def _deliver(self):
        self.inboxes = {n: [] for n in self.nodes}
        while self.queue and self.queue[0][0] <= self.time:
            _, _, msg = heapq.heappop(self.queue)
            link = self.links[key(msg['sender'], msg['receiver'])]
            if not link['up'] or link['epoch'] != msg['epoch']:
                self.event('drop', reason='链路中断或已换代，丢弃旧在途消息', **msg)
            else:
                self.inboxes[msg['receiver']].append(deepcopy(msg))
                self.routers[msg['receiver']].setdefault('heard', {})[msg['sender']] = deepcopy(msg)
                self.event('deliver', **msg)

    def _validate_update(self, node, result):
        if not isinstance(result, dict) or not isinstance(result.get('table'), dict):
            raise ProtocolError("update 阶段需返回 {'table': 路由表, 'advertise': {邻居: 距离向量}}；"
                                "forward 阶段才返回下一跳字符串（或 None 等待）。")
        if len(result['table']) > 64:
            raise ProtocolError("教学网络最多支持 64 个目的地址。")
        table = {}
        neighbor_names = {n['to'] for n in self.neighbors(node)}
        for dest, route in result['table'].items():
            if not isinstance(dest, str) or not isinstance(route, dict):
                raise ProtocolError("路由表格式：{'F': {'metric': 3, 'next_hop': 'B'}}。")
            value = metric(route.get('metric'))
            hop = route.get('next_hop')
            if hop is not None and hop not in neighbor_names and hop != node:
                raise ProtocolError(f'{node} 的下一跳 {hop!r} 不是直接邻居。')
            table[dest] = dict(metric=value, next_hop=hop)
        table[node] = dict(metric=0, next_hop=node)
        ads = result.get('advertise', {})
        if not isinstance(ads, dict):
            raise ProtocolError('advertise 必须按接收邻居分别组织。')
        clean = {}
        for receiver, vector in ads.items():
            if receiver not in neighbor_names or not isinstance(vector, dict) or len(vector) > 64:
                raise ProtocolError('只能向直接邻居发送最多 64 项的距离向量。')
            if not all(isinstance(d, str) for d in vector):
                raise ProtocolError('距离向量目的地址必须是字符串。')
            clean[receiver] = {d: metric(v) for d, v in vector.items()}
        return table, clean

    def step(self, solve):
        """One tick: physical events -> arrivals -> independent updates -> sends."""
        self.time += 1
        for change in self.schedule[:]:
            if change['time'] <= self.time:
                self.set_link(change['a'], change['b'], up=change['up'])
                self.schedule.remove(change)
        self._deliver()
        outgoing = []
        for node in self.nodes:
            ctx = self.context(node)
            self.last_contexts[node] = deepcopy(ctx)
            result = solve(node, ctx)
            table, ads = self._validate_update(node, result)
            if not isinstance(ctx['state'], dict):
                raise ProtocolError('ctx[state] 必须保留为字典；其中可存放 JSON 数据。')
            router = self.routers[node]
            router['state'] = deepcopy(ctx['state'])
            if table != router['table']:
                self.event('table', node=node, before=router['table'], after=table)
                router['last_change'] = self.time
            router['table'] = table
            router['seq'] += 1
            if node in self.spoofed:
                # Environment-controlled attacker, using the same transport as honest nodes.
                ads = {n['to']: {node: 0, 'F': 0} for n in self.neighbors(node) if n['up']}
            outgoing.extend((node, receiver, vector) for receiver, vector in sorted(ads.items()))
        for sender, receiver, vector in outgoing:
            self.send(sender, receiver, vector)
        self.record_frame()

    def record_frame(self, packet=None):
        if packet is None and self.frames and self.frames[-1]['time'] == self.time:
            packet = self.frames[-1].get('packet')
        changes = [e for e in self.events if e['time'] == self.time]
        frame = dict(time=self.time, tables={n: deepcopy(r['table']) for n, r in self.routers.items()},
                     routing_loops=self.routing_loops(),
                     in_flight=len(self.queue),
                     transit=[(m['sender'], m['receiver'], m['sent_at'], m['deliver_at'])
                              for _, _, m in self.queue],
                     changes=deepcopy(changes),
                     failed=[list(e) for e, link in self.links.items() if not link['up']],
                     packet=packet)
        if self.frames and self.frames[-1]['time'] == self.time:
            self.frames[-1] = frame
        else:
            self.frames.append(frame)

    def routing_loops(self, destination='F'):
        """Observer-only cycles in the current forwarding graph, once per cycle.

        A loop can exist before any probe packet enters it. Ignore unusable
        links and unreachable entries; inspecting a cycle never changes tables.
        """
        successor = {}
        for node, router in self.routers.items():
            route = router['table'].get(destination, {})
            hop = route.get('next_hop')
            if node == destination or node in self.blocked | self.spoofed:
                continue
            if route.get('metric', INFINITY) >= INFINITY or not isinstance(hop, str):
                continue
            link = self.links.get(key(node, hop))
            if link and link['up'] and hop not in self.blocked | self.spoofed:
                successor[node] = hop
        cycles, finished = set(), set()
        for start in sorted(successor):
            path, positions = [], {}
            node = start
            while node in successor and node not in finished and node not in positions:
                positions[node] = len(path)
                path.append(node)
                node = successor[node]
            if node in positions:
                cycle = path[positions[node]:]
                pivot = cycle.index(min(cycle))
                cycles.add(tuple(cycle[pivot:] + cycle[:pivot]))
            finished.update(path)
        return [list(cycle) + [cycle[0]] for cycle in sorted(cycles)]

    def checkpoint(self):
        return dict(time=self.time, next_id=self.next_id, routers=deepcopy(self.routers),
                    links=[dict(ends=list(ends), **link) for ends, link in sorted(self.links.items())],
                    pending=[deepcopy(msg) for _, _, msg in sorted(self.queue)])

    def destination_convergence(self, destination='F'):
        """Observer-only oracle. Never exposed in solve(ctx) or used to build tables."""
        expected = {n: INFINITY for n in self.nodes}
        expected[destination] = 0
        for _ in self.nodes:
            for (a, b), link in self.links.items():
                if not link['up'] or a in self.blocked | self.spoofed or b in self.blocked | self.spoofed:
                    continue
                expected[a] = min(expected[a], INFINITY, link['cost'] + expected[b])
                expected[b] = min(expected[b], INFINITY, link['cost'] + expected[a])
        wrong = []
        for n in self.nodes:
            if n in self.blocked | self.spoofed:
                continue
            route = self.routers[n]['table'].get(destination, dict(metric=INFINITY, next_hop=None))
            correct = route['metric'] == expected[n]
            if correct and n != destination and expected[n] < INFINITY:
                hop = route['next_hop']
                link = self.links.get(key(n, hop)) if isinstance(hop, str) else None
                correct = bool(link and link['up'] and hop not in self.blocked | self.spoofed
                               and link['cost'] + expected.get(hop, INFINITY) == expected[n])
            if not correct:
                wrong.append(n)
        return dict(correct=not wrong, unsettled=wrong,
                    stable_for=self.time - max(r['last_change'] for r in self.routers.values()))
