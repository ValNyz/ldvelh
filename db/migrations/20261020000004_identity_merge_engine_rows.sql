-- migrate:up
-- Engine rows and skills follow a merge, audited (#153, final review of PR 1b). An engine
-- row (npc_fate, npc_d6, npc_narrative; object_fate, object_d6, object_narrative: one per
-- entity) of drop moves to keep when keep has none, listed under '<table>.<column>' in
-- entity_merges.moved_edges; when keep has its own, keep's wins and drop's is listed under
-- '<table>.dropped' and copied into entity_merges.dropped_row ('engine') before the delete
-- of drop's domain row cascades to it. The operator preview (identity_merge_edges in a
-- rolled-back savepoint) lists both. A skill keep already has open is closed on drop's
-- side ('skills.closed') rather than listed twice. Every write still goes through the
-- journal triggers: undoing the turn restores every row. No trigger, no foreign key.

-- The engine rows of an entity, {table: row} (tables without a row left out).
CREATE FUNCTION public.identity_engine_rows(p_entity uuid, p_entity_type text)
        RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(jsonb_object_agg(engine.tbl, engine.row)
                        FILTER (WHERE engine.row IS NOT NULL), '{}'::jsonb)
      FROM (SELECT 'npc_fate', (SELECT to_jsonb(t) FROM public.npc_fate AS t
                                 WHERE t.character_id = p_entity)
             WHERE p_entity_type = 'character'
            UNION ALL
            SELECT 'npc_d6', (SELECT to_jsonb(t) FROM public.npc_d6 AS t
                               WHERE t.character_id = p_entity)
             WHERE p_entity_type = 'character'
            UNION ALL
            SELECT 'npc_narrative', (SELECT to_jsonb(t) FROM public.npc_narrative AS t
                                      WHERE t.character_id = p_entity)
             WHERE p_entity_type = 'character'
            UNION ALL
            SELECT 'object_fate', (SELECT to_jsonb(t) FROM public.object_fate AS t
                                    WHERE t.object_id = p_entity)
             WHERE p_entity_type = 'object'
            UNION ALL
            SELECT 'object_d6', (SELECT to_jsonb(t) FROM public.object_d6 AS t
                                  WHERE t.object_id = p_entity)
             WHERE p_entity_type = 'object'
            UNION ALL
            SELECT 'object_narrative', (SELECT to_jsonb(t) FROM public.object_narrative AS t
                                         WHERE t.object_id = p_entity)
             WHERE p_entity_type = 'object') AS engine (tbl, row)
$$;

-- Every edge of drop goes to keep (spec §4.7 effect 1); returns the moved row ids by
-- table.column. Relations: an open relation that keep already has (same other end, same
-- type) is closed (end_cycle, the entity_merges row tells why) rather than duplicated, a
-- relation between keep and drop is closed and left on the tombstone. Pivots: a row keep
-- already has is deleted. Inventory: quantities of the same object and owner are added up.
-- Skills: one keep has open is closed on drop's side. Engine rows: drop's moves when keep
-- has none, else it is listed under '<table>.dropped'.
CREATE OR REPLACE FUNCTION public.identity_merge_edges(p_keep uuid, p_drop uuid, p_entity_type text)
        RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_cycle integer;
    v_edges jsonb := '{}'::jsonb;
