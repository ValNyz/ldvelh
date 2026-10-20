"""The model calls of an evaluated scene: recorded, and answered live or from files (#154).

Every identity call of a scene goes through a `TappedProvider`, one per purpose, around
the provider the app would use for it. The tap records the exact request (model and wire
options, system, messages, tool) and the model's raw output, for the leak check (L) and
for the staged replay without an API key:

- live (`Tap(script=None)`): the call goes to the real provider, its usage is the API's;
- replay (`Tap(script=Script(...))`): the answer is the raw output a responder wrote
  for that request, `<token>.<n>.txt` next to `<token>.<n>.json` (n = 1, 2... in call
  order). The token is opaque (`request_token`, a hash of the scene id) and the request
  carries no scene id: corpus ids name their gold category, and a responder must have
  no way to see it. The scorer recomputes the token from the scene id. The calls of a scene are staged: the cascade's second call depends on the
  first answer. The first call without an answer writes its request file and makes the
  scene pending; it and every later call of the scene get a quiet answer (no mention), so
  the cascade ends without a warning, and the pending scene is not scored. An answer
  whose request file differs from the request the code now builds is stale (the prompt,
  the blocking or the model changed since): the scene is marked `stale` and answered
  quietly like a pending one (the cascade catches every provider error, so an exception
  would only read as a failed call), and the caller refuses to score.

Replayed usage is estimated: tokens ≈ characters / CHARS_PER_TOKEN (the repo's rough
estimate, services/game_service.py), priced by the session's usage ledger like a real
call. An answer to a tool request is read as the tool input (one JSON object, fences and
small defects repaired like any model JSON); anything else raises the provider's "no
tool_use block" ValueError, which the cascade counts as a failed call.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path

from llm.session import LLMSession, Purpose
from prompts.identity_prompt import SEPARATOR, format_handle
from services.llm_providers import CompletionResult, LLMProvider, LLMUsage, ToolResult
from utils import parse_json_response

CHARS_PER_TOKEN = 4
IDENTITY_PURPOSES = (Purpose.IDENTITY, Purpose.IDENTITY_STRONG)
# The answer of a call nobody answered yet: a valid, empty decision list.
QUIET_OUTPUT = '{"mentions": []}'
PENDING_INDEX = "pending.json"
TOKEN_CHARS = 12


def request_options(
    provider: LLMProvider, *, max_tokens: int, temperature: float, purpose: str
) -> dict:
    """Model and sampling options the provider puts on the wire for one request.
    Reads the provider's private `_request_options` (the exact wire options) when it has
    one, else the bare model and sampling options."""
    build = getattr(provider, "_request_options", None)
    if build is None:
        return {
            "model": provider.model_name(purpose),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    return build(max_tokens, temperature)


def dumps_request(request: dict) -> str:
    return json.dumps(request, ensure_ascii=False, indent=2) + "\n"


def request_token(scene_id: str) -> str:
    """The opaque name of a scene's request files (no gold category shows through)."""
    return hashlib.sha256(scene_id.encode("utf-8")).hexdigest()[:TOKEN_CHARS]


def estimate_tokens(text: str) -> int:
    return ceil(len(text) / CHARS_PER_TOKEN)


# --- the calls of a scene ----------------------------------------------------------------


@dataclass(frozen=True)
class Call:
    purpose: str
    request: dict
    output: str  # raw model output; QUIET_OUTPUT for a call nobody answered


@dataclass(frozen=True)
class Pending:
    """The first unanswered request of a scene."""

    path: Path
    purpose: str
    model: str


class Script:
    """The answers of one scene's calls in `directory`, read in call order."""

    def __init__(self, directory: Path, scene_id: str, *, write: bool = True) -> None:
        self.directory, self.token = directory, request_token(scene_id)
        self.write = write  # False: a pending call is noted, its request not written
        self.calls = 0
        self.pending: Pending | None = None
        self.stale: str | None = None  # the answer file written for another request

    def answer(self, request: dict) -> str | None:
        """The answer to the next call, or None (written as a request when it is the
        scene's first unanswered call)."""
        self.calls += 1
        if self.pending is not None or self.stale is not None:
            return None
        stem = f"{self.token}.{self.calls}"
        asked = self.directory / f"{stem}.json"
        answered = self.directory / f"{stem}.txt"
        text = dumps_request(request)
        if answered.is_file():
            if not asked.is_file() or asked.read_text(encoding="utf-8") != text:
                self.stale = answered.name
                return None
            return answered.read_text(encoding="utf-8")
        if self.write:
            self.directory.mkdir(parents=True, exist_ok=True)
            asked.write_text(text, encoding="utf-8")
        self.pending = Pending(asked, request["purpose"], request["model"])
        return None


@dataclass
class Tap:
    """The calls of one scene; `script` answers them (None: the live provider does)."""

    scene_id: str
    script: Script | None = None
    calls: list[Call] = field(default_factory=list)

    @property
    def pending(self) -> Pending | None:
        return self.script.pending if self.script is not None else None

    def card_lines(self) -> list[str]:
        """The candidate cards the scene's requests showed (lines led by a handle)."""
        return [line for line in self._lines() if _is_card(line)]

    def texts(self) -> list[str]:
        """The rest of what the scene sent to the models, and what they answered."""
        rest = [line for line in self._lines() if not _is_card(line)]
        return [*rest, *(call.output for call in self.calls)]

    def _lines(self) -> list[str]:
        return [
            line
            for call in self.calls
            for m in call.request["messages"]
            for line in m["content"].splitlines()
        ]


