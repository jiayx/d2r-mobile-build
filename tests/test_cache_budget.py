from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cache_budget import choose


class CacheBudgetTests(unittest.TestCase):
    def test_near_capacity_preserves_reserve_and_prioritizes_complete_payload(self):
        self.assertEqual(choose(800, {'payload': 100, 'rewrite': 80, 'shaders': 200, 'tools': 20},
                                limit=1000, reserve=50),
                         {'payload': True, 'rewrite': False, 'shaders': False, 'tools': True})

    def test_full_or_already_exceeded_limit_never_saves_optional_cache(self):
        for used in (950, 1000, 1100):
            self.assertFalse(any(choose(used, {'payload': 10}, limit=1000, reserve=50).values()))


if __name__ == '__main__':
    unittest.main()
