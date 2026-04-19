-- migrate:up
-- Fix rollback_to_cycle: add missing table cleanup (inventory, seeds, director_plans)
-- and fix arc deletion when no chronology row exists for target cycle.

CREATE OR REPLACE FUNCTION public.rollback_to_cycle(
    p_game_id uuid,
    p_target_cycle integer
) RETURNS TABLE(
    deleted_facts integer,
    deleted_events integer,
    deleted_arcs integer,
    reverted_relations integer
)
LANGUAGE plpgsql AS $$
DECLARE
  v_deleted_facts INTEGER;
  v_deleted_events INTEGER;
  v_deleted_arcs INTEGER;
  v_reverted_relations INTEGER;
BEGIN
  -- Facts
  DELETE FROM facts WHERE game_id = p_game_id AND cycle > p_target_cycle;
  GET DIAGNOSTICS v_deleted_facts = ROW_COUNT;

  -- Events
  DELETE FROM events WHERE game_id = p_game_id AND planned_cycle > p_target_cycle;
  GET DIAGNOSTICS v_deleted_events = ROW_COUNT;

  -- Narrative arcs created after target cycle
  -- Use chronology timestamp with fallback to avoid NULL comparison
  DELETE FROM narrative_arcs WHERE game_id = p_game_id
    AND created_at > COALESCE(
      (SELECT created_at FROM chronology WHERE game_id = p_game_id AND cycle = p_target_cycle LIMIT 1),
      (SELECT MAX(created_at) FROM chronology WHERE game_id = p_game_id AND cycle <= p_target_cycle),
      '1970-01-01'::timestamptz
    );
  GET DIAGNOSTICS v_deleted_arcs = ROW_COUNT;

  -- Relations
  DELETE FROM relations WHERE game_id = p_game_id AND start_cycle > p_target_cycle;
  GET DIAGNOSTICS v_reverted_relations = ROW_COUNT;
  UPDATE relations SET end_cycle = NULL, end_reason = NULL
    WHERE game_id = p_game_id AND end_cycle > p_target_cycle;

  -- Skills
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

  -- Inventory acquired after target cycle
  DELETE FROM inventory WHERE game_id = p_game_id AND acquired_cycle > p_target_cycle;

  -- Narrative seeds from future cycles
  DELETE FROM narrative_seeds WHERE game_id = p_game_id AND cycle > p_target_cycle;

  -- Director plans from future cycles
  DELETE FROM director_plans WHERE game_id = p_game_id AND cycle > p_target_cycle;

  UPDATE games SET updated_at = now() WHERE id = p_game_id;
  RETURN QUERY SELECT v_deleted_facts, v_deleted_events, v_deleted_arcs, v_reverted_relations;
END;
$$;

-- migrate:down
-- Restoring the old function requires the baseline source.
