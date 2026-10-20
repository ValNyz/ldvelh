-- migrate:up
-- Internal label suffix for every entity type (#153, ruling R14). A character already had
-- one (label_suffix, ruling R9): its label (name, registry, normalised uniqueness) is its
-- true name or descriptor, then " (<suffix>)", and the player never reads it. The other
-- types get the same column: their domain name stays what the player reads, the registry
-- label is that name followed by the suffix. Homonyms share the bare name as an alias (an
-- ambiguous reference), each keeps its suffixed label (an internal one). The identity
-- migration gave the homonyms of those types a displayed suffix (« Nom (2) » in their
-- name): it becomes the internal one here.

ALTER TABLE public.locations ADD COLUMN label_suffix text;
ALTER TABLE public.organizations ADD COLUMN label_suffix text;
ALTER TABLE public.objects ADD COLUMN label_suffix text;
ALTER TABLE public.protagonists ADD COLUMN label_suffix text;
ALTER TABLE public.companions ADD COLUMN label_suffix text;

-- The registry label of a domain row: a character's name (its trigger already appends the
-- suffix to it), the name of another entity followed by " (<label_suffix>)" when it has one.
CREATE FUNCTION public.identity_label(p_type text, p_row jsonb) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
    SELECT CASE WHEN p_type = 'character' THEN p_row ->> 'name'
                ELSE (p_row ->> 'name') || COALESCE(' (' || (p_row ->> 'label_suffix') || ')', '')
           END
$$;

-- The alias of each current name of an entity, made by the triggers (source 'system'): a
-- character's true name (known when the PC knows it) and descriptor (known), another
-- entity's name (its bare label, known), plus the suffixed label of any entity that has a
-- label_suffix (internal lookup). True names, descriptors and bare names stay suffix-free:
-- homonyms share them. Invariant: every entity has an alias of its current name_norm.
-- The services add the derived aliases (short forms, titles).
CREATE OR REPLACE FUNCTION public.identity_name_aliases(p_type text, p_row jsonb, p_turn uuid)
        RETURNS void
    LANGUAGE sql
    AS $$
    INSERT INTO public.entity_aliases
           (game_id, entity_id, entity_type, alias, kind, known, source, turn_id)
    SELECT (p_row ->> 'game_id')::uuid, (p_row ->> 'id')::uuid, p_type, forms.alias, forms.kind,
           forms.known, 'system', p_turn
      FROM (VALUES
              (CASE WHEN p_type = 'character' THEN p_row ->> 'true_name'
                    ELSE p_row ->> 'name' END,
               CASE WHEN p_type = 'character' THEN 'true_name' ELSE 'label' END,
               p_type <> 'character'
                   OR COALESCE((p_row ->> 'known_by_protagonist')::boolean, false)),
              (CASE WHEN p_type = 'character' THEN p_row ->> 'descriptor' END,
               'descriptor', true),
              (CASE WHEN p_row ->> 'label_suffix' IS NOT NULL
                    THEN public.identity_label(p_type, p_row) END,
               'label',
               p_type <> 'character' OR p_row ->> 'true_name' IS NULL
                   OR COALESCE((p_row ->> 'known_by_protagonist')::boolean, false))
           ) AS forms (alias, kind, known)
     WHERE forms.alias IS NOT NULL
    ON CONFLICT DO NOTHING
$$;

-- BEFORE INSERT on a domain table: its registry row, at the same id and with its label,
-- with the turn that created it, and the aliases of its names.
CREATE OR REPLACE FUNCTION public.identity_register() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_turn uuid := nullif(current_setting('ldvelh.turn_id', true), '')::uuid;
    v_row jsonb := to_jsonb(NEW);
    v_id uuid;
BEGIN
    IF current_setting('ldvelh.replay', true) = 'on' THEN
        RETURN NEW;
    END IF;
    INSERT INTO public.entity_registry (id, game_id, entity_type, name, created_turn_id)
    VALUES (NEW.id, NEW.game_id, TG_ARGV[0], public.identity_label(TG_ARGV[0], v_row), v_turn)
    ON CONFLICT (id) DO NOTHING
    RETURNING id INTO v_id;
    IF v_id IS NOT NULL THEN
        PERFORM public.identity_name_aliases(TG_ARGV[0], v_row, v_turn);
    END IF;
    RETURN NEW;
END $$;

-- AFTER UPDATE of a name or a label suffix: the registry follows the label, by id (a
-- normalised collision with another entity of the type raises, never a silent second
-- entry); a label or true name replaced becomes a former name (neither the bare name nor
-- the suffixed label of an entity is), and the new names get their aliases.
CREATE OR REPLACE FUNCTION public.identity_sync_name() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_type text := TG_ARGV[0];
    v_turn uuid := nullif(current_setting('ldvelh.turn_id', true), '')::uuid;
    v_row jsonb := to_jsonb(NEW);
    v_kind text := CASE WHEN TG_ARGV[0] = 'character' THEN 'true_name' ELSE 'label' END;
    v_label text := public.identity_label(TG_ARGV[0], to_jsonb(NEW));
    v_label_norm text;
    v_current text;
    v_norm text;
