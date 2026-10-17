"""
LDVELH - Simple in-memory rate limiter (auth, world enhance, chat).

Sliding window of timestamps per key (client IP or user). Sufficient for a
single-server deployment; idle keys are purged once per window.
"""

import time
from collections.abc import Callable

from fastapi import HTTPException, Request

from config import get_settings

RATE_LIMITED_CODE = "rate_limited"


class RateLimited(HTTPException):
    """429 with a French message; api.http_errors adds `code: rate_limited` to the body."""

    code = RATE_LIMITED_CODE

    def __init__(self, retry_after: int):
        super().__init__(
            status_code=429,
            detail=f"Trop de requêtes. Réessaie dans {retry_after} s.",
            headers={"Retry-After": str(retry_after)},
        )


def client_ip(request: Request, hops: int) -> str:
    """Client address as seen by the outermost of `hops` trusted reverse proxies.

    Each proxy appends the address it received the request from to X-Forwarded-For,
    so entries left of the ones the trusted proxies added are client-supplied and
    ignored. With hops=0 (no proxy) the header is ignored altogether.
    """
    peer = request.client.host if request.client else "unknown"
    if hops <= 0:
        return peer
    forwarded = [part.strip()
                 for header in request.headers.getlist("x-forwarded-for")
                 for part in header.split(",") if part.strip()]
    if len(forwarded) >= hops:
        return forwarded[-hops]
    return forwarded[0] if forwarded else peer


class RateLimiter:
    """Sliding-window rate limiter keyed by an arbitrary string."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 60,
                 clock: Callable[[], float] = time.monotonic):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, list[float]] = {}
        self._last_purge = clock()
        _LIMITERS.append(self)

    def hit(self, key: str) -> None:
        """Count one request for `key`; raise RateLimited if over the limit."""
        now = self._clock()
        cutoff = now - self.window_seconds
        self._purge_idle(now, cutoff)
        hits = [t for t in self._hits.get(key, ()) if t > cutoff]
        if len(hits) >= self.max_requests:
            self._hits[key] = hits
            raise RateLimited(self.window_seconds)
        hits.append(now)
        self._hits[key] = hits

    def check(self, request: Request) -> None:
        """Count one request for the client IP (behind TRUSTED_PROXY_HOPS proxies)."""
        self.hit(client_ip(request, get_settings().trusted_proxy_hops))

    def reset(self) -> None:
        self._hits.clear()

    def _purge_idle(self, now: float, cutoff: float) -> None:
        """Drop keys with no hit in the last window, at most once per window."""
        if now - self._last_purge < self.window_seconds:
            return
        self._last_purge = now
        self._hits = {key: hits for key, hits in self._hits.items() if hits and hits[-1] > cutoff}


_LIMITERS: list[RateLimiter] = []


def reset_all_limiters() -> None:
    """Forget every hit of every limiter (tests)."""
    for limiter in _LIMITERS:
        limiter.reset()


# Shared instance: 5 auth attempts per 60s per IP
auth_limiter = RateLimiter(max_requests=5, window_seconds=60)
