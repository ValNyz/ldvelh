-- migrate:up
-- #87: re-listing an existing relation (extractors send relations_created again, with
-- known_by_protagonist defaulting to true) must not reveal or hide it: the existing row
-- keeps its known_by_protagonist, only relations_updated.now_known / mark_relation_known
-- change it. A blank context ('' or whitespace only) no longer wipes the stored one either.
CREATE OR REPLACE FUNCTION public.upsert_relation(p_game_id uuid, p_source_id uuid, p_target_id uuid, p_type public.relation_type, p_cycle integer DEFAULT 1, p_level integer DEFAULT NULL::integer, p_context text DEFAULT NULL::text, p_known_by_protagonist boolean DEFAULT true) RETURNS uuid
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
      context = COALESCE(NULLIF(BTRIM(p_context), ''), context)
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

-- migrate:down
-- Restore the definition from 20260413000000_baseline.sql.
CREATE OR REPLACE FUNCTION public.upsert_relation(p_game_id uuid, p_source_id uuid, p_target_id uuid, p_type public.relation_type, p_cycle integer DEFAULT 1, p_level integer DEFAULT NULL::integer, p_context text DEFAULT NULL::text, p_known_by_protagonist boolean DEFAULT true) RETURNS uuid
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
