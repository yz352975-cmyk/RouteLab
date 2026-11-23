"""Behavior tests: no GUI, no sockets, deterministic simulated time."""
import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from distance_vector import DistanceVectorNetwork, INFINITY, ProtocolError
from engine import World, LAB_EDGES, ctx_for, reference_code, shortest_path, validate_global, world_for
from runner import _program, evaluate, run_isolated


def controller(code=None, silent=False):
    code = code or reference_code(6)
    programs = {}
    def update(node, ctx):
        if node not in programs:
            programs[node] = _program(code)
        result = programs[node](ctx)
        if silent:
            result['advertise'] = {}
        return result
    return update


def advance(sim, update, ticks):
    for _ in range(ticks):
        sim.step(update)


class CompatibilityTests(unittest.TestCase):
    def test_original_global_program_still_runs(self):
        code = (Path(__file__).parent / 'fixtures/v02_global.py').read_text(encoding='utf-8')
        self.assertTrue(evaluate(code, world_for(0, random.Random(0)))['ok'])

    def test_original_local_api_remains_available_for_legacy_worlds(self):
        code = (Path(__file__).parent / 'fixtures/v02_local.py').read_text(encoding='utf-8')
        world = World(1, '', '', '', 'local')
        self.assertTrue(evaluate(code, world)['ok'])
        self.assertIn('visited', ctx_for(world))

    def test_global_validator_rejects_failed_link(self):
        world = world_for(0, random.Random(0))
        world.failed = (('E', 'F'),)
        self.assertFalse(validate_global(world, ['A', 'B', 'C', 'E', 'F'])[0])

    def test_malformed_route_does_not_crash_validator(self):
        world = world_for(0, random.Random(0))
        self.assertFalse(validate_global(world, ['A', {}, 'F'])[0])


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.sim = DistanceVectorNetwork([('A', 'B', 1)], nodes=['F'], delay=(1, 1))
        self.silent = controller(silent=True)

    def test_delay_and_equal_time_fifo_order(self):
        first = self.sim.send('B', 'A', {'F': 5}, delay=3, seq=7)
        second = self.sim.send('B', 'A', {'F': 6}, delay=3, seq=8)
        advance(self.sim, self.silent, 2)
        self.assertEqual(self.sim.inboxes['A'], [])
        self.sim.step(self.silent)
        self.assertEqual([m['id'] for m in self.sim.inboxes['A']], [first, second])
        self.assertEqual(self.sim.time, 3)

    def test_message_overtaking_is_visible_not_fixed_by_engine(self):
        self.sim.send('B', 'A', {'F': 1}, delay=5, seq=10)
        self.sim.send('B', 'A', {'F': 9}, delay=1, seq=20)
        update = controller(reference_code(6).replace('CHECK_ORDER = True', 'CHECK_ORDER = False'), silent=True)
        advance(self.sim, update, 1)
        self.assertEqual(self.sim.routers['A']['table']['F']['metric'], 10)
        advance(self.sim, update, 4)
        self.assertEqual(self.sim.routers['A']['table']['F']['metric'], 2)
        received = [e['seq'] for e in self.sim.events if e['kind'] == 'deliver']
        self.assertEqual(received, [20, 10])

    def test_player_sequence_rule_rejects_old_and_duplicate_messages(self):
        self.sim.send('B', 'A', {'F': 9}, delay=1, seq=20)
        self.sim.send('B', 'A', {'F': 1}, delay=3, seq=10)
        self.sim.send('B', 'A', {'F': 2}, delay=4, seq=20)
        advance(self.sim, self.silent, 5)
        self.assertEqual(self.sim.routers['A']['table']['F']['metric'], 10)
        self.assertEqual(self.sim.routers['A']['state']['vectors']['B']['seq'], 20)

    def test_inflight_message_dies_across_link_down_and_repair(self):
        self.sim.send('B', 'A', {'F': 1}, delay=4)
        self.sim.set_link('A', 'B', up=False)
        self.sim.set_link('A', 'B', up=True)
        advance(self.sim, self.silent, 4)
        self.assertEqual(self.sim.inboxes['A'], [])
        self.assertEqual(sum(e['kind'] == 'drop' for e in self.sim.events), 1)

    def test_timeout_expires_only_cached_remote_information(self):
        self.sim.send('B', 'A', {'F': 1}, delay=1)
        advance(self.sim, self.silent, 2)
        self.assertEqual(self.sim.routers['A']['table']['F']['metric'], 2)
        advance(self.sim, self.silent, 20)
        self.assertEqual(self.sim.routers['A']['table']['F']['metric'], INFINITY)
        self.assertEqual(self.sim.routers['A']['table']['B']['metric'], 1)

    def test_impossible_zero_delay_is_rejected(self):
        with self.assertRaises(ValueError):
            self.sim.send('B', 'A', {'F': 1}, delay=0)


