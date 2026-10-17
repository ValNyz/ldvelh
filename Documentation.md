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
│   │   ├── routes.py          # Endpoints; _handle_chat is a thin adapter (lock, session, error report)
│   │   ├── streaming.py       # SSEWriter, SSE event types
│   │   ├── game_writers.py    # Accepted /chat writers per game (busy check, C-13)
│   │   ├── auth.py            # Auth endpoints (register, login, verify)
│   │   ├── tooltips.py        # Tooltip endpoints
│   │   └── dependencies.py    # FastAPI dependency injection
│   ├── pipeline/              # Turn pipeline (no FastAPI, no SQL)
│   │   ├── turn.py            # run_turn: load → arbitrate → narrate → commit → respond → schedule
│   │   ├── init_flow.py       # World generation turn (INIT)
│   │   ├── context.py         # TurnContext, TurnRequest, InitParams
│   │   ├── narration_stream.py# Provider stream, partial-JSON chunks, display text
│   │   ├── errors.py          # report_error: exception → one French TurnError
│   │   ├── ports.py           # EventSink protocol (SSEWriter satisfies it)
│   │   ├── uncancellable.py   # finish_despite_cancel (commit and post-commit part)
│   │   └── steps/             # load, arbitrate, narrate, commit, respond, schedule
│   ├── domain/                # Pure types: turn.py (PendingRoll, AppliedDeltas, NarrationState), errors.py (TurnError), game.py
│   ├── repos/                 # SQL: games.py, turns.py (the turn transaction), users.py, llm_models.py
│   ├── services/
│   │   ├── game_service.py    # Game CRUD, state loading, messages, rollback
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
│   │   ├── narration.py       # NarrationOutput, NarrationContext, lenient parsing (parse_narration)
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

Three steps collect data locally (the only API call is the optional AI fill below):

| Step | Component | Data Collected |
|------|-----------|----------------|
| 0 | `EngineSelectionStep` | `engine`: `"none"` / `"narrative"` / `"fate_core"` / `"d6"` |
| 1 | `WorldConfigStep` | `worldConfig`: `{genre, difficulty, duration, hardcore, lore}` + `manualEntities`: `{npcs, locations, organizations}` |
| 2 | `CharacterCreationStep` | `characterData`: `{name, gender, occupation, description}` + engine-specific stats (traits, aspects, attributes, etc.) |

On "Create" click → calls `onComplete({engine, worldConfig, characterData, manualEntities})`. `characterData` is sent for every engine (free mode included) when not empty. For D6, the wizard keeps skills as `{name: dice added}` and sends `skills: [{attribute, name, dice_value}]` with the full code (attribute + added dice) and every attribute (2D when untouched); skills of another genre are dropped.

**AI fill ("✨ Enrichir avec l'IA").** The player writes a few words in "Contexte libre" (world step) or in the character "Description"; the button sends `POST /world/enhance` with `scope` (`"world"` / `"character"`), `engine`, `provider`, `model` and the whole form as `current`. One LLM call (`Purpose.WORLD_GEN`, prompts in `backend/prompts/world_enhance_prompt.py`) rewrites that text richer and fills the rest of the step: genre (only an existing slug), difficulty, duration, entities for `world`; name, gender, occupation and the selected engine's section for `character`: narrative traits; Fate aspects and the skill pyramid (1 at +4, 2 at +3, 3 at +2, 4 at +1, completed from the current sheet then the list); D6 attributes (1D–5D, 18D total) and skills (dice added to the attribute, at most 2D each, up to 7D). Skills come only from the genre's list (`engine_data.py`, keyed by genre slug, mirrored in `frontend/lib/game/engineConfig.js`). `services/world_enhance.py` validates every field and falls back to the form's current value; the player's entities are kept, and a skill proposal with nothing usable keeps the current skills. An empty text invents the step from the form's other choices ("✨ Inventer avec l'IA"). Re-roll ("✨ Nouvelle version", shown while the text is an AI version): each click starts from the player's own state, never from the previous AI version — `lib/game/enhanceBase.mjs` remembers each fill as `{base, result}` and sends a field still holding an AI result as its base; AI-suggested entities carry their AI version in `suggested` (✨ until edited) and are left out of the next request. Errors: 400 (unknown scope/engine/provider, no API key), 422 (form over 20 000 characters or over 20 entities of a kind, before any LLM call), 502 (no usable JSON), 429 (10 calls/min per IP). The step is disabled while the call runs.

