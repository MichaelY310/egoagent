import unittest
from quote import subtotal


class QuoteTests(unittest.TestCase):
    def test_subtotal(self):
        self.assertAlmostEqual(subtotal(3, 19.9), 59.7)


if __name__ == '__main__':
    unittest.main()
