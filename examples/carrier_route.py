def solve(ctx):
    import heapq
    queue = [(0, [ctx['from']])]
    settled = set()
    while queue:
        score, path = heapq.heappop(queue)
        node = path[-1]
        if node == ctx['to']:
            return path
        if node in settled:
            continue
        settled.add(node)
        for link in ctx['links']:
            if link['a'] != node or not link['up']:
                continue
            target = link['b']
            owner = ctx['destination_owner']
            if link['origin'] != owner:
                continue
            if link['contract'] == 'peering' and ctx['owners'][target] != owner:
                continue
            if ctx['objective'] == 'cost':
                metric = link['cost'] + link['fee']
            elif ctx['objective'] == 'delay':
                metric = link['delay'] + link['congestion']
            else:
                metric = link['risk']
            heapq.heappush(queue, (score + metric, path + [target]))
    return []
