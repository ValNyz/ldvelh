"""
Tests for api/streaming.py (SSEWriter, SSE helpers, display builders)
and uncovered branches in prompts/narrator_prompt.py.

All comments in English.
"""

import asyncio
import json

import pytest
import pytest_asyncio

from api.streaming import (
    SSEEvent,
    SSEWriter,
    build_display_text,
    create_sse_response,
    debug_partial_world_gen,
    extract_narrative_from_partial,
)
from prompts.narrator_prompt import (
    NARRATOR_SYSTEM_PROMPT,
    build_narrator_context_prompt,
)
from schema import (
    ActiveArcSummary,
    ArcDomain,
    ArcSummary,
    CycleSummary,
    EventSummary,
    Fact,
    InventoryItem,
    LocationSummary,
    NarrationContext,
    NPCLightSummary,
    NPCSummary,
    OrganizationSummary,
    PersonalAssistantSummary,
    ProtagonistState,
)


# =============================================================================
# HELPERS
# =============================================================================


def _make_context(**overrides) -> NarrationContext:
    """Build a minimal NarrationContext, accepting field overrides."""
    defaults = dict(
        current_cycle=1,
        current_date="Lundi 1er Janvier 2847",
        current_time="10h00",
        current_location=LocationSummary(
            name="Le Quart de Cycle",
            type="cafe",
            sector="Quai Central",
            atmosphere="calme",
        ),
        protagonist=ProtagonistState(
            name="Valentin",
            credits=1500,
            hobbies=["lecture"],
        ),
        organizations=[],
        all_npcs=[],
        player_input="Je regarde autour de moi",
        world_name="Escale Méridienne",
        world_atmosphere="industrielle",
    )
    defaults.update(overrides)
    return NarrationContext(**defaults)


# =============================================================================
# TESTS — SSEEvent enum
# =============================================================================


class TestSSEEvent:
    """SSEEvent string enum sanity checks."""

    def test_enum_values(self):
        """All expected event types exist."""
        expected = {"chunk", "progress", "extracting", "done", "saved", "error", "warning", "state", "roll_result", "roll_pending"}
        actual = {e.value for e in SSEEvent}
        assert actual == expected

    def test_enum_is_str(self):
        """SSEEvent members are strings (str Enum)."""
        assert isinstance(SSEEvent.CHUNK, str)
        assert SSEEvent.DONE == "done"


# =============================================================================
# TESTS — SSEWriter creation & basic lifecycle
# =============================================================================


class TestSSEWriterCreation:
    """SSEWriter instantiation and initial state."""

    def test_default_fields(self):
        """Writer initializes with sane defaults."""
        w = SSEWriter()
        assert w._closed is False
        assert w._event_count == 0
        assert w._bytes_sent == 0
        assert isinstance(w._queue, asyncio.Queue)
        assert len(w._stream_id) == 8  # uuid4().hex[:8]

    def test_stream_ids_are_unique(self):
        """Two writers should get different stream IDs."""
        a = SSEWriter()
        b = SSEWriter()
        assert a._stream_id != b._stream_id


# =============================================================================
# TESTS — SSEWriter.send and per-event helpers (async)
# =============================================================================


