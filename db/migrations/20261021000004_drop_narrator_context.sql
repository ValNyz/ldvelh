-- migrate:up
-- messages.narrator_context goes (#155): the mentions are served by entity id from
-- entity_mentions (spec §4.9), and the resolver no longer writes the column.
--
-- A game the legacy pass has not normalised yet (no language: section 3.4 of the identity
-- migration skipped it, scripts/identity_backfill.py gives it one, then rebuilds its
-- mentions) still needs its old spans: they move to identity_legacy_spans, which step e
-- of identity_legacy_normalise reads and empties for the game. Every other game already
-- has its spans in entity_mentions (section 3.4, or the backfill), or never had any.
CREATE TABLE public.identity_legacy_spans (
    message_id uuid PRIMARY KEY
        REFERENCES public.messages(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    spans jsonb NOT NULL
);

INSERT INTO public.identity_legacy_spans (message_id, spans)
SELECT mg.id, mg.narrator_context
  FROM public.messages AS mg
  JOIN public.games AS gm ON gm.id = mg.game_id
 WHERE gm.language IS NULL
   AND CASE WHEN jsonb_typeof(mg.narrator_context) = 'array'
            THEN jsonb_array_length(mg.narrator_context) > 0 ELSE false END;

-- Steps a-d unchanged; e. reads the staged spans [start, end, name, type], then drops the
-- game's staged rows (consumed: resolved ones are mentions, the others are counted).
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
          FROM public.identity_legacy_spans AS ls
          JOIN public.messages AS mg ON mg.id = ls.message_id
         CROSS JOIN LATERAL jsonb_array_elements(
                CASE WHEN jsonb_typeof(ls.spans) = 'array'
                     THEN ls.spans ELSE '[]'::jsonb END) AS span
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
    DELETE FROM public.identity_legacy_spans AS ls USING public.messages AS mg
     WHERE mg.id = ls.message_id AND mg.game_id = p_game;
    RETURN v_counts || jsonb_build_object('mentions', v_count, 'mentions_dropped', v_dropped);
END $$;


ALTER TABLE public.messages DROP COLUMN narrator_context;

-- migrate:down
-- The column comes back in its legacy format, [start, end, label, type] per span, label =
-- display_for_player, from the stored mentions (merges followed), in text order; a message
-- whose spans are still staged gets them back as they were.
ALTER TABLE public.messages ADD COLUMN narrator_context jsonb;

UPDATE public.messages AS mg
   SET narrator_context = rebuilt.spans
  FROM (SELECT m.message_id,
               jsonb_agg(jsonb_build_array(m.start_pos, m.end_pos,
                                           public.display_for_player(m.entity_id),
                                           er.entity_type)
                         ORDER BY m.start_pos, m.end_pos) AS spans
          FROM public.entity_mentions AS m
          JOIN public.entity_registry AS er
            ON er.id = public.entity_follow_merge(m.entity_id)
         WHERE public.display_for_player(m.entity_id) IS NOT NULL
         GROUP BY m.message_id) AS rebuilt
 WHERE mg.id = rebuilt.message_id;

UPDATE public.messages AS mg
   SET narrator_context = ls.spans
  FROM public.identity_legacy_spans AS ls
 WHERE mg.id = ls.message_id AND mg.narrator_context IS NULL;

-- identity_legacy_normalise as 20261020000002 left it (step e on the column).
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


DROP TABLE public.identity_legacy_spans;