BEGIN
    IF current_setting('ldvelh.replay', true) = 'on' THEN
        RETURN NEW;
    END IF;
    UPDATE public.entity_registry SET name = v_label
     WHERE id = NEW.id AND name IS DISTINCT FROM v_label;
    v_label_norm := public.ldvelh_norm_for_game(NEW.game_id, v_label);
    v_current := v_row ->> CASE WHEN v_type = 'character' THEN 'true_name' ELSE 'name' END;
    IF v_current IS NOT NULL THEN
        v_norm := public.ldvelh_norm_for_game(NEW.game_id, v_current);
    END IF;
    UPDATE public.entity_aliases AS al SET kind = 'former_name'
     WHERE al.entity_id = NEW.id AND al.kind = v_kind
       AND (v_norm IS NULL OR al.alias_norm <> v_norm)
       AND (v_type = 'character' OR al.alias_norm <> v_label_norm);
    IF v_type = 'character' THEN
        -- A suffixed label no longer the character's label.
        UPDATE public.entity_aliases AS al SET kind = 'former_name'
         WHERE al.entity_id = NEW.id AND al.kind = 'label' AND al.alias_norm <> v_label_norm;
    END IF;
    PERFORM public.identity_name_aliases(v_type, v_row, v_turn);
    RETURN NEW;
END $$;

DROP TRIGGER sync_registry_location ON public.locations;
DROP TRIGGER sync_registry_organization ON public.organizations;
DROP TRIGGER sync_registry_object ON public.objects;
DROP TRIGGER sync_registry_protagonist ON public.protagonists;
DROP TRIGGER sync_registry_companion ON public.companions;
CREATE TRIGGER sync_registry_location AFTER UPDATE OF name, label_suffix ON public.locations
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('location');
CREATE TRIGGER sync_registry_organization
    AFTER UPDATE OF name, label_suffix ON public.organizations
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('organization');
CREATE TRIGGER sync_registry_object AFTER UPDATE OF name, label_suffix ON public.objects
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('object');
CREATE TRIGGER sync_registry_protagonist
    AFTER UPDATE OF name, label_suffix ON public.protagonists
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('protagonist');
CREATE TRIGGER sync_registry_companion AFTER UPDATE OF name, label_suffix ON public.companions
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('companion');

-- What the player may read for an entity: a character's true name only when the PC knows
-- it, else its descriptor, else the pack's label for an unnamed character; the domain name
-- of any other entity (its label without the internal suffix). Merges followed.
CREATE OR REPLACE FUNCTION public.display_for_player(p_entity_id uuid) RETURNS text
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
    v_id uuid := public.entity_follow_merge(p_entity_id);
    v_game uuid;
    v_type text;
    v_name text;
    v_true_name text;
    v_descriptor text;
    v_known boolean;
BEGIN
    SELECT er.game_id, er.entity_type, er.name INTO v_game, v_type, v_name
      FROM public.entity_registry AS er WHERE er.id = v_id;
    IF v_type IS NULL THEN
        RETURN NULL;
    END IF;
    IF v_type <> 'character' THEN
        RETURN COALESCE(public.identity_domain_row(v_type, v_id) ->> 'name', v_name);
    END IF;
    SELECT ch.true_name, ch.descriptor, ch.known_by_protagonist
      INTO v_true_name, v_descriptor, v_known
      FROM public.characters AS ch WHERE ch.id = v_id;
    IF v_known AND v_true_name IS NOT NULL THEN
        RETURN v_true_name;
    END IF;
    RETURN COALESCE(v_descriptor,
                    public.ldvelh_lang_params(v_game) ->> 'unknown_character_label');
END $$;