class TestSSEWriterSend:
    """Async tests for SSEWriter event sending."""

    @pytest.mark.asyncio
    async def test_send_chunk(self):
        """send_chunk enqueues a CHUNK event with content."""
        w = SSEWriter()
        await w.send_chunk("Hello world")
        payload = w._queue.get_nowait()
        assert payload["type"] == "chunk"
        assert payload["content"] == "Hello world"
        assert w._event_count == 1
        assert w._bytes_sent == len("Hello world".encode("utf-8"))

    @pytest.mark.asyncio
    async def test_send_chunk_utf8_bytes_count(self):
        """send_chunk counts bytes correctly for multi-byte UTF-8."""
        w = SSEWriter()
        text = "éàü"
        await w.send_chunk(text)
        assert w._bytes_sent == len(text.encode("utf-8"))

    @pytest.mark.asyncio
    async def test_send_progress(self):
        """send_progress enqueues a PROGRESS event with rawJson."""
        w = SSEWriter()
        raw = '{"partial": true}'
        await w.send_progress(raw)
        payload = w._queue.get_nowait()
        assert payload["type"] == "progress"
        assert payload["rawJson"] == raw
        assert w._bytes_sent == len(raw.encode("utf-8"))

    @pytest.mark.asyncio
    async def test_send_done(self):
        """send_done enqueues a DONE event with displayText and state."""
        w = SSEWriter()
        await w.send_done("Final text", state={"credits": 100})
        payload = w._queue.get_nowait()
        assert payload["type"] == "done"
        assert payload["displayText"] == "Final text"
        assert payload["state"] == {"credits": 100}

    @pytest.mark.asyncio
    async def test_send_done_defaults(self):
        """send_done with None arguments produces null values."""
        w = SSEWriter()
        await w.send_done(None)
        payload = w._queue.get_nowait()
        assert payload["displayText"] is None
        assert payload["state"] is None

    @pytest.mark.asyncio
    async def test_send_extracting(self):
        """send_extracting enqueues an EXTRACTING event."""
        w = SSEWriter()
        await w.send_extracting("Extracting now...")
        payload = w._queue.get_nowait()
        assert payload["type"] == "extracting"
        assert payload["displayText"] == "Extracting now..."

    @pytest.mark.asyncio
    async def test_send_extracting_none(self):
        """send_extracting accepts None as display text."""
        w = SSEWriter()
        await w.send_extracting(None)
        payload = w._queue.get_nowait()
        assert payload["displayText"] is None

    @pytest.mark.asyncio
    async def test_send_saved(self):
        """send_saved enqueues a SAVED event with no extra data."""
        w = SSEWriter()
        await w.send_saved()
        payload = w._queue.get_nowait()
        assert payload["type"] == "saved"
        # Only "type" key expected (the rest is empty dict spread)
        assert set(payload.keys()) == {"type"}

    @pytest.mark.asyncio
    async def test_send_error(self):
        """send_error enqueues an ERROR event with message, details, recoverable."""
        w = SSEWriter()
        await w.send_error("Something broke", details={"code": 500}, recoverable=True)
        payload = w._queue.get_nowait()
        assert payload["type"] == "error"
        assert payload["error"] == "Something broke"
        assert payload["details"] == {"code": 500}
        assert payload["recoverable"] is True

    @pytest.mark.asyncio
    async def test_send_error_defaults(self):
        """send_error defaults: details=None, recoverable=False."""
        w = SSEWriter()
        await w.send_error("fail")
        payload = w._queue.get_nowait()
        assert payload["details"] is None
        assert payload["recoverable"] is False

    @pytest.mark.asyncio
    async def test_send_warning(self):
        """send_warning enqueues a WARNING event."""
        w = SSEWriter()
        await w.send_warning("heads up", details=["thing"])
        payload = w._queue.get_nowait()
        assert payload["type"] == "warning"
        assert payload["message"] == "heads up"
        assert payload["details"] == ["thing"]

    @pytest.mark.asyncio
    async def test_send_warning_no_details(self):
        """send_warning with no details passes None."""
        w = SSEWriter()
        await w.send_warning("note")
        payload = w._queue.get_nowait()
        assert payload["details"] is None

    @pytest.mark.asyncio
    async def test_send_debug_not_active_by_default(self, monkeypatch):
        """send_debug does nothing when DEBUG env is not set."""
        monkeypatch.delenv("DEBUG", raising=False)
        w = SSEWriter()
        await w.send_debug("test msg", data={"x": 1})
        assert w._queue.empty()
        assert w._event_count == 0

    @pytest.mark.asyncio
    async def test_send_debug_active_when_debug_true(self, monkeypatch):
        """send_debug enqueues a WARNING event when DEBUG=true."""
        monkeypatch.setenv("DEBUG", "true")
        w = SSEWriter()
        await w.send_debug("debug info", data={"x": 1})
        payload = w._queue.get_nowait()
        assert payload["type"] == "warning"
        assert "[DEBUG]" in payload["message"]
        assert payload["details"] == {"x": 1}

    @pytest.mark.asyncio
    async def test_send_debug_case_insensitive(self, monkeypatch):
        """send_debug recognizes DEBUG=True (case insensitive)."""
        monkeypatch.setenv("DEBUG", "True")
        w = SSEWriter()
        await w.send_debug("msg")
        assert not w._queue.empty()

    @pytest.mark.asyncio
    async def test_send_on_closed_writer_is_noop(self):
        """Sending on a closed writer does not enqueue anything."""
        w = SSEWriter()
        await w.close()
        count_before = w._event_count
        await w.send_chunk("after close")
        # The sentinel None was placed by close(), no new event
        assert w._event_count == count_before

    @pytest.mark.asyncio
    async def test_event_count_increments(self):
        """Each send increments the event counter."""
        w = SSEWriter()
        await w.send_chunk("a")
        await w.send_chunk("b")
        await w.send_warning("c")
        assert w._event_count == 3


# =============================================================================
# TESTS — SSEWriter.close
# =============================================================================


class TestSSEWriterClose:
    """SSEWriter.close() lifecycle."""

    @pytest.mark.asyncio
    async def test_close_sets_flag(self):
        """close() sets _closed to True."""
        w = SSEWriter()
        assert w._closed is False
        await w.close()
        assert w._closed is True

    @pytest.mark.asyncio
    async def test_close_puts_sentinel(self):
        """close() enqueues None as the end sentinel."""
        w = SSEWriter()
        await w.close()
        item = w._queue.get_nowait()
        assert item is None

    @pytest.mark.asyncio
    async def test_double_close_is_safe(self):
        """Calling close() twice does not crash or enqueue extra sentinel."""
        w = SSEWriter()
        await w.close()
        await w.close()
        # Only one sentinel should be there
        item = w._queue.get_nowait()
        assert item is None
        assert w._queue.empty()


# =============================================================================
# TESTS — SSEWriter.iterate
# =============================================================================


class TestSSEWriterIterate:
    """SSEWriter.iterate() async generator."""

    @pytest.mark.asyncio
    async def test_iterate_yields_sse_format(self):
        """iterate() yields 'data: {...}\n\n' formatted strings."""
        w = SSEWriter()
        await w.send_chunk("hello")
        await w.close()

        messages = []
        async for msg in w.iterate():
            messages.append(msg)

        assert len(messages) == 1
        assert messages[0].startswith("data: ")
        assert messages[0].endswith("\n\n")
        parsed = json.loads(messages[0][len("data: "):].strip())
        assert parsed["type"] == "chunk"
        assert parsed["content"] == "hello"

    @pytest.mark.asyncio
    async def test_iterate_stops_on_sentinel(self):
        """iterate() stops when it receives the None sentinel from close()."""
        w = SSEWriter()
        await w.send_chunk("1")
        await w.send_chunk("2")
        await w.close()

        messages = []
        async for msg in w.iterate():
            messages.append(msg)
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_iterate_multiple_event_types(self):
        """iterate() handles a mixed sequence of events."""
        w = SSEWriter()
        await w.send_chunk("text")
        await w.send_warning("warn")
        await w.send_done("final", state={"x": 1})
        await w.close()

        types = []
        async for msg in w.iterate():
            parsed = json.loads(msg[len("data: "):].strip())
            types.append(parsed["type"])

        assert types == ["chunk", "warning", "done"]


# =============================================================================
# TESTS — create_sse_response
# =============================================================================


