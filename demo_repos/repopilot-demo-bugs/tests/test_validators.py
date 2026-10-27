import pytest

from shop.validators import extract_domain, normalize_email


def test_extract_domain_ok():
    assert extract_domain("Ana@Example.COM ") == "example.com"


def test_empty_email_is_rejected_with_value_error():
    with pytest.raises(ValueError):
        extract_domain("")


def test_normalize_email():
    assert normalize_email("  Ana@Example.com ") == "ana@example.com"
