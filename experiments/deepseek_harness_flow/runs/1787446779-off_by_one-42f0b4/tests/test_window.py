import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from window import moving_average


class MovingAverageTests(unittest.TestCase):
    def test_all_complete_windows_are_returned(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])

    def test_equal_window_length_returns_one_average(self):
        self.assertEqual(moving_average([2, 4, 6], 3), [4.0])

    def test_invalid_window_is_preserved(self):
        with self.assertRaises(ValueError):
            moving_average([1], 0)


if __name__ == "__main__":
    unittest.main()
