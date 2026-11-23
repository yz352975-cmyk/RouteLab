"""RouteLab simulation core. No GUI dependencies, all sample graphs are fictional."""
from __future__ import annotations
import heapq
import random
from dataclasses import dataclass

POSITIONS = {
    "A": (0.09, 0.48), "B": (0.27, 0.22), "C": (0.39, 0.70),
    "D": (0.57, 0.19), "E": (0.67, 0.60), "F": (0.90, 0.48),
    "G": (0.58, 0.88),
}
# Undirected network with positive weights.
BASE_EDGES = [
    ("A", "B", 2), ("A", "C", 6), ("B", "C", 1),
    ("B", "D", 5), ("B", "G", 9), ("C", "D", 3),
    ("C", "E", 2), ("C", "G", 4), ("D", "E", 2),
    ("D", "F", 3), ("E", "F", 2), ("E", "G", 3),
    ("G", "F", 2),
]
SOURCE, DESTINATION = "A", "F"


def edge_key(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


@dataclass
class World:
    chapter: int
    title: str
    headline: str
    brief: str
    mode: str
    failed: tuple[tuple[str, str], ...] = ()
    blocked: tuple[str, ...] = ()
    spoofed: tuple[str, ...] = ()
    cycle: int = 0
    protocol: str = "legacy"
    seed: int = 0
    edges: tuple = ()
    delay_min: int = 1
    delay_max: int = 2
    pre_ticks: int = 1
    run_ticks: int = 160
    changes: tuple = ()
    carrier_event: int | None = None
    amendments: dict | None = None

    def graph(self) -> list[dict]:
        down = {edge_key(*e) for e in self.failed}
        return [dict(a=a, b=b, cost=cost, up=edge_key(a, b) not in down)
                for a, b, cost in (self.edges or BASE_EDGES)]

    def can_use(self, a: str, b: str) -> bool:
        if a in self.blocked or b in self.blocked or a in self.spoofed or b in self.spoofed:
            return False
        return any((x == a and y == b or y == a and x == b)
                   and edge_key(x, y) not in {edge_key(*e) for e in self.failed}
                   for x, y, _ in (self.edges or BASE_EDGES))


def shortest_path(world: World, start=SOURCE, end=DESTINATION) -> tuple[list[str], float]:
    adj = {n: [] for n in POSITIONS}
    down = {edge_key(*e) for e in world.failed}
    for a, b, cost in (world.edges or BASE_EDGES):
        if edge_key(a, b) in down or a in world.blocked or b in world.blocked or a in world.spoofed or b in world.spoofed:
            continue
        adj[a].append((b, cost)); adj[b].append((a, cost))
    queue = [(0, start)]
    distances = {start: 0}
    parents = {}
    while queue:
        total, node = heapq.heappop(queue)
        if total > distances[node]:
            continue
        if node == end:
            path = [end]
            while path[-1] != start:
                path.append(parents[path[-1]])
            return list(reversed(path)), total
        for other, cost in adj[node]:
            new_total = total + cost
            if new_total < distances.get(other, float("inf")):
                distances[other] = new_total
                parents[other] = node
                heapq.heappush(queue, (new_total, other))
    return [], float("inf")


def base_distance(start, end=DESTINATION):
    # Old routing announcements intentionally ignore later outages and policies.
    world = World(0, "", "", "", "global")
    return shortest_path(world, start, end)[1]



# A small ring with a cheap branch to F and a longer backup path. This is a
# different physical topology, not pre-computed neighbor routing knowledge.
LAB_EDGES = (("A", "B", 1), ("B", "C", 1), ("C", "F", 1),
             ("A", "D", 2), ("D", "E", 2), ("E", "G", 2), ("G", "F", 4))


def _world_for(chapter: int, rng: random.Random, cycle: int = 0) -> World:
    seed = rng.randrange(2**31)
    if chapter == 0:
        return World(0, "全局拓扑", "网络刚刚上线", "地图完整可见。找出 A 到 F 总代价最低的路线。成功后，网络将切换到分布式试验网。", "global", seed=seed)
    common = dict(protocol="dv", seed=seed, edges=LAB_EDGES, cycle=cycle)
    if chapter == 1:
        return World(1, "局部消息", "调度权移交 · 路由器开始交换消息",
                     "网络切换到环形试验网。每台路由器从自己的邻居开始学习：update 阶段更新表并通告，forward 阶段选择下一跳。先观察 24 个时隙内的收敛。", "local", pre_ticks=24, **common)
    if chapter == 2:
        return World(2, "故障传播", "C—F 断开 · 坏消息还在路上",
                     "保留上一轮路由表和在途消息。C 已发现故障，B 仍可能声称可以到 F。观察 C↔B 环路、距离增长与 TTL 耗尽；修改消息更新规则后重试。", "local",
                     failed=(("C", "F"),), delay_min=3, delay_max=3, **common)
    if chapter == 3:
        return World(3, "分区恢复", "F 暂时失联 · 消息延迟开始变化",
                     "C—F 和 G—F 同时断开；18 个时隙后 G—F 修复。旧通告可能比新通告晚到。观察不可达的传播、计数到 16，再验证恢复。", "local",
                     failed=(("C", "F"), ("G", "F")), delay_min=1, delay_max=6,
                     changes=({"after": 18, "a": "G", "b": "F", "up": True},), **common)
    if chapter == 4:
        return World(4, "路由策略", "物理链路恢复 · C 停止承载中转流量",
                     "链路都恢复了，但 C 成为禁行区域。只更新一个数据包的下一跳不够：策略必须进入每台路由器的候选路径与通告。", "local", blocked=("C",), delay_max=4, **common)
    if chapter == 5:
        return World(5, "错误通告", "B 声称到 F 的距离为 0",
                     "B 发出未通过来源校验的虚假距离向量，并丢弃收到的数据包。检查消息来源，别把低距离等同于可信路由。认证也不能证明内容一定正确。", "local", spoofed=("B",), delay_max=4, **common)
    # Subsequent incidents change the physical and policy premises, never filter
    # for a particular greedy answer. A valid path below infinity is enough.
    for _ in range(100):
        failed = tuple(rng.sample([("C", "F"), ("G", "F"), ("B", "C"), ("D", "E")], rng.choice([0, 1, 2])))
        blocked = (rng.choice(["C", "E"]),) if rng.random() < .4 else ()
        spoofed = (rng.choice(["B", "G"]),) if rng.random() < .4 else ()
        w = World(chapter, "持续演化", "网络再次变化", "", "local", failed=failed,
                  blocked=blocked, spoofed=spoofed, delay_max=rng.choice([2, 4, 6]), **common)
        path, cost = shortest_path(w)
        if path and cost < 16:
            w.headline = "网络变化 · " + ("、".join("—".join(e) + " 断开" for e in failed) or "链路恢复")
            w.brief = (f"禁行：{', '.join(blocked) or '无'}；错误通告源：{', '.join(spoofed) or '无'}；"
                       f"消息延迟 1～{w.delay_max} 时隙。旧路由状态继续保留，请验证收敛后的转发。")
            return w
    return World(chapter, "恢复", "网络恢复", "线路与策略恢复，旧表仍需重新收敛。", "local", **common)


def ctx_for(world: World, current: str = SOURCE, visited: list[str] | None = None, checkpoint=None) -> dict:
    if world.protocol == 'service':
        from service_incident import INCIDENTS, observe, windows
        incident = INCIDENTS[world.title]
        return observe(0, next(windows(world.seed, incident)), 0, [], incident)
    if world.protocol == 'carrier':
        from carriers import market
        return dict(mode='carrier', **{'from': SOURCE, 'to': DESTINATION},
                    **market(world.carrier_event, world.amendments))
    if world.mode == "global":
        return {"mode": "global", "from": SOURCE, "to": DESTINATION, "graph": world.graph()}
    if world.protocol == "dv":
        from distance_vector import DistanceVectorNetwork
        return DistanceVectorNetwork.for_world(world, checkpoint).context(current)
    visited = visited or []
    options = []
    for a, b, cost in BASE_EDGES:
        if a == current or b == current:
            other = b if a == current else a
            estimate = base_distance(other)
            if other in world.spoofed:
                estimate = -30  # deliberately misleading report
            options.append({
                "to": other, "cost": cost, "estimate": estimate,
                "up": edge_key(a, b) not in {edge_key(*e) for e in world.failed},
                "allowed": other not in world.blocked,
                "authenticated": other not in world.spoofed,
            })
    return {
        "mode": "local", "current": current, "destination": DESTINATION,
        "neighbors": options, "visited": list(visited),
    }


def _v02_reference_code(chapter: int) -> str:
    if chapter == 0:
        return '''def solve(ctx):
    # 全局视野：经典 Dijkstra 最短路径。
    graph = ctx["graph"]
    nodes = {ctx["from"], ctx["to"]}
    for edge in graph:
        nodes.update((edge["a"], edge["b"]))
    dist = {n: float("inf") for n in nodes}
    prev = {}
    remaining = set(nodes)
    dist[ctx["from"]] = 0
    while remaining:
        u = min(remaining, key=lambda n: dist[n])
        if dist[u] == float("inf"):
            break
        remaining.remove(u)
        for edge in graph:
            v = edge["b"] if edge["a"] == u else (edge["a"] if edge["b"] == u else None)
            if v is None or not edge["up"]:
                continue
            if dist[u] + edge["cost"] < dist[v]:
                dist[v] = dist[u] + edge["cost"]
                prev[v] = u
    result = [ctx["to"]]
    while result[0] != ctx["from"]:
        if result[0] not in prev:
            return []
        result.insert(0, prev[result[0]])
    return result
'''
    gates = ['n["up"]', 'n["allowed"]', 'n["authenticated"]']
    filters = ['n["to"] not in ctx["visited"]']
    if chapter >= 2: filters.insert(0, gates[0])
    if chapter >= 3: filters.insert(1, gates[1])
    if chapter >= 4: filters.insert(2, gates[2])
    if chapter >= 5: filters = gates + ['n["to"] not in ctx["visited"]']
    condition = ' and '.join(filters)
    return f'''def solve(ctx):
    # 局部视野：当前节点只知道邻居及其通告。
    choices = [n for n in ctx["neighbors"]
               if {condition}]
    if not choices:
        return None
    best = min(choices, key=lambda n: n["cost"] + n["estimate"])
    return best["to"]
'''


def reference_code(chapter: int) -> str:
    if chapter == 0:
        return _v02_reference_code(0)
    from pathlib import Path
    code = (Path(__file__).resolve().parent / "examples" / "distance_vector.py").read_text(encoding="utf-8")
    flags = {"USE_POISON": chapter >= 2, "CHECK_ORDER": chapter >= 3,
             "CHECK_POLICY": chapter >= 4, "CHECK_AUTH": chapter >= 5,
             "WAIT_FOR_STABILITY": chapter >= 2}
    for name, value in flags.items():
        code = code.replace(name + " = True", name + " = " + str(value), 1)
    return code


def validate_global(world: World, route: list) -> tuple[bool, str, list, int]:
    if not isinstance(route, list) or len(route) < 2:
        return False, "全局模式要返回节点列表，例如 ['A','B','C','E','F']。", [], 0
    if route[0] != SOURCE or route[-1] != DESTINATION:
        return False, "路线必须从 A 出发并到达 F。", [], 0
    if not all(isinstance(n, str) and n in POSITIONS for n in route):
        return False, "路线中的每一项必须是有效的节点名字符串。", [], 0
    if len(set(route)) != len(route):
        return False, "路线中存在重复节点；请避免环路。", [], 0
    cost = 0
    for index, (a, b) in enumerate(zip(route, route[1:])):
        found = next((e[2] for e in (world.edges or BASE_EDGES) if edge_key(e[0], e[1]) == edge_key(a, b)), None)
        if found is None:
            return False, f"{a} 与 {b} 没有直接链路。", route[:index + 1], cost
        if not world.can_use(a, b):
            return False, f"线路 {a}—{b} 不可用或违反策略。", route[:index + 1], cost
        cost += found
    _, optimum = shortest_path(world)
    if cost > optimum:
        return False, f"找到了能走的路线（成本 {cost}），但还有更便宜的路线。试着优化。", route, cost
    return True, f"最低成本 {cost} · 你找到了最优路径。", route, cost


def validate_local_hop(world: World, current: str, chosen, visited: list[str]):
    if not isinstance(chosen, str):
        return False, "局部模式要返回下一跳节点名字符串，例如 'B'。", 0
    options = {n["to"]: n for n in ctx_for(world, current, visited)["neighbors"]}
    if chosen not in options:
        return False, f"{chosen} 不是 {current} 的直接邻居。你现在没有全局视野。", 0
    neighbor = options[chosen]
    if not neighbor["up"]:
        return False, f"线路 {current}—{chosen} 已断开。", 0
    if not neighbor["allowed"]:
        return False, f"策略禁止经过 {chosen}。", 0
    if not neighbor["authenticated"]:
        return False, f"{chosen} 的通告未通过来源认证（教学简化场景）。", 0
    if chosen in visited or chosen == current:
        return False, f"数据包走回了 {chosen}，形成环路。", 0
    return True, "", neighbor["cost"]


def world_for(chapter, rng, cycle=0):
    from learning_help import STORIES
    world = _world_for(chapter, rng, cycle)
    if chapter < len(STORIES):
        world.brief = STORIES[chapter]
    return world


def session_world(chapter, rng, cycle=0, amendments=None):
    """Keep the original DV generator callable for legacy experiments."""
    from carriers import EVENTS, market, next_contract
    if chapter in (17, 18):
        from service_incident import S1, S2, SOURCES
        incident = S1 if chapter == 17 else S2
        return World(chapter, incident.id, incident.title, incident.brief, 'global', protocol='service',
                     seed=rng.randrange(2**31), edges=tuple((s, 'F', 1) for s in SOURCES))
    slot = chapter - 2 if chapter > 18 else chapter
    index = slot - 7
    if slot >= 19 and (slot - 19) % 3 == 0:
        index = len(EVENTS) - 1
        title, brief, amendments = next_contract(amendments, rng)
    elif 0 <= index < len(EVENTS):
        title, brief, _, _ = EVENTS[index]
        amendments = None
    else:
        return world_for(chapter, rng, cycle)
    links = market(index, amendments)['links']
    return World(chapter, '跨网运营', title, brief, 'global', protocol='carrier',
                 seed=rng.randrange(2**31), carrier_event=index, amendments=amendments,
                 edges=tuple((e['a'], e['b'], e['cost']) for e in links),
                 failed=tuple((e['a'], e['b']) for e in links if not e['up']))


def reference_for(world):
    if world.protocol == 'service':
        return 'def solve(ctx):\n    # 查看 sources 的统计，再填写每窗配额\n    return {}\n'
    if world.protocol == 'carrier':
        from pathlib import Path
        return (Path(__file__).parent / 'examples' / 'carrier_route.py').read_text(encoding='utf-8')
    return reference_code(world.chapter)
