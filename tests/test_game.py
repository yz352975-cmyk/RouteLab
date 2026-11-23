import random
import unittest
import sys
import json
import subprocess
from pathlib import Path
from dataclasses import asdict
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import world_for, reference_code, shortest_path, ctx_for
from runner import evaluate

class GameTests(unittest.TestCase):
    def test_reference_code_every_story_event(self):
        for chapter in range(6):
            for seed in range(20):
                with self.subTest(chapter=chapter, seed=seed):
                    world = world_for(chapter, random.Random(seed))
                    result = evaluate(reference_code(chapter), world)
                    self.assertTrue(result['ok'], result)

    def test_reference_code_random_incidents(self):
        for seed in range(150):
            rng = random.Random(seed)
            world = world_for(6, rng, seed+1)
            with self.subTest(seed=seed):
                self.assertTrue(shortest_path(world)[0])
                result = evaluate(reference_code(6), world)
                self.assertTrue(result['ok'], result)

    def test_failure_during_vision_change(self):
        world = world_for(1, random.Random(3))
        result = evaluate(reference_code(0), world)
        self.assertFalse(result['ok'])
        self.assertIn("'graph'", result['message'])

    def test_runner_subprocess(self):
        world = world_for(0, random.Random(0))
        process = subprocess.run([sys.executable, '-I', 'runner.py'],
            cwd=str(Path(__file__).resolve().parents[1]),
            input=json.dumps({'world': asdict(world), 'code': reference_code(0)}),
            text=True, encoding='utf-8', capture_output=True, timeout=3)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(json.loads(process.stdout)['ok'])

    def test_invalid_start_returns_no_animation_route(self):
        world = world_for(0, random.Random(0))
        result = evaluate("def solve(ctx): return ['X', 'F']", world)
        self.assertFalse(result['ok'])
        self.assertEqual(result['route'], [])

    def test_player_error_location(self):
        world = world_for(0, random.Random(0))
        for code in ('def solve(ctx):\n    return absent', 'def solve(ctx):\n    if :'):
            self.assertEqual(evaluate(code, world)['error_line'], 2)

    def test_split_horizon_omits_reverse_destination_from_real_messages(self):
        world = world_for(1, random.Random(7))
        code = reference_code(1).replace('SPLIT_HORIZON = False', 'SPLIT_HORIZON = True')
        result = evaluate(code, world)
        self.assertTrue(result['ok'], result['message'])
        sent = [e for e in result['events'] if e['kind'] == 'send' and e['sender'] == 'A' and e['receiver'] == 'B']
        self.assertTrue(sent)
        self.assertTrue(all('B' not in e['vector'] for e in sent))

if __name__ == '__main__':
    unittest.main()