-- The steps of §5.2 that compare normalised names, for one game with a language: section 3
-- runs them for the games that have one, scripts/identity_backfill.py for the others once
-- it gave them one. Idempotent; returns what it changed, by step:
-- a. alias norms: the forms of an entity that normalise alike are kept once (the first by
--    kind: true name, label, descriptor, then derived forms), the others get their norm;
-- b. orphans (registry rows without domain row, step 2): their edges go to the one live
--    entity of the type whose label or alias has the orphan's norm (identity_merge_edges),
--    then the orphan is deleted; without such an entity its edges go with it (counted)
--    and its id leaves the director's commitments. The journal follows, so that undoing a
--    turn played before the migration still commits: the orphan's id becomes the entity's
--    in the rows of its edges and of the alias rows 3.3 added for it, or those rows go
--    when the edges went; its own registry rows go (an undo must not bring back a row the
--    model no longer has);
-- c. normalised collisions (step 6): of the live entities of a type sharing a norm, the
--    oldest keeps its name, the others get the internal label_suffix " (2)", " (3)"...
--    (never shown: rulings R9, R14);
-- d. registry norms, the name_norm of the registry's journal rows included (I7);
-- e. mentions (step 5): each narrator_context span [start, end, name, type] whose (name,
--    type) find_entity resolves to one entity becomes an entity_mentions row
--    ('deterministic'); the others are dropped and counted. narrator_context is kept.
CREATE OR REPLACE FUNCTION public.identity_legacy_normalise(p_game uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_counts jsonb := '{}'::jsonb;
    v_count integer;
    v_dropped integer;
    v_orphan record;
    v_clash record;
    v_norm text;
    v_targets uuid[];
    v_repointed integer := 0;
    v_deleted integer := 0;
    v_suffixed integer := 0;
    v_suffix integer;
    v_journal_moved integer := 0;
    v_journal_dropped integer := 0;
    v_commitments integer := 0;
    v_edge_tables text[] := ARRAY['relations', 'fact_participants', 'arc_participants',
                                  'chronology_participants', 'event_participants',
                                  'inventory', 'narrative_arcs', 'entity_aliases'];
BEGIN
    -- a.
    WITH ranked AS (
        SELECT al.id, al.alias_norm IS NULL AS missing,
               row_number() OVER (
                   PARTITION BY al.entity_id,
                                COALESCE(al.alias_norm,
                                         public.ldvelh_norm_for_game(p_game, al.alias))
                   ORDER BY al.alias_norm IS NULL,
                            array_position(ARRAY['true_name', 'label', 'descriptor', 'title',
                                                 'short', 'nickname', 'former_name'],
                                           al.kind),
                            al.created_at, al.id) AS rank
          FROM public.entity_aliases AS al
         WHERE al.game_id = p_game)
    DELETE FROM public.entity_aliases AS al USING ranked
     WHERE al.id = ranked.id AND ranked.missing AND ranked.rank > 1;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_counts := v_counts || jsonb_build_object('aliases_deduplicated', v_count);
    UPDATE public.entity_aliases AS al
       SET alias_norm = public.ldvelh_norm_for_game(p_game, al.alias)
     WHERE al.game_id = p_game AND al.alias_norm IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_counts := v_counts || jsonb_build_object('alias_norms', v_count);

    -- b.
    FOR v_orphan IN
        SELECT er.id, er.entity_type, er.name FROM public.entity_registry AS er
         WHERE er.game_id = p_game AND er.merged_into IS NULL
           AND public.identity_domain_row(er.entity_type, er.id) IS NULL
    LOOP
        v_norm := public.ldvelh_norm_for_game(p_game, v_orphan.name);
        SELECT array_agg(DISTINCT cand.id) INTO v_targets
          FROM (SELECT er.id FROM public.entity_registry AS er
                 WHERE er.game_id = p_game AND er.entity_type = v_orphan.entity_type
                   AND er.merged_into IS NULL
                   AND COALESCE(er.name_norm,
                                public.ldvelh_norm_for_game(p_game, er.name)) = v_norm
                UNION
                SELECT al.entity_id FROM public.entity_aliases AS al
                 WHERE al.game_id = p_game AND al.entity_type = v_orphan.entity_type
                   AND al.alias_norm = v_norm) AS cand
         WHERE cand.id <> v_orphan.id
           AND public.identity_domain_row(v_orphan.entity_type, cand.id) IS NOT NULL;
        IF cardinality(v_targets) = 1 THEN
            PERFORM public.identity_merge_edges(v_targets[1], v_orphan.id,
                                                v_orphan.entity_type);
            UPDATE public.world_changes AS wc
               SET old_row = replace(wc.old_row::text, v_orphan.id::text,
                                     v_targets[1]::text)::jsonb,
                   new_row = replace(wc.new_row::text, v_orphan.id::text,
                                     v_targets[1]::text)::jsonb
              FROM public.turns AS tn
             WHERE tn.id = wc.turn_id AND tn.game_id = p_game
               AND wc.table_name = ANY (v_edge_tables || 'director_commitments'::text)
               AND concat(wc.old_row::text, wc.new_row::text) LIKE '%' || v_orphan.id || '%';
            GET DIAGNOSTICS v_count = ROW_COUNT;
            v_journal_moved := v_journal_moved + v_count;
            v_repointed := v_repointed + 1;
        ELSE
            DELETE FROM public.world_changes AS wc USING public.turns AS tn
             WHERE tn.id = wc.turn_id AND tn.game_id = p_game
               AND wc.table_name = ANY (v_edge_tables)
               AND concat(wc.old_row::text, wc.new_row::text) LIKE '%' || v_orphan.id || '%';
            GET DIAGNOSTICS v_count = ROW_COUNT;
            v_journal_dropped := v_journal_dropped + v_count;
            UPDATE public.world_changes AS wc
               SET old_row = public.identity_drop_related(wc.old_row, v_orphan.id),
                   new_row = public.identity_drop_related(wc.new_row, v_orphan.id)
              FROM public.turns AS tn
             WHERE tn.id = wc.turn_id AND tn.game_id = p_game
               AND wc.table_name = 'director_commitments'
               AND concat(wc.old_row::text, wc.new_row::text) LIKE '%' || v_orphan.id || '%';
            UPDATE public.director_commitments AS dc
               SET related_entities = array_remove(dc.related_entities, v_orphan.id)
             WHERE dc.game_id = p_game AND v_orphan.id = ANY (dc.related_entities);
            GET DIAGNOSTICS v_count = ROW_COUNT;
            v_commitments := v_commitments + v_count;
            v_deleted := v_deleted + 1;
        END IF;
        DELETE FROM public.world_changes AS wc USING public.turns AS tn
         WHERE tn.id = wc.turn_id AND tn.game_id = p_game
           AND wc.table_name = 'entity_registry' AND wc.row_id = v_orphan.id;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_journal_dropped := v_journal_dropped + v_count;
        DELETE FROM public.entity_registry WHERE id = v_orphan.id;
    END LOOP;
    v_counts := v_counts || jsonb_build_object(
        'orphans_repointed', v_repointed, 'orphans_deleted', v_deleted,
        'orphan_journal_rows_repointed', v_journal_moved,
        'orphan_journal_rows_dropped', v_journal_dropped,
        'orphan_commitments_purged', v_commitments);

    -- c.
    FOR v_clash IN
        SELECT ranked.id, ranked.entity_type, ranked.name, ranked.rank FROM (
            SELECT er.id, er.entity_type, er.name,
                   row_number() OVER (
                       PARTITION BY er.entity_type,
                                    COALESCE(er.name_norm,
                                             public.ldvelh_norm_for_game(p_game, er.name))
                       ORDER BY (public.identity_domain_row(er.entity_type, er.id)
                                 ->> 'created_at')::timestamptz,
                                er.name COLLATE "C", er.id) AS rank
              FROM public.entity_registry AS er
             WHERE er.game_id = p_game AND er.merged_into IS NULL) AS ranked
         WHERE ranked.rank > 1
         ORDER BY ranked.entity_type, ranked.rank, ranked.id
    LOOP
        v_suffix := v_clash.rank;
        WHILE EXISTS (
            SELECT 1 FROM public.entity_registry AS er
             WHERE er.game_id = p_game AND er.entity_type = v_clash.entity_type
               AND er.merged_into IS NULL
               AND COALESCE(er.name_norm, public.ldvelh_norm_for_game(p_game, er.name))
                   = public.ldvelh_norm_for_game(p_game,
                                                 v_clash.name || ' (' || v_suffix || ')'))
        LOOP
            v_suffix := v_suffix + 1;
        END LOOP;
        EXECUTE 'UPDATE ' || public.identity_domain_table(v_clash.entity_type)::text
                || ' SET label_suffix = $2 WHERE id = $1'
          USING v_clash.id, v_suffix::text;
        v_suffixed := v_suffixed + 1;
    END LOOP;
    v_counts := v_counts || jsonb_build_object('collisions_suffixed', v_suffixed);

    -- d.
    UPDATE public.entity_registry AS er
       SET name_norm = public.ldvelh_norm_for_game(p_game, er.name)
     WHERE er.game_id = p_game AND er.name_norm IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_counts := v_counts || jsonb_build_object('registry_norms', v_count);
    UPDATE public.world_changes AS wc
       SET old_row = CASE WHEN wc.old_row ? 'name' AND NOT wc.old_row ? 'name_norm'
                          THEN wc.old_row || jsonb_build_object('name_norm',
                                   public.ldvelh_norm_for_game(p_game, wc.old_row ->> 'name'))
                          ELSE wc.old_row END,
           new_row = CASE WHEN wc.new_row ? 'name' AND NOT wc.new_row ? 'name_norm'
                          THEN wc.new_row || jsonb_build_object('name_norm',
                                   public.ldvelh_norm_for_game(p_game, wc.new_row ->> 'name'))
                          ELSE wc.new_row END
      FROM public.turns AS tn
     WHERE tn.id = wc.turn_id AND tn.game_id = p_game AND wc.table_name = 'entity_registry'
       AND ((wc.old_row ? 'name' AND NOT wc.old_row ? 'name_norm')
            OR (wc.new_row ? 'name' AND NOT wc.new_row ? 'name_norm'));
    -- The alias rows 3.3 adds to the journal of an entity a turn deleted.
    UPDATE public.world_changes AS wc
       SET old_row = wc.old_row || jsonb_build_object('alias_norm',
                         public.ldvelh_norm_for_game(p_game, wc.old_row ->> 'alias'))
      FROM public.turns AS tn
     WHERE tn.id = wc.turn_id AND tn.game_id = p_game AND wc.table_name = 'entity_aliases'
       AND wc.old_row ? 'alias' AND (wc.old_row ->> 'alias_norm') IS NULL;
    PERFORM public.identity_journal_alias_conflicts(p_game);

    -- e.
    WITH spans AS (
        SELECT mg.id AS message_id, mg.turn_id, mg.content, span.value AS entry
          FROM public.messages AS mg
         CROSS JOIN LATERAL jsonb_array_elements(
                CASE WHEN jsonb_typeof(mg.narrator_context) = 'array'
                     THEN mg.narrator_context ELSE '[]'::jsonb END) AS span
         WHERE mg.game_id = p_game
           AND jsonb_typeof(span.value) = 'array' AND jsonb_array_length(span.value) >= 4
           AND (span.value ->> 0) ~ '^[0-9]+([.]0+)?$'
           AND (span.value ->> 1) ~ '^[0-9]+([.]0+)?$'
           AND jsonb_typeof(span.value -> 2) = 'string'
           AND jsonb_typeof(span.value -> 3) = 'string'),
    resolved AS (
        SELECT sp.message_id, sp.turn_id, sp.content, sp.entry ->> 2 AS name,
               (sp.entry ->> 0)::numeric::integer AS start_pos,
               (sp.entry ->> 1)::numeric::integer AS end_pos,
               public.identity_find_span_entity(p_game, sp.entry ->> 2, sp.entry ->> 3)
                   AS entity_id
          FROM spans AS sp),
    inserted AS (
        INSERT INTO public.entity_mentions
               (game_id, message_id, turn_id, start_pos, end_pos, surface, entity_id, decision)
        SELECT p_game, rs.message_id, rs.turn_id, rs.start_pos, rs.end_pos,
               COALESCE(NULLIF(substr(rs.content, rs.start_pos + 1, rs.end_pos - rs.start_pos),
                               ''), rs.name),
               rs.entity_id, 'deterministic'
          FROM resolved AS rs
         WHERE rs.entity_id IS NOT NULL AND rs.start_pos >= 0 AND rs.end_pos > rs.start_pos
        ON CONFLICT (message_id, start_pos, end_pos) DO NOTHING
        RETURNING 1)
    SELECT (SELECT count(*) FROM inserted),
           (SELECT count(*) FROM resolved WHERE resolved.entity_id IS NULL)
      INTO v_count, v_dropped;
    RETURN v_counts || jsonb_build_object('mentions', v_count, 'mentions_dropped', v_dropped);
END $$;

-- The displayed suffixes the identity migration wrote (identity_legacy_normalise step c,
-- games that had a language): a name ending with " (<number>)" whose bare form is the label
-- of another live entity of its type becomes that bare name with the internal suffix
-- <number>; its registry label does not change. The bare name, a former name since that
-- step, is the entity's label alias again. A game without language is not normalised yet:
-- the backfill runs the step above on it.
DO $$
DECLARE
    v_type text;
    v_table regclass;
BEGIN
    FOREACH v_type IN ARRAY ARRAY['location', 'organization', 'object', 'protagonist',
                                  'companion'] LOOP
        v_table := public.identity_domain_table(v_type);
        EXECUTE format($sql$
            WITH suffixed AS (
                SELECT dom.id, split.parts[1] AS base, split.parts[2] AS suffix
                  FROM %1$s AS dom
                  JOIN public.games AS gm ON gm.id = dom.game_id
                 CROSS JOIN LATERAL (
                       SELECT regexp_match(dom.name, '^(.+) [(]([0-9]+)[)]$') AS parts
                 ) AS split
                 WHERE gm.language IS NOT NULL AND dom.label_suffix IS NULL
                   AND split.parts IS NOT NULL
                   AND EXISTS (
                       SELECT 1 FROM public.entity_registry AS er
                        WHERE er.game_id = dom.game_id AND er.entity_type = %2$L
                          AND er.merged_into IS NULL AND er.id <> dom.id
                          AND er.name_norm
                              = public.ldvelh_norm_for_game(dom.game_id, split.parts[1])))
            UPDATE %1$s AS dom SET name = suffixed.base, label_suffix = suffixed.suffix
              FROM suffixed WHERE dom.id = suffixed.id
            $sql$, v_table, v_type);
        EXECUTE format($sql$
            UPDATE public.entity_aliases AS al SET kind = 'label'
              FROM %1$s AS dom
             WHERE al.entity_id = dom.id AND dom.label_suffix IS NOT NULL
               AND al.kind = 'former_name'
               AND al.alias_norm = public.ldvelh_norm_for_game(dom.game_id, dom.name)
            $sql$, v_table);
    END LOOP;
END $$;


-- migrate:down
-- The PR 1a functions and triggers come back first, then the internal suffixes of the
-- types other than characters are displayed again (in their name, as the identity
-- migration wrote them) before their column goes.
-- The alias of each current name of an entity, made by the triggers (source 'system'): a
-- character's true name (known when the PC knows it) and descriptor (known), plus its
-- suffixed label when it has a label_suffix (internal lookup); another entity's label (its
-- name). True names and descriptors stay suffix-free: homonyms share them. Invariant:
-- every entity has an alias of its current name_norm.
-- The services add the derived aliases (short forms, titles).
CREATE OR REPLACE FUNCTION public.identity_name_aliases(p_type text, p_row jsonb, p_turn uuid)
        RETURNS void
    LANGUAGE sql
    AS $$
    INSERT INTO public.entity_aliases
           (game_id, entity_id, entity_type, alias, kind, known, source, turn_id)
    SELECT (p_row ->> 'game_id')::uuid, (p_row ->> 'id')::uuid, p_type, forms.alias, forms.kind,
           forms.known, 'system', p_turn
      FROM (VALUES
              (CASE WHEN p_type = 'character' THEN p_row ->> 'true_name'
                    ELSE p_row ->> 'name' END,
               CASE WHEN p_type = 'character' THEN 'true_name' ELSE 'label' END,
               p_type <> 'character'
                   OR COALESCE((p_row ->> 'known_by_protagonist')::boolean, false)),
              (CASE WHEN p_type = 'character' THEN p_row ->> 'descriptor' END,
               'descriptor', true),
              (CASE WHEN p_type = 'character' AND p_row ->> 'label_suffix' IS NOT NULL
                    THEN p_row ->> 'name' END,
               'label',
               p_row ->> 'true_name' IS NULL
                   OR COALESCE((p_row ->> 'known_by_protagonist')::boolean, false))
           ) AS forms (alias, kind, known)
     WHERE forms.alias IS NOT NULL
    ON CONFLICT DO NOTHING
