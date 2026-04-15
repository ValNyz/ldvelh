-- migrate:up
ALTER TABLE protagonists ADD COLUMN gender VARCHAR(20);

-- migrate:down
ALTER TABLE protagonists DROP COLUMN gender;
