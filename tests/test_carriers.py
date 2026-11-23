import random
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from carriers import EVENTS, market, optimum, validate
from engine import reference_for, session_world
from runner import evaluate, run_isolated
from dataclasses import asdict


class CarrierTests(unittest.TestCase):
    def test_seeded_free_play_keeps_contract_history_and_dv_checkpoint(self):
        def play(seed):
            rng, checkpoint, amendments = random.Random(seed), None, None
            history = []
            for chapter in range(35):
                world = session_world(chapter, rng, max(0, chapter-5), amendments)
                code = reference_for(world)
                if world.protocol == 'service':
                    code = ("def solve(ctx): return {'repeat_limits': {s: 1 for s,v in ctx['sources'].items() "
                            "if v['repeats'] > 8 and v.get('sessions', 0) <= 4}}")
                result = evaluate(code, world, checkpoint)
                self.assertTrue(result['ok'], (chapter, result['message']))
                if world.protocol == 'carrier':
                    amendments = world.amendments
                elif world.protocol != 'service':
                    checkpoint = result.get('checkpoint')
                history.append((world.headline, world.seed, result['route'], result['cost']))
            return history
        self.assertEqual(play(42), play(42))
        self.assertNotEqual(play(1), play(42))

    def test_ten_incidents_through_runner(self):
        rng = random.Random(42)
        for index in range(10):
            world = session_world(7 + index, rng)
            result = run_isolated(dict(code=reference_for(world), world=asdict(world)))
            self.assertTrue(result['ok'], result['message'])
            self.assertEqual(result['cost'], optimum(market(index)))
        self.assertEqual(session_world(17, rng).protocol, 'service')
        self.assertEqual(session_world(18, rng).title, 'S2')
        self.assertEqual(session_world(19, rng).protocol, 'dv')

    def test_player_cannot_rewrite_contracts_in_validator(self):
        world = session_world(8, random.Random(42))
        code = "def solve(ctx):\n    ctx['links'][1]['contract'] = 'transit'\n    return ['A','B','C','F']"
        self.assertFalse(evaluate(code, world)['ok'])

    def test_contract_expiry_stops_packet_at_border(self):
        route = ['A', 'B', 'C', 'F']
        self.assertTrue(validate(market(0), route)[0])
        ok, message, prefix, _ = validate(market(1), route)
        self.assertFalse(ok)
        self.assertEqual(prefix, ['A', 'B'])
        self.assertIn('对等协议', message)
        self.assertTrue(validate(market(1), ['A', 'D', 'E', 'F'])[0])

    def test_market_history_is_independent_and_always_reachable(self):
        for index in range(len(EVENTS)):
            data = market(index)
            self.assertLess(optimum(data), float('inf'))
            data['links'].clear()
            self.assertTrue(market(index)['links'])