$$;

-- BEFORE INSERT on a domain table: its registry row, at the same id, with the turn that
-- created it, and the aliases of its names.
CREATE OR REPLACE FUNCTION public.identity_register() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_turn uuid := nullif(current_setting('ldvelh.turn_id', true), '')::uuid;
    v_id uuid;
BEGIN
    IF current_setting('ldvelh.replay', true) = 'on' THEN
        RETURN NEW;
    END IF;
    INSERT INTO public.entity_registry (id, game_id, entity_type, name, created_turn_id)
    VALUES (NEW.id, NEW.game_id, TG_ARGV[0], NEW.name, v_turn)
    ON CONFLICT (id) DO NOTHING
    RETURNING id INTO v_id;
    IF v_id IS NOT NULL THEN
        PERFORM public.identity_name_aliases(TG_ARGV[0], to_jsonb(NEW), v_turn);
    END IF;
    RETURN NEW;
END $$;

-- AFTER UPDATE of a name: the registry follows the domain name, by id (a normalised
-- collision with another entity of the type raises, never a silent second entry); a label
-- or true name replaced becomes a former name, and the new names get their aliases.
CREATE OR REPLACE FUNCTION public.identity_sync_name() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_type text := TG_ARGV[0];
    v_turn uuid := nullif(current_setting('ldvelh.turn_id', true), '')::uuid;
    v_row jsonb := to_jsonb(NEW);
    v_kind text := CASE WHEN TG_ARGV[0] = 'character' THEN 'true_name' ELSE 'label' END;
    v_current text;
    v_norm text;
