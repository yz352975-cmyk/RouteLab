"""Headless, deterministic reference experiment. Never changes the GUI editor."""
import argparse
import json
from pathlib import Path
import random
from engine import reference_code, world_for
from runner import evaluate


def experiment(seed):
    rng = random.Random(seed)
    checkpoint = None
    cases = []
    for chapter in range(6):
        world = world_for(chapter, rng)
        programs = [('reference', reference_code(chapter))]
        if chapter in (2, 4, 5):
            programs.insert(0, ('previous_algorithm', reference_code(chapter-1)))
        for kind, program in programs:
            result = evaluate(program, world, checkpoint)
            case = dict(event=world.title, seed=world.seed, algorithm=kind,
                        ok=result['ok'], message=result['message'], route=result['route'],
                        cost=result['cost'], convergence=result.get('convergence'), log=result['log'])
            case['timeline'] = [dict(time=f['time'],
                                     to_F={n: table.get('F', {'metric':16, 'next_hop':None})
                                           for n, table in f['tables'].items()},
                                     in_flight=f['in_flight'], failed=f['failed'],
                                     routing_loops=f.get('routing_loops', []),
                                     packet=f['packet']) for f in result.get('frames', [])]
            case['messages'] = [e for e in result.get('events', []) if e['kind'] in ('send','deliver','drop','link','loop')]
            cases.append(case)
            if kind == 'reference':
                if not result['ok']:
                    raise RuntimeError(case['message'])
                checkpoint = result.get('checkpoint')
    return dict(session_seed=seed, cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=20261028)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = experiment(args.seed)
    for case in result['cases']:
        print(f"{case['event']} / {case['algorithm']}: {case['ok']} | {case['message']}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
