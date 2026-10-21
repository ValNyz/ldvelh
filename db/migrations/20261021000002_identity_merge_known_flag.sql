-- migrate:up
-- A merge no longer ORs known_by_protagonist (#154, ruling R42): keep's flag says whether
-- the protagonist knows keep's name (a character's true name); drop's flag only carries
-- over when keep takes drop's name or when both names are one. ORing them could make a
-- secret true name readable (display_for_player) after an operator merge. The mandatory
-- flag is still ORed. Same signature: identity_merge_entities calls it unchanged.
CREATE OR REPLACE FUNCTION public.identity_merge_fields(p_keep uuid, p_drop uuid, p_entity_type text)
        RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_table regclass := public.identity_domain_table(p_entity_type);
    v_keep_row jsonb := public.identity_domain_row(p_entity_type, p_keep);
    v_drop_row jsonb := public.identity_domain_row(p_entity_type, p_drop);
    v_merged jsonb;
    v_name_key text := CASE WHEN v_keep_row ? 'true_name' THEN 'true_name' ELSE 'name' END;
    v_known boolean;
    v_cols text;
    v_vals text;
BEGIN
    IF v_keep_row IS NULL OR v_drop_row IS NULL THEN
        RETURN;
    END IF;
    -- The protagonist knows keep's name only if keep's flag says so: drop's flag is about
    -- drop's name. It carries over when keep had no name (keep takes drop's) or when both
    -- names are one (same normalised form); drop's own name moves as an alias with its
    -- own flags (merge_entities moves the aliases), never making keep's different name known.
    v_known := CASE
        WHEN v_keep_row ->> v_name_key IS NULL
            THEN COALESCE((v_drop_row ->> 'known_by_protagonist')::boolean, false)
        WHEN v_drop_row ->> v_name_key IS NOT NULL
             AND public.ldvelh_norm_for_game((v_keep_row ->> 'game_id')::uuid,
                                             v_keep_row ->> v_name_key)
               = public.ldvelh_norm_for_game((v_keep_row ->> 'game_id')::uuid,
                                             v_drop_row ->> v_name_key)
            THEN COALESCE((v_keep_row ->> 'known_by_protagonist')::boolean, false)
                 OR COALESCE((v_drop_row ->> 'known_by_protagonist')::boolean, false)
        ELSE (v_keep_row ->> 'known_by_protagonist')::boolean
    END;
    SELECT v_keep_row || COALESCE(jsonb_object_agg(dropped.key, CASE
               WHEN dropped.key = 'known_by_protagonist'
                   THEN to_jsonb(v_known)
               WHEN COALESCE(v_keep_row -> dropped.key, 'null'::jsonb) = 'null'::jsonb
                   THEN dropped.value
               WHEN dropped.key = 'is_mandatory'
                   THEN to_jsonb((v_keep_row ->> dropped.key)::boolean
                                 OR (dropped.value #>> '{}')::boolean)
               WHEN jsonb_typeof(dropped.value) = 'object'
                    AND jsonb_typeof(v_keep_row -> dropped.key) = 'object'
                   THEN dropped.value || (v_keep_row -> dropped.key)
               WHEN jsonb_typeof(dropped.value) = 'array'
                    AND jsonb_typeof(v_keep_row -> dropped.key) = 'array'
                   THEN (v_keep_row -> dropped.key) || COALESCE(
                       (SELECT jsonb_agg(elem) FROM jsonb_array_elements(dropped.value) AS elem
                         WHERE NOT (v_keep_row -> dropped.key) @> jsonb_build_array(elem)),
                       '[]'::jsonb)
               ELSE v_keep_row -> dropped.key
           END), '{}'::jsonb)
      INTO v_merged
      FROM jsonb_each(v_drop_row) AS dropped
     WHERE dropped.key <> ALL (ARRAY['id', 'game_id', 'name', 'label_suffix', 'created_at',
                                'updated_at', 'created_cycle', 'removed_cycle'])
       AND dropped.value <> 'null'::jsonb;
    SELECT string_agg(quote_ident(att.attname), ', ' ORDER BY att.attnum),
           string_agg('(jsonb_populate_record(NULL::' || v_table || ', $2)).'
                      || quote_ident(att.attname), ', ' ORDER BY att.attnum)
      INTO v_cols, v_vals
      FROM pg_attribute AS att
     WHERE att.attrelid = v_table AND att.attnum > 0 AND NOT att.attisdropped
       AND (v_merged -> att.attname::text) IS DISTINCT FROM (v_keep_row -> att.attname::text);
    IF v_cols IS NOT NULL THEN
        EXECUTE 'UPDATE ' || v_table || ' SET (' || v_cols || ') = ROW(' || v_vals || ')'
             || ' WHERE id = $1'
          USING p_keep, v_merged;
    END IF;
END $$;


-- migrate:down
-- The previous body (20261020000001_entity_identity.sql): known and mandatory flags ORed.
CREATE OR REPLACE FUNCTION public.identity_merge_fields(p_keep uuid, p_drop uuid, p_entity_type text)
        RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_table regclass := public.identity_domain_table(p_entity_type);
    v_keep_row jsonb := public.identity_domain_row(p_entity_type, p_keep);
    v_drop_row jsonb := public.identity_domain_row(p_entity_type, p_drop);
    v_merged jsonb;
    v_cols text;
    v_vals text;
BEGIN
    IF v_keep_row IS NULL OR v_drop_row IS NULL THEN
        RETURN;
    END IF;
    SELECT v_keep_row || COALESCE(jsonb_object_agg(dropped.key, CASE
               WHEN COALESCE(v_keep_row -> dropped.key, 'null'::jsonb) = 'null'::jsonb
                   THEN dropped.value
               WHEN dropped.key IN ('known_by_protagonist', 'is_mandatory')
                   THEN to_jsonb((v_keep_row ->> dropped.key)::boolean
                                 OR (dropped.value #>> '{}')::boolean)
               WHEN jsonb_typeof(dropped.value) = 'object'
                    AND jsonb_typeof(v_keep_row -> dropped.key) = 'object'
                   THEN dropped.value || (v_keep_row -> dropped.key)
               WHEN jsonb_typeof(dropped.value) = 'array'
                    AND jsonb_typeof(v_keep_row -> dropped.key) = 'array'
                   THEN (v_keep_row -> dropped.key) || COALESCE(
                       (SELECT jsonb_agg(elem) FROM jsonb_array_elements(dropped.value) AS elem
                         WHERE NOT (v_keep_row -> dropped.key) @> jsonb_build_array(elem)),
                       '[]'::jsonb)
               ELSE v_keep_row -> dropped.key
           END), '{}'::jsonb)
      INTO v_merged
      FROM jsonb_each(v_drop_row) AS dropped
     WHERE dropped.key <> ALL (ARRAY['id', 'game_id', 'name', 'label_suffix', 'created_at',
                                'updated_at', 'created_cycle', 'removed_cycle'])
       AND dropped.value <> 'null'::jsonb;
    SELECT string_agg(quote_ident(att.attname), ', ' ORDER BY att.attnum),
           string_agg('(jsonb_populate_record(NULL::' || v_table || ', $2)).'
                      || quote_ident(att.attname), ', ' ORDER BY att.attnum)
      INTO v_cols, v_vals
      FROM pg_attribute AS att
     WHERE att.attrelid = v_table AND att.attnum > 0 AND NOT att.attisdropped
       AND (v_merged -> att.attname::text) IS DISTINCT FROM (v_keep_row -> att.attname::text);
    IF v_cols IS NOT NULL THEN
        EXECUTE 'UPDATE ' || v_table || ' SET (' || v_cols || ') = ROW(' || v_vals || ')'
             || ' WHERE id = $1'
          USING p_keep, v_merged;
    END IF;
END $$;
