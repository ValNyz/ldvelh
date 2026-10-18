-- migrate:up
-- #85: narrative arcs get the cycle they were created in, and rollback_to_cycle deletes
-- them by that cycle instead of comparing created_at with a chronology timestamp.
--
-- Backfill heuristic (best effort, existing rows only). For each arc, take the game's
-- latest message (non-null cycle) and latest Director plan saved at or before the arc's
-- created_at:
-- - the plan is the more recent of the two: the arc comes from that Director run
--   (run_director inserts its plan, then its arcs), so it takes the plan's cycle, the
--   cycle the Director ran for. This covers the race where the scheduled Director, a
--   background task that does not block the next turn, returns after the player's next
--   turn was saved: going by messages alone would give such an arc that next turn's
--   cycle, and rolling back a day-change next turn would then wrongly delete it.
-- - otherwise the arc takes the message's cycle: arcs are written after their turn's
--   messages, with the post-turn cycle, so that message carries the arc's cycle.
-- - neither exists (world generation, before any plan or message) or created_at is
--   NULL: 1, the cycle the world is created in (initial characters, locations, objects
--   use created_cycle = 1 too). A rollback never targets a cycle below 1 (the arrival
--   scene is protected), so such an arc is kept by every rollback: keeping an arc is
--   the safe side, deleting one loses story silently.
-- Residual limit: a Director arc whose plan and arc inserts were split by another
-- turn's messages (microseconds apart) falls back to the message rule.
-- chronology is not used: it only has one row per day and its timestamps are what made
-- the old rule wrong (#85).
-- No DEFAULT: every writer stamps the column, and one that forgets fails on NOT NULL
-- instead of silently writing an arc no rollback removes.
ALTER TABLE narrative_arcs ADD COLUMN created_cycle integer;

UPDATE narrative_arcs na SET created_cycle = COALESCE(
  CASE WHEN dp.created_at IS NOT NULL
            AND (m.created_at IS NULL OR dp.created_at >= m.created_at)
       THEN dp.cycle ELSE m.cycle END,
  1)
FROM narrative_arcs a
LEFT JOIN LATERAL (
  SELECT mm.cycle, mm.created_at FROM messages mm
   WHERE mm.game_id = a.game_id AND mm.cycle IS NOT NULL
     AND mm.created_at <= a.created_at
   ORDER BY mm.created_at DESC, mm.sequence DESC LIMIT 1
) m ON true
LEFT JOIN LATERAL (
  SELECT p.cycle, p.created_at FROM director_plans p
   WHERE p.game_id = a.game_id AND p.created_at <= a.created_at
   ORDER BY p.created_at DESC LIMIT 1
) dp ON true
WHERE na.id = a.id;

ALTER TABLE narrative_arcs ALTER COLUMN created_cycle SET NOT NULL;

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

  -- Narrative arcs created after target cycle (#85: by cycle, like the other tables)
  DELETE FROM narrative_arcs WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
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

  -- Inventory before objects (FK constraint: inventory references objects)
  DELETE FROM inventory WHERE game_id = p_game_id AND acquired_cycle > p_target_cycle;

  -- Entities created after target cycle
  DELETE FROM characters WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM locations WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM organizations WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM objects WHERE game_id = p_game_id AND created_cycle > p_target_cycle;

  -- Narrative seeds from future cycles
  DELETE FROM narrative_seeds WHERE game_id = p_game_id AND cycle > p_target_cycle;

  -- Director plans from future cycles
  DELETE FROM director_plans WHERE game_id = p_game_id AND cycle > p_target_cycle;

  UPDATE games SET updated_at = now() WHERE id = p_game_id;
  RETURN QUERY SELECT v_deleted_facts, v_deleted_events, v_deleted_arcs, v_reverted_relations;
END;
$$;

-- migrate:down
-- Restore the definition from 20260419000000_fix_rollback_function.sql, then drop the column.
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

  -- Inventory before objects (FK constraint: inventory references objects)
  DELETE FROM inventory WHERE game_id = p_game_id AND acquired_cycle > p_target_cycle;

  -- Entities created after target cycle
  DELETE FROM characters WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM locations WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM organizations WHERE game_id = p_game_id AND created_cycle > p_target_cycle;
  DELETE FROM objects WHERE game_id = p_game_id AND created_cycle > p_target_cycle;

  -- Narrative seeds from future cycles
  DELETE FROM narrative_seeds WHERE game_id = p_game_id AND cycle > p_target_cycle;

  -- Director plans from future cycles
  DELETE FROM director_plans WHERE game_id = p_game_id AND cycle > p_target_cycle;

  UPDATE games SET updated_at = now() WHERE id = p_game_id;
  RETURN QUERY SELECT v_deleted_facts, v_deleted_events, v_deleted_arcs, v_reverted_relations;
END;
$$;

ALTER TABLE narrative_arcs DROP COLUMN created_cycle;
