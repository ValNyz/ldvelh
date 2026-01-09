-- ============================================================================
-- LDVELH - Final Database Schema
-- Architecture: CORE → NARRATION → HISTORY
-- All names in English
-- ============================================================================

-- ============================================================================
-- ENUMS
-- ============================================================================

CREATE TYPE entity_type AS ENUM (
  'protagonist', 'character', 'location', 'object', 'ai', 'organization'
);

CREATE TYPE relation_type AS ENUM (
  'knows', 'friend_of', 'enemy_of', 'family_of', 'romantic',
  'employed_by', 'colleague_of', 'manages',
  'frequents', 'lives_at', 'located_in', 'works_at',
  'owns', 'owes_to'
);

CREATE TYPE certainty_level AS ENUM (
  'certain', 'probable', 'rumor', 'uncertain'
);

CREATE TYPE fact_type AS ENUM (
  'action', 'dialogue', 'discovery', 'incident', 'encounter'
);

CREATE TYPE fact_domain AS ENUM (
  'personal', 'professional', 'romantic', 'social', 'exploration', 'financial', 'other'
);

CREATE TYPE participant_role AS ENUM (
  'actor', 'witness', 'target', 'mentioned'
);

CREATE TYPE event_type AS ENUM (
  'appointment', 'deadline', 'celebration', 'recurring', 'financial_due'
);

CREATE TYPE commitment_type AS ENUM (
  'foreshadowing', 'secret', 'setup', 'chekhov_gun', 'arc'
);

CREATE TYPE contradiction_type AS ENUM (
  'temporal', 'factual', 'relational', 'spatial'
);

CREATE TYPE contradiction_resolution AS ENUM (
  'keep_existing', 'accept_new', 'merge', 'manual'
);

-- ============================================================================
-- CORE: GAMES
-- ============================================================================

CREATE TABLE games (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) DEFAULT 'New Game',
  active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- CORE: ENTITIES (parent table)
-- ============================================================================

CREATE TABLE entities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  type entity_type NOT NULL,
  name VARCHAR(255) NOT NULL,
  aliases TEXT[] DEFAULT '{}',
  confirmed BOOLEAN DEFAULT true,
  created_cycle INTEGER NOT NULL DEFAULT 1,
  removed_cycle INTEGER,
  removal_reason TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_id, type, name)
);

CREATE INDEX idx_entities_game ON entities(game_id);
CREATE INDEX idx_entities_type ON entities(game_id, type);
CREATE INDEX idx_entities_name ON entities(game_id, name);
CREATE INDEX idx_entities_aliases ON entities USING GIN(aliases);
CREATE INDEX idx_entities_active ON entities(game_id) 
  WHERE removed_cycle IS NULL;

-- ============================================================================
-- CORE: TYPED ENTITY TABLES
-- ============================================================================

CREATE TABLE entity_protagonists (
  entity_id UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
  origin_location VARCHAR(100),
  departure_reason TEXT,
  backstory TEXT
);

CREATE TABLE entity_characters (
  entity_id UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
  species VARCHAR(50) DEFAULT 'human',
  gender VARCHAR(20),
  pronouns VARCHAR(20),
  station_arrival_cycle INTEGER,
  origin_location VARCHAR(100),
  physical_description TEXT,
  traits TEXT
);

CREATE TABLE entity_locations (
  entity_id UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
  location_type VARCHAR(50),
  sector VARCHAR(50),
  parent_location_id UUID REFERENCES entities(id) ON DELETE SET NULL,
  accessible BOOLEAN DEFAULT true
);

CREATE INDEX idx_locations_parent ON entity_locations(parent_location_id);
CREATE INDEX idx_locations_sector ON entity_locations(sector);

CREATE TABLE entity_objects (
  entity_id UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
  category VARCHAR(50),
  transportable BOOLEAN DEFAULT true,
  stackable BOOLEAN DEFAULT false,
  base_value INTEGER DEFAULT 0
);

CREATE TABLE entity_ais (
  entity_id UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
  creator_id UUID REFERENCES entities(id) ON DELETE SET NULL,
  ai_creation_cycle INTEGER,
  substrate VARCHAR(50),
  traits TEXT
);

CREATE TABLE entity_organizations (
  entity_id UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
  org_type VARCHAR(50),
  domain VARCHAR(100),
  size VARCHAR(20),
  founding_cycle INTEGER,
  headquarters_id UUID REFERENCES entities(id) ON DELETE SET NULL
);

-- ============================================================================
-- CORE: SKILLS
-- ============================================================================

CREATE TABLE skills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  name VARCHAR(50) NOT NULL,
  level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 5),
  start_cycle INTEGER NOT NULL,
  end_cycle INTEGER,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_id, entity_id, name, start_cycle)
);

CREATE INDEX idx_skills_entity ON skills(entity_id);
CREATE INDEX idx_skills_active ON skills(entity_id) WHERE end_cycle IS NULL;

-- ============================================================================
-- CORE: ATTRIBUTES
-- ============================================================================

CREATE TABLE attributes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  key VARCHAR(100) NOT NULL,
  value TEXT NOT NULL,
  details JSONB,
  start_cycle INTEGER NOT NULL,
  end_cycle INTEGER,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_attributes_entity ON attributes(entity_id);
