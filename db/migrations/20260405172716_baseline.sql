-- migrate:up

-- ============================================================================
-- LDVELH - Baseline schema
-- Full schema as of 2026-04-05 (parallel extractors complete)
-- ============================================================================

-- ENUMS
CREATE TYPE relation_type AS ENUM (
  'knows', 'friend_of', 'enemy_of', 'family_of', 'romantic',
  'employed_by', 'colleague_of', 'manages',
  'frequents', 'lives_at', 'located_in', 'works_at',
  'owns', 'owes_to'
);

-- AUTH
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(100) UNIQUE,
  preferences JSONB DEFAULT '{}',
  email_verified BOOLEAN DEFAULT false,
  email_verification_token VARCHAR(64),
  email_verification_sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- GAMES
CREATE TABLE games (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  name VARCHAR(255) DEFAULT 'Nouvelle partie',
  current_cycle INTEGER DEFAULT 0,
  "current_date" VARCHAR(50),
  "current_time" VARCHAR(5),
  current_location_id UUID,
  world_name VARCHAR(255),
  world_description TEXT,
  world_atmosphere VARCHAR(255),
  world_seed_words TEXT[],
  world_founding_cycle INTEGER,
  extracted_up_to_cycle INTEGER DEFAULT 0,
  extraction_checkpoints JSONB DEFAULT '{}',
  last_extraction_time VARCHAR(5),
  detail_requests TEXT[] DEFAULT '{}',
  active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_games_user ON games(user_id);
CREATE INDEX idx_games_active ON games(user_id) WHERE active = true;

-- PROTAGONISTS
CREATE TABLE protagonists (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID UNIQUE NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  name VARCHAR(100) NOT NULL,
  energy NUMERIC(3,1) DEFAULT 4.0,
  morale NUMERIC(3,1) DEFAULT 3.0,
  health NUMERIC(3,1) DEFAULT 5.0,
  credits INTEGER DEFAULT 1400,
  occupation VARCHAR(255),
  employer_id UUID,
  residence_id UUID,
  origin VARCHAR(255),
  departure_reason VARCHAR(50),
  backstory TEXT,
  hobbies TEXT[],
  description TEXT,
  details JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- PERSONAL ASSISTANTS
CREATE TABLE personal_assistants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID UNIQUE NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  name VARCHAR(100) NOT NULL,
  voice VARCHAR(255),
  traits TEXT[],
  quirk TEXT,
  substrate VARCHAR(100) DEFAULT 'terminal personnel',
  details JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- LOCATIONS
CREATE TABLE locations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  parent_id UUID REFERENCES locations(id),
  location_type VARCHAR(100),
  sector VARCHAR(255),
  description TEXT,
  atmosphere VARCHAR(255),
  accessible BOOLEAN DEFAULT true,
  notable_features TEXT[],
  typical_crowd VARCHAR(255),
  operating_hours VARCHAR(50),
  price_range VARCHAR(50),
  ambient TEXT,
  details JSONB DEFAULT '{}',
  created_cycle INTEGER DEFAULT 1,
  removed_cycle INTEGER,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_id, name)
);

CREATE INDEX idx_locations_game ON locations(game_id);
CREATE INDEX idx_locations_active ON locations(game_id) WHERE removed_cycle IS NULL;
CREATE INDEX idx_locations_parent ON locations(parent_id);

ALTER TABLE games ADD CONSTRAINT fk_games_current_location
  FOREIGN KEY (current_location_id) REFERENCES locations(id);
ALTER TABLE protagonists ADD CONSTRAINT fk_protagonists_residence
  FOREIGN KEY (residence_id) REFERENCES locations(id);

-- ORGANIZATIONS
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  org_type VARCHAR(100),
  domain VARCHAR(255),
  size VARCHAR(50),
  description TEXT,
  reputation VARCHAR(255),
  headquarters_id UUID REFERENCES locations(id),
  founding_cycle INTEGER,
  ambient TEXT,
  details JSONB DEFAULT '{}',
  created_cycle INTEGER DEFAULT 1,
  removed_cycle INTEGER,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_id, name)
);