BEGIN
    SELECT gm.current_cycle INTO v_cycle
      FROM public.games AS gm JOIN public.entity_registry AS er ON er.game_id = gm.id
     WHERE er.id = p_keep;

    WITH closed AS (
        UPDATE public.relations AS rel SET end_cycle = v_cycle
         WHERE rel.end_cycle IS NULL AND p_drop IN (rel.source_id, rel.target_id)
           AND (p_keep IN (rel.source_id, rel.target_id)
                OR EXISTS (
                    SELECT 1 FROM public.relations AS dup
                     WHERE dup.end_cycle IS NULL AND dup.type = rel.type
                       AND dup.source_id = CASE WHEN rel.source_id = p_drop THEN p_keep
                                                ELSE rel.source_id END
                       AND dup.target_id = CASE WHEN rel.target_id = p_drop THEN p_keep
                                                ELSE rel.target_id END))
        RETURNING rel.id)
    SELECT v_edges || jsonb_build_object('relations.closed', array_agg(closed.id))
      INTO v_edges FROM closed;
    WITH moved AS (
        UPDATE public.relations AS rel SET source_id = p_keep
         WHERE rel.source_id = p_drop AND rel.target_id <> p_keep RETURNING rel.id)
    SELECT v_edges || jsonb_build_object('relations.source_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    WITH moved AS (
        UPDATE public.relations AS rel SET target_id = p_keep
         WHERE rel.target_id = p_drop AND rel.source_id <> p_keep RETURNING rel.id)
    SELECT v_edges || jsonb_build_object('relations.target_id', array_agg(moved.id))
      INTO v_edges FROM moved;

    DELETE FROM public.fact_participants AS fp
     WHERE fp.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.fact_participants AS kp
                    WHERE kp.fact_id = fp.fact_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.fact_participants AS fp SET entity_id = p_keep
         WHERE fp.entity_id = p_drop RETURNING fp.id)
    SELECT v_edges || jsonb_build_object('fact_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    DELETE FROM public.arc_participants AS ap
     WHERE ap.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.arc_participants AS kp
                    WHERE kp.arc_id = ap.arc_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.arc_participants AS ap SET entity_id = p_keep
         WHERE ap.entity_id = p_drop RETURNING ap.id)
    SELECT v_edges || jsonb_build_object('arc_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    DELETE FROM public.chronology_participants AS cp
     WHERE cp.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.chronology_participants AS kp
                    WHERE kp.chronology_id = cp.chronology_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.chronology_participants AS cp SET entity_id = p_keep
         WHERE cp.entity_id = p_drop RETURNING cp.id)
    SELECT v_edges
           || jsonb_build_object('chronology_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    DELETE FROM public.event_participants AS ep
     WHERE ep.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.event_participants AS kp
                    WHERE kp.event_id = ep.event_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.event_participants AS ep SET entity_id = p_keep
         WHERE ep.entity_id = p_drop RETURNING ep.id)
    SELECT v_edges || jsonb_build_object('event_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;

    UPDATE public.inventory AS kept SET quantity = COALESCE(kept.quantity, 0)
                                                   + COALESCE(gone.quantity, 0)
      FROM public.inventory AS gone
     WHERE kept.owner_id = p_keep AND gone.owner_id = p_drop
       AND gone.object_id = kept.object_id;
    DELETE FROM public.inventory AS gone
     WHERE gone.owner_id = p_drop
       AND EXISTS (SELECT 1 FROM public.inventory AS kept
                    WHERE kept.owner_id = p_keep AND kept.object_id = gone.object_id);
    WITH moved AS (
        UPDATE public.inventory AS inv SET owner_id = p_keep
         WHERE inv.owner_id = p_drop RETURNING inv.id)
    SELECT v_edges || jsonb_build_object('inventory.owner_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    WITH moved AS (
        UPDATE public.narrative_arcs AS na SET owner_id = p_keep
         WHERE na.owner_id = p_drop RETURNING na.id)
    SELECT v_edges || jsonb_build_object('narrative_arcs.owner_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    WITH moved AS (
        UPDATE public.director_commitments AS dc
           SET related_entities = CASE WHEN p_keep = ANY (dc.related_entities)
                                       THEN array_remove(dc.related_entities, p_drop)
                                       ELSE array_replace(dc.related_entities, p_drop, p_keep)
                                  END
         WHERE p_drop = ANY (dc.related_entities) RETURNING dc.id)
    SELECT v_edges
           || jsonb_build_object('director_commitments.related_entities', array_agg(moved.id))
      INTO v_edges FROM moved;

    IF p_entity_type = 'character' THEN
        -- A skill keep already has open (same name, case aside) is closed on drop's side
        -- (end_cycle, the entity_merges row tells why) rather than listed twice.
        WITH closed AS (
            UPDATE public.skills AS sk SET end_cycle = v_cycle
             WHERE sk.character_id = p_drop AND sk.end_cycle IS NULL
               AND EXISTS (SELECT 1 FROM public.skills AS ks
                            WHERE ks.character_id = p_keep AND ks.end_cycle IS NULL
                              AND lower(ks.name) = lower(sk.name))
            RETURNING sk.id)
        SELECT v_edges || jsonb_build_object('skills.closed', array_agg(closed.id))
          INTO v_edges FROM closed;
        WITH moved AS (
            UPDATE public.skills AS sk SET character_id = p_keep
             WHERE sk.character_id = p_drop RETURNING sk.id)
        SELECT v_edges || jsonb_build_object('skills.character_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        -- Engine rows (one per character): drop's moves when keep has none; otherwise
        -- keep's wins and drop's, left behind, is listed under '<table>.dropped'.
        WITH moved AS (
            UPDATE public.npc_fate AS eng SET character_id = p_keep
             WHERE eng.character_id = p_drop
               AND NOT EXISTS (SELECT 1 FROM public.npc_fate AS kept
                                WHERE kept.character_id = p_keep)
            RETURNING eng.id)
        SELECT v_edges || jsonb_build_object('npc_fate.character_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        SELECT v_edges || jsonb_build_object('npc_fate.dropped', array_agg(eng.id))
          INTO v_edges FROM public.npc_fate AS eng WHERE eng.character_id = p_drop;
        WITH moved AS (
            UPDATE public.npc_d6 AS eng SET character_id = p_keep
             WHERE eng.character_id = p_drop
               AND NOT EXISTS (SELECT 1 FROM public.npc_d6 AS kept
                                WHERE kept.character_id = p_keep)
            RETURNING eng.id)
        SELECT v_edges || jsonb_build_object('npc_d6.character_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        SELECT v_edges || jsonb_build_object('npc_d6.dropped', array_agg(eng.id))
          INTO v_edges FROM public.npc_d6 AS eng WHERE eng.character_id = p_drop;
        WITH moved AS (
            UPDATE public.npc_narrative AS eng SET character_id = p_keep
             WHERE eng.character_id = p_drop
               AND NOT EXISTS (SELECT 1 FROM public.npc_narrative AS kept
                                WHERE kept.character_id = p_keep)
            RETURNING eng.id)
        SELECT v_edges || jsonb_build_object('npc_narrative.character_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        SELECT v_edges || jsonb_build_object('npc_narrative.dropped', array_agg(eng.id))
          INTO v_edges FROM public.npc_narrative AS eng WHERE eng.character_id = p_drop;
    ELSIF p_entity_type = 'location' THEN
        -- facts_immutable lets a fact follow its location to the one it was merged into.
        WITH moved AS (
            UPDATE public.facts AS ft SET location_id = p_keep
             WHERE ft.location_id = p_drop RETURNING ft.id)
        SELECT v_edges || jsonb_build_object('facts.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.characters AS ch SET workplace_id = p_keep
             WHERE ch.workplace_id = p_drop RETURNING ch.id)
        SELECT v_edges || jsonb_build_object('characters.workplace_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.characters AS ch SET residence_id = p_keep
             WHERE ch.residence_id = p_drop RETURNING ch.id)
        SELECT v_edges || jsonb_build_object('characters.residence_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.messages AS mg SET location_id = p_keep
             WHERE mg.location_id = p_drop RETURNING mg.id)
        SELECT v_edges || jsonb_build_object('messages.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.games AS gm SET current_location_id = p_keep
             WHERE gm.current_location_id = p_drop RETURNING gm.id)
        SELECT v_edges
               || jsonb_build_object('games.current_location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.chronology AS cr SET location_id = p_keep
             WHERE cr.location_id = p_drop RETURNING cr.id)
        SELECT v_edges || jsonb_build_object('chronology.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.events AS ev SET location_id = p_keep
             WHERE ev.location_id = p_drop RETURNING ev.id)
        SELECT v_edges || jsonb_build_object('events.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.locations AS lc SET parent_id = p_keep
             WHERE lc.parent_id = p_drop AND lc.id <> p_keep RETURNING lc.id)
        SELECT v_edges || jsonb_build_object('locations.parent_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.organizations AS og SET headquarters_id = p_keep
             WHERE og.headquarters_id = p_drop RETURNING og.id)
        SELECT v_edges
               || jsonb_build_object('organizations.headquarters_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.protagonists AS pc SET residence_id = p_keep
             WHERE pc.residence_id = p_drop RETURNING pc.id)
        SELECT v_edges || jsonb_build_object('protagonists.residence_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.narrative_seeds AS ns SET location_id = p_keep
             WHERE ns.location_id = p_drop RETURNING ns.id)
        SELECT v_edges
               || jsonb_build_object('narrative_seeds.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
    ELSIF p_entity_type = 'organization' THEN
        WITH moved AS (
            UPDATE public.protagonists AS pc SET employer_id = p_keep
             WHERE pc.employer_id = p_drop RETURNING pc.id)
        SELECT v_edges || jsonb_build_object('protagonists.employer_id', array_agg(moved.id))
          INTO v_edges FROM moved;
    ELSIF p_entity_type = 'object' THEN
        UPDATE public.inventory AS kept SET quantity = COALESCE(kept.quantity, 0)
                                                       + COALESCE(gone.quantity, 0)
          FROM public.inventory AS gone
         WHERE kept.object_id = p_keep AND gone.object_id = p_drop
           AND gone.owner_id IS NOT DISTINCT FROM kept.owner_id;
        DELETE FROM public.inventory AS gone
         WHERE gone.object_id = p_drop
           AND EXISTS (SELECT 1 FROM public.inventory AS kept
                        WHERE kept.object_id = p_keep
                          AND kept.owner_id IS NOT DISTINCT FROM gone.owner_id);
        WITH moved AS (
            UPDATE public.inventory AS inv SET object_id = p_keep
             WHERE inv.object_id = p_drop RETURNING inv.id)
        SELECT v_edges || jsonb_build_object('inventory.object_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        -- Engine rows (one per object): as a character's.
        WITH moved AS (
            UPDATE public.object_fate AS eng SET object_id = p_keep
             WHERE eng.object_id = p_drop
               AND NOT EXISTS (SELECT 1 FROM public.object_fate AS kept
                                WHERE kept.object_id = p_keep)
            RETURNING eng.id)
        SELECT v_edges || jsonb_build_object('object_fate.object_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        SELECT v_edges || jsonb_build_object('object_fate.dropped', array_agg(eng.id))
          INTO v_edges FROM public.object_fate AS eng WHERE eng.object_id = p_drop;
        WITH moved AS (
            UPDATE public.object_d6 AS eng SET object_id = p_keep
             WHERE eng.object_id = p_drop
               AND NOT EXISTS (SELECT 1 FROM public.object_d6 AS kept
                                WHERE kept.object_id = p_keep)
            RETURNING eng.id)
        SELECT v_edges || jsonb_build_object('object_d6.object_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        SELECT v_edges || jsonb_build_object('object_d6.dropped', array_agg(eng.id))
          INTO v_edges FROM public.object_d6 AS eng WHERE eng.object_id = p_drop;
        WITH moved AS (
            UPDATE public.object_narrative AS eng SET object_id = p_keep
             WHERE eng.object_id = p_drop
               AND NOT EXISTS (SELECT 1 FROM public.object_narrative AS kept
                                WHERE kept.object_id = p_keep)
            RETURNING eng.id)
        SELECT v_edges || jsonb_build_object('object_narrative.object_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        SELECT v_edges || jsonb_build_object('object_narrative.dropped', array_agg(eng.id))
          INTO v_edges FROM public.object_narrative AS eng WHERE eng.object_id = p_drop;
    END IF;
    RETURN jsonb_strip_nulls(v_edges);
END $$;

-- Merge drop into keep (see 20261020000001): the snapshot of drop's domain row also
-- carries, under 'engine', its engine rows that keep's own replaced.
CREATE OR REPLACE FUNCTION public.merge_entities(p_keep uuid, p_drop uuid, p_reason text,
        p_evidence text) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_turn uuid := nullif(current_setting('ldvelh.turn_id', true), '')::uuid;
    v_keep public.entity_registry;
    v_drop public.entity_registry;
    v_drop_row jsonb;
    v_keep_norm text;
    v_character boolean;
    v_edges jsonb;
    v_engine jsonb;
    v_merge_id uuid;
BEGIN
    SELECT * INTO v_keep FROM public.entity_registry WHERE id = p_keep;
    SELECT * INTO v_drop FROM public.entity_registry WHERE id = p_drop;
    IF v_keep.id IS NULL OR v_drop.id IS NULL THEN
        RAISE EXCEPTION 'merge_entities: entity missing (%, %)', p_keep, p_drop;
    END IF;
    -- Integrity, not policy (the policy guards live in the identity service): one entity
    -- with itself, two games, or a tombstone on either side would destroy or cross data.
    IF p_keep = p_drop THEN
        RAISE EXCEPTION 'merge_entities: keep = drop (%)', p_keep;
    END IF;
    IF v_keep.game_id <> v_drop.game_id THEN
        RAISE EXCEPTION 'merge_entities: entities in two games (%, %)', p_keep, p_drop;
    END IF;
    IF v_keep.merged_into IS NOT NULL OR v_drop.merged_into IS NOT NULL THEN
        RAISE EXCEPTION 'merge_entities: already merged (%, %)', p_keep, p_drop;
    END IF;
    IF v_keep.entity_type <> v_drop.entity_type THEN
        RAISE EXCEPTION 'merge_entities: entity types differ (%, %)',
            v_keep.entity_type, v_drop.entity_type;
    END IF;
    v_character := v_keep.entity_type = 'character';
    v_drop_row := public.identity_domain_row(v_drop.entity_type, p_drop);

    -- The tombstone first: keep may then take drop's name without a normalised collision.
    UPDATE public.entity_registry SET merged_into = p_keep WHERE id = p_drop;
    PERFORM public.identity_merge_fields(p_keep, p_drop, v_keep.entity_type);
    SELECT er.name_norm INTO v_keep_norm FROM public.entity_registry AS er WHERE er.id = p_keep;

    -- A label or true name of drop that is not keep's own becomes a former name.
    UPDATE public.entity_aliases AS al
       SET entity_id = p_keep,
           kind = CASE WHEN al.kind IN ('label', 'true_name') AND al.alias_norm <> v_keep_norm
                       THEN 'former_name' ELSE al.kind END
     WHERE al.entity_id = p_drop
       AND NOT EXISTS (SELECT 1 FROM public.entity_aliases AS ka
                        WHERE ka.entity_id = p_keep AND ka.alias_norm = al.alias_norm);
    INSERT INTO public.entity_aliases
           (game_id, entity_id, entity_type, alias, kind, known, source, turn_id)
    VALUES (v_keep.game_id, p_keep, v_keep.entity_type, v_drop.name,
            CASE WHEN v_character AND v_drop_row ->> 'true_name' IS NULL THEN 'descriptor'
                 WHEN v_drop.name_norm = v_keep_norm AND v_character THEN 'true_name'
                 WHEN v_drop.name_norm = v_keep_norm THEN 'label'
                 ELSE 'former_name' END,
            NOT v_character OR v_drop_row ->> 'true_name' IS NULL
                OR COALESCE((v_drop_row ->> 'known_by_protagonist')::boolean, false),
            'system', v_turn)
    ON CONFLICT DO NOTHING;

    v_edges := public.identity_merge_edges(p_keep, p_drop, v_keep.entity_type);
    -- The engine rows drop keeps (keep had its own): copied into the audit row before the
    -- domain row's delete cascades to them.
    v_engine := public.identity_engine_rows(p_drop, v_keep.entity_type);
    IF v_engine <> '{}'::jsonb THEN
        v_drop_row := COALESCE(v_drop_row, '{}'::jsonb) || jsonb_build_object('engine', v_engine);
    END IF;

    CASE v_keep.entity_type
        WHEN 'character' THEN DELETE FROM public.characters WHERE id = p_drop;
        WHEN 'location' THEN DELETE FROM public.locations WHERE id = p_drop;
        WHEN 'organization' THEN DELETE FROM public.organizations WHERE id = p_drop;
        WHEN 'object' THEN DELETE FROM public.objects WHERE id = p_drop;
        WHEN 'protagonist' THEN DELETE FROM public.protagonists WHERE id = p_drop;
        WHEN 'companion' THEN DELETE FROM public.companions WHERE id = p_drop;
    END CASE;

    INSERT INTO public.entity_merges (game_id, kept_id, dropped_id, dropped_registry,
                                      dropped_row, moved_edges, reason, evidence, turn_id)
    VALUES (v_keep.game_id, p_keep, p_drop, to_jsonb(v_drop), v_drop_row, v_edges,
            p_reason, p_evidence, v_turn)
    RETURNING id INTO v_merge_id;
    INSERT INTO public.identity_events (game_id, turn_id, kind, entity_id, payload)
    VALUES (v_keep.game_id, v_turn, 'merge', p_keep,
            jsonb_build_object('merge_id', v_merge_id, 'dropped_id', p_drop));
    RETURN v_merge_id;
END $$;

-- migrate:down
-- The PR 1a merge: engine rows moved silently (drop's lost when keep had one), skills
-- moved without dedup.
CREATE OR REPLACE FUNCTION public.identity_merge_edges(p_keep uuid, p_drop uuid, p_entity_type text)
        RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_cycle integer;
    v_edges jsonb := '{}'::jsonb;
BEGIN
    SELECT gm.current_cycle INTO v_cycle
      FROM public.games AS gm JOIN public.entity_registry AS er ON er.game_id = gm.id
     WHERE er.id = p_keep;

    WITH closed AS (
        UPDATE public.relations AS rel SET end_cycle = v_cycle
         WHERE rel.end_cycle IS NULL AND p_drop IN (rel.source_id, rel.target_id)
           AND (p_keep IN (rel.source_id, rel.target_id)
                OR EXISTS (
                    SELECT 1 FROM public.relations AS dup
                     WHERE dup.end_cycle IS NULL AND dup.type = rel.type
                       AND dup.source_id = CASE WHEN rel.source_id = p_drop THEN p_keep
                                                ELSE rel.source_id END
                       AND dup.target_id = CASE WHEN rel.target_id = p_drop THEN p_keep
                                                ELSE rel.target_id END))
        RETURNING rel.id)
    SELECT v_edges || jsonb_build_object('relations.closed', array_agg(closed.id))
      INTO v_edges FROM closed;
    WITH moved AS (
        UPDATE public.relations AS rel SET source_id = p_keep
         WHERE rel.source_id = p_drop AND rel.target_id <> p_keep RETURNING rel.id)
    SELECT v_edges || jsonb_build_object('relations.source_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    WITH moved AS (
        UPDATE public.relations AS rel SET target_id = p_keep
         WHERE rel.target_id = p_drop AND rel.source_id <> p_keep RETURNING rel.id)
    SELECT v_edges || jsonb_build_object('relations.target_id', array_agg(moved.id))
      INTO v_edges FROM moved;

    DELETE FROM public.fact_participants AS fp
     WHERE fp.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.fact_participants AS kp
                    WHERE kp.fact_id = fp.fact_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.fact_participants AS fp SET entity_id = p_keep
         WHERE fp.entity_id = p_drop RETURNING fp.id)
    SELECT v_edges || jsonb_build_object('fact_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    DELETE FROM public.arc_participants AS ap
     WHERE ap.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.arc_participants AS kp
                    WHERE kp.arc_id = ap.arc_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.arc_participants AS ap SET entity_id = p_keep
         WHERE ap.entity_id = p_drop RETURNING ap.id)
    SELECT v_edges || jsonb_build_object('arc_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    DELETE FROM public.chronology_participants AS cp
     WHERE cp.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.chronology_participants AS kp
                    WHERE kp.chronology_id = cp.chronology_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.chronology_participants AS cp SET entity_id = p_keep
         WHERE cp.entity_id = p_drop RETURNING cp.id)
    SELECT v_edges
           || jsonb_build_object('chronology_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    DELETE FROM public.event_participants AS ep
     WHERE ep.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.event_participants AS kp
                    WHERE kp.event_id = ep.event_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.event_participants AS ep SET entity_id = p_keep
         WHERE ep.entity_id = p_drop RETURNING ep.id)
    SELECT v_edges || jsonb_build_object('event_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;

    UPDATE public.inventory AS kept SET quantity = COALESCE(kept.quantity, 0)
                                                   + COALESCE(gone.quantity, 0)
      FROM public.inventory AS gone
     WHERE kept.owner_id = p_keep AND gone.owner_id = p_drop
       AND gone.object_id = kept.object_id;
    DELETE FROM public.inventory AS gone
     WHERE gone.owner_id = p_drop
       AND EXISTS (SELECT 1 FROM public.inventory AS kept
                    WHERE kept.owner_id = p_keep AND kept.object_id = gone.object_id);
    WITH moved AS (
        UPDATE public.inventory AS inv SET owner_id = p_keep
         WHERE inv.owner_id = p_drop RETURNING inv.id)
    SELECT v_edges || jsonb_build_object('inventory.owner_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    WITH moved AS (
        UPDATE public.narrative_arcs AS na SET owner_id = p_keep
         WHERE na.owner_id = p_drop RETURNING na.id)
    SELECT v_edges || jsonb_build_object('narrative_arcs.owner_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    WITH moved AS (
        UPDATE public.director_commitments AS dc
           SET related_entities = CASE WHEN p_keep = ANY (dc.related_entities)
                                       THEN array_remove(dc.related_entities, p_drop)
                                       ELSE array_replace(dc.related_entities, p_drop, p_keep)
                                  END
         WHERE p_drop = ANY (dc.related_entities) RETURNING dc.id)
    SELECT v_edges
           || jsonb_build_object('director_commitments.related_entities', array_agg(moved.id))
      INTO v_edges FROM moved;

    IF p_entity_type = 'character' THEN
        WITH moved AS (
            UPDATE public.skills AS sk SET character_id = p_keep
             WHERE sk.character_id = p_drop RETURNING sk.id)
        SELECT v_edges || jsonb_build_object('skills.character_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        -- Engine rows (one per character): drop's only when keep has none.
        UPDATE public.npc_fate SET character_id = p_keep WHERE character_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.npc_fate WHERE character_id = p_keep);
        UPDATE public.npc_d6 SET character_id = p_keep WHERE character_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.npc_d6 WHERE character_id = p_keep);
        UPDATE public.npc_narrative SET character_id = p_keep WHERE character_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.npc_narrative WHERE character_id = p_keep);
    ELSIF p_entity_type = 'location' THEN
        -- facts_immutable lets a fact follow its location to the one it was merged into.
        WITH moved AS (
            UPDATE public.facts AS ft SET location_id = p_keep
             WHERE ft.location_id = p_drop RETURNING ft.id)
        SELECT v_edges || jsonb_build_object('facts.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.characters AS ch SET workplace_id = p_keep
             WHERE ch.workplace_id = p_drop RETURNING ch.id)
        SELECT v_edges || jsonb_build_object('characters.workplace_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.characters AS ch SET residence_id = p_keep
             WHERE ch.residence_id = p_drop RETURNING ch.id)
        SELECT v_edges || jsonb_build_object('characters.residence_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.messages AS mg SET location_id = p_keep
             WHERE mg.location_id = p_drop RETURNING mg.id)
        SELECT v_edges || jsonb_build_object('messages.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.games AS gm SET current_location_id = p_keep
             WHERE gm.current_location_id = p_drop RETURNING gm.id)
        SELECT v_edges
               || jsonb_build_object('games.current_location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.chronology AS cr SET location_id = p_keep
             WHERE cr.location_id = p_drop RETURNING cr.id)
        SELECT v_edges || jsonb_build_object('chronology.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.events AS ev SET location_id = p_keep
             WHERE ev.location_id = p_drop RETURNING ev.id)
        SELECT v_edges || jsonb_build_object('events.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.locations AS lc SET parent_id = p_keep
             WHERE lc.parent_id = p_drop AND lc.id <> p_keep RETURNING lc.id)
        SELECT v_edges || jsonb_build_object('locations.parent_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.organizations AS og SET headquarters_id = p_keep
             WHERE og.headquarters_id = p_drop RETURNING og.id)
        SELECT v_edges
               || jsonb_build_object('organizations.headquarters_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.protagonists AS pc SET residence_id = p_keep
             WHERE pc.residence_id = p_drop RETURNING pc.id)
        SELECT v_edges || jsonb_build_object('protagonists.residence_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.narrative_seeds AS ns SET location_id = p_keep
             WHERE ns.location_id = p_drop RETURNING ns.id)
        SELECT v_edges
               || jsonb_build_object('narrative_seeds.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
    ELSIF p_entity_type = 'organization' THEN
        WITH moved AS (
            UPDATE public.protagonists AS pc SET employer_id = p_keep
             WHERE pc.employer_id = p_drop RETURNING pc.id)
        SELECT v_edges || jsonb_build_object('protagonists.employer_id', array_agg(moved.id))
          INTO v_edges FROM moved;
    ELSIF p_entity_type = 'object' THEN
        UPDATE public.inventory AS kept SET quantity = COALESCE(kept.quantity, 0)
                                                       + COALESCE(gone.quantity, 0)
          FROM public.inventory AS gone
         WHERE kept.object_id = p_keep AND gone.object_id = p_drop
           AND gone.owner_id IS NOT DISTINCT FROM kept.owner_id;
        DELETE FROM public.inventory AS gone
         WHERE gone.object_id = p_drop
           AND EXISTS (SELECT 1 FROM public.inventory AS kept
                        WHERE kept.object_id = p_keep
                          AND kept.owner_id IS NOT DISTINCT FROM gone.owner_id);
        WITH moved AS (
            UPDATE public.inventory AS inv SET object_id = p_keep
             WHERE inv.object_id = p_drop RETURNING inv.id)
        SELECT v_edges || jsonb_build_object('inventory.object_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        UPDATE public.object_fate SET object_id = p_keep WHERE object_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.object_fate WHERE object_id = p_keep);
        UPDATE public.object_d6 SET object_id = p_keep WHERE object_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.object_d6 WHERE object_id = p_keep);
        UPDATE public.object_narrative SET object_id = p_keep WHERE object_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.object_narrative WHERE object_id = p_keep);
    END IF;
    RETURN jsonb_strip_nulls(v_edges);
END $$;

CREATE OR REPLACE FUNCTION public.merge_entities(p_keep uuid, p_drop uuid, p_reason text,
        p_evidence text) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_turn uuid := nullif(current_setting('ldvelh.turn_id', true), '')::uuid;
    v_keep public.entity_registry;
    v_drop public.entity_registry;
    v_drop_row jsonb;
    v_keep_norm text;
    v_character boolean;
    v_edges jsonb;
    v_merge_id uuid;
BEGIN
    SELECT * INTO v_keep FROM public.entity_registry WHERE id = p_keep;
    SELECT * INTO v_drop FROM public.entity_registry WHERE id = p_drop;
    IF v_keep.id IS NULL OR v_drop.id IS NULL THEN
        RAISE EXCEPTION 'merge_entities: entity missing (%, %)', p_keep, p_drop;
    END IF;
    -- Integrity, not policy (the policy guards live in the identity service): one entity
    -- with itself, two games, or a tombstone on either side would destroy or cross data.
    IF p_keep = p_drop THEN
        RAISE EXCEPTION 'merge_entities: keep = drop (%)', p_keep;
    END IF;
    IF v_keep.game_id <> v_drop.game_id THEN
        RAISE EXCEPTION 'merge_entities: entities in two games (%, %)', p_keep, p_drop;
    END IF;
    IF v_keep.merged_into IS NOT NULL OR v_drop.merged_into IS NOT NULL THEN
        RAISE EXCEPTION 'merge_entities: already merged (%, %)', p_keep, p_drop;
    END IF;
    IF v_keep.entity_type <> v_drop.entity_type THEN
        RAISE EXCEPTION 'merge_entities: entity types differ (%, %)',
            v_keep.entity_type, v_drop.entity_type;
    END IF;
    v_character := v_keep.entity_type = 'character';
    v_drop_row := public.identity_domain_row(v_drop.entity_type, p_drop);

    -- The tombstone first: keep may then take drop's name without a normalised collision.
    UPDATE public.entity_registry SET merged_into = p_keep WHERE id = p_drop;
    PERFORM public.identity_merge_fields(p_keep, p_drop, v_keep.entity_type);
    SELECT er.name_norm INTO v_keep_norm FROM public.entity_registry AS er WHERE er.id = p_keep;

    -- A label or true name of drop that is not keep's own becomes a former name.
    UPDATE public.entity_aliases AS al
       SET entity_id = p_keep,
           kind = CASE WHEN al.kind IN ('label', 'true_name') AND al.alias_norm <> v_keep_norm
                       THEN 'former_name' ELSE al.kind END
     WHERE al.entity_id = p_drop
       AND NOT EXISTS (SELECT 1 FROM public.entity_aliases AS ka
                        WHERE ka.entity_id = p_keep AND ka.alias_norm = al.alias_norm);
    INSERT INTO public.entity_aliases
           (game_id, entity_id, entity_type, alias, kind, known, source, turn_id)
    VALUES (v_keep.game_id, p_keep, v_keep.entity_type, v_drop.name,
            CASE WHEN v_character AND v_drop_row ->> 'true_name' IS NULL THEN 'descriptor'
                 WHEN v_drop.name_norm = v_keep_norm AND v_character THEN 'true_name'
                 WHEN v_drop.name_norm = v_keep_norm THEN 'label'
                 ELSE 'former_name' END,
            NOT v_character OR v_drop_row ->> 'true_name' IS NULL
                OR COALESCE((v_drop_row ->> 'known_by_protagonist')::boolean, false),
            'system', v_turn)
    ON CONFLICT DO NOTHING;

    v_edges := public.identity_merge_edges(p_keep, p_drop, v_keep.entity_type);

    CASE v_keep.entity_type
        WHEN 'character' THEN DELETE FROM public.characters WHERE id = p_drop;
        WHEN 'location' THEN DELETE FROM public.locations WHERE id = p_drop;
        WHEN 'organization' THEN DELETE FROM public.organizations WHERE id = p_drop;
        WHEN 'object' THEN DELETE FROM public.objects WHERE id = p_drop;
        WHEN 'protagonist' THEN DELETE FROM public.protagonists WHERE id = p_drop;
        WHEN 'companion' THEN DELETE FROM public.companions WHERE id = p_drop;
    END CASE;

    INSERT INTO public.entity_merges (game_id, kept_id, dropped_id, dropped_registry,
                                      dropped_row, moved_edges, reason, evidence, turn_id)
    VALUES (v_keep.game_id, p_keep, p_drop, to_jsonb(v_drop), v_drop_row, v_edges,
            p_reason, p_evidence, v_turn)
    RETURNING id INTO v_merge_id;
    INSERT INTO public.identity_events (game_id, turn_id, kind, entity_id, payload)
    VALUES (v_keep.game_id, v_turn, 'merge', p_keep,
            jsonb_build_object('merge_id', v_merge_id, 'dropped_id', p_drop));
    RETURN v_merge_id;
END $$;

DROP FUNCTION public.identity_engine_rows(uuid, text);
