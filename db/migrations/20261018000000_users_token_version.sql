-- migrate:up
-- #83: every JWT carries the user's token_version; bumping it (password change, logout)
-- revokes all the sessions issued before.
ALTER TABLE users ADD COLUMN token_version integer NOT NULL DEFAULT 0;

-- migrate:down
ALTER TABLE users DROP COLUMN token_version;
