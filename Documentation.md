# LDVELH — Technical Documentation

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [World Generation Pipeline](#2-world-generation-pipeline)
3. [Chat / Narration Pipeline](#3-chat--narration-pipeline)
4. [Game Engine System](#4-game-engine-system)
5. [Batch Extraction System](#5-batch-extraction-system)
6. [Game CRUD](#6-game-crud)
7. [Rollback & Message Editing](#7-rollback--message-editing)
8. [Auth System](#8-auth-system)
9. [Knowledge Graph Layer](#9-knowledge-graph-layer)
10. [State Normalization](#10-state-normalization)
11. [SSE Streaming](#11-sse-streaming)
12. [Tooltips & World Sidebar](#12-tooltips--world-sidebar)
13. [Frontend Architecture](#13-frontend-architecture)

---

## 1. Architecture Overview

### Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js (App Router) + Tailwind CSS |
| Backend | Python / FastAPI |
| Database | PostgreSQL 16 |
| AI Models | Claude Sonnet 4.5 (narration + extraction), Claude Haiku 4.5 (summaries + mechanical decisions) |
| Streaming | Server-Sent Events (SSE) |
| Auth | JWT (bcrypt password hashing) |

### Project Structure

```
ldvelh/
├── backend/
│   ├── api/
│   │   ├── routes.py          # Main endpoints, _handle_chat core flow
│   │   ├── streaming.py       # SSEWriter, SSE event types
│   │   ├── auth.py            # Auth endpoints (register, login, verify)
│   │   ├── tooltips.py        # Tooltip endpoints
│   │   └── dependencies.py    # FastAPI dependency injection
│   ├── services/
│   │   ├── game_service.py    # Game CRUD, state loading, messages, rollback
│   │   ├── llm_service.py     # Claude API integration, streaming
│   │   ├── context_builder.py # Builds NarrationContext from DB
│   │   ├── state_normalizer.py# Normalizes game state for frontend
│   │   ├── auth_service.py    # JWT, password hashing, email verification
│   │   ├── engine/            # Game engine system (strategy pattern)
│   │   │   ├── __init__.py    # get_engine() factory
│   │   │   ├── base.py        # BaseEngine ABC
│   │   │   ├── none.py        # NoneEngine (free narrative, no mechanics)
│   │   │   ├── narrative.py   # NarrativeEngine (traits-based resistance)
│   │   │   ├── fate_core.py   # FateCoreEngine (4dF, aspects, stress)
│   │   │   ├── d6.py          # D6Engine (NdD6, wild die, wounds)
│   │   │   ├── mechanical_service.py  # Mechanical LLM step
│   │   │   └── engine_data.py # Canonical skill/attribute lists per genre
│   │   └── extraction/        # Batch extractors
│   │       ├── orchestrator.py# Extraction dispatcher
│   │       ├── base.py        # BaseExtractor
│   │       ├── characters.py  # Character extraction
│   │       ├── locations.py   # Location extraction
│   │       ├── organizations.py
│   │       ├── inventory.py   # Inventory extraction (+ engine extensions)
│   │       ├── narrative_arcs.py
│   │       └── progression.py # Engine progression extraction
│   ├── kg/                    # Knowledge Graph layer
│   │   ├── reader.py          # KnowledgeGraphReader (SELECT queries)
│   │   ├── populator.py       # KnowledgeGraphPopulator (INSERT/UPDATE)
│   │   └── specialized_populator.py  # WorldPopulator, ExtractionPopulator
│   ├── prompts/
│   │   ├── narrator_prompt.py # System + context prompts for narration
│   │   ├── world_generation_prompt.py # World gen prompts
│   │   ├── mechanical_prompt.py       # Mechanical decision prompts
│   │   ├── examples.py        # Single source of truth for JSON examples
│   │   └── extraction/        # Per-extractor prompt modules
│   ├── schema/                # Pydantic models
│   │   ├── core.py            # Base types (Name, ShortText, etc.)
│   │   ├── narration.py       # NarrationOutput, NarrationContext
│   │   ├── world_generation.py# WorldGeneration schema
│   │   ├── engine.py          # Engine types, MechanicalDecision, RollResult
│   │   ├── extraction.py      # Extraction models
│   │   ├── sse_payload.py     # SSE payload models
│   │   ├── entities.py        # Entity models (Character, Location, etc.)
│   │   ├── relations.py       # Relation models
│   │   └── narrative.py       # Narrative arc models
│   └── tests/                 # 840+ tests, 94% coverage
├── frontend/
│   ├── app/
│   │   ├── page.js            # Main page, phase routing
│   │   ├── layout.js          # Root layout
│   │   └── (auth)/            # Login, register, verify pages
│   ├── hooks/
│   │   ├── useGameOrchestrator.js  # All game business logic
│   │   ├── useStreaming.js         # SSE handling
│   │   ├── useGameState.js         # Game state management
│   │   ├── useGamePhase.js         # Phase state machine
│   │   ├── useAuth.js              # Auth hook
│   │   ├── usePreferences.js       # User preferences
│   │   ├── useTooltips.js          # Tooltip loading
│   │   └── useWorldData.js         # World sidebar data
│   ├── components/game/
│   │   ├── GameHeader.jsx
│   │   ├── StatsBar.jsx       # Engine-polymorphic stats display
│   │   ├── EngineStats.jsx    # Per-engine stat components
│   │   ├── MessageList.jsx    # Message display
│   │   ├── Message.jsx        # Single message + dice roll
│   │   ├── DiceRollDisplay.jsx# Inline dice visuals
│   │   ├── InputArea.jsx      # Text input
│   │   ├── WorldGenerationScreen.jsx  # World gen progress + completion
│   │   ├── CharacterSheet.jsx # Full character sheet overlay
│   │   ├── AspectInvocationModal.jsx  # Fate Core invocation modal
│   │   ├── Sidebars.jsx       # Inventory + World sidebars
│   │   └── wizard/            # World creation wizard (3 steps)
│   └── lib/
│       ├── api.js             # API client with auth headers + 401 retry
│       ├── AuthContext.js     # Auth context provider
│       └── game/
│           ├── gameState.js   # Default state, merge utilities
│           └── engineConfig.js# Engine options, genre/difficulty constants
├── schema.sql                 # Canonical DB schema
└── db/migrations/             # Incremental migrations (dbmate format)
```

### Key Design Patterns

- **Strategy Pattern**: `get_engine(engine_type)` returns a `BaseEngine` subclass. All engine-specific logic (dice, stats, prompts, progression) goes through this abstraction.
- **Reader/Populator Separation**: `kg/reader.py` handles all SELECTs, `kg/populator.py` handles all INSERTs/UPDATEs. They share the same `(pool, game_id)` constructor.
- **SSE Streaming**: All real-time communication uses an async queue (`SSEWriter`) that serializes events as `data: {json}\n\n` lines.
- **Narrator Deltas**: The narrator LLM outputs live deltas (credits, inventory hints, entity reveals) applied immediately — no extraction needed for these.
- **Batch Extraction**: Heavier extraction (characters, locations, orgs, arcs, inventory, progression) runs fire-and-forget on `day_transition` triggers.

---

## 2. World Generation Pipeline

### Overview

```
User clicks "New Game"
  → Wizard (3 steps: engine, world config, character)
    → POST /games (create empty game)
      → POST /chat with __INIT__ (stream world JSON)
        → LLM generates full world JSON
          → WorldPopulator writes all entities to DB
            → SSE done event with world summary
              → Frontend shows "Start Adventure" button
```

### Step-by-step

#### 2.1 Frontend: Wizard Entry

**File:** `frontend/hooks/useGameOrchestrator.js`

`handleNewGame()` resets state and sets phase to `WIZARD`:
```
gs.setError(null) → gs.setMessages([]) → gs.replaceGameState(null)
→ phase.setGamePhase(GAME_PHASE.WIZARD)
```

**File:** `frontend/app/page.js`

Phase routing renders `WizardContainer` when `phaseHook.isWizard`.

#### 2.2 Frontend: Wizard Data Collection

**File:** `frontend/components/game/wizard/WizardContainer.jsx`

Three steps collect data locally (no API calls):

| Step | Component | Data Collected |
|------|-----------|----------------|
| 0 | `EngineSelectionStep` | `engine`: `"none"` / `"narrative"` / `"fate_core"` / `"d6"` |
| 1 | `WorldConfigStep` | `worldConfig`: `{genre, difficulty, hardcore, lore}` + `manualEntities`: `{npcs, locations, organizations}` |
| 2 | `CharacterCreationStep` | `characterData`: engine-specific stats (traits, aspects, attributes, etc.) |

On "Create" click → calls `onComplete({engine, worldConfig, characterData, manualEntities})`.

#### 2.3 Frontend: handleWizardComplete

**File:** `frontend/hooks/useGameOrchestrator.js`

```
1. games.createGame(engine)    → POST /games → returns gameId
2. gs.setGameId(id)
3. games.loadGames()           → refresh game list
4. phase.setGamePhase(GENERATING_WORLD)
5. startStream('/chat', {
     message: '__INIT__',
     gameId: id,
     gameState: null,
     provider, model,
     engine, world_config, character_data, manual_entities
   })
```

#### 2.4 Backend: POST /games

**File:** `backend/api/routes.py`

Creates an empty game row with optional engine type:
```
GameService.create_game(user_id, engine)
  → KnowledgeGraphPopulator.create_game(conn, name, user_id)
    → INSERT INTO games (id, name, user_id, engine, ...)
```

#### 2.5 Backend: POST /chat (INIT mode)

**File:** `backend/api/routes.py` — `_handle_chat()`

INIT mode is detected when `server_state.get("world_created") == False`.

1. **Build prompt**: `get_full_generation_prompt(mandatory_npcs, theme_preferences, engine, world_config, character_data, manual_entities)`
   - **File:** `backend/prompts/world_generation_prompt.py`
   - System prompt: world-building instructions in French, entity constraints (3-6 NPCs, 4-5 locations, 1-3 orgs), JSON output format
   - User prompt: example JSON, engine-specific sections, manual entity constraints, genre/difficulty

2. **Stream LLM**: `llm_service.stream_narration(system, messages, sse_writer, is_init_mode=True)`
   - **File:** `backend/services/llm_service.py`
   - Uses `max_tokens_init` (higher limit for world gen)
   - Sends `SSEEvent.PROGRESS` every ~500 characters with the partial raw JSON
   - Frontend uses partial JSON to show real-time progress bar

3. **on_init_complete callback**: fires when LLM finishes
   - Validates JSON as `WorldGeneration` Pydantic model
   - Calls `game_service.process_init(game_id, world_gen)` which calls `WorldPopulator.populate()`
   - Sets engine + creates engine character if engine != "none"
   - Loads canonical state, builds `SSEDonePayload` with `world_info`
   - Sends `SSEEvent.DONE` then `SSEEvent.SAVED`

#### 2.6 Backend: WorldPopulator.populate()

**File:** `backend/kg/specialized_populator.py`

All writes happen in a single atomic transaction:

```
1.  Rename game with world name
2.  Store world metadata (atmosphere, sectors, seed words, world_config)
3.  Create station as top-level location
4.  Create protagonist (name, origin, credits, departure_reason)
5.  Create personal assistant (name, traits, voice, quirk)
6.  Create organizations (1-3, with is_employer flag)
7.  Create locations (4-5, with parent refs)
8.  Resolve FK references (location parents, org HQs, protagonist employer/residence)
9.  Create characters (3-6 NPCs, with workplace/residence FKs)
10. Create objects + inventory entries
11. Load entity_registry (for relation/arc creation)
12. Create explicit relations (lives_at, works_at, employed_by, knows, etc.)
13. Create narrative arcs (global + per-character)
14. Store arrival event as facts + chronology entry
15. Set initial game state (cycle=1, date, time, location)
```

**DB tables written:** games, locations, protagonists, personal_assistants, organizations, characters, objects, protagonist_inventory, entity_registry (auto via triggers), relations, narrative_arcs, facts, events, chronology, extraction_log.

#### 2.7 Frontend: Progress Display

**File:** `frontend/components/game/WorldGenerationScreen.jsx`

During generation:
- `partialJson` (from `SSEEvent.PROGRESS`) is parsed to calculate progress percentage
- Progress is based on which JSON keys have appeared: `generation_seed_words` → `world` → `locations` → `organizations` → `protagonist` → `personal_assistant` → `characters` → `inventory` → `narrative_arcs` → `initial_relations` → `arrival_event`
- Each key has a weight (heaviest: `characters` at 28%)
- Progress capped at 95% until stream completes
- Shows current step label, world name (extracted via regex), progress bar

On completion (`worldData` is set via `onDone`):
- Shows NPC/location/org/credits counts
- World atmosphere, AI personality, arrival details
- Generation cost (provider, model, tokens, USD)
- "Start Adventure" button → calls `handleStartAdventure()`

#### 2.8 Starting the Adventure

`handleStartAdventure()` sends `POST /chat` with `message: '__ARRIVEE__'` (arrival token). The backend enters LIGHT mode (world is created), builds context from the freshly populated world, and streams the first narrative response.

---

## 3. Chat / Narration Pipeline

### Overview

```
User types message
  → POST /chat (LIGHT mode)
    → Load context from DB (ContextBuilder)
      → Mechanical step (if engine requires dice)
        → Build narrator prompt (system + context)
          → Stream narration from LLM
            → SSE chunks to frontend
              → on_light_complete:
                → Apply narrator deltas (credits, entity reveals)
                → Save messages to DB
                → Trigger extraction (fire-and-forget)
                → SSE done + saved events
```

### Step-by-step

#### 3.1 Frontend: Send Message

**File:** `frontend/hooks/useGameOrchestrator.js` — `handleSendMessage(content)`

```
1. Guard: check gameId, sendingRef, isExtracting
2. sendingRef.current = true (prevent concurrent sends)
3. setLastUserMessage(content) (for regenerate)
4. Add user message to UI immediately
5. gs.setLoading(true), gs.setSaving(true)
6. startStream('/chat', {gameId, message, gameState, provider, model})
```

#### 3.2 Backend: _handle_chat (LIGHT mode)

**File:** `backend/api/routes.py` — `_handle_chat()`

LIGHT mode is the default when `world_created == True`.

**Step 1: Load context**

```python
builder = ContextBuilder(pool, game_id)
context = await builder.build(conn, player_input, current_cycle, current_time, current_location_name)
```

**File:** `backend/services/context_builder.py` — `ContextBuilder.build()`

Loads from DB via `KnowledgeGraphReader`:

| Data | Reader Method | Description |
|------|--------------|-------------|
| World info | `get_root_location()` | Station name, atmosphere |
| Game state | `get_game()` | Date, cycle, engine type, world metadata |
| Protagonist | `get_protagonist()` | Name, credits, occupation, employer |
| Inventory | `get_inventory()` | Items with quantities |
| Personal AI | `get_personal_assistant()` | Name, voice, traits, quirk |
| Current location | `get_location_by_name()` | Name, type, sector, ambient |
| Connected locations | `get_sibling_locations()` | Accessible nearby locations |
| NPCs (present) | `get_npcs_at_location()` | NPCs at current location |
| NPCs (relevant) | `get_all_characters()` | Top 5 by relation strength |
| NPCs (all) | `get_all_characters()` | Light summaries of everyone |
| Organizations | reader query | With protagonist relation |
| Active arcs | `get_active_arcs()` | Narrative arcs in progress |
| Upcoming events | `get_upcoming_events()` | Scheduled events |
| Recent facts | `get_facts()` | Important facts |
| Requested details | `get_entity_details_by_name()` | Entities the narrator requested last turn |
| Cycle summaries | `get_chronology()` | History before conversation window |
| Engine stats | `engine.get_stats()` | Fate/D6/Narrative character data |

Returns a `NarrationContext` object with all this data.

**Step 2: Mechanical step (engine-aware)**

If `engine.needs_mechanical_step()` returns True (Fate Core or D6):

```python
mechanical_result = await run_mechanical_step(engine, context, message, provider_name, api_key)
```

**File:** `backend/services/engine/mechanical_service.py` — `run_mechanical_step()`

1. Builds a mechanical context prompt (player message + engine stats + world difficulty)
2. Calls Haiku model to get a `MechanicalDecision` JSON:
   ```json
   {"requires_test": true, "skill": "Athlétisme", "skill_value": 3, "difficulty": 4, "reason": "..."}
   ```
3. If `requires_test`: calls `engine.roll_dice(decision)` → returns `RollResult`
4. Applies roll result to DB via `engine.apply_roll_result()`
5. Sends `SSEEvent.ROLL_RESULT` to frontend for dice display

**Fate Core special case:** If roll outcome is failure and player has fate_points > 0 and aspects, the pipeline **pauses**:
- Stores pending roll in `mechanic_rolls` table (with `message_id = NULL`)
- Sends `SSEEvent.ROLL_PENDING` with `{roll_id, roll, aspects, fate_points}`
- Closes the SSE stream and returns
- Frontend shows aspect invocation modal → player selects aspects
- Frontend sends new `POST /chat` with `roll_id + invoked_aspects`
- Backend loads pending roll, applies +2/aspect bonus, recalculates outcome, continues to narration

**Step 3: Build narrator prompts**

**File:** `backend/prompts/narrator_prompt.py`

```python
system_prompt = build_narrator_system_prompt(engine_type)
context_prompt = build_narrator_context_prompt(context, engine_type, mechanical_result)
```

System prompt (~210 lines): narrative rules, tone, structure, delta output format (credits, inventory hints, entity reveals, info requests, extraction triggers).

Context prompt: markdown sections built from `NarrationContext`:
- `## TEMPS` — cycle, date, time
- `## MONDE` — world name, atmosphere
- `## LIEU ACTUEL` — current location + accessible locations
- `## PROTAGONISTE` — name, occupation, credits
- `## ENGINE STATS` — engine-specific vitals (delegated to engine)
- `## INVENTAIRE` — items with quantities
- `## IA PERSONNELLE` — AI companion details
- `## ORGANISATIONS` — with protagonist relation
- `## PNJs` — 3-tier hierarchy (requested details → present NPCs → all known)
- `## ARCS & ENGAGEMENTS ACTIFS` — active narrative arcs
- `## ÉVÉNEMENTS À VENIR` — scheduled events
- `## FAITS PERTINENTS` — recent facts
- `## RÉSUMÉ CYCLES PRÉCÉDENTS` — history
- `## RÉSULTAT MÉCANIQUE` — dice roll outcome (if applicable)
- `## ACTION DU JOUEUR` — the player's input

**Step 4: Build message history**

**File:** `backend/services/game_service.py` — `build_llm_messages()`

- Loads messages from DB for the last 2 cycles (conversation window)
- User messages enriched with `[Cycle N — HHhMM — Location]` metadata
- Assistant messages append arc progression hints from narrator_deltas
- Applies `cache_control: ephemeral` on last message of cycle N-1 (Anthropic prompt caching)
- Appends context prompt as final user message

**Step 5: Stream narration**

**File:** `backend/services/llm_service.py` — `stream_narration()`

- Calls `provider.stream(system_prompt, messages, temperature, max_tokens)`
- For LIGHT mode: extracts displayable narrative text in real-time
- Sends `SSEEvent.CHUNK` for each text delta
- On completion: parses full JSON response, calls `on_complete` callback

**Step 6: on_light_complete**

**File:** `backend/api/routes.py`

1. **Validate output** as `NarrationOutput` Pydantic model
2. **Process game state**: `game_service.process_light()` — updates cycle, time, location, NPCs present
3. **Apply narrator deltas**: `game_service.apply_narrator_deltas()` — credit transactions, entity reveals (mark characters known, locations accessible)
4. **Store info requests**: saves narrator's `info_requests` list for next turn's context prefetch
5. **Build client state**: loads fresh state from DB, normalizes for frontend
6. **Send SSE done**: `SSEEvent.DONE` with display text + full game state + cost
7. **Save messages**: user message + assistant message to DB (with narrator_deltas and engine snapshot)
8. **Trigger extraction**: if `extraction_triggers` is non-empty, fires `asyncio.create_task(run_triggered_extraction(...))` — fire-and-forget
9. **Send SSE saved**: `SSEEvent.SAVED` confirms DB write is complete

#### 3.3 Frontend: Receiving Events

**File:** `frontend/hooks/useStreaming.js` — `startStream()`

SSE events dispatched to callbacks in `useGameOrchestrator`:

| SSE Event | Callback | UI Effect |
|-----------|----------|-----------|
| `chunk` | `onChunk` | Appends text to last assistant message (streaming: true) |
| `roll_result` | `onRollResult` | Stores in `pendingRollRef` for attachment to next message |
| `roll_pending` | `onRollPending` | Shows aspect invocation modal (Fate Core) |
| `extracting` | `onExtracting` | Sets message to extracting state |
| `done` | `onDone` | Finalizes message (streaming: false), updates game state |
| `saved` | `onSaved` | Stops saving spinner, refreshes tooltips + world sidebar |
| `error` | `onError` | Shows error message |

---

## 4. Game Engine System

### Strategy Pattern

**File:** `backend/services/engine/__init__.py`

```python
def get_engine(engine_type: str) -> BaseEngine:
    # Returns singleton: NoneEngine, NarrativeEngine, FateCoreEngine, or D6Engine
```

All engine-specific logic goes through the `BaseEngine` interface.

### BaseEngine Interface

**File:** `backend/services/engine/base.py`

| Method | Type | Description |
|--------|------|-------------|
| `get_stats(conn, game_id)` | async | Load character stats from DB |
| `get_vitals_display(conn, game_id)` | async | Formatted vitals for frontend |
| `create_character(conn, game_id, data)` | async | Create engine-specific character |
| `apply_roll_result(conn, game_id, roll, cycle)` | async | Apply mechanical consequences |
| `snapshot_state(conn, game_id)` | async | Capture state for rollback |
| `restore_snapshot(conn, game_id, snapshot)` | async | Restore from snapshot |
| `needs_mechanical_step()` | sync | Whether this engine uses dice |
| `roll_dice(decision)` | sync | Execute dice roll |
| `build_narrator_addon(roll_result)` | sync | Extra text for narrator |
| `get_gauge_policy()` | sync | `"none"` or `"engine"` |
| `get_system_prompt_addon()` | sync | Engine-specific narrator rules |
| `build_context_stats(engine_stats)` | sync | Stats section for context prompt |
| `get_progression_system_prompt()` | sync | Progression extraction prompt |
| `apply_progression(conn, game_id, extraction)` | async | Apply progression to DB |
| `get_object_prompt_addon()` | sync | Object extraction additions |
| `create_object_extension(conn, object_id, data)` | async | Engine-specific object row |

### Engine Implementations

| Engine | File | Dice | Key Features |
|--------|------|------|-------------|
| `none` | `engine/none.py` | None | Free narrative, no mechanics, no stats |
| `narrative` | `engine/narrative.py` | None | Traits-based resistance, LLM judges difficulty |
| `fate_core` | `engine/fate_core.py` | 4dF | Aspects, stress/consequences, skill pyramid, fate points, aspect invocation |
| `d6` | `engine/d6.py` | NdD6 | Attributes + skills, wild die (6=explode, 1=complication), wound track, force points |

### Dice Rolling

**Fate Core:** 4 Fudge dice (each: -1, 0, or +1) + skill value. Outcome: fail (<0 shifts), tie (0), success (1-2 shifts), success with style (3+ shifts).

**D6:** Roll NdD6 based on skill dice code (e.g. "3D+2"). One die is the "wild die": if it rolls 6, it explodes (reroll and add); if it rolls 1, it's a complication (remove highest normal die).

### Aspect Invocation (Fate Core)

When a Fate Core roll fails and the player has fate points + aspects:
1. Pipeline pauses, sends `SSEEvent.ROLL_PENDING`
2. Frontend shows `AspectInvocationModal.jsx` with aspect selection
3. Player invokes aspects (+2 per aspect to roll total), spending 1 fate point each
4. Frontend sends `POST /chat` with `roll_id` + `invoked_aspects`
5. Backend loads pending roll, applies bonus, recalculates outcome, continues to narration

### Engine Stats Tables

| Engine | Character Table | Skill/Trait Table | Object Extension |
|--------|----------------|-------------------|------------------|
| narrative | `character_narrative` | `traits_narrative` | `object_narrative` |
| fate_core | `character_fate` | `skills_fate` | `object_fate` |
| d6 | `character_d6` | `skills_d6` | `object_d6` |

### Engine Snapshot & Rollback

After each narration, the engine state is snapshot and stored on the assistant message (`messages.engine_snapshot` JSONB column). On rollback, the engine state is restored from the last remaining message's snapshot.

---

## 5. Batch Extraction System

### Trigger Mechanism

The narrator's JSON output includes an `extraction_triggers` field — a list of extractor names to run. Common trigger: `"day_transition"` which fires all extractors.

### Orchestrator

**File:** `backend/services/extraction/orchestrator.py`

```python
EXTRACTOR_MAP = {
    "characters":     CharactersExtractor,
    "locations":      LocationsExtractor,
    "organizations":  OrganizationsExtractor,
    "inventory":      InventoryExtractor,
    "narrative_arcs": NarrativeArcsExtractor,
    "progression":    ProgressionExtractor,
}
```

`run_triggered_extraction()`:
1. Filters triggers to valid names from `EXTRACTOR_MAP`
2. Creates extractor instances
3. Runs all in parallel via `asyncio.gather()`
4. Aggregates results and costs
5. Updates assistant message with extraction cost
6. Guards against concurrent extractions for same game via `_extracting_games` set

### Extractors

Each extractor (subclass of `BaseExtractor`):
1. Loads recent narrative context from DB
2. Builds system + user prompt for its domain
3. Calls Sonnet model with structured output (tool use)
4. Parses extraction result
5. Writes to DB via populator

| Extractor | What it extracts | DB writes |
|-----------|-----------------|-----------|
| Characters | New/updated NPCs, trait changes | `characters`, `entity_registry` |
| Locations | New/updated locations | `locations`, `entity_registry` |
| Organizations | Org changes | `organizations`, `entity_registry` |
| Inventory | Object acquisitions/losses | `objects`, `protagonist_inventory` + engine extensions |
| Narrative Arcs | Arc progress, new arcs | `narrative_arcs` |
| Progression | Engine skill/trait evolution | `skills_fate`/`skills_d6`/`traits_narrative` (delegated to engine) |

### Extraction is Fire-and-Forget

Extraction runs as a background `asyncio.create_task()`. It does not block the narration response. The frontend receives `SSEEvent.SAVED` before extraction completes.

---

## 6. Game CRUD

### Create Game

```
Frontend: handleWizardComplete() → games.createGame(engine)
  → POST /games {engine}
    → GameService.create_game(user_id, engine)
      → KnowledgeGraphPopulator.create_game(conn, name, user_id)
        → INSERT INTO games
```

### Load Game

```
Frontend: handleLoadGame(id) → games.loadGame(id)
  → GET /games/{id}
    → GameService.load_game_state(game_id)  # Full state from DB
    → GameService.load_chat_messages(game_id)  # Message history
    → Optionally: load world_info if world created but no messages yet
```

State restoration:
- `gs.replaceGameState(data.state)` — full game state
- `gs.setMessages(data.messages)` — message history
- Phase set based on: messages > 0 → PLAYING, world_created → WORLD_READY, else → GENERATING_WORLD

### Delete Game

```
Frontend: handleDeleteGame(id) → games.deleteGame(id)
  → DELETE /games/{id}
    → GameService.delete_game(game_id)
      → Sets games.active = false (soft delete)
```

### Rename Game

```
Frontend: handleRenameGame(newName) → games.renameGame(gameId, newName)
  → PATCH /games/{id} {name}
    → GameService.rename_game(game_id, name)
      → UPDATE games SET name = ...
```

### List Games

```
Frontend: gamesHook.loadGames()
  → GET /games
    → GameService.list_games(user_id)
      → SELECT from games WHERE user_id = ... AND active = true
```

---

## 7. Rollback & Message Editing

### Three Rollback Scenarios

All three follow the same pattern: rollback to a message index, then re-send.

**Edit (modify text):**
```
handleSubmitEdit(content):
  1. stateApi.rollback(gameId, editingIndex)  → POST /games/{id}/rollback {fromIndex}
  2. gs.setMessages(prev => prev.slice(0, editingIndex))
  3. handleSendMessage(content)  // new text
```

**Resend (same text):**
```
handleResend(index):
  1. Get message at index (must be user role)
  2. stateApi.rollback(gameId, index)
  3. gs.setMessages(prev => prev.slice(0, index))
  4. handleSendMessage(msg.content)  // same text
```

**Regenerate (redo last assistant response):**
```
handleRegenerate():
  1. stateApi.rollback(gameId, messages.length - 2)
  2. gs.setMessages(prev => prev.slice(0, -2))  // remove user + assistant
  3. handleSendMessage(lastUserMessage)
```

### Backend Rollback

**File:** `backend/api/routes.py` — `POST /games/{game_id}/rollback`

Calls `GameService.rollback_to_message(game_id, keep_until_index)`:
1. Deletes messages after `keep_until_index`
2. Restores engine snapshot from last remaining message (if present)
3. Returns updated state and remaining messages

---

## 8. Auth System

### Frontend

**File:** `frontend/hooks/useAuth.js`

- **Login:** `login(identifier, password)` → `POST /auth/login` → stores JWT + user in localStorage
- **Register:** `register(email, password, passwordConfirm, displayName)` → `POST /auth/register`
- **Session restore:** on mount, reads localStorage → validates via `GET /auth/me` → refreshes token
- **Token refresh:** every 30 minutes via `POST /auth/refresh`
- **Logout:** clears localStorage

**File:** `frontend/lib/api.js`

All API requests include `Authorization: Bearer {token}` header. On 401 response, automatically attempts token refresh and retries the original request. On refresh failure, clears auth and redirects to `/login/`.

### Backend

**File:** `backend/api/auth.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/register` | POST | Create user, hash password, send verification email |
| `/auth/login` | POST | Authenticate by email or display_name, return JWT |
| `/auth/me` | GET | Return current user (requires auth) |
| `/auth/refresh` | POST | Issue fresh JWT |
| `/auth/verify` | GET | Verify email via token (24h expiry) |
| `/auth/resend-verification` | POST | Resend verification email |
| `/auth/change-password` | POST | Verify current + update password |
| `/auth/profile` | PATCH | Update display name |
| `/auth/preferences` | GET | Load user preferences (API keys masked) |
| `/auth/preferences` | PATCH | Update preferences (API keys encrypted) |

**File:** `backend/services/auth_service.py`

- Password hashing: bcrypt
- JWT: signed with `JWT_SECRET`, expiry configurable via `jwt_expiry_hours`
- Email verification tokens: 24h expiry, stored in `users.verification_token`

### Preferences

Stored in `users.preferences` JSONB column. Includes:
- `font_size`, `show_debug` — UI settings
- `active_provider`, `active_model` — LLM provider selection
- `api_keys` — encrypted per-provider API keys

---

## 9. Knowledge Graph Layer

### Architecture

**File:** `backend/kg/__init__.py`

```
KnowledgeGraphReader (SELECT)     → kg/reader.py
KnowledgeGraphPopulator (INSERT/UPDATE/DELETE) → kg/populator.py
  └── EntityRegistry              → in-memory cache of entity_registry table
WorldPopulator (extends Populator) → kg/specialized_populator.py
```

### Reader

**File:** `backend/kg/reader.py` — `KnowledgeGraphReader(pool, game_id)`

All read operations. Key methods:

| Method | Returns |
|--------|---------|
| `get_game(conn)` | Full game row with world metadata |
| `get_protagonist(conn)` | Protagonist with credits, employer, occupation |
| `get_inventory(conn)` | Items with quantities (via `v_protagonist_inventory` view) |
| `get_personal_assistant(conn)` | AI companion data |
| `get_location_by_name(conn, name)` | Location details |
| `get_sibling_locations(conn, location_id)` | Connected locations |
| `get_all_characters(conn)` | All NPCs with relation strength |
| `get_npcs_at_location(conn, location_name)` | NPCs at specific location |
| `get_active_arcs(conn)` | Active narrative arcs |
| `get_upcoming_events(conn)` | Scheduled events |
| `get_facts(conn)` | Recent important facts |
| `get_entity_details_by_name(conn, names)` | Full entity details for requested entities |
| `get_chronology(conn)` | Past cycle summaries |
| `get_messages_for_cycles(conn, min_cycle, max_cycle)` | Message history |

### Populator

**File:** `backend/kg/populator.py` — `KnowledgeGraphPopulator(pool, game_id)`

All write operations. Maintains an in-memory `EntityRegistry` cache mapping entity names to `entity_registry` UUIDs.

Key methods: `create_game`, `delete_game`, `rename_game`, `create_character`, `create_location`, `create_organization`, `create_object`, `add_to_inventory`, `create_relation`, `create_narrative_arc`, `create_fact`, `credit_transaction`, `mark_character_known`, `mark_location_accessible`, `update_game_state`.

### Entity Registry

PostgreSQL triggers auto-register entities (characters, locations, organizations) into `entity_registry` on INSERT. This provides a unified ID lookup for cross-table references (relations, facts, arcs, chronology participants).

### WorldPopulator

**File:** `backend/kg/specialized_populator.py`

Extends `KnowledgeGraphPopulator` with methods specific to initial world population: `populate()`, `_create_station_location()`, `_resolve_location_parents()`, `_resolve_org_headquarters()`, `_store_arrival_event()`.

---

## 10. State Normalization

**File:** `backend/services/state_normalizer.py`

Converts raw DB data into a clean `GameState` for the frontend.

### GameState Structure

```
GameState:
  game: GameSessionState
    - id, name, current_cycle, game_date, time
    - current_location, npcs_present, status
    - engine, engine_locked, world_created
  player: PlayerState
    - credits, inventory: [{name, quantity, description}]
    - engine_stats: dict | None (engine-specific)
  ai: AIState
    - name, personality, voice, quirk, relationship
```

### Where it's used

- `GameService.load_game_state()` calls `normalize_game_state()` after loading raw data
- SSE `done` event carries the normalized state as `game_state`
- Frontend `useGameState` hook stores and exposes this structure

---

## 11. SSE Streaming

### SSE Event Types

**File:** `backend/api/streaming.py`

| Event | Payload | When |
|-------|---------|------|
| `chunk` | `{content}` | Each text delta during narration streaming |
| `progress` | `{rawJson}` | Partial JSON during world generation (every ~500 chars) |
| `extracting` | `{displayText}` | Narration done, extraction starting |
| `done` | `{displayText, state}` | Final result with full game state |
| `saved` | `{}` | DB save confirmed |
| `error` | `{error, details, recoverable}` | Error occurred |
| `warning` | `{message, details}` | Non-fatal warning |
| `roll_result` | `{roll}` | Dice roll result for display |
| `roll_pending` | `{roll_id, roll, aspects, fate_points}` | Fate Core invocation pause |

### SSEWriter

Async queue-based writer. Events are pushed via typed methods (`send_chunk`, `send_progress`, `send_done`, etc.) and consumed by `iterate()` which yields `data: {json}\n\n` lines. Includes 60-second keepalive timeout.

### Frontend Handling

**File:** `frontend/hooks/useStreaming.js`

`startStream(url, body)`:
1. POSTs to backend with JSON body
2. If response is `text/event-stream`: reads via `ReadableStream` reader
3. Parses `data: ` lines as JSON
4. Dispatches to callbacks: `onChunk`, `onProgress`, `onExtracting`, `onDone`, `onSaved`, `onError`, `onRollResult`, `onRollPending`
5. Returns `{success, fullJson}` or `{success: false, aborted}` on cancel

Cancellation: `cancel()` aborts the `AbortController`, frontend updates message with "*(Annulé)*" suffix.

---

## 12. Tooltips & World Sidebar

### Tooltips

**File:** `backend/api/tooltips.py`

`GET /api/tooltips?gameId={id}`:
- Queries entities with LEFT JOIN facts
- Groups knowledge facts per entity
- Loads relation to protagonist
- Returns `{tooltips: {[name_lower]: {entity_type, entity_name, facts, relation, formatted}}}`

**Frontend:** `useTooltips(gameId)` hook. Auto-refreshes on `onSaved` event. Returns `tooltipMap` used by `MessageList` to render entity name hover cards.

### World Sidebar

**File:** `backend/api/routes.py` — `GET /games/{id}/world`

Returns:
- `npcs`: characters (name, description, occupation, location)
- `locations`: all locations (name, type, sector)
- `quests`: narrative arcs with `arc_type = 'quest'`
- `organizations`: all organizations

**Frontend:** `useWorldData(gameId, enabled)` hook. Auto-refreshes on `onSaved` event. Displayed in `WorldSidebar` component (right sidebar).

---

## 13. Frontend Architecture

### Phase State Machine

**File:** `frontend/hooks/useGamePhase.js`

```
LIST → WIZARD → GENERATING_WORLD → WORLD_READY → STARTING_ADVENTURE → PLAYING
                                                                        ↕
                                                                     SETTINGS
```

| Phase | What's shown |
|-------|-------------|
| `LIST` | Game list (create, load, delete) |
| `WIZARD` | 3-step world creation wizard |
| `GENERATING_WORLD` | Progress bar with partial JSON parsing |
| `WORLD_READY` | World summary + "Start Adventure" button |
| `STARTING_ADVENTURE` | Loading spinner |
| `PLAYING` | Main game UI (messages, input, sidebars) |
| `SETTINGS` | Settings page |

### Hook Architecture

**File:** `frontend/app/page.js`

```javascript
const gs = useGameState();        // Game state (messages, loading, error, gameState)
const gamesHook = useGames();     // Game list CRUD
const phaseHook = useGamePhase(); // Phase state machine
const prefs = usePreferences(user); // User preferences
const tooltips = useTooltips(gs.gameId);  // Entity tooltips
const worldData = useWorldData(gs.gameId, phaseHook.isPlaying);  // World sidebar

const orch = useGameOrchestrator({
    gameState: gs,
    games: gamesHook,
    phase: phaseHook,
    tooltips: { refresh: refreshTooltips },
    world: { refresh: refreshWorld },
    preferences: prefs,
});
```

### Orchestrator Pattern

**File:** `frontend/hooks/useGameOrchestrator.js`

All game business logic lives in `useGameOrchestrator`. It:
- Registers all SSE callbacks (onChunk, onDone, onSaved, onError, etc.)
- Exposes game handlers (handleNewGame, handleLoadGame, handleDeleteGame, etc.)
- Exposes message handlers (handleSendMessage, handleCancel, handleEdit, handleResend, handleRegenerate)
- Exposes world generation handlers (handleStartAdventure, handleWizardComplete)
- Manages local state: `isExtracting`, `editingIndex`, `lastUserMessage`, `invocationData`

### Phase Routing

`page.js` renders different components based on phase (checked top-to-bottom, first match wins):

1. Auth loading → spinner
2. Not authenticated → redirect to `/login/`
3. `SETTINGS` → `SettingsPage`
4. `LIST` or no gameId (and not wizard) → `GamesList`
5. `WIZARD` → `WizardContainer`
6. `GENERATING_WORLD` or `WORLD_READY` → `WorldGenerationScreen`
7. `STARTING_ADVENTURE` with no messages → loading spinner
8. Default (PLAYING) → main game UI (header, stats, messages, input, sidebars)