CREATE INDEX idx_organizations_game ON organizations(game_id);
CREATE INDEX idx_organizations_active ON organizations(game_id) WHERE removed_cycle IS NULL;

ALTER TABLE protagonists ADD CONSTRAINT fk_protagonists_employer
  FOREIGN KEY (employer_id) REFERENCES organizations(id);

-- CHARACTERS
CREATE TABLE characters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  known_by_protagonist BOOLEAN DEFAULT false,
  unknown_name VARCHAR(255),
  species VARCHAR(100),
  gender VARCHAR(50),
  pronouns VARCHAR(30),
  age VARCHAR(30),
  description TEXT,
  traits TEXT[],
  mood VARCHAR(255),
  occupation VARCHAR(255),
  origin VARCHAR(255),
  workplace_id UUID REFERENCES locations(id),
  residence_id UUID REFERENCES locations(id),
  romantic_potential BOOLEAN DEFAULT false,
  is_mandatory BOOLEAN DEFAULT false,
  ambient TEXT,
  details JSONB DEFAULT '{}',
  created_cycle INTEGER DEFAULT 1,
  removed_cycle INTEGER,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_id, name)
);

CREATE INDEX idx_characters_game ON characters(game_id);
CREATE INDEX idx_characters_active ON characters(game_id) WHERE removed_cycle IS NULL;
CREATE INDEX idx_characters_known ON characters(game_id)
  WHERE known_by_protagonist = true AND removed_cycle IS NULL;

-- OBJECTS
CREATE TABLE objects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  canonical_name VARCHAR(100),
  category VARCHAR(100),
  description TEXT,
  transportable BOOLEAN DEFAULT true,
  stackable BOOLEAN DEFAULT false,
  base_value INTEGER,
  details JSONB DEFAULT '{}',
  created_cycle INTEGER DEFAULT 1,
  removed_cycle INTEGER,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_id, name)
);

CREATE INDEX idx_objects_game ON objects(game_id);
CREATE INDEX idx_objects_active ON objects(game_id) WHERE removed_cycle IS NULL;
CREATE UNIQUE INDEX idx_objects_canonical ON objects(game_id, canonical_name)
  WHERE canonical_name IS NOT NULL AND removed_cycle IS NULL;

-- SKILLS
CREATE TABLE skills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  protagonist_id UUID REFERENCES protagonists(id),
  character_id UUID REFERENCES characters(id),
  name VARCHAR(100) NOT NULL,
  level INTEGER CHECK (level BETWEEN 1 AND 5),
  start_cycle INTEGER DEFAULT 1,
  end_cycle INTEGER,
  created_at TIMESTAMPTZ DEFAULT now(),
  CHECK (
    (protagonist_id IS NOT NULL AND character_id IS NULL) OR
    (protagonist_id IS NULL AND character_id IS NOT NULL)
  )
);

CREATE INDEX idx_skills_protagonist ON skills(protagonist_id) WHERE end_cycle IS NULL;
CREATE INDEX idx_skills_character ON skills(character_id) WHERE end_cycle IS NULL;

-- ENTITY REGISTRY
CREATE TABLE entity_registry (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  entity_type VARCHAR(50) NOT NULL,
  name VARCHAR(255) NOT NULL,
  UNIQUE(game_id, entity_type, name)
);

CREATE INDEX idx_entity_registry_game ON entity_registry(game_id);
CREATE INDEX idx_entity_registry_name ON entity_registry(game_id, name);

-- Trigger: auto-register entities
CREATE OR REPLACE FUNCTION register_entity()
RETURNS TRIGGER LANGUAGE plpgsql AS $func$
BEGIN
  INSERT INTO entity_registry (game_id, entity_type, name)
  VALUES (NEW.game_id, TG_ARGV[0], NEW.name)
  ON CONFLICT (game_id, entity_type, name) DO NOTHING;
  RETURN NEW;
END;
$func$;

CREATE TRIGGER register_protagonist AFTER INSERT ON protagonists
  FOR EACH ROW EXECUTE FUNCTION register_entity('protagonist');
CREATE TRIGGER register_character AFTER INSERT ON characters
  FOR EACH ROW EXECUTE FUNCTION register_entity('character');
