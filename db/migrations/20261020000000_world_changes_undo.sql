-- migrate:up
-- #22: world_changes_undo, the inverse replay of turns' journal (#105). It walks the
-- world_changes rows of the given turns newest first and undoes each one: I deletes the
-- row, U puts back the old values of the changed keys, D re-inserts the old row.
--
-- Two things make a plain newest-first walk exact:
-- * Foreign keys are checked at the end of the replay, not row by row. The journal is not
--   in dependency order: an ON DELETE CASCADE / SET NULL journals the child rows after
--   their parent's D, so newest first re-inserts (or re-points) a child before its parent.
--   Every foreign key the replay can trip is therefore DEFERRABLE INITIALLY IMMEDIATE
--   (no change outside the replay): the ones of a journaled table (its inserts and updates)
--   and the NO ACTION ones to a journaled table (its deletes; CASCADE and SET NULL actions
--   are never deferred). The replay defers them all, then checks them all before
--   returning: referential integrity is still enforced, once.
-- * Side-effect triggers on journaled tables stay quiet while ldvelh.replay = 'on'. What
--   they wrote at the time (entity_registry rows, renames) is in the journal itself and is
--   replayed as such; firing them again would duplicate it (a re-inserted character would
--   register a second registry row before the journaled one comes back). The journal
--   triggers are quiet too: the replay runs with an empty ldvelh.turn_id.
--   Any new trigger on a journaled table must follow the same rule.

DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT c.conname, c.conrelid::regclass AS tbl
      FROM pg_constraint c
     WHERE c.contype = 'f' AND NOT c.condeferrable
       AND EXISTS (SELECT 1 FROM pg_trigger t
                    WHERE t.tgname = 'zz_journal_id'
                      AND (t.tgrelid = c.conrelid
                           OR (t.tgrelid = c.confrelid AND c.confdeltype = 'a')))
  LOOP
    EXECUTE format('ALTER TABLE %s ALTER CONSTRAINT %I DEFERRABLE INITIALLY IMMEDIATE',
                   r.tbl, r.conname);
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.register_entity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  -- Replay (#22): the registry row comes back from the journal.
  IF current_setting('ldvelh.replay', true) = 'on' THEN
    RETURN NEW;
  END IF;
  INSERT INTO entity_registry (game_id, entity_type, name)
  VALUES (NEW.game_id, TG_ARGV[0], NEW.name)
  ON CONFLICT (game_id, entity_type, name) DO NOTHING;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.update_entity_registry_name() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  -- Replay (#22): the registry name comes back from the journal.
  IF current_setting('ldvelh.replay', true) = 'on' THEN
    RETURN NEW;
  END IF;
  IF OLD.name != NEW.name THEN
    UPDATE entity_registry
    SET name = NEW.name
    WHERE game_id = NEW.game_id AND entity_type = TG_ARGV[0] AND name = OLD.name;
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.facts_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  -- Replay (#22): a location coming back restores the location_id SET NULL cleared.
  IF current_setting('ldvelh.replay', true) = 'on' THEN
    RETURN NEW;
  END IF;
  IF NEW.location_id IS NULL AND OLD.location_id IS NOT NULL
     AND (to_jsonb(NEW) - 'location_id') = (to_jsonb(OLD) - 'location_id') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Les faits sont immutables';
END;
$$;

-- Undo the journal of p_turn_ids, newest change first; returns the number of journal rows
-- replayed. Idempotent: a row already deleted, already present or already restored is a
-- no-op. Keys of old_row that are no longer columns of the table are ignored; on a D,
-- columns added since the row was journaled take their default.
CREATE FUNCTION public.world_changes_undo(p_turn_ids uuid[]) RETURNS integer
    LANGUAGE plpgsql
    SET ldvelh.turn_id = ''
    SET ldvelh.replay = 'on'
    AS $$
DECLARE
  r record;
  v_cols text;
  v_count integer := 0;
BEGIN
  SET CONSTRAINTS ALL DEFERRED;
  FOR r IN SELECT table_name, row_id, op, old_row FROM public.world_changes
            WHERE turn_id = ANY(p_turn_ids) ORDER BY id DESC
  LOOP
    v_count := v_count + 1;
    IF r.op = 'I' THEN
      EXECUTE format('DELETE FROM public.%I WHERE id = $1', r.table_name) USING r.row_id;
      CONTINUE;
    END IF;
    SELECT string_agg(quote_ident(c.column_name), ', ' ORDER BY c.ordinal_position)
      INTO v_cols
      FROM information_schema.columns c
     WHERE c.table_schema = 'public' AND c.table_name = r.table_name
       AND r.old_row ? c.column_name;
    IF v_cols IS NULL THEN
      CONTINUE;
    END IF;
    IF r.op = 'U' THEN
      EXECUTE format(
        'UPDATE public.%I SET (%s) = (SELECT %s FROM jsonb_populate_record(NULL::public.%I, $1)) '
        'WHERE id = $2', r.table_name, v_cols, v_cols, r.table_name)
        USING r.old_row, r.row_id;
    ELSE
      EXECUTE format(
        'INSERT INTO public.%I (%s) SELECT %s FROM jsonb_populate_record(NULL::public.%I, $1) '
        'ON CONFLICT (id) DO NOTHING', r.table_name, v_cols, v_cols, r.table_name)
        USING r.old_row;
    END IF;
  END LOOP;
  -- Check every deferred foreign key now: a broken reference fails the replay here.
  SET CONSTRAINTS ALL IMMEDIATE;
  RETURN v_count;
END;
$$;

-- migrate:down
DROP FUNCTION public.world_changes_undo(uuid[]);

CREATE OR REPLACE FUNCTION public.facts_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.location_id IS NULL AND OLD.location_id IS NOT NULL
     AND (to_jsonb(NEW) - 'location_id') = (to_jsonb(OLD) - 'location_id') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Les faits sont immutables';
END;
$$;

CREATE OR REPLACE FUNCTION public.update_entity_registry_name() RETURNS trigger
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

CREATE OR REPLACE FUNCTION public.register_entity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO entity_registry (game_id, entity_type, name)
  VALUES (NEW.game_id, TG_ARGV[0], NEW.name)
  ON CONFLICT (game_id, entity_type, name) DO NOTHING;
  RETURN NEW;
END;
$$;

-- No foreign key was deferrable before the up.
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT conname, conrelid::regclass AS tbl FROM pg_constraint
            WHERE contype = 'f' AND condeferrable
  LOOP
    EXECUTE format('ALTER TABLE %s ALTER CONSTRAINT %I NOT DEFERRABLE', r.tbl, r.conname);
  END LOOP;
END;
$$;