def _is_card(line: str) -> bool:
    head = line.split(SEPARATOR, 1)[0]
    number = head[1:]
    return number.isdigit() and head == format_handle(int(number))


def _input_text(request: dict) -> str:
    parts = [request["system"], *(m["content"] for m in request["messages"])]
    if "tools" in request:
        parts.append(json.dumps(request["tools"], ensure_ascii=False))
    return "\n".join(parts)


class TappedProvider(LLMProvider):
    """The provider of one purpose, its calls recorded on `tap` (see the module doc)."""

    def __init__(self, inner: LLMProvider, purpose: Purpose, tap: Tap) -> None:
        self.inner, self.purpose, self.tap = inner, purpose, tap
        self.MODEL_MAIN = inner.model_name(purpose.value)
        self.profile = inner.profile

    @property
    def provider_name(self) -> str:
        return self.inner.provider_name

    @property
    def supports_cache_control(self) -> bool:
        return self.inner.supports_cache_control

    @property
    def structured_output_mode(self):
        return self.inner.structured_output_mode

    def model_name(self, purpose: str) -> str:
        return self.inner.model_name(purpose)

    def _request(self, system, messages, temperature, max_tokens, **extra) -> dict:
        options = request_options(
            self.inner,
            max_tokens=max_tokens,
            temperature=temperature,
            purpose=self.purpose.value,
        )
        return {
            "call": len(self.tap.calls) + 1,
            "purpose": self.purpose.value,
            **options,
            "system": system,
            "messages": messages,
            **extra,
        }

    async def _call(self, request: dict, live: Callable, read: Callable):
        """(result, raw output) of a call, live or replayed, recorded on the tap."""
        if self.tap.script is None:
            result = await live()
            output = read(result)
        else:
            answer = self.tap.script.answer(request)
            output = QUIET_OUTPUT if answer is None else answer
            result = None
        self.tap.calls.append(Call(self.purpose.value, request, output))
        usage = LLMUsage(
            input_tokens=estimate_tokens(_input_text(request)),
            output_tokens=estimate_tokens(output),
        )
        return result, output, usage

    async def stream(self, system_prompt, messages, temperature, max_tokens):
        raise NotImplementedError("the identity decision makes no streamed call")
        yield  # pragma: no cover

    async def complete(self, system_prompt, messages, temperature, max_tokens):
        request = self._request(system_prompt, messages, temperature, max_tokens)
        result, output, usage = await self._call(
            request,
            lambda: self.inner.complete(
                system_prompt, messages, temperature, max_tokens
            ),
            lambda r: r.content,
        )
        return result or CompletionResult(content=output, usage=usage)

    async def complete_with_tools(
        self, system_prompt, messages, tools, tool_choice, temperature, max_tokens
    ):
        request = self._request(
            system_prompt,
            messages,
            temperature,
            max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        result, output, usage = await self._call(
            request,
            lambda: self.inner.complete_with_tools(
                system_prompt, messages, tools, tool_choice, temperature, max_tokens
            ),
            lambda r: json.dumps(r.tool_input, ensure_ascii=False),
        )
        if result is not None:
            return result
        tool_input = parse_json_response(output)
        if not isinstance(tool_input, dict):
            raise ValueError("No tool_use block in response")
        return ToolResult(
            tool_name=tools[0]["name"], tool_input=tool_input, usage=usage
        )

    async def complete_with_schema(
        self, system_prompt, messages, schema_name, schema, temperature, max_tokens
    ):
        request = self._request(
            system_prompt,
            messages,
            temperature,
            max_tokens,
            response_format={"name": schema_name, "schema": schema},
        )
        result, output, usage = await self._call(
            request,
            lambda: self.inner.complete_with_schema(
                system_prompt, messages, schema_name, schema, temperature, max_tokens
            ),
            lambda r: r.content,
        )
        return result or CompletionResult(content=output, usage=usage)


def tapped_session(providers: dict[Purpose, LLMProvider], tap: Tap) -> LLMSession:
    """A session whose identity calls go through `tap`, on the providers of `providers`
    (one per identity purpose)."""
    tapped = {p: TappedProvider(providers[p], p, tap) for p in IDENTITY_PURPOSES}
    return LLMSession.from_providers(tapped[Purpose.IDENTITY], tapped)


# --- a responses directory -----------------------------------------------------------------


class Responses:
    """The responses directory of one run: a script per scene, its pending requests."""

    def __init__(self, directory: Path, *, write: bool = True) -> None:
        self.directory, self.write = directory, write
        self.taps: dict[str, Tap] = {}

    def tap(self, scene_id: str) -> Tap:
        script = Script(self.directory, scene_id, write=self.write)
        self.taps[scene_id] = Tap(scene_id, script)
        return self.taps[scene_id]

    @property
    def pending(self) -> list[Pending]:
        return [t.pending for t in self.taps.values() if t.pending is not None]

    @property
    def stale(self) -> list[str]:
        """The answer files written for another request than the one now built."""
        scripts = [t.script for t in self.taps.values() if t.script is not None]
        return [s.stale for s in scripts if s.stale is not None]


def write_pending_index(root: Path, pending: list[Pending]) -> Path:
    """`<root>/pending.json`: one entry per pending request (file relative to `root`,
    purpose, model), what a dispatcher routes to its responder."""
    root.mkdir(parents=True, exist_ok=True)
    entries = [
        {
            "file": p.path.relative_to(root).as_posix(),
            "purpose": p.purpose,
            "model": p.model,
        }
        for p in pending
    ]
    path = root / PENDING_INDEX
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return path
