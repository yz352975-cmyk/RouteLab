"""Incremental Dijkstra workshop; checks behavior on several small maps."""
from copy import deepcopy
import re

LESSONS = [
('把地图变成邻居表', '''先做一件小事：整理每个站能直接去哪里。
ctx["graph"] 中每条道路有 a、b、cost、up。道路双向，只有 up 为 True 才能走。
请建立 adj 字典，例如 {"A": [("B", 2)], "B": [("A", 2)]}。
Python 小提示：adj.setdefault(a, []).append((b, cost)) 会先准备列表，再加入邻居。另一方向也要加入。
本步只检查邻居表，不要求送达包裹。''', '''def solve(ctx):
    adj = {ctx["from"]: [], ctx["to"]: []}
    # TODO：遍历 ctx["graph"]，把通车道路的两个方向加入 adj
''', '    return adj\n'),
('准备费用账本', '''现在邻居表有了。我们要记录“从起点到每个站，目前知道的最低费用”。
建立 dist：每站初值 float("inf")，起点设为 0；建立空字典 prev，稍后记录上一站；建立 remaining = set(adj)，表示尚未确认的站。
为什么其他站不是 0？因为还不知道怎么到那里，不能误当作免费。
Python 小提示：{n: float("inf") for n in adj} 可以建立字典。''', '''    # TODO：创建 dist、prev、remaining；起点费用设为 0
''', '    return {"adj": adj, "dist": dist, "prev": prev, "remaining": sorted(remaining)}\n'),
('反复找最便宜的站', '''这是 Dijkstra 的核心。每轮从 remaining 中选 dist 最小的站 u。
如果它的距离仍是无穷大，说明剩下的站到不了，break。否则移除 u，再检查 adj[u] 里的每个邻居 v 和费用 cost。
计算 candidate = dist[u] + cost；如果比 dist[v] 更小，就更新 dist[v]，并记 prev[v] = u。
Python 小提示：min(remaining, key=lambda n: dist[n])；while remaining:；for v, cost in adj[u]:。
为什么选最便宜的？这里道路费用都为正，再绕路不会让已经最便宜的站更便宜。''', '''    # TODO：while remaining 循环，选择 u，比较邻居费用并更新 dist / prev
''', '    return {"dist": dist, "prev": prev}\n'),
('沿脚印拼回路线', '''费用算好了，但包裹需要一串站名。prev 记录每个站是从哪里过来的。
从终点开始建立 route，反复查 prev，把上一站接到路线前面，直到起点。
如果查不到上一站，说明终点不可达，返回 []。
Python 小提示：route = [ctx["to"]]；route.insert(0, prev[route[0]])。
最终返回 route。通过后会播放你的路线，并自动发生下一次网络事件。''', '''    # TODO：从终点沿 prev 回到起点，返回 route；不可达时返回 []
''', '')]
MARKER = '    # --- 新手引导临时返回 ---\n'

# Short tasks stay beside the editor. The longer lesson is available on demand.
TASKS = (
    '写一份直达站清单。若 A 和 B 之间的路费是 2 元，两站的清单都要记上对方和 2 元。',
    '准备一本费用账本。包裹还在起点，已花 0 元；其他站先记为“还不知道”。',
    '试着省钱。直达花 9 元，经过邻站只花 2 + 3 元，就改记 5 元，并记下从哪一站来。',
    '从 F 看账本里的“上一站”，一路倒推到 A。把站名排成出发顺序；到不了就返回空列表。',
)

WALKTHROUGH = (
    (
        '读地图：ctx 是游戏交给函数的字典，相当于带标签的资料袋。ctx["graph"] 拿出道路清单；每次取一条路，可以叫它 edge。',
        '逐条看：输入 fo，按 Tab 补出循环。for 表示“对每条路都做一次”。冒号后换行并多缩进 4 格，写循环里要做的事。',
        '看开关：edge["up"] 是这条路的通车标记。用 if 判断，只在通车时读出 edge["a"]、edge["b"] 和 edge["cost"]。',
        '记两个方向：假设 A—B 花 2 元，A 的列表加 ("B", 2)，B 的列表加 ("A", 2)。setdefault 可以给新站准备空列表，append 向列表末尾加一项。',
    ),
    (
        '建账本：字典用站名查费用。先写 dist = {}。遍历 adj 的站名，给每站记 float("inf")，表示暂时没发现走法。',
        '记起点：ctx["from"] 给出发站的名字。出发前一分钱也没花，单独把这个站的 dist 改为 0。',
        '备两份记录：prev = {} 用来记来路；set(adj) 收集所有站名，把它交给 remaining，稍后逐个确认。想一想：此时 F 的费用应该是多少？',
    ),
    (
        '挑一站：只要 remaining 还有站就继续。用 min 比较每站的 dist，取最便宜的站 u。若最小费用也是无穷大，就用 break 停下；否则用 remove 移走 u。',
        '试一条路：从 adj[u] 逐个取邻站 v 和路费 cost。如果已花 2 元到 u，再花 3 元到 v，这条候选走法共花 dist[u] + cost，也就是 5 元。',
        '改两笔：若 v 原来记了 9 元，现在的 5 元更低，就更新 dist[v]，同时把 prev[v] 记为 u。若原本只花 4 元，两笔都保留原样。',
    ),
    (
        '从收件站往回看：先把 ctx["to"] 放进列表 route。route[0] 表示当前排在最前面的站。',
        '接上一站：假设 prev["F"] 是 B，就把 B 插到 F 前面。用 insert(0, 上一站)；反复查看新的 route[0]，直到它等于起点。',
        '检查走不通的情况：还没回到起点，却查不到上一站，说明无法送达，返回 []。回到起点时，列表已经按发送顺序排好，返回 route。',
    ),
)