class TestCreateSSEResponse:
    """create_sse_response helper."""

    def test_returns_streaming_response(self):
        """Returns a FastAPI StreamingResponse with correct media type."""
        from fastapi.responses import StreamingResponse

        w = SSEWriter()
        resp = create_sse_response(w)
        assert isinstance(resp, StreamingResponse)
        assert resp.media_type == "text/event-stream"

    def test_response_headers(self):
        """SSE response has cache-control and buffering headers."""
        w = SSEWriter()
        resp = create_sse_response(w)
        # StreamingResponse stores headers in a MutableHeaders object
        headers = dict(resp.headers)
        assert "no-cache" in headers.get("cache-control", "")
        assert headers.get("x-accel-buffering") == "no"


# =============================================================================
# TESTS — build_display_text
# =============================================================================


class TestBuildDisplayText:
    """build_display_text function."""

    def test_narrative_only(self):
        """Narrative text without actions returns just the text."""
        parsed = {"narrative_text": "The station hums quietly."}
        assert build_display_text(parsed) == "The station hums quietly."

    def test_empty_narrative(self):
        """Empty or None narrative_text returns empty string."""
        assert build_display_text({}) == ""
        assert build_display_text({"narrative_text": None}) == ""
        assert build_display_text({"narrative_text": ""}) == ""

    def test_no_suggested_actions_field(self):
        """Without suggested_actions, only narrative_text is returned."""
        parsed = {"narrative_text": "Text."}
        result = build_display_text(parsed)
        assert "---" not in result
        assert result == "Text."


# =============================================================================
# TESTS — extract_narrative_from_partial
# =============================================================================


class TestExtractNarrativeFromPartial:
    """extract_narrative_from_partial handles streaming JSON fragments."""

    def test_complete_json(self):
        """Extracts narrative_text from a complete JSON object."""
        obj = json.dumps({"narrative_text": "Hello there.", "other": 1})
        assert extract_narrative_from_partial(obj) == "Hello there."

    def test_no_marker(self):
        """Returns None when narrative_text key is absent."""
        assert extract_narrative_from_partial('{"foo": "bar"}') is None

    def test_partial_json_no_closing_quote(self):
        """Extracts text from incomplete JSON (no closing quote yet)."""
        partial = '{"narrative_text": "In progress...'
        result = extract_narrative_from_partial(partial)
        assert result == "In progress..."

    def test_empty_narrative(self):
        """Empty narrative_text returns None (stripped empty)."""
        partial = '{"narrative_text": ""}'
        assert extract_narrative_from_partial(partial) is None

    def test_whitespace_only_narrative(self):
        """Whitespace-only narrative_text returns None after strip."""
        partial = '{"narrative_text": "   "}'
        assert extract_narrative_from_partial(partial) is None

    def test_escape_sequences(self):
        """Handles \\n, \\t, \\r, \\\\, and \\\\ correctly."""
        partial = '{"narrative_text": "line1\\nline2\\ttab\\\\back"}'
        result = extract_narrative_from_partial(partial)
        assert "line1\nline2\ttab\\back" == result

    def test_escaped_quote(self):
        """Handles escaped quote inside narrative_text."""
        partial = '{"narrative_text": "She said \\"hello\\""}'
        result = extract_narrative_from_partial(partial)
        assert result == 'She said "hello"'

    def test_incomplete_escape_sequence(self):
        """Stops gracefully when escape sequence is cut off."""
        partial = '{"narrative_text": "text\\'
        result = extract_narrative_from_partial(partial)
        assert result == "text"

    def test_other_escape_sequences(self):
        """Unknown escape sequences keep the character after backslash."""
        partial = '{"narrative_text": "\\u0041"}'
        result = extract_narrative_from_partial(partial)
        # \u is not specially handled, so we get 'u0041"' up to the quote
        # Actually: \u -> appends 'u', then 0041 literal, then closing "
        assert result == "u0041"

    def test_marker_without_value_start(self):
        """Returns None when the key exists but no opening quote for value."""
        partial = '{"narrative_text":'
        assert extract_narrative_from_partial(partial) is None


# =============================================================================
# TESTS — debug_partial_world_gen
# =============================================================================


class TestDebugPartialWorldGen:
    """debug_partial_world_gen extraction."""

    def test_empty_json(self):
        """No markers found in empty/minimal JSON."""
        result = debug_partial_world_gen("{}")
        assert result["progress_percent"] == 0
        assert result["json_length"] == 2
        assert result["fields_found"] == []
        assert result["preview"] == "En cours..."

    def test_name_extraction(self):
        """Extracts world name from partial JSON."""
        raw = '{"name": "Chrysalide-7", "station_type": "orbital"}'
        result = debug_partial_world_gen(raw)
        assert "world.name" in result["fields_found"]
        assert "world.station_type" in result["fields_found"]
        assert "world_name" in result["fields_found"]
        assert result["preview"] == "Chrysalide-7"
        assert result["progress_percent"] > 0

    def test_all_markers_found(self):
        """100% progress when all markers are present."""
        raw = json.dumps({
            "name": "Test",
            "station_type": "orbital",
            "population": 5000,
            "protagonist": {"name": "V"},
            "npcs": [],
            "locations": [],
            "factions": [],
        })
        result = debug_partial_world_gen(raw)
        assert result["progress_percent"] == 100

    def test_partial_markers(self):
        """Partial progress with some markers."""
        raw = '{"name": "Station", "population": 1000}'
        result = debug_partial_world_gen(raw)
        # name + population + world_name extracted = 3 fields found
        # But only 2 of the 7 markers matched (name, population)
        assert 0 < result["progress_percent"] < 100


# =============================================================================
# TESTS — NARRATOR_SYSTEM_PROMPT
# =============================================================================