CREATE TRIGGER register_location AFTER INSERT ON locations
  FOR EACH ROW EXECUTE FUNCTION register_entity('location');
CREATE TRIGGER register_organization AFTER INSERT ON organizations
  FOR EACH ROW EXECUTE FUNCTION register_entity('organization');
CREATE TRIGGER register_object AFTER INSERT ON objects
  FOR EACH ROW EXECUTE FUNCTION register_entity('object');

-- Trigger: sync entity name on rename
CREATE OR REPLACE FUNCTION update_entity_registry_name()
RETURNS TRIGGER LANGUAGE plpgsql AS $func$
BEGIN
  IF OLD.name != NEW.name THEN
    UPDATE entity_registry
    SET name = NEW.name
    WHERE game_id = NEW.game_id AND entity_type = TG_ARGV[0] AND name = OLD.name;
  END IF;
  RETURN NEW;
END;
$func$;

CREATE TRIGGER update_registry_character AFTER UPDATE OF name ON characters
  FOR EACH ROW EXECUTE FUNCTION update_entity_registry_name('character');
CREATE TRIGGER update_registry_location AFTER UPDATE OF name ON locations
  FOR EACH ROW EXECUTE FUNCTION update_entity_registry_name('location');
CREATE TRIGGER update_registry_organization AFTER UPDATE OF name ON organizations
  FOR EACH ROW EXECUTE FUNCTION update_entity_registry_name('organization');
CREATE TRIGGER update_registry_object AFTER UPDATE OF name ON objects
  FOR EACH ROW EXECUTE FUNCTION update_entity_registry_name('object');

-- RELATIONS
CREATE TABLE relations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  type relation_type NOT NULL,
  source_id UUID NOT NULL REFERENCES entity_registry(id),
  target_id UUID NOT NULL REFERENCES entity_registry(id),
  level INTEGER,
  context TEXT,
  known_by_protagonist BOOLEAN DEFAULT true,
  start_cycle INTEGER DEFAULT 1,
  end_cycle INTEGER,
  end_reason TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_relations_game ON relations(game_id);
CREATE INDEX idx_relations_source ON relations(source_id);
CREATE INDEX idx_relations_target ON relations(target_id);
CREATE INDEX idx_relations_type ON relations(game_id, type);
CREATE INDEX idx_relations_active ON relations(game_id) WHERE end_cycle IS NULL;
CREATE INDEX idx_relations_known ON relations(game_id)
  WHERE known_by_protagonist = true AND end_cycle IS NULL;

-- NARRATIVE ARCS
CREATE TABLE narrative_arcs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  title VARCHAR(255) NOT NULL,
  domain VARCHAR(50),
  description TEXT,
  intensity INTEGER DEFAULT 3 CHECK (intensity BETWEEN 1 AND 5),
  progress INTEGER DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  situation TEXT,
  desire TEXT,
  obstacle TEXT,
  potential_triggers TEXT[],
  stakes TEXT,
  deadline_cycle INTEGER,
  resolved BOOLEAN DEFAULT false,
  resolved_cycle INTEGER,
  resolution TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_arcs_game ON narrative_arcs(game_id);
CREATE INDEX idx_arcs_active ON narrative_arcs(game_id) WHERE resolved = false;
CREATE INDEX idx_arcs_deadline ON narrative_arcs(game_id, deadline_cycle)
  WHERE resolved = false AND deadline_cycle IS NOT NULL;

CREATE TABLE arc_participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  arc_id UUID NOT NULL REFERENCES narrative_arcs(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entity_registry(id),
  role VARCHAR(50),
  UNIQUE(arc_id, entity_id)
);

CREATE INDEX idx_arc_participants_entity ON arc_participants(entity_id);

-- FACTS (immutable)
CREATE TABLE facts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  cycle INTEGER NOT NULL,
  time VARCHAR(5),
  type VARCHAR(50) NOT NULL,
  description TEXT NOT NULL,
  location_id UUID REFERENCES locations(id),
  importance INTEGER DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
  semantic_key VARCHAR(100),
  UNIQUE(game_id, cycle, semantic_key),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_facts_game ON facts(game_id);