# Each entry is one local expression or loop header, never a whole solution.
COMPLETIONS = (
    ('for edge in ctx["graph"]:', 'ctx["graph"]', 'edge["up"]', 'edge["cost"]',
     'edge["a"]', 'edge["b"]', 'setdefault', 'append'),
    ('for node in adj:', 'float("inf")', 'ctx["from"]', 'remaining', 'dist', 'prev', 'set(adj)'),
    ('while remaining:', 'min(remaining, key=lambda n: dist[n])', 'remaining', 'remove',
     'for v, cost in adj[u]:', 'candidate', 'dist', 'prev', 'break'),
    ('ctx["to"]', 'ctx["from"]', 'while route[0] != ctx["from"]:', 'insert', 'route', 'prev', 'return'),
)

def completion(line, step):
    """Return the untyped suffix of the most specific matching expression."""
    if '#' in line:
        return None
    for match in re.finditer(r'\b[A-Za-z_]\w*', line):
        prefix = line[match.start():]
        if len(prefix) < 2:
            continue
        for phrase in COMPLETIONS[step]:
            if phrase == prefix:
                return None
            if phrase.startswith(prefix):
                return phrase[len(prefix):], phrase
    return None

def initial_code():
    return LESSONS[0][2] + '    \n' + MARKER + LESSONS[0][3]

def extend_code(code, step):
    if MARKER not in code:
        raise ValueError('找不到“新手引导临时返回”标记。请保留这行；它下面只是本步的检查出口。你的代码未被替换。')
    body, tail = code.split(MARKER, 1)
    temporary_return = LESSONS[step - 1][3].rstrip('\n')
    line, _, notes = tail.partition('\n')
    if line.rstrip() != temporary_return:
        raise ValueError('临时返回行已改动。请把自己的代码放在标记上方，并还原标记下的临时返回行后继续。')
    if notes and not notes.endswith('\n'):
        notes += '\n'
    return body + LESSONS[step][2] + '    \n' + (MARKER + LESSONS[step][3] if step < 3 else '') + notes

def check(code, step):
    from runner import _program
    from engine import World, validate_global, shortest_path
    if step not in range(4):
        raise ValueError('无效引导步骤')
    graphs = [
        [('A','B',2,True),('B','F',3,True),('A','F',9,True)],
        [('A','F',8,False),('F','B',1,True),('B','A',2,True)],
        [('A','B',1,True),('C','F',1,True)],
    ]
    for index, edges in enumerate(graphs):
        ctx = {'mode':'global','from':'A','to':'F','graph':[dict(a=a,b=b,cost=c,up=up) for a,b,c,up in edges]}
        adj = {'A':[], 'F':[]}
        for a,b,c,up in edges:
            if up:
                adj.setdefault(a,[]).append((b,c));adj.setdefault(b,[]).append((a,c))
        result = _program(code)(deepcopy(ctx))
        label = ['普通地图','道路反向记录与断路','终点无法到达'][index]
        normalize = lambda x: {n: sorted(tuple(v) for v in ns) for n,ns in x.items()}
        if step == 0:
            advice = '返回按站名索引的字典，每个邻居写成（站名，费用）。'
            try:
                actual = normalize(result) if isinstance(result, dict) else {}
            except (TypeError, ValueError):
                actual = {}
            ok = actual == normalize(adj)
            for station, neighbors in adj.items():
                if station not in actual:
                    advice = f'邻居表缺少站点 {station}。即使暂时没有出口，也要给起点和终点留出空列表。'
                    break
                missing = next((pair for pair in neighbors if pair not in actual[station]), None)
                if missing:
                    advice = f'从 {station} 出发应能花 {missing[1]} 到 {missing[0]}。看看这条通车道路的两个方向是否都登记了。'
                    break
        elif step == 1:
            expected = {n: 0 if n == 'A' else float('inf') for n in adj}
            ok = isinstance(result,dict) and result.get('dist') == expected and result.get('prev') == {} and set(result.get('remaining',[])) == set(adj) and isinstance(result.get('adj'), dict) and normalize(result['adj']) == normalize(adj)
            advice = '检查起点为 0，其他站为无穷大，prev 为空，remaining 包含所有站。'
        else:
            w = World(0,'','','','global',edges=tuple((a,b,c) for a,b,c,up in edges),failed=tuple((a,b) for a,b,c,up in edges if not up))
            if step == 2:
                expected = {n:shortest_path(w,'A',n)[1] for n in adj}
                ok = isinstance(result,dict) and result.get('dist') == expected
                prev = result.get('prev',{}) if isinstance(result,dict) else {}
                for n,d in expected.items():
                    if n != 'A' and d != float('inf'):
                        parent=prev.get(n)
                        ok = ok and any(v == n and expected.get(parent,float('inf'))+c == d for v,c in adj.get(parent,[]))
                advice = '检查是否反复处理所有可达站、允许更低费用覆盖旧费用，并更新 prev。'
            else:
                path,_ = shortest_path(w)
                ok = result == [] if not path else validate_global(w,result)[0]
                advice = '检查路线的起终点、前驱顺序、最低费用，以及不可达时返回空列表。'
        if not ok:
            return dict(ok=False,message=f'练习地图：{label}。'+advice,route=[],cost=0,log=[])
    return dict(ok=True,message='本步通过：普通道路、断路/反向道路和不可达地图均验证成功。',route=[],cost=0,log=[])
