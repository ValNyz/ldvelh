-- migrate:up
-- #105: turn journal. A turn groups the world writes of one narration turn; every row a
-- turn inserts, updates or deletes in a world table is recorded in world_changes by the
-- generic zz_journal_* triggers, so a rollback can undo exactly that turn's writes.
-- The triggers only write when the transaction set ldvelh.turn_id (backend repos/uow.py):
-- anything outside a turn is not journaled.
CREATE TABLE public.turns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL REFERENCES public.games(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'committed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    committed_at timestamptz
);
CREATE INDEX turns_game_created_idx ON public.turns (game_id, created_at);

CREATE TABLE public.world_changes (
    id bigserial PRIMARY KEY,
    turn_id uuid NOT NULL REFERENCES public.turns(id) ON DELETE CASCADE,
    table_name text NOT NULL,
    row_id uuid NOT NULL,
    op char(1) NOT NULL CHECK (op IN ('I', 'U', 'D')),
    old_row jsonb,
    new_row jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX world_changes_turn_idx ON public.world_changes (turn_id, id);

-- Nullable: legacy rows predate turns. Messages and rolls outlive a deleted turn.
ALTER TABLE public.messages
    ADD COLUMN turn_id uuid REFERENCES public.turns(id) ON DELETE SET NULL;
ALTER TABLE public.mechanic_rolls
    ADD COLUMN turn_id uuid REFERENCES public.turns(id) ON DELETE SET NULL;
ALTER TABLE public.extraction_logs
    ADD COLUMN turn_id uuid REFERENCES public.turns(id) ON DELETE CASCADE;
-- Deleting a turn runs the FK action on each referencing table: index the references
-- (partial, legacy rows have none).
CREATE INDEX messages_turn_idx ON public.messages (turn_id) WHERE turn_id IS NOT NULL;
CREATE INDEX mechanic_rolls_turn_idx
    ON public.mechanic_rolls (turn_id) WHERE turn_id IS NOT NULL;
CREATE INDEX extraction_logs_turn_idx
    ON public.extraction_logs (turn_id) WHERE turn_id IS NOT NULL;

-- One world_changes row per written row. U keeps only the changed keys (old and new).
-- AFTER triggers named zz_* fire last on their row (trigger names sort byte-wise): rows
-- written by the entity_registry triggers are journaled before the entity. Rows deleted by
-- an ON DELETE CASCADE come after their parent: RI runs the child deletes without firing
-- their AFTER triggers on the spot, so they queue behind the parent's zz_journal_id.
CREATE FUNCTION public.ldvelh_journal_row() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  v_turn uuid := nullif(current_setting('ldvelh.turn_id', true), '')::uuid;
  v_old jsonb;
  v_new jsonb;
BEGIN
  IF v_turn IS NULL THEN
    RETURN NULL;
  END IF;
  IF TG_OP <> 'INSERT' THEN v_old := to_jsonb(OLD); END IF;
  IF TG_OP <> 'DELETE' THEN v_new := to_jsonb(NEW); END IF;
  IF TG_OP = 'UPDATE' THEN
    SELECT jsonb_object_agg(o.key, o.value), jsonb_object_agg(o.key, v_new -> o.key)
      INTO v_old, v_new
      FROM jsonb_each(v_old) o
     WHERE o.value IS DISTINCT FROM v_new -> o.key;
  END IF;
  INSERT INTO public.world_changes (turn_id, table_name, row_id, op, old_row, new_row)
  VALUES (v_turn, TG_TABLE_NAME, (COALESCE(to_jsonb(NEW), to_jsonb(OLD)) ->> 'id')::uuid,
          left(TG_OP, 1), v_old, v_new);
  RETURN NULL;
END;
$$;

-- Attach the journal to a table; p_update_of restricts the U trigger to those columns.
CREATE FUNCTION public.ldvelh_journal(p_table text, p_update_of text DEFAULT NULL) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
  EXECUTE format(
    'CREATE TRIGGER zz_journal_id AFTER INSERT OR DELETE ON public.%I '
    'FOR EACH ROW EXECUTE FUNCTION public.ldvelh_journal_row()', p_table);
  EXECUTE format(
    'CREATE TRIGGER zz_journal_u AFTER UPDATE %s ON public.%I FOR EACH ROW '
    'WHEN (to_jsonb(OLD) IS DISTINCT FROM to_jsonb(NEW)) '
    'EXECUTE FUNCTION public.ldvelh_journal_row()',
    CASE WHEN p_update_of IS NULL THEN '' ELSE 'OF ' || p_update_of END, p_table);
END;
$$;

SELECT public.ldvelh_journal(t) FROM unnest(ARRAY[
    'characters', 'locations', 'organizations', 'objects', 'facts', 'fact_participants',
    'relations', 'inventory', 'chronology', 'chronology_participants', 'events',
    'event_participants', 'narrative_seeds', 'narrative_arcs', 'arc_participants',
    'director_plans', 'skills', 'skills_fate', 'skills_d6', 'traits_narrative', 'aspects_fate',
    'character_fate', 'character_d6', 'character_narrative', 'npc_fate', 'npc_d6',
    'npc_narrative', 'object_fate', 'object_d6', 'object_narrative', 'protagonists',
    'companions', 'entity_registry', 'mechanic_rolls'
]) AS t;
-- games: only the world columns a turn changes (not name, active, settings...).
SELECT public.ldvelh_journal('games', 'current_cycle, "current_date", "current_time", '
    'current_location_id, detail_requests, last_director_time, last_extraction_time, '
    'engine_locked');

-- migrate:down
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT tgname, tgrelid::regclass AS tbl FROM pg_trigger
           WHERE tgname IN ('zz_journal_id', 'zz_journal_u') AND NOT tgisinternal
  LOOP
    EXECUTE format('DROP TRIGGER %I ON %s', r.tgname, r.tbl);
  END LOOP;
END;
$$;
DROP FUNCTION public.ldvelh_journal(text, text);
DROP FUNCTION public.ldvelh_journal_row();
DROP INDEX public.extraction_logs_turn_idx, public.mechanic_rolls_turn_idx,
    public.messages_turn_idx;
ALTER TABLE public.extraction_logs DROP COLUMN turn_id;
ALTER TABLE public.mechanic_rolls DROP COLUMN turn_id;
ALTER TABLE public.messages DROP COLUMN turn_id;
DROP TABLE public.world_changes, public.turns;
