"""Log exceptions without leaking story text.

A pydantic ValidationError embeds `input_value=` fragments of the validated payload (here:
the generated story) in its message and traceback. Anything logged at WARNING or above
describes such a cause by its field paths and error types only.
"""

import logging

from pydantic import ValidationError


def validation_summary(exc: ValidationError) -> str:
    """`ValidationError: errors=2 (time.new_time: missing; credit_delta: int_parsing)`."""
    errors = exc.errors(include_input=False, include_url=False, include_context=False)
    where = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['type']}"
                      for e in errors)
    return f"{exc.title}: errors={len(errors)} ({where})"


def _chain(exc: BaseException | None):
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def has_validation_error(exc: BaseException) -> bool:
    return any(isinstance(e, ValidationError) for e in _chain(exc))


def safe_repr(exc: BaseException) -> str:
    """`repr(exc)`, except that validation errors in the cause chain are summarised.

    Other exceptions of such a chain keep their text (`RuntimeError: db hiccup`).
    """
    if not has_validation_error(exc):
        return repr(exc)
    return " <- ".join(validation_summary(e) if isinstance(e, ValidationError)
                       else f"{type(e).__name__}: {e}" for e in _chain(exc))


def safe_text(exc: BaseException) -> str:
    """`str(exc)`, except that validation errors in the cause chain are summarised."""
    if not has_validation_error(exc):
        return str(exc)
    return safe_repr(exc)


def log_exception(logger: logging.Logger, level: int, message: str, exc: BaseException,
                  *, debug_detail: bool = False) -> None:
    """Log `message` with the traceback of `exc`, or its safe summary for validation causes.

    With a validation error in the chain, the full traceback (story fragments) is only
    emitted at DEBUG, and only when `debug_detail` (the LOG_PROMPTS setting) allows it.
    """
    if not has_validation_error(exc):
        logger.log(level, message, exc_info=exc)
        return
    logger.log(level, f"{message} [cause: {safe_repr(exc)}]")
    if debug_detail:
        logger.debug(message, exc_info=exc)