class DistributedAlgorithmTests(unittest.TestCase):
    def test_observer_detects_real_fault_loop_before_probe(self):
        sim, update = self.line(poison=False)
        sim.set_link('B', 'F', up=False)
        sim.step(update)
        self.assertEqual(sim.routing_loops(), [['A', 'B', 'A']])
        self.assertEqual(sim.frames[-1]['routing_loops'], [['A', 'B', 'A']])
        self.assertFalse(any(e['kind'] == 'packet' for e in sim.events))
        before = sim.checkpoint()
        self.assertNotIn('routing_loops', sim.context('A'))
        self.assertEqual(sim.checkpoint(), before)
        advance(sim, update, 40)
        self.assertEqual(sim.routing_loops(), [])

    def test_loop_observer_deduplicates_and_ignores_down_links(self):
        sim = DistanceVectorNetwork([('A', 'B', 1), ('B', 'C', 1),
                                     ('C', 'A', 1), ('D', 'A', 1)], nodes=['F'])
        for node, hop in [('A', 'B'), ('B', 'C'), ('C', 'A'), ('D', 'A')]:
            sim.routers[node]['table']['F'] = dict(metric=3, next_hop=hop)
        self.assertEqual(sim.routing_loops(), [['A', 'B', 'C', 'A']])
        sim.set_link('B', 'C', up=False)
        self.assertEqual(sim.routing_loops(), [])

    def line(self, poison=True, delay=1):
        sim = DistanceVectorNetwork([('A', 'B', 1), ('B', 'F', 1)], delay=(delay, delay))
        code = reference_code(6).replace('USE_POISON = True', 'USE_POISON = ' + str(poison))
        update = controller(code)
        advance(sim, update, 20)
        return sim, update

    def test_local_view_contains_no_graph_or_oracle_distances(self):
        w = world_for(1, random.Random(0))
        with patch('engine.base_distance', side_effect=AssertionError('oracle leak')):
            ctx = ctx_for(w)
        self.assertNotIn('graph', ctx)
        self.assertNotIn('edges', ctx)
        self.assertEqual(ctx['table'], {'A': {'metric': 0, 'next_hop': 'A'}})
        self.assertEqual(ctx['inbox'], [])
        self.assertTrue(all(n['estimate'] == INFINITY for n in ctx['neighbors']))

    def test_learning_requires_actual_message_arrival(self):
        sim = DistanceVectorNetwork([('A', 'B', 1), ('B', 'F', 1)], delay=(2, 2))
        update = controller()
        advance(sim, update, 2)
        self.assertNotIn('F', sim.routers['A']['table'])
        sim.step(update)
        self.assertEqual(sim.routers['A']['table']['F'], {'metric': 2, 'next_hop': 'B'})
        self.assertTrue(sim.destination_convergence()['correct'])

    def test_context_cannot_mutate_other_tables(self):
        sim, _ = self.line()
        ctx = sim.context('A')
        ctx['table']['F']['metric'] = 0
        ctx['state'].clear()
        self.assertEqual(sim.routers['A']['table']['F']['metric'], 2)
        self.assertTrue(sim.routers['B']['state']['vectors'])

    def test_player_state_schema_is_not_assumed_by_engine(self):
        sim, _ = self.line()
        sim.routers['A']['state'] = {'vectors': ['a player-defined schema']}
        ctx = sim.context('A')
        self.assertEqual(ctx['state']['vectors'], ['a player-defined schema'])
        self.assertEqual(next(n for n in ctx['neighbors'] if n['to']=='B')['estimate'], 1)

    def test_bad_news_increases_distance_instead_of_minimum_only(self):
        sim, update = self.line(poison=False)
        sim.set_link('B', 'F', up=False)
        sim.step(update)
        self.assertEqual(sim.routers['B']['table']['F'], {'metric': 3, 'next_hop': 'A'})
        sim.step(update)
        self.assertEqual(sim.routers['A']['table']['F']['metric'], 4)

    def test_count_to_infinity_is_a_computed_sequence(self):
        sim, update = self.line(poison=False)
        sim.set_link('B', 'F', up=False)
        values = []
        for _ in range(18):
            sim.step(update)
            values.append(sim.routers['A']['table']['F']['metric'])
        self.assertEqual(values[:8], [2, 4, 4, 6, 6, 8, 8, 10])
        self.assertEqual(values[-1], 16)
        self.assertEqual(sim.routers['B']['table']['F']['metric'], 16)
        self.assertTrue(sim.destination_convergence()['correct'])

    def test_poison_reverse_removes_two_router_loop(self):
        sim, update = self.line(poison=True)
        sim.set_link('B', 'F', up=False)
        advance(sim, update, 2)
        self.assertEqual(sim.routers['A']['table']['F']['metric'], 16)
        self.assertEqual(sim.routers['B']['table']['F']['metric'], 16)
        reverse = [e for e in sim.events if e['kind'] == 'send' and e['sender'] == 'A' and e['receiver'] == 'B']
        self.assertTrue(any(e['vector'].get('F') == 16 for e in reverse))

    def test_poison_reverse_does_not_claim_to_prevent_all_longer_loops(self):
        sim = DistanceVectorNetwork([('A', 'B', 1), ('B', 'C', 1), ('C', 'A', 3), ('C', 'F', 1)], delay=(3, 3))
        update = controller()
        advance(sim, update, 40)
        sim.set_link('C', 'F', up=False)
        sim.step(update)
        self.assertEqual([sim.routers[n]['table']['F']['next_hop'] for n in 'ABC'], ['B', 'C', 'A'])

    def test_partition_then_repair_converges_from_existing_state(self):
        sim, update = self.line(poison=False)
        sim.set_link('B', 'F', up=False)
        advance(sim, update, 25)
        self.assertEqual(sim.routers['A']['table']['F']['metric'], 16)
        sim.set_link('B', 'F', up=True)
        advance(sim, update, 5)
        self.assertEqual(sim.routers['A']['table']['F']['metric'], 2)
        self.assertTrue(sim.destination_convergence()['correct'])

    def test_policy_changes_propagate_into_remote_tables(self):
        sim = DistanceVectorNetwork(LAB_EDGES, blocked=['C'], delay=(1, 2))
        advance(sim, controller(), 40)
        self.assertEqual(sim.routers['A']['table']['F'], {'metric': 10, 'next_hop': 'D'})
        self.assertTrue(sim.destination_convergence()['correct'])

    def test_false_announcement_uses_real_message_transport(self):
        sim = DistanceVectorNetwork(LAB_EDGES, spoofed=['B'], delay=(1, 2))
        advance(sim, controller(), 32)
        lies = [e for e in sim.events if e['kind'] == 'deliver' and e['sender'] == 'B']
        self.assertTrue(lies)
        self.assertTrue(all(e['vector']['F'] == 0 and not e['authenticated'] for e in lies))
        self.assertNotIn('B', sim.routers['A']['state']['vectors'])
        self.assertEqual(sim.routers['A']['table']['F']['next_hop'], 'D')

    def test_authenticated_source_can_still_lie(self):
        sim = DistanceVectorNetwork(LAB_EDGES, spoofed=['B'], authenticated_attack=True)
        advance(sim, controller(), 32)
        self.assertEqual(sim.routers['A']['table']['F'], {'metric': 1, 'next_hop': 'B'})
        self.assertFalse(sim.destination_convergence()['correct'])

    def test_invalid_metrics_get_explanatory_error(self):
        sim = DistanceVectorNetwork([('A', 'B', 1)])
        for value in [-1, float('nan'), float('inf'), True, 17]:
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                sim.step(lambda n, ctx: {'table': {'F': {'metric': value, 'next_hop': None}}})


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.warm = evaluate(reference_code(1), world_for(1, random.Random(42)))
        assert cls.warm['ok'], cls.warm

    def test_checkpoint_retains_old_tables_and_pending_messages(self):
        cp = self.warm['checkpoint']
        sim = DistanceVectorNetwork.for_world(world_for(2, random.Random(42)), cp)
        self.assertEqual(sim.routers['A'], cp['routers']['A'])
        self.assertEqual(len(sim.queue), len(cp['pending']))
        self.assertFalse(next(n for n in sim.neighbors('C') if n['to'] == 'F')['up'])
        self.assertEqual({n['to'] for n in sim.neighbors('A')}, {'B', 'D'})

    def test_failure_loop_is_forwarded_until_ttl_not_rejected_by_visited(self):
        r = evaluate(reference_code(1), world_for(2, random.Random(42)), self.warm['checkpoint'])
        self.assertFalse(r['ok'])
        self.assertIn('TTL', r['message'])
        self.assertEqual(len(r['route']), 13)
        self.assertLess(len(set(r['route'])), len(r['route']))
        self.assertTrue(any(e['kind'] == 'loop' for e in r['events']))
        self.assertEqual([e['ttl'] for e in r['events'] if e['kind'] == 'packet'], list(range(11, -1, -1)))

    def test_delivery_without_distributed_convergence_cannot_skip_experiment(self):
        code = """def solve(ctx):
    if ctx['phase'] == 'update':
        return {'table':ctx['table'], 'advertise':{}}
    return {'A':'B','B':'C','C':'F'}.get(ctx['current'])
"""
        r = evaluate(code, world_for(1, random.Random(42)))
        self.assertFalse(r['ok'])
        self.assertEqual(r['route'], ['A','B','C','F'])
        self.assertIn('尚未收敛', r['message'])

    def test_same_event_and_retry_are_bitwise_reproducible(self):
        cp = copy.deepcopy(self.warm['checkpoint'])
        w = world_for(2, random.Random(42))
        a, b = [evaluate(reference_code(1), w, cp) for _ in range(2)]
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(cp, self.warm['checkpoint'])

    def test_three_prior_algorithms_fail_for_different_reasons(self):
        cp = self.warm['checkpoint']
        for chapter, expected in [(2, 'TTL'), (4, '策略'), (5, '黑洞')]:
            w = world_for(chapter, random.Random(42))
            old = evaluate(reference_code(chapter-1), w, cp)
            self.assertFalse(old['ok'], old['message'])
            self.assertIn(expected, old['message'])
            fixed = evaluate(reference_code(chapter), w, cp)
            self.assertTrue(fixed['ok'], fixed['message'])
            self.assertTrue(fixed['convergence']['correct'])
            cp = fixed['checkpoint']

    def test_scheduled_partition_and_recovery_are_in_trace(self):
        r = evaluate(reference_code(6), world_for(3, random.Random(5)), self.warm['checkpoint'])
        self.assertTrue(r['ok'], r['message'])
        changes = [e for e in r['events'] if e['kind'] == 'link']
        repaired = next(e for e in changes if e['up'])
        self.assertEqual(repaired['time'] - self.warm['checkpoint']['time'], 18)
        self.assertTrue(r['convergence']['correct'])

    def test_ten_consecutive_random_incidents_no_forced_dead_end(self):
        for seed in [0, 1, 7, 42, 20261028]:
            rng, cp = random.Random(seed), self.warm['checkpoint']
            for i in range(10):
                with self.subTest(seed=seed, incident=i):
                    w = world_for(6+i, rng, i+1)
                    self.assertTrue(shortest_path(w)[0])
                    r = evaluate(reference_code(6), w, cp)
                    self.assertTrue(r['ok'], r['message'])
                    self.assertTrue(r['convergence']['correct'], r['convergence'])
                    cp = r['checkpoint']

    def test_module_globals_are_independent_per_router(self):
        code = '''counter = 0

def solve(ctx):
    global counter
    counter += 1
    ctx['state']['counter'] = counter
    if ctx['phase'] == 'forward':
        return None
    return {'table': ctx['table']}
'''
        w = replace(world_for(1, random.Random(0)), pre_ticks=0, run_ticks=1)
        r = evaluate(code, w)
        self.assertEqual({n: s['state']['counter'] for n, s in r['checkpoint']['routers'].items()},
                         {n: 2 if n == 'A' else 1 for n in 'ABCDEFG'})

    def test_forward_phase_state_mutations_are_retained(self):
        code = """def solve(ctx):
    if ctx['phase'] == 'update':
        return {'table':ctx['table']}
    ctx['state']['waits'] = ctx['state'].get('waits', 0) + 1
    return None
"""
        w = replace(world_for(1, random.Random(0)), pre_ticks=0, run_ticks=3)
        r = evaluate(code, w)
        self.assertEqual(r['checkpoint']['routers']['A']['state']['waits'], 3)
        self.assertEqual(r['checkpoint']['routers']['B']['state'], {})

    def test_child_print_unicode_does_not_break_json(self):
        w = world_for(0, random.Random(0))
        r = run_isolated({'world': asdict(w), 'code': "print('测试 🚦')\n" + reference_code(0)})
        self.assertTrue(r['ok'], r)
        self.assertIn('测试 🚦', r['log'][-1])

    def test_real_child_timeout(self):
        w = world_for(0, random.Random(0))
        r = run_isolated({'world': asdict(w), 'code': 'def solve(ctx):\n    while True: pass'}, timeout=.25)
        self.assertFalse(r['ok'])
        self.assertIn('超过', r['message'])

    def test_unserializable_state_is_reported_cleanly(self):
        w = replace(world_for(1, random.Random(0)), pre_ticks=0, run_ticks=1)
        code = "def solve(ctx):\n    ctx['state']['bad'] = {1, 2}\n    return {'table':ctx['table']}"
        r = run_isolated({'world': asdict(w), 'code': code})
        self.assertFalse(r['ok'])
        self.assertIn('JSON', r['message'])


if __name__ == '__main__':
    unittest.main()
