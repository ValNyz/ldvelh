-- migrate:up
-- #28 (review round 1).

-- 1. Preset genre world generation examples: the sample PC was called "Valentin", a real
-- name the world builder copied. It becomes the slot {{PROTAGONIST_NAME}}, replaced at
-- prompt build time by the wizard's name, or by a visible "invent a name" marker
-- (prompts/world_generation_prompt.py::PROTAGONIST_NAME_SLOT). Only the protagonist object
-- carries "name": "Valentin" in these rows; the down section restores the exact text.
UPDATE public.genres
SET world_gen_example = replace(world_gen_example,
      '"name": "Valentin"', '"name": "{{PROTAGONIST_NAME}}"')
WHERE world_gen_example LIKE '%"name": "Valentin"%';

-- 2. find_entity trims space, tab, CR and LF (not every Unicode whitespace, unlike Python's
-- str.strip() in EntityRegistry.resolve), so " PROTAGONIST\n" resolves on both sides of one
-- extraction.
CREATE OR REPLACE FUNCTION public.find_entity(p_game_id uuid, p_name text, p_type character varying DEFAULT NULL::character varying) RETURNS uuid
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
  v_id UUID;
  v_name TEXT := LOWER(BTRIM(p_name, E' \t\r\n'));
BEGIN
  IF v_name = 'protagonist' THEN
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
    AND LOWER(name) = v_name
  LIMIT 1;
  RETURN v_id;
END;
$$;

-- migrate:down
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

UPDATE public.genres
SET world_gen_example = replace(world_gen_example,
      '"name": "{{PROTAGONIST_NAME}}"', '"name": "Valentin"')
WHERE world_gen_example LIKE '%"name": "{{PROTAGONIST_NAME}}"%';
