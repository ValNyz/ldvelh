-- migrate:up

-- ============================================================================
-- ENGINE COLUMNS ON GAMES
-- ============================================================================

ALTER TABLE games ADD COLUMN engine VARCHAR(20) NOT NULL DEFAULT 'none';
ALTER TABLE games ADD COLUMN engine_locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE games ADD COLUMN world_config JSONB;

-- ============================================================================
-- ENGINE CHARACTER TABLES (1:1 with game, protagonist only)
-- ============================================================================

CREATE TABLE character_fate (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID UNIQUE NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  aspects JSONB DEFAULT '[]',
  stunts JSONB DEFAULT '[]',
  stress_physical BOOLEAN[] DEFAULT '{f,f,f,f}',
  stress_mental BOOLEAN[] DEFAULT '{f,f,f,f}',
  consequences JSONB DEFAULT '{}',
  fate_points INTEGER DEFAULT 3,
  refresh INTEGER DEFAULT 3,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE character_d6 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID UNIQUE NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  attributes JSONB DEFAULT '{}',
  wounds JSONB DEFAULT '{}',
  force_points INTEGER DEFAULT 3,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE character_narrative (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID UNIQUE NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- PER-ENGINE SKILL / TRAIT TABLES
-- ============================================================================

CREATE TABLE skills_fate (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  name VARCHAR(100) NOT NULL,
  level INTEGER NOT NULL DEFAULT 0,
  custom BOOLEAN DEFAULT FALSE,
  UNIQUE(game_id, name)
);

CREATE TABLE skills_d6 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  attribute VARCHAR(50) NOT NULL,
  name VARCHAR(100) NOT NULL,
  dice_value VARCHAR(10) NOT NULL,
  custom BOOLEAN DEFAULT FALSE,
  UNIQUE(game_id, name)
);

CREATE TABLE traits_narrative (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  name VARCHAR(200) NOT NULL,
  description TEXT,
  active BOOLEAN DEFAULT TRUE,
  replaced_by UUID REFERENCES traits_narrative(id),
  created_cycle INTEGER DEFAULT 1,
  UNIQUE(game_id, name)
);

CREATE INDEX idx_skills_fate_game ON skills_fate(game_id);
CREATE INDEX idx_skills_d6_game ON skills_d6(game_id);
CREATE INDEX idx_traits_narrative_game ON traits_narrative(game_id) WHERE active = TRUE;

-- ============================================================================
-- MECHANIC ROLLS LOG
-- ============================================================================

CREATE TABLE mechanic_rolls (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
  engine VARCHAR(20) NOT NULL,
  skill_used VARCHAR(100),
  roll_details JSONB NOT NULL,
  outcome VARCHAR(50) NOT NULL,
  complication BOOLEAN DEFAULT FALSE,
  cycle INTEGER,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_mechanic_rolls_game ON mechanic_rolls(game_id, cycle);

-- ============================================================================
-- ITEM ENGINE EXTENSIONS (FK to existing objects table)
-- ============================================================================

CREATE TABLE object_d6 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  object_id UUID UNIQUE NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
  stats JSONB DEFAULT '{}'
);

CREATE TABLE object_fate (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  object_id UUID UNIQUE NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
  item_type VARCHAR(20),
  stunts JSONB DEFAULT '[]'
);

CREATE TABLE object_narrative (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  object_id UUID UNIQUE NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
  narrative_description TEXT
);

-- ============================================================================
-- ENGINE STATE SNAPSHOT ON MESSAGES (for rollback)
-- ============================================================================

ALTER TABLE messages ADD COLUMN engine_snapshot JSONB;

-- ============================================================================
-- UPDATE ROLLBACK FUNCTION — add mechanic_rolls cleanup
-- ============================================================================

CREATE OR REPLACE FUNCTION rollback_to_cycle(
  p_game_id UUID,
  p_target_cycle INTEGER
)
RETURNS TABLE(
  deleted_facts INTEGER,
  deleted_events INTEGER,
  deleted_arcs INTEGER,
  reverted_relations INTEGER
) LANGUAGE plpgsql AS $func$
DECLARE
  v_deleted_facts INTEGER;
  v_deleted_events INTEGER;
  v_deleted_arcs INTEGER;
  v_reverted_relations INTEGER;
BEGIN
  -- Facts (immutable but we delete via DELETE, not UPDATE)
  DELETE FROM facts WHERE game_id = p_game_id AND cycle > p_target_cycle;
  GET DIAGNOSTICS v_deleted_facts = ROW_COUNT;

  -- Events
  DELETE FROM events WHERE game_id = p_game_id AND planned_cycle > p_target_cycle;
  GET DIAGNOSTICS v_deleted_events = ROW_COUNT;

  -- Narrative arcs created after target cycle
  DELETE FROM narrative_arcs WHERE game_id = p_game_id
    AND created_at > (SELECT created_at FROM chronology WHERE game_id = p_game_id AND cycle = p_target_cycle LIMIT 1);
  GET DIAGNOSTICS v_deleted_arcs = ROW_COUNT;

  -- Relations created after target cycle
  DELETE FROM relations WHERE game_id = p_game_id AND start_cycle > p_target_cycle;
  GET DIAGNOSTICS v_reverted_relations = ROW_COUNT;

  -- Reactivate relations ended after target cycle
  UPDATE relations SET end_cycle = NULL, end_reason = NULL
  WHERE game_id = p_game_id AND end_cycle > p_target_cycle;

  -- Skills (legacy)
  DELETE FROM skills WHERE game_id = p_game_id AND start_cycle > p_target_cycle;
  UPDATE skills SET end_cycle = NULL WHERE game_id = p_game_id AND end_cycle > p_target_cycle;

  -- Mechanic rolls
  DELETE FROM mechanic_rolls WHERE game_id = p_game_id AND cycle > p_target_cycle;

  -- Messages and chronology
  DELETE FROM messages WHERE game_id = p_game_id AND cycle > p_target_cycle;
  DELETE FROM chronology WHERE game_id = p_game_id AND cycle > p_target_cycle;
  DELETE FROM extraction_logs WHERE game_id = p_game_id AND cycle > p_target_cycle;

  -- Entities created after target cycle
  DELETE FROM characters WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM locations WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM organizations WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM objects WHERE game_id = p_game_id AND created_cycle > p_target_cycle;

  UPDATE games SET updated_at = now() WHERE id = p_game_id;

  RETURN QUERY SELECT v_deleted_facts, v_deleted_events, v_deleted_arcs, v_reverted_relations;
END;
$func$;


-- migrate:down

-- Drop engine extensions
DROP TABLE IF EXISTS object_narrative;
DROP TABLE IF EXISTS object_fate;
DROP TABLE IF EXISTS object_d6;

-- Drop mechanic rolls
DROP TABLE IF EXISTS mechanic_rolls;

-- Drop skill/trait tables
DROP TABLE IF EXISTS traits_narrative;
DROP TABLE IF EXISTS skills_d6;
DROP TABLE IF EXISTS skills_fate;

-- Drop character tables
DROP TABLE IF EXISTS character_narrative;
DROP TABLE IF EXISTS character_d6;
DROP TABLE IF EXISTS character_fate;

-- Remove columns from messages
ALTER TABLE messages DROP COLUMN IF EXISTS engine_snapshot;

-- Remove columns from games
ALTER TABLE games DROP COLUMN IF EXISTS world_config;
ALTER TABLE games DROP COLUMN IF EXISTS engine_locked;
ALTER TABLE games DROP COLUMN IF EXISTS engine;

-- Restore original rollback function (without mechanic_rolls line)
CREATE OR REPLACE FUNCTION rollback_to_cycle(
  p_game_id UUID,
  p_target_cycle INTEGER
)
RETURNS TABLE(
  deleted_facts INTEGER,
  deleted_events INTEGER,
  deleted_arcs INTEGER,
  reverted_relations INTEGER
) LANGUAGE plpgsql AS $func$
DECLARE
  v_deleted_facts INTEGER;
  v_deleted_events INTEGER;
  v_deleted_arcs INTEGER;
  v_reverted_relations INTEGER;
BEGIN
  DELETE FROM facts WHERE game_id = p_game_id AND cycle > p_target_cycle;
  GET DIAGNOSTICS v_deleted_facts = ROW_COUNT;
  DELETE FROM events WHERE game_id = p_game_id AND planned_cycle > p_target_cycle;
  GET DIAGNOSTICS v_deleted_events = ROW_COUNT;
  DELETE FROM narrative_arcs WHERE game_id = p_game_id
    AND created_at > (SELECT created_at FROM chronology WHERE game_id = p_game_id AND cycle = p_target_cycle LIMIT 1);
  GET DIAGNOSTICS v_deleted_arcs = ROW_COUNT;
  DELETE FROM relations WHERE game_id = p_game_id AND start_cycle > p_target_cycle;
  GET DIAGNOSTICS v_reverted_relations = ROW_COUNT;
  UPDATE relations SET end_cycle = NULL, end_reason = NULL
  WHERE game_id = p_game_id AND end_cycle > p_target_cycle;
  DELETE FROM skills WHERE game_id = p_game_id AND start_cycle > p_target_cycle;
  UPDATE skills SET end_cycle = NULL WHERE game_id = p_game_id AND end_cycle > p_target_cycle;
  DELETE FROM messages WHERE game_id = p_game_id AND cycle > p_target_cycle;
  DELETE FROM chronology WHERE game_id = p_game_id AND cycle > p_target_cycle;
  DELETE FROM extraction_logs WHERE game_id = p_game_id AND cycle > p_target_cycle;
  DELETE FROM characters WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM locations WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM organizations WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM objects WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  UPDATE games SET updated_at = now() WHERE id = p_game_id;
  RETURN QUERY SELECT v_deleted_facts, v_deleted_events, v_deleted_arcs, v_reverted_relations;
END;
$func$;
