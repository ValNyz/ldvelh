--
-- PostgreSQL database dump
--

\restrict gVyNwITtOHthEWD96hwU6McnxPXh2SzuGy7LbsfjGYdd992rXZ1Wnr4g9B10p6t

-- Dumped from database version 16.11
-- Dumped by pg_dump version 16.11

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


--
-- Name: relation_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.relation_type AS ENUM (
    'knows',
    'friend_of',
    'enemy_of',
    'family_of',
    'romantic',
    'employed_by',
    'colleague_of',
    'manages',
    'frequents',
    'lives_at',
    'located_in',
    'works_at',
    'owns',
    'owes_to'
);


--
-- Name: create_fact(uuid, integer, character varying, text, uuid, character varying, integer, jsonb, character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.create_fact(p_game_id uuid, p_cycle integer, p_type character varying, p_description text, p_location_id uuid DEFAULT NULL::uuid, p_time character varying DEFAULT NULL::character varying, p_importance integer DEFAULT 3, p_participants jsonb DEFAULT '[]'::jsonb, p_semantic_key character varying DEFAULT NULL::character varying) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
DECLARE
  v_fact_id UUID;
  v_participant JSONB;
  v_entity_id UUID;
BEGIN
  -- Dédup par semantic_key
  IF p_semantic_key IS NOT NULL THEN
    SELECT id INTO v_fact_id FROM facts
    WHERE game_id = p_game_id AND cycle = p_cycle AND semantic_key = p_semantic_key;
    IF v_fact_id IS NOT NULL THEN RETURN v_fact_id; END IF;
  END IF;

  INSERT INTO facts (game_id, cycle, type, description, location_id, time, importance, semantic_key)
  VALUES (p_game_id, p_cycle, p_type, p_description, p_location_id, p_time, p_importance, p_semantic_key)
  RETURNING id INTO v_fact_id;

  -- Insérer les participants
  -- Format attendu : [{"name": "Valentin", "role": "actor"}, ...]
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
$$;


--
-- Name: credit_transaction(uuid, integer, integer, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.credit_transaction(p_game_id uuid, p_amount integer, p_cycle integer, p_description text DEFAULT NULL::text) RETURNS TABLE(success boolean, new_balance integer, error text)
    LANGUAGE plpgsql
    AS $$
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
$$;


--
-- Name: end_relation(uuid, text, text, public.relation_type, integer, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.end_relation(p_game_id uuid, p_source_name text, p_target_name text, p_type public.relation_type, p_cycle integer, p_reason text DEFAULT NULL::text) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
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
$$;


--
-- Name: facts_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.facts_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  RAISE EXCEPTION 'Les faits sont immutables';
END;
$$;


--
-- Name: find_entity(uuid, text, character varying); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.find_entity(p_game_id uuid, p_name text, p_type character varying DEFAULT NULL::character varying) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
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
$$;


--
-- Name: register_entity(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.register_entity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO entity_registry (game_id, entity_type, name)
  VALUES (NEW.game_id, TG_ARGV[0], NEW.name)
  ON CONFLICT (game_id, entity_type, name) DO NOTHING;
  RETURN NEW;
END;
$$;


--
-- Name: rollback_to_cycle(uuid, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.rollback_to_cycle(p_game_id uuid, p_target_cycle integer) RETURNS TABLE(deleted_facts integer, deleted_events integer, deleted_arcs integer, reverted_relations integer)
    LANGUAGE plpgsql
    AS $$
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
$$;


--
-- Name: update_entity_registry_name(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_entity_registry_name() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF OLD.name != NEW.name THEN
    UPDATE entity_registry
    SET name = NEW.name
    WHERE game_id = NEW.game_id AND entity_type = TG_ARGV[0] AND name = OLD.name;
  END IF;
  RETURN NEW;
END;
$$;


--
-- Name: update_gauge(uuid, character varying, numeric, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_gauge(p_game_id uuid, p_gauge character varying, p_delta numeric, p_cycle integer) RETURNS TABLE(success boolean, old_value numeric, new_value numeric)
    LANGUAGE plpgsql
    AS $_$
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
$_$;


--
-- Name: upsert_relation(uuid, uuid, uuid, public.relation_type, integer, integer, text, boolean); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.upsert_relation(p_game_id uuid, p_source_id uuid, p_target_id uuid, p_type public.relation_type, p_cycle integer DEFAULT 1, p_level integer DEFAULT NULL::integer, p_context text DEFAULT NULL::text, p_known_by_protagonist boolean DEFAULT true) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
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
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: arc_participants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.arc_participants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    arc_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    role character varying(50)
);


--
-- Name: character_d6; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.character_d6 (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    attributes jsonb DEFAULT '{}'::jsonb,
    wounds jsonb DEFAULT '{}'::jsonb,
    force_points integer DEFAULT 3,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: character_fate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.character_fate (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    aspects jsonb DEFAULT '[]'::jsonb,
    stunts jsonb DEFAULT '[]'::jsonb,
    stress_physical boolean[] DEFAULT '{f,f,f,f}'::boolean[],
    stress_mental boolean[] DEFAULT '{f,f,f,f}'::boolean[],
    consequences jsonb DEFAULT '{}'::jsonb,
    fate_points integer DEFAULT 3,
    refresh integer DEFAULT 3,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: character_narrative; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.character_narrative (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: characters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.characters (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    known_by_protagonist boolean DEFAULT false,
    unknown_name character varying(255),
    species character varying(100),
    gender character varying(50),
    pronouns character varying(30),
    age character varying(30),
    description text,
    traits text[],
    mood character varying(255),
    occupation character varying(255),
    origin character varying(255),
    workplace_id uuid,
    residence_id uuid,
    romantic_potential boolean DEFAULT false,
    is_mandatory boolean DEFAULT false,
    ambient text,
    details jsonb DEFAULT '{}'::jsonb,
    created_cycle integer DEFAULT 1,
    removed_cycle integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: chronology; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chronology (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    cycle integer NOT NULL,
    "time" character varying(5),
    location_id uuid,
    summary text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: chronology_participants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chronology_participants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    chronology_id uuid NOT NULL,
    entity_id uuid NOT NULL
);


--
-- Name: conversations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    start_cycle integer NOT NULL,
    end_cycle integer,
    compacted boolean DEFAULT false,
    compacted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: entity_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entity_registry (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    entity_type character varying(50) NOT NULL,
    name character varying(255) NOT NULL
);


--
-- Name: event_participants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_participants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_id uuid NOT NULL,
    entity_id uuid NOT NULL
);


--
-- Name: events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    type character varying(50) NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    planned_cycle integer,
    "time" character varying(5),
    location_id uuid,
    completed boolean DEFAULT false,
    cancelled boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: extraction_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.extraction_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    conversation_id uuid,
    cycle integer,
    type character varying(50),
    duration_ms integer,
    messages_processed integer,
    facts_created integer DEFAULT 0,
    entities_modified integer DEFAULT 0,
    errors jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: fact_participants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fact_participants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    fact_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    role character varying(50)
);


--
-- Name: facts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    cycle integer NOT NULL,
    "time" character varying(5),
    type character varying(50) NOT NULL,
    description text NOT NULL,
    location_id uuid,
    importance integer DEFAULT 3,
    semantic_key character varying(100),
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT facts_importance_check CHECK (((importance >= 1) AND (importance <= 5)))
);


--
-- Name: games; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.games (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name character varying(255) DEFAULT 'Nouvelle partie'::character varying,
    current_cycle integer DEFAULT 0,
    "current_date" character varying(50),
    "current_time" character varying(5),
    current_location_id uuid,
    world_name character varying(255),
    world_description text,
    world_atmosphere character varying(255),
    world_seed_words text[],
    world_founding_cycle integer,
    detail_requests text[] DEFAULT '{}'::text[],
    active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    last_extraction_time character varying(5),
    engine character varying(20) DEFAULT 'none'::character varying NOT NULL,
    engine_locked boolean DEFAULT false NOT NULL,
    world_config jsonb,
    genre_id uuid
);


--
-- Name: genres; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.genres (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    slug character varying(30) NOT NULL,
    label character varying(100) NOT NULL,
    is_preset boolean DEFAULT false,
    tone_style text NOT NULL,
    friction_flavor text NOT NULL,
    atmosphere_guidelines text,
    world_type character varying(100),
    location_types text[],
    npc_archetypes text[],
    arrival_prompt text,
    world_gen_example text,
    forbidden_ai_names text[],
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: inventory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inventory (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    object_id uuid NOT NULL,
    owner_id uuid,
    quantity integer DEFAULT 1,
    acquired_cycle integer,
    origin character varying(50)
);


--
-- Name: locations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.locations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    parent_id uuid,
    location_type character varying(100),
    sector character varying(255),
    description text,
    atmosphere character varying(255),
    accessible boolean DEFAULT true,
    notable_features text[],
    typical_crowd character varying(255),
    operating_hours character varying(50),
    price_range character varying(50),
    ambient text,
    details jsonb DEFAULT '{}'::jsonb,
    created_cycle integer DEFAULT 1,
    removed_cycle integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: mechanic_rolls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mechanic_rolls (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    message_id uuid,
    engine character varying(20) NOT NULL,
    skill_used character varying(100),
    roll_details jsonb NOT NULL,
    outcome character varying(50) NOT NULL,
    complication boolean DEFAULT false,
    cycle integer,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.messages (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    role character varying(20) NOT NULL,
    content text NOT NULL,
    cycle integer,
    "time" character varying(5),
    location_id uuid,
    chronology_id uuid,
    narrator_deltas jsonb,
    sequence integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    game_date character varying(50),
    engine_snapshot jsonb,
    narrator_context jsonb
);


--
-- Name: narrative_arcs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.narrative_arcs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    title character varying(255) NOT NULL,
    domain character varying(50),
    description text,
    intensity integer DEFAULT 3,
    progress integer DEFAULT 0,
    situation text,
    desire text,
    obstacle text,
    potential_triggers text[],
    stakes text,
    deadline_cycle integer,
    resolved boolean DEFAULT false,
    resolved_cycle integer,
    resolution text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    owner_id uuid,
    objective text,
    steps jsonb DEFAULT '[]'::jsonb,
    CONSTRAINT narrative_arcs_intensity_check CHECK (((intensity >= 1) AND (intensity <= 5))),
    CONSTRAINT narrative_arcs_progress_check CHECK (((progress >= 0) AND (progress <= 100)))
);


--
-- Name: narrative_seeds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.narrative_seeds (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    cycle integer NOT NULL,
    text text NOT NULL,
    location_id uuid,
    status character varying(20) DEFAULT 'active'::character varying,
    crystallized_arc_id uuid,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: npc_d6; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.npc_d6 (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    character_id uuid NOT NULL,
    attributes jsonb DEFAULT '{}'::jsonb,
    skills jsonb DEFAULT '{}'::jsonb,
    wounds jsonb DEFAULT '{}'::jsonb,
    force_points integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: npc_fate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.npc_fate (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    character_id uuid NOT NULL,
    aspects jsonb DEFAULT '[]'::jsonb,
    skills jsonb DEFAULT '{}'::jsonb,
    stunts jsonb DEFAULT '[]'::jsonb,
    stress_physical boolean[] DEFAULT '{f,f}'::boolean[],
    stress_mental boolean[] DEFAULT '{f,f}'::boolean[],
    consequences jsonb DEFAULT '{}'::jsonb,
    fate_points integer DEFAULT 1,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: npc_narrative; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.npc_narrative (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    character_id uuid NOT NULL,
    traits jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: object_d6; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.object_d6 (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    object_id uuid NOT NULL,
    stats jsonb DEFAULT '{}'::jsonb
);


--
-- Name: object_fate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.object_fate (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    object_id uuid NOT NULL,
    item_type character varying(20),
    stunts jsonb DEFAULT '[]'::jsonb
);


--
-- Name: object_narrative; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.object_narrative (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    object_id uuid NOT NULL,
    narrative_description text
);


--
-- Name: objects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.objects (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    category character varying(100),
    description text,
    transportable boolean DEFAULT true,
    stackable boolean DEFAULT false,
    base_value integer,
    details jsonb DEFAULT '{}'::jsonb,
    created_cycle integer DEFAULT 1,
    removed_cycle integer,
    created_at timestamp with time zone DEFAULT now(),
    canonical_name character varying(100)
);


--
-- Name: organizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organizations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    org_type character varying(100),
    domain character varying(255),
    size character varying(50),
    description text,
    reputation character varying(255),
    headquarters_id uuid,
    founding_cycle integer,
    ambient text,
    details jsonb DEFAULT '{}'::jsonb,
    created_cycle integer DEFAULT 1,
    removed_cycle integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: personal_assistants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.personal_assistants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    voice character varying(255),
    traits text[],
    quirk text,
    substrate character varying(100) DEFAULT 'terminal personnel'::character varying,
    details jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: protagonists; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protagonists (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    energy numeric(3,1) DEFAULT 4.0,
    morale numeric(3,1) DEFAULT 3.0,
    health numeric(3,1) DEFAULT 5.0,
    credits integer DEFAULT 1400,
    occupation character varying(255),
    employer_id uuid,
    residence_id uuid,
    origin character varying(255),
    departure_reason character varying(50),
    backstory text,
    hobbies text[],
    description text,
    details jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.relations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    type public.relation_type NOT NULL,
    source_id uuid NOT NULL,
    target_id uuid NOT NULL,
    level integer,
    context text,
    known_by_protagonist boolean DEFAULT true,
    start_cycle integer DEFAULT 1,
    end_cycle integer,
    end_reason text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying(128) NOT NULL
);


--
-- Name: skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skills (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    protagonist_id uuid,
    character_id uuid,
    name character varying(100) NOT NULL,
    level integer,
    start_cycle integer DEFAULT 1,
    end_cycle integer,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT skills_check CHECK ((((protagonist_id IS NOT NULL) AND (character_id IS NULL)) OR ((protagonist_id IS NULL) AND (character_id IS NOT NULL)))),
    CONSTRAINT skills_level_check CHECK (((level >= 1) AND (level <= 5)))
);


--
-- Name: skills_d6; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skills_d6 (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    attribute character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    dice_value character varying(10) NOT NULL,
    custom boolean DEFAULT false
);


--
-- Name: skills_fate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.skills_fate (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    level integer DEFAULT 0 NOT NULL,
    custom boolean DEFAULT false
);


--
-- Name: traits_narrative; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.traits_narrative (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    game_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    active boolean DEFAULT true,
    replaced_by uuid,
    created_cycle integer DEFAULT 1
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    display_name character varying(100),
    created_at timestamp with time zone DEFAULT now(),
    preferences jsonb DEFAULT '{}'::jsonb,
    email_verified boolean DEFAULT false,
    email_verification_token character varying(64),
    email_verification_sent_at timestamp with time zone
);


--
-- Name: v_active_arcs; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_active_arcs AS
SELECT
    NULL::uuid AS id,
    NULL::uuid AS game_id,
    NULL::character varying(255) AS title,
    NULL::character varying(50) AS domain,
    NULL::text AS description,
    NULL::integer AS intensity,
    NULL::integer AS progress,
    NULL::text AS situation,
    NULL::text AS desire,
    NULL::text AS obstacle,
    NULL::text AS stakes,
    NULL::integer AS deadline_cycle,
    NULL::jsonb[] AS participants;


--
-- Name: v_active_relations; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_active_relations AS
 SELECT r.id AS relation_id,
    r.game_id,
    r.type AS relation_type,
    r.source_id,
    es.entity_type AS source_type,
    es.name AS source_name,
    r.target_id,
    et.entity_type AS target_type,
    et.name AS target_name,
    r.level,
    r.context,
    r.known_by_protagonist,
    r.start_cycle
   FROM ((public.relations r
     JOIN public.entity_registry es ON ((r.source_id = es.id)))
     JOIN public.entity_registry et ON ((r.target_id = et.id)))
  WHERE (r.end_cycle IS NULL);


--
-- Name: v_chronology; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_chronology AS
SELECT
    NULL::uuid AS id,
    NULL::uuid AS game_id,
    NULL::integer AS cycle,
    NULL::character varying(5) AS "time",
    NULL::character varying(255) AS location_name,
    NULL::text AS summary,
    NULL::character varying[] AS npcs_present;


--
-- Name: v_protagonist_inventory; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_protagonist_inventory AS
 SELECT i.game_id,
    o.id AS object_id,
    o.name AS object_name,
    o.category,
    o.base_value,
    o.description,
    i.quantity,
    i.origin,
    i.acquired_cycle
   FROM (public.inventory i
     JOIN public.objects o ON ((i.object_id = o.id)))
  WHERE ((i.owner_id IS NULL) AND (o.removed_cycle IS NULL));


--
-- Name: v_recent_facts; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_recent_facts AS
SELECT
    NULL::uuid AS id,
    NULL::uuid AS game_id,
    NULL::integer AS cycle,
    NULL::character varying(5) AS "time",
    NULL::character varying(50) AS type,
    NULL::text AS description,
    NULL::integer AS importance,
    NULL::character varying(100) AS semantic_key,
    NULL::character varying(255) AS location_name,
    NULL::jsonb[] AS participants;


--
-- Name: v_upcoming_events; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_upcoming_events AS
SELECT
    NULL::uuid AS id,
    NULL::uuid AS game_id,
    NULL::character varying(50) AS type,
    NULL::character varying(255) AS title,
    NULL::text AS description,
    NULL::integer AS planned_cycle,
    NULL::character varying(5) AS "time",
    NULL::character varying(255) AS location_name,
    NULL::character varying[] AS participants;


--
-- Name: arc_participants arc_participants_arc_id_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.arc_participants
    ADD CONSTRAINT arc_participants_arc_id_entity_id_key UNIQUE (arc_id, entity_id);


--
-- Name: arc_participants arc_participants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.arc_participants
    ADD CONSTRAINT arc_participants_pkey PRIMARY KEY (id);


--
-- Name: character_d6 character_d6_game_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_d6
    ADD CONSTRAINT character_d6_game_id_key UNIQUE (game_id);


--
-- Name: character_d6 character_d6_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_d6
    ADD CONSTRAINT character_d6_pkey PRIMARY KEY (id);


--
-- Name: character_fate character_fate_game_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_fate
    ADD CONSTRAINT character_fate_game_id_key UNIQUE (game_id);


--
-- Name: character_fate character_fate_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_fate
    ADD CONSTRAINT character_fate_pkey PRIMARY KEY (id);


--
-- Name: character_narrative character_narrative_game_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_narrative
    ADD CONSTRAINT character_narrative_game_id_key UNIQUE (game_id);


--
-- Name: character_narrative character_narrative_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_narrative
    ADD CONSTRAINT character_narrative_pkey PRIMARY KEY (id);


--
-- Name: characters characters_game_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.characters
    ADD CONSTRAINT characters_game_id_name_key UNIQUE (game_id, name);


--
-- Name: characters characters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.characters
    ADD CONSTRAINT characters_pkey PRIMARY KEY (id);


--
-- Name: chronology_participants chronology_participants_chronology_id_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chronology_participants
    ADD CONSTRAINT chronology_participants_chronology_id_entity_id_key UNIQUE (chronology_id, entity_id);


--
-- Name: chronology_participants chronology_participants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chronology_participants
    ADD CONSTRAINT chronology_participants_pkey PRIMARY KEY (id);


--
-- Name: chronology chronology_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chronology
    ADD CONSTRAINT chronology_pkey PRIMARY KEY (id);


--
-- Name: conversations conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);


--
-- Name: entity_registry entity_registry_game_id_entity_type_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_registry
    ADD CONSTRAINT entity_registry_game_id_entity_type_name_key UNIQUE (game_id, entity_type, name);


--
-- Name: entity_registry entity_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_registry
    ADD CONSTRAINT entity_registry_pkey PRIMARY KEY (id);


--
-- Name: event_participants event_participants_event_id_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_participants
    ADD CONSTRAINT event_participants_event_id_entity_id_key UNIQUE (event_id, entity_id);


--
-- Name: event_participants event_participants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_participants
    ADD CONSTRAINT event_participants_pkey PRIMARY KEY (id);


--
-- Name: events events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_pkey PRIMARY KEY (id);


--
-- Name: extraction_logs extraction_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extraction_logs
    ADD CONSTRAINT extraction_logs_pkey PRIMARY KEY (id);


--
-- Name: fact_participants fact_participants_fact_id_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_participants
    ADD CONSTRAINT fact_participants_fact_id_entity_id_key UNIQUE (fact_id, entity_id);


--
-- Name: fact_participants fact_participants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_participants
    ADD CONSTRAINT fact_participants_pkey PRIMARY KEY (id);


--
-- Name: facts facts_game_id_cycle_semantic_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_game_id_cycle_semantic_key_key UNIQUE (game_id, cycle, semantic_key);


--
-- Name: facts facts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_pkey PRIMARY KEY (id);


--
-- Name: games games_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.games
    ADD CONSTRAINT games_pkey PRIMARY KEY (id);


--
-- Name: genres genres_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.genres
    ADD CONSTRAINT genres_pkey PRIMARY KEY (id);


--
-- Name: genres genres_slug_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.genres
    ADD CONSTRAINT genres_slug_user_id_key UNIQUE (slug, user_id);


--
-- Name: inventory inventory_game_id_object_id_owner_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_game_id_object_id_owner_id_key UNIQUE (game_id, object_id, owner_id);


--
-- Name: inventory inventory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_pkey PRIMARY KEY (id);


--
-- Name: locations locations_game_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations
    ADD CONSTRAINT locations_game_id_name_key UNIQUE (game_id, name);


--
-- Name: locations locations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations
    ADD CONSTRAINT locations_pkey PRIMARY KEY (id);


--
-- Name: mechanic_rolls mechanic_rolls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mechanic_rolls
    ADD CONSTRAINT mechanic_rolls_pkey PRIMARY KEY (id);


--
-- Name: messages messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);


--
-- Name: narrative_arcs narrative_arcs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.narrative_arcs
    ADD CONSTRAINT narrative_arcs_pkey PRIMARY KEY (id);


--
-- Name: narrative_seeds narrative_seeds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.narrative_seeds
    ADD CONSTRAINT narrative_seeds_pkey PRIMARY KEY (id);


--
-- Name: npc_d6 npc_d6_character_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_d6
    ADD CONSTRAINT npc_d6_character_id_key UNIQUE (character_id);


--
-- Name: npc_d6 npc_d6_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_d6
    ADD CONSTRAINT npc_d6_pkey PRIMARY KEY (id);


--
-- Name: npc_fate npc_fate_character_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_fate
    ADD CONSTRAINT npc_fate_character_id_key UNIQUE (character_id);


--
-- Name: npc_fate npc_fate_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_fate
    ADD CONSTRAINT npc_fate_pkey PRIMARY KEY (id);


--
-- Name: npc_narrative npc_narrative_character_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_narrative
    ADD CONSTRAINT npc_narrative_character_id_key UNIQUE (character_id);


--
-- Name: npc_narrative npc_narrative_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_narrative
    ADD CONSTRAINT npc_narrative_pkey PRIMARY KEY (id);


--
-- Name: object_d6 object_d6_object_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_d6
    ADD CONSTRAINT object_d6_object_id_key UNIQUE (object_id);


--
-- Name: object_d6 object_d6_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_d6
    ADD CONSTRAINT object_d6_pkey PRIMARY KEY (id);


--
-- Name: object_fate object_fate_object_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_fate
    ADD CONSTRAINT object_fate_object_id_key UNIQUE (object_id);


--
-- Name: object_fate object_fate_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_fate
    ADD CONSTRAINT object_fate_pkey PRIMARY KEY (id);


--
-- Name: object_narrative object_narrative_object_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_narrative
    ADD CONSTRAINT object_narrative_object_id_key UNIQUE (object_id);


--
-- Name: object_narrative object_narrative_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_narrative
    ADD CONSTRAINT object_narrative_pkey PRIMARY KEY (id);


--
-- Name: objects objects_game_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.objects
    ADD CONSTRAINT objects_game_id_name_key UNIQUE (game_id, name);


--
-- Name: objects objects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.objects
    ADD CONSTRAINT objects_pkey PRIMARY KEY (id);


--
-- Name: organizations organizations_game_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_game_id_name_key UNIQUE (game_id, name);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- Name: personal_assistants personal_assistants_game_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_assistants
    ADD CONSTRAINT personal_assistants_game_id_key UNIQUE (game_id);


--
-- Name: personal_assistants personal_assistants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_assistants
    ADD CONSTRAINT personal_assistants_pkey PRIMARY KEY (id);


--
-- Name: protagonists protagonists_game_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protagonists
    ADD CONSTRAINT protagonists_game_id_key UNIQUE (game_id);


--
-- Name: protagonists protagonists_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protagonists
    ADD CONSTRAINT protagonists_pkey PRIMARY KEY (id);


--
-- Name: relations relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.relations
    ADD CONSTRAINT relations_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: skills_d6 skills_d6_game_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills_d6
    ADD CONSTRAINT skills_d6_game_id_name_key UNIQUE (game_id, name);


--
-- Name: skills_d6 skills_d6_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills_d6
    ADD CONSTRAINT skills_d6_pkey PRIMARY KEY (id);


--
-- Name: skills_fate skills_fate_game_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills_fate
    ADD CONSTRAINT skills_fate_game_id_name_key UNIQUE (game_id, name);


--
-- Name: skills_fate skills_fate_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills_fate
    ADD CONSTRAINT skills_fate_pkey PRIMARY KEY (id);


--
-- Name: skills skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_pkey PRIMARY KEY (id);


--
-- Name: traits_narrative traits_narrative_game_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.traits_narrative
    ADD CONSTRAINT traits_narrative_game_id_name_key UNIQUE (game_id, name);


--
-- Name: traits_narrative traits_narrative_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.traits_narrative
    ADD CONSTRAINT traits_narrative_pkey PRIMARY KEY (id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: idx_arc_participants_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_arc_participants_entity ON public.arc_participants USING btree (entity_id);


--
-- Name: idx_arcs_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_arcs_active ON public.narrative_arcs USING btree (game_id) WHERE (resolved = false);


--
-- Name: idx_arcs_deadline; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_arcs_deadline ON public.narrative_arcs USING btree (game_id, deadline_cycle) WHERE ((resolved = false) AND (deadline_cycle IS NOT NULL));


--
-- Name: idx_arcs_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_arcs_game ON public.narrative_arcs USING btree (game_id);


--
-- Name: idx_arcs_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_arcs_owner ON public.narrative_arcs USING btree (owner_id) WHERE (owner_id IS NOT NULL);


--
-- Name: idx_characters_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_characters_active ON public.characters USING btree (game_id) WHERE (removed_cycle IS NULL);


--
-- Name: idx_characters_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_characters_game ON public.characters USING btree (game_id);


--
-- Name: idx_characters_known; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_characters_known ON public.characters USING btree (game_id) WHERE ((known_by_protagonist = true) AND (removed_cycle IS NULL));


--
-- Name: idx_chronology_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chronology_game ON public.chronology USING btree (game_id, cycle);


--
-- Name: idx_chronology_participants; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chronology_participants ON public.chronology_participants USING btree (entity_id);


--
-- Name: idx_conversations_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversations_active ON public.conversations USING btree (game_id) WHERE (compacted = false);


--
-- Name: idx_conversations_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversations_game ON public.conversations USING btree (game_id);


--
-- Name: idx_entity_registry_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entity_registry_game ON public.entity_registry USING btree (game_id);


--
-- Name: idx_entity_registry_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entity_registry_name ON public.entity_registry USING btree (game_id, name);


--
-- Name: idx_event_participants_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_participants_entity ON public.event_participants USING btree (entity_id);


--
-- Name: idx_events_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_active ON public.events USING btree (game_id, planned_cycle) WHERE ((completed = false) AND (cancelled = false));


--
-- Name: idx_events_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_events_game ON public.events USING btree (game_id);


--
-- Name: idx_extraction_logs_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_extraction_logs_game ON public.extraction_logs USING btree (game_id, cycle);


--
-- Name: idx_fact_participants_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fact_participants_entity ON public.fact_participants USING btree (entity_id);


--
-- Name: idx_fact_participants_fact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fact_participants_fact ON public.fact_participants USING btree (fact_id);


--
-- Name: idx_facts_cycle; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_facts_cycle ON public.facts USING btree (game_id, cycle);


--
-- Name: idx_facts_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_facts_game ON public.facts USING btree (game_id);


--
-- Name: idx_facts_location; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_facts_location ON public.facts USING btree (location_id);


--
-- Name: idx_facts_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_facts_type ON public.facts USING btree (game_id, type);


--
-- Name: idx_games_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_games_active ON public.games USING btree (user_id) WHERE (active = true);


--
-- Name: idx_games_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_games_user ON public.games USING btree (user_id);


--
-- Name: idx_genres_presets; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_genres_presets ON public.genres USING btree (is_preset) WHERE (is_preset = true);


--
-- Name: idx_genres_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_genres_user ON public.genres USING btree (user_id) WHERE (user_id IS NOT NULL);


--
-- Name: idx_inventory_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_inventory_game ON public.inventory USING btree (game_id);


--
-- Name: idx_inventory_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_inventory_owner ON public.inventory USING btree (owner_id);


--
-- Name: idx_locations_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_locations_active ON public.locations USING btree (game_id) WHERE (removed_cycle IS NULL);


--
-- Name: idx_locations_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_locations_game ON public.locations USING btree (game_id);


--
-- Name: idx_locations_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_locations_parent ON public.locations USING btree (parent_id);


--
-- Name: idx_mechanic_rolls_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mechanic_rolls_game ON public.mechanic_rolls USING btree (game_id, cycle);


--
-- Name: idx_messages_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_messages_conversation ON public.messages USING btree (conversation_id, sequence);


--
-- Name: idx_messages_game_cycle; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_messages_game_cycle ON public.messages USING btree (game_id, cycle);


--
-- Name: idx_npc_d6_char; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_npc_d6_char ON public.npc_d6 USING btree (character_id);


--
-- Name: idx_npc_fate_char; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_npc_fate_char ON public.npc_fate USING btree (character_id);


--
-- Name: idx_npc_narrative_char; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_npc_narrative_char ON public.npc_narrative USING btree (character_id);


--
-- Name: idx_objects_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_objects_active ON public.objects USING btree (game_id) WHERE (removed_cycle IS NULL);


--
-- Name: idx_objects_canonical; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_objects_canonical ON public.objects USING btree (game_id, canonical_name) WHERE ((canonical_name IS NOT NULL) AND (removed_cycle IS NULL));


--
-- Name: idx_objects_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_objects_game ON public.objects USING btree (game_id);


--
-- Name: idx_organizations_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_organizations_active ON public.organizations USING btree (game_id) WHERE (removed_cycle IS NULL);


--
-- Name: idx_organizations_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_organizations_game ON public.organizations USING btree (game_id);


--
-- Name: idx_relations_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relations_active ON public.relations USING btree (game_id) WHERE (end_cycle IS NULL);


--
-- Name: idx_relations_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relations_game ON public.relations USING btree (game_id);


--
-- Name: idx_relations_known; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relations_known ON public.relations USING btree (game_id) WHERE ((known_by_protagonist = true) AND (end_cycle IS NULL));


--
-- Name: idx_relations_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relations_source ON public.relations USING btree (source_id);


--
-- Name: idx_relations_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relations_target ON public.relations USING btree (target_id);


--
-- Name: idx_relations_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relations_type ON public.relations USING btree (game_id, type);


--
-- Name: idx_seeds_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_seeds_active ON public.narrative_seeds USING btree (game_id) WHERE ((status)::text = 'active'::text);


--
-- Name: idx_seeds_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_seeds_game ON public.narrative_seeds USING btree (game_id);


--
-- Name: idx_skills_character; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_skills_character ON public.skills USING btree (character_id) WHERE (end_cycle IS NULL);


--
-- Name: idx_skills_d6_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_skills_d6_game ON public.skills_d6 USING btree (game_id);


--
-- Name: idx_skills_fate_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_skills_fate_game ON public.skills_fate USING btree (game_id);


--
-- Name: idx_skills_protagonist; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_skills_protagonist ON public.skills USING btree (protagonist_id) WHERE (end_cycle IS NULL);


--
-- Name: idx_traits_narrative_game; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_traits_narrative_game ON public.traits_narrative USING btree (game_id) WHERE (active = true);


--
-- Name: users_display_name_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX users_display_name_key ON public.users USING btree (display_name) WHERE (display_name IS NOT NULL);


--
-- Name: v_active_arcs _RETURN; Type: RULE; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.v_active_arcs AS
 SELECT na.id,
    na.game_id,
    na.title,
    na.domain,
    na.description,
    na.intensity,
    na.progress,
    na.situation,
    na.desire,
    na.obstacle,
    na.stakes,
    na.deadline_cycle,
    array_agg(jsonb_build_object('name', er.name, 'type', er.entity_type, 'role', ap.role)) FILTER (WHERE (er.name IS NOT NULL)) AS participants
   FROM ((public.narrative_arcs na
     LEFT JOIN public.arc_participants ap ON ((ap.arc_id = na.id)))
     LEFT JOIN public.entity_registry er ON ((ap.entity_id = er.id)))
  WHERE (na.resolved = false)
  GROUP BY na.id;


--
-- Name: v_chronology _RETURN; Type: RULE; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.v_chronology AS
 SELECT c.id,
    c.game_id,
    c.cycle,
    c."time",
    l.name AS location_name,
    c.summary,
    array_agg(er.name) FILTER (WHERE (er.name IS NOT NULL)) AS npcs_present
   FROM (((public.chronology c
     LEFT JOIN public.locations l ON ((c.location_id = l.id)))
     LEFT JOIN public.chronology_participants cp ON ((cp.chronology_id = c.id)))
     LEFT JOIN public.entity_registry er ON ((cp.entity_id = er.id)))
  GROUP BY c.id, l.name;


--
-- Name: v_recent_facts _RETURN; Type: RULE; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.v_recent_facts AS
 SELECT f.id,
    f.game_id,
    f.cycle,
    f."time",
    f.type,
    f.description,
    f.importance,
    f.semantic_key,
    l.name AS location_name,
    array_agg(jsonb_build_object('name', er.name, 'role', fp.role)) FILTER (WHERE (er.name IS NOT NULL)) AS participants
   FROM (((public.facts f
     LEFT JOIN public.locations l ON ((f.location_id = l.id)))
     LEFT JOIN public.fact_participants fp ON ((fp.fact_id = f.id)))
     LEFT JOIN public.entity_registry er ON ((fp.entity_id = er.id)))
  GROUP BY f.id, l.name;


--
-- Name: v_upcoming_events _RETURN; Type: RULE; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.v_upcoming_events AS
 SELECT ev.id,
    ev.game_id,
    ev.type,
    ev.title,
    ev.description,
    ev.planned_cycle,
    ev."time",
    l.name AS location_name,
    array_agg(er.name) FILTER (WHERE (er.name IS NOT NULL)) AS participants
   FROM (((public.events ev
     LEFT JOIN public.locations l ON ((ev.location_id = l.id)))
     LEFT JOIN public.event_participants ep ON ((ev.id = ep.event_id)))
     LEFT JOIN public.entity_registry er ON ((ep.entity_id = er.id)))
  WHERE ((ev.completed = false) AND (ev.cancelled = false))
  GROUP BY ev.id, l.name;


--
-- Name: facts facts_no_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER facts_no_update BEFORE UPDATE ON public.facts FOR EACH ROW EXECUTE FUNCTION public.facts_immutable();


--
-- Name: characters register_character; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER register_character AFTER INSERT ON public.characters FOR EACH ROW EXECUTE FUNCTION public.register_entity('character');


--
-- Name: locations register_location; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER register_location AFTER INSERT ON public.locations FOR EACH ROW EXECUTE FUNCTION public.register_entity('location');


--
-- Name: objects register_object; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER register_object AFTER INSERT ON public.objects FOR EACH ROW EXECUTE FUNCTION public.register_entity('object');


--
-- Name: organizations register_organization; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER register_organization AFTER INSERT ON public.organizations FOR EACH ROW EXECUTE FUNCTION public.register_entity('organization');


--
-- Name: protagonists register_protagonist; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER register_protagonist AFTER INSERT ON public.protagonists FOR EACH ROW EXECUTE FUNCTION public.register_entity('protagonist');


--
-- Name: characters update_registry_character; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_registry_character AFTER UPDATE OF name ON public.characters FOR EACH ROW EXECUTE FUNCTION public.update_entity_registry_name('character');


--
-- Name: locations update_registry_location; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_registry_location AFTER UPDATE OF name ON public.locations FOR EACH ROW EXECUTE FUNCTION public.update_entity_registry_name('location');


--
-- Name: objects update_registry_object; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_registry_object AFTER UPDATE OF name ON public.objects FOR EACH ROW EXECUTE FUNCTION public.update_entity_registry_name('object');


--
-- Name: organizations update_registry_organization; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_registry_organization AFTER UPDATE OF name ON public.organizations FOR EACH ROW EXECUTE FUNCTION public.update_entity_registry_name('organization');


--
-- Name: arc_participants arc_participants_arc_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.arc_participants
    ADD CONSTRAINT arc_participants_arc_id_fkey FOREIGN KEY (arc_id) REFERENCES public.narrative_arcs(id) ON DELETE CASCADE;


--
-- Name: arc_participants arc_participants_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.arc_participants
    ADD CONSTRAINT arc_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entity_registry(id);


--
-- Name: character_d6 character_d6_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_d6
    ADD CONSTRAINT character_d6_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: character_fate character_fate_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_fate
    ADD CONSTRAINT character_fate_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: character_narrative character_narrative_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.character_narrative
    ADD CONSTRAINT character_narrative_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: characters characters_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.characters
    ADD CONSTRAINT characters_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: characters characters_residence_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.characters
    ADD CONSTRAINT characters_residence_id_fkey FOREIGN KEY (residence_id) REFERENCES public.locations(id);


--
-- Name: characters characters_workplace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.characters
    ADD CONSTRAINT characters_workplace_id_fkey FOREIGN KEY (workplace_id) REFERENCES public.locations(id);


--
-- Name: chronology chronology_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chronology
    ADD CONSTRAINT chronology_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: chronology chronology_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chronology
    ADD CONSTRAINT chronology_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id);


--
-- Name: chronology_participants chronology_participants_chronology_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chronology_participants
    ADD CONSTRAINT chronology_participants_chronology_id_fkey FOREIGN KEY (chronology_id) REFERENCES public.chronology(id) ON DELETE CASCADE;


--
-- Name: chronology_participants chronology_participants_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chronology_participants
    ADD CONSTRAINT chronology_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entity_registry(id);


--
-- Name: conversations conversations_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: entity_registry entity_registry_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_registry
    ADD CONSTRAINT entity_registry_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: event_participants event_participants_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_participants
    ADD CONSTRAINT event_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entity_registry(id);


--
-- Name: event_participants event_participants_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_participants
    ADD CONSTRAINT event_participants_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.events(id) ON DELETE CASCADE;


--
-- Name: events events_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: events events_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id);


--
-- Name: extraction_logs extraction_logs_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extraction_logs
    ADD CONSTRAINT extraction_logs_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id);


--
-- Name: extraction_logs extraction_logs_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.extraction_logs
    ADD CONSTRAINT extraction_logs_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: fact_participants fact_participants_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_participants
    ADD CONSTRAINT fact_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entity_registry(id);


--
-- Name: fact_participants fact_participants_fact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_participants
    ADD CONSTRAINT fact_participants_fact_id_fkey FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE CASCADE;


--
-- Name: facts facts_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: facts facts_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id);


--
-- Name: games fk_games_current_location; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.games
    ADD CONSTRAINT fk_games_current_location FOREIGN KEY (current_location_id) REFERENCES public.locations(id);


--
-- Name: protagonists fk_protagonists_employer; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protagonists
    ADD CONSTRAINT fk_protagonists_employer FOREIGN KEY (employer_id) REFERENCES public.organizations(id);


--
-- Name: protagonists fk_protagonists_residence; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protagonists
    ADD CONSTRAINT fk_protagonists_residence FOREIGN KEY (residence_id) REFERENCES public.locations(id);


--
-- Name: games games_genre_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.games
    ADD CONSTRAINT games_genre_id_fkey FOREIGN KEY (genre_id) REFERENCES public.genres(id);


--
-- Name: games games_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.games
    ADD CONSTRAINT games_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: genres genres_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.genres
    ADD CONSTRAINT genres_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: inventory inventory_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: inventory inventory_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_object_id_fkey FOREIGN KEY (object_id) REFERENCES public.objects(id);


--
-- Name: inventory inventory_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.entity_registry(id);


--
-- Name: locations locations_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations
    ADD CONSTRAINT locations_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: locations locations_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations
    ADD CONSTRAINT locations_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.locations(id);


--
-- Name: mechanic_rolls mechanic_rolls_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mechanic_rolls
    ADD CONSTRAINT mechanic_rolls_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: mechanic_rolls mechanic_rolls_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mechanic_rolls
    ADD CONSTRAINT mechanic_rolls_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE SET NULL;


--
-- Name: messages messages_chronology_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_chronology_id_fkey FOREIGN KEY (chronology_id) REFERENCES public.chronology(id);


--
-- Name: messages messages_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE CASCADE;


--
-- Name: messages messages_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: messages messages_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id);


--
-- Name: narrative_arcs narrative_arcs_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.narrative_arcs
    ADD CONSTRAINT narrative_arcs_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: narrative_arcs narrative_arcs_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.narrative_arcs
    ADD CONSTRAINT narrative_arcs_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.entity_registry(id);


--
-- Name: narrative_seeds narrative_seeds_crystallized_arc_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.narrative_seeds
    ADD CONSTRAINT narrative_seeds_crystallized_arc_id_fkey FOREIGN KEY (crystallized_arc_id) REFERENCES public.narrative_arcs(id);


--
-- Name: narrative_seeds narrative_seeds_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.narrative_seeds
    ADD CONSTRAINT narrative_seeds_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: narrative_seeds narrative_seeds_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.narrative_seeds
    ADD CONSTRAINT narrative_seeds_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id);


--
-- Name: npc_d6 npc_d6_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_d6
    ADD CONSTRAINT npc_d6_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id) ON DELETE CASCADE;


--
-- Name: npc_fate npc_fate_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_fate
    ADD CONSTRAINT npc_fate_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id) ON DELETE CASCADE;


--
-- Name: npc_narrative npc_narrative_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.npc_narrative
    ADD CONSTRAINT npc_narrative_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id) ON DELETE CASCADE;


--
-- Name: object_d6 object_d6_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_d6
    ADD CONSTRAINT object_d6_object_id_fkey FOREIGN KEY (object_id) REFERENCES public.objects(id) ON DELETE CASCADE;


--
-- Name: object_fate object_fate_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_fate
    ADD CONSTRAINT object_fate_object_id_fkey FOREIGN KEY (object_id) REFERENCES public.objects(id) ON DELETE CASCADE;


--
-- Name: object_narrative object_narrative_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.object_narrative
    ADD CONSTRAINT object_narrative_object_id_fkey FOREIGN KEY (object_id) REFERENCES public.objects(id) ON DELETE CASCADE;


--
-- Name: objects objects_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.objects
    ADD CONSTRAINT objects_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: organizations organizations_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: organizations organizations_headquarters_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_headquarters_id_fkey FOREIGN KEY (headquarters_id) REFERENCES public.locations(id);


--
-- Name: personal_assistants personal_assistants_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.personal_assistants
    ADD CONSTRAINT personal_assistants_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: protagonists protagonists_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protagonists
    ADD CONSTRAINT protagonists_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: relations relations_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.relations
    ADD CONSTRAINT relations_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: relations relations_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.relations
    ADD CONSTRAINT relations_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.entity_registry(id);


--
-- Name: relations relations_target_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.relations
    ADD CONSTRAINT relations_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.entity_registry(id);


--
-- Name: skills skills_character_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_character_id_fkey FOREIGN KEY (character_id) REFERENCES public.characters(id);


--
-- Name: skills_d6 skills_d6_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills_d6
    ADD CONSTRAINT skills_d6_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: skills_fate skills_fate_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills_fate
    ADD CONSTRAINT skills_fate_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: skills skills_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: skills skills_protagonist_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_protagonist_id_fkey FOREIGN KEY (protagonist_id) REFERENCES public.protagonists(id);


--
-- Name: traits_narrative traits_narrative_game_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.traits_narrative
    ADD CONSTRAINT traits_narrative_game_id_fkey FOREIGN KEY (game_id) REFERENCES public.games(id) ON DELETE CASCADE;


--
-- Name: traits_narrative traits_narrative_replaced_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.traits_narrative
    ADD CONSTRAINT traits_narrative_replaced_by_fkey FOREIGN KEY (replaced_by) REFERENCES public.traits_narrative(id);


--
-- PostgreSQL database dump complete
--