CREATE INDEX idx_attributes_key ON attributes(entity_id, key);
CREATE INDEX idx_attributes_active ON attributes(entity_id) WHERE end_cycle IS NULL;
CREATE INDEX idx_attributes_game ON attributes(game_id);

-- ============================================================================
-- CORE: RELATIONS (parent table)
-- ============================================================================

CREATE TABLE relations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  source_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  target_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  type relation_type NOT NULL,
  start_cycle INTEGER NOT NULL,
  end_cycle INTEGER,
  end_reason TEXT,
  certainty certainty_level DEFAULT 'certain',
  is_true BOOLEAN DEFAULT true,
  source_info VARCHAR(255),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_id, source_id, target_id, type, start_cycle)
);

CREATE INDEX idx_relations_game ON relations(game_id);
CREATE INDEX idx_relations_source ON relations(source_id);
CREATE INDEX idx_relations_target ON relations(target_id);
CREATE INDEX idx_relations_type ON relations(game_id, type);
CREATE INDEX idx_relations_active ON relations(game_id) WHERE end_cycle IS NULL;

-- ============================================================================
-- CORE: TYPED RELATION TABLES
-- ============================================================================

CREATE TABLE relations_social (
  relation_id UUID PRIMARY KEY REFERENCES relations(id) ON DELETE CASCADE,
  level INTEGER CHECK (level BETWEEN 0 AND 10),
  context TEXT,
  romantic_stage INTEGER CHECK (romantic_stage BETWEEN 0 AND 6),
  family_bond VARCHAR(30)
);

CREATE TABLE relations_professional (
  relation_id UUID PRIMARY KEY REFERENCES relations(id) ON DELETE CASCADE,
  position VARCHAR(100),
  position_start_cycle INTEGER,
  part_time BOOLEAN DEFAULT false
);

CREATE TABLE relations_spatial (
  relation_id UUID PRIMARY KEY REFERENCES relations(id) ON DELETE CASCADE,
  regularity VARCHAR(30),
  time_of_day VARCHAR(50)
);

CREATE TABLE relations_ownership (
  relation_id UUID PRIMARY KEY REFERENCES relations(id) ON DELETE CASCADE,
  quantity INTEGER DEFAULT 1,
  origin VARCHAR(30),
  amount INTEGER,
  acquisition_cycle INTEGER
);

-- ============================================================================
-- CORE: FACTS (immutable past events)
-- ============================================================================

CREATE TABLE facts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  cycle INTEGER NOT NULL,
  moment VARCHAR(20),
  type fact_type NOT NULL,
  domain fact_domain DEFAULT 'other',
  description TEXT NOT NULL,
  location_id UUID REFERENCES entities(id) ON DELETE SET NULL,
  importance INTEGER DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_facts_game ON facts(game_id);
CREATE INDEX idx_facts_cycle ON facts(game_id, cycle);
CREATE INDEX idx_facts_type ON facts(game_id, type);
CREATE INDEX idx_facts_domain ON facts(game_id, domain);
CREATE INDEX idx_facts_importance ON facts(game_id, importance DESC);
CREATE INDEX idx_facts_location ON facts(location_id);

CREATE OR REPLACE FUNCTION prevent_fact_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $func$
BEGIN
  RAISE EXCEPTION 'Facts are immutable and cannot be updated';
END;
$func$;

CREATE TRIGGER facts_immutable
BEFORE UPDATE ON facts
FOR EACH ROW EXECUTE FUNCTION prevent_fact_update();

CREATE TABLE fact_participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  role participant_role NOT NULL,
  UNIQUE(fact_id, entity_id)
);

CREATE INDEX idx_fact_participants_fact ON fact_participants(fact_id);
CREATE INDEX idx_fact_participants_entity ON fact_participants(entity_id);

-- ============================================================================
-- CORE: BELIEFS (what the protagonist thinks they know)
-- ============================================================================

CREATE TABLE beliefs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  subject_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  key VARCHAR(100) NOT NULL,
  content TEXT NOT NULL,
  is_true BOOLEAN DEFAULT true,
  certainty certainty_level DEFAULT 'certain',
  source_fact_id UUID REFERENCES facts(id) ON DELETE SET NULL,
  acquisition_cycle INTEGER NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_id, subject_id, key)
);

CREATE INDEX idx_beliefs_game ON beliefs(game_id);
CREATE INDEX idx_beliefs_subject ON beliefs(subject_id);
CREATE INDEX idx_beliefs_false ON beliefs(game_id) WHERE is_true = false;

-- ============================================================================
-- CORE: CONTRADICTIONS
-- ============================================================================

CREATE TABLE contradictions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  detection_cycle INTEGER NOT NULL,
  type contradiction_type NOT NULL,
  entity_id UUID REFERENCES entities(id) ON DELETE CASCADE,
  relation_id UUID REFERENCES relations(id) ON DELETE CASCADE,
  field_name VARCHAR(100),
  existing_value TEXT,
  new_value TEXT,
  existing_source VARCHAR(255),
  new_source VARCHAR(255),
  resolved BOOLEAN DEFAULT false,
  resolution contradiction_resolution,
  resolution_notes TEXT,
  resolution_cycle INTEGER,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_contradictions_game ON contradictions(game_id);
CREATE INDEX idx_contradictions_open ON contradictions(game_id) WHERE resolved = false;

-- ============================================================================
-- NARRATION: EVENTS
-- ============================================================================