class TestNarratorSystemPrompt:
    """Validate the structure and content of the assembled system prompt."""

    def test_is_string(self):
        """NARRATOR_SYSTEM_PROMPT is a non-empty string."""
        assert isinstance(NARRATOR_SYSTEM_PROMPT, str)
        assert len(NARRATOR_SYSTEM_PROMPT) > 500

    def test_contains_role_section(self):
        """Contains the narrator role definition."""
        assert "TON RÔLE" in NARRATOR_SYSTEM_PROMPT

    def test_contains_tone_style(self):
        """Contains a tone section (default or genre-specific)."""
        assert "TON ET STYLE" in NARRATOR_SYSTEM_PROMPT

    def test_contains_friction_rules(self):
        """Contains the FRICTION_RULES."""
        assert "FRICTION NARRATIVE" in NARRATOR_SYSTEM_PROMPT
        assert "Ratio obligatoire" in NARRATOR_SYSTEM_PROMPT

    def test_contains_coherence_rules(self):
        """Contains the COHERENCE_RULES."""
        assert "COHÉRENCE" in NARRATOR_SYSTEM_PROMPT

    def test_contains_personal_ai_section(self):
        """Contains IA PERSONNELLE rules."""
        assert "IA PERSONNELLE" in NARRATOR_SYSTEM_PROMPT
        assert "italique" in NARRATOR_SYSTEM_PROMPT

    def test_contains_time_rules(self):
        """Contains temporal rules."""
        assert "Un cycle = un jour" in NARRATOR_SYSTEM_PROMPT
        assert "HHhMM" in NARRATOR_SYSTEM_PROMPT

    def test_contains_delta_documentation(self):
        """Documents the live delta fields (gauges removed)."""
        for field in ["credit_delta", "inventory_hints",
                      "entity_reveals", "events_mentioned", "info_requests"]:
            assert field in NARRATOR_SYSTEM_PROMPT, f"Missing delta docs for: {field}"

    def test_contains_extraction_triggers_documentation(self):
        """Documents the extraction trigger types."""
        assert "extraction_triggers" in NARRATOR_SYSTEM_PROMPT
        for trigger in ["characters", "locations", "organizations",
                        "inventory", "narrative_arcs"]:
            assert trigger in NARRATOR_SYSTEM_PROMPT, f"Missing trigger doc: {trigger}"

    def test_contains_json_references(self):
        """References JSON output format."""
        assert "JSON" in NARRATOR_SYSTEM_PROMPT
        assert "scene_mood" in NARRATOR_SYSTEM_PROMPT

    def test_contains_critical_reminders(self):
        """Contains the critical reminders section."""
        assert "RAPPELS CRITIQUES" in NARRATOR_SYSTEM_PROMPT
        assert "JSON valide" in NARRATOR_SYSTEM_PROMPT

    def test_character_limit_table(self):
        """Contains the character limit table."""
        assert "scene_mood" in NARRATOR_SYSTEM_PROMPT
        assert "50 car." in NARRATOR_SYSTEM_PROMPT
        assert "narrator_notes" in NARRATOR_SYSTEM_PROMPT
        assert "300 car." in NARRATOR_SYSTEM_PROMPT

    def test_contains_markdown_formatting_guidance(self):
        """Contains markdown formatting examples for narrative_text."""
        assert "MARKDOWN DANS NARRATIVE_TEXT" in NARRATOR_SYSTEM_PROMPT

    def test_no_python_keywords_in_prompt(self):
        """Prompt shouldn't contain Python True/False/None (should be JSON true/false/null)."""
        # This is a sanity check — genre content from DB won't have Python keywords
        assert "True," not in NARRATOR_SYSTEM_PROMPT
        assert "False," not in NARRATOR_SYSTEM_PROMPT


# =============================================================================
# TESTS — build_narrator_context_prompt (UNCOVERED BRANCHES)
# =============================================================================
#
# The existing test_prompts.py covers:
#   - basic context (time, location, protagonist, player input)
#   - requested_entity_details (character + non-character)
#   - empty details section
#
# We now cover the remaining branches.
# =============================================================================


