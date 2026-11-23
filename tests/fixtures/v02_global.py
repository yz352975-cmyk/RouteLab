def solve(ctx):
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
