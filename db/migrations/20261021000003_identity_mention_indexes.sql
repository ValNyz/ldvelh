-- migrate:up
-- Reads of the mentions that follow the scene, not the game (#155). The mentions of a
-- set of entities (mentioned_elsewhere, the cards' last turn): one probe per entity of
-- the game, never a pass over every mention of the game.
CREATE INDEX idx_entity_mentions_game_entity ON public.entity_mentions (game_id, entity_id);
-- The turn rank of a message (a card's "seen at turn N"): the count of the game's
-- assistant messages up to it, read from the index alone.
CREATE INDEX idx_messages_game_role_sequence ON public.messages
    (game_id, role, sequence, created_at);

-- migrate:down
DROP INDEX IF EXISTS public.idx_messages_game_role_sequence;
DROP INDEX IF EXISTS public.idx_entity_mentions_game_entity;