CREATE TABLE events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  type event_type NOT NULL,
  category VARCHAR(50),
  title VARCHAR(255) NOT NULL,
  description TEXT,
  planned_cycle INTEGER NOT NULL,
  moment VARCHAR(20),
  location_id UUID REFERENCES entities(id) ON DELETE SET NULL,
  recurrence JSONB,
  amount INTEGER,
  source_fact_id UUID REFERENCES facts(id) ON DELETE SET NULL,
  completed BOOLEAN DEFAULT false,
  cancelled BOOLEAN DEFAULT false,
  cancellation_reason TEXT,
  resolution_fact_id UUID REFERENCES facts(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_events_game ON events(game_id);
CREATE INDEX idx_events_cycle ON events(game_id, planned_cycle);
CREATE INDEX idx_events_active ON events(game_id, planned_cycle) 
  WHERE completed = false AND cancelled = false;

CREATE TABLE event_participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  role VARCHAR(50),
  confirmed BOOLEAN DEFAULT false,
  UNIQUE(event_id, entity_id)
);

CREATE INDEX idx_event_participants_event ON event_participants(event_id);
CREATE INDEX idx_event_participants_entity ON event_participants(entity_id);

-- ============================================================================
-- NARRATION: COMMITMENTS
-- ============================================================================

CREATE TABLE commitments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  type commitment_type NOT NULL,
  description TEXT NOT NULL,
  created_cycle INTEGER NOT NULL,
  deadline_cycle INTEGER,
  resolved BOOLEAN DEFAULT false,
  resolution_fact_id UUID REFERENCES facts(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_commitments_game ON commitments(game_id);
CREATE INDEX idx_commitments_unresolved ON commitments(game_id) WHERE resolved = false;
CREATE INDEX idx_commitments_deadline ON commitments(game_id, deadline_cycle) 
  WHERE resolved = false AND deadline_cycle IS NOT NULL;

CREATE TABLE commitment_arcs (
  commitment_id UUID PRIMARY KEY REFERENCES commitments(id) ON DELETE CASCADE,
  objective TEXT NOT NULL,
  obstacle TEXT NOT NULL,
  progress INTEGER DEFAULT 0 CHECK (progress BETWEEN 0 AND 100)
);

CREATE TABLE commitment_entities (
  commitment_id UUID NOT NULL REFERENCES commitments(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  role VARCHAR(50),
  PRIMARY KEY (commitment_id, entity_id)
);

CREATE INDEX idx_commitment_entities_entity ON commitment_entities(entity_id);

-- ============================================================================
-- HISTORY: CHAT MESSAGES
-- ============================================================================

CREATE TABLE chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  role VARCHAR(20) NOT NULL,
  content TEXT NOT NULL,
  cycle INTEGER NOT NULL,
  day INTEGER,
  date VARCHAR(50),
  location_id UUID REFERENCES entities(id) ON DELETE SET NULL,
  npcs_present UUID[] DEFAULT '{}',
  summary TEXT,
  state_snapshot JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_messages_game ON chat_messages(game_id);
CREATE INDEX idx_messages_cycle ON chat_messages(game_id, cycle);
CREATE INDEX idx_messages_summary ON chat_messages(game_id, cycle) 
  WHERE summary IS NOT NULL;

-- ============================================================================
-- HISTORY: CYCLE SUMMARIES
-- ============================================================================

CREATE TABLE cycle_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  cycle INTEGER NOT NULL,
  day INTEGER,
  date VARCHAR(50),
  summary TEXT,
  key_events JSONB,
  modified_relations JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_id, cycle)
);

CREATE INDEX idx_summaries_game ON cycle_summaries(game_id, cycle);

-- ============================================================================
-- HISTORY: EXTRACTION LOGS
-- ============================================================================

CREATE TABLE extraction_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  cycle INTEGER NOT NULL,
  duration_ms INTEGER,
  operations_count INTEGER DEFAULT 0,
  entities_created INTEGER DEFAULT 0,
  relations_created INTEGER DEFAULT 0,
  facts_created INTEGER DEFAULT 0,
  attributes_modified INTEGER DEFAULT 0,
  contradictions_found INTEGER DEFAULT 0,
  contradictions JSONB,
  errors JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_logs_game ON extraction_logs(game_id);
CREATE INDEX idx_logs_cycle ON extraction_logs(game_id, cycle);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