CREATE INDEX idx_facts_cycle ON facts(game_id, cycle);
CREATE INDEX idx_facts_type ON facts(game_id, type);
CREATE INDEX idx_facts_location ON facts(location_id);

CREATE OR REPLACE FUNCTION facts_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $func$
BEGIN
  RAISE EXCEPTION 'Les faits sont immutables';
END;
$func$;

CREATE TRIGGER facts_no_update BEFORE UPDATE ON facts
  FOR EACH ROW EXECUTE FUNCTION facts_immutable();

CREATE TABLE fact_participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entity_registry(id),
  role VARCHAR(50),
  UNIQUE(fact_id, entity_id)
);

CREATE INDEX idx_fact_participants_fact ON fact_participants(fact_id);
CREATE INDEX idx_fact_participants_entity ON fact_participants(entity_id);

-- CHRONOLOGY
CREATE TABLE chronology (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  cycle INTEGER NOT NULL,
  time VARCHAR(5),
  location_id UUID REFERENCES locations(id),
  summary TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_chronology_game ON chronology(game_id, cycle);

CREATE TABLE chronology_participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chronology_id UUID NOT NULL REFERENCES chronology(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entity_registry(id),
  UNIQUE(chronology_id, entity_id)
);

CREATE INDEX idx_chronology_participants ON chronology_participants(entity_id);

-- EVENTS
CREATE TABLE events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  type VARCHAR(50) NOT NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT,
  planned_cycle INTEGER,
  time VARCHAR(5),
  location_id UUID REFERENCES locations(id),
  completed BOOLEAN DEFAULT false,
  cancelled BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_events_game ON events(game_id);
CREATE INDEX idx_events_active ON events(game_id, planned_cycle)
  WHERE completed = false AND cancelled = false;

CREATE TABLE event_participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entity_registry(id),
  UNIQUE(event_id, entity_id)
);

CREATE INDEX idx_event_participants_entity ON event_participants(entity_id);

-- CONVERSATIONS & MESSAGES
CREATE TABLE conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  start_cycle INTEGER NOT NULL,
  end_cycle INTEGER,
  compacted BOOLEAN DEFAULT false,
  compacted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_conversations_game ON conversations(game_id);
CREATE INDEX idx_conversations_active ON conversations(game_id)
  WHERE compacted = false;

CREATE TABLE messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role VARCHAR(20) NOT NULL,
  content TEXT NOT NULL,
  cycle INTEGER,
  "game_date" VARCHAR(50),
  time VARCHAR(5),
  location_id UUID REFERENCES locations(id),
  extracted BOOLEAN DEFAULT false,
  chronology_id UUID REFERENCES chronology(id),
  narrator_deltas JSONB,
  sequence INTEGER NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id, sequence);
CREATE INDEX idx_messages_game_cycle ON messages(game_id, cycle);
CREATE INDEX idx_messages_unextracted ON messages(game_id)
  WHERE extracted = false;

-- INVENTORY
CREATE TABLE inventory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  object_id UUID NOT NULL REFERENCES objects(id),
  owner_id UUID REFERENCES entity_registry(id),
  quantity INTEGER DEFAULT 1,
  acquired_cycle INTEGER,
  origin VARCHAR(50),
  UNIQUE(game_id, object_id, owner_id)
);

CREATE INDEX idx_inventory_game ON inventory(game_id);
CREATE INDEX idx_inventory_owner ON inventory(owner_id);

-- EXTRACTION LOGS
CREATE TABLE extraction_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  conversation_id UUID REFERENCES conversations(id),
  cycle INTEGER,
  type VARCHAR(50),
  duration_ms INTEGER,
  messages_processed INTEGER,
  facts_created INTEGER DEFAULT 0,
  entities_modified INTEGER DEFAULT 0,
  errors JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_extraction_logs_game ON extraction_logs(game_id, cycle);

-- UTILITY FUNCTIONS
CREATE OR REPLACE FUNCTION find_entity(
  p_game_id UUID,
  p_name TEXT,
  p_type VARCHAR(50) DEFAULT NULL
)
RETURNS UUID LANGUAGE plpgsql AS $func$
DECLARE
  v_id UUID;