BEGIN
    IF current_setting('ldvelh.replay', true) = 'on' THEN
        RETURN NEW;
    END IF;
    IF NEW.name IS DISTINCT FROM OLD.name THEN
        UPDATE public.entity_registry SET name = NEW.name WHERE id = NEW.id;
    END IF;
    v_current := v_row ->> CASE WHEN v_type = 'character' THEN 'true_name' ELSE 'name' END;
    IF v_current IS NOT NULL THEN
        v_norm := public.ldvelh_norm_for_game(NEW.game_id, v_current);
    END IF;
    UPDATE public.entity_aliases AS al SET kind = 'former_name'
     WHERE al.entity_id = NEW.id AND al.kind = v_kind
       AND (v_norm IS NULL OR al.alias_norm <> v_norm);
    IF v_type = 'character' THEN
        -- A suffixed label no longer the character's label.
        UPDATE public.entity_aliases AS al SET kind = 'former_name'
         WHERE al.entity_id = NEW.id AND al.kind = 'label'
           AND al.alias_norm <> public.ldvelh_norm_for_game(NEW.game_id, NEW.name);
    END IF;
    PERFORM public.identity_name_aliases(v_type, v_row, v_turn);
    RETURN NEW;
END $$;

-- What the player may read for an entity: a character's true name only when the PC knows
-- it, else its descriptor, else the pack's label for an unnamed character; the label of
-- any other entity. Merges followed.
CREATE OR REPLACE FUNCTION public.display_for_player(p_entity_id uuid) RETURNS text
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
    v_id uuid := public.entity_follow_merge(p_entity_id);
    v_game uuid;
    v_type text;
    v_name text;
    v_true_name text;
    v_descriptor text;
    v_known boolean;
