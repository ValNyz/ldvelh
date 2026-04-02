"""
LDVELH - Simple in-memory rate limiter for auth endpoints.

Uses a dict of {ip: [timestamps]} with sliding window.
Sufficient for single-server deployment.
"""

import time
from collections import defaultdict

from fastapi import Request, HTTPException


class RateLimiter:
    """Sliding-window rate limiter keyed by client IP."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def check(self, request: Request) -> None:
        """Raise 429 if rate limit exceeded."""
        ip = self._client_ip(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds

        # Prune old entries
        hits = self._hits[ip]
        self._hits[ip] = [t for t in hits if t > cutoff]

        if len(self._hits[ip]) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Try again in {self.window_seconds}s.",
            )

        self._hits[ip].append(now)


# Shared instance: 5 auth attempts per 60s per IP
auth_limiter = RateLimiter(max_requests=5, window_seconds=60)
