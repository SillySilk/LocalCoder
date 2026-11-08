import unittest

from inventory import low_stock, total_value
from report import build_report

ITEMS = [
    {"name": "widget", "price": 2.50, "qty": 10},
    {"name": "gadget", "price": 10.00, "qty": 2},
]


class InventoryTests(unittest.TestCase):
    def test_total_value(self):
        self.assertAlmostEqual(total_value(ITEMS), 45.00)

    def test_low_stock(self):
        self.assertEqual(low_stock(ITEMS), ["gadget"])

    def test_report(self):
        self.assertIn("Reorder: gadget", build_report(ITEMS))


if __name__ == "__main__":
    unittest.main()
