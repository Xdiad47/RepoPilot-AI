import pytest

from shop.stats import average, median


def test_average():
    assert average([2, 4, 6]) == 4


def test_average_of_no_orders_is_zero():
    assert average([]) == 0.0


def test_median_odd():
    assert median([5, 1, 3]) == 3


def test_median_even_is_mean_of_middle_values():
    assert median([1, 2, 3, 4]) == 2.5


def test_median_empty():
    with pytest.raises(ValueError):
        median([])
