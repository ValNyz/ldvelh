"""finish_despite_cancel: the post-commit part of a turn outlives a cancellation (#20)."""

import asyncio
import logging

import pytest

from pipeline.uncancellable import finish_despite_cancel

TIMEOUT = 5.0


async def test_not_cancelled_behaves_like_await():
    async def boom():
        raise RuntimeError("disk full")

    with pytest.raises(RuntimeError):
        await finish_despite_cancel(boom(), ref="t")


async def test_cancelled_caller_waits_for_completion_then_reraises():
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def after_commit():
        entered.set()
        await release.wait()
        finished.set()

    outer = asyncio.create_task(finish_despite_cancel(after_commit(), ref="t"))
    await asyncio.wait_for(entered.wait(), TIMEOUT)
    outer.cancel()
    await asyncio.sleep(0.01)
    assert not outer.done()  # still waiting for the shielded part
    outer.cancel()  # a second cancel does not stop it either
    await asyncio.sleep(0.01)
    release.set()

    await asyncio.wait({outer}, timeout=TIMEOUT)
    assert finished.is_set()
    assert outer.cancelled()


async def test_failure_after_cancellation_is_logged(caplog):
    entered, release = asyncio.Event(), asyncio.Event()

    async def after_commit():
        entered.set()
        await release.wait()
        raise RuntimeError("director exploded")

    outer = asyncio.create_task(finish_despite_cancel(after_commit(), ref="t"))
    await asyncio.wait_for(entered.wait(), TIMEOUT)
    with caplog.at_level(logging.ERROR, logger="pipeline.uncancellable"):
        outer.cancel()
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait({outer}, timeout=TIMEOUT)

    assert outer.cancelled()
    assert "Post-commit step failed after cancellation" in caplog.text
    assert "director exploded" in caplog.text
