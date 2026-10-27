"""Pagination for product lists. Pages are numbered starting at 1."""


def paginate(items: list, page: int, per_page: int = 10) -> list:
    """Return the items on the given (1-based) page."""
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page must be positive")
    start = page * per_page
    end = start + per_page
    return items[start:end]


def page_count(total_items: int, per_page: int = 10) -> int:
    """Number of pages needed to show total_items."""
    return (total_items + per_page - 1) // per_page
