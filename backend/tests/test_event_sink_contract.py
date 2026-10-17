"""SSEWriter satisfies the pipeline's EventSink port: a renamed or reshaped method fails here."""

import inspect

import pytest

from api.streaming import SSEWriter
from pipeline.ports import EventSink

PORT_METHODS = sorted(
    name for name, member in vars(EventSink).items()
    if inspect.isfunction(member) and not name.startswith("_")
)


def _shape(func) -> list[tuple]:
    """Parameter names, defaults and kinds; annotations are left to the type checker."""
    return [(p.name, p.default, p.kind) for p in inspect.signature(func).parameters.values()]


def test_the_port_declares_methods():
    assert "send_error" in PORT_METHODS and "send_done" in PORT_METHODS


@pytest.mark.parametrize("name", PORT_METHODS)
def test_sse_writer_implements_every_port_method(name):
    implementation = getattr(SSEWriter, name, None)
    assert implementation is not None, f"SSEWriter has no {name}"
    assert inspect.iscoroutinefunction(implementation)
    assert _shape(implementation) == _shape(getattr(EventSink, name))
