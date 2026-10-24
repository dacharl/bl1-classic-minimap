"""Check that quality gates reject missing, incomplete and below-threshold results."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_checks import coverage_errors, mutation_errors  # noqa: E402


class GateChecks(unittest.TestCase):
    def test_coverage_uses_separate_line_and_branch_floors(self):
        report = {'files': {'mod.py': {'summary': {
            'num_statements': 10, 'covered_lines': 9,
            'num_branches': 10, 'covered_branches': 7,
        }}}}
        floors = {'mod.py': {'line': 90, 'branch': 70}}
        self.assertEqual(coverage_errors(report, floors), [])
        floors['mod.py']['branch'] = 71
        self.assertTrue(coverage_errors(report, floors))
        self.assertTrue(coverage_errors({'files': {}}, floors))

    def test_mutations_fail_closed_and_count_timeouts_as_undetected(self):
        report = {'mod.py': {'total': 10, 'killed': 8, 'survived': 1,
                             'timeout': 1, 'error': 0, 'pending': 0}}
        self.assertEqual(mutation_errors(report, {'mod.py': 80}), [])
        self.assertTrue(mutation_errors(report, {'mod.py': 81}))
        report['mod.py']['error'] = 1
        self.assertTrue(mutation_errors(report, {'mod.py': 0}))
        self.assertTrue(mutation_errors({}, {'mod.py': 0}))
        for result in ({'total': 0}, {'total': 1, 'pending': 1},
                       {'total': 2, 'killed': 1}):
            self.assertTrue(mutation_errors({'mod.py': result}, {'mod.py': 0}))


if __name__ == '__main__':
    unittest.main()