**Undo / redo.** The whole form (`engine`, `worldConfig`, `characterData`, `manualEntities`) lives in one history (`hooks/useFormHistory.js` over the pure `lib/game/formHistory.mjs`, tested by `npm test`). Every change, by the player or the AI fill, is an entry; successive edits of the same field (typing, clicks on one skill) are merged into one entry until another field changes or the field loses focus; the long texts (lore, description) are also cut after a 2 s pause, like a text editor. Buttons in the step card and Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z, Ctrl/Cmd+Y; undoing a change made on another step goes back to that step. Step navigation is not recorded.

**Draft (world being created).** The wizard's `{ step, form }` is saved on every change and survives a reload or a closed tab. Layers, each replaceable on its own: `lib/game/wizardForm.mjs` (steps, empty form), `lib/game/wizardDraft.mjs` (draft format `{ version, step, form, open, savedAt }`, validation, blank check), `lib/game/draftStores.mjs` (stores with an async `{ load, save, clear }` interface; `localDraftStore` keeps one draft per user in `localStorage` under `ldvelh.wizardDraft.<userId>`, a server store can replace it), `hooks/useWizardSession.js` (lifecycle). The wizard only takes `initialDraft` and reports `onSnapshot`. A reload while the wizard is open (`open: true`) goes straight back to it at the same step; leaving it ("Annuler") keeps the draft as a "Création en cours" card in the game list (Reprendre / Supprimer). One draft at a time: "Nouvelle aventure" replaces it at the first change only; an emptied form drops it; creating the game drops it (`handleWizardComplete(data, { onCreated })`). The undo history does not survive a reload. Bump `DRAFT_VERSION` when the form shape changes: older drafts are then ignored.

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

**Files:** `backend/api/routes.py` — `_handle_chat()` (adapter), `backend/pipeline/init_flow.py` — `run_init()`

INIT mode is detected when the game snapshot has `world_created == False`.

1. **Build prompt**: `get_full_generation_prompt(mandatory_npcs, theme_preferences, engine, world_config, character_data, manual_entities)`
   - **File:** `backend/prompts/world_generation_prompt.py`
   - System prompt: world-building instructions in French, entity constraints (3-6 NPCs, 4-5 locations, 1-3 orgs), JSON output format
   - User prompt: example JSON, engine-specific sections, manual entity constraints, genre/difficulty

2. **Stream LLM**: `narration_stream.stream_narration(session, sink, system_prompt=..., messages=..., world_gen=True)`
   - **File:** `backend/pipeline/narration_stream.py`
   - Uses `max_tokens_init` (higher limit for world gen)
   - Sends `SSEEvent.PROGRESS` every ~500 characters with the partial raw JSON
   - Frontend uses partial JSON to show real-time progress bar

