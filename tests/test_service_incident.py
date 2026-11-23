import sys
import unittest
from dataclasses import asdict
from pathlib import Path
from random import Random
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import session_world
from runner import run_isolated, read_result
from service_incident import S1, S2, evaluate_service, simulate


class ServiceTests(unittest.TestCase):
    def test_activity_retries_and_policy_side_effects(self):
        old = lambda c: {'repeat_limits': dict.fromkeys(c['sources'], 2)}
        self.assertTrue(evaluate_service(42, old)['ok'])
        strict = evaluate_service(42, old, S2)
        self.assertFalse(strict['ok'])
        self.assertGreater(strict['after']['false_positive'], .10)
        def adjusted(ctx):
            return {'repeat_limits': {s: 1 for s,v in ctx['sources'].items()
                                      if v['repeats'] > 8 and v['sessions'] <= 4}}
        result = evaluate_service(42, adjusted, S2)
        self.assertTrue(result['ok'])
        self.assertLess(result['after']['false_positive'], strict['after']['false_positive'])
        self.assertLessEqual(result['after']['false_negative'], .30)
        self.assertTrue(result['frames'][5]['observation']['history'][-1]['sources'])
        for f in result['frames']:
            self.assertEqual(sum(f['backlog'].values()), f['service']['queue'])
            for row in f['observation']['sources'].values():
                self.assertLessEqual(row['sessions'], row['requests'])

    def test_overload_and_conservation(self):
        frames, _ = simulate(42, lambda ctx: {})
        backlog = 0
        for frame in frames:
            m = frame['service']
            self.assertEqual(m['offered'], m['filtered'] + m['received'] + m['dropped'])
            self.assertEqual(backlog + m['received'], m['queue'] + m['processed'])
            backlog = m['queue']
        self.assertFalse(any(f['service']['queue'] for f in frames[:S1.onset]))
        self.assertGreater(frames[-1]['service']['dropped'], 0)
        self.assertEqual(simulate(42, lambda ctx: {})[0], frames)

    def test_availability_and_distinct_valid_policies(self):
        def policy(quota):
            return lambda c: {'repeat_limits': {s:quota for s in c['sources'] if c['sources'][s]['repeats'] > 8}}
        strict, moderate = (evaluate_service(42, policy(n)) for n in (1, 3))
        self.assertTrue(strict['ok'] and moderate['ok'])
        self.assertLess(strict['after']['unwanted'], moderate['after']['unwanted'])
        self.assertFalse(evaluate_service(42, lambda c: {})['ok'])
        blocked = evaluate_service(42, lambda c: {'limits':dict.fromkeys(c['sources'], 0)})
        self.assertFalse(blocked['ok'])
        self.assertEqual(blocked['after']['availability'], 0)

    def test_observations_are_copies_and_limits_validated(self):
        def mutate(ctx):
            ctx['sources'].clear()
            ctx['history'].clear()
            return {}
        self.assertEqual(simulate(0, mutate), simulate(0, lambda c: {}))
        for invalid in ({'win': True}, {'limits': {'F':0}}, {'limits':{'B':False}}, []):
            with self.assertRaises(ValueError):
                simulate(0, lambda c: invalid)

    def test_real_child_and_backend_refusal(self):
        payload = dict(world=asdict(session_world(17, Random(7))),
                       code="def solve(ctx): return {'repeat_limits': dict.fromkeys(ctx['sources'], 2)}")
        self.assertTrue(run_isolated(payload)['ok'])
        with patch('runner.OUTPUT_LIMIT', 64):
            self.assertIn('输出超过', run_isolated(payload)['message'])
        self.assertTrue(run_isolated(payload)['ok'])
        with patch('runner.local_exchange', side_effect=AssertionError('fallback')):
            self.assertFalse(run_isolated(payload, backend='isolated')['ok'])
            self.assertFalse(run_isolated(dict(code='a'*(2**21)))['ok'])
        with self.assertRaises(ValueError):
            read_result(b'{"ok":1}')
