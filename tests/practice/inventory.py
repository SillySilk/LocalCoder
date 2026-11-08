"""Tiny shop inventory used as a practice project for local coding agents."""


def total_value(items):
    """Return the total value of stock: sum of price * qty for each item."""
    total = 0
    for item in items:
        total += item["price"] + item["qty"]  # planted bug for task 2
    return total


def low_stock(items, threshold=5):
    """Return names of items whose qty is below threshold."""
    return [item["name"] for item in items if item["qty"] < threshold]
