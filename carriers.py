"""Fictional directed offers towards one data centre. Independent of DV."""
from copy import deepcopy
from itertools import pairwise

OPERATORS = {
    'A': dict(name='禾线 · 低成本', color='#90D674', goal='减少跨网支出'),
    'B': dict(name='蓝港 · 高质量', color='#68A6FF', goal='低延迟、低故障风险'),
    'C': dict(name='云渡 · 区域网', color='#E8AC63', goal='保持城市到数据中心的覆盖'),
}
OWNER = dict(A='C', B='C', G='C', C='A', D='B', E='B', F='B')

# All offers are directional. A peering exit serves only the receiving network.
def offer(a, b, cost, delay, risk, contract='internal', fee=0):
    return dict(a=a, b=b, cost=cost, delay=delay, risk=risk, contract=contract,
                fee=fee, up=True, origin='B', congestion=0)


BASE = [
    offer('A', 'B', 1, 1, 1), offer('B', 'C', 1, 2, 2, 'transit', 1),
    offer('C', 'F', 1, 2, 2, 'peering'), offer('A', 'D', 2, 1, 1, 'transit', 1),
    offer('D', 'E', 2, 1, 1), offer('E', 'F', 2, 1, 1),
    offer('B', 'G', 3, 2, 1), offer('G', 'F', 2, 2, 1, 'transit', 6),
    offer('D', 'F', 5, 6, 2),
]

# One incident per successful transmission. Earlier amendments remain in force.
EVENTS = (
    ('新城接入', '你在云渡负责新城 A。请把用户的包送到蓝港数据中心 F，比较线路费用和转接账单。', 'cost', {}),
    ('转接合同到期', '禾线与云渡只续签了对等协议。B→C 仍通车，但禾线只提供到自己网络的路由。', 'cost', {'BC':dict(contract='peering', fee=0)}),
    ('转接涨价', '蓝港在 A→D 出口提高转接费。云渡还有 G 出口，比较两张账单。', 'cost', {'AD':dict(fee=9)}),
    ('开通对等出口', '两家签订新协议，新建 B→E 专线，允许直接访问蓝港自己的数据中心。', 'cost', {'BE':offer('B','E',1,1,1,'peering')}),
    ('区域拥塞', '晚高峰让 E→F 多排队 12 毫秒。这次运送直播数据，请选合规且总延迟最低的出口。', 'delay', {'EF':dict(congestion=12)}),
    ('出口通告异常', 'G 出口收到一份自称来自禾线的 F 通告。客户要求核对目的地归属，再选择最快的合规路线。', 'delay', {'GF':dict(origin='A')}),
    ('廉价线路变慢', 'D→F 改走长途光缆，基础延迟增到 25 毫秒。比较继续直达和经过排队链路的时间。', 'delay', {'DF':dict(delay=25)}),
    ('核心线路中断', '蓝港 E→F 失去光信号。云渡要在仍通车的线路中恢复送达，并选择最低时延。', 'delay', {'EF':dict(up=False)}),
    ('临时借线', '云渡借到 G→F 应急专线，蓝港重新发布正确通告。医疗通知优先选累计风险分最低的路线。', 'risk', {'GF':dict(origin='B',risk=0)}),
    ('备用出口检修', '云渡 G 站停机检修，入站和出站都不可用。切到仍能送达、风险分最低的备用出口。', 'risk', {'BG':dict(up=False),'GF':dict(up=False)}),
)


def market(index, amendments=None):
    links = {e['a'] + e['b']: dict(e) for e in BASE}
    for _, _, _, changes in EVENTS[:index + 1]:
        for key, fields in changes.items():
            links.setdefault(key, {}).update(fields)
    for key, fields in (amendments or {}).items():
        links[key].update(fields)
    return dict(owners=dict(OWNER), operators=deepcopy(OPERATORS), links=list(links.values()),
                objective='cost' if amendments else EVENTS[index][2], destination_owner=OWNER['F'])


def next_contract(amendments, rng):
    """Apply one seeded change to the live market, retaining previous amendments."""
    last = len(EVENTS) - 1
    current = market(last, amendments)
    current['objective'] = 'cost'
    before = optimum(current)
    links = {e['a'] + e['b']: e for e in current['links']}
    transit = links['BC']['contract'] != 'transit'
    fee = 1 if links['AD']['fee'] > 1 else 9
    up = not links['EF']['up']
    options = [
        ('转接重新签约' if transit else '转接不再续签',
         'B→C 恢复第三方转接。' if transit else 'B→C 仅保留对等互联。',
         {'BC': dict(contract='transit' if transit else 'peering', fee=2 if transit else 0)}),
        ('出口调价', f'A→D 的新合同将转接单价定为 {fee}。', {'AD': dict(fee=fee)}),
        ('核心线路恢复' if up else '核心线路抢修', 'E→F ' + ('恢复通车。' if up else '暂时停运。'),
         {'EF': dict(up=up)}),
    ]
    rng.shuffle(options)
    for title, brief, changes in options:
        updated = deepcopy(amendments or {})
        for key, fields in changes.items():
            updated.setdefault(key, {}).update(fields)
        score = optimum(market(last, updated))
        if score != before and score < float('inf'):
            return title, brief + '请重新计算最低合规费用。', updated
    raise ValueError('没有可达且会改变费用的合同事件')


def denial(link, data):
    if not link['up']:
        return '线路或站点已离线'
    if link['origin'] != data['destination_owner']:
        return '目的地通告的来源与登记运营商不符'
    if link['contract'] == 'peering' and data['owners'][link['b']] != data['destination_owner']:
        return '对等协议只出口本运营商目的地，未购买第三方转接'
    return ''


def weight(link, objective):
    if objective == 'cost':
        return link['cost'] + link['fee']
    if objective == 'delay':
        return link['delay'] + link['congestion']
    return link['risk']


def optimum(data):
    # Independent small-map oracle: enumerate simple legal paths to F.
    def visit(node, seen):
        if node == 'F':
            return 0
        return min((weight(e, data['objective']) + visit(e['b'], seen | {e['b']})
                    for e in data['links'] if e['a'] == node and e['b'] not in seen
                    and not denial(e, data)), default=float('inf'))
    return visit('A', {'A'})


def validate(data, route):
    if not isinstance(route, list) or not route or route[0] != 'A':
        return False, '跨网任务要返回从 A 出发的站名列表。', [], 0
    path, total = ['A'], 0
    for a, b in pairwise(route):
        link = next((e for e in data['links'] if (e['a'], e['b']) == (a, b)), None)
        reason = denial(link, data) if link else '没有这个方向的出口'
        if reason or b in path:
            return False, f'包停在 {a}，{a}→{b}：{reason or "路线重复经过同一站"}。', path, total
        path.append(b)
        total += weight(link, data['objective'])
    if path[-1] != 'F':
        return False, f'包停在 {path[-1]}，尚未到达数据中心 F。', path, total
    best = optimum(data)
    unit = {'cost':'费用点','delay':'毫秒','risk':'风险分'}[data['objective']]
    if total > best:
        return False, f'路线合规，但总计 {total} {unit}；有路线只需 {best} {unit}。', path, total
    return True, f'合规送达，最优总计 {total} {unit}。', path, total
