import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from duration import parse_duration


class DurationTests(unittest.TestCase):
    def test_single_part(self):
        self.assertEqual(parse_duration("2h"), 7200)

    def test_composite_duration(self):
        self.assertEqual(parse_duration("1h30m5s"), 5405)

    def test_rejects_unconsumed_or_reordered_text(self):
        for value in ("1hwat", "30m1h", "", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_duration(value)


if __name__ == "__main__":
    unittest.main()
