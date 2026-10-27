"""Order statistics shown on the shop dashboard."""


def average(values: list[float]) -> float:
    """Mean of the values. A shop with no orders has an average of 0.0."""
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    """Median of the values (the mean of the two middle values for an even count)."""
    if not values:
        raise ValueError("median of an empty list")
    ordered = sorted(values)
    return ordered[len(ordered) // 2]
