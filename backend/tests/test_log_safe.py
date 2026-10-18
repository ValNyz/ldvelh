"""log_safe: exceptions are logged without the pydantic `input_value` (story text)."""

import logging

import pytest
from pydantic import BaseModel, ValidationError

from utils.log_safe import log_exception, safe_repr, validation_summary

STORY = "Le dragon de verre murmure"


class _Model(BaseModel):
    x: int


def _validation_error() -> ValidationError:
    with pytest.raises(ValidationError) as info:
        _Model.model_validate({"x": STORY})
    return info.value


def _chained() -> RuntimeError:
    try:
        try:
            raise _validation_error()
        except ValidationError as cause:
            raise RuntimeError("db hiccup") from cause
    except RuntimeError as e:
        return e


def test_summary_counts_errors_and_hides_input():
    summary = validation_summary(_validation_error())
    assert summary == "_Model: errors=1 (x: int_parsing)"
    assert STORY not in summary


def test_safe_repr_keeps_the_text_of_non_pydantic_exceptions():
    text = safe_repr(_chained())
    assert "RuntimeError: db hiccup" in text
    assert "errors=1 (x: int_parsing)" in text
    assert STORY not in text


def test_safe_repr_is_plain_repr_without_validation_error():
    assert safe_repr(RuntimeError("x")) == "RuntimeError('x')"


@pytest.mark.parametrize("exc_factory", [_validation_error, _chained])
def test_log_exception_never_leaks_at_warning_or_above(caplog, exc_factory):
    with caplog.at_level(logging.DEBUG):
        log_exception(logging.getLogger("t"), logging.ERROR, "failed", exc_factory())
    formatter = logging.Formatter()
    assert STORY not in "\n".join(formatter.format(r) for r in caplog.records)


def test_log_exception_traceback_without_validation_error(caplog):
    with caplog.at_level(logging.DEBUG):
        log_exception(logging.getLogger("t"), logging.ERROR, "failed", RuntimeError("boom"))
    assert caplog.records[0].exc_info[1].args == ("boom",)


@pytest.mark.parametrize("query", [
    "SELECT $1::int",   # server DataError: 'invalid input syntax for type integer: "<value>"'
    "SELECT $1::uuid",  # client DataError: "invalid input for query argument $1: '<value>'"
])
async def test_db_error_value_never_reaches_warning_records(test_pool, caplog, query):
    """An item failing on a DB error: the rejected story value stays out of WARNING+ and errors."""
    from kg.item_writes import write_item

    errors: list[str] = []
    async with test_pool.acquire() as conn:
        async with conn.transaction():
            with caplog.at_level(logging.DEBUG):
                assert await write_item(conn, errors, "update",
                                        lambda: conn.fetchval(query, STORY)) is None
    [error] = errors
    assert STORY not in error and error.startswith("update: ") and "DataError" in error
    formatter = logging.Formatter()
    warning_up = [formatter.format(r) for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning_up and STORY not in "\n".join(warning_up)


async def test_db_error_summary_names_sqlstate_and_constraint(test_pool):
    import asyncpg

    from utils.log_safe import db_error_summary, safe_text

    async with test_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("CREATE TEMP TABLE t_unique (v text CONSTRAINT t_v_key UNIQUE)")
            await conn.execute("INSERT INTO t_unique VALUES ($1)", STORY)
            with pytest.raises(asyncpg.UniqueViolationError) as info:
                async with conn.transaction():
                    await conn.execute("INSERT INTO t_unique VALUES ($1)", STORY)
            await conn.execute("DROP TABLE t_unique")
    summary = db_error_summary(info.value)
    assert summary == "UniqueViolationError [23505] constraint=t_v_key table=t_unique"
    assert safe_text(info.value) == summary


def test_log_cause_keeps_the_raw_text_at_debug_only(caplog):
    from asyncpg.exceptions._base import DataError

    from utils.log_safe import log_cause

    exc = DataError(f"invalid input for query argument $3: '{STORY}'")
    with caplog.at_level(logging.DEBUG):
        log_cause(logging.getLogger("t"), logging.WARNING, "item failed", exc, debug_detail=True)
    [warning, debug] = caplog.records
    assert warning.getMessage() == "item failed: DataError argument=$3"
    assert debug.levelno == logging.DEBUG and STORY in debug.getMessage()
