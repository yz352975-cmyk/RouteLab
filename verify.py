"""Run the standard-library test suite and write auditable UTF-8 reports."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import platform
import sys
import time
import unittest

HERE = Path(__file__).resolve().parent


class Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, value):
        for stream in self.streams:
            stream.write(value)
    def flush(self):
        for stream in self.streams:
            stream.flush()


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append(dict(test=test.id(), status='passed'))
    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append(dict(test=test.id(), status='failed'))
    def addError(self, test, err):
        super().addError(test, err)
        self.records.append(dict(test=test.id(), status='error'))
    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records.append(dict(test=test.id(), status='skipped', reason=reason))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=HERE/'reports')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (args.output_dir/'test_output.txt').open('w', encoding='utf-8') as log:
        suite = unittest.defaultTestLoader.discover(str(HERE/'tests'))
        result = unittest.TextTestRunner(stream=Tee(sys.stdout, log), verbosity=2,
                                        resultclass=RecordedResult).run(suite)
    report = dict(date=datetime.now(timezone(timedelta(hours=8))).isoformat(),
                  python=sys.version, platform=platform.platform(), tests=result.testsRun,
                  failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                  elapsed_seconds=round(time.monotonic()-started, 3),
                  gui_executed=any('.UITests.' in r['test'] and r['status']=='passed' for r in result.records),
                  successful=result.wasSuccessful(), cases=result.records)
    (args.output_dir/'test_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