3. **Completion** (in `run_init`, once the stream ends):
   - Validates JSON as `WorldGeneration` Pydantic model
   - Calls `game_service.process_init(game_id, world_gen, finalize=...)` which calls `WorldPopulator.populate()`; the engine + world config, the engine character (if engine != "none") and the game duration are written by `finalize` in the same transaction: the world is saved whole or not at all (#79). As in `run_turn`, the connection is acquired first (a cancellable wait), then the transaction and the initial Director start run under `finish_despite_cancel`: a disconnect once the save has started, COMMIT included, never leaves a saved world without its initial Director
   - Starts the initial Director (30 s timeout) right after the save, as its own task registered in `pipeline/director_runs.py`, and waits for it, so a connected client gets its `status` events first
   - Loads canonical state, builds `SSEDonePayload` with `world_info`, sends `SSEEvent.DONE` then `SSEEvent.SAVED`
   - A client gone after the world is saved: the Director finishes in the background and the game lock is released without waiting for it. The game's next turn (the arrival) waits for that Director, at most for what is left of its 30 s, so its context has the plan; it holds the game lock meanwhile (by design: only the first turn after a disconnect during world generation can wait, and never longer than the Director's own timeout); a scheduled Director is never started while another one runs for the game (#79)

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
16. Store generation metadata (games.updated_at, extraction_log entry with entity/relation counts)
17. Caller's `finalize(conn)` (from `run_init`): engine + world_config and game duration on `games`,
    engine character (Fate Core: character_fate + skills_fate; D6: character_d6 + skills_d6)
```

`populate` uses the caller's connection when given (`run_init` acquires it before the shield, see 2.5), else one from the pool.

**DB tables written:** games, locations, protagonists, personal_assistants, organizations, characters, objects, protagonist_inventory, entity_registry (auto via triggers), relations, narrative_arcs, facts, events, chronology, extraction_log; and through `finalize`: games (engine, world_config, game_duration), character_fate + skills_fate (Fate Core) or character_d6 + skills_d6 (D6).

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
  → POST /chat → routes._handle_chat (snapshot, API key, LLMSession, TurnContext)
    → pipeline.turn.run_turn
      → load       player input, context from DB (ContextBuilder), pending roll
      → arbitrate  mechanical step and dice (Fate Core may pause: roll_pending)
      → narrate    narrator prompts, history, stream from the LLM, SSE chunks, lenient parsing
      → commit     ONE transaction: roll effects, state, deltas, messages
      → respond    SSE done + saved
      → schedule   extraction and Director (fire-and-forget)
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

#### 3.2 Backend: the turn pipeline (LIGHT mode)

**Files:** `backend/api/routes.py` (adapter), `backend/pipeline/turn.py` (`run_turn`), `backend/pipeline/steps/*.py`

LIGHT mode is the default when `world_created == True` (the first turn after world generation is a FIRST_LIGHT turn through the same pipeline).

**Layers.** `api/` (routes, `SSEWriter`) talks HTTP and SSE only. `pipeline/` orchestrates a turn and knows nothing of FastAPI or SQL: it sends events through the `EventSink` port (`pipeline/ports.py`) that `SSEWriter` satisfies. SQL lives in `repos/` (`games.py`, `turns.py`, `users.py`); pure types in `domain/`. Only `api/` imports FastAPI: services raise domain errors (`GameNotFound`, `GameAccessDenied`) that `api/http_errors.py` answers with 404 / 403. `tests/test_architecture.py` enforces these dependency rules and that `_handle_chat` stays under 80 lines.

**Adapter.** `_handle_chat` loads the game snapshot, resolves the API key, builds an `LLMSession` and a `TurnContext`, then calls `run_turn` (or `run_init` when the world is not created). Any exception is caught there once and sent by `report_error`. The session belongs to the authenticated user (usage is attributed to them). `TurnContext` builds one `GameService` per turn (`ctx.games`: game state, narrator history); steps read genres and set the engine through `repos/games.py`.

**Steps** (each a module in `pipeline/steps/`, run in order by `run_turn`):

| Step | Role |
|------|------|
| `load` | Pending roll, player input (the stored action on a resume), context from the DB (step 1 below) |
| `arbitrate` | Mechanical step, dice, pending Fate roll (step 2); may return `HALT` and end the turn |
| `narrate` | Narrator prompts and message history, streams the narration, parses it leniently (steps 3, 4, 5) |
| `commit` | Writes everything of the turn in one transaction (step 6) |
| `respond` | Sends `done` then `saved` |
| `schedule` | Starts extraction and the Director in the background |

**Transaction.** The roll is *computed* before the narration (the narrator needs it) but *applied* at commit. `commit_turn` writes roll effects (stress, fate points), narration state, narrator deltas, engine snapshot, both messages, the roll log (or the claim of the resumed pending roll) and the engine lock in a single transaction (`repos/turns.py`). A failure or a cancellation anywhere before it leaves nothing behind (#16, #20). Credit deltas are stored as the ledger applied them (`applied`, `error`), not as the narrator asked (#33); a refused debit is reported to the narrator on the next turn.

**Lenient narration parsing** (`schema/narration.py`, `parse_narration`). An optional field that is invalid (for example a malformed `day_transition` object) is ignored instead of discarding the turn; `day_transition` accepts `true`, a string or a partial object; `false`, `0`, `0.0` and the strings `null`, `false`, `none`, `aucune`, `non`, `no` (any case) mean no transition. A narration that cannot be used at all raises `narration_invalid`.

**Errors.** A failure during a turn produces exactly one `error` event, in French, with a `code` and a `ref` (the stream id, also in the logs as `[TURN:<ref>]`); SQL, Pydantic or SDK text is never sent (#45).

| Code | Recoverable | Meaning |
|------|-------------|---------|
| `provider_auth` | no | Provider rejected the API key |
| `provider_rate_limit` | yes | Provider rate limit (429) |
| `provider_error` | yes | Any other provider failure |
| `narration_invalid` | yes | The narration could not be parsed or validated |
| `internal` | yes | Unexpected error; the message gives the `ref` to report |
| `world_gen_failed` | yes | World generation failed (INIT) |
| `game_not_found` | no | No such game |
| `no_api_key` | no | No API key for the chosen provider |
| `invalid_invocation` | yes | Aspect invocation refused (unknown aspect, or more invocations than fate points; duplicates count once) |
| `roll_not_pending` | yes | The roll to resume is not pending (already resolved or expired) |
| `saved_display_failed` | no | The turn (or world) was saved, but a later step (summary log, done payload, background scheduling) failed: reload, do not resend |

**Logging.** One INFO line per completed turn: `[TURN] game= engine= provider= model= history= in= out= cache_read= cost=$0.0000 ms=`. Prompts and narrator JSON are logged at DEBUG only, and only when `LOG_PROMPTS=true`.

A turn that stops on a pending roll (HALT) logs `[TURN] game= engine= provider= halted=roll_pending ms=` instead (no tokens, no cost: nothing was narrated). `[CHAT] Deltas applied` (DEBUG) always has the shape `{"credit": {amount, description, applied, new_balance, error} | null, "compel": {...} | null}`. Story text never reaches WARNING or above: a pydantic `ValidationError` cause is logged as its field paths and error types (`utils/log_safe.py`; the full traceback only at DEBUG with `LOG_PROMPTS=true`), the arbiter's `reason` is DEBUG-only, and an unparsable narration logs its length at ERROR and an excerpt at DEBUG with `LOG_PROMPTS=true`. A failure after the save is logged once, at ERROR, by `report_error` (or by `finish_despite_cancel` when the client is gone), with its cause.

**Disconnect.** `start_chat` attaches the turn task to its `SSEWriter` (`attach`); closing the stream (Cancel, tab closed) marks it `disconnected` and cancels the task. Nothing is committed, the game lock is released, and the next message is accepted at once (a writer whose client is gone does not count as busy; the new turn queues behind it). Every accepted writer is registered in `api/game_writers.py` from `start_chat` until its own task is done (done callback), so a task cancelled before its first step leaves no entry, and a queued resend cancelled meanwhile does not make the next message look busy while an older client-less turn still holds the lock (#79). The busy decision (C-13) is `game_writers.is_busy`. The commit's connection is acquired before the shield, so a disconnect while the pool is exhausted still cancels the turn (nothing saved). Once the commit has started, the commit itself, `respond` and `schedule` run under `finish_despite_cancel` (`pipeline/uncancellable.py`): a disconnect at that moment does not lose the done payload or the background work. A failure there is logged; a `BaseException` that is not an `Exception` is logged, then re-raised. Likewise, once `done` is queued on the writer, a disconnect no longer cancels the turn, and everything after the commit is shielded.

**Step 1: Load context**

The pending roll is loaded first: on a resume (`roll_id` of the pending roll), the stored action is the turn's input from the start, for the context, the narrator and the saved user message, whatever the request carried. Otherwise the received message is used (`__ARRIVEE__` is narrated as the genre's arrival text and saved as the token). A new pending roll that hits the one-pending-per-game index (another one was stored after load) is dropped and the stored one is offered again (`roll_pending`), as for any message while a roll waits (#79).

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

**Step 2: Mechanical step (engine-aware), `arbitrate`**

If `engine.needs_mechanical_step()` returns True (Fate Core or D6):

```python
mechanical = await run_mechanical_step(engine, engine_stats, player_message,
                                       context_summary, world_difficulty, session)
```

**File:** `backend/services/engine/mechanical_service.py` — `run_mechanical_step()`

1. Builds a mechanical context prompt (player message + engine stats + world difficulty)
2. Calls Haiku model to get a `MechanicalDecision` JSON:
   ```json
   {"requires_test": true, "skill": "Athlétisme", "skill_value": 3, "difficulty": 4, "reason": "..."}
   ```
3. If `requires_test`: calls `engine.roll_dice(decision)` → returns `RollResult`
4. Keeps the roll effects for the commit (they are applied there, in the turn transaction, only if the turn is saved)
5. Sends `SSEEvent.ROLL_RESULT` to frontend for dice display (before the narration)

**Invocation pause (Fate Core):** `arbitrate` asks the engine `engine.invocation_offer(roll, engine_stats)`; Fate Core offers one when the roll failed and the player has fate_points > 0 and aspects (other engines never do). On an offer the pipeline **pauses**:
- Stores the roll in `mechanic_rolls` with `status = 'pending'` (migration `20261017000000`: `pending` / `resolved` / `expired`) and the player's message (at most one per game)
- Sends `SSEEvent.ROLL_PENDING` with `{roll_id, roll, aspects, fate_points}`
- Returns `HALT`: the stream closes, nothing else is committed
- Frontend shows aspect invocation modal → player selects aspects
- Frontend sends new `POST /chat` with `roll_id + invoked_aspects`
- Backend validates the invocation (known aspects, enough fate points, duplicates count once; otherwise `invalid_invocation`), applies +2/aspect to the original roll, recalculates outcome and narrates the stored message; the commit claims the roll (`status = 'resolved'`) once, a second resume gets `roll_not_pending`
- Any other `POST /chat` while the roll waits gets the same `roll_pending` again, and `GET /games/{id}` returns it as `state.pending_roll` (with `player_message`) so the modal and the waiting action come back after a reload; a rollback expires it

**Step 3: Build narrator prompts**

**File:** `backend/prompts/narrator_prompt.py`

```python
system_prompt = build_narrator_system_prompt(engine_type)
context_prompt = build_narrator_context_prompt(context, engine_type, mechanical)
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

**Files:** `backend/pipeline/steps/narrate.py`, `backend/pipeline/narration_stream.py`

- Calls `provider.stream(system_prompt, messages, temperature, max_tokens)`
- For LIGHT mode: extracts displayable narrative text in real-time
- Sends `SSEEvent.CHUNK` for each text delta
- On completion: parses full JSON response, calls `on_complete` callback

**Step 6: commit, respond, schedule**

**Files:** `backend/pipeline/steps/commit.py`, `respond.py`, `schedule.py`; SQL in `backend/repos/turns.py`

1. **Commit** (one transaction): roll effects, game state (cycle, time, location, NPCs present), narrator deltas (credit transactions, entity reveals), stored `info_requests` for the next turn's prefetch, engine snapshot, user and assistant messages (with narrator_deltas), roll log or claim of the resumed roll
2. **Respond**: `SSEEvent.DONE` with display text, fresh normalized game state and cost, then `SSEEvent.SAVED`
3. **Schedule**: resolver and, if `extraction_triggers` is non-empty, extractors, plus the Director when its interval has elapsed, all as fire-and-forget tasks

#### 3.3 Frontend: Receiving Events

**Files:** `frontend/lib/chatStream.mjs` (`runChatStream`, pure, tested by `npm test`) and `frontend/hooks/useStreaming.js` (`startStream()`: cancellation + dispatch)

SSE events dispatched to callbacks in `useGameOrchestrator`. A stream that is not cancelled always ends with exactly one terminal event (`done`, `error` or `roll_pending`); the client synthesizes it when the server gives none, so the "turn in progress" state can never stay stuck (#35): HTTP error → `error` with `status` (FastAPI `detail` as message); stream closed without a terminal event or network failure → `error` with `interrupted: true` (recoverable, "Réessayer"); a 401 refreshes the session once (`refreshSession()` in `lib/api.js`, shared with the REST client) and retries, or sends to the login page. Every terminal callback ends the turn through one helper (`endTurn`).

| SSE Event | Callback | UI Effect |
|-----------|----------|-----------|
| `chunk` | `onChunk` | Appends text to last assistant message (streaming: true) |
| `roll_result` | `onRollResult` | Stores in `pendingRollRef` for attachment to next message |
| `roll_pending` | `onRollPending` | Shows aspect invocation modal (Fate Core) |
| `extracting` | `onExtracting` | Sets message to extracting state |
| `done` | `onDone` | Finalizes message (streaming: false), updates game state |
| `saved` | `onSaved` | Stops saving spinner, refreshes tooltips + world sidebar |
| `error` | `onError` | Shows error message |
| `save_unconfirmed` (client-side) | `onSaveUnconfirmed` | `done` came but `saved` never did: stops the spinner, shows a warning |

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
| `available_invocations(engine_stats)` | sync | Aspects the player may invoke and fate points (default: none) |
| `invocation_offer(roll, engine_stats)` | sync | What the player may spend on this roll before narration, or `None` (default); an offer pauses the turn |
| `apply_invocation(roll, invoked, aspects, fate_points)` | sync | The offered roll with the invoked aspects applied; default raises `NotImplementedError`, required from any engine that overrides `invocation_offer` (contract test) |
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
| `error` | `{error, details, recoverable, code, ref}` | Error occurred; `code` and `ref` on turn errors (see 3.2) |
| `warning` | `{message, details}` | Non-fatal warning |
| `roll_result` | `{roll}` | Dice roll result for display |
| `roll_pending` | `{roll_id, roll, aspects, fate_points}` | Fate Core invocation pause |

### SSEWriter

Async queue-based writer. Events are pushed via typed methods (`send_chunk`, `send_progress`, `send_done`, etc.) and consumed by `iterate()` which yields `data: {json}\n\n` lines. Includes 60-second keepalive timeout. `attach(task)` ties the turn task to the writer; when the client closes the stream, `disconnected` becomes true and the task is cancelled (see 3.2, Disconnect). If the stream itself fails server-side (e.g. an event that cannot be serialized), one `error` event is sent before the stream closes: `code: internal` with the stream `ref`, or `saved_display_failed` (not recoverable) once `done` was queued, then the turn is cancelled as on a disconnect (unless `done` was queued).

### Frontend Handling

**File:** `frontend/hooks/useStreaming.js`

`startStream(url, body)` runs `runChatStream` (`frontend/lib/chatStream.mjs`):
1. POSTs to backend with JSON body; a 401 refreshes the session once and retries
2. A non-2xx answer becomes one `error` event (`status`, FastAPI `detail`)
3. If response is `text/event-stream`: reads via `ReadableStream` reader, parses `data: ` events (`lib/sse.mjs`, partial events buffered)
4. No terminal event before the end → synthetic recoverable `error` (`interrupted: true`); `done` without `saved` → `save_unconfirmed`
5. Dispatches to callbacks: `onChunk`, `onProgress`, `onExtracting`, `onDone`, `onSaved`, `onSaveUnconfirmed`, `onError(message, details, { status, interrupted })`, `onRollResult`, `onRollPending`
6. Returns `{success, fullJson}`, `{success: false, interrupted}` or `{success: false, aborted}` on cancel

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
