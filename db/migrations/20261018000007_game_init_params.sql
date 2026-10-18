-- migrate:up
-- #88: the wizard parameters of a game whose world is not created yet. A failed world
-- generation is retried from the game list with a bare __INIT__: the server reads these
-- back (with world_config, already on games) instead of generating a default world.
-- Size is capped at the API (api/request_types.py WizardPart, ManualEntities).
ALTER TABLE public.games
    ADD COLUMN character_data jsonb,
    ADD COLUMN manual_entities jsonb;

-- migrate:down
ALTER TABLE public.games
    DROP COLUMN manual_entities,
    DROP COLUMN character_data;
