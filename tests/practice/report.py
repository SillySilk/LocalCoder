from inventory import total_value, low_stock


def build_report(items):
    lines = [f"Total stock value: {total_value(items):.2f}"]
    for name in low_stock(items):
        lines.append(f"Reorder: {name}")
    return "\n".join(lines)
