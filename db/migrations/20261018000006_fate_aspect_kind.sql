-- migrate:up
-- #93: the kind of a protagonist's Fate aspect (high concept, trouble, other) was implied
-- by its position in character_fate.aspects (jsonb), so an empty wizard slot shifted the
-- labels. One row per aspect now stores its kind; at most one high concept and one
-- trouble per character.
CREATE TABLE public.aspects_fate (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    game_id uuid NOT NULL REFERENCES public.games(id) ON DELETE CASCADE,
    "position" integer NOT NULL,
    name text NOT NULL CONSTRAINT aspects_fate_name_check CHECK (btrim(name) <> ''),
    kind text DEFAULT 'other' NOT NULL
        CONSTRAINT aspects_fate_kind_check CHECK (kind IN ('high_concept', 'trouble', 'other')),
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT aspects_fate_game_id_position_key UNIQUE (game_id, "position")
);
CREATE UNIQUE INDEX aspects_fate_one_high_concept ON public.aspects_fate (game_id)
    WHERE kind = 'high_concept';
CREATE UNIQUE INDEX aspects_fate_one_trouble ON public.aspects_fate (game_id)
    WHERE kind = 'trouble';

-- Backfill, best effort: the wizard input was not stored, so whether a slot was left
-- empty is unknown.
-- * A row holding typed dicts ({"name"|"text", "type"}) keeps each valid type; untyped
--   or invalid entries become 'other'.
-- * A plain string list (what create_character wrote) with two aspects or more: the
--   first is the high concept and the second the trouble (the order create_character
--   used when the wizard filled both slots); everything else, and a lone aspect, 'other'.
-- * Blank entries are dropped; a second high concept or trouble becomes 'other'.
WITH elems AS (
    SELECT cf.game_id, e.ord,
           CASE jsonb_typeof(e.val)
               WHEN 'string' THEN e.val #>> '{}'
               WHEN 'object' THEN COALESCE(NULLIF(btrim(e.val ->> 'name'), ''), e.val ->> 'text')
           END AS name,
           CASE WHEN jsonb_typeof(e.val) = 'object' THEN e.val ->> 'type' END AS dict_type,
           bool_or(jsonb_typeof(e.val) = 'object' AND e.val ? 'type')
               OVER (PARTITION BY cf.game_id) AS typed
    FROM public.character_fate cf
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(cf.aspects) = 'array' THEN cf.aspects ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS e(val, ord)
), kept AS (
    SELECT game_id, ord, name, dict_type, typed,
           row_number() OVER (PARTITION BY game_id ORDER BY ord) - 1 AS pos,
           count(*) OVER (PARTITION BY game_id) AS n
    FROM elems
    WHERE name IS NOT NULL AND btrim(name) <> ''
), kinded AS (
    SELECT game_id, pos, name,
           CASE
               WHEN typed THEN CASE WHEN dict_type IN ('high_concept', 'trouble', 'other')
                                    THEN dict_type ELSE 'other' END
               WHEN n >= 2 AND pos = 0 THEN 'high_concept'
               WHEN n >= 2 AND pos = 1 THEN 'trouble'
               ELSE 'other'
           END AS kind
    FROM kept
)
INSERT INTO public.aspects_fate (game_id, "position", name, kind)
SELECT game_id, pos, name,
       CASE WHEN kind <> 'other'
                 AND row_number() OVER (PARTITION BY game_id, kind ORDER BY pos) > 1
            THEN 'other' ELSE kind END
FROM kinded;

ALTER TABLE public.character_fate DROP COLUMN aspects;

-- migrate:down
-- Back to the jsonb string list, in position order (the kind is lost, as before).
ALTER TABLE public.character_fate ADD COLUMN aspects jsonb DEFAULT '[]'::jsonb;
UPDATE public.character_fate cf
SET aspects = COALESCE(
    (SELECT jsonb_agg(a.name ORDER BY a."position") FROM public.aspects_fate a
     WHERE a.game_id = cf.game_id),
    '[]'::jsonb);
DROP TABLE public.aspects_fate;