BEGIN
  SELECT id INTO v_id FROM entity_registry
  WHERE game_id = p_game_id
    AND (p_type IS NULL OR entity_type = p_type)
    AND LOWER(name) = LOWER(TRIM(p_name))
  LIMIT 1;
  RETURN v_id;
END;
$func$;

CREATE OR REPLACE FUNCTION upsert_relation(
  p_game_id UUID,
  p_source_id UUID,
  p_target_id UUID,
  p_type relation_type,
  p_cycle INTEGER DEFAULT 1,
  p_level INTEGER DEFAULT NULL,
  p_context TEXT DEFAULT NULL,
  p_known_by_protagonist BOOLEAN DEFAULT true
)
RETURNS UUID LANGUAGE plpgsql AS $func$
DECLARE
  v_id UUID;
BEGIN
  SELECT id INTO v_id FROM relations
  WHERE game_id = p_game_id
    AND source_id = p_source_id
    AND target_id = p_target_id
    AND type = p_type
    AND end_cycle IS NULL;

  IF v_id IS NOT NULL THEN
    UPDATE relations SET
      level = COALESCE(p_level, level),
      context = COALESCE(p_context, context),
      known_by_protagonist = p_known_by_protagonist
    WHERE id = v_id;
    RETURN v_id;
  ELSE
    INSERT INTO relations (game_id, source_id, target_id, type, start_cycle, level, context, known_by_protagonist)
    VALUES (p_game_id, p_source_id, p_target_id, p_type, p_cycle, p_level, p_context, p_known_by_protagonist)
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
RETURNS BOOLEAN LANGUAGE plpgsql AS $func$
DECLARE
  v_source_id UUID;
  v_target_id UUID;
BEGIN
  v_source_id := find_entity(p_game_id, p_source_name);
  v_target_id := find_entity(p_game_id, p_target_name);
  IF v_source_id IS NULL OR v_target_id IS NULL THEN RETURN false; END IF;

  UPDATE relations SET end_cycle = p_cycle, end_reason = p_reason
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
  p_type VARCHAR(50),
  p_description TEXT,
  p_location_id UUID DEFAULT NULL,
  p_time VARCHAR(5) DEFAULT NULL,
  p_importance INTEGER DEFAULT 3,
  p_participants JSONB DEFAULT '[]',
  p_semantic_key VARCHAR(100) DEFAULT NULL
)
RETURNS UUID LANGUAGE plpgsql AS $func$
DECLARE
  v_fact_id UUID;
  v_participant JSONB;
  v_entity_id UUID;
BEGIN
  IF p_semantic_key IS NOT NULL THEN
    SELECT id INTO v_fact_id FROM facts
    WHERE game_id = p_game_id AND cycle = p_cycle AND semantic_key = p_semantic_key;
    IF v_fact_id IS NOT NULL THEN RETURN v_fact_id; END IF;
  END IF;

  INSERT INTO facts (game_id, cycle, type, description, location_id, time, importance, semantic_key)
  VALUES (p_game_id, p_cycle, p_type, p_description, p_location_id, p_time, p_importance, p_semantic_key)
  RETURNING id INTO v_fact_id;

  FOR v_participant IN SELECT * FROM jsonb_array_elements(p_participants)
  LOOP
    v_entity_id := find_entity(p_game_id, v_participant->>'name');
    IF v_entity_id IS NOT NULL THEN
      INSERT INTO fact_participants (fact_id, entity_id, role)
      VALUES (v_fact_id, v_entity_id, v_participant->>'role')
      ON CONFLICT (fact_id, entity_id) DO NOTHING;
    END IF;
  END LOOP;

  RETURN v_fact_id;
END;
$func$;

CREATE OR REPLACE FUNCTION credit_transaction(
  p_game_id UUID,
  p_amount INTEGER,
  p_cycle INTEGER,
  p_description TEXT DEFAULT NULL
)
RETURNS TABLE(success BOOLEAN, new_balance INTEGER, error TEXT) LANGUAGE plpgsql AS $func$
DECLARE
  v_current_balance INTEGER;
  v_new_balance INTEGER;
