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
    # client-side encoding error (asyncpg.DataError, 22000):
    # "invalid input for query argument $1: '<value>'"
    "SELECT $1::uuid",
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


@pytest.mark.parametrize("debug_detail", [True, False])
def test_log_cause_keeps_the_raw_text_at_debug_only(caplog, debug_detail):
    """The raw DB text is logged at DEBUG only, and only with debug_detail (LOG_PROMPTS)."""
    import asyncpg

    from utils.log_safe import log_cause

    exc = asyncpg.DataError(f"invalid input for query argument $3: '{STORY}'")
    with caplog.at_level(logging.DEBUG):
        log_cause(logging.getLogger("t"), logging.WARNING, "item failed", exc,
                  debug_detail=debug_detail)
    warning, *rest = caplog.records
    assert warning.getMessage() == "item failed: DataError [22000] argument=$3"
    if debug_detail:
        [debug] = rest
        assert debug.levelno == logging.DEBUG and STORY in debug.getMessage()
    else:
        assert rest == [] and STORY not in warning.getMessage()



async def test_unroutable_entity_warnings_carry_no_entity_name(test_pool, test_user, caplog):
    """An unsupported creation type or an unknown update target is logged without the name."""
    from kg.specialized_populator import ExtractionPopulator
    from schema import NarrativeExtraction
    from services.game_service import GameService

    game_id = await GameService(test_pool).create_game(test_user["id"])
    extraction = NarrativeExtraction.model_validate({
        "cycle": 1,
        "entities_created": [{"entity_type": "protagonist", "name": STORY, "data": {}}],
        "entities_updated": [{"entity_ref": STORY, "changes": {"mood": "calme"}}],
    })
    with caplog.at_level(logging.DEBUG):
        await ExtractionPopulator(test_pool, game_id).process_extraction(extraction)
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Unsupported entity type" in w for w in warnings)
    assert any("Unknown entity type" in w for w in warnings)
    assert not [w for w in warnings if STORY in w]
