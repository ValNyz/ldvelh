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
    assert "Commit or post-commit step failed after cancellation" in caplog.text
    assert "director exploded" in caplog.text


async def test_cancelled_post_save_failure_is_logged_exactly_once(caplog):
    """No report_error runs once the caller is gone: finish_despite_cancel logs it, once."""
    from pipeline.errors import finish_saved

    entered, release = asyncio.Event(), asyncio.Event()

    async def failing_step():
        entered.set()
        await release.wait()
        raise RuntimeError("db hiccup")

    outer = asyncio.create_task(
        finish_despite_cancel(finish_saved(failing_step(), ref="t"), ref="t"))
    with caplog.at_level(logging.INFO):
        await asyncio.wait_for(entered.wait(), TIMEOUT)
        outer.cancel()
        await asyncio.sleep(0.01)
        release.set()
        await asyncio.wait({outer}, timeout=TIMEOUT)
    logged = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(logged) == 1, [r.getMessage() for r in logged]
    assert "db hiccup" in logging.Formatter().format(logged[0])


class _Abort(BaseException):
    """A BaseException that is not an Exception (as KeyboardInterrupt, without its loop side effects)."""


async def test_base_exception_after_cancellation_is_logged_then_reraised(caplog):
    entered, release = asyncio.Event(), asyncio.Event()

    async def after_commit():
        entered.set()
        await release.wait()
        raise _Abort("interrupted")

    outer = asyncio.create_task(finish_despite_cancel(after_commit(), ref="t"))
    await asyncio.wait_for(entered.wait(), TIMEOUT)
    with caplog.at_level(logging.ERROR, logger="pipeline.uncancellable"):
        outer.cancel()
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait({outer}, timeout=TIMEOUT)

    assert isinstance(outer.exception(), _Abort)
    assert "Commit or post-commit step failed after cancellation" in caplog.text
    assert "interrupted" in caplog.text


async def test_base_exception_without_cancellation_is_logged_then_reraised(caplog):
    async def after_commit():
        raise _Abort("interrupted")

    with caplog.at_level(logging.ERROR, logger="pipeline.uncancellable"):
        with pytest.raises(_Abort):
            await finish_despite_cancel(after_commit(), ref="t")

    assert "Commit or post-commit step aborted" in caplog.text
    assert "interrupted" in caplog.text


async def test_returns_the_result_of_the_shielded_part():
    async def after_commit():
        return 42

    assert await finish_despite_cancel(after_commit(), ref="t") == 42
