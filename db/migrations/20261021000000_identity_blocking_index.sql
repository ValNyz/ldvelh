-- migrate:up
-- Candidate blocking (#154, spec §4.5.2): the trigram generator looks up, among the
-- aliases of one game, those holding a fuzzy form of a word of the narration
-- (`word <% alias_norm`). A GIN index on (game_id, alias_norm) serves both conditions in
-- one scan: with many games in the table the planner would otherwise take the btree on
-- game_id and compare every alias of the game with every word. btree_gin (PostgreSQL
-- contrib, like pg_trgm) gives game_id its GIN operator class.
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE INDEX idx_entity_aliases_game_norm_trgm ON public.entity_aliases
    USING gin (game_id, alias_norm public.gin_trgm_ops);

-- migrate:down
DROP INDEX IF EXISTS public.idx_entity_aliases_game_norm_trgm;
DROP EXTENSION IF EXISTS btree_gin;
