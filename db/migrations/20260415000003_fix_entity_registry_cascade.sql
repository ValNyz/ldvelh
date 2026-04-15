-- migrate:up
-- Fix: all FKs to entity_registry need ON DELETE CASCADE so game deletion works

ALTER TABLE arc_participants DROP CONSTRAINT arc_participants_entity_id_fkey,
    ADD CONSTRAINT arc_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES entity_registry(id) ON DELETE CASCADE;

ALTER TABLE chronology_participants DROP CONSTRAINT chronology_participants_entity_id_fkey,
    ADD CONSTRAINT chronology_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES entity_registry(id) ON DELETE CASCADE;

ALTER TABLE event_participants DROP CONSTRAINT event_participants_entity_id_fkey,
    ADD CONSTRAINT event_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES entity_registry(id) ON DELETE CASCADE;

ALTER TABLE fact_participants DROP CONSTRAINT fact_participants_entity_id_fkey,
    ADD CONSTRAINT fact_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES entity_registry(id) ON DELETE CASCADE;

ALTER TABLE inventory DROP CONSTRAINT inventory_owner_id_fkey,
    ADD CONSTRAINT inventory_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES entity_registry(id) ON DELETE CASCADE;

ALTER TABLE narrative_arcs DROP CONSTRAINT narrative_arcs_owner_id_fkey,
    ADD CONSTRAINT narrative_arcs_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES entity_registry(id) ON DELETE CASCADE;

ALTER TABLE relations DROP CONSTRAINT relations_source_id_fkey,
    ADD CONSTRAINT relations_source_id_fkey FOREIGN KEY (source_id) REFERENCES entity_registry(id) ON DELETE CASCADE;

ALTER TABLE relations DROP CONSTRAINT relations_target_id_fkey,
    ADD CONSTRAINT relations_target_id_fkey FOREIGN KEY (target_id) REFERENCES entity_registry(id) ON DELETE CASCADE;

-- migrate:down
-- Revert to non-cascading FKs (original state)

ALTER TABLE arc_participants DROP CONSTRAINT arc_participants_entity_id_fkey,
    ADD CONSTRAINT arc_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES entity_registry(id);

ALTER TABLE chronology_participants DROP CONSTRAINT chronology_participants_entity_id_fkey,
    ADD CONSTRAINT chronology_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES entity_registry(id);

ALTER TABLE event_participants DROP CONSTRAINT event_participants_entity_id_fkey,
    ADD CONSTRAINT event_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES entity_registry(id);

ALTER TABLE fact_participants DROP CONSTRAINT fact_participants_entity_id_fkey,
    ADD CONSTRAINT fact_participants_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES entity_registry(id);

ALTER TABLE inventory DROP CONSTRAINT inventory_owner_id_fkey,
    ADD CONSTRAINT inventory_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES entity_registry(id);

ALTER TABLE narrative_arcs DROP CONSTRAINT narrative_arcs_owner_id_fkey,
    ADD CONSTRAINT narrative_arcs_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES entity_registry(id);

ALTER TABLE relations DROP CONSTRAINT relations_source_id_fkey,
    ADD CONSTRAINT relations_source_id_fkey FOREIGN KEY (source_id) REFERENCES entity_registry(id);

ALTER TABLE relations DROP CONSTRAINT relations_target_id_fkey,
    ADD CONSTRAINT relations_target_id_fkey FOREIGN KEY (target_id) REFERENCES entity_registry(id);
