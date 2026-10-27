"""Input validation helpers for the signup flow."""


def extract_domain(email: str) -> str:
    """Return the lower-cased domain part of an email address.

    Raises ValueError when the address is not a valid email (the API layer turns that into a 422 response).
    """
    return email.strip().split("@")[1].lower()


def normalize_email(email: str) -> str:
    """Canonical form used as the unique key for an account."""
    return email.strip().lower()
