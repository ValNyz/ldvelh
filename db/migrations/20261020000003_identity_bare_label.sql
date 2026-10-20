-- migrate:up
-- The label prompts read (#153, ruling R14): the registry label without its internal
-- homonym suffix. What a prompt knows does not change (a character still reads its true
-- name, else its descriptor; the three-state rules come later): only the suffix, which
-- the narrator could echo into a narration, goes.

-- The bare label of an entity: a character's true name, else its descriptor; the domain
-- name of any other entity; the registry label when there is no domain row. Merges
-- followed.
CREATE FUNCTION public.identity_bare_label(p_entity_id uuid) RETURNS text
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(
               CASE WHEN er.entity_type = 'character'
                    THEN (SELECT COALESCE(ch.true_name, ch.descriptor)
                            FROM public.characters AS ch WHERE ch.id = er.id)
                    ELSE public.identity_domain_row(er.entity_type, er.id) ->> 'name'
               END,
               er.name)
      FROM public.entity_registry AS er
     WHERE er.id = public.entity_follow_merge(p_entity_id)
$$;

CREATE OR REPLACE VIEW public.v_active_relations AS
 SELECT r.id AS relation_id,
    r.game_id,
    r.type AS relation_type,
    r.source_id,
    es.entity_type AS source_type,
    public.identity_bare_label(es.id)::character varying(255) AS source_name,
    r.target_id,
    et.entity_type AS target_type,
    public.identity_bare_label(et.id)::character varying(255) AS target_name,
    r.level,
    r.context,
    r.known_by_protagonist,
    r.start_cycle
   FROM ((public.relations r
     JOIN public.entity_registry es ON ((r.source_id = es.id)))
     JOIN public.entity_registry et ON ((r.target_id = et.id)))
  WHERE (r.end_cycle IS NULL);


-- migrate:down
CREATE OR REPLACE VIEW public.v_active_relations AS
 SELECT r.id AS relation_id,
    r.game_id,
    r.type AS relation_type,
    r.source_id,
    es.entity_type AS source_type,
    es.name AS source_name,
    r.target_id,
    et.entity_type AS target_type,
    et.name AS target_name,
    r.level,
    r.context,
    r.known_by_protagonist,
    r.start_cycle
   FROM ((public.relations r
     JOIN public.entity_registry es ON ((r.source_id = es.id)))
     JOIN public.entity_registry et ON ((r.target_id = et.id)))
  WHERE (r.end_cycle IS NULL);

DROP FUNCTION public.identity_bare_label(uuid);
