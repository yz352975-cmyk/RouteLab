# 可选参考实现；事件推进不会自动载入或更改玩家代码。
# update: 返回 table + 按邻居区分的 advertise；forward: 返回邻居名或 None。
USE_POISON = True
SPLIT_HORIZON = False
SPLIT_HORIZON = False
CHECK_ORDER = True
CHECK_POLICY = True
CHECK_AUTH = True
WAIT_FOR_STABILITY = True


def solve(ctx):
    me, inf = ctx['current'], ctx['infinity']
    if ctx['phase'] == 'forward':
        # None 在游戏里表示暂缓注入/转发，控制面仍继续交换消息。
        # 这是教学用观察窗口，不是通用网络收敛证明。
        if WAIT_FOR_STABILITY:
            if ctx['elapsed'] < 48 + 4 * ctx['max_delay']:
                return None
            if ctx['stable_for'] < 2 * ctx['max_delay'] + ctx['period']:
                return None
        route = ctx['table'].get(ctx['destination'], {})
        return route.get('next_hop') if route.get('metric', inf) < inf else None

    state = ctx['state']  # 每台路由器自己的显式状态，可随网络事件延续。
    vectors = state.setdefault('vectors', {})
    neighbors = {n['to']: n for n in ctx['neighbors']}
    usable = {name: n for name, n in neighbors.items()
              if n['up'] and (not CHECK_POLICY or n['allowed'])
              and (not CHECK_AUTH or n['authenticated'])}
    for name in list(vectors):
        if name not in usable:
            del vectors[name]
    for msg in ctx['inbox']:
        name = msg['sender']
        if name not in usable or (CHECK_AUTH and not msg['authenticated']):
            continue
        old = vectors.get(name)
        # 模拟器提供的序号是教学扩展，不是基础 RIP 的字段。
        if CHECK_ORDER and old and msg['seq'] <= old['seq']:
            continue
        vectors[name] = dict(vector=msg['vector'], seq=msg['seq'], received_at=ctx['time'])
    for name in list(vectors):
        if ctx['time'] - vectors[name]['received_at'] > ctx['route_timeout']:
            del vectors[name]

    destinations = set(ctx['table']) | {me} | set(usable)
    for cached in vectors.values():
        destinations.update(cached['vector'])
    # 每次重新计算，而非只接受更小的数值；坏消息也必须使距离增加。
    table = {}
    for dest in sorted(destinations):
        best, hop = inf, None
        for name, n in sorted(usable.items()):
            advertised = vectors.get(name, {}).get('vector', {}).get(dest, inf)
            candidate = min(inf, n['cost'] + advertised)
            if name == dest:
                candidate = n['cost']
            if candidate < best:
                best, hop = candidate, name
        table[dest] = dict(metric=best, next_hop=hop)
    table[me] = dict(metric=0, next_hop=me)

    advertise = {}
    if table != ctx['table'] or ctx['elapsed'] == 1 or ctx['time'] % ctx['period'] == 0:
        for name in usable:
            vector = {}
            for dest, route in table.items():
                value = route['metric']
                if USE_POISON and route['next_hop'] == name and dest != me:
                    value = inf  # 向学到路由的邻居反向通告“不可达”。
                elif SPLIT_HORIZON and route['next_hop'] == name and dest != me:
                    continue  # 水平分割：在给这个邻居的向量中省略此目的地。
                elif SPLIT_HORIZON and route['next_hop'] == name and dest != me:
                    continue  # 水平分割：在给这个邻居的向量中省略此目的地。
                vector[dest] = value
            advertise[name] = vector
    return dict(table=table, advertise=advertise)
