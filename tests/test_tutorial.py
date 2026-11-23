import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from tutorial import initial_code, extend_code, check, MARKER

class TutorialTests(unittest.TestCase):
    def test_incremental_workshop(self):
        code = initial_code().replace('    # TODO：遍历 ctx["graph"]，把通车道路的两个方向加入 adj', '''    for e in ctx['graph']:
        if e['up']:
            adj.setdefault(e['a'], []).append((e['b'], e['cost']))
            adj.setdefault(e['b'], []).append((e['a'], e['cost']))''')
        self.assertTrue(check(code,0)['ok'])
        code=extend_code(code,1).replace('    # TODO：创建 dist、prev、remaining；起点费用设为 0', '''    dist = {n: float('inf') for n in adj}
    dist[ctx['from']] = 0
    prev = {}
    remaining = set(adj)''')
        self.assertTrue(check(code,1)['ok'])
        code=extend_code(code,2).replace('    # TODO：while remaining 循环，选择 u，比较邻居费用并更新 dist / prev', '''    while remaining:
        u = min(remaining, key=lambda n: dist[n])
        if dist[u] == float('inf'): break
        remaining.remove(u)
        for v, cost in adj[u]:
            if dist[u]+cost < dist[v]:
                dist[v] = dist[u]+cost
                prev[v] = u''')
        self.assertTrue(check(code,2)['ok'])
        code=extend_code(code,3)+'''    route = [ctx['to']]
    while route[0] != ctx['from']:
        if route[0] not in prev: return []
        route.insert(0, prev[route[0]])
    return route
'''
        self.assertTrue(check(code,3)['ok'])

    def test_empty_and_hardcoded_solutions_fail(self):
        self.assertFalse(check(initial_code(),0)['ok'])
        self.assertFalse(check("def solve(ctx): return ['A','B','F']",3)['ok'])

    def test_extension_preserves_player_work(self):
        code=initial_code().replace(MARKER, '    # 我的笔记\n'+MARKER)
        self.assertIn('# 我的笔记',extend_code(code,1))
        self.assertIn('    # 下一步提醒', extend_code(code + '    # 下一步提醒', 1))
        with self.assertRaises(ValueError):
            extend_code(code.replace('return adj', 'return dict(adj)'), 1)
        with self.assertRaises(ValueError): extend_code('def solve(ctx): pass',1)
