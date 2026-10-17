"""
LDVELH - Simple in-memory rate limiter (auth, world enhance, chat).

Sliding window of timestamps per key (client IP or user). Sufficient for a
single-server deployment; idle keys are purged once per window.
"""

import ipaddress
import math
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


def _valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def client_ip(request: Request, hops: int) -> str:
    """Client address as seen by the outermost of `hops` trusted reverse proxies.

    Each proxy appends the address it received the request from to X-Forwarded-For,
    so entries left of the ones the trusted proxies added are client-supplied and
    ignored. With hops=0 (no proxy) the header is ignored altogether.

    `hops` must not exceed the number of proxies really in front of the backend: one
    too many makes the chosen entry a client-supplied one, i.e. a key the client
    picks. A chosen entry that is not an IP address falls back to the TCP peer.
    """
    peer = request.client.host if request.client else "unknown"
    if hops <= 0:
        return peer
    forwarded = [part.strip()
                 for header in request.headers.getlist("x-forwarded-for")
                 for part in header.split(",") if part.strip()]
    if not forwarded:
        return peer
    chosen = forwarded[-hops] if len(forwarded) >= hops else forwarded[0]
    return chosen if _valid_ip(chosen) else peer


class RateLimiter:
    """Sliding-window rate limiter keyed by an arbitrary string."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 60,
                 clock: Callable[[], float] = time.monotonic):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, list[float]] = {}
        self._last_purge = clock()

    def hit(self, key: str) -> None:
        """Count one request for `key`; raise RateLimited if over the limit."""
        hit_all((self, key))

    def check(self, request: Request) -> None:
        """Count one request for the client IP (behind TRUSTED_PROXY_HOPS proxies)."""
        self.hit(request_ip(request))

    def reset(self) -> None:
        self._hits.clear()

    def _recent(self, key: str, now: float) -> list[float]:
        """Hits of `key` still in the window (purging idle keys once per window first)."""
        cutoff = now - self.window_seconds
        if now - self._last_purge >= self.window_seconds:
            self._last_purge = now
            self._hits = {k: hits for k, hits in self._hits.items() if hits and hits[-1] > cutoff}
        return [t for t in self._hits.get(key, ()) if t > cutoff]

    def _retry_after(self, hits: list[float], now: float) -> int:
        """Seconds until the oldest hit leaves the window (at least 1)."""
        if not hits:  # max_requests == 0
            return self.window_seconds
        return max(1, math.ceil(hits[0] + self.window_seconds - now))


def hit_all(*counted: tuple[RateLimiter, str]) -> None:
    """Count one request on every (limiter, key), or on none if any of them is full.

    A request refused by one limit must not use up a slot of another one.
    """
    pending = []
    retry_after = 0
    for limiter, key in counted:
        now = limiter._clock()
        hits = limiter._recent(key, now)
        if len(hits) >= limiter.max_requests:
            retry_after = max(retry_after, limiter._retry_after(hits, now))
        pending.append((limiter, key, hits, now))
    if retry_after:
        raise RateLimited(retry_after)
    for limiter, key, hits, now in pending:
        limiter._hits[key] = [*hits, now]


def request_ip(request: Request) -> str:
    """Rate-limit key of the client address, behind TRUSTED_PROXY_HOPS proxies."""
    return client_ip(request, get_settings().trusted_proxy_hops)


_SHARED: list[RateLimiter] = []


def shared_limiter(max_requests: int, window_seconds: int) -> RateLimiter:
    """A module-level limiter of the app, reset between tests by reset_all_limiters()."""
    limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)
    _SHARED.append(limiter)
    return limiter


def reset_all_limiters() -> None:
    """Forget every hit of the app's shared limiters (tests)."""
    for limiter in _SHARED:
        limiter.reset()


# 5 auth attempts per 60s per IP
auth_limiter = shared_limiter(max_requests=5, window_seconds=60)
