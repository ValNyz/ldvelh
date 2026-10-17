"""Unit tests of the in-memory rate limiter and the client IP behind trusted proxies (#82)."""

import pytest
from starlette.requests import Request

from utils.rate_limit import RateLimited, RateLimiter, client_ip


def _request(peer: str = "10.0.0.2", forwarded: list[str] | None = None) -> Request:
    headers = [(b"x-forwarded-for", value.encode()) for value in forwarded or []]
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_without_trusted_proxy_the_header_is_ignored():
    assert client_ip(_request(forwarded=["6.6.6.6"]), hops=0) == "10.0.0.2"


def test_one_trusted_proxy_takes_the_entry_it_appended_not_the_client_supplied_head():
    # Traefik appends the address it saw: whatever the client sent stays at the head.
    request = _request(forwarded=["6.6.6.6, 7.7.7.7", "203.0.113.9"])
    assert client_ip(request, hops=1) == "203.0.113.9"


def test_two_trusted_proxies_skip_the_inner_one():
    request = _request(forwarded=["6.6.6.6, 203.0.113.9, 172.18.0.5"])
    assert client_ip(request, hops=2) == "203.0.113.9"


def test_fewer_entries_than_hops_falls_back_to_the_leftmost_then_the_peer():
    assert client_ip(_request(forwarded=["203.0.113.9"]), hops=2) == "203.0.113.9"
    assert client_ip(_request(), hops=1) == "10.0.0.2"


def test_limit_raises_a_french_rate_limited_error_with_retry_after():
    limiter = RateLimiter(max_requests=2, window_seconds=30, clock=_Clock())
    limiter.hit("user:1")
    limiter.hit("user:1")
    with pytest.raises(RateLimited) as caught:
        limiter.hit("user:1")
    assert caught.value.status_code == 429
    assert caught.value.code == "rate_limited"
    assert "Trop de requêtes" in caught.value.detail
    assert caught.value.headers == {"Retry-After": "30"}
    limiter.hit("user:2")  # other keys are independent


def test_the_window_slides():
    clock = _Clock()
    limiter = RateLimiter(max_requests=1, window_seconds=60, clock=clock)
    limiter.hit("k")
    clock.now += 61
    limiter.hit("k")


def test_idle_keys_are_purged():
    clock = _Clock()
    limiter = RateLimiter(max_requests=5, window_seconds=60, clock=clock)
    for i in range(100):
        limiter.hit(f"ip-{i}")
    clock.now += 30
    limiter.hit("active")
    assert len(limiter._hits) == 101  # nothing idle for a full window yet
    clock.now += 31  # ip-* idle for 61 s, "active" for 31 s
    limiter.hit("other")
    assert set(limiter._hits) == {"active", "other"}