BEGIN
  SELECT credits INTO v_current_balance FROM protagonists
  WHERE game_id = p_game_id;

  IF v_current_balance IS NULL THEN
    RETURN QUERY SELECT false, 0, 'Protagoniste non trouvé'::TEXT;
    RETURN;
  END IF;

  v_new_balance := v_current_balance + p_amount;

  IF v_new_balance < 0 THEN
    RETURN QUERY SELECT false, v_current_balance,
      format('Fonds insuffisants : %s + (%s) = %s', v_current_balance, p_amount, v_new_balance)::TEXT;
    RETURN;
  END IF;

  UPDATE protagonists SET credits = v_new_balance, updated_at = now()
  WHERE game_id = p_game_id;

  RETURN QUERY SELECT true, v_new_balance, NULL::TEXT;
END;
$func$;

CREATE OR REPLACE FUNCTION update_gauge(
  p_game_id UUID,
  p_gauge VARCHAR(20),
  p_delta NUMERIC,
  p_cycle INTEGER
)
RETURNS TABLE(success BOOLEAN, old_value NUMERIC, new_value NUMERIC) LANGUAGE plpgsql AS $func$
DECLARE
  v_current NUMERIC;
  v_new NUMERIC;
BEGIN
  IF p_gauge NOT IN ('energy', 'morale', 'health') THEN
    RETURN QUERY SELECT false, 0::NUMERIC, 0::NUMERIC;
    RETURN;
  END IF;

  EXECUTE format('SELECT %I FROM protagonists WHERE game_id = $1', p_gauge)
    INTO v_current USING p_game_id;

  IF v_current IS NULL THEN
    RETURN QUERY SELECT false, 0::NUMERIC, 0::NUMERIC;
    RETURN;
  END IF;

  v_new := ROUND((v_current + p_delta) * 2) / 2;
  v_new := GREATEST(0, LEAST(5, v_new));

  IF v_new != v_current THEN
    EXECUTE format('UPDATE protagonists SET %I = $1, updated_at = now() WHERE game_id = $2', p_gauge)
      USING v_new, p_game_id;
  END IF;

  RETURN QUERY SELECT true, v_current, v_new;
END;
$func$;

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

-- VIEWS
CREATE OR REPLACE VIEW v_active_relations AS
SELECT
  r.id AS relation_id, r.game_id, r.type AS relation_type,
  r.source_id, es.entity_type AS source_type, es.name AS source_name,
  r.target_id, et.entity_type AS target_type, et.name AS target_name,
  r.level, r.context, r.known_by_protagonist, r.start_cycle
FROM relations r
JOIN entity_registry es ON r.source_id = es.id
JOIN entity_registry et ON r.target_id = et.id
WHERE r.end_cycle IS NULL;

CREATE OR REPLACE VIEW v_recent_facts AS
SELECT
  f.id, f.game_id, f.cycle, f.time, f.type, f.description,
  f.importance, f.semantic_key, l.name AS location_name,
  array_agg(jsonb_build_object('name', er.name, 'role', fp.role))
    FILTER (WHERE er.name IS NOT NULL) AS participants
FROM facts f
LEFT JOIN locations l ON f.location_id = l.id
LEFT JOIN fact_participants fp ON fp.fact_id = f.id
LEFT JOIN entity_registry er ON fp.entity_id = er.id
GROUP BY f.id, l.name;

CREATE OR REPLACE VIEW v_active_arcs AS
SELECT
  na.id, na.game_id, na.title, na.domain, na.description,
  na.intensity, na.progress, na.situation, na.desire, na.obstacle,
  na.stakes, na.deadline_cycle,
  array_agg(jsonb_build_object('name', er.name, 'type', er.entity_type, 'role', ap.role))
    FILTER (WHERE er.name IS NOT NULL) AS participants
FROM narrative_arcs na
LEFT JOIN arc_participants ap ON ap.arc_id = na.id
LEFT JOIN entity_registry er ON ap.entity_id = er.id
WHERE na.resolved = false
GROUP BY na.id;

