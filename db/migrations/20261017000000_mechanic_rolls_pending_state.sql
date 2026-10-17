-- migrate:up
-- #32: a roll waiting for an aspect invocation is explicit (status), resolved once, at most
-- one per game, and keeps the player's message so the resumed turn narrates that action.
ALTER TABLE mechanic_rolls
  ADD COLUMN status varchar(10) NOT NULL DEFAULT 'resolved'
    CHECK (status IN ('pending', 'resolved', 'expired')),
  ADD COLUMN player_message text;
UPDATE mechanic_rolls SET status = 'expired' WHERE message_id IS NULL;
CREATE UNIQUE INDEX mechanic_rolls_one_pending_per_game
  ON mechanic_rolls (game_id) WHERE status = 'pending';

-- migrate:down
DROP INDEX mechanic_rolls_one_pending_per_game;
ALTER TABLE mechanic_rolls
  DROP COLUMN player_message,
  DROP COLUMN status;
