"""
Shared helpers for integration tests.
"""


def auth_headers(token: str) -> dict:
    """Build Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}