CREATE OR REPLACE VIEW v_upcoming_events AS
SELECT
  ev.id, ev.game_id, ev.type, ev.title, ev.description,
  ev.planned_cycle, ev.time, l.name AS location_name,
  array_agg(er.name) FILTER (WHERE er.name IS NOT NULL) AS participants
FROM events ev
LEFT JOIN locations l ON ev.location_id = l.id
LEFT JOIN event_participants ep ON ev.id = ep.event_id
LEFT JOIN entity_registry er ON ep.entity_id = er.id
WHERE ev.completed = false AND ev.cancelled = false
GROUP BY ev.id, l.name;

CREATE OR REPLACE VIEW v_protagonist_inventory AS
SELECT
  i.game_id, o.id AS object_id, o.name AS object_name,
  o.category, o.base_value, o.description, i.quantity, i.origin, i.acquired_cycle
FROM inventory i
JOIN objects o ON i.object_id = o.id
WHERE i.owner_id IS NULL AND o.removed_cycle IS NULL;

CREATE OR REPLACE VIEW v_chronology AS
SELECT
  c.id, c.game_id, c.cycle, c.time, l.name AS location_name, c.summary,
  array_agg(er.name) FILTER (WHERE er.name IS NOT NULL) AS npcs_present
FROM chronology c
LEFT JOIN locations l ON c.location_id = l.id
LEFT JOIN chronology_participants cp ON cp.chronology_id = c.id
LEFT JOIN entity_registry er ON cp.entity_id = er.id
GROUP BY c.id, l.name;

-- GRANTS
GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO postgres;


-- migrate:down

DROP VIEW IF EXISTS v_chronology CASCADE;
DROP VIEW IF EXISTS v_protagonist_inventory CASCADE;
DROP VIEW IF EXISTS v_upcoming_events CASCADE;
DROP VIEW IF EXISTS v_active_arcs CASCADE;
DROP VIEW IF EXISTS v_recent_facts CASCADE;
DROP VIEW IF EXISTS v_active_relations CASCADE;

DROP FUNCTION IF EXISTS rollback_to_cycle CASCADE;
DROP FUNCTION IF EXISTS update_gauge CASCADE;
DROP FUNCTION IF EXISTS credit_transaction CASCADE;
DROP FUNCTION IF EXISTS create_fact CASCADE;
DROP FUNCTION IF EXISTS end_relation CASCADE;
DROP FUNCTION IF EXISTS upsert_relation CASCADE;
DROP FUNCTION IF EXISTS find_entity CASCADE;
DROP FUNCTION IF EXISTS facts_immutable CASCADE;
DROP FUNCTION IF EXISTS update_entity_registry_name CASCADE;
DROP FUNCTION IF EXISTS register_entity CASCADE;

DROP TABLE IF EXISTS extraction_logs CASCADE;
DROP TABLE IF EXISTS inventory CASCADE;
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS conversations CASCADE;
DROP TABLE IF EXISTS event_participants CASCADE;
DROP TABLE IF EXISTS events CASCADE;
DROP TABLE IF EXISTS chronology_participants CASCADE;
DROP TABLE IF EXISTS chronology CASCADE;
DROP TABLE IF EXISTS fact_participants CASCADE;
DROP TABLE IF EXISTS facts CASCADE;
DROP TABLE IF EXISTS arc_participants CASCADE;
DROP TABLE IF EXISTS narrative_arcs CASCADE;
DROP TABLE IF EXISTS relations CASCADE;
DROP TABLE IF EXISTS entity_registry CASCADE;
DROP TABLE IF EXISTS skills CASCADE;
DROP TABLE IF EXISTS objects CASCADE;
DROP TABLE IF EXISTS characters CASCADE;
DROP TABLE IF EXISTS organizations CASCADE;
DROP TABLE IF EXISTS locations CASCADE;
DROP TABLE IF EXISTS personal_assistants CASCADE;
DROP TABLE IF EXISTS protagonists CASCADE;
DROP TABLE IF EXISTS games CASCADE;
DROP TABLE IF EXISTS users CASCADE;

DROP TYPE IF EXISTS relation_type CASCADE;
