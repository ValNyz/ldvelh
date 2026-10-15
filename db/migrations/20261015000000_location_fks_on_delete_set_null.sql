-- migrate:up
-- #11: rollback deletes locations/organizations created after the target cycle.
-- References to them must not block the delete (and leave the game half rolled back):
-- clear them instead.
ALTER TABLE public.characters DROP CONSTRAINT characters_residence_id_fkey;
ALTER TABLE public.characters ADD CONSTRAINT characters_residence_id_fkey FOREIGN KEY (residence_id) REFERENCES public.locations(id) ON DELETE SET NULL;
ALTER TABLE public.characters DROP CONSTRAINT characters_workplace_id_fkey;
ALTER TABLE public.characters ADD CONSTRAINT characters_workplace_id_fkey FOREIGN KEY (workplace_id) REFERENCES public.locations(id) ON DELETE SET NULL;
ALTER TABLE public.chronology DROP CONSTRAINT chronology_location_id_fkey;
ALTER TABLE public.chronology ADD CONSTRAINT chronology_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id) ON DELETE SET NULL;
ALTER TABLE public.events DROP CONSTRAINT events_location_id_fkey;
ALTER TABLE public.events ADD CONSTRAINT events_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id) ON DELETE SET NULL;
ALTER TABLE public.facts DROP CONSTRAINT facts_location_id_fkey;
ALTER TABLE public.facts ADD CONSTRAINT facts_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id) ON DELETE SET NULL;
ALTER TABLE public.games DROP CONSTRAINT fk_games_current_location;
ALTER TABLE public.games ADD CONSTRAINT fk_games_current_location FOREIGN KEY (current_location_id) REFERENCES public.locations(id) ON DELETE SET NULL;
ALTER TABLE public.protagonists DROP CONSTRAINT fk_protagonists_employer;
ALTER TABLE public.protagonists ADD CONSTRAINT fk_protagonists_employer FOREIGN KEY (employer_id) REFERENCES public.organizations(id) ON DELETE SET NULL;
ALTER TABLE public.protagonists DROP CONSTRAINT fk_protagonists_residence;
ALTER TABLE public.protagonists ADD CONSTRAINT fk_protagonists_residence FOREIGN KEY (residence_id) REFERENCES public.locations(id) ON DELETE SET NULL;
ALTER TABLE public.locations DROP CONSTRAINT locations_parent_id_fkey;
ALTER TABLE public.locations ADD CONSTRAINT locations_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.locations(id) ON DELETE SET NULL;
ALTER TABLE public.messages DROP CONSTRAINT messages_location_id_fkey;
ALTER TABLE public.messages ADD CONSTRAINT messages_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id) ON DELETE SET NULL;
ALTER TABLE public.narrative_seeds DROP CONSTRAINT narrative_seeds_location_id_fkey;
ALTER TABLE public.narrative_seeds ADD CONSTRAINT narrative_seeds_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id) ON DELETE SET NULL;
ALTER TABLE public.organizations DROP CONSTRAINT organizations_headquarters_id_fkey;
ALTER TABLE public.organizations ADD CONSTRAINT organizations_headquarters_id_fkey FOREIGN KEY (headquarters_id) REFERENCES public.locations(id) ON DELETE SET NULL;

-- migrate:down
ALTER TABLE public.characters DROP CONSTRAINT characters_residence_id_fkey;
ALTER TABLE public.characters ADD CONSTRAINT characters_residence_id_fkey FOREIGN KEY (residence_id) REFERENCES public.locations(id);
ALTER TABLE public.characters DROP CONSTRAINT characters_workplace_id_fkey;
ALTER TABLE public.characters ADD CONSTRAINT characters_workplace_id_fkey FOREIGN KEY (workplace_id) REFERENCES public.locations(id);
ALTER TABLE public.chronology DROP CONSTRAINT chronology_location_id_fkey;
ALTER TABLE public.chronology ADD CONSTRAINT chronology_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id);
ALTER TABLE public.events DROP CONSTRAINT events_location_id_fkey;
ALTER TABLE public.events ADD CONSTRAINT events_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id);
ALTER TABLE public.facts DROP CONSTRAINT facts_location_id_fkey;
ALTER TABLE public.facts ADD CONSTRAINT facts_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id);
ALTER TABLE public.games DROP CONSTRAINT fk_games_current_location;
ALTER TABLE public.games ADD CONSTRAINT fk_games_current_location FOREIGN KEY (current_location_id) REFERENCES public.locations(id);
ALTER TABLE public.protagonists DROP CONSTRAINT fk_protagonists_employer;
ALTER TABLE public.protagonists ADD CONSTRAINT fk_protagonists_employer FOREIGN KEY (employer_id) REFERENCES public.organizations(id);
ALTER TABLE public.protagonists DROP CONSTRAINT fk_protagonists_residence;
ALTER TABLE public.protagonists ADD CONSTRAINT fk_protagonists_residence FOREIGN KEY (residence_id) REFERENCES public.locations(id);
ALTER TABLE public.locations DROP CONSTRAINT locations_parent_id_fkey;
ALTER TABLE public.locations ADD CONSTRAINT locations_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.locations(id);
ALTER TABLE public.messages DROP CONSTRAINT messages_location_id_fkey;
ALTER TABLE public.messages ADD CONSTRAINT messages_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id);
ALTER TABLE public.narrative_seeds DROP CONSTRAINT narrative_seeds_location_id_fkey;
ALTER TABLE public.narrative_seeds ADD CONSTRAINT narrative_seeds_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id);
ALTER TABLE public.organizations DROP CONSTRAINT organizations_headquarters_id_fkey;
ALTER TABLE public.organizations ADD CONSTRAINT organizations_headquarters_id_fkey FOREIGN KEY (headquarters_id) REFERENCES public.locations(id);
