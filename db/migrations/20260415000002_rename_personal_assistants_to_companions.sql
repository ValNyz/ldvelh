-- migrate:up
ALTER TABLE personal_assistants RENAME TO companions;

-- migrate:down
ALTER TABLE companions RENAME TO personal_assistants;