BEGIN
    SELECT er.game_id, er.entity_type, er.name INTO v_game, v_type, v_name
      FROM public.entity_registry AS er WHERE er.id = v_id;
    IF v_type IS NULL THEN
        RETURN NULL;
    END IF;
    IF v_type <> 'character' THEN
        RETURN v_name;
    END IF;
    SELECT ch.true_name, ch.descriptor, ch.known_by_protagonist
      INTO v_true_name, v_descriptor, v_known
      FROM public.characters AS ch WHERE ch.id = v_id;
    IF v_known AND v_true_name IS NOT NULL THEN
        RETURN v_true_name;
    END IF;
    RETURN COALESCE(v_descriptor,
                    public.ldvelh_lang_params(v_game) ->> 'unknown_character_label');
END $$;

-- The steps of §5.2 that compare normalised names, for one game with a language: section 3
-- runs them for the games that have one, scripts/identity_backfill.py for the others once
-- it gave them one. Idempotent; returns what it changed, by step:
-- a. alias norms: the forms of an entity that normalise alike are kept once (the first by
--    kind: true name, label, descriptor, then derived forms), the others get their norm;
-- b. orphans (registry rows without domain row, step 2): their edges go to the one live
--    entity of the type whose label or alias has the orphan's norm (identity_merge_edges),
--    then the orphan is deleted; without such an entity its edges go with it (counted)
--    and its id leaves the director's commitments. The journal follows, so that undoing a
--    turn played before the migration still commits: the orphan's id becomes the entity's
--    in the rows of its edges and of the alias rows 3.3 added for it, or those rows go
--    when the edges went; its own registry rows go (an undo must not bring back a row the
--    model no longer has);
-- c. normalised collisions (step 6): of the live entities of a type sharing a norm, the
--    oldest keeps its name, the others get the suffix " (2)", " (3)"...: a character in its
--    internal label_suffix (never shown, ruling R9), another entity in its name;
-- d. registry norms, the name_norm of the registry's journal rows included (I7);
-- e. mentions (step 5): each narrator_context span [start, end, name, type] whose (name,
--    type) find_entity resolves to one entity becomes an entity_mentions row
--    ('deterministic'); the others are dropped and counted. narrator_context is kept.
CREATE OR REPLACE FUNCTION public.identity_legacy_normalise(p_game uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_counts jsonb := '{}'::jsonb;
    v_count integer;
    v_dropped integer;
    v_orphan record;
    v_clash record;
    v_norm text;
    v_targets uuid[];
    v_repointed integer := 0;
    v_deleted integer := 0;
    v_suffixed integer := 0;
    v_suffix integer;
    v_journal_moved integer := 0;
    v_journal_dropped integer := 0;
    v_commitments integer := 0;
    v_edge_tables text[] := ARRAY['relations', 'fact_participants', 'arc_participants',
                                  'chronology_participants', 'event_participants',
                                  'inventory', 'narrative_arcs', 'entity_aliases'];
BEGIN
    -- a.
    WITH ranked AS (
        SELECT al.id, al.alias_norm IS NULL AS missing,
               row_number() OVER (
                   PARTITION BY al.entity_id,
                                COALESCE(al.alias_norm,
                                         public.ldvelh_norm_for_game(p_game, al.alias))
                   ORDER BY al.alias_norm IS NULL,
                            array_position(ARRAY['true_name', 'label', 'descriptor', 'title',
                                                 'short', 'nickname', 'former_name'],
                                           al.kind),
                            al.created_at, al.id) AS rank
          FROM public.entity_aliases AS al
         WHERE al.game_id = p_game)
    DELETE FROM public.entity_aliases AS al USING ranked
     WHERE al.id = ranked.id AND ranked.missing AND ranked.rank > 1;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_counts := v_counts || jsonb_build_object('aliases_deduplicated', v_count);
    UPDATE public.entity_aliases AS al
       SET alias_norm = public.ldvelh_norm_for_game(p_game, al.alias)
     WHERE al.game_id = p_game AND al.alias_norm IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_counts := v_counts || jsonb_build_object('alias_norms', v_count);

    -- b.
    FOR v_orphan IN
        SELECT er.id, er.entity_type, er.name FROM public.entity_registry AS er
         WHERE er.game_id = p_game AND er.merged_into IS NULL
           AND public.identity_domain_row(er.entity_type, er.id) IS NULL
    LOOP
        v_norm := public.ldvelh_norm_for_game(p_game, v_orphan.name);
        SELECT array_agg(DISTINCT cand.id) INTO v_targets
          FROM (SELECT er.id FROM public.entity_registry AS er
                 WHERE er.game_id = p_game AND er.entity_type = v_orphan.entity_type
                   AND er.merged_into IS NULL
                   AND COALESCE(er.name_norm,
                                public.ldvelh_norm_for_game(p_game, er.name)) = v_norm
                UNION
                SELECT al.entity_id FROM public.entity_aliases AS al
                 WHERE al.game_id = p_game AND al.entity_type = v_orphan.entity_type
                   AND al.alias_norm = v_norm) AS cand
         WHERE cand.id <> v_orphan.id
           AND public.identity_domain_row(v_orphan.entity_type, cand.id) IS NOT NULL;
        IF cardinality(v_targets) = 1 THEN
            PERFORM public.identity_merge_edges(v_targets[1], v_orphan.id,
                                                v_orphan.entity_type);
            UPDATE public.world_changes AS wc
               SET old_row = replace(wc.old_row::text, v_orphan.id::text,
                                     v_targets[1]::text)::jsonb,
                   new_row = replace(wc.new_row::text, v_orphan.id::text,
                                     v_targets[1]::text)::jsonb
              FROM public.turns AS tn
             WHERE tn.id = wc.turn_id AND tn.game_id = p_game
               AND wc.table_name = ANY (v_edge_tables || 'director_commitments'::text)
               AND concat(wc.old_row::text, wc.new_row::text) LIKE '%' || v_orphan.id || '%';
            GET DIAGNOSTICS v_count = ROW_COUNT;
            v_journal_moved := v_journal_moved + v_count;
            v_repointed := v_repointed + 1;
        ELSE
            DELETE FROM public.world_changes AS wc USING public.turns AS tn
             WHERE tn.id = wc.turn_id AND tn.game_id = p_game
               AND wc.table_name = ANY (v_edge_tables)
               AND concat(wc.old_row::text, wc.new_row::text) LIKE '%' || v_orphan.id || '%';
            GET DIAGNOSTICS v_count = ROW_COUNT;
            v_journal_dropped := v_journal_dropped + v_count;
            UPDATE public.world_changes AS wc
               SET old_row = public.identity_drop_related(wc.old_row, v_orphan.id),
                   new_row = public.identity_drop_related(wc.new_row, v_orphan.id)
              FROM public.turns AS tn
             WHERE tn.id = wc.turn_id AND tn.game_id = p_game
               AND wc.table_name = 'director_commitments'
               AND concat(wc.old_row::text, wc.new_row::text) LIKE '%' || v_orphan.id || '%';
            UPDATE public.director_commitments AS dc
               SET related_entities = array_remove(dc.related_entities, v_orphan.id)
             WHERE dc.game_id = p_game AND v_orphan.id = ANY (dc.related_entities);
            GET DIAGNOSTICS v_count = ROW_COUNT;
            v_commitments := v_commitments + v_count;
            v_deleted := v_deleted + 1;
        END IF;
        DELETE FROM public.world_changes AS wc USING public.turns AS tn
         WHERE tn.id = wc.turn_id AND tn.game_id = p_game
           AND wc.table_name = 'entity_registry' AND wc.row_id = v_orphan.id;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_journal_dropped := v_journal_dropped + v_count;
        DELETE FROM public.entity_registry WHERE id = v_orphan.id;
    END LOOP;
    v_counts := v_counts || jsonb_build_object(
        'orphans_repointed', v_repointed, 'orphans_deleted', v_deleted,
        'orphan_journal_rows_repointed', v_journal_moved,
        'orphan_journal_rows_dropped', v_journal_dropped,
        'orphan_commitments_purged', v_commitments);

    -- c.
    FOR v_clash IN
        SELECT ranked.id, ranked.entity_type, ranked.name, ranked.rank FROM (
            SELECT er.id, er.entity_type, er.name,
                   row_number() OVER (
                       PARTITION BY er.entity_type,
                                    COALESCE(er.name_norm,
                                             public.ldvelh_norm_for_game(p_game, er.name))
                       ORDER BY (public.identity_domain_row(er.entity_type, er.id)
                                 ->> 'created_at')::timestamptz,
                                er.name COLLATE "C", er.id) AS rank
              FROM public.entity_registry AS er
             WHERE er.game_id = p_game AND er.merged_into IS NULL) AS ranked
         WHERE ranked.rank > 1
         ORDER BY ranked.entity_type, ranked.rank, ranked.id
    LOOP
        v_suffix := v_clash.rank;
        WHILE EXISTS (
            SELECT 1 FROM public.entity_registry AS er
             WHERE er.game_id = p_game AND er.entity_type = v_clash.entity_type
               AND er.merged_into IS NULL
               AND COALESCE(er.name_norm, public.ldvelh_norm_for_game(p_game, er.name))
                   = public.ldvelh_norm_for_game(p_game,
                                                 v_clash.name || ' (' || v_suffix || ')'))
        LOOP
            v_suffix := v_suffix + 1;
        END LOOP;
        IF v_clash.entity_type = 'character' THEN
            UPDATE public.characters SET label_suffix = v_suffix::text WHERE id = v_clash.id;
        ELSE
            EXECUTE 'UPDATE ' || public.identity_domain_table(v_clash.entity_type)::text
                    || ' SET name = name || $2 WHERE id = $1'
              USING v_clash.id, ' (' || v_suffix || ')';
        END IF;
        v_suffixed := v_suffixed + 1;
    END LOOP;
    v_counts := v_counts || jsonb_build_object('collisions_suffixed', v_suffixed);

    -- d.
    UPDATE public.entity_registry AS er
       SET name_norm = public.ldvelh_norm_for_game(p_game, er.name)
     WHERE er.game_id = p_game AND er.name_norm IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_counts := v_counts || jsonb_build_object('registry_norms', v_count);
    UPDATE public.world_changes AS wc
       SET old_row = CASE WHEN wc.old_row ? 'name' AND NOT wc.old_row ? 'name_norm'
                          THEN wc.old_row || jsonb_build_object('name_norm',
                                   public.ldvelh_norm_for_game(p_game, wc.old_row ->> 'name'))
                          ELSE wc.old_row END,
           new_row = CASE WHEN wc.new_row ? 'name' AND NOT wc.new_row ? 'name_norm'
                          THEN wc.new_row || jsonb_build_object('name_norm',
                                   public.ldvelh_norm_for_game(p_game, wc.new_row ->> 'name'))
                          ELSE wc.new_row END
      FROM public.turns AS tn
     WHERE tn.id = wc.turn_id AND tn.game_id = p_game AND wc.table_name = 'entity_registry'
       AND ((wc.old_row ? 'name' AND NOT wc.old_row ? 'name_norm')
            OR (wc.new_row ? 'name' AND NOT wc.new_row ? 'name_norm'));
    -- The alias rows 3.3 adds to the journal of an entity a turn deleted.
    UPDATE public.world_changes AS wc
       SET old_row = wc.old_row || jsonb_build_object('alias_norm',
                         public.ldvelh_norm_for_game(p_game, wc.old_row ->> 'alias'))
      FROM public.turns AS tn
     WHERE tn.id = wc.turn_id AND tn.game_id = p_game AND wc.table_name = 'entity_aliases'
       AND wc.old_row ? 'alias' AND (wc.old_row ->> 'alias_norm') IS NULL;
    PERFORM public.identity_journal_alias_conflicts(p_game);

    -- e.
    WITH spans AS (
        SELECT mg.id AS message_id, mg.turn_id, mg.content, span.value AS entry
          FROM public.messages AS mg
         CROSS JOIN LATERAL jsonb_array_elements(
                CASE WHEN jsonb_typeof(mg.narrator_context) = 'array'
                     THEN mg.narrator_context ELSE '[]'::jsonb END) AS span
         WHERE mg.game_id = p_game
           AND jsonb_typeof(span.value) = 'array' AND jsonb_array_length(span.value) >= 4
           AND (span.value ->> 0) ~ '^[0-9]+([.]0+)?$'
           AND (span.value ->> 1) ~ '^[0-9]+([.]0+)?$'
           AND jsonb_typeof(span.value -> 2) = 'string'
           AND jsonb_typeof(span.value -> 3) = 'string'),
    resolved AS (
        SELECT sp.message_id, sp.turn_id, sp.content, sp.entry ->> 2 AS name,
               (sp.entry ->> 0)::numeric::integer AS start_pos,
               (sp.entry ->> 1)::numeric::integer AS end_pos,
               public.identity_find_span_entity(p_game, sp.entry ->> 2, sp.entry ->> 3)
                   AS entity_id
          FROM spans AS sp),
    inserted AS (
        INSERT INTO public.entity_mentions
               (game_id, message_id, turn_id, start_pos, end_pos, surface, entity_id, decision)
        SELECT p_game, rs.message_id, rs.turn_id, rs.start_pos, rs.end_pos,
               COALESCE(NULLIF(substr(rs.content, rs.start_pos + 1, rs.end_pos - rs.start_pos),
                               ''), rs.name),
               rs.entity_id, 'deterministic'
          FROM resolved AS rs
         WHERE rs.entity_id IS NOT NULL AND rs.start_pos >= 0 AND rs.end_pos > rs.start_pos
        ON CONFLICT (message_id, start_pos, end_pos) DO NOTHING
        RETURNING 1)
    SELECT (SELECT count(*) FROM inserted),
           (SELECT count(*) FROM resolved WHERE resolved.entity_id IS NULL)
      INTO v_count, v_dropped;
    RETURN v_counts || jsonb_build_object('mentions', v_count, 'mentions_dropped', v_dropped);
END $$;

DROP TRIGGER sync_registry_location ON public.locations;
DROP TRIGGER sync_registry_organization ON public.organizations;
DROP TRIGGER sync_registry_object ON public.objects;
DROP TRIGGER sync_registry_protagonist ON public.protagonists;
DROP TRIGGER sync_registry_companion ON public.companions;
CREATE TRIGGER sync_registry_location AFTER UPDATE OF name ON public.locations
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('location');
CREATE TRIGGER sync_registry_organization AFTER UPDATE OF name ON public.organizations
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('organization');
CREATE TRIGGER sync_registry_object AFTER UPDATE OF name ON public.objects
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('object');
CREATE TRIGGER sync_registry_protagonist AFTER UPDATE OF name ON public.protagonists
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('protagonist');
CREATE TRIGGER sync_registry_companion AFTER UPDATE OF name ON public.companions
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('companion');

UPDATE public.locations SET name = name || ' (' || label_suffix || ')'
 WHERE label_suffix IS NOT NULL;
UPDATE public.organizations SET name = name || ' (' || label_suffix || ')'
 WHERE label_suffix IS NOT NULL;
UPDATE public.objects SET name = name || ' (' || label_suffix || ')'
 WHERE label_suffix IS NOT NULL;
UPDATE public.protagonists SET name = name || ' (' || label_suffix || ')'
 WHERE label_suffix IS NOT NULL;
UPDATE public.companions SET name = name || ' (' || label_suffix || ')'
 WHERE label_suffix IS NOT NULL;

DROP FUNCTION public.identity_label(text, jsonb);
ALTER TABLE public.companions DROP COLUMN label_suffix;
ALTER TABLE public.protagonists DROP COLUMN label_suffix;
ALTER TABLE public.objects DROP COLUMN label_suffix;
ALTER TABLE public.organizations DROP COLUMN label_suffix;
ALTER TABLE public.locations DROP COLUMN label_suffix;