CREATE OR REPLACE FUNCTION find_entity(
  p_game_id UUID,
  p_name TEXT,
  p_type entity_type DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $func$
DECLARE
  v_id UUID;
  v_name_lower TEXT := LOWER(TRIM(p_name));
BEGIN
  SELECT id INTO v_id
  FROM entities
  WHERE game_id = p_game_id
    AND (p_type IS NULL OR type = p_type)
    AND removed_cycle IS NULL
    AND LOWER(name) = v_name_lower
  LIMIT 1;
  
  IF v_id IS NOT NULL THEN RETURN v_id; END IF;
  
  SELECT id INTO v_id
  FROM entities
  WHERE game_id = p_game_id
    AND (p_type IS NULL OR type = p_type)
    AND removed_cycle IS NULL
    AND v_name_lower = ANY(SELECT LOWER(unnest(aliases)))
  LIMIT 1;
  
  IF v_id IS NOT NULL THEN RETURN v_id; END IF;
  
  SELECT id INTO v_id
  FROM entities
  WHERE game_id = p_game_id
    AND (p_type IS NULL OR type = p_type)
    AND removed_cycle IS NULL
    AND (
      LOWER(name) LIKE v_name_lower || ' %'
      OR LOWER(name) LIKE '% ' || v_name_lower
    )
  LIMIT 1;
  
  RETURN v_id;
END;
$func$;

CREATE OR REPLACE FUNCTION upsert_entity(
  p_game_id UUID,
  p_type entity_type,
  p_name VARCHAR(255),
  p_aliases TEXT[] DEFAULT '{}',
  p_cycle INTEGER DEFAULT 1,
  p_confirmed BOOLEAN DEFAULT true
)
RETURNS UUID
LANGUAGE plpgsql
AS $func$
DECLARE
  v_id UUID;
  v_existing_aliases TEXT[];
BEGIN
  v_id := find_entity(p_game_id, p_name, p_type);
  
  IF v_id IS NOT NULL THEN
    SELECT aliases INTO v_existing_aliases FROM entities WHERE id = v_id;
    
    UPDATE entities SET
      aliases = ARRAY(SELECT DISTINCT unnest(v_existing_aliases || p_aliases)),
      confirmed = GREATEST(confirmed::int, p_confirmed::int)::boolean,
      updated_at = NOW()
    WHERE id = v_id;
    
    RETURN v_id;
  ELSE
    INSERT INTO entities (game_id, type, name, aliases, created_cycle, confirmed)
    VALUES (p_game_id, p_type, p_name, p_aliases, p_cycle, p_confirmed)
    RETURNING id INTO v_id;
    
    RETURN v_id;
  END IF;
END;
$func$;

CREATE OR REPLACE FUNCTION set_attribute(
  p_game_id UUID,
  p_entity_id UUID,
  p_key VARCHAR(100),
  p_value TEXT,
  p_cycle INTEGER,
  p_details JSONB DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $func$
DECLARE
  v_id UUID;
  v_old_value TEXT;
BEGIN
  SELECT value INTO v_old_value
  FROM attributes
  WHERE entity_id = p_entity_id
    AND key = p_key
    AND end_cycle IS NULL;
  
  IF v_old_value = p_value THEN
    RETURN NULL;
  END IF;
  
  UPDATE attributes SET end_cycle = p_cycle
  WHERE entity_id = p_entity_id
    AND key = p_key
    AND end_cycle IS NULL;
  
  INSERT INTO attributes (game_id, entity_id, key, value, details, start_cycle)
  VALUES (p_game_id, p_entity_id, p_key, p_value, p_details, p_cycle)
  RETURNING id INTO v_id;
  
  RETURN v_id;
END;
$func$;

CREATE OR REPLACE FUNCTION upsert_relation(
  p_game_id UUID,
  p_source_id UUID,
  p_target_id UUID,
  p_type relation_type,
  p_cycle INTEGER DEFAULT 1,
  p_certainty certainty_level DEFAULT 'certain',
  p_is_true BOOLEAN DEFAULT true,
  p_source_info VARCHAR(255) DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $func$
DECLARE
  v_id UUID;
BEGIN
  SELECT id INTO v_id
  FROM relations
  WHERE game_id = p_game_id
    AND source_id = p_source_id
    AND target_id = p_target_id
    AND type = p_type
    AND end_cycle IS NULL;
  
  IF v_id IS NOT NULL THEN
    UPDATE relations SET
      certainty = p_certainty,
      is_true = p_is_true,
      source_info = COALESCE(p_source_info, source_info)
    WHERE id = v_id;
    
    RETURN v_id;
  ELSE
    INSERT INTO relations (
      game_id, source_id, target_id, type,
      start_cycle, certainty, is_true, source_info
    )
    VALUES (
      p_game_id, p_source_id, p_target_id, p_type,
      p_cycle, p_certainty, p_is_true, p_source_info
    )
    RETURNING id INTO v_id;
    
    RETURN v_id;
  END IF;
END;
$func$;

CREATE OR REPLACE FUNCTION end_relation(
  p_game_id UUID,
  p_source_name TEXT,
  p_target_name TEXT,
  p_type relation_type,
  p_cycle INTEGER,
  p_reason TEXT DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $func$
DECLARE
  v_source_id UUID;
  v_target_id UUID;
BEGIN
  v_source_id := find_entity(p_game_id, p_source_name);
  v_target_id := find_entity(p_game_id, p_target_name);
  
  IF v_source_id IS NULL OR v_target_id IS NULL THEN
    RETURN false;
  END IF;
  
  UPDATE relations SET
    end_cycle = p_cycle,
    end_reason = p_reason
  WHERE game_id = p_game_id
    AND source_id = v_source_id
    AND target_id = v_target_id
    AND type = p_type
    AND end_cycle IS NULL;
  
  RETURN FOUND;
END;
$func$;

CREATE OR REPLACE FUNCTION create_fact(
  p_game_id UUID,
  p_cycle INTEGER,
  p_type fact_type,
  p_description TEXT,
  p_domain fact_domain DEFAULT 'other',
  p_location_id UUID DEFAULT NULL,
  p_moment VARCHAR(20) DEFAULT NULL,
  p_importance INTEGER DEFAULT 3,
  p_participants JSONB DEFAULT '[]'
)
RETURNS UUID
LANGUAGE plpgsql
AS $func$
DECLARE
  v_fact_id UUID;
  v_participant JSONB;
  v_entity_id UUID;
BEGIN
  INSERT INTO facts (game_id, cycle, type, domain, description, location_id, moment, importance)
  VALUES (p_game_id, p_cycle, p_type, p_domain, p_description, p_location_id, p_moment, p_importance)
  RETURNING id INTO v_fact_id;
  
  FOR v_participant IN SELECT * FROM jsonb_array_elements(p_participants)
  LOOP
    v_entity_id := find_entity(p_game_id, v_participant->>'name');
    IF v_entity_id IS NOT NULL THEN
      INSERT INTO fact_participants (fact_id, entity_id, role)
      VALUES (
        v_fact_id, 
        v_entity_id, 
        COALESCE((v_participant->>'role')::participant_role, 'actor')
      )
      ON CONFLICT (fact_id, entity_id) DO NOTHING;
    END IF;
  END LOOP;
  
  RETURN v_fact_id;
END;
$func$;

CREATE OR REPLACE FUNCTION set_belief(
  p_game_id UUID,
  p_subject_id UUID,
  p_key VARCHAR(100),
  p_content TEXT,
  p_cycle INTEGER,
  p_is_true BOOLEAN DEFAULT true,
  p_certainty certainty_level DEFAULT 'certain',
  p_source_fact_id UUID DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $func$
DECLARE
  v_id UUID;
BEGIN
  INSERT INTO beliefs (
    game_id, subject_id, key, content, 
    is_true, certainty, source_fact_id, acquisition_cycle
  )
  VALUES (
    p_game_id, p_subject_id, p_key, p_content,
    p_is_true, p_certainty, p_source_fact_id, p_cycle
  )
  ON CONFLICT (game_id, subject_id, key) DO UPDATE SET
    content = EXCLUDED.content,
    is_true = EXCLUDED.is_true,
    certainty = EXCLUDED.certainty,
    source_fact_id = COALESCE(EXCLUDED.source_fact_id, beliefs.source_fact_id)
  RETURNING id INTO v_id;
  
  RETURN v_id;
END;
$func$;

CREATE OR REPLACE FUNCTION set_skill(
  p_game_id UUID,
  p_entity_id UUID,
  p_name VARCHAR(50),
  p_level INTEGER,
  p_cycle INTEGER
)
RETURNS UUID
LANGUAGE plpgsql
AS $func$
DECLARE
  v_id UUID;
  v_old_level INTEGER;
BEGIN
  SELECT level INTO v_old_level
  FROM skills
  WHERE entity_id = p_entity_id
    AND name = p_name
    AND end_cycle IS NULL;
  
  IF v_old_level = p_level THEN
    RETURN NULL;
  END IF;
  
  UPDATE skills SET end_cycle = p_cycle
  WHERE entity_id = p_entity_id
    AND name = p_name
    AND end_cycle IS NULL;
  
  INSERT INTO skills (game_id, entity_id, name, level, start_cycle)
  VALUES (p_game_id, p_entity_id, p_name, p_level, p_cycle)
  RETURNING id INTO v_id;
  
  RETURN v_id;
END;
$func$;

CREATE OR REPLACE FUNCTION credit_transaction(
  p_game_id UUID,
  p_amount INTEGER,
  p_cycle INTEGER,
  p_description TEXT DEFAULT NULL
)
RETURNS TABLE(success BOOLEAN, new_balance INTEGER, error TEXT)
LANGUAGE plpgsql
AS $func$
DECLARE
  v_protagonist_id UUID;
  v_current_balance INTEGER;
  v_new_balance INTEGER;
BEGIN
  SELECT e.id INTO v_protagonist_id
  FROM entities e
  WHERE e.game_id = p_game_id
    AND e.type = 'protagonist'
    AND e.removed_cycle IS NULL;
  
  IF v_protagonist_id IS NULL THEN
    RETURN QUERY SELECT false, 0, 'Protagonist not found'::TEXT;
    RETURN;
  END IF;
  
  SELECT COALESCE(a.value::INTEGER, 1400) INTO v_current_balance
  FROM attributes a
  WHERE a.entity_id = v_protagonist_id
    AND a.key = 'credits'
    AND a.end_cycle IS NULL;
  
  IF v_current_balance IS NULL THEN
    v_current_balance := 1400;
  END IF;
  
  v_new_balance := v_current_balance + p_amount;
  
  IF v_new_balance < 0 THEN
    RETURN QUERY SELECT 
      false, 
      v_current_balance, 
      format('Insufficient funds: %s + (%s) = %s', v_current_balance, p_amount, v_new_balance)::TEXT;
    RETURN;
  END IF;
  
  PERFORM set_attribute(
    p_game_id,
    v_protagonist_id,
    'credits',
    v_new_balance::TEXT,
    p_cycle,
    jsonb_build_object('description', p_description, 'amount', p_amount)
  );
  
  RETURN QUERY SELECT true, v_new_balance, NULL::TEXT;
END;
$func$;

CREATE OR REPLACE FUNCTION update_gauge(
  p_game_id UUID,
  p_attribute VARCHAR(100),
  p_delta NUMERIC,
  p_cycle INTEGER
)
RETURNS TABLE(success BOOLEAN, old_value NUMERIC, new_value NUMERIC)
LANGUAGE plpgsql
AS $func$
DECLARE
  v_protagonist_id UUID;
  v_current_value NUMERIC;
  v_new_value NUMERIC;
BEGIN
  IF p_attribute NOT IN ('energy', 'morale', 'health') THEN
    RETURN QUERY SELECT false, 0::NUMERIC, 0::NUMERIC;
    RETURN;
  END IF;
  
  SELECT e.id INTO v_protagonist_id
  FROM entities e
  WHERE e.game_id = p_game_id
    AND e.type = 'protagonist'
    AND e.removed_cycle IS NULL;
  
  IF v_protagonist_id IS NULL THEN
    RETURN QUERY SELECT false, 0::NUMERIC, 0::NUMERIC;
    RETURN;
  END IF;
  
  SELECT COALESCE(a.value::NUMERIC, 3) INTO v_current_value
  FROM attributes a
  WHERE a.entity_id = v_protagonist_id
    AND a.key = p_attribute
    AND a.end_cycle IS NULL;
  
  IF v_current_value IS NULL THEN
    v_current_value := 3;
  END IF;
  
  v_new_value := v_current_value + p_delta;
  v_new_value := ROUND(v_new_value * 2) / 2;
  v_new_value := GREATEST(0, LEAST(5, v_new_value));
  
  IF v_new_value != v_current_value THEN
    PERFORM set_attribute(
      p_game_id,
      v_protagonist_id,
      p_attribute,
      v_new_value::TEXT,
      p_cycle
    );
  END IF;
  
  RETURN QUERY SELECT true, v_current_value, v_new_value;
END;
$func$;

CREATE OR REPLACE FUNCTION rollback_to_cycle(
  p_game_id UUID,
  p_target_cycle INTEGER
)
RETURNS TABLE(
  deleted_facts INTEGER,
  deleted_events INTEGER,
  deleted_commitments INTEGER,
  reverted_attributes INTEGER,
  reverted_relations INTEGER
)
LANGUAGE plpgsql
AS $func$
DECLARE
  v_deleted_facts INTEGER;
  v_deleted_events INTEGER;
  v_deleted_commitments INTEGER;
  v_reverted_attributes INTEGER;
  v_reverted_relations INTEGER;
BEGIN
  DELETE FROM facts WHERE game_id = p_game_id AND cycle > p_target_cycle;
  GET DIAGNOSTICS v_deleted_facts = ROW_COUNT;
  
  DELETE FROM events WHERE game_id = p_game_id AND planned_cycle > p_target_cycle;
  GET DIAGNOSTICS v_deleted_events = ROW_COUNT;
  
  DELETE FROM commitments WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  GET DIAGNOSTICS v_deleted_commitments = ROW_COUNT;
  
  DELETE FROM attributes WHERE game_id = p_game_id AND start_cycle > p_target_cycle;
  GET DIAGNOSTICS v_reverted_attributes = ROW_COUNT;
  
  UPDATE attributes SET end_cycle = NULL 
  WHERE game_id = p_game_id AND end_cycle > p_target_cycle;
  
  DELETE FROM relations WHERE game_id = p_game_id AND start_cycle > p_target_cycle;
  GET DIAGNOSTICS v_reverted_relations = ROW_COUNT;
  
  UPDATE relations SET end_cycle = NULL, end_reason = NULL
  WHERE game_id = p_game_id AND end_cycle > p_target_cycle;
  
  DELETE FROM beliefs WHERE game_id = p_game_id AND acquisition_cycle > p_target_cycle;
  
  DELETE FROM skills WHERE game_id = p_game_id AND start_cycle > p_target_cycle;
  UPDATE skills SET end_cycle = NULL WHERE game_id = p_game_id AND end_cycle > p_target_cycle;
  
  DELETE FROM contradictions WHERE game_id = p_game_id AND detection_cycle > p_target_cycle;
  
  DELETE FROM chat_messages WHERE game_id = p_game_id AND cycle > p_target_cycle;
  
  DELETE FROM cycle_summaries WHERE game_id = p_game_id AND cycle > p_target_cycle;
  
  DELETE FROM extraction_logs WHERE game_id = p_game_id AND cycle > p_target_cycle;
  
  UPDATE games SET updated_at = NOW() WHERE id = p_game_id;
  
  RETURN QUERY SELECT 
    v_deleted_facts, 
    v_deleted_events, 
    v_deleted_commitments,
    v_reverted_attributes,
    v_reverted_relations;
END;
$func$;

-- ============================================================================
-- VIEWS
-- ============================================================================

CREATE OR REPLACE VIEW v_active_entities AS
SELECT * FROM entities WHERE removed_cycle IS NULL;

CREATE OR REPLACE VIEW v_active_relations AS
SELECT 
  r.game_id,
  r.id AS relation_id,
  r.source_id,
  e_source.type AS source_type,
  e_source.name AS source_name,
  r.type AS relation_type,
  r.target_id,
  e_target.type AS target_type,
  e_target.name AS target_name,
  r.start_cycle,
  r.certainty,
  r.is_true,
  rs.level,
  rs.context,
  rs.romantic_stage,
  rs.family_bond,
  rp.position,
  rp.position_start_cycle,
  rp.part_time,
  rsp.regularity,
  rsp.time_of_day,
  ro.quantity,
  ro.origin,
  ro.amount,
  ro.acquisition_cycle
FROM relations r
JOIN entities e_source ON r.source_id = e_source.id
JOIN entities e_target ON r.target_id = e_target.id
LEFT JOIN relations_social rs ON r.id = rs.relation_id
LEFT JOIN relations_professional rp ON r.id = rp.relation_id
LEFT JOIN relations_spatial rsp ON r.id = rsp.relation_id
LEFT JOIN relations_ownership ro ON r.id = ro.relation_id
WHERE r.end_cycle IS NULL
  AND e_source.removed_cycle IS NULL
  AND e_target.removed_cycle IS NULL;

CREATE OR REPLACE VIEW v_current_attributes AS
SELECT 
  a.game_id,
  a.entity_id,
  e.type AS entity_type,
  e.name AS entity_name,
  a.key,
  a.value,
  a.details,
  a.start_cycle
FROM attributes a
JOIN entities e ON a.entity_id = e.id
WHERE a.end_cycle IS NULL
  AND e.removed_cycle IS NULL;

CREATE OR REPLACE VIEW v_current_skills AS
SELECT 
  s.game_id,
  s.entity_id,
  e.name AS entity_name,
  s.name AS skill_name,
  s.level,
  s.start_cycle
FROM skills s
JOIN entities e ON s.entity_id = e.id
WHERE s.end_cycle IS NULL
  AND e.removed_cycle IS NULL;

CREATE OR REPLACE VIEW v_beliefs AS
SELECT 
  b.game_id,
  b.subject_id,
  e.name AS subject_name,
  e.type AS subject_type,
  b.key,
  b.content,
  b.is_true,
  b.certainty,
  b.acquisition_cycle
FROM beliefs b
JOIN entities e ON b.subject_id = e.id
WHERE e.removed_cycle IS NULL;

CREATE OR REPLACE VIEW v_upcoming_events AS
SELECT 
  ev.id,
  ev.game_id,
  ev.type,
  ev.category,
  ev.title,
  ev.description,
  ev.planned_cycle,
  ev.moment,
  ev.recurrence,
  ev.amount,
  l.name AS location_name,
  array_agg(DISTINCT ent.name) FILTER (WHERE ent.name IS NOT NULL) AS participants
FROM events ev
LEFT JOIN entities l ON ev.location_id = l.id
LEFT JOIN event_participants ep ON ev.id = ep.event_id
LEFT JOIN entities ent ON ep.entity_id = ent.id
WHERE ev.completed = false
  AND ev.cancelled = false
GROUP BY ev.id, l.name;

CREATE OR REPLACE VIEW v_inventory AS
SELECT 
  r.game_id,
  e_obj.id AS object_id,
  e_obj.name AS object_name,
  eo.category,
  eo.base_value,
  ro.quantity,
  ro.origin,
  ro.amount AS purchase_price,
  a_state.value AS state,
  a_loc.value AS location,
  r.start_cycle AS owned_since
FROM relations r
JOIN entities e_proto ON r.source_id = e_proto.id 
  AND e_proto.type = 'protagonist'
JOIN entities e_obj ON r.target_id = e_obj.id 
  AND e_obj.type = 'object'
JOIN relations_ownership ro ON r.id = ro.relation_id
LEFT JOIN entity_objects eo ON eo.entity_id = e_obj.id
LEFT JOIN attributes a_state ON a_state.entity_id = e_obj.id 
  AND a_state.key = 'state' AND a_state.end_cycle IS NULL
LEFT JOIN attributes a_loc ON a_loc.entity_id = e_obj.id 
  AND a_loc.key = 'location' AND a_loc.end_cycle IS NULL
WHERE r.type = 'owns'
  AND r.end_cycle IS NULL
  AND e_obj.removed_cycle IS NULL;

CREATE OR REPLACE VIEW v_characters_context AS
SELECT 
  e.game_id,
  e.id AS entity_id,
  e.name,
  e.aliases,
  ec.species,
  ec.gender,
  ec.pronouns,
  ec.station_arrival_cycle,
  ec.origin_location,
  ec.physical_description,
  ec.traits,
  a_pos.value AS current_position,
  a_status.value AS employment_status,
  a_mood.value AS mood,
  rs.level AS relation_level,
  rs.context AS relation_context,
  rs.romantic_stage
FROM entities e
JOIN entity_characters ec ON ec.entity_id = e.id
LEFT JOIN attributes a_pos ON a_pos.entity_id = e.id 
  AND a_pos.key = 'position' AND a_pos.end_cycle IS NULL
LEFT JOIN attributes a_status ON a_status.entity_id = e.id 
  AND a_status.key = 'employment_status' AND a_status.end_cycle IS NULL
LEFT JOIN attributes a_mood ON a_mood.entity_id = e.id 
  AND a_mood.key = 'mood' AND a_mood.end_cycle IS NULL
LEFT JOIN relations r_knows ON r_knows.target_id = e.id 
  AND r_knows.type = 'knows' AND r_knows.end_cycle IS NULL
  AND r_knows.source_id IN (
    SELECT id FROM entities WHERE type = 'protagonist' AND game_id = e.game_id
  )
LEFT JOIN relations_social rs ON rs.relation_id = r_knows.id
WHERE e.removed_cycle IS NULL
  AND e.type = 'character';

CREATE OR REPLACE VIEW v_active_commitments AS
SELECT 
  c.id,
  c.game_id,
  c.type,
  c.description,
  c.created_cycle,
  c.deadline_cycle,
  ca.objective,
  ca.obstacle,
  ca.progress,
  array_agg(
    jsonb_build_object('name', e.name, 'role', ce.role)
  ) FILTER (WHERE e.name IS NOT NULL) AS entities
FROM commitments c
LEFT JOIN commitment_arcs ca ON ca.commitment_id = c.id
LEFT JOIN commitment_entities ce ON ce.commitment_id = c.id
LEFT JOIN entities e ON ce.entity_id = e.id
WHERE c.resolved = false
GROUP BY c.id, ca.objective, ca.obstacle, ca.progress;

CREATE OR REPLACE VIEW v_recent_facts AS
SELECT 
  f.id,
  f.game_id,
  f.cycle,
  f.moment,
  f.type,
  f.domain,
  f.description,
  f.importance,
  l.name AS location_name,
  array_agg(
    jsonb_build_object('name', e.name, 'role', fp.role)
  ) FILTER (WHERE e.name IS NOT NULL) AS participants
FROM facts f
LEFT JOIN entities l ON f.location_id = l.id
LEFT JOIN fact_participants fp ON fp.fact_id = f.id
LEFT JOIN entities e ON fp.entity_id = e.id
GROUP BY f.id, l.name;

CREATE OR REPLACE VIEW v_open_contradictions AS
SELECT 
  c.id,
  c.game_id,
  c.detection_cycle,
  c.type,
  e.name AS entity_name,
  c.field_name,
  c.existing_value,
  c.new_value,
  c.existing_source,
  c.new_source
FROM contradictions c
LEFT JOIN entities e ON c.entity_id = e.id
WHERE c.resolved = false;

-- ============================================================================
-- GRANTS: SERVICE_ROLE ACCESS
-- ============================================================================

GRANT ALL ON games TO postgres;
GRANT ALL ON entities TO postgres;
GRANT ALL ON entity_protagonists TO postgres;
GRANT ALL ON entity_characters TO postgres;
GRANT ALL ON entity_locations TO postgres;
GRANT ALL ON entity_objects TO postgres;
GRANT ALL ON entity_ais TO postgres;
GRANT ALL ON entity_organizations TO postgres;
GRANT ALL ON skills TO postgres;
GRANT ALL ON attributes TO postgres;
GRANT ALL ON relations TO postgres;
GRANT ALL ON relations_social TO postgres;
GRANT ALL ON relations_professional TO postgres;
GRANT ALL ON relations_spatial TO postgres;
GRANT ALL ON relations_ownership TO postgres;
GRANT ALL ON facts TO postgres;
GRANT ALL ON fact_participants TO postgres;
GRANT ALL ON beliefs TO postgres;
GRANT ALL ON contradictions TO postgres;
GRANT ALL ON events TO postgres;
GRANT ALL ON event_participants TO postgres;
GRANT ALL ON commitments TO postgres;
GRANT ALL ON commitment_arcs TO postgres;
GRANT ALL ON commitment_entities TO postgres;
GRANT ALL ON chat_messages TO postgres;
GRANT ALL ON cycle_summaries TO postgres;
GRANT ALL ON extraction_logs TO postgres;

GRANT SELECT ON v_active_entities TO postgres;
GRANT SELECT ON v_active_relations TO postgres;
GRANT SELECT ON v_current_attributes TO postgres;
GRANT SELECT ON v_current_skills TO postgres;
GRANT SELECT ON v_beliefs TO postgres;
GRANT SELECT ON v_upcoming_events TO postgres;
GRANT SELECT ON v_inventory TO postgres;
GRANT SELECT ON v_characters_context TO postgres;
GRANT SELECT ON v_active_commitments TO postgres;
GRANT SELECT ON v_recent_facts TO postgres;
GRANT SELECT ON v_open_contradictions TO postgres;

GRANT EXECUTE ON FUNCTION find_entity(UUID, TEXT, entity_type) TO postgres;
GRANT EXECUTE ON FUNCTION upsert_entity(UUID, entity_type, VARCHAR, TEXT[], INTEGER, BOOLEAN) TO postgres;
GRANT EXECUTE ON FUNCTION set_attribute(UUID, UUID, VARCHAR, TEXT, INTEGER, JSONB) TO postgres;
GRANT EXECUTE ON FUNCTION upsert_relation(UUID, UUID, UUID, relation_type, INTEGER, certainty_level, BOOLEAN, VARCHAR) TO postgres;
GRANT EXECUTE ON FUNCTION end_relation(UUID, TEXT, TEXT, relation_type, INTEGER, TEXT) TO postgres;
GRANT EXECUTE ON FUNCTION create_fact(UUID, INTEGER, fact_type, TEXT, fact_domain, UUID, VARCHAR, INTEGER, JSONB) TO postgres;
GRANT EXECUTE ON FUNCTION set_belief(UUID, UUID, VARCHAR, TEXT, INTEGER, BOOLEAN, certainty_level, UUID) TO postgres;
GRANT EXECUTE ON FUNCTION set_skill(UUID, UUID, VARCHAR, INTEGER, INTEGER) TO postgres;
GRANT EXECUTE ON FUNCTION credit_transaction(UUID, INTEGER, INTEGER, TEXT) TO postgres;
GRANT EXECUTE ON FUNCTION update_gauge(UUID, VARCHAR, NUMERIC, INTEGER) TO postgres;
GRANT EXECUTE ON FUNCTION rollback_to_cycle(UUID, INTEGER) TO postgres;

GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO postgres;
