"""Log exceptions without leaking story text.

A pydantic ValidationError embeds `input_value=` fragments of the validated payload (here:
the generated story) in its message and traceback. A database error can quote the
rejected value too (asyncpg: "invalid input for query argument $7: '<value>'", or the
server's DETAIL/message). Anything logged at WARNING or above describes such a cause by
its field paths and error types, or by its exception class and SQLSTATE / constraint /
table / column names, only.
"""

import logging
import re

from asyncpg.exceptions import PostgresError
from asyncpg.exceptions._base import DataError as ClientDataError  # argument encoding
from pydantic import ValidationError


def validation_summary(exc: ValidationError) -> str:
    """`ValidationError: errors=2 (time.new_time: missing; credit_delta: int_parsing)`."""
    errors = exc.errors(include_input=False, include_url=False, include_context=False)
    where = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['type']}"
                      for e in errors)
    return f"{exc.title}: errors={len(errors)} ({where})"


_DB_NAMES = ("constraint_name", "table_name", "column_name")


def db_error_summary(exc: PostgresError | ClientDataError) -> str:
    """`UniqueViolationError [23505] constraint=characters_game_id_name_key table=characters`.

    The message itself is left out: it may quote the rejected value.
    """
    parts = [type(exc).__name__]
    if isinstance(exc, PostgresError):
        if exc.sqlstate:
            parts.append(f"[{exc.sqlstate}]")
        parts += [f"{n.removesuffix('_name')}={getattr(exc, n)}"
                  for n in _DB_NAMES if getattr(exc, n, None)]
    arg = re.search(r"query argument \$(\d+)", str(exc))
    if arg:
        parts.append(f"argument=${arg.group(1)}")
    return " ".join(parts)


def _is_db_error(exc: BaseException) -> bool:
    return isinstance(exc, (PostgresError, ClientDataError))


def _chain(exc: BaseException | None):
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def has_validation_error(exc: BaseException) -> bool:
    return any(isinstance(e, ValidationError) for e in _chain(exc))


def has_sensitive_error(exc: BaseException) -> bool:
    """A validation or database error in the cause chain: its text may quote story text."""
    return any(isinstance(e, ValidationError) or _is_db_error(e) for e in _chain(exc))


def _summary(exc: BaseException) -> str:
    if isinstance(exc, ValidationError):
        return validation_summary(exc)
    if _is_db_error(exc):
        return db_error_summary(exc)
    return f"{type(exc).__name__}: {exc}"


def safe_repr(exc: BaseException) -> str:
    """`repr(exc)`, except that validation and database errors in the chain are summarised.

    Other exceptions of such a chain keep their text (`RuntimeError: db hiccup`).
    """
    if not has_sensitive_error(exc):
        return repr(exc)
    parts, below_db = [], False
    for e in _chain(exc):
        # The cause of a DB error (e.g. the ValueError of an argument encoding) quotes the
        # same value: only its class is kept.
        parts.append(type(e).__name__ if below_db and not isinstance(e, ValidationError)
                     else _summary(e))
        below_db = below_db or _is_db_error(e)
    return " <- ".join(parts)


def safe_text(exc: BaseException) -> str:
    """`str(exc)`, except that validation and database errors in the chain are summarised."""
    if not has_sensitive_error(exc):
        return str(exc)
    return safe_repr(exc)


def log_exception(logger: logging.Logger, level: int, message: str, exc: BaseException,
                  *, debug_detail: bool = False) -> None:
    """Log `message` with the traceback of `exc`, or its safe summary for validation causes.

    With a validation or database error in the chain, the full traceback (story fragments)
    is only emitted at DEBUG, and only when `debug_detail` (the LOG_PROMPTS setting) allows it.
    """
    if not has_sensitive_error(exc):
        logger.log(level, message, exc_info=exc)
        return
    logger.log(level, f"{message} [cause: {safe_repr(exc)}]")
    if debug_detail:
        logger.debug(message, exc_info=exc)


def log_cause(logger: logging.Logger, level: int, message: str, exc: BaseException,
              *, debug_detail: bool = False) -> None:
    """Log `message: <safe_text(exc)>` without traceback (an expected, recorded failure).

    The raw exception text is only emitted at DEBUG, when `debug_detail` (LOG_PROMPTS) allows.
    """
    logger.log(level, f"{message}: {safe_text(exc)}")
    if debug_detail and has_sensitive_error(exc):
        logger.debug(f"{message}: {type(exc).__name__}: {exc}")
