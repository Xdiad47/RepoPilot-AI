import pytest

from shop.cart import apply_discount, cart_total


def test_ten_percent_discount():
    assert apply_discount(200.0, 10) == 180.0


def test_no_discount():
    assert apply_discount(99.99, 0) == 99.99


def test_invalid_percent():
    with pytest.raises(ValueError):
        apply_discount(10, 101)


def test_cart_total():
    assert cart_total([2.5, 10.0], [2, 1]) == 15.0
