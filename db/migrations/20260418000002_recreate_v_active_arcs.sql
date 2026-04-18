-- migrate:up
-- Recreate v_active_arcs view after CASCADE dropped it (columns removed:
-- situation, desire, obstacle, potential_triggers, stakes, deadline_cycle,
-- objective, steps, progress).

CREATE OR REPLACE VIEW public.v_active_arcs AS
 SELECT na.id,
    na.game_id,
    na.title,
    na.domain,
    na.description,
    na.intensity,
    array_agg(jsonb_build_object('name', er.name, 'type', er.entity_type, 'role', ap.role))
      FILTER (WHERE (er.name IS NOT NULL)) AS participants
   FROM ((public.narrative_arcs na
     LEFT JOIN public.arc_participants ap ON ((ap.arc_id = na.id)))
     LEFT JOIN public.entity_registry er ON ((ap.entity_id = er.id)))
  WHERE (na.resolved = false)
  GROUP BY na.id;

-- migrate:down
DROP VIEW IF EXISTS public.v_active_arcs;
