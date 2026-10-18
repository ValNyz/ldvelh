-- migrate:up
-- #28: the protagonist is resolved by type, not by the hardcoded name "Valentin".

-- 1. find_entity maps the reserved reference 'PROTAGONIST' (schema.core.PROTAGONIST_REF,
-- case-insensitive) to the game's entity_type='protagonist' row. The real PC name still
-- resolves through the name lookup (register_protagonist puts it in entity_registry).
-- create_fact (participants) and end_relation call it. STABLE: it only reads.
CREATE OR REPLACE FUNCTION public.find_entity(p_game_id uuid, p_name text, p_type character varying DEFAULT NULL::character varying) RETURNS uuid
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
  v_id UUID;
BEGIN
  IF LOWER(TRIM(p_name)) = 'protagonist' THEN
    SELECT id INTO v_id FROM entity_registry
    WHERE game_id = p_game_id
      AND entity_type = 'protagonist'
      AND (p_type IS NULL OR p_type = 'protagonist')
    LIMIT 1;
    RETURN v_id;
  END IF;
  SELECT id INTO v_id FROM entity_registry
  WHERE game_id = p_game_id
    AND (p_type IS NULL OR entity_type = p_type)
    AND LOWER(name) = LOWER(TRIM(p_name))
  LIMIT 1;
  RETURN v_id;
END;
$$;

-- 2. System semantic keys written by the populator: valentin:arrival:* and valentin:use:*
-- become protagonist:* (kg/semantic_keys.py; reader.get_arrival_event reads the new keys).
-- Facts are immutable (facts_no_update): the trigger is disabled for this one UPDATE only.
-- dbmate runs the migration in a transaction and ALTER TABLE locks facts until COMMIT, so
-- no other session can write facts, or see the trigger disabled, in between.
-- NOT EXISTS keeps UNIQUE (game_id, cycle, semantic_key) if a new key is already taken.
ALTER TABLE public.facts DISABLE TRIGGER facts_no_update;
UPDATE public.facts f
SET semantic_key = 'protagonist:' || substr(f.semantic_key, length('valentin:') + 1)
WHERE (f.semantic_key LIKE 'valentin:arrival:%' OR f.semantic_key LIKE 'valentin:use:%')
  AND NOT EXISTS (
    SELECT 1 FROM public.facts o
    WHERE o.game_id = f.game_id AND o.cycle = f.cycle
      AND o.semantic_key = 'protagonist:' || substr(f.semantic_key, length('valentin:') + 1));
ALTER TABLE public.facts ENABLE TRIGGER facts_no_update;

-- 3. Genre world generation examples: initial relations reference the PC by the reserved
-- reference, so the model does not copy "Valentin" into the relations of another PC.
UPDATE public.genres
SET world_gen_example = replace(replace(world_gen_example,
      '"source_ref": "Valentin"', '"source_ref": "PROTAGONIST"'),
      '"target_ref": "Valentin"', '"target_ref": "PROTAGONIST"')
WHERE world_gen_example LIKE '%_ref": "Valentin"%';

-- migrate:down
UPDATE public.genres
SET world_gen_example = replace(replace(world_gen_example,
      '"source_ref": "PROTAGONIST"', '"source_ref": "Valentin"'),
      '"target_ref": "PROTAGONIST"', '"target_ref": "Valentin"')
WHERE world_gen_example LIKE '%_ref": "PROTAGONIST"%';

ALTER TABLE public.facts DISABLE TRIGGER facts_no_update;
UPDATE public.facts f
SET semantic_key = 'valentin:' || substr(f.semantic_key, length('protagonist:') + 1)
WHERE (f.semantic_key LIKE 'protagonist:arrival:%' OR f.semantic_key LIKE 'protagonist:use:%')
  AND NOT EXISTS (
    SELECT 1 FROM public.facts o
    WHERE o.game_id = f.game_id AND o.cycle = f.cycle
      AND o.semantic_key = 'valentin:' || substr(f.semantic_key, length('protagonist:') + 1));
ALTER TABLE public.facts ENABLE TRIGGER facts_no_update;

CREATE OR REPLACE FUNCTION public.find_entity(p_game_id uuid, p_name text, p_type character varying DEFAULT NULL::character varying) RETURNS uuid
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
