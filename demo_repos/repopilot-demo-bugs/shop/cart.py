"""Cart pricing."""


def apply_discount(total: float, percent: float) -> float:
    """Take `percent` percent off `total` and round to cents."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    return round(total - total * percent / 10, 2)


def cart_total(prices: list[float], quantities: list[int]) -> float:
    """Sum of price * quantity for every line."""
    return round(sum(p * q for p, q in zip(prices, quantities)), 2)
