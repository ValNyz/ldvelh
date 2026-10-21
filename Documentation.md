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
14. [Background jobs](#14-background-jobs)

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
│   │   ├── chosen_name.py     # Wizard PC name made authoritative over the world builder's
│   │   ├── context.py         # TurnContext, TurnRequest, InitParams
│   │   ├── init_params.py     # Wizard parameters stored on the game until its world exists (#88)
│   │   ├── narration_stream.py# Provider stream, partial-JSON chunks, display text
│   │   ├── narrative_scanner.py # NarrativeScanner: incremental narrative_text extraction (#90)
│   │   ├── json_escape.py     # JSON string escape decoder for a partial stream (#90)
│   │   ├── errors.py          # report_error: exception → one French TurnError
│   │   ├── ports.py           # EventSink protocol (SSEWriter satisfies it)
│   │   ├── uncancellable.py   # finish_despite_cancel (commit and post-commit part)
│   │   ├── post_turn.py       # run_post_turn: resolver, extraction, then the post-turn hooks (one supervisor job per turn)
│   │   ├── director_runs.py   # Initial Director run (a supervisor job the first turn waits for)
│   │   └── steps/             # load, arbitrate, narrate, commit, respond, schedule
│   ├── domain/                # Pure types: turn.py (PendingRoll, AppliedDeltas, NarrationState), errors.py (TurnError), game.py, identity.py (identity value types and failures: NewEntitySpec, AliasSpec, EntityRef, FactRef, RevealOutcome, MergeOutcome, ResolvedRef, IdentityFailure and subclasses)
│   ├── workers/               # Process-level concurrency, imports no other layer
│   │   ├── supervisor.py      # Per-game background job queue (enqueue, wait_idle, cancel_game, drain)
│   │   └── game_locks.py      # Per-game turn lock (hold, is_held), idle entries purged
│   ├── llm/                   # LLMSession, usage, call_log.py (CallLog: buffered llm_calls rows, flushed once per phase, #106)
│   ├── repos/                 # SQL: games.py, turns.py (SQL of the turn's own rows: messages, rolls, turns), uow.py (unit of work: transaction journaled under a turn, `hold_source_message`), llm_calls.py (call log), users.py, llm_models.py
│   ├── services/
│   │   ├── game_service.py    # Game CRUD, state loading, messages, rollback
│   │   ├── context_builder.py # Builds NarrationContext from DB
│   │   ├── state_normalizer.py# Normalizes game state for frontend
│   │   ├── hooks.py           # Post-turn hooks: on_turn_committed, on_new_cycle (registry, runners)
│   │   ├── turn_effects.py    # What a narration changes at commit: `apply_narration_state`, `apply_narrator_deltas` (credit, reveals, compel)
│   │   ├── subscribers.py     # Default subscribers: scheduled Director, engine new-cycle work, seed archiving
│   │   ├── director_service.py# Director run: collect, LLM call, apply
│   │   ├── director_context.py# Director run, collect step (reads, no connection kept during the call)
│   │   ├── director_apply.py  # Director run, apply step (plan and arcs in one transaction)
│   │   ├── auth_service.py    # JWT, password hashing, email verification
│   │   ├── engine/            # Game engine system (strategy pattern)
│   │   │   ├── __init__.py    # get_engine() factory
│   │   │   ├── base.py        # BaseEngine ABC
│   │   │   ├── none.py        # NoneEngine (free narrative, no mechanics)
│   │   │   ├── narrative.py   # NarrativeEngine (traits-based resistance)
│   │   │   ├── fate_core.py   # FateCoreEngine (4dF, aspects, stress)
│   │   │   ├── fate_aspects.py# Protagonist aspects with their kind (aspects_fate table, #93)
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
│   ├── repos/
│   │   └── entities.py        # Entity identity SQL: find_entity, registry, aliases, domain rows, merges
│   ├── services/identity/     # IdentityService: create_entity, resolve_ref, update_entity, reveal, merge; reveals.py: `apply_entity_reveals`, `reveal_location`
│   ├── kg/                    # Knowledge Graph layer
│   │   ├── reader.py          # KnowledgeGraphReader (SELECT queries)
│   │   ├── populator.py       # KnowledgeGraphPopulator (writes by entity id; creates no entity)
│   │   ├── refs.py            # References resolved at the edge (required / optional)
│   │   ├── item_writes.py     # Per-item SAVEPOINT writes (write_item, write_items)
│   │   ├── upsert_sql.py      # Guarded SET lists for re-listed entity upserts
│   │   ├── semantic_keys.py   # Fact semantic keys (protagonist:*)
│   │   └── specialized_populator.py  # WorldPopulator, ExtractionPopulator
│   ├── prompts/
│   │   ├── narrator_prompt.py # System + context prompts for narration
│   │   ├── world_generation_prompt.py # World gen prompts
│   │   ├── mechanical_prompt.py       # Mechanical decision prompts
│   │   └── extraction/        # Per-extractor prompt modules
│   ├── schema/                # Pydantic models
│   │   ├── core.py            # Base types (Name, ShortText, GameTime, PROTAGONIST_REF, etc.)
│   │   ├── coerce.py          # coerce_json_list, coerce_json_dict (shared validators for JSON-encoded fields)
│   │   ├── columns.py         # Entity field bounds: min(product limit, column width)
│   │   ├── entity_changes.py  # EntityUpdate.changes typed per column (bound_changes)
│   │   ├── narration.py       # NarrationOutput, NarrationContext, lenient parsing (parse_narration)
│   │   ├── world_generation.py# WorldGeneration schema
│   │   ├── engine.py          # Engine types, MechanicalDecision, RollResult
│   │   ├── extraction.py      # Extraction models
│   │   ├── sse_payload.py     # SSE payload models
│   │   ├── entities.py        # Entity models (Character, Location, etc.)
│   │   ├── relations.py       # Relation models
│   │   └── narrative.py       # Narrative arc models
│   └── tests/                 # 2500+ tests, CI coverage floor 91%
├── frontend/
│   ├── app/
│   │   ├── page.js            # Main page, phase routing
│   │   ├── layout.js          # Root layout
│   │   └── (auth)/            # Login, register, verify pages
│   ├── hooks/
│   │   ├── useGameOrchestrator.js  # All game business logic
│   │   ├── useWizardSession.js     # Wizard drafts: new world, one per game not generated yet
│   │   ├── useGenres.js            # Genres from GET /genres, genre labels
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
│   │   ├── WorldPendingScreen.jsx     # World not created yet: its parameters, retry or edit (#88)
│   │   ├── WorldRetryActions.jsx      # Retry / edit parameters / back buttons (#88)
│   │   ├── CharacterSheet.jsx # Full character sheet overlay
│   │   ├── AspectInvocationModal.jsx  # Fate Core invocation modal
│   │   ├── Sidebars.jsx       # Inventory + World sidebars
│   │   └── wizard/            # World creation wizard (3 steps)
│   └── lib/
│       ├── api.js             # API client with auth headers + 401 retry
│       ├── AuthContext.js     # Auth context provider
│       └── game/
│           ├── gameState.js   # Default state, merge utilities
│           ├── characterSheet.mjs # Character sheet display from player.sheet (#93)
│           └── engineConfig.js# Engine options, genre/difficulty constants
└── db/migrations/             # Schema: baseline + incremental migrations (dbmate format)
```

### Key Design Patterns

- **Strategy Pattern**: `get_engine(engine_type)` returns a `BaseEngine` subclass. All engine-specific logic (dice, stats, prompts, progression) goes through this abstraction.
- **Reader/Populator Separation**: `kg/reader.py` handles all SELECTs, `kg/populator.py` handles all INSERTs/UPDATEs. They share the same `(pool, game_id)` constructor.
- **SSE Streaming**: All real-time communication uses an async queue (`SSEWriter`) that serializes events as `data: {json}\n\n` lines.
- **Narrator Deltas**: The narrator LLM outputs live deltas (credits, inventory hints, entity reveals) applied immediately — no extraction needed for these.
- **Batch Extraction**: Heavier extraction (characters, locations, orgs, arcs, inventory, progression) runs as a background job on the game's supervisor queue (see §14), never skipped.

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

**AI fill ("✨ Enrichir avec l'IA").** The player writes a few words in "Contexte libre" (world step) or in the character "Description"; the button sends `POST /world/enhance` with `scope` (`"world"` / `"character"`), `engine`, `provider`, `model` and the whole form as `current`. One LLM call (`Purpose.WORLD_GEN`, prompts in `backend/prompts/world_enhance_prompt.py`) rewrites that text richer and fills the rest of the step: genre (only an existing slug), difficulty, duration, entities for `world`; name, gender, occupation and the selected engine's section for `character`: narrative traits; Fate aspects and the skill pyramid (1 at +4, 2 at +3, 3 at +2, 4 at +1, completed from the current sheet then the list); D6 attributes (1D–5D, 18D total) and skills (dice added to the attribute, at most 2D each, up to 7D). Skills come only from the genre's list (`engine_data.py`, keyed by genre slug, mirrored in `frontend/lib/game/engineConfig.js`). `services/world_enhance.py` validates every field and falls back to the form's current value; the player's entities are kept, and a skill proposal with nothing usable keeps the current skills. An empty text invents the step from the form's other choices ("✨ Inventer avec l'IA"). Re-roll ("✨ Nouvelle version", shown while the text is an AI version): each click starts from the player's own state, never from the previous AI version — `lib/game/enhanceBase.mjs` remembers each fill as `{base, result}` and sends a field still holding an AI result as its base; AI-suggested entities carry their AI version in `suggested` (✨ until edited) and are left out of the next request. Errors: 400 (unknown scope/provider, no API key), 422 (unknown engine), 422 (form over 20 000 characters or over 20 entities of a kind, before any LLM call), 502 (no usable JSON), 429 (10 calls/min per IP). The step is disabled while the call runs.

**Undo / redo.** The whole form (`engine`, `worldConfig`, `characterData`, `manualEntities`) lives in one history (`hooks/useFormHistory.js` over the pure `lib/game/formHistory.mjs`, tested by `npm test`). Every change, by the player or the AI fill, is an entry; successive edits of the same field (typing, clicks on one skill) are merged into one entry until another field changes or the field loses focus; the long texts (lore, description) are also cut after a 2 s pause, like a text editor. Buttons in the step card and Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z, Ctrl/Cmd+Y; undoing a change made on another step goes back to that step. Step navigation is not recorded.

**Draft (world being created).** The wizard's `{ step, form }` is saved on every change and survives a reload or a closed tab. Layers, each replaceable on its own: `lib/game/wizardForm.mjs` (steps, empty form), `lib/game/wizardDraft.mjs` (draft format `{ version, step, form, open, savedAt, gameId?, submitted? }`, validation, blank check), `lib/game/draftStores.mjs` (stores with an async `{ load(gameId?), save(draft), clear(gameId?), gameIds() }` interface; `localDraftStore` keeps, per user in `localStorage`, the draft of the world not created yet under `ldvelh.wizardDraft.<userId>` and one draft per unfinished game under `ldvelh.wizardDraft.<userId>.<gameId>`; a server store can replace it), `lib/game/wizardParams.mjs` (server parameters to `__INIT__` parameters, and those back to a wizard form), `hooks/useWizardSession.js` (lifecycle). The wizard only takes `initialDraft` and reports `onSnapshot`. A reload while the wizard is open (`open: true`) goes straight back to it at the same step; leaving it ("Annuler") keeps the draft as a "Création en cours" card in the game list (Reprendre / Supprimer). One new-world draft at a time: "Nouvelle aventure" replaces it at the first change only; an emptied form drops it. Creating the game does not drop it (#88): `handleWizardComplete(data, { gameId, onCreated })` calls `onCreated(id)`, which moves the draft under the game's key (`gameId`, plus `submitted`: the parameters sent with `__INIT__`; it then leaves the list card), so another creation never overwrites it. A game's draft is dropped when its world exists (phase `WORLD_READY` or `PLAYING` for that game, `useWizardSession.forget`), when the game is deleted, and, on the first game list, when its game is gone (`prune`). Until then a failed generation offers « Réessayer » (resends `submitted`), « Modifier les paramètres » (reopens the wizard on the game's draft, else on the server's parameters, `GET /games/{id}` `init_params`; completing it sends `__INIT__` to the same game, no new `POST /games`) and « Retour aux parties ». Reopening a game with `world_created=false` no longer starts a generation by itself: it shows `WorldPendingScreen` (phase `WORLD_PENDING`) with the same three actions and the saved parameters (genre label from `hooks/useGenres.js`); without a local draft « Réessayer » sends a bare `__INIT__` and the server reuses the set it stored (§2.5). The undo history does not survive a reload. Bump `DRAFT_VERSION` when the form shape changes: older drafts are then ignored.

#### 2.3 Frontend: handleWizardComplete

**File:** `frontend/hooks/useGameOrchestrator.js`

```
handleWizardComplete(params, { gameId, onCreated })
1. id = gameId || games.createGame(engine)   → POST /games only for a new game
                                                (gameId: the wizard edited an unfinished game)
2. onCreated(id)               → the wizard draft moves under the game's key (#88)
3. gs.setGameId(id)
4. games.loadGames()           → refresh game list
5. generateWorld(id, params)   → phase GENERATING_WORLD, then sendChat({
     message: '__INIT__', engine, world_config, character_data, manual_entities
   }, id)
```
`generateWorld(id)` without parameters (a retry with no local draft) sends a bare `__INIT__`.

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

0. **Wizard parameters** (`pipeline/init_params.py`, #88): before the paid call, each `__INIT__` stores the parameters it sends on `games` (`engine`, `world_config`, `character_data`, `manual_entities`; `repos/games.save_init_params`, only while the game has no protagonist), outside the world transaction so a failed generation keeps them. An `__INIT__` that carries any of the three parts (`ChatRequest.model_fields_set`, `InitParams.carries_wizard`) replaces the stored set entirely: a part sent as `null` (the wizard sends `null` for no entities or no character) is cleared, never restored from an earlier attempt. A bare `__INIT__` (game list retry, another browser) reuses the stored set, so it generates the same world request (genre, lore, difficulty, duration, character sheet, manual entities). While the world is not created, `GET /games/{id}` returns the stored set as `init_params` (`{ engine, world_config, character_data, manual_entities }`), so the wizard can be prefilled in a browser without the draft. The wizard's genre slug also wins over a genre stored by an earlier attempt (`resolve_genre`). The three fields are bounded exactly like `/world/enhance`: both requests use the one type `api/request_types.WizardForm` (`ChatRequest` inherits it, `/world/enhance`'s `current` is one): 20 000 characters per part and for the whole form, 20 entities per kind; over → French 422, nothing stored, no LLM call.

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
   - Enqueues the initial Director right after the save as a `director_initial` job on the game's supervisor queue (`pipeline/director_runs.py`), and waits for it, so a connected client gets its `status` events first. The wait for a supervisor slot (at most `SUPERVISOR_MAX_GAMES` games run a job at once) comes before the Director's own 30 s timeout starts: under saturation the world's `done` waits for a slot, by design (bounding that wait could let the Director write `status` to a closed SSE sink). `director_runs` is reduced to this one job's registry (`start_initial`, the first turn's bounded wait); the scheduled Director is a post-turn hook
   - Loads canonical state, builds `SSEDonePayload` with `world_info`, sends `SSEEvent.DONE` then `SSEEvent.SAVED`
   - A client gone after the world is saved: the Director finishes in the background and the game lock is released without waiting for it. The game's next turn (the arrival) waits for that Director, at most for what is left of its 30 s, so its context has the plan; it holds the game lock meanwhile (by design: only the first turn after a disconnect during world generation can wait, and never longer than the Director's own timeout); the scheduled Director runs inside the game's `post_turn` job, which the supervisor queues behind the initial Director job, so the two never run at once (see §14)

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
    engine character (Fate Core: character_fate + aspects_fate + skills_fate; D6: character_d6 + skills_d6)
```

`populate` uses the caller's connection when given (`run_init` acquires it before the shield, see 2.5), else one from the pool.

**DB tables written:** games, locations, protagonists, personal_assistants, organizations, characters, objects, protagonist_inventory, entity_registry (auto via triggers), relations, narrative_arcs, facts, events, chronology, extraction_log; and through `finalize`: games (engine, world_config, game_duration), character_fate + aspects_fate + skills_fate (Fate Core) or character_d6 + skills_d6 (D6).

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
      → schedule   enqueues one post_turn job on the supervisor
```

### Step-by-step

#### 3.1 Frontend: Send Message

**File:** `frontend/hooks/useGameOrchestrator.js` — `handleSendMessage(content)`

```
1. Guard: check gameId, sendingRef
2. sendingRef.current = true (prevent concurrent sends)
3. setLastUserMessage(content) (for retry after an error, and the roll resume)
4. Add user message to UI immediately
5. gs.setLoading(true), gs.setSaving(true)
6. sendChat({message})
```

**One /chat body (#55).** Every `/chat` call (turn, `__INIT__`, `__ARRIVEE__`, roll resume, edit / resend / regenerate) goes through `sendChat(extra, gameId)`, whose body comes from `buildChatPayload` (`frontend/lib/game/chatRequest.mjs`): `{gameId, provider, model, ...extra}`. The client game state is not sent: the server always reloads it. `ChatRequest` ignores unknown fields (pydantic default, not `extra='forbid'`), so a frontend cached before #55 that still sends `gameState` keeps working during a deploy.

#### 3.2 Backend: the turn pipeline (LIGHT mode)

**Files:** `backend/api/routes.py` (adapter), `backend/pipeline/turn.py` (`run_turn`), `backend/pipeline/steps/*.py`

LIGHT mode is the default when `world_created == True` (the first turn after world generation is a FIRST_LIGHT turn through the same pipeline).

**Layers.** `api/` (routes, `SSEWriter`) talks HTTP and SSE only. `pipeline/` orchestrates a turn and knows nothing of FastAPI or SQL: it sends events through the `EventSink` port (`pipeline/ports.py`) that `SSEWriter` satisfies (same method shapes, checked by `tests/test_event_sink_contract.py`; `send_done(display_text, state=None, *, world=False)`, `world=True` for the world generation's done, #80). SQL lives in `repos/` (`games.py`, `turns.py`, `uow.py`, `llm_calls.py`, `users.py`); pure types in `domain/`. The connection pool is created by the lifespan in `main.py` and kept on `app.state.pool` (set to `None` once closed); routes get it through `api.dependencies.get_pool(request)`, which raises `RuntimeError` when it is missing, and `api/` never imports `main`. Only `api/` imports FastAPI: services raise domain errors (`GameNotFound`, `GameAccessDenied`) that `api/http_errors.py` answers with 404 / 403. `tests/test_architecture.py` enforces these dependency rules (existing breaches are frozen in `KNOWN_VIOLATIONS`, see CONTRIBUTING) and that `_handle_chat` stays under 80 lines.

**Turn journal (P5a, #105).** `load` opens a turn (`repos.turns.open_turn`: a `turns` row in status `open`, `ctx.turn_id`) and binds it to the `LLMSession`, so every LLM call of the request is logged under it. The commit runs under `repos.uow.uow(conn, ctx.turn_id)`: the transaction sets `ldvelh.turn_id` locally and the world writes of the turn are recorded in `world_changes` by the database triggers (§7). `mark_committed` is the last statement of the commit transaction. A turn halted on a pending roll, failed or disconnected stays `open` (its journal rows, if any, were written in the transaction that stored the pending roll); open turns are purged by the next rollback. A turn resuming a pending roll adopts its halted turn at commit (§7).

**Adapter.** `_handle_chat` loads the game snapshot, resolves the API key, builds an `LLMSession` and a `TurnContext`, then calls `run_turn` (or `run_init` when the world is not created). Any exception is caught there once and sent by `report_error`. The session belongs to the authenticated user (usage is attributed to them). `TurnContext` builds one `GameService` per turn (`ctx.games`: game state, narrator history); steps read genres and set the engine through `repos/games.py`.

**Steps** (each a module in `pipeline/steps/`, run in order by `run_turn`):

| Step | Role |
|------|------|
| `load` | Pending roll, player input (the stored action on a resume), context from the DB (step 1 below) |
| `arbitrate` | Mechanical step, dice, pending Fate roll (step 2); may return `HALT` and end the turn |
| `narrate` | Narrator prompts and message history, streams the narration, parses it leniently (steps 3, 4, 5) |
| `commit` | Writes everything of the turn in one transaction (step 6) |
| `respond` | Sends `done` then `saved`; `done.state.meta` carries `user_message_id` and `assistant_message_id`, the turn's saved messages (#55) |
| `schedule` | Starts extraction and the Director in the background |

**Transaction.** The roll is *computed* before the narration (the narrator needs it) but *applied* at commit. `commit_turn` writes roll effects (stress, fate points), narration state, narrator deltas, engine snapshot, both messages, the roll log (or the claim of the resumed pending roll) and the engine lock in a single transaction (`pipeline/steps/commit.py`: effects in `services/turn_effects.py`, SQL in `repos/turns.py`). A failure or a cancellation anywhere before it leaves nothing behind (#16, #20). Credit deltas are stored as the ledger applied them (`applied`, `error`), not as the narrator asked (#33); a refused debit is reported to the narrator on the next turn.

**Lenient narration parsing** (`schema/narration.py`, `parse_narration`). An optional field that is invalid (for example a malformed `day_transition` object) is ignored instead of discarding the turn; in an optional list (`entity_reveals`, `inventory_hints`, ...) only the invalid elements are dropped and the valid ones kept (logged as `entity_reveals[1]`), the whole list only when it is not a list (#80); `day_transition` accepts `true`, a string or a partial object; `false`, `0`, `0.0` and the strings `null`, `false`, `none`, `aucune`, `non`, `no` (any case) mean no transition. A narration that cannot be used at all raises `narration_invalid`. Narrator clock times (`time.new_time`, event `planned_time`, extractor `time`) go through the `GameTime` type (`schema/core.py`): `9h5`, `09:05`, `21H30` become `09h05`; anything else (`vers 10h`, `24h00`) becomes `None`, logged as `[GameTime] <field>: unusable time ignored` (no value at WARNING), and the commit step keeps the game's previous time (#86). A world-generation `arrival_event.time` that is unusable falls back to `DEFAULT_GAME_TIME` (`08h00`, `schema/core.py`) with a warning, so world creation never fails on it. A bare-string or non-object `time` in the narration is tolerated too. `day_transition.new_date` is a `Tag` (50 chars, the column width): longer dates are truncated.

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
| `saved_display_failed` | no | The turn (or world) was saved, but a later step (summary log, done payload, background scheduling) failed: reload, do not resend. The message names the action ("Ton action est enregistrée, …") or, for world generation, the world ("Ton monde est enregistré, …", #80) |
| `game_busy` | yes | Another `/chat` is already running for this game (C-13): "Une action est déjà en cours pour cette partie. …" (#80) |

**Logging.** One INFO line per completed turn: `[TURN] game= engine= provider= model= history= in= out= cache_read= cost=$0.0000 ms=`. Prompts and narrator JSON are logged at DEBUG only, and only when `LOG_PROMPTS=true`.

A turn that stops on a pending roll (HALT) logs `[TURN] game= engine= provider= halted=roll_pending ms=` instead (no tokens, no cost: nothing was narrated). `[CHAT] Deltas applied` (DEBUG) always has the shape `{"credit": {amount, description, applied, new_balance, error} | null, "compel": {...} | null}`. Story text never reaches WARNING or above: a pydantic `ValidationError` cause is logged as its field paths and error types, and a database error (asyncpg server or argument-encoding error, which can quote the rejected value) as its class, SQLSTATE and constraint / table / column / argument names (`utils/log_safe.py` `safe_text` / `log_cause` / `log_exception`; the full message or traceback only at DEBUG with `LOG_PROMPTS=true`; the same summary goes into `stats["errors"]` and `extraction_logs`), the arbiter's `reason` is DEBUG-only, and an unparsable narration logs its length at ERROR and an excerpt at DEBUG with `LOG_PROMPTS=true`, and a truncated LLM value logs its field and lengths at WARNING and a 60-char preview at DEBUG with `LOG_PROMPTS=true`. A failure after the save is logged once, at ERROR, by `report_error` (or by `finish_despite_cancel` when the client is gone), with its cause.

**Disconnect.** `start_chat` attaches the turn task to its `SSEWriter` (`attach`); closing the stream (Cancel, tab closed) marks it `disconnected` and cancels the task. Nothing is committed, the game lock is released, and the next message is accepted at once (a writer whose client is gone does not count as busy; the new turn queues behind it). Every accepted writer is registered in `api/game_writers.py` from `start_chat` until its own task is done (done callback), so a task cancelled before its first step leaves no entry, and a queued resend cancelled meanwhile does not make the next message look busy while an older client-less turn still holds the lock (#79). The busy decision (C-13) is `game_writers.is_busy`. The per-game turn lock itself lives in `workers/game_locks.py` (`hold`, `is_held`): its entry is dropped once no turn holds or awaits it (#94). The commit's connection is acquired before the shield, so a disconnect while the pool is exhausted still cancels the turn (nothing saved). Once the commit has started, the commit itself, `respond` and `schedule` run under `finish_despite_cancel` (`pipeline/uncancellable.py`): a disconnect at that moment does not lose the done payload or the background work. A failure there is logged; a `BaseException` that is not an `Exception` is logged, then re-raised. Likewise, once `done` is queued on the writer, a disconnect no longer cancels the turn, and everything after the commit is shielded.

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
| Requested details | `get_entity_details_by_name()` | Entities the narrator requested last turn only: the set is replaced by every commit (empty when the turn requested nothing), so details are injected for one turn unless requested again (#64) |
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
- Any other `POST /chat` while the roll waits gets the same `roll_pending` again, and `GET /games/{id}` returns it as `state.pending_roll` (with `player_message`) so the modal and the waiting action come back after a reload; a rollback expires it. A pending roll is stored at the cycle before its turn and re-stamped with the turn's post-turn cycle when it is resolved, so rolling that turn back removes it (#134); a rollback also restores the engine state by replaying the journal (§7)

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
- For LIGHT mode: extracts displayable narrative text in real-time with `pipeline/narrative_scanner.NarrativeScanner` (#90): incremental (each chunk examined once, linear in the stream, including the search for the `"narrative_text":` key), it decodes `\uXXXX` escapes and surrogate pairs like `json.loads` (`pipeline/json_escape.py`) and holds back an escape cut off at the end of a chunk
- A lone surrogate (in the stream, at `parse_json_response`, and on the structured-output paths of `llm/session.py` via `utils.replace_lone_surrogates`) becomes U+FFFD: it could not be encoded to UTF-8 for the client
- Sends `SSEEvent.CHUNK` for each text delta
- On completion: parses full JSON response, calls `on_complete` callback

**Step 6: commit, respond, schedule**

**Files:** `backend/pipeline/steps/commit.py`, `respond.py`, `schedule.py`; turn effects (narration state, narrator deltas) in `backend/services/turn_effects.py`, SQL in `backend/repos/turns.py`

1. **Commit** (one transaction): roll effects, game state (cycle, time, location, NPCs present), narrator deltas (credit transactions, entity reveals), stored `info_requests` for the next turn's prefetch, engine snapshot, user and assistant messages (with narrator_deltas), roll log or claim of the resumed roll
2. **Respond**: `SSEEvent.DONE` with display text, fresh normalized game state and cost, then `SSEEvent.SAVED`
3. **Schedule**: enqueues one `post_turn` job on the game's supervisor queue (`pipeline/post_turn.py`, `TurnCommitted` event): the resolver, the extractors if triggered, then the post-turn hooks (new-cycle work, the Director when its interval has elapsed). It returns at once; see §14

#### 3.3 Frontend: Receiving Events

**Files:** `frontend/lib/chatStream.mjs` (`runChatStream`, pure, tested by `npm test`) and `frontend/hooks/useStreaming.js` (`startStream()`: cancellation + dispatch)

SSE events dispatched to callbacks in `useGameOrchestrator`. A stream that is not cancelled always ends with exactly one terminal event (`done`, `error` or `roll_pending`); the client synthesizes it when the server gives none, so the "turn in progress" state can never stay stuck (#35): HTTP error → `error` with `status` (FastAPI `detail` as message); stream closed without a terminal event or network failure → `error` with `interrupted: true` (recoverable, "Réessayer"); a 401 refreshes the session once (`refreshSession()` in `lib/api.js`, shared with the REST client) and retries, or sends to the login page. Every terminal callback ends the turn through one helper (`endTurn`).

| SSE Event | Callback | UI Effect |
|-----------|----------|-----------|
| `chunk` | `onChunk` | Appends text to last assistant message (streaming: true) |
| `roll_result` | `onRollResult` | Stores in `pendingRollRef` for attachment to next message |
| `roll_pending` | `onRollPending` | Shows aspect invocation modal (Fate Core) |
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
| `vitals_from_stats(stats)` | sync | Formatted vitals for frontend (`player.engine_stats`), from `get_stats`; `get_vitals_display(conn, game_id)` loads and formats |
| `sheet_from_stats(stats)` | sync | Read-only character sheet for frontend (`player.sheet`), from `get_stats`; `get_sheet_display(conn, game_id)` loads and formats. `load_game_state` calls `get_stats` once for both: Fate `aspects` [{type: high_concept/trouble/other, name}] with the kind stored in `aspects_fate`, `skills` [{name, level, label}], `stunts`; D6 `attributes` {name: dice}, `skills` [{attribute, name, dice_value}]; empty by default (narrative, none) |
| `create_character(conn, game_id, data)` | async | Create engine-specific character |
| `apply_roll_result(conn, game_id, roll)` | async | Apply mechanical consequences |
| `snapshot_turn_state(conn, game_id)` | async | Capture the state a turn's own transaction writes (Fate: stress, consequences, fate points; D6: wounds, force points; Narrative: nothing), stored with the assistant message |
| `restore_turn_state(conn, game_id, snapshot)` | async | Rollback: restore only that turn-owned state; progression (skills, aspects, traits) follows the cycle-based rollback |
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
| `d6` | `engine/d6.py` | NdD6 | Attributes + skills, wild die (6=explode, 1=complication: wild die counts as 0), wound track, force points |

### Dice Rolling

**Fate Core:** 4 Fudge dice (each: -1, 0, or +1) + skill value. Outcome: fail (<0 shifts), tie (0), success (1-2 shifts), success with style (3+ shifts).

**D6:** Roll NdD6 based on skill dice code (e.g. "3D+2"). One die is the "wild die": if it rolls 6, it explodes (reroll and add); if it rolls 1, it's a complication with a single penalty: the wild die counts as 0, the other dice are kept, and a complication flag is passed to the narrator.

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
| fate_core | `character_fate` (+ `aspects_fate`: one row per aspect with its kind, at most one high concept and one trouble) | `skills_fate` | `object_fate` |
| d6 | `character_d6` | `skills_d6` | `object_d6` |

### Engine Snapshot & Rollback

After each narration, the engine state is snapshot and stored on the assistant message (`messages.engine_snapshot` JSONB column). Since P5b (#22) the snapshot is **write-only** by default: the rollback restores the engine state (stress, fate points, wounds, force points...) by replaying the turn journal (§7), and only `ROLLBACK_ENGINE=cycle` (the pre-P5 rollback) still reads the last remaining message's snapshot. The write, the column and the SQL function go away with the cycle engine (removal tracked in #160, "Remove ROLLBACK_ENGINE=cycle, rollback_to_cycle and messages.engine_snapshot after one release").

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

`run_resolve_and_extract()`:
1. Filters triggers to valid names from `EXTRACTOR_MAP`
2. Creates extractor instances
3. Runs all in parallel via `asyncio.gather()`
4. Aggregates results and costs, and logs the real outcome of each extractor (`N succeeded, N partial, N failed, N skipped`)
5. Updates assistant message with extraction cost
6. Never skips a run: there is no "already extracting" guard any more. Concurrent turns are serialised by the game's supervisor queue (the extraction of turn N+1 runs after the one of turn N, #17, gate C-17)

Which extractors run: the narrator's triggers, plus the extractors of the entity types the resolver v2 created in the turn or linked while still a bare stub named for the first time (`TurnResolution.new_types`, `orchestrator.resolver_triggers`); a failed resolution keeps the narrator's triggers. Order inside the `post_turn` job: resolver v2, extraction, then the hooks, so the Director reads what was extracted.

Write guard (#23): every extractor transaction, the orchestrator's re-apply of narrator `entity_reveals`, the `on_new_cycle` hooks and the Director's apply take `SELECT 1 FROM messages WHERE id = $1 FOR SHARE` on the turn's assistant message first. The guard is part of the unit of work: `uow(conn, turn_id, source_message_id=...)` share-locks the message (`repos/uow.hold_source_message`) right after opening the transaction and raises `SourceMessageGone` when it is gone, and journals the writes under the turn (`BaseExtractor.run(turn_id=..., source_message_id=...)`; the progression extractor takes `turn_id` like the others, and the unused `run_triggered_extraction` was removed). A rollback deleting that message waits for the commit; a turn already rolled back writes nothing. The extraction cost append and the annotation `UPDATE messages` need no lock: they are no-ops once the message is deleted.

### Resolver v2 (#154, spec §4.5)

**Files:** `services/identity/resolution.py` (block, decide, apply), `services/identity/prepass.py` (prepass), `services/identity/decision.py` (parsing, verifications, cascade), `services/identity/candidates.py` (blocking), `services/identity/scene.py` (scene context), `prompts/identity_prompt.py`. Entry points: the three steps `IdentityService.block` / `decide` / `apply_resolution`, which `orchestrator.resolve_phase` runs apart so that no pool connection and no lock is held during a model call (#94): the scene and the candidates are read on one connection, the cascade reads merges through `repos.pooled.PooledReads`, and the application runs in the turn's unit of work (`uow`, source message share-locked; the decided links are checked again there: a merge committed meanwhile is followed, a link to an entity gone is dropped, event `link_stale`).

- **Blocking** (SQL, no model): the candidates of the whole narration (exact names, fuzzy `pg_trgm` and Levenshtein generators, occupations, the scene's context: present, place, recent messages, reveals, planned NPCs), at most `IdentityConfig.max_candidates`, each shown to the model as a card under its handle `E<n>` (an object's card says when the protagonist carries it, from `inventory` rows without owner; a candidate sharing a name with another shown one names it, with its type); a secret alias is never matched nor shown without an open disclosure.
- **Cascade**, one call per turn over the turn's candidates: the deterministic prepass (`services/identity/prepass.py`) links the unique exact names without the model, each decision at its own occurrence (`MentionDecision.start`), without a leading article or elision the matched name does not hold (« Le Terminal » takes « Terminal » for the entity « Terminal »); an exact name the protagonist does not know, written in full, is revealed (ALIAS true_name, no presence check, R36), while an unknown short form alone is a plain MATCH that reveals nothing; it leaves to the model a name the text continues (a number, or, where the pack's `case_marks_names` holds, a capitalised word in the same phrase), a name after a word of the pack's `other_markers` (within `IdentityConfig.other_marker_reach` words), a short form written or stored in lower case, and, where `case_marks_names` holds, a short form right after a capitalised word opening the sentence that is neither an article nor a title of the pack (« Elara Voss entre » may name another Voss), the last two listed to the model under TO CHECK; a model decision on an occurrence the prepass decided, under the same or another surface (« Terminal » inside « Le Terminal »), is dropped, never escalated, and counted (`overruled`) when it named something else; the small model (`Purpose.IDENTITY`, catalog role `identity`: Haiku on Anthropic) decides the rest, retried once on an invalid output; the strong model (`Purpose.IDENTITY_STRONG`, role `identity_strong`: Sonnet) is called at most once, only for the abstentions (UNSURE), the revealed true names and the links that would merge two entities. At most 2 `identity` calls and 1 `identity_strong` call per turn. `IdentityConfig.escalation = false` (`IDENTITY_ESCALATION`) keeps the small model's decisions (the cheap tier the evaluation measures with `--tier cheap`). A provider with no holder of a role falls back to its narration model; when the provider has rows carrying the role but none enabled (a catalog refresh retired or failed its holder), the session logs one WARNING (provider, roles, model ids) and `scripts/refresh_model_catalog.py` reports the optional role left without an enabled, priced holder (never moved: an operator sets it with `--set-role`).
- **Verifications** (code, never a guess): unknown handle, surface absent from the text, two mentions that talk to each other on one entity, a true name whose holder is not in the scene (model decisions only), a NEW without type, an ALIAS on the protagonist or the companion: the link is refused (UNSURE, the check's code kept) or downgraded (ALIAS without kind becomes MATCH). An unanswered escalation never applies the risky link (`escalation_unconfirmed`).
- **Output** (spec deviation, ruling R40): each mention is `{surface, before, decision, handle, alias_kind, new_type, new_kind, evidence, talks_to}`. The spec's §4.5.3 `category` is not asked: it named the gold corpus's categories, which the prompt never defined, and nothing but one telemetry payload read it (the `uncertain` event now carries no payload).
- **Secrets**: a card never shows a secret name as its label or usual place (a whole-secret entity is no candidate), nor does the scene the extractors read (`scene_entity_rows`) or a stored annotation label (`mentions_for_messages`): a secret label gives way to a descriptor or a known alias, a whole-secret entity is left out. A reveal of a secret name without an open disclosure is a `reveal_noop` with reason `secret_closed` (R42, R43).
- **Fallback**: when the small model fails twice, only the prepass applies (`resolver_fallback`); a failed resolution never stops the turn (logged at WARNING without story text, the extractors still run on the narrator's triggers).
- **Application**: a NEW creates its entity through `IdentityService.create_entity` (source `resolver`; a verified trap gets an internal suffix, an ambiguous label creates nothing), an ALIAS adds its surface as an alias (an introduction by a true name goes through the reveal table), the spans are placed before anything is written, so a decision that takes no span (a longer one took every occurrence) writes no alias, no reveal and no entity; every linked mention becomes `entity_mentions` rows (one per whole-word occurrence, `services/identity/mentions.place`), served by entity id (`/tooltips/annotations`, §12). The extractors then see the scene's entities by handle (`TurnResolution.scene_entities`).
- **Telemetry**: per turn, `TurnResolution.stats()` (mentions, deterministic, escalated, fallback, unsure, overruled, created, aliases, reveals) and the usage per purpose (calls, tokens, cost) go into the orchestrator's result (`resolver`) and one INFO log line of counts; the resolver's cost reaches the message's `extraction_cost` on every resolved turn, with or without extractors; the cascade's non-trivial decisions (rejections by code, `probable_duplicate`, `tombstone_redirected`, `link_stale`, `resolver_fallback`) are `identity_events` rows with codes, handles and counts, never a surface or a name. The escalation rate has a target and an alert level (`IdentityConfig.escalation_target_rate` 0.20, `escalation_alert_rate` 0.25, D29).
- **Evaluation**: the resolver v2 is measured offline on the identity gold corpus by `scripts/eval_identity.py --adapter v2` (`evals/identity/adapters/resolver_v2.py`, CONTRIBUTING.md "Identity evaluation"). PR 2 gate (hard pool ≥ 0.85, W ≤ 0.02, L = 0, escalation rate and cost per turn printed), frozen test split, 3 runs: hard pool 0.859 [0.804; 0.908], W 0.018, L 0, D 0.018, hard macro 0.869, EASY+PC+SKIP 0.960, C@10 0.980, escalation rate 0.265 (above the 0.20 target and the 0.25 alert level, D29; reported), cost about 0.0017 $ per turn (estimated), cheap tier alone hard pool 0.848 (`tests/reports/identity/2026-10-21-pr2-gate-anthropic-haiku-sonnet.md`; subagent responders, to confirm with 3 API runs when a key exists). Two test reads were made, against the one-read rule, by ruling R42 (user decision): the first failed on L = 69, an artefact of the evaluation's world loader, and was redone after the fixes. The PR 2 gate was measured on d482ca1; the fixes I1/I3/M1 that landed after it were checked on a 3-run dev confirmation (dev confirmation on eefbe58, 3 runs: hard pool 0.855 [0.821; 0.885], W 0.009 [0.003; 0.018], L 0, D 0.025, EASY+PC+SKIP 0.965, cheap tier hard pool 0.843, cost about 0.0021 $ per turn (estimated); the escalation rate rose to 0.328, above the 0.25 alert level; REVEAL fell to 0.795 (0.932 before) because an unknown short form no longer reveals the full name (I3, point-of-view correct, at a cost on the gold's REVEAL); protocol deviation: one responder of run 2 revised one answer after reading the next request and ran a no-op shell command, the answer was kept). The final review's fixes (prepass span overlap, sentence-start short forms, article left out of a prepass span) change decisions again and get a second dev confirmation: dev confirmation 2 on ec35813, 3 runs: hard pool 0.861 [0.830; 0.888], W 0.011 [0.005; 0.019], L 0, D 0.025, REVEAL 0.829, DESC 0.774, NEW 0.869, XTYPE 0.865, PART 0.912, GAP 0.978, EASY+PC+SKIP 0.935, cheap tier hard pool 0.851, cost about 0.0024 $ per turn (estimated); the PR 2 gate holds on dev. The escalation rate rose to 0.385 (0.328 at c8), further above the 0.25 alert level: short forms right after a capitalised word opening a sentence now go to the model under TO CHECK instead of being linked by the prepass (deterministic share 0.510), so the model, and its escalation, see more mentions. PR 5 re-reads test (R44). Deviations from the spec: no `category` in the output (R40); an exact unknown name in the narration, written in full, is revealed by the prepass (R36); corpus objects carry a protagonist-carried flag (test split refrozen, R39); cards never show a secret name and a merge keeps the survivor's own known flag (R42); a secret name is never revealed without an open disclosure (R43).

### Extractors

Each extractor (subclass of `BaseExtractor`):
1. Loads recent narrative context from DB
2. Builds system + user prompt for its domain
3. Calls Sonnet model with structured output (tool use)
4. Parses extraction result
5. Writes to DB via populator, in one transaction with one SAVEPOINT per item (`kg/item_writes.py` `write_item` / `write_items`, wrapped by `BaseExtractor._write_item` / `_write_items`): a failed item (validation, unique violation, FK, CHECK, or an SQL error swallowed inside the item) is rolled back alone and recorded as `"<label>: <cause>"` in `stats["errors"]`, the other items commit. Every run is logged in `extraction_logs` with its errors.

Values are bounded before SQL: `EntityUpdate.changes` goes through `schema/entity_changes.py` (one typed model per entity table; each varchar field is bounded by min(product limit, column width): `schema/columns.py` holds the bounded type of each field, shared with the creation models in `schema/entities.py`; the widths stay in the DB and a test checks every bound <= its `information_schema` width), so an over-long value is truncated to its bound and a mistyped field (a name in a uuid column, a non-boolean flag) is dropped alone, logged by field name only; the other fields of the update are kept. This is done once, in `KnowledgeGraphPopulator.update_entity`, the SQL sink every update path reaches (which also writes only those columns). List fields (`traits`, `hobbies`, `notable_features`) share one `StrList` type: a JSON array string or a bare string becomes a list. `Skill.level` is clamped to 1..5 (`skills_level_check`). Progression is applied by the engine as one item (atomic per message), except Fate skill upgrades, which are validated one by one (`FateSkillUpgrade`) and skipped alone when invalid.

Re-listed entities never wipe or reveal (#87): extractors often send an existing character, location or organization again in `entities_created`, with defaults for the fields they do not repeat. `IdentityService.create_entity(refill=True)` reuses the entity holding the label and fills a column a re-listing may fill (`service._REFILLABLE`) only when the new value is not NULL, blank (`''` or whitespace only) or `[]`, and never touches the names or `known_by_protagonist` (one found only through an alias, or contested, is left untouched); the SQL function `upsert_relation` likewise keeps an existing relation's `known_by_protagonist` (and a blank `context` keeps the stored one). The same holds for the other dedup upserts: a re-listed open arc (`create_narrative_arc`) keeps its intensity unless the extractor sends one, and a re-listed narrative-engine trait (`traits_narrative`, `NarrativeEngine.apply_progression`) keeps its description unless a non-blank one is sent. Only explicit reveals change visibility: narrator `entity_reveals`, `entities_updated[].now_known`, `relations_updated[].now_known`. On a new entity, `EntityCreation.known_by_protagonist` defaults to `true`, except when the extractor gives a `descriptor` without the flag: the character is then created hidden.

`run()` result: `success: True` only when everything committed without item errors; `success: False, partial: True` when some items failed and the rest committed; `success: False, error: "populate_failed"` when the transaction was rolled back (nothing was written; this includes a transaction already aborted outside any savepoint). The LLM `cost` is returned on every exit once the LLM was called (`empty_response` and unexpected errors included).

| Extractor | What it extracts | DB writes |
|-----------|-----------------|-----------|
| Characters | New/updated NPCs, trait changes | `characters` (registry and aliases through `IdentityService`) |
| Locations | New/updated locations | `locations` (same) |
| Organizations | Org changes | `organizations` (same) |
| Inventory | Object acquisitions/losses | `objects`, `protagonist_inventory` + engine extensions |
| Narrative Arcs | Arc progress, new arcs | `narrative_arcs` |
| Progression | Engine skill/trait evolution | `skills_fate`/`skills_d6`/`traits_narrative` (delegated to engine) |

Extractors do not create entities themselves (#153): a creation is an `IdentityService.create_entity` call (it returns the entity already holding the label), every reference an item carries is resolved before the write by `IdentityService.require_ref` through `kg/refs.py`, and an update or a removal is written by entity id. An item whose required reference does not resolve is not written and is counted as `ref_dropped`.

### Extraction is a Background Job

Extraction runs as a `post_turn` job on the game's supervisor queue (§14). It does not block the narration response. The frontend receives `SSEEvent.SAVED` before extraction completes.

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

All three go through `rollbackThenSend(messageId, content)`: rollback to the action, then send `content` in its place. A message without id (not saved) is refused with "Ce message n'est pas encore enregistré : recharge la partie pour le reprendre." (not recoverable: no "Réessayer"). Loaded messages carry their ids; a turn played in the session gets them from `done.state.meta` (`withTurnIds`, `frontend/lib/game/chatHistory.mjs`): the answer, and the action just before it (#55).

`rollbackTo(messageId)` calls `stateApi.rollback` (`POST /games/{id}/rollback {messageId}`, `messageId` required: 422 without it), then shows the returned `messages` and `state`; the invocation modal follows `state.pending_roll` (null after a rollback, which expires the pending roll, #80). A refused rollback shows the server's French message (not recoverable) and sends nothing.

**Edit (modify text):** `handleSubmitEdit(content)`: `rollbackThenSend(messages[editingIndex].id, content)` (new text).

**Resend (same text):** `handleResend(index)`: the message must be a user one; `rollbackThenSend(msg.id, msg.content)`.

**Regenerate (redo last assistant response):** `handleRegenerate()`: the last user message, found scanning backwards (`findLastUserMessage`); `rollbackThenSend(msg.id, msg.content)`. It needs no earlier send in the session, so it works right after loading a saved game.

### Backend Rollback

**File:** `backend/api/routes.py` — `POST /games/{game_id}/rollback`

The route holds the game lock (`workers/game_locks`), then cancels the game's background jobs (`supervisor.cancel_game`, wait bounded by `SUPERVISOR_CANCEL_TIMEOUT`) **before** the service validates the request: a rollback rejected with 400 still cancels the game's pending extraction and Director (documented trade-off). Then it calls `GameService.rollback_to_message(game_id, message_id)`, which reads the messages, builds the plan (`services/rollback.plan_rollback`) and, by default, runs `services/rollback.undo_turns`:

- **Plan.** `plan_rollback` returns the messages to delete, the target cycle, the distinct turn ids of those messages (in message order) and whether one of them has no `turn_id`. Nothing to delete gives `None`; a target before the arrival pair raises `RollbackRejected(ARRIVAL_SCENE)`.
- **Legacy boundary.** A message to delete played before the journal (`turn_id` NULL) is refused: `RollbackRejected(BEFORE_JOURNAL)` (`domain/errors.py`), answered 400 with "Impossible de revenir sur un tour joué avant la mise en place du journal des tours." There is no fallback to the cycle rollback (it would rewrite world rows outside the journal). A legacy game can still roll back its turns played after the journal.
- **One transaction, in this order.** (1) `DELETE FROM messages` of the plan, the first statement (lock order against the `FOR SHARE` guard of §5; also required before the undo because `messages.chronology_id` is NO ACTION); (2) `expire_pending_rolls` (the undo may put a resumed roll back to pending while a newer roll is pending, and there is one pending roll per game: a unique index, not deferrable); (3) repair of the resumes among the plan's turns (`_repair_resumed_rolls`): a halted turn still open (a resume committed under P5a, before the adoption) is adopted now; when the halted turn is gone (adopted at commit, or purged by an earlier rollback together with the roll's insert under P5a) the roll is deleted **before** the undo, which could otherwise only put it back to pending (two such rolls would break the one-pending-roll index) and restore a `turn_id` pointing at the purged turn; (4) `world_changes_undo(turn_ids)`; (5) `repos.turns.delete_turns` (the plan's turns plus every open turn of the game; after the undo, so a restored `turn_id` still points at an existing turn when the foreign keys are checked); (6) `expire_pending_rolls` again, then `games.updated_at`. All or nothing.
- **Result.** `rollback_result` is `{"undone_changes": n, "deleted_turns": n}`.
- **Adoption.** A turn that resumes a pending roll adopts its halted turn at commit (`repos.turns.adopt_halted_turn`): the halted turn's journal and references move to the resuming turn and the halted turn is deleted. Rolling back the resume therefore removes the roll whole, and no later rollback purges the halted turn's journal as an abandoned open turn (C-05 counts 2 turns, not 3).
- **`ROLLBACK_ENGINE`.** `journal` (default) uses the replay above; `cycle` keeps the pre-P5 rollback (`services/rollback_cycle.py`, `kg/populator.rollback_to_cycle`, the engine snapshot, `narrator_deltas`) for one release and logs a WARNING at startup; its removal is tracked in #160. An invalid value stops the start. Switching from `cycle` back to `journal` is unsafe for games rolled back under `cycle` meanwhile: the cycle path rewrites world rows outside any turn, so the journal of the kept turns no longer describes them. Such a game keeps `cycle` until the flag is removed.

#### `world_changes_undo(uuid[])`

**File:** `db/migrations/20261020000000_world_changes_undo.sql` (SQL function). It replays the journal of the given turns **newest first** (`world_changes.id` descending): an `I` row is deleted, a `U` row gets its old keys back, a `D` row is re-inserted from `old_row`. Cascaded children are journaled after their parent, so going backwards re-inserts the parent first.

- **Deferred foreign keys.** Every foreign key the replay can trip is `DEFERRABLE INITIALLY IMMEDIATE`: those of a journaled table, and the NO ACTION ones pointing at a journaled table from any table (`messages.chronology_id`, for instance; CASCADE and SET NULL actions are never deferred). That is 65 today, pinned by `test_every_foreign_key_the_replay_can_trip_is_deferrable`. Behaviour is unchanged outside the replay. The function runs `SET CONSTRAINTS ALL DEFERRED` for the replay and `SET CONSTRAINTS ALL IMMEDIATE` before returning, which checks them all (this also applies to the rest of the caller's transaction).
- **Replay flag.** The function sets `ldvelh.replay`; `register_entity`, `update_entity_registry_name` and `facts_immutable` do nothing under it (the registry rows are restored by their own journal rows).
- **Allowlist.** Only tables carrying the `zz_journal_id` trigger are replayed. A row for another existing table raises; a row for a table dropped since is skipped.
- **No journal, idempotent.** The replay writes no journal rows, and replaying already-undone turns changes nothing.
- **Return value.** The number of journal rows replayed: rows skipped (dropped table, no column of `old_row` left on the table) are not counted; a replayed row that changes nothing (already undone) is.
- **Maintenance.** Guard tests fail when a new foreign key is not deferrable or a new trigger would fire during the replay. A later migration that removes the journal from a table makes the rollback of older turns touching it raise.

Known residual: `messages.location_id` is ON DELETE SET NULL and messages are not journaled, so a location deleted by a rolled-back turn and restored by the undo does not re-point the older messages that referenced it (their `location_id` stays NULL).

### Turn journal (P5a)

**Files:** `db/migrations/20261019000000_turns_and_world_changes.sql`, `backend/repos/turns.py`, `backend/repos/uow.py`

P5a records what each turn writes; since P5b (#22) the rollback replays it backwards (above).

- **Tables.** `turns` (`id`, `game_id` ON DELETE CASCADE, `status` `open` | `committed`, `created_at`, `committed_at`) and `world_changes` (`id` bigserial, `turn_id` ON DELETE CASCADE, `table_name`, `row_id`, `op` `I` | `U` | `D`, `old_row`, `new_row` as jsonb, `created_at`). `messages.turn_id` and `mechanic_rolls.turn_id` are nullable (legacy rows have none; ON DELETE SET NULL, they outlive a deleted turn). `extraction_logs.turn_id` is ON DELETE CASCADE: the extraction log of a rolled-back turn goes with it (C-12 snapshot). `director_commitments` (#107, schema only for now) and `llm_calls` also carry a nullable `turn_id` (SET NULL). Every `turn_id` foreign key has a partial index (`WHERE turn_id IS NOT NULL`), so deleting a turn does not scan the referencing tables.
- **Trigger.** `ldvelh_journal(table)` attaches two AFTER ROW triggers, `zz_journal_id` (INSERT, DELETE) and `zz_journal_u` (UPDATE, only when the row changed) to a table; both run `ldvelh_journal_row()`, which reads `current_setting('ldvelh.turn_id', true)` and does nothing when it is unset. An `I` row stores `new_row`, a `D` row `old_row` (whole rows), a `U` row only the changed keys (old and new). `games` is journaled on its world columns only (cycle, date, time, location, `detail_requests`, `last_director_time`, `last_extraction_time`, `engine_locked`), not on `name`, `active` or settings. The names sort after Postgres' own `RI_ConstraintTrigger_*` and the `register_*` triggers, so rows written by the `entity_registry` triggers are journaled before their entity. The journaled tables are the 34 listed in the migration (world tables, `entity_registry`, `mechanic_rolls`), `games` (columns above) and `director_commitments`.
- **Order of cascaded deletes.** Rows removed by an ON DELETE CASCADE are journaled **after** their parent's `D` row (the child deletes run inside the referential trigger and their AFTER triggers queue behind the parent's). The undo goes newest first, so the parent is re-inserted before its children.
- **Unit of work.** `repos.uow.uow(conn, turn_id, *, source_message_id=None)` opens a transaction on the caller's connection, optionally share-locks the source message (§5), and sets `ldvelh.turn_id` with `set_config(..., is_local => true)`, so the setting ends with the transaction. With `turn_id=None` nothing is journaled. It **must be the outermost transaction**: it raises `RuntimeError` when the connection is already in one (the setting would otherwise outlive the block). A step needing a failure-tolerant write inside it uses a savepoint (`conn.transaction()` inside the `uow`, as `kg/item_writes.py` does); no pipeline, extractor, hook or Director code opens a transaction outside `uow`.
- **What is journaled.** Everything the turn writes through a `uow`: the arbitrate step (pending roll), the commit, each extractor transaction, the orchestrator's entity reveals, the `on_new_cycle` hooks and the Director apply. A Director run or extraction is journaled under the turn that triggered it, in its own transaction, after the commit.
- **What is not journaled.** Writes outside a turn: world generation and the initial Director (no turn), game CRUD and settings, the rollback itself, accounting (`llm_calls`, §14), and tables that are not world state (users, preferences, catalog, `turns` and `world_changes` themselves). Legacy turns, played before the migration, have no journal; the rollback refuses them (`BEFORE_JOURNAL`).
- **Purge.** `repos.turns.delete_turns` (called by the rollback, in its transaction) deletes the turns of the deleted messages plus every `open` turn of the game (abandoned ones); their `world_changes` and `extraction_logs` cascade, their messages and rolls keep `turn_id` NULL.
- **Cost.** About 2 journal rows and 1.1 KB per real turn. The trigger overhead measured in the test environment is above the planned 10 % of commit latency; see `backend/tests/characterization/FEATURES.md`, Phase 5a. The overhead gate was not met in the test environment (+0.11 to +0.21 ms per commit); the owner decided to proceed with P5b and a production measurement remains advisable.

Identity tables (#152): `entity_aliases`, `entity_mentions` and `entity_merges` are journaled (their foreign keys are deferrable, their triggers skip the replay), so a rollback undoes an alias, a mention or a merge written by the turn. `identity_events` is **not** journaled and is exempt from the purge: its rows (`identity_backfill`, `identity_exception`, `handle_reserved`) are durable state, markers that a migration step or an owner correction was applied once, and rolling a turn back never reopens them.

A refused rollback raises `RollbackRejected(reason)`; the route answers 400 with a fixed French `detail` per reason (`arrival_scene`: "Impossible de revenir avant la scène d'arrivée.", `before_journal`: see above), never the exception text (#80).

---

## 8. Auth System

### Frontend

**File:** `frontend/hooks/useAuth.js`

- **Login:** `login(identifier, password)` → `POST /auth/login` → stores JWT + user in localStorage
- **Register:** `register(email, password, passwordConfirm, displayName)` → `POST /auth/register`
- **Session restore:** on mount, reads localStorage → validates via `GET /auth/me` → refreshes token
- **Token refresh:** every 30 minutes via `POST /auth/refresh` (same session: never past the absolute lifetime, then the player logs in again)
- **Logout:** `POST /auth/logout` (best effort, 3 s timeout), then clears localStorage. The backend revokes every session of the player: logging out on one device logs out all of them
- **Session lifetime:** a session lasts at most `JWT_SESSION_MAX_HOURS` (720 h, 30 days, by default) from login, refreshes included: players log in again every 30 days
- **Password change** (Settings): stores the token returned by `POST /auth/change-password`; the player's other sessions are revoked

**File:** `frontend/lib/api.js`

All API requests include `Authorization: Bearer {token}` header. On 401 response, automatically attempts token refresh and retries the original request. On refresh failure, clears auth and redirects to `/login/`.

### Backend

**File:** `backend/api/auth.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/register` | POST | Create user, hash password, send verification email |
| `/auth/login` | POST | Authenticate by email or display_name, return JWT |
| `/auth/me` | GET | Return current user (requires auth) |
| `/auth/refresh` | POST | Issue a fresh JWT for the same session (keeps `orig_iat`) |
| `/auth/logout` | POST | Revoke every token of the player (bumps `token_version`, all devices) |
| `/auth/verify` | GET | Verify email via token (24h expiry) |
| `/auth/resend-verification` | POST | Resend verification email (3 per 10 min per player) |
| `/auth/change-password` | POST | Verify current (5 checks per 10 min per player) + update password, revoke every session, return a new `token` for this one |
| `/auth/profile` | PATCH | Update display name |
| `/auth/preferences` | GET | Load user preferences (API keys masked) |
| `/auth/preferences` | PATCH | Update preferences (API keys encrypted) |

**File:** `backend/services/auth_service.py`

- Password hashing: bcrypt
- JWT: signed with `JWT_SECRET`, claims `sub`, `email`, `ver`, `iat`, `orig_iat`, `exp`. `exp` is `jwt_expiry_hours` (72 h) after issue, capped at `orig_iat` + `jwt_session_max_hours` (`JWT_SESSION_MAX_HOURS`, 720 h): `orig_iat` is the session start (login, registration, password change) and a refresh keeps it, so a stolen token cannot be refreshed forever (#83). `get_current_user` answers 401 when `ver` differs from `users.token_version` (`Session revoked`), when the session is older than the absolute lifetime (`Session expired`) or when a claim is missing (tokens issued before #83: players log in once again). `token_version` is incremented by a password change and by `POST /auth/logout`.
- Rate limits (`utils/rate_limit.py`, in memory, sliding window, idle keys purged once per window): login/register 5/min per IP, `/world/enhance` 10/min per IP, `/chat` 10/min per player and 30/min per IP (counted on both or neither: a refusal by one limit uses no slot of the other), resend-verification 3 per 10 min per player, current-password checks of `/auth/change-password` 5 per 10 min per player (successful changes count too). Over the limit: 429 `{"detail": "Trop de requêtes. Réessaie dans N s.", "code": "rate_limited"}` with `Retry-After` (N: seconds until the oldest counted request leaves the window); the chat client shows that French text (or its own when a 429 has another body). The client IP is the TCP peer, or with `TRUSTED_PROXY_HOPS=N` the N-th `X-Forwarded-For` entry from the right (the one the outermost trusted proxy appended): client-supplied entries on the left are ignored, so varying the header no longer resets a limit (#82). N must not exceed the real proxy count; a chosen entry that is not an IP address falls back to the TCP peer.
- At startup `main.py` runs `startup_checks.check_startup_config`: the backend refuses to start, even with `DEBUG=true`, when `JWT_SECRET` is under 32 characters, has outer whitespace, uses fewer than 8 distinct characters, contains `change-me` or is a value published in the repo, or when `ENCRYPTION_KEY` is set but has outer whitespace or is not a valid (unpublished) Fernet key; an empty `ENCRYPTION_KEY` is refused outside debug mode. `config.py` has no JWT default (empty, hence refused)
- Email verification tokens: 24h expiry, stored in `users.verification_token`

### Preferences

Stored in `users.preferences` JSONB column. Includes:
- `font_size`, `show_debug` — UI settings
- `active_provider`, `active_model` — LLM provider selection
- `api_keys` — encrypted per-provider API keys

A PATCH is rejected (422) when `api_keys` is not `{provider: key|null}`, has more than 10 entries or a key over 512 characters, or when the patch, or the merged preferences about to be stored, exceed 16 384 serialized characters or 50 top-level keys (`api/request_types.py`).

### Request validation

Bad client input (malformed `messageId`, rename over 255 characters or blank, `engine` outside `EngineType` on `POST /games` and `/chat`, malformed e-mail, `display_name` over 100) answers 422 `{"detail": "Requête invalide : champ : problème."}` in French, built by one `RequestValidationError` handler (`api/http_errors.py`): field names and error kinds only, never the submitted value. The e-mail check is a shape check (no `email-validator` dependency). `/world/enhance` types `engine` the same way (422 instead of its former hand-written 400). Every `detail` the API returns is French; `code` fields stay machine-readable.

A game whose stored `games.engine` is not an `EngineType` (rows from before this validation; migration `20261018000005` rewrites them to `none`) loads as engine `none`. `schema.engine.coerce_engine(value, game_id)` is applied where DB data is read (game load and rollback, the game snapshot, the KG reader, the context builder, the `/games` listing) and logs one WARNING naming the game, never the stored value; `get_engine` itself stays strict and raises on an unknown value.

Registration refusals are typed (`domain/errors.py`: `PasswordTooShort` 400, `DisplayNameTaken` 409, `EmailTaken` 409); `api/http_errors.py` maps each to a French `detail` plus a stable `code` (`password_too_short`, `display_name_taken`, `email_taken`).

---

## 9. Knowledge Graph Layer

### Architecture

**File:** `backend/kg/__init__.py`

```
KnowledgeGraphReader (SELECT)     → kg/reader.py
KnowledgeGraphPopulator (INSERT/UPDATE/DELETE, by id) → kg/populator.py
WorldPopulator, ExtractionPopulator (extend it)        → kg/specialized_populator.py
References resolved at the edge                        → kg/refs.py
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

All write operations, by entity id (#153, spec §4.6). There is no in-memory registry any more (the `EntityRegistry` cache is gone): every reference is resolved by SQL on the transaction's connection, so a write sees the entities, reveals and merges of the turn so far. Entities are created only by `IdentityService.create_entity` (the populator builds no domain row of a character, location, organization or object itself; the protagonist and the companion are made by game creation and registered by their triggers).

Key methods: `create_game`, `delete_game`, `rename_game`, `update_entity(conn, entity_id, entity_type, fields)` (extracted changes bounded by `schema.entity_changes`, written by `IdentityService.update_entity`; `known_by_protagonist` is a reveal's, dropped), `remove_entity(conn, entity_id, entity_type, cycle)`, `add_to_inventory(conn, object_id, ...)`, `create_relation(conn, source_id, target_id, relation_type, ...)`, `end_relation(conn, source_id, target_id, ...)`, `create_narrative_arc(conn, arc, cycle, participant_ids)`, `create_fact(conn, fact, participants=[(entity_id, role)], location_id)`, `create_event(..., location_id)`, `save_chronology_entry(..., location_id, npc_ids)`, `credit_transaction`, `update_game_state`. `identity(conn)` gives the game's `IdentityService`, built once per populator.

**References at the edge** (`kg/refs.py`): the extractors, the world generation, the commit and the Director turn a reference (handle `E<n>`, label, alias, `PROTAGONIST`/`COMPANION`) into an id with `IdentityService.require_ref` (typed) or `require_any_live_ref` (untyped: fact participants, relation ends, arc, event and chronology participants, world-generation references; exactly one type must know it, once, live first: the live homonym of a removed entity is found by its name, two live entities are an ambiguity, and only a name no live entity holds may name a removed one, so a fact about a dead NPC still attaches). `refs.required` is for what an item cannot be written without (a fact participant, a relation end, the entity an update, a removal or an ambient update names, an inventory object; `live=True` for a write target, only live entities count, and the `ref_dropped` event then carries `removed`, the count of removed entities the name holds, so a removed entity is told apart from an unknown name; `live_first=True` for the entity an update changes): `RefUnresolved` makes `write_item` roll the item back and count `{"code": "ref_dropped", "item": <item>}`, so a fact is never written without a participant it names. `refs.optional` is for what an item stands without (a fact's or an event's place, an event or arc participant, a character's workplace or residence, a location's parent): an unresolved one is counted the same way in its own savepoint and the item is written without it (C12).

**Creation paths (C1-C14).** World generation (`WorldPopulator`): the station (root location), organizations, locations, characters (true name, descriptor, `known_by_protagonist`) and objects each through `create_entity(source='world_gen')`, so they get their derived aliases (`title`, `short`); parents, headquarters, the protagonist's employer and residence, characters' workplace and residence, relations and arc participants are resolved to ids afterwards; an item that cannot be written is counted in the generation's `extraction_logs.errors`. Extractors (`ExtractionPopulator.create_extracted_entity`): `create_entity(source='extractor', refill=True)`: a re-listed entity that holds the label takes the non-blank values of the columns a re-listing may fill (#87), never its names nor `known_by_protagonist`; a removed entity is never reused nor refilled: a label only removed entities hold creates a fresh live entity (internal suffix while a removed one keeps the label, event `label_suffixed`), the live homonym is the one reused afterwards; a character found through the extractor's own name (not a proper name) is reused with a `create_reused` event (`via: name`); a character name that does not look like a proper name is a descriptor (`classify.extracted_character_names`). An object an extractor lists is created but never put in the inventory: only `acquired` (`objects_created`, `inventory_changes` acquire) does (F18). Updates (`_process_entity_update`), removals and ambient updates resolve their reference first, live first (`refs.required(..., live_first=True)`, `IdentityService.require_live_ref(or_removed=True)`): the live homonym of a removed entity is reached by its name, a name only one removed entity holds still names it, and removing an entity already removed is a counted no-op (event `remove_noop`), not an error (an update by descriptor writes that character, F12; a null type is resolved among every type); a known flag among the changes is a reveal without a name. The narrated location (`services/turn_effects._resolve_location`, C10, R21): `resolve_live_ref(type='location')`, else a stub through `create_entity(kind='descriptor', source='system', trap=True)`, so a name only removed locations hold gets a fresh suffixed location; a name two live locations share creates nothing. Location reveals resolve the location live first, then mark it accessible by id. Director arcs (C13) link the participants that resolve and count the others.

### Entity Registry

**Files:** `db/migrations/20261020000001_entity_identity.sql`, `db/migrations/20261020000002_identity_label_suffix.sql`, `db/migrations/20261020000003_identity_bare_label.sql`, `db/migrations/20261020000004_identity_merge_engine_rows.sql`, `backend/repos/entities.py`, `backend/services/identity/`, `backend/packs/lang/`, `backend/scripts/identity_backfill.py`

Since #152 the registry is the identity of every entity. PostgreSQL triggers register characters, locations, organizations, objects, facts-bearing entities and the companion into `entity_registry` on INSERT, and `entity_registry.id` **is** the domain row's id (no second id).

- **Handles.** Each registry row has a per-game `handle` (`E<n>`, unique per game, numbered by a trigger under an advisory lock) that the prompts and the resolver use instead of a name. Facts have their own `handle` (`F<n>`).
- **Language packs.** `packs/lang/*.yaml` (synced to the `lang_packs` table at boot by `scripts/sync_lang_packs.py`) hold everything language-specific: folded normalisation parameters, lexicon, label of an unidentified character (`unknown_character_label`), the words announcing another entity (`other_markers`) and whether letter case marks names (`case_marks_names`, false for a script without case or a language that capitalises every noun). `config.IdentityConfig` holds the language-neutral thresholds and the default language. `games.language` selects the pack. No language or genre word appears in code or SQL (guarded by `tests/identity/test_genericity.py`).
- **Normalisation.** `ldvelh_norm(text, folded params)` (SQL) has a Python mirror (`services/identity/normalize.py`) tested for parity. `name_norm` (registry) and `alias_norm` are filled by trigger; a normalised unique index forbids two live entities of a type with the same norm.
- **Names.** A non-character has a `label`; a character has `true_name` (nullable until revealed) and `descriptor` ("the woman with the green coat"), with a CHECK that one of them is set. Homonyms of any type get an internal `label_suffix` (`db/migrations/20261020000002_identity_label_suffix.sql`, #153): it is appended to the registry label only (`identity_label`), never to what the player reads (a non-character's domain `name`, `display_for_player`). Homonyms share the bare name as an alias, so it is an ambiguous reference; each keeps its suffixed label as an internal alias (`known = false`). Invariant: a suffixed label alias is internal, no reader may show an alias whose norm is the registry `name_norm` of a suffixed entity. A rename (`IdentityService.update_entity`) drops a suffix no homonym needs any more. Prompts (narrator, Director, extraction contexts) read `identity_bare_label(entity_id)` (`db/migrations/20261020000003_identity_bare_label.sql`): the label without its suffix (a character's true name, else its descriptor; another entity's domain name). `v_active_relations`, `KnowledgeGraphReader` (characters, arc owners, entities, entity details) and the first-turn resolver reference use it; what a prompt knows is otherwise unchanged.
- **Aliases.** `entity_aliases` (typed `kind`: `label` for non-characters, `true_name`, `descriptor`, `short`, `title`, `former_name`, `nickname`; `source`: `world_gen`, `extractor`, `resolver`, `reveal`, `director`, `migration`, `system` for trigger-made aliases; a `known` and a `secret` flag).
- **Other tables.** `entity_mentions` (a span of a message resolved to an entity, with its `decision`), `entity_merges` (non-destructive merges: the loser keeps its row with `merged_into`) and `identity_events` (state kinds `identity_backfill`, `identity_exception`, `handle_reserved`; telemetry kinds such as `ambiguous_ref`, `create_reused`, `create_contested`, `create_ambiguous`, `label_suffixed`, `ref_dropped`, `write_miss`, `remove_noop`).
- **`find_entity(game, ref, type)`** (SQL, and `repos.entities.find_entity`): the type is required. It resolves `PROTAGONIST` / `COMPANION`, `E<n>`, a uuid, then `name_norm`, then `alias_norm` (labels and aliases together), and follows merges. Two or more matches (ambiguity) return NULL: a wrong merge is worse than a duplicate. `find_any` (untyped) answers only when exactly one type matches and none is ambiguous.
- **`display_for_player(entity_id)`** is the only name the player may read: the true name once known, else the descriptor, else the pack's unknown label. Views and the tooltips go through it.
- **`IdentityService`** (`services/identity/service.py`, #153): the entry point that creates, names and references entities, on the caller's connection. `create_entity(spec)` returns the live entity of the type that already holds the label (event `create_reused`) unless the caller verified a trap; a label that only aliases of several entities hold creates nothing and raises `AmbiguousLabel` (code `create_ambiguous`), or, with a trap, creates with an event `create_contested`. With a trap on a held label the newcomer gets a `label_suffix` from the scene location's name, else the first free number (event `label_suffixed`); it inserts the domain row (the triggers register it and add the aliases of its names, source `system`) and adds the derived aliases (`aliases.derive`) and the spec's own with the caller's source. `resolve_ref` is exact (`find_entity`), never an LLM, and logs `ambiguous_ref`; `require_ref` raises `RefUnresolved`; `update_entity` writes by id, raises `IdentityWriteMiss` on no row and refuses `known_by_protagonist` (reveals own it); `handles_for_prompt` gives `E<n>`. `kg.item_writes.write_item` records every `IdentityFailure` as `{"code": "ref_dropped" | "write_miss" | "create_ambiguous", "item": <label>}` in `stats.errors` and as an `identity_events` row of that kind, without story text, written after the item's rollback and in its own savepoint (a failure to write it is logged, never aborts the turn). An `ambiguous_ref` event written inside an item that is then dropped goes with it: the ambiguity appears as `ref_dropped` with `candidates >= 2`.
- **Reveals** (`IdentityService.reveal(ref, real_name, turn_id=, source=)`, `services/identity/reveals.py`, #153): called by the commit (`services/turn_effects.apply_narrator_deltas`) and its re-apply by the extraction orchestrator, both through `apply_entity_reveals` (one loop, one savepoint per reveal), and the extractors' `now_known` (`source='extractor'`). The reference is resolved by `find_entity` (handle, id, label or alias of the type); unresolved or ambiguous: a counted no-op (`reveal_noop`), never a guess. Then spec §4.7 row by row: no real name: the true name it has becomes known (`known_only`), none: `reveal_noop`; the real name designates another entity of the type (a character only by a `true_name` alias, never a descriptor, even an unnamed character's registry label, nor a short form; another entity by its label or a `label` alias): merge into the older (`merged`, the survivor then goes through the table, so a different hidden true name gives way to the narration's), unless a guard refuses (`merge_refused`, codes `ambiguous`, `never_auto_merged` for objects, or a merge guard; nothing is written, so the holder still resolves by its name, and the event lists `holder_ids`); a form another entity holds as its registry label without designating it (an unnamed character's descriptor) is still given as the name, with an internal `label_suffix` on the revealed entity's registry label (R14, event `label_suffixed`): the player reads the true name, prompts the bare label; no true name yet: it is set, known, with its derived aliases, the descriptor stays (`applied`); same norm or `similarity >= IDENTITY_REVEAL_MATCH`: known, the narration's spelling a `true_name` alias, the existing spelling kept (`known_only`); otherwise the narration wins, the old name becomes a `former_name` (`conflict`, event `reveal_conflict`). `FactRef` (`F<n>` or id) sets `facts.known`. Idempotent: a second call writes nothing and records no event; `reveal_noop` and `merge_refused` are recorded once per turn (else per transaction) for the same entity and payload, an unresolved reference carrying `ref_key` (a SHA-256 of its normalised form, never its text), so two different reveals are two events. At the commit each reveal runs in its own savepoint (`write_item`): a failing one never blocks the turn. Nothing is deleted: every write is journaled, `world_changes_undo` restores the entity.
- **Merges** (`IdentityService.merge(keep, drop, reason=, turn_id=)`, `services/identity/merges.py`): the policy guards (codes `same_entity`, `missing`, `reserved_type` for the protagonist or the companion, `type_mismatch`, `already_merged`, `both_mandatory`), refused: event `merge_refused`; then the SQL `merge_entities` (integrity only: not the same entity, same game, same type, neither side already merged) re-points every edge to the kept entity, moves the aliases, completes its empty fields (keep's `known_by_protagonist` stays its own, except when keep takes drop's name or both names are one, `db/migrations/20261021000002_identity_merge_known_flag.sql`, ruling R42: an OR could make a secret true name readable), leaves a tombstone (`merged_into`) and writes `entity_merges` and the `merge` event. Engine rows (`npc_fate`, `npc_d6`, `npc_narrative`; `object_fate`, `object_d6`, `object_narrative`; one per entity, `db/migrations/20261020000004_identity_merge_engine_rows.sql`): drop's moves to keep when keep has none (`moved_edges` `<table>.<column>`); when both have one, keep's wins, and drop's is listed under `<table>.dropped` and copied into `entity_merges.dropped_row` (key `engine`) before the cascade deletes it. A skill keep already has open (same name, case aside) is closed on drop's side (`skills.closed`) rather than listed twice. In a turn, the journal undoes all of it. Mentions are not rewritten (reads follow the tombstone). Reveals never merge objects; suspected duplicates are otherwise only reported.
- **Operator merge** (`backend/scripts/merge_entities.py`, #153): the only way to merge two entities outside a reveal. `python -m scripts.merge_entities --database-url-env VAR --game GAME --keep E12 --drop E31 --reason TEXT [--yes]`. One of `--database-url` or `--database-url-env VAR` is required (no default, no other environment read; prefer the second, a URL on the command line shows in `ps`): it never touches a database by chance. A connection failure prints one line without the URL. It reminds the operator to take a backup, prints the two entity cards (names included: the operator owns the data) then the guard verdict (refused: it says so and exits without asking, nothing written) and every edge the SQL merge would move (`repos.entities.edge_preview` runs `identity_merge_edges` in a rolled-back savepoint, so it cannot drift from the merge), then the engine rows of drop that keep's own replace, asks for confirmation on stdin (a refusal changes nothing; `--yes` skips it), then calls `IdentityService.merge` outside any turn, in one transaction, and prints the merge id or the refusal code. Outside a turn the merge is audited in `entity_merges` but no turn rollback undoes it; CONTRIBUTING.md, "Merging duplicates", gives the procedure.
- **Rulings of PR 1b.** R14/R19b: a second entity under a held label, or a revealed name that is another entity's registry label without designating it, gets an internal `label_suffix` (any type), never shown; the player reads the bare name, the prompts the handle. R16: an ambiguous label (several entities hold it by alias) creates nothing: `create_ambiguous` is counted in `stats.errors` and `identity_events`. R18: a descriptor or a short form never designates another character, so it never merges. R19a: a refused merge writes no alias, the holder stays resolvable by its name (the event lists `holder_ids`). R21: a removed location is never a turn's place: the current-location path creates a fresh live location (internal suffix) rather than reusing it, journaled and undone by the turn's rollback. Final review: a removed entity of any type is never a creation or refill target (extractor creations create a fresh live one), and updates, removals, ambient updates and location reveals resolve live first. Deferred: the NOT NULL constraints on `name_norm`, `alias_norm` and `games.language`, and the removal of the transition functions, wait for the production backfill (#166).
- **Existing data.** The migration's data section re-identifies the legacy registry (ids become the domain ids), registers the companion, builds aliases, flags facts and rewrites the journal of pre-migration turns. `scripts/identity_backfill.py` then gives each old game its language, norms and mentions, resolves orphans and collisions, classifies unknown characters (true name or descriptor, shared rule in `services/identity/classify.py`) and applies `IDENTITY_BACKFILL_EXCEPTIONS` (a `true_name` correction drops any descriptor whose normalised words contain the true name, a descriptor the player saw included: the player then reads the pack's unknown label, never the hidden name). A game already backfilled skips the legacy pass (norms, collisions, mentions) when a late correction arrives, and only the corrected characters get derived aliases. The container entrypoint runs it automatically after `dbmate up`; the startup check refuses to serve while a norm is missing. `scripts/identity_migration_report.py` produces the read-only dry-run report. Deploy steps: CONTRIBUTING.md, "Deploying the identity migration".

The player character is referenced by type, not by name (#28): the reserved reference `PROTAGONIST` (`schema.core.PROTAGONIST_REF`) resolves to the game's `entity_type='protagonist'` row in the SQL `find_entity()` (and `COMPANION` to the companion), which every reference of a write goes through (`kg/refs.py`). The real PC name still resolves. Extraction prompts teach the token in every reference field and the extractor user prompt names the PC for free text (`prompts/extraction/shared.py::protagonist_section`). Facts the populator writes about the PC use role-based keys (`kg/semantic_keys.py`: `protagonist:arrival:*`, `protagonist:use:*`). The name `PROTAGONIST` is reserved: an extracted or generated entity with that name is skipped. The PC name has no default and is never blank: the wizard's name is authoritative (`pipeline/chosen_name.py` overwrites the world builder's name and its mentions), else the name the world builder invents; an unusable invented name (blank, `<`/`>`, `PROTAGONIST`) becomes `DEFAULT_PROTAGONIST_NAME` ("Alex", `schema/core.py`) with a WARNING, so world generation never fails after the paid call because of the name. A typed wizard name with `<`/`>` or equal to `PROTAGONIST` is refused by `POST /api/chat` with a 400 ("Nom du protagoniste invalide…") before any LLM call; the wizard applies the same rule first (`lib/game/wizardForm.mjs::protagonistNameError`; both sides are tested on `frontend/tests/fixtures/protagonist-names.json`): the message is shown under the field and « Créer le monde » stays disabled. The rename matches the model's name case-insensitively on the original spelling plus its casefold (so "Weiß", "WEISS" and "İlker" work), treats `'` and `’` as the same apostrophe, and leaves surname-only mentions alone. Genre `world_gen_example` rows carry the slot `{{PROTAGONIST_NAME}}`, filled at prompt build time with the wizard's name or the marker `<prénom inventé>`.

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
    - engine_stats: dict | None (engine-specific vitals, vitals_from_stats)
    - sheet: dict | None (character sheet, sheet_from_stats; {} without one)
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
| `done` | `{displayText, state}` | Final result with full game state. `state = {game_state, meta, ui?}` (`SSEDonePayload`). On a turn's done, `meta = {narration_cost?, mechanical_cost?, user_message_id, assistant_message_id}` is always present: the two ids (UUID strings) name the turn's saved messages, for edit / resend / regenerate (#55). The world-generation done has `world_info` and no message ids (it saves no messages) |
| `saved` | `{}` | DB save confirmed |
| `error` | `{error, details, recoverable, code, ref}` | Error occurred; `code` and `ref` on turn errors (see 3.2) |
| `warning` | `{message, details}` | Non-fatal warning |
| `roll_result` | `{roll}` | Dice roll result for display |
| `roll_pending` | `{roll_id, roll, aspects, fate_points}` | Fate Core invocation pause |

### SSEWriter

Async queue-based writer. Events are pushed via typed methods (`send_chunk`, `send_progress`, `send_done`, etc.) and consumed by `iterate()` which yields `data: {json}\n\n` lines. Includes 60-second keepalive timeout. `attach(task)` ties the turn task to the writer; when the client closes the stream, `disconnected` becomes true and the task is cancelled (see 3.2, Disconnect). If the stream itself fails server-side (e.g. an event that cannot be serialized), one `error` event is sent before the stream closes: `code: internal` with the stream `ref`, or `saved_display_failed` (not recoverable) once `done` was queued (worded for the world when that done was sent with `send_done(..., world=True)`, as world generation does, #80), then the turn is cancelled as on a disconnect (unless `done` was queued).

### Frontend Handling

**File:** `frontend/hooks/useStreaming.js`

`startStream(url, body)` runs `runChatStream` (`frontend/lib/chatStream.mjs`):
1. POSTs to backend with JSON body; a 401 refreshes the session once and retries
2. A non-2xx answer becomes one `error` event (`status`, FastAPI `detail`)
3. If response is `text/event-stream`: reads via `ReadableStream` reader, parses `data: ` events (`lib/sse.mjs`, partial events buffered)
4. No terminal event before the end → synthetic recoverable `error` (`interrupted: true`); `done` without `saved` → `save_unconfirmed`
5. Dispatches to callbacks: `onChunk`, `onProgress`, `onDone`, `onSaved`, `onSaveUnconfirmed`, `onError(message, details, { status, interrupted })`, `onRollResult`, `onRollPending`
6. Returns `{success, fullJson}`, `{success: false, interrupted}` or `{success: false, aborted}` on cancel

Cancellation: `cancel()` aborts the `AbortController`, frontend updates message with "*(Annulé)*" suffix.

---

## 12. Tooltips & World Sidebar

### Tooltips

**File:** `backend/api/tooltips.py`

Every endpoint of this section checks that the caller owns the game (`GameService.verify_ownership`): 404 `Game not found` for an unknown game, 403 `Access denied` for someone else's.

- `GET /api/tooltips/annotations?gameId={id}&limit=10[&before={sequence}]`: the stored mentions (`entity_mentions`) of the latest assistant messages that hold one (`services/tooltips.py`), or of the page older than `before` (a message sequence; `limit` at most 50). Returns `{messages: [{message_id, sequence, annotations}]}`, each annotation with `start`, `end` (offsets in the raw text), `entity_id`, `entity_type` and `label`: the live entity (merge tombstones followed) and what the player may read for it (`display_for_player`, a secret name replaced by a readable descriptor or alias; a mention of an entity with nothing readable is left out).
- `GET /api/tooltips/entity?gameId={id}&id={uuid}`: hover card of one entity of the game, by id (a merge tombstone gives its survivor; an arc gets its title and domain). Returns `{found: true, tooltip: {icon, name, type, infos, relation}}`, or `{found: false}` only when the id is no entity nor arc of the game. An NPC the protagonist has not identified shows its descriptor and what anyone can observe (species, mood, ambient), never its occupation, description or relation; `relation` is the type of the protagonist's latest open relation to an identified NPC (null otherwise, and for any other entity); an entity with nothing readable shows the language pack's unknown label (`unknown_character_label` for a character, `unknown_entity_label` otherwise) and no detail.
- `GET /api/tooltips/entities?gameId={id}&ids={uuid},{uuid}`: the same cards in batch, `{tooltips: {<id>: tooltip}}` keyed by the id asked for; at most 100 ids (422 beyond, or on a malformed id); an id that is no entity nor arc of the game is absent.

The mentions live only in `entity_mentions` (one row per occurrence of a linked surface, by entity id, written by the resolver v2 after the turn commits). The legacy column `messages.narrator_context` (`[start, end, label, type]` spans) is no longer written nor read by the application (#155): only the identity backfill still reads it, to rebuild the mentions of a game not yet backfilled, and the dry-run report, which previews that step. The column is dropped by #166, after the identity backfill has run in production (`dbmate up` runs before the backfill).

Every route that reads a game id (path, query, header or body) must check ownership: `backend/tests/test_game_ownership_guard.py` lists them from the OpenAPI schema and calls each one as another user (403, game unchanged), so a new game route without the check fails CI until it is added there. `PATCH /games/{id}` takes the id from the path only (its body is `{name}`).

Tooltips are looked up by entity id. The hover card of a character not yet identified shows `display_for_player` as its name and no occupation, description or relation. Whatever the entity, a detail line whose text holds one of its hidden names (a secret alias, an unknown alias other than a descriptor, its true name while unknown) is left out, except an object's description (PR 4). Line labels and unknown labels come from the game's language pack (`tooltip_labels`, `unknown_character_label`, `unknown_entity_label`); the species not worth a line comes from the genre pack (`default_species`), else `IDENTITY_DEFAULT_SPECIES`.

**Frontend:** `useTooltips(gameId, messageIds)` hook (the chat's message ids: a message no longer shown loses its mentions), refreshed on the `onSaved` event. It keeps `spansByMessage` (`{message_id: [{start, end, entity_id}]}`, each annotations page merged into the known spans, older pages read back with `before` while a page brings a new message or changes a known one (a reveal, a merge); a message leaves it only when the chat no longer shows it) and `tooltipMap` (`{entity_id: tooltip}`, filled by the batch endpoint for new ids and for entities whose label changed). `injectEntityMarkers(text, spans)` writes each span as an `entity:<id>` link by offset (code points), only inside one plain text node of the markdown parse; `Message.jsx` renders that link with the tooltip of its id. Mentions are never matched by name.

### World Sidebar

**File:** `backend/api/routes.py` — `GET /games/{id}/world`

Returns (`services/world_panel.py`):
- `npcs`: every active NPC under what the player may read for it, with `known` (identified by the protagonist under a true name that is no secret); an NPC not identified shows no occupation, description nor relation, and a detail holding one of an entity's hidden names is left out
- `locations`: the locations (type, sector) under their readable label; one with nothing readable is left out
- `quests`: narrative arcs with `arc_type = 'quest'`
- `organizations`: the organizations under their readable label, same rule

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
| `WORLD_PENDING` | Reopened game whose world was never generated: retry, edit the parameters, or back (#88) |
| `GENERATING_WORLD` | Progress bar with partial JSON parsing; on failure, retry / edit / back |
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
- Exposes world generation handlers (handleStartAdventure, handleWizardComplete, handleRetryWorld)
- Manages local state: `editingIndex`, `lastUserMessage`, `invocationData`

### Phase Routing

`page.js` renders different components based on phase (checked top-to-bottom, first match wins):

1. Auth loading → spinner
2. Not authenticated → redirect to `/login/`
3. `SETTINGS` → `SettingsPage`
4. `LIST` or no gameId (and not wizard) → `GamesList`
5. `WIZARD` → `WizardContainer`
6. `WORLD_PENDING` → `WorldPendingScreen`
7. `GENERATING_WORLD` or `WORLD_READY` → `WorldGenerationScreen`
8. `STARTING_ADVENTURE` with no messages → loading spinner
9. Default (PLAYING) → main game UI (header, stats, messages, input, sidebars)

---

## 14. Background jobs

**Files:** `backend/workers/supervisor.py`, `workers/game_locks.py`, `pipeline/post_turn.py`, `services/hooks.py`, `services/subscribers.py`

`workers/` is the lowest layer: it imports no other layer of the backend (`tests/test_architecture.py`). It owns the in-process concurrency primitives; nothing else keeps a per-game lock or queue.

### Supervisor

Every background job goes through `supervisor.enqueue(game_id, kind, coro)`: the `post_turn` job of each committed turn (resolver, extraction, hooks) and the `director_initial` job of world generation. `asyncio.create_task` is used only in `workers/supervisor.py`, `pipeline/uncancellable.py` (the shield) and twice in `api/routes.py` (the busy rejection and the turn task, tied to the SSE writer); the grep gate of the phase checklist lists them.

- **Order.** The jobs of one game run one after the other, in enqueue order. A job waits for every unfinished job of its game, not only the last one: if a queued middle job is cancelled, an earlier job may still be running, and chaining on the last one alone would let two jobs of one game overlap. A cancelled or failed predecessor does not block the next job, and a job never cancels its predecessor.
- **Bounds.** At most `SUPERVISOR_MAX_GAMES` (default 3, at least 1) games run a job at once (a semaphore taken after the chain wait, so a queued job holds no slot). A warning `[SUPERVISOR] game=... queue depth=N` is logged when a game has more than 3 unfinished jobs.
- **Settings.** `SUPERVISOR_MAX_GAMES`, `SUPERVISOR_DRAIN_TIMEOUT` (default 20 s) and `SUPERVISOR_CANCEL_TIMEOUT` (default 10 s) are read when `Settings()` is built and validated there: `SUPERVISOR_MAX_GAMES` must be at least 1 and the two timeouts must be greater than 0; the error names the env var.
- **Journals.** A task is named `kind:game_id` and referenced until it ends. A failure is logged at ERROR (`[SUPERVISOR] <kind> failed game=...`, exception type only, no story text); cancellation at INFO; success at DEBUG.
- **Cancellation at rollback.** `cancel_game(game_id, timeout=...)` cancels the unfinished jobs of a game and waits for them (§7). Combined with the `FOR SHARE` guard of §5, a rolled-back turn cannot write its extraction or Director plan afterwards. A write that wins the race and commits before the rollback's DELETE is journaled under the turn, so the replay of §7 undoes it.
- **Drain.** At shutdown the lifespan calls `drain(SUPERVISOR_DRAIN_TIMEOUT)`: jobs get that long to finish, then the rest is cancelled (`[SUPERVISOR] Cancelled at shutdown kind=... game=...`) with a 5 s grace. The pool and the shared HTTP clients are always closed afterwards, even if the drain raised. `docker-compose.yml` sets `stop_grace_period: 30s` to cover both.
- **Rule for jobs.** A job must not await `wait_idle` on its own game, nor a job it enqueued on its own game: successors wait on the current job, so such an await blocks until its timeout.
- **Single worker.** The queues and the game locks live in the process. The backend refuses to start with `WEB_CONCURRENCY` or `UVICORN_WORKERS` above 1 (`startup_checks.py`).
- **Pool.** Pooled connections set `idle_in_transaction_session_timeout=30s` and `statement_timeout=60s` (`main.POOL_SERVER_SETTINGS`). Jobs hold no connection during an LLM call.
- **Limits.** Jobs are in memory: a crash loses the queue (follow-up #140, persist jobs in Postgres). A restart during world generation is handled by the retry of `__INIT__`.

### Game locks

`workers/game_locks.hold(game_id)` serialises the turns of a game (and the rollback); `is_held` feeds the busy decision. An entry is dropped once no turn holds or awaits it, so the map stays bounded (#94).

### Post-turn hooks

`pipeline/post_turn.run_post_turn` runs, in this order: the resolver, the extractors (if triggered), then, when the turn started a new in-game day, `hooks.run_new_cycle`, then `hooks.run_turn_committed`. It is the only caller of the hooks.

- `@hooks.on_turn_committed` subscribers `(pool, session, event: TurnCommitted)` run after every turn, each on its own: a failure is logged (`[HOOKS] turn_committed subscriber ... failed`) and the next one still runs. The scheduled Director is one of them. They run outside any guard.
- `@hooks.on_new_cycle` subscribers `(conn, game_id, cycle)` run in one `uow(conn, event.turn_id, source_message_id=event.assistant_message_id)` (the turn's assistant message is share-locked and the writes are journaled under the turn): one failure rolls them all back, and a turn already rolled back runs nothing. The engine's `on_new_cycle` and the archiving of seeds older than 10 cycles are subscribers.
- **How to subscribe.** Decorate an async function in `services/subscribers.py` (or any module imported before the first turn); registration is idempotent. Only `on_new_cycle` subscribers are guarded by the runner: an `on_turn_committed` subscriber that writes must open `uow(conn, event.turn_id, source_message_id=event.assistant_message_id)` itself, so its writes are guarded and journaled under the turn, and skip them on `SourceMessageGone`, as `director_apply` does (see `services/hooks.py`). `register_defaults()` runs once at import in `main.py` and before each test (`conftest`); tests reset with `hooks.reset()`.
- The Director run is split in `director_context` (collect, reads), the LLM call (no connection held) and `director_apply` (plan and arc updates in one `uow` under the `FOR SHARE` guard, journaled under the turn).

### Data robustness added with the supervisor (#27)

An unknown enum value is never mapped to the first member any more (`schema/core.py::_normalize_enum_value`, WARNING with the value cut to 40 characters): the normalizers either use an explicit fallback (`FactType.OTHER` for facts, a documented value elsewhere) or reject the item (`entity_type`, `relation_type`, moment), so the extractor's per-item savepoint drops that item alone. World generation drops an `initial_relations` entry with an unknown `relation_type` (WARNING) instead of failing the world after the paid call; the synonyms `connait`, `connaît` and `connu` map to `knows`. No migration.

### LLM call ledger (#106)

**Files:** `backend/llm/call_log.py`, `backend/repos/llm_calls.py`, `db/migrations/20261019000002_llm_calls.sql`

Every billed LLM call is a row of `llm_calls` (`turn_id`, `game_id`, `user_id`, `purpose`, `provider`, `model`, `usage` jsonb, `cost_usd`, `cost_unknown` for unpriced models, `created_at`). It is accounting, not world state: never journaled, written outside any turn transaction.

- **Buffered, flushed once per phase.** `LLMSession` appends each call to a `CallLog` (memory only) with `created_at` = the call's time. The phase flushes it with one multi-row insert in a `finally`, so halted, failed and disconnected work is logged too: the request (`session.flush_calls()` in the route, **after the game lock is released**), the `post_turn` job (its own buffer, `session.for_background()`), the initial world generation (`init_flow`), the `director_initial` job and `/world/enhance`. It never goes through the supervisor: a rollback cancelling the jobs would drop the rows. The flush acquires its own pool connection (bounded wait, `FLUSH_ACQUIRE_TIMEOUT`); a flush failure is logged at ERROR and never raised.
- **Deleted turn or game.** `llm_calls.turn_id` and `game_id` are ON DELETE SET NULL, and the insert stores NULL for a turn or game already gone. A rollback or a deleted game therefore keeps its paid calls in the account total. A deletion racing the insert raises a foreign key violation, retried once.
- **`/session/cost`.** The user's all-time total, summed per purpose then per model from `llm_calls` (`repos.llm_calls.user_summary`): it survives a restart or a redeploy (it used to be a per-process total) and covers only the requesting user's calls.

### Follow-ups

#139 (`tests/workers` shadows the `workers` package), #140 (persist jobs in Postgres), #22 (journal-based rollback: P5b).
