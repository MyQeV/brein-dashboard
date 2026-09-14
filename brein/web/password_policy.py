"""Password policy: min 10 length, 1 upper, 1 lower, 1 digit, 1 special; no username/full name."""

# Special characters for policy (no currency symbols per spec)
_SPECIAL_CHARS = set("'-!\"#$%&()*,./:;?@[]^_`{|}~+<=>")


def _password_contains_username(password: str, username: str) -> bool:
    """True if password contains username (case-insensitive)."""
    u = (username or "").strip()
    if not u:
        return False
    return u.lower() in password.lower()


def _password_contains_full_name(password: str, full_name: str | None) -> bool:
    """True if password contains entire display name (case-insensitive)."""
    if not full_name or not full_name.strip():
        return False
    return full_name.strip().lower() in password.lower()


def validate_password_for_user(
    password: str,
    username: str,
    full_name: str | None = None,
) -> None:
    """
    Validate password for create/setup. Raises ValueError with message on failure.
    Rules: length >= 10, at least 1 uppercase, 1 lowercase, 1 digit, 1 special;
    must not contain username or entire full name (case-insensitive).
    """
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")

    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c in "0123456789" for c in password)
    has_special = any(c in _SPECIAL_CHARS for c in password)

    if not has_upper:
        raise ValueError("Password must contain at least one uppercase letter")
    if not has_lower:
        raise ValueError("Password must contain at least one lowercase letter")
    if not has_digit:
        raise ValueError("Password must contain at least one digit")
    if not has_special:
        raise ValueError("Password must contain at least one special character")

    if _password_contains_username(password, username):
        raise ValueError("Password must not contain your username")

    if _password_contains_full_name(password, full_name):
        raise ValueError("Password must not contain your full name")