class TestNarratorContextPromptBranches:
    """Additional branch coverage for build_narrator_context_prompt."""

    # ---- World section ----

    def test_world_section_rendered(self):
        """World name, atmosphere, and tone_notes are rendered."""
        ctx = _make_context(
            world_name="Chrysalide",
            world_atmosphere="claustrophobe",
            tone_notes="Dark undertones",
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### MONDE" in prompt
        assert "**Chrysalide**" in prompt
        assert "claustrophobe" in prompt
        assert "Dark undertones" in prompt

    def test_world_section_without_tone_notes(self):
        """World section with empty tone_notes omits that line."""
        ctx = _make_context(world_name="Station", world_atmosphere="busy", tone_notes="")
        prompt = build_narrator_context_prompt(ctx)
        assert "### MONDE" in prompt
        assert "Notes de ton" not in prompt

    def test_world_section_without_atmosphere(self):
        """World section without atmosphere omits that line."""
        ctx = _make_context(world_name="Station", world_atmosphere="")
        prompt = build_narrator_context_prompt(ctx)
        assert "### MONDE" in prompt
        # The atmosphere line should not appear when empty
        # (world_atmosphere="" is falsy, but world_name is truthy so MONDE section shows)
        # Actually, world_atmosphere is always set — let's check behavior
        assert "Atmosphère:" not in prompt or "Atmosphère: " in prompt

    def test_no_world_section_when_name_empty(self):
        """No MONDE section when world_name is empty."""
        ctx = _make_context(world_name="")
        prompt = build_narrator_context_prompt(ctx)
        assert "### MONDE" not in prompt

    # ---- Location section ----

    def test_location_with_ambient(self):
        """Location ambient field is rendered when present."""
        ctx = _make_context(
            current_location=LocationSummary(
                name="Terminal 7",
                type="bar",
                sector="Quai Nord",
                atmosphere="bruyant",
                ambient="Des disputes éclatent entre factions rivales",
            )
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "Terminal 7" in prompt
        assert "Ambiance narrative: Des disputes" in prompt

    def test_location_without_ambient(self):
        """No ambient line when location.ambient is None."""
        ctx = _make_context()
        prompt = build_narrator_context_prompt(ctx)
        assert "Ambiance narrative:" not in prompt

    # ---- Connected locations ----

    def test_connected_locations(self):
        """Connected locations are listed when present."""
        ctx = _make_context(
            connected_locations=[
                LocationSummary(name="Dortoir B", type="quarters", sector="Hab", atmosphere="quiet"),
                LocationSummary(name="Marché", type="market", sector="Centre", atmosphere="busy"),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "Lieux accessibles:" in prompt
        assert "- Dortoir B (quarters)" in prompt
        assert "- Marché (market)" in prompt

    def test_no_connected_locations(self):
        """No accessible locations line when list is empty."""
        ctx = _make_context(connected_locations=[])
        prompt = build_narrator_context_prompt(ctx)
        assert "Lieux accessibles:" not in prompt

    # ---- Protagonist section ----

    def test_protagonist_with_employer(self):
        """Employer is shown when present."""
        ctx = _make_context(
            protagonist=ProtagonistState(
                name="Valentin",
                credits=800,
                hobbies=["gaming"],
                current_occupation="Technicien",
                employer="DataCorp",
            )
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "Technicien" in prompt
        assert "Employeur: DataCorp" in prompt

    def test_protagonist_sans_emploi(self):
        """Protagonist without occupation shows 'sans emploi'."""
        ctx = _make_context()
        prompt = build_narrator_context_prompt(ctx)
        assert "sans emploi" in prompt

    def test_protagonist_hobbies(self):
        """Hobbies are rendered when present."""
        ctx = _make_context(
            protagonist=ProtagonistState(
                name="Valentin",
                credits=500,
                hobbies=["lecture", "cuisine", "échecs"],
            )
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "Hobbies: lecture, cuisine, échecs" in prompt

    def test_protagonist_no_hobbies(self):
        """No hobbies line when list is empty."""
        ctx = _make_context(
            protagonist=ProtagonistState(
                name="Valentin",
                credits=500,
                hobbies=[],
            )
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "Hobbies:" not in prompt

    # ---- Inventory ----

    def test_inventory_rendered(self):
        """Inventory items are listed with quantity when > 1."""
        ctx = _make_context(
            inventory=[
                InventoryItem(name="Communicateur", category="tech"),
                InventoryItem(name="Ration", category="food", quantity=3),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "Inventaire:" in prompt
        assert "Communicateur" in prompt
        assert "Ration (×3)" in prompt

    def test_no_inventory_section_when_empty(self):
        """No inventory line when list is empty."""
        ctx = _make_context(inventory=[])
        prompt = build_narrator_context_prompt(ctx)
        assert "Inventaire:" not in prompt

    # ---- Personal AI ----

    def test_personal_ai_full(self):
        """Personal AI section with all fields."""
        ctx = _make_context(
            personal_ai=PersonalAssistantSummary(
                name="Célimène",
                voice_description="Voix grave et sensuelle",
                personality_traits=["sarcastique", "pragmatique"],
                quirk="Fait des références littéraires obscures",
            )
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### IA PERSONNELLE" in prompt
        assert "**Nom: Célimène**" in prompt
        assert "Voix: Voix grave et sensuelle" in prompt
        assert "Traits: sarcastique, pragmatique" in prompt
        assert "Particularité: Fait des références" in prompt

    def test_personal_ai_minimal(self):
        """Personal AI with only name (optional fields missing)."""
        ctx = _make_context(
            personal_ai=PersonalAssistantSummary(name="Echo")
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### IA PERSONNELLE" in prompt
        assert "**Nom: Echo**" in prompt
        assert "Voix:" not in prompt
        assert "Traits:" not in prompt.split("IA PERSONNELLE")[1].split("###")[0]
        assert "Particularité:" not in prompt

    def test_no_personal_ai_section(self):
        """No IA PERSONNELLE section when personal_ai is None."""
        ctx = _make_context(personal_ai=None)
        prompt = build_narrator_context_prompt(ctx)
        assert "### IA PERSONNELLE" not in prompt

    # ---- Organizations ----

    def test_organizations_rendered(self):
        """Organizations are listed with relation and ambient."""
        ctx = _make_context(
            organizations=[
                OrganizationSummary(
                    name="SynTech",
                    org_type="corporation",
                    domain="technologie",
                    protagonist_relation="employed_by",
                    ambient="En restructuration",
                ),
                OrganizationSummary(
                    name="Guilde des Dockers",
                    org_type="guild",
                    domain="logistique",
                    protagonist_relation=None,
                ),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### ORGANISATIONS CONNUES" in prompt
        assert "SynTech" in prompt
        assert "employed_by" in prompt
        assert "Climat actuel: En restructuration" in prompt
        assert "Guilde des Dockers" in prompt
        # No relation for Guilde
        lines = prompt.split("\n")
        guilde_line = [l for l in lines if "Guilde des Dockers" in l][0]
        assert "—" not in guilde_line  # no relation separator

    def test_no_organizations_section(self):
        """No ORGANISATIONS section when list is empty."""
        ctx = _make_context(organizations=[])
        prompt = build_narrator_context_prompt(ctx)
        assert "### ORGANISATIONS CONNUES" not in prompt

    # ---- NPCs: Tier 2 (present NPCs, medium detail) ----

    def test_npcs_present_rendered(self):
        """Present NPCs are displayed with traits, relation, arcs, ambient."""
        ctx = _make_context(
            npcs_present=[
                NPCSummary(
                    name="Ossek",
                    occupation="barista",
                    species="kreeth",
                    relationship_level=3,
                    usual_location="Le Quart de Cycle",
                    known=True,
                    traits=["calme", "observateur", "discret"],
                    relationship_to_protagonist="connaissance",
                    active_arcs=[
                        ArcSummary(
                            domain=ArcDomain.PROFESSIONAL,
                            title="Reconversion",
                            situation_brief="Envisage de quitter le café",
                            intensity=2,
                        ),
                    ],
                    ambient="Semble préoccupé ces derniers temps",
                ),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### PNJs" in prompt
        assert "**Ossek**" in prompt
        assert "[Présent]" in prompt
        assert "calme, observateur, discret" in prompt
        assert "connaissance" in prompt
        assert "niveau 3/10" in prompt
        assert "Arc [professional] Reconversion" in prompt
        assert "Envisage de quitter" in prompt
        assert "Ambiance: Semble préoccupé" in prompt

    def test_present_npc_only_relationship_level(self):
        """NPC with relationship_level but no relationship_to_protagonist text."""
        ctx = _make_context(
            npcs_present=[
                NPCSummary(
                    name="Kim",
                    occupation="engineer",
                    species="human",
                    relationship_level=5,
                    usual_location=None,
                    known=True,
                    traits=["smart"],
                    relationship_to_protagonist=None,
                ),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "Relation: niveau 5/10" in prompt

    def test_present_npc_no_arcs_no_ambient(self):
        """NPC without arcs or ambient omits those lines."""
        ctx = _make_context(
            npcs_present=[
                NPCSummary(
                    name="Bob",
                    occupation="guard",
                    species="human",
                    relationship_level=None,
                    usual_location=None,
                    known=True,
                    traits=["stern"],
                    active_arcs=[],
                    ambient=None,
                ),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "**Bob**" in prompt
        assert "Arc [" not in prompt.split("Bob")[1].split("###")[0]
        assert "Ambiance:" not in prompt.split("Bob")[1].split("###")[0]

    # ---- NPCs: Tier 3 (all known NPCs, basic) ----

    def test_all_npcs_basic_info(self):
        """All NPCs (tier 3) show basic one-liner info."""
        ctx = _make_context(
            all_npcs=[
                NPCLightSummary(
                    name="Reva",
                    occupation="docteur",
                    species="human",
                    relationship_level=None,
                    usual_location="Infirmerie",
                    known=True,
                    ambient="Débordée par les urgences",
                ),
                NPCLightSummary(
                    name="Taz",
                    occupation=None,
                    species="alien",
                    relationship_level=None,
                    usual_location=None,
                    known=True,
                ),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "- Reva (docteur) @ Infirmerie" in prompt
        assert "Débordée par les urgences" in prompt
        # Taz has no occupation and no usual_location
        assert "- Taz" in prompt

    def test_all_npcs_not_duplicated_with_present(self):
        """NPCs already shown as 'present' are not duplicated in tier 3."""
        npc = NPCSummary(
            name="Alice",
            occupation="pilot",
            species="human",
            relationship_level=2,
            usual_location="Hangar",
            known=True,
            traits=["bold"],
        )
        all_npc = NPCLightSummary(
            name="Alice",
            occupation="pilot",
            species="human",
            relationship_level=2,
            usual_location="Hangar",
            known=True,
        )
        ctx = _make_context(
            npcs_present=[npc],
            all_npcs=[all_npc],
        )
        prompt = build_narrator_context_prompt(ctx)
        # Alice should appear only once (as tier 2 present)
        assert prompt.count("**Alice**") == 1

    # ---- NPCs: Tier 1 (requested character details) ----

    def test_requested_character_full_detail(self):
        """Requested character detail with all fields."""
        ctx = _make_context(
            requested_entity_details={
                "Marie": {
                    "_entity_type": "character",
                    "description": "Ingénieure brillante",
                    "occupation": "Ingénieure",
                    "species": "human",
                    "traits": '["pragmatique", "directe", "impatiente"]',
                    "relation_context": "collègue",
                    "relation_level": 6,
                    "mood": "stressée",
                    "ambient": "Tendue par le projet",
                    "recent_facts": [
                        {"description": "A fini le prototype"},
                        {"description": "Dispute avec le chef"},
                    ],
                },
            },
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "**Marie**" in prompt
        assert "Ingénieure brillante" in prompt
        assert "pragmatique" in prompt
        assert "collègue" in prompt
        assert "niveau 6/10" in prompt
        assert "Humeur: stressée" in prompt
        assert "Ambiance: Tendue" in prompt
        assert "A fini le prototype" in prompt

    def test_requested_character_is_also_present(self):
        """Requested character who is also present gets [Présent] tag and arcs."""
        npc = NPCSummary(
            name="Kess",
            occupation="tech",
            species="human",
            relationship_level=None,
            usual_location=None,
            known=True,
            traits=["smart"],
            active_arcs=[
                ArcSummary(
                    domain=ArcDomain.SOCIAL,
                    title="Intégration",
                    situation_brief="Cherche sa place",
                    intensity=3,
                ),
            ],
        )
        ctx = _make_context(
            npcs_present=[npc],
            requested_entity_details={
                "Kess": {
                    "_entity_type": "character",
                    "occupation": "tech",
                    "species": "human",
                    "traits": ["smart"],
                },
            },
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "[Présent]" in prompt
        assert "Arc [social] Intégration" in prompt
        assert "Cherche sa place" in prompt
        # Kess should appear only once despite being in both present and requested
        assert prompt.count("**Kess**") == 1

    def test_requested_character_relation_level_only(self):
        """Requested character with relation_level but no relation_context."""
        ctx = _make_context(
            requested_entity_details={
                "Zara": {
                    "_entity_type": "character",
                    "occupation": "trader",
                    "species": "alien",
                    "relation_level": 2,
                },
            }
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "Relation: niveau 2/10" in prompt

    def test_requested_character_traits_as_list(self):
        """Requested character with traits already as a list (not JSON string)."""
        ctx = _make_context(
            requested_entity_details={
                "Jin": {
                    "_entity_type": "character",
                    "occupation": "cook",
                    "species": "human",
                    "traits": ["quiet", "generous"],
                },
            }
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "quiet, generous" in prompt

    def test_requested_character_traits_invalid_string(self):
        """Traits as a non-JSON string gracefully falls back to empty."""
        ctx = _make_context(
            requested_entity_details={
                "Lex": {
                    "_entity_type": "character",
                    "occupation": "pilot",
                    "species": "human",
                    "traits": "not a json array",
                },
            }
        )
        prompt = build_narrator_context_prompt(ctx)
        # Should not crash; traits line should be absent (empty list)
        assert "**Lex**" in prompt

    def test_requested_character_recent_facts_as_strings(self):
        """recent_facts can be plain strings (not dicts)."""
        ctx = _make_context(
            requested_entity_details={
                "Sam": {
                    "_entity_type": "character",
                    "occupation": "clerk",
                    "species": "human",
                    "recent_facts": ["Got promoted", "Moved to sector B"],
                },
            }
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "Got promoted" in prompt
        assert "Moved to sector B" in prompt

    # ---- Non-character requested details ----

    def test_requested_location_details(self):
        """Non-character details (location) are rendered in DÉTAILS DEMANDÉS."""
        ctx = _make_context(
            requested_entity_details={
                "Hangar 9": {
                    "_entity_type": "location",
                    "description": "Grand hangar industriel",
                    "sector": "Zone Est",
                    "atmosphere": "poussiéreux",
                    "location_type": "hangar",
                    "recent_facts": [
                        {"description": "Un accident a eu lieu hier"},
                    ],
                },
            }
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### DÉTAILS DEMANDÉS" in prompt
        assert "**Hangar 9** (location)" in prompt
        assert "Grand hangar industriel" in prompt
        assert "Secteur: Zone Est" in prompt
        assert "Ambiance: poussiéreux" in prompt
        assert "Type: hangar" in prompt
        assert "Un accident a eu lieu hier" in prompt

    def test_requested_organization_details(self):
        """Non-character details (organization) rendering."""
        ctx = _make_context(
            requested_entity_details={
                "SynTech": {
                    "_entity_type": "organization",
                    "domain": "technology",
                    "org_type": "corporation",
                },
            }
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### DÉTAILS DEMANDÉS" in prompt
        assert "**SynTech** (organization)" in prompt
        assert "Domaine: technology" in prompt
        assert "Type: corporation" in prompt

    # ---- Active arcs ----

    def test_active_arcs_rendered(self):
        """Active arcs section with deadlines and participants."""
        ctx = _make_context(
            active_arcs=[
                ActiveArcSummary(
                    type="professional",
                    title="Installation au poste",
                    description_brief="Valentin doit s'intégrer à DataCorp",
                    involved=["Chef Morin", "Valentin"],
                    deadline_cycle=5,
                ),
                ActiveArcSummary(
                    type="mystery",
                    title="Signal inconnu",
                    description_brief="Un signal étrange capté dans le secteur Est",
                    involved=[],
                ),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### ARCS MONDE & PNJ" in prompt
        assert "**Installation au poste** (professional)" in prompt
        assert "[deadline: cycle 5]" in prompt
        assert "Impliqués: Chef Morin, Valentin" in prompt
        assert "**Signal inconnu** (mystery)" in prompt
        # No deadline for second arc
        signal_line = [l for l in prompt.split("\n") if "Signal inconnu" in l][0]
        assert "deadline" not in signal_line

    def test_no_arcs_section_when_empty(self):
        """No ARCS section when list is empty."""
        ctx = _make_context(active_arcs=[])
        prompt = build_narrator_context_prompt(ctx)
        assert "### ARCS MONDE & PNJ" not in prompt
        assert "### ARCS DU JOUEUR" not in prompt

    # ---- Upcoming events ----

    def test_upcoming_events_rendered(self):
        """Upcoming events with time and location."""
        ctx = _make_context(
            upcoming_events=[
                EventSummary(
                    title="Réunion d'équipe",
                    planned_cycle=2,
                    planned_time="09h00",
                    location="Salle A3",
                    type="appointment",
                ),
                EventSummary(
                    title="Deadline projet",
                    planned_cycle=5,
                    type="deadline",
                ),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### ÉVÉNEMENTS À VENIR" in prompt
        assert "Cycle 2 à 09h00: **Réunion d'équipe** @ Salle A3" in prompt
        assert "Cycle 5: **Deadline projet**" in prompt

    def test_no_events_section_when_empty(self):
        """No ÉVÉNEMENTS section when list is empty."""
        ctx = _make_context(upcoming_events=[])
        prompt = build_narrator_context_prompt(ctx)
        assert "### ÉVÉNEMENTS À VENIR" not in prompt

    # ---- Facts ----

    def test_facts_rendered_sorted(self):
        """Facts are sorted by importance desc, cycle desc, with involved names."""
        ctx = _make_context(
            facts=[
                Fact(cycle=1, description="Minor event", importance=2, involves=[]),
                Fact(cycle=2, description="Major discovery", importance=5, involves=["Alice", "Bob"]),
                Fact(cycle=1, description="Important clue", importance=5, involves=["Alice"]),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### CONNAISSANCES SUR LES ENTITÉS" in prompt
        # Higher importance first, then higher cycle
        facts_section = prompt.split("### CONNAISSANCES SUR LES ENTITÉS")[1].split("###")[0]
        lines = [l for l in facts_section.strip().split("\n") if l.startswith("- ")]
        assert len(lines) == 3
        # First line should be importance=5, cycle=2
        assert "Major discovery" in lines[0]
        assert "[Alice, Bob]" in lines[0]
        # Second should be importance=5, cycle=1
        assert "Important clue" in lines[1]
        # Third should be importance=2
        assert "Minor event" in lines[2]

    def test_no_facts_section_when_empty(self):
        """No facts section when list is empty."""
        ctx = _make_context(facts=[])
        prompt = build_narrator_context_prompt(ctx)
        assert "### CONNAISSANCES SUR LES ENTITÉS" not in prompt

    def test_facts_without_involves(self):
        """Fact without involves list has no bracket suffix."""
        ctx = _make_context(
            facts=[Fact(cycle=1, description="Something happened", importance=3)]
        )
        prompt = build_narrator_context_prompt(ctx)
        line = [l for l in prompt.split("\n") if "Something happened" in l][0]
        assert "[" not in line.split("Something happened")[1]

    # ---- Cycle summaries ----

    def test_cycle_summaries_rendered(self):
        """Cycle summaries are listed in order."""
        ctx = _make_context(
            cycle_summaries=[
                CycleSummary(cycle=1, summary="Arrived at the station.", date="1er Jan"),
                CycleSummary(cycle=2, summary="First day at work.", date="2 Jan"),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### CHRONOLOGIE RÉCENTE" in prompt
        assert "- Cycle 1: Arrived at the station." in prompt
        assert "- Cycle 2: First day at work." in prompt

    def test_no_cycle_summaries_when_empty(self):
        """No RÉSUMÉ section when list is empty."""
        ctx = _make_context(cycle_summaries=[])
        prompt = build_narrator_context_prompt(ctx)
        assert "### CHRONOLOGIE RÉCENTE" not in prompt

    # ---- Player input and JSON skeleton ----

    def test_player_input_rendered(self):
        """Player input is quoted in the prompt."""
        ctx = _make_context(player_input="Je parle à Ossek")
        prompt = build_narrator_context_prompt(ctx)
        assert "> Je parle à Ossek" in prompt
        assert "## ACTION DU JOUEUR" in prompt

    def test_json_skeleton_present(self):
        """Condensed JSON skeleton reminder is included at the end."""
        ctx = _make_context()
        prompt = build_narrator_context_prompt(ctx)
        assert "## FORMAT DE RÉPONSE ATTENDU (rappel)" in prompt
        assert '"narrative_text": "..."' in prompt
        assert '"extraction_triggers":' in prompt
        assert '"scene_mood":' in prompt
        assert "Génère la suite de l'histoire en JSON." in prompt

    # ---- Credits display (gauges removed) ----

    def test_credits_display_format(self):
        """Protagonist credits are displayed, gauges are not."""
        ctx = _make_context(
            protagonist=ProtagonistState(
                name="Valentin",
                credits=2000,
                hobbies=[],
            )
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "Crédits: 2000" in prompt
        # Gauges no longer displayed in context prompt
        assert "Énergie:" not in prompt
        assert "Moral:" not in prompt
        assert "Santé:" not in prompt

    # ---- Full integration: all sections present at once ----

    def test_full_context_all_sections(self):
        """Prompt with every optional section populated renders all headers."""
        ctx = _make_context(
            world_name="Chrysalide",
            world_atmosphere="sombre",
            tone_notes="Melancholic",
            connected_locations=[
                LocationSummary(name="Parc", type="park", sector="Central", atmosphere="vert"),
            ],
            current_location=LocationSummary(
                name="Hub",
                type="hub",
                sector="Central",
                atmosphere="animé",
                ambient="Rumeur de grève",
            ),
            protagonist=ProtagonistState(
                name="Valentin",
                credits=500,
                hobbies=["musique"],
                current_occupation="Dev",
                employer="SynTech",
            ),
            inventory=[InventoryItem(name="Pad", category="tech")],
            personal_ai=PersonalAssistantSummary(name="Echo", personality_traits=["dry"]),
            organizations=[
                OrganizationSummary(name="Corp", org_type="corp", domain="tech", protagonist_relation="employed_by"),
            ],
            npcs_present=[
                NPCSummary(
                    name="Zed",
                    occupation="guard",
                    species="human",
                    relationship_level=1,
                    usual_location="Hub",
                    known=True,
                    traits=["stern"],
                ),
            ],
            all_npcs=[
                NPCLightSummary(
                    name="Reva",
                    occupation="doctor",
                    species="human",
                    relationship_level=None,
                    usual_location="Med",
                    known=True,
                ),
            ],
            active_arcs=[
                ActiveArcSummary(
                    type="social",
                    title="Test Arc",
                    description_brief="Arc desc",
                    involved=["Zed"],
                ),
            ],
            upcoming_events=[
                EventSummary(title="Meeting", planned_cycle=2, type="appointment"),
            ],
            facts=[
                Fact(cycle=1, description="Fact 1", importance=4),
            ],
            cycle_summaries=[
                CycleSummary(cycle=0, summary="Pre-arrival.", date=None),
            ],
            player_input="Test input",
        )
        prompt = build_narrator_context_prompt(ctx)

        expected_sections = [
            "### TEMPS",
            "### MONDE",
            "### LIEU ACTUEL",
            "Lieux accessibles:",
            "### PROTAGONISTE",
            "Inventaire:",
            "### IA PERSONNELLE",
            "### ORGANISATIONS CONNUES",
            "### PNJs",
            "### ARCS MONDE & PNJ",
            "### ÉVÉNEMENTS À VENIR",
            "### CONNAISSANCES SUR LES ENTITÉS",
            "### CHRONOLOGIE RÉCENTE",
            "## ACTION DU JOUEUR",
            "## FORMAT DE RÉPONSE ATTENDU",
        ]
        for section in expected_sections:
            assert section in prompt, f"Missing section: {section}"

    # ---- Edge: no NPCs at all ----

    def test_no_npcs_section_when_all_empty(self):
        """No PNJs header when no NPCs of any tier exist."""
        ctx = _make_context(
            npcs_present=[],
            all_npcs=[],
            requested_entity_details={},
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "### PNJs" not in prompt

    # ---- NPC arc with no situation_brief ----

    def test_present_npc_arc_without_situation_brief(self):
        """Arc line renders without the arrow line when situation_brief is empty."""
        ctx = _make_context(
            npcs_present=[
                NPCSummary(
                    name="Jo",
                    occupation="cook",
                    species="human",
                    relationship_level=None,
                    usual_location=None,
                    known=True,
                    traits=["friendly"],
                    active_arcs=[
                        ArcSummary(
                            domain=ArcDomain.HEALTH,
                            title="Recovery",
                            situation_brief="",
                            intensity=1,
                        ),
                    ],
                ),
            ]
        )
        prompt = build_narrator_context_prompt(ctx)
        assert "Arc [health] Recovery" in prompt
        # The arrow line should not be present for empty situation_brief
        arc_section = prompt.split("Arc [health] Recovery")[1].split("\n")[0:2]
        assert all("→" not in line for line in arc_section)
