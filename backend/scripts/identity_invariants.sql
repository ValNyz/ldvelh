-- Invariants of the identity model (#152), to check after the migration and the backfill
-- on a restored copy (CONTRIBUTING, "Deploying the identity migration"); read only:
--   psql -v ON_ERROR_STOP=1 -f backend/scripts/identity_invariants.sql
-- Every count of the first table must be 0 (the mentions total aside); then the name model
-- of the characters and the aliases by kind, for a look.
SET default_transaction_read_only = on;
\pset footer off
SELECT 'domain rows without registry at same id' AS check, count(*) FROM (
  SELECT id,'character' t FROM characters UNION ALL SELECT id,'location' FROM locations UNION ALL SELECT id,'organization' FROM organizations
  UNION ALL SELECT id,'object' FROM objects UNION ALL SELECT id,'protagonist' FROM protagonists UNION ALL SELECT id,'companion' FROM companions) d
  WHERE NOT EXISTS (SELECT 1 FROM entity_registry er WHERE er.id=d.id AND er.entity_type=d.t)
UNION ALL SELECT 'orphan registry rows', count(*) FROM entity_registry er WHERE merged_into IS NULL AND identity_domain_row(entity_type, id) IS NULL
UNION ALL SELECT 'registry name_norm NULL', count(*) FROM entity_registry WHERE name_norm IS NULL
UNION ALL SELECT 'alias_norm NULL', count(*) FROM entity_aliases WHERE alias_norm IS NULL
UNION ALL SELECT 'games without language', count(*) FROM games WHERE language IS NULL
UNION ALL SELECT 'entities without alias of their name_norm', count(*) FROM entity_registry er WHERE merged_into IS NULL AND NOT EXISTS (SELECT 1 FROM entity_aliases al WHERE al.entity_id=er.id AND al.alias_norm=er.name_norm)
UNION ALL SELECT 'characters name inconsistent', count(*) FROM characters c JOIN entity_registry er ON er.id=c.id WHERE c.name <> COALESCE(c.true_name,c.descriptor)||COALESCE(' ('||c.label_suffix||')','') OR er.name <> c.name OR er.name_norm <> ldvelh_norm_for_game(c.game_id, c.name)
UNION ALL SELECT 'registry norm stale', count(*) FROM entity_registry WHERE name_norm <> ldvelh_norm_for_game(game_id, name)
UNION ALL SELECT 'alias norm stale', count(*) FROM entity_aliases WHERE alias_norm <> ldvelh_norm_for_game(game_id, alias)
UNION ALL SELECT 'companions unregistered', count(*) FROM companions cm WHERE NOT EXISTS (SELECT 1 FROM entity_registry er WHERE er.id=cm.id)
UNION ALL SELECT 'mentions to missing entities', count(*) FROM entity_mentions m WHERE NOT EXISTS (SELECT 1 FROM entity_registry er WHERE er.id=m.entity_id)
UNION ALL SELECT 'mentions total', count(*) FROM entity_mentions
UNION ALL SELECT 'unknown characters whose descriptor is their true name', count(*) FROM characters c WHERE NOT COALESCE(c.known_by_protagonist, false) AND c.true_name IS NOT NULL AND ldvelh_norm_for_game(c.game_id, c.descriptor) = ldvelh_norm_for_game(c.game_id, c.true_name)
UNION ALL SELECT 'display_for_player NULL', count(*) FROM entity_registry er WHERE display_for_player(er.id) IS NULL;
SELECT c.name, c.true_name, c.descriptor, c.known_by_protagonist k, display_for_player(c.id) shown FROM characters c ORDER BY c.created_at;
SELECT kind, source, known, secret, count(*) FROM entity_aliases GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
