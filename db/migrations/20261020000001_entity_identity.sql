-- migrate:up
-- P6 entity identity (#152), spec §4.2 and §4.12.
--
-- Section 1: normalisation. ldvelh_norm(text, params) is IMMUTABLE and names no word of
-- any language: the articles, elisions, ordinal markers and apostrophes come from the
-- language packs (backend/packs/lang/<lang>.yaml), synchronised into lang_packs at startup
-- and by the test harness. ldvelh_norm_for_game reads the pack of a game's language.
-- backend/services/identity/normalize.py is the Python mirror (same steps, parity test).
-- lang_packs is configuration, not world state: it is not journaled.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

-- unaccent() is STABLE (it looks its dictionary up by name); with the dictionary named
-- explicitly the result only depends on the input, so this wrapper may be IMMUTABLE.
CREATE FUNCTION public.ldvelh_unaccent(p_text text) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, p_text) $$;

-- Steps 1-2 of ldvelh_norm: lower case, unaccent, every Unicode space as a plain space,
-- every pack apostrophe as a plain one.
CREATE FUNCTION public.ldvelh_norm_fold(p_text text, p_params jsonb) RETURNS text
    LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
    AS $$
DECLARE
    v_out text;
    v_apostrophe text;
BEGIN
    v_out := regexp_replace(public.ldvelh_unaccent(lower(p_text)),
                            '[\t\n\v\f\r   -     　]',
                            ' ', 'g');
    FOR v_apostrophe IN SELECT jsonb_array_elements_text(p_params -> 'apostrophes') LOOP
        v_out := replace(v_out, v_apostrophe, '''');
    END LOOP;
    RETURN v_out;
END $$;

-- 3. drop an ordinal marker before a number; 4. replace by a space every character that is
-- not a letter, a digit, a space, an apostrophe or a hyphen; 5. keep a hyphen only between
-- two letters (a space otherwise), collapse spaces; 6. drop one leading elision (prefix) or
-- article (whole word) when something follows it; 7. drop apostrophes, collapse spaces.
--
-- p_params is what packs.loader.norm_params writes into lang_packs: the articles, elisions
-- and ordinal markers already folded (steps 1-2), longest first, marked "folded": true;
-- the function raises on params without that mark. About 13 µs a call: meant for the
-- trigger-filled name_norm/alias_norm columns and for one ldvelh_norm_for_game($1) per
-- query, not for a per-row predicate of a query.
CREATE FUNCTION public.ldvelh_norm(p_text text, p_params jsonb) RETURNS text
    LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
    AS $$
DECLARE
    v_out text;
    v_markers text;
    v_prefix text;
    v_head text;
    v_stripped boolean := false;
BEGIN
    IF (p_params -> 'folded') IS DISTINCT FROM 'true'::jsonb THEN
        RAISE EXCEPTION 'ldvelh_norm: unfolded params, see norm_params';
    END IF;
    v_out := public.ldvelh_norm_fold(p_text, p_params);

    SELECT string_agg(regexp_replace(mrk.entry, '([^[:alnum:] ])', '\\\1', 'g'), '|'
                      ORDER BY mrk.pos)
      INTO v_markers
      FROM jsonb_array_elements_text(p_params -> 'ordinal_markers')
           WITH ORDINALITY AS mrk(entry, pos);
    IF v_markers IS NOT NULL THEN
        v_out := regexp_replace(v_out, '(^|[^[:alnum:]])(' || v_markers || ') *(?=[0-9])',
                                '\1', 'g');
    END IF;

    v_out := regexp_replace(v_out, '[^[:alnum:] ''-]', ' ', 'g');
    v_out := regexp_replace(v_out, '(?<![[:alpha:]])-|-(?![[:alpha:]])', ' ', 'g');
    v_out := btrim(regexp_replace(v_out, ' +', ' ', 'g'), ' ');

    FOR v_prefix IN SELECT jsonb_array_elements_text(p_params -> 'elisions') LOOP
        IF length(v_out) > length(v_prefix) AND left(v_out, length(v_prefix)) = v_prefix THEN
            v_out := ltrim(substr(v_out, length(v_prefix) + 1), ' ');
            v_stripped := true;
            EXIT;
        END IF;
    END LOOP;
    IF NOT v_stripped AND position(' ' IN v_out) > 0 THEN
        v_head := split_part(v_out, ' ', 1);
        IF (p_params -> 'articles') ? v_head THEN
            v_out := substr(v_out, length(v_head) + 2);
        END IF;
    END IF;

    RETURN btrim(regexp_replace(replace(v_out, '''', ''), ' +', ' ', 'g'), ' ');
END $$;

-- IF NOT EXISTS: scripts/sync_lang_packs.py creates and fills it before `dbmate up` (same
-- DDL), so that the data section below can normalise the names of a game with a language.
CREATE TABLE IF NOT EXISTS public.lang_packs (
    lang text PRIMARY KEY,
    version text NOT NULL,
    params jsonb NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

-- The language of a game (spec §4.12): the pack its names are normalised with. Nullable
-- here; the backfill (Task 9) gives every existing game one, the PR 1b migration sets it
-- NOT NULL. A new game gets IdentityConfig.default_language at creation.
ALTER TABLE public.games
    ADD COLUMN language text,
    ADD CONSTRAINT games_language_fkey FOREIGN KEY (language)
        REFERENCES public.lang_packs(lang) DEFERRABLE INITIALLY IMMEDIATE;

-- The pack parameters of a game's language; raises when the game has no language or its
-- pack is not synchronised.
CREATE FUNCTION public.ldvelh_lang_params(p_game_id uuid) RETURNS jsonb
    LANGUAGE plpgsql STABLE PARALLEL SAFE
    AS $$
DECLARE
    v_lang text;
    v_params jsonb;
BEGIN
    SELECT gm.language INTO v_lang FROM public.games AS gm WHERE gm.id = p_game_id;
    SELECT lp.params INTO v_params FROM public.lang_packs AS lp WHERE lp.lang = v_lang;
    IF v_params IS NULL THEN
        RAISE EXCEPTION 'missing lang pack %', v_lang;
    END IF;
    RETURN v_params;
END $$;

-- The normalisation of a game's language (raises like ldvelh_lang_params).
CREATE FUNCTION public.ldvelh_norm_for_game(p_game_id uuid, p_text text) RETURNS text
    LANGUAGE plpgsql STABLE PARALLEL SAFE
    AS $$
BEGIN
    RETURN public.ldvelh_norm(p_text, public.ldvelh_lang_params(p_game_id));
END $$;

-- Section 2: the identity schema (spec §4.2, §4.7). The registry id IS the domain id
-- (characters.id = entity_registry.id, idem locations, organizations, objects, the
-- protagonist and the companion); names serve display and search only.
--
-- P5b replay (world_changes_undo): every foreign key the replay can trip is DEFERRABLE
-- INITIALLY IMMEDIATE, and every trigger below with a side effect or a computed column
-- returns at once under ldvelh.replay: the replayed journal already holds their effects
-- (registry rows, aliases, names, norms, handles), re-inserted as they were.

DROP TRIGGER register_character ON public.characters;
DROP TRIGGER register_location ON public.locations;
DROP TRIGGER register_object ON public.objects;
DROP TRIGGER register_organization ON public.organizations;
DROP TRIGGER register_protagonist ON public.protagonists;
DROP TRIGGER update_registry_character ON public.characters;
DROP TRIGGER update_registry_location ON public.locations;
DROP TRIGGER update_registry_object ON public.objects;
DROP TRIGGER update_registry_organization ON public.organizations;
DROP FUNCTION public.register_entity();
DROP FUNCTION public.update_entity_registry_name();

-- 2.1 Registry. name_norm is filled by identity_norm_fill (not GENERATED: it reads the pack
-- of the game's language); existing rows get it in the data section, and the column is set
-- NOT NULL at the end of this migration when they all have one. handle (E<n> in prompts) is
-- a per-game sequence set by identity_assign_handle; merged_into marks a merge tombstone,
-- deleted with the entity it points to (nothing is left for it to redirect to).
ALTER TABLE public.entity_registry
    DROP CONSTRAINT entity_registry_game_id_entity_type_name_key,
    ADD COLUMN name_norm text,
    ADD COLUMN handle integer,
    ADD COLUMN merged_into uuid,
    ADD COLUMN created_turn_id uuid,
    ADD CONSTRAINT entity_registry_merged_into_fkey FOREIGN KEY (merged_into)
        REFERENCES public.entity_registry(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    ADD CONSTRAINT entity_registry_created_turn_id_fkey FOREIGN KEY (created_turn_id)
        REFERENCES public.turns(id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE,
    ADD CONSTRAINT entity_registry_entity_type_check CHECK (entity_type IN (
        'character', 'location', 'organization', 'object', 'protagonist', 'companion'));

UPDATE public.entity_registry er
   SET handle = numbered.rank
  FROM (SELECT id, row_number() OVER (PARTITION BY game_id ORDER BY entity_type, name, id)
                   AS rank
          FROM public.entity_registry) AS numbered
 WHERE numbered.id = er.id;
ALTER TABLE public.entity_registry
    ALTER COLUMN handle SET NOT NULL,
    ADD CONSTRAINT entity_registry_game_id_handle_key UNIQUE (game_id, handle);
CREATE INDEX idx_entity_registry_norm ON public.entity_registry (game_id, entity_type, name_norm);
-- Referencing columns: a registry or turn delete looks them up (cascade, SET NULL).
CREATE INDEX idx_entity_registry_merged_into ON public.entity_registry (merged_into)
    WHERE merged_into IS NOT NULL;
CREATE INDEX idx_entity_registry_created_turn ON public.entity_registry (created_turn_id)
    WHERE created_turn_id IS NOT NULL;

-- 2.2 Domain tables. The normalised uniqueness of the registry replaces their
-- UNIQUE (game_id, name): one source of uniqueness.
ALTER TABLE public.characters RENAME COLUMN unknown_name TO descriptor;
-- label_suffix: internal only, it tells two homonyms apart in the label (name, registry,
-- normalised uniqueness), never in what the player reads (true_name, descriptor). Only
-- characters need it: their name is derived; another entity's name is its label, which
-- takes a suffix directly.
ALTER TABLE public.characters
    DROP CONSTRAINT characters_game_id_name_key,
    ADD COLUMN true_name character varying(255),
    ADD COLUMN label_suffix text;
-- Until the data section classifies them, existing characters keep their label as their
-- true name: always valid for the CHECK below.
UPDATE public.characters SET true_name = name WHERE true_name IS NULL;
ALTER TABLE public.characters
    ADD CONSTRAINT characters_true_name_or_descriptor
        CHECK (true_name IS NOT NULL OR descriptor IS NOT NULL);
ALTER TABLE public.locations DROP CONSTRAINT locations_game_id_name_key;
ALTER TABLE public.organizations DROP CONSTRAINT organizations_game_id_name_key;
ALTER TABLE public.objects DROP CONSTRAINT objects_game_id_name_key;
-- objects.canonical_name is dropped in section 4: the data section first turns it into a
-- 'label' alias.

-- Facts: the three-state knowledge model (§4.8) and F<n> handles, numbered by creation.
ALTER TABLE public.facts
    ADD COLUMN known boolean NOT NULL DEFAULT true,
    ADD COLUMN secret boolean NOT NULL DEFAULT false,
    ADD COLUMN handle integer;
ALTER TABLE public.facts DISABLE TRIGGER facts_no_update;
UPDATE public.facts ft
   SET handle = numbered.rank
  FROM (SELECT id, row_number() OVER (PARTITION BY game_id ORDER BY created_at, id) AS rank
          FROM public.facts) AS numbered
 WHERE numbered.id = ft.id;
ALTER TABLE public.facts ENABLE TRIGGER facts_no_update;
ALTER TABLE public.facts
    ALTER COLUMN handle SET NOT NULL,
    ADD CONSTRAINT facts_game_id_handle_key UNIQUE (game_id, handle);

-- 2.3 New tables. entity_aliases, entity_mentions and entity_merges are world state
-- (journaled below); identity_events is telemetry, kept by a rollback like llm_calls.
CREATE TABLE public.entity_aliases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    entity_type character varying(50) NOT NULL,
    alias text NOT NULL,
    -- NOT NULL from section 4, like entity_registry.name_norm: the aliases the data
    -- section gives the entities of a game without language get theirs from the backfill.
    alias_norm text,
    kind text NOT NULL CHECK (kind IN ('true_name', 'descriptor', 'short', 'title',
                                       'former_name', 'nickname', 'label')),
    -- The PC knows this form (state 1 of §4.8); secret: guarded by the Director (state 3).
    known boolean NOT NULL,
    secret boolean NOT NULL DEFAULT false,
    source text NOT NULL CHECK (source IN ('world_gen', 'extractor', 'resolver', 'reveal',
                                           'director', 'migration', 'system')),
    -- Short excerpt of the turn behind the alias: never logged above DEBUG.
    evidence text,
    turn_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    -- An alias may be shared by two entities: the ambiguity is resolved downstream.
    CONSTRAINT entity_aliases_game_id_entity_id_alias_norm_key
        UNIQUE (game_id, entity_id, alias_norm),
    CONSTRAINT entity_aliases_game_id_fkey FOREIGN KEY (game_id)
        REFERENCES public.games(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT entity_aliases_entity_id_fkey FOREIGN KEY (entity_id)
        REFERENCES public.entity_registry(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT entity_aliases_turn_id_fkey FOREIGN KEY (turn_id)
        REFERENCES public.turns(id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE
);
CREATE INDEX idx_entity_aliases_norm_trgm ON public.entity_aliases
    USING gin (alias_norm public.gin_trgm_ops);
CREATE INDEX idx_entity_aliases_game_norm ON public.entity_aliases (game_id, alias_norm);
CREATE INDEX idx_entity_aliases_entity ON public.entity_aliases (entity_id);
CREATE INDEX idx_entity_aliases_turn ON public.entity_aliases (turn_id) WHERE turn_id IS NOT NULL;

-- Replaces messages.narrator_context: what each span of a narration was resolved to. The
-- entity is the one of the decision; a read follows merged_into.
CREATE TABLE public.entity_mentions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    message_id uuid NOT NULL,
    turn_id uuid,
    start_pos integer NOT NULL,
    end_pos integer NOT NULL,
    surface text NOT NULL,
    entity_id uuid NOT NULL,
    decision text NOT NULL CHECK (decision IN ('match', 'alias', 'new', 'deterministic')),
    evidence text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT entity_mentions_message_id_start_pos_end_pos_key
        UNIQUE (message_id, start_pos, end_pos),
    CONSTRAINT entity_mentions_game_id_fkey FOREIGN KEY (game_id)
        REFERENCES public.games(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT entity_mentions_message_id_fkey FOREIGN KEY (message_id)
        REFERENCES public.messages(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT entity_mentions_turn_id_fkey FOREIGN KEY (turn_id)
        REFERENCES public.turns(id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT entity_mentions_entity_id_fkey FOREIGN KEY (entity_id)
        REFERENCES public.entity_registry(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);
CREATE INDEX idx_entity_mentions_game_message ON public.entity_mentions (game_id, message_id);
CREATE INDEX idx_entity_mentions_entity ON public.entity_mentions (entity_id);
CREATE INDEX idx_entity_mentions_turn ON public.entity_mentions (turn_id)
    WHERE turn_id IS NOT NULL;

-- Audit of merge_entities, with the snapshots of what the merge removed or moved.
CREATE TABLE public.entity_merges (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    kept_id uuid NOT NULL,
    dropped_id uuid NOT NULL,
    dropped_registry jsonb NOT NULL,
    dropped_row jsonb,
    moved_edges jsonb NOT NULL,
    reason text,
    evidence text,
    turn_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT entity_merges_game_id_fkey FOREIGN KEY (game_id)
        REFERENCES public.games(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT entity_merges_kept_id_fkey FOREIGN KEY (kept_id)
        REFERENCES public.entity_registry(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT entity_merges_dropped_id_fkey FOREIGN KEY (dropped_id)
        REFERENCES public.entity_registry(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT entity_merges_turn_id_fkey FOREIGN KEY (turn_id)
        REFERENCES public.turns(id) ON DELETE SET NULL DEFERRABLE INITIALLY IMMEDIATE
);
CREATE INDEX idx_entity_merges_kept ON public.entity_merges (kept_id);
CREATE INDEX idx_entity_merges_dropped ON public.entity_merges (dropped_id);
CREATE INDEX idx_entity_merges_turn ON public.entity_merges (turn_id) WHERE turn_id IS NOT NULL;

-- Telemetry, except three kinds that are durable state (identity_event_is_state): the
-- marks of the identity backfill ('identity_backfill': a game done, never classified
-- again; 'identity_exception': a correction applied, never applied again) and the handles
-- the journal of a pre-migration turn holds ('handle_reserved', read by
-- identity_assign_handle). Any purge of identity_events must keep them.
CREATE TABLE public.identity_events (
    id bigserial PRIMARY KEY,
    game_id uuid NOT NULL REFERENCES public.games(id) ON DELETE CASCADE,
    turn_id uuid REFERENCES public.turns(id) ON DELETE SET NULL,
    kind text NOT NULL,
    entity_id uuid,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_identity_events_game_created ON public.identity_events (game_id, created_at);
CREATE INDEX idx_identity_events_turn ON public.identity_events (turn_id)
    WHERE turn_id IS NOT NULL;
-- identity_assign_handle reads the reservations of a game on every entity or fact insert.
CREATE INDEX idx_identity_events_handle_reserved ON public.identity_events (game_id)
    WHERE kind = 'handle_reserved';

-- True for the kinds of identity_events that are state, not telemetry: a purge keeps them.
CREATE FUNCTION public.identity_event_is_state(p_kind text) RETURNS boolean
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$ SELECT p_kind IN ('identity_backfill', 'identity_exception', 'handle_reserved') $$;

SELECT public.ldvelh_journal('entity_aliases');
SELECT public.ldvelh_journal('entity_mentions');
SELECT public.ldvelh_journal('entity_merges');

-- 2.4 Triggers.

-- name_norm / alias_norm: the normalisation of the game's language; raises
-- 'missing lang pack <lang>' when the game has none.
CREATE FUNCTION public.identity_norm_fill() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF current_setting('ldvelh.replay', true) = 'on' THEN
        RETURN NEW;
    END IF;
    IF TG_TABLE_NAME = 'entity_aliases' THEN
        NEW.alias_norm := public.ldvelh_norm_for_game(NEW.game_id, NEW.alias);
    ELSE
        NEW.name_norm := public.ldvelh_norm_for_game(NEW.game_id, NEW.name);
    END IF;
    RETURN NEW;
END $$;

-- E<n> / F<n>: next handle of the game, unless one is given (kept as it is), past the
-- reserved ones: the handles the journal of a turn played before this migration holds for
-- an entity or a fact no longer there (identity_events 'handle_reserved', section 3.3):
-- undoing that turn brings the row back with it, so no new row may take it meanwhile.
CREATE FUNCTION public.identity_assign_handle() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF current_setting('ldvelh.replay', true) = 'on' THEN
        RETURN NEW;
    END IF;
    IF NEW.handle IS NOT NULL THEN
        RETURN NEW;
    END IF;
    -- Two writers of one game would read the same maximum: serialise them.
    PERFORM pg_advisory_xact_lock(hashtextextended(TG_TABLE_NAME || NEW.game_id::text, 0));
    IF TG_TABLE_NAME = 'facts' THEN
        SELECT COALESCE(MAX(ft.handle), 0) INTO NEW.handle
          FROM public.facts AS ft WHERE ft.game_id = NEW.game_id;
    ELSE
        SELECT COALESCE(MAX(er.handle), 0) INTO NEW.handle
          FROM public.entity_registry AS er WHERE er.game_id = NEW.game_id;
    END IF;
    SELECT GREATEST(NEW.handle, COALESCE(MAX((ev.payload ->> 'handle')::integer), 0)) + 1
      INTO NEW.handle
      FROM public.identity_events AS ev
     WHERE ev.game_id = NEW.game_id AND ev.kind = 'handle_reserved'
       AND ev.payload ->> 'table' = TG_TABLE_NAME;
    RETURN NEW;
END $$;

-- characters.name is the internal label: the true name, else the descriptor, followed by
-- " (<label_suffix>)" for a homonym. A direct write of name is overridden by that value:
-- name never drifts from true_name/descriptor.
CREATE FUNCTION public.identity_character_name() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF current_setting('ldvelh.replay', true) = 'on' THEN
        RETURN NEW;
    END IF;
    IF COALESCE(NEW.true_name, NEW.descriptor) IS NOT NULL THEN
        NEW.name := COALESCE(NEW.true_name, NEW.descriptor)
                    || COALESCE(' (' || NEW.label_suffix || ')', '');
    END IF;
    RETURN NEW;
END $$;

-- The alias of each current name of an entity, made by the triggers (source 'system'): a
-- character's true name (known when the PC knows it) and descriptor (known), plus its
-- suffixed label when it has a label_suffix (internal lookup); another entity's label (its
-- name). True names and descriptors stay suffix-free: homonyms share them. Invariant:
-- every entity has an alias of its current name_norm.
-- The services add the derived aliases (short forms, titles).
CREATE FUNCTION public.identity_name_aliases(p_type text, p_row jsonb, p_turn uuid)
        RETURNS void
    LANGUAGE sql
    AS $$
    INSERT INTO public.entity_aliases
           (game_id, entity_id, entity_type, alias, kind, known, source, turn_id)
    SELECT (p_row ->> 'game_id')::uuid, (p_row ->> 'id')::uuid, p_type, forms.alias, forms.kind,
           forms.known, 'system', p_turn
      FROM (VALUES
              (CASE WHEN p_type = 'character' THEN p_row ->> 'true_name'
                    ELSE p_row ->> 'name' END,
               CASE WHEN p_type = 'character' THEN 'true_name' ELSE 'label' END,
               p_type <> 'character'
                   OR COALESCE((p_row ->> 'known_by_protagonist')::boolean, false)),
              (CASE WHEN p_type = 'character' THEN p_row ->> 'descriptor' END,
               'descriptor', true),
              (CASE WHEN p_type = 'character' AND p_row ->> 'label_suffix' IS NOT NULL
                    THEN p_row ->> 'name' END,
               'label',
               p_row ->> 'true_name' IS NULL
                   OR COALESCE((p_row ->> 'known_by_protagonist')::boolean, false))
           ) AS forms (alias, kind, known)
     WHERE forms.alias IS NOT NULL
    ON CONFLICT DO NOTHING
$$;

-- BEFORE INSERT on a domain table: its registry row, at the same id, with the turn that
-- created it, and the aliases of its names.
CREATE FUNCTION public.identity_register() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_turn uuid := nullif(current_setting('ldvelh.turn_id', true), '')::uuid;
    v_id uuid;
BEGIN
    IF current_setting('ldvelh.replay', true) = 'on' THEN
        RETURN NEW;
    END IF;
    INSERT INTO public.entity_registry (id, game_id, entity_type, name, created_turn_id)
    VALUES (NEW.id, NEW.game_id, TG_ARGV[0], NEW.name, v_turn)
    ON CONFLICT (id) DO NOTHING
    RETURNING id INTO v_id;
    IF v_id IS NOT NULL THEN
        PERFORM public.identity_name_aliases(TG_ARGV[0], to_jsonb(NEW), v_turn);
    END IF;
    RETURN NEW;
END $$;

-- AFTER UPDATE of a name: the registry follows the domain name, by id (a normalised
-- collision with another entity of the type raises, never a silent second entry); a label
-- or true name replaced becomes a former name, and the new names get their aliases.
CREATE FUNCTION public.identity_sync_name() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_type text := TG_ARGV[0];
    v_turn uuid := nullif(current_setting('ldvelh.turn_id', true), '')::uuid;
    v_row jsonb := to_jsonb(NEW);
    v_kind text := CASE WHEN TG_ARGV[0] = 'character' THEN 'true_name' ELSE 'label' END;
    v_current text;
    v_norm text;
BEGIN
    IF current_setting('ldvelh.replay', true) = 'on' THEN
        RETURN NEW;
    END IF;
    IF NEW.name IS DISTINCT FROM OLD.name THEN
        UPDATE public.entity_registry SET name = NEW.name WHERE id = NEW.id;
    END IF;
    v_current := v_row ->> CASE WHEN v_type = 'character' THEN 'true_name' ELSE 'name' END;
    IF v_current IS NOT NULL THEN
        v_norm := public.ldvelh_norm_for_game(NEW.game_id, v_current);
    END IF;
    UPDATE public.entity_aliases AS al SET kind = 'former_name'
     WHERE al.entity_id = NEW.id AND al.kind = v_kind
       AND (v_norm IS NULL OR al.alias_norm <> v_norm);
    IF v_type = 'character' THEN
        -- A suffixed label no longer the character's label.
        UPDATE public.entity_aliases AS al SET kind = 'former_name'
         WHERE al.entity_id = NEW.id AND al.kind = 'label'
           AND al.alias_norm <> public.ldvelh_norm_for_game(NEW.game_id, NEW.name);
    END IF;
    PERFORM public.identity_name_aliases(v_type, v_row, v_turn);
    RETURN NEW;
END $$;

-- AFTER DELETE: the registry row goes, unless it is a merge tombstone; the cascade takes
-- the aliases, edges and mentions of the entity.
CREATE FUNCTION public.identity_unregister() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF current_setting('ldvelh.replay', true) = 'on' THEN
        RETURN NEW;
    END IF;
    DELETE FROM public.entity_registry WHERE id = OLD.id AND merged_into IS NULL;
    RETURN OLD;
END $$;

CREATE TRIGGER identity_handle BEFORE INSERT ON public.entity_registry
    FOR EACH ROW EXECUTE FUNCTION public.identity_assign_handle();
CREATE TRIGGER identity_norm_fill BEFORE INSERT OR UPDATE OF name ON public.entity_registry
    FOR EACH ROW EXECUTE FUNCTION public.identity_norm_fill();
CREATE TRIGGER identity_norm_fill BEFORE INSERT OR UPDATE OF alias ON public.entity_aliases
    FOR EACH ROW EXECUTE FUNCTION public.identity_norm_fill();
CREATE TRIGGER identity_handle BEFORE INSERT ON public.facts
    FOR EACH ROW EXECUTE FUNCTION public.identity_assign_handle();

-- identity_character_name fires before register_character (alphabetical order): the
-- registry gets the computed name.
CREATE TRIGGER identity_character_name
    BEFORE INSERT OR UPDATE OF name, true_name, descriptor, label_suffix ON public.characters
    FOR EACH ROW EXECUTE FUNCTION public.identity_character_name();
CREATE TRIGGER register_character BEFORE INSERT ON public.characters
    FOR EACH ROW EXECUTE FUNCTION public.identity_register('character');
CREATE TRIGGER register_location BEFORE INSERT ON public.locations
    FOR EACH ROW EXECUTE FUNCTION public.identity_register('location');
CREATE TRIGGER register_organization BEFORE INSERT ON public.organizations
    FOR EACH ROW EXECUTE FUNCTION public.identity_register('organization');
CREATE TRIGGER register_object BEFORE INSERT ON public.objects
    FOR EACH ROW EXECUTE FUNCTION public.identity_register('object');
CREATE TRIGGER register_protagonist BEFORE INSERT ON public.protagonists
    FOR EACH ROW EXECUTE FUNCTION public.identity_register('protagonist');
CREATE TRIGGER register_companion BEFORE INSERT ON public.companions
    FOR EACH ROW EXECUTE FUNCTION public.identity_register('companion');
-- characters.name changes through true_name/descriptor (identity_character_name), which an
-- UPDATE OF name trigger alone would not see.
CREATE TRIGGER sync_registry_character
    AFTER UPDATE OF name, true_name, descriptor, label_suffix ON public.characters
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('character');
CREATE TRIGGER sync_registry_location AFTER UPDATE OF name ON public.locations
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('location');
CREATE TRIGGER sync_registry_organization AFTER UPDATE OF name ON public.organizations
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('organization');
CREATE TRIGGER sync_registry_object AFTER UPDATE OF name ON public.objects
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('object');
CREATE TRIGGER sync_registry_protagonist AFTER UPDATE OF name ON public.protagonists
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('protagonist');
CREATE TRIGGER sync_registry_companion AFTER UPDATE OF name ON public.companions
    FOR EACH ROW EXECUTE FUNCTION public.identity_sync_name('companion');
CREATE TRIGGER unregister_character AFTER DELETE ON public.characters
    FOR EACH ROW EXECUTE FUNCTION public.identity_unregister();
CREATE TRIGGER unregister_location AFTER DELETE ON public.locations
    FOR EACH ROW EXECUTE FUNCTION public.identity_unregister();
CREATE TRIGGER unregister_organization AFTER DELETE ON public.organizations
    FOR EACH ROW EXECUTE FUNCTION public.identity_unregister();
CREATE TRIGGER unregister_object AFTER DELETE ON public.objects
    FOR EACH ROW EXECUTE FUNCTION public.identity_unregister();
CREATE TRIGGER unregister_protagonist AFTER DELETE ON public.protagonists
    FOR EACH ROW EXECUTE FUNCTION public.identity_unregister();
CREATE TRIGGER unregister_companion AFTER DELETE ON public.companions
    FOR EACH ROW EXECUTE FUNCTION public.identity_unregister();

-- Facts stay immutable, except their knowledge flags (a revealed fact becomes known), the
-- location_id a deleted location's SET NULL clears (#22), and a location_id moved by a merge
-- from the tombstone to the location it was merged into.
CREATE OR REPLACE FUNCTION public.facts_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF current_setting('ldvelh.replay', true) = 'on' THEN
        RETURN NEW;
    END IF;
    IF (to_jsonb(NEW) - ARRAY['known', 'secret']) = (to_jsonb(OLD) - ARRAY['known', 'secret'])
    THEN
        RETURN NEW;
    END IF;
    IF (to_jsonb(NEW) - 'location_id') = (to_jsonb(OLD) - 'location_id')
       AND OLD.location_id IS NOT NULL
       AND (NEW.location_id IS NULL
            OR EXISTS (SELECT 1 FROM public.entity_registry AS er
                        WHERE er.id = OLD.location_id AND er.merged_into = NEW.location_id))
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'facts are immutable (known, secret aside)';
END $$;

-- 2.5 References. Resolution by name happens at the edge (find_entity); the functions
-- that write edges take ids.

-- The live entity behind an id: merged_into followed, at most 5 hops (a longer chain or a
-- cycle stops where it is).
CREATE FUNCTION public.entity_follow_merge(p_entity_id uuid) RETURNS uuid
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
    v_id uuid := p_entity_id;
    v_next uuid;
BEGIN
    FOR v_hop IN 1..5 LOOP
        SELECT er.merged_into INTO v_next FROM public.entity_registry AS er WHERE er.id = v_id;
        EXIT WHEN v_next IS NULL;
        v_id := v_next;
    END LOOP;
    RETURN v_id;
END $$;

-- The entity a reference names, the type being required: the reserved PROTAGONIST and
-- COMPANION (only for their own type: another type looks them up as names), a handle E<n>
-- (any case), an id, else the normalised labels and aliases together (a descriptor shared
-- by two homonyms is ambiguous even if it is one's label); merges followed. Two distinct
-- entities or more: NULL, never an arbitrary pick (the caller records the ambiguity).
CREATE FUNCTION public.find_entity(p_game uuid, p_ref text, p_type text) RETURNS uuid
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
    v_ref text := btrim(p_ref, E' \t\r\n');
    v_norm text;
    v_ids uuid[];
BEGIN
    IF p_type IS NULL THEN
        RAISE EXCEPTION 'find_entity: p_type is required';
    END IF;
    IF v_ref IS NULL OR v_ref = '' THEN
        RETURN NULL;
    END IF;
    IF upper(v_ref) IN ('PROTAGONIST', 'COMPANION') AND lower(v_ref) = p_type THEN
        SELECT array_agg(er.id) INTO v_ids FROM public.entity_registry AS er
         WHERE er.game_id = p_game AND er.entity_type = p_type AND er.merged_into IS NULL;
    ELSIF v_ref ~* '^E[0-9]{1,9}$' THEN
        SELECT array_agg(er.id) INTO v_ids FROM public.entity_registry AS er
         WHERE er.game_id = p_game AND er.entity_type = p_type
           AND er.handle = substr(v_ref, 2)::integer;
    ELSIF v_ref ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
        SELECT array_agg(er.id) INTO v_ids FROM public.entity_registry AS er
         WHERE er.game_id = p_game AND er.entity_type = p_type AND er.id = v_ref::uuid;
    ELSE
        v_norm := public.ldvelh_norm_for_game(p_game, v_ref);
        SELECT array_agg(er.id) INTO v_ids FROM public.entity_registry AS er
         WHERE er.game_id = p_game AND er.entity_type = p_type AND er.name_norm = v_norm;
        SELECT COALESCE(v_ids, '{}') || COALESCE(array_agg(al.entity_id), '{}') INTO v_ids
          FROM public.entity_aliases AS al
         WHERE al.game_id = p_game AND al.entity_type = p_type AND al.alias_norm = v_norm;
    END IF;
    SELECT array_agg(DISTINCT public.entity_follow_merge(ref.id)) INTO v_ids
      FROM unnest(v_ids) AS ref (id);
    IF cardinality(v_ids) = 1 THEN
        RETURN v_ids[1];
    END IF;
    RETURN NULL;
END $$;

-- The fact a reference names: a handle F<n> (any case) or an id of the game.
CREATE FUNCTION public.find_fact(p_game uuid, p_ref text) RETURNS uuid
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
    v_ref text := btrim(p_ref, E' \t\r\n');
    v_id uuid;
BEGIN
    IF v_ref ~* '^F[0-9]{1,9}$' THEN
        SELECT ft.id INTO v_id FROM public.facts AS ft
         WHERE ft.game_id = p_game AND ft.handle = substr(v_ref, 2)::integer;
    ELSIF v_ref ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
        SELECT ft.id INTO v_id FROM public.facts AS ft
         WHERE ft.game_id = p_game AND ft.id = v_ref::uuid;
    END IF;
    RETURN v_id;
END $$;

-- What the player may read for an entity: a character's true name only when the PC knows
-- it, else its descriptor, else the pack's label for an unnamed character; the label of
-- any other entity. Merges followed.
CREATE FUNCTION public.display_for_player(p_entity_id uuid) RETURNS text
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
    v_id uuid := public.entity_follow_merge(p_entity_id);
    v_game uuid;
    v_type text;
    v_name text;
    v_true_name text;
    v_descriptor text;
    v_known boolean;
BEGIN
    SELECT er.game_id, er.entity_type, er.name INTO v_game, v_type, v_name
      FROM public.entity_registry AS er WHERE er.id = v_id;
    IF v_type IS NULL THEN
        RETURN NULL;
    END IF;
    IF v_type <> 'character' THEN
        RETURN v_name;
    END IF;
    SELECT ch.true_name, ch.descriptor, ch.known_by_protagonist
      INTO v_true_name, v_descriptor, v_known
      FROM public.characters AS ch WHERE ch.id = v_id;
    IF v_known AND v_true_name IS NOT NULL THEN
        RETURN v_true_name;
    END IF;
    RETURN COALESCE(v_descriptor,
                    public.ldvelh_lang_params(v_game) ->> 'unknown_character_label');
END $$;

-- Participants are ids resolved by the caller: [{"entity_id": "<uuid>", "role": "actor"}];
-- an id outside the game, or not an id, is skipped; a merged one stands for its live entity.
CREATE OR REPLACE FUNCTION public.create_fact(p_game_id uuid, p_cycle integer,
        p_type character varying, p_description text, p_location_id uuid DEFAULT NULL::uuid,
        p_time character varying DEFAULT NULL::character varying, p_importance integer DEFAULT 3,
        p_participants jsonb DEFAULT '[]'::jsonb,
        p_semantic_key character varying DEFAULT NULL::character varying) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_fact_id uuid;
    v_participant jsonb;
    v_entity_id uuid;
BEGIN
    -- Deduplication by semantic_key.
    IF p_semantic_key IS NOT NULL THEN
        SELECT ft.id INTO v_fact_id FROM public.facts AS ft
         WHERE ft.game_id = p_game_id AND ft.cycle = p_cycle
           AND ft.semantic_key = p_semantic_key;
        IF v_fact_id IS NOT NULL THEN
            RETURN v_fact_id;
        END IF;
    END IF;
    INSERT INTO public.facts (game_id, cycle, type, description, location_id, "time",
                              importance, semantic_key)
    VALUES (p_game_id, p_cycle, p_type, p_description, p_location_id, p_time, p_importance,
            p_semantic_key)
    RETURNING id INTO v_fact_id;
    FOR v_participant IN SELECT jsonb_array_elements(p_participants) LOOP
        v_entity_id := NULL;
        IF v_participant ->> 'entity_id'
           ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
            SELECT public.entity_follow_merge(er.id) INTO v_entity_id
              FROM public.entity_registry AS er
             WHERE er.game_id = p_game_id AND er.id = (v_participant ->> 'entity_id')::uuid;
        END IF;
        IF v_entity_id IS NOT NULL THEN
            INSERT INTO public.fact_participants (fact_id, entity_id, role)
            VALUES (v_fact_id, v_entity_id, v_participant ->> 'role')
            ON CONFLICT (fact_id, entity_id) DO NOTHING;
        END IF;
    END LOOP;
    RETURN v_fact_id;
END $$;

DROP FUNCTION public.end_relation(uuid, text, text, public.relation_type, integer, text);
CREATE FUNCTION public.end_relation(p_game_id uuid, p_source_id uuid, p_target_id uuid,
        p_type public.relation_type, p_cycle integer, p_reason text DEFAULT NULL::text)
        RETURNS boolean
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE public.relations AS rel SET end_cycle = p_cycle, end_reason = p_reason
     WHERE rel.game_id = p_game_id AND rel.source_id = p_source_id
       AND rel.target_id = p_target_id AND rel.type = p_type AND rel.end_cycle IS NULL;
    RETURN FOUND;
END $$;

DROP FUNCTION public.find_entity(uuid, text, character varying);

-- 2.6 Merges (spec §4.7). The guards (same type, not two mandatory entities, neither PC
-- nor companion, not already merged) live in the identity service; this function only
-- refuses two types. Every write goes through the journal triggers: a rollback undoes the
-- merge row by row.

-- The domain table of an entity type.
CREATE FUNCTION public.identity_domain_table(p_entity_type text) RETURNS regclass
    LANGUAGE sql STABLE
    AS $$
    SELECT (CASE p_entity_type
                WHEN 'character' THEN 'public.characters'
                WHEN 'location' THEN 'public.locations'
                WHEN 'organization' THEN 'public.organizations'
                WHEN 'object' THEN 'public.objects'
                WHEN 'protagonist' THEN 'public.protagonists'
                WHEN 'companion' THEN 'public.companions'
            END)::regclass
$$;

-- The domain row of an entity, as jsonb (NULL when it has none).
CREATE FUNCTION public.identity_domain_row(p_entity_type text, p_entity_id uuid)
        RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
    SELECT CASE p_entity_type
        WHEN 'character' THEN
            (SELECT to_jsonb(ch) FROM public.characters AS ch WHERE ch.id = p_entity_id)
        WHEN 'location' THEN
            (SELECT to_jsonb(lc) FROM public.locations AS lc WHERE lc.id = p_entity_id)
        WHEN 'organization' THEN
            (SELECT to_jsonb(og) FROM public.organizations AS og WHERE og.id = p_entity_id)
        WHEN 'object' THEN
            (SELECT to_jsonb(ob) FROM public.objects AS ob WHERE ob.id = p_entity_id)
        WHEN 'protagonist' THEN
            (SELECT to_jsonb(pc) FROM public.protagonists AS pc WHERE pc.id = p_entity_id)
        WHEN 'companion' THEN
            (SELECT to_jsonb(cm) FROM public.companions AS cm WHERE cm.id = p_entity_id)
    END
$$;

-- keep's fields completed from drop: a NULL takes drop's value; jsonb objects (details) are
-- combined, keep's keys winning; arrays (traits) get drop's missing elements; known and
-- mandatory flags are ORed. Only the columns that change are written.
CREATE FUNCTION public.identity_merge_fields(p_keep uuid, p_drop uuid, p_entity_type text)
        RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_table regclass := public.identity_domain_table(p_entity_type);
    v_keep_row jsonb := public.identity_domain_row(p_entity_type, p_keep);
    v_drop_row jsonb := public.identity_domain_row(p_entity_type, p_drop);
    v_merged jsonb;
    v_cols text;
    v_vals text;
BEGIN
    IF v_keep_row IS NULL OR v_drop_row IS NULL THEN
        RETURN;
    END IF;
    SELECT v_keep_row || COALESCE(jsonb_object_agg(dropped.key, CASE
               WHEN COALESCE(v_keep_row -> dropped.key, 'null'::jsonb) = 'null'::jsonb
                   THEN dropped.value
               WHEN dropped.key IN ('known_by_protagonist', 'is_mandatory')
                   THEN to_jsonb((v_keep_row ->> dropped.key)::boolean
                                 OR (dropped.value #>> '{}')::boolean)
               WHEN jsonb_typeof(dropped.value) = 'object'
                    AND jsonb_typeof(v_keep_row -> dropped.key) = 'object'
                   THEN dropped.value || (v_keep_row -> dropped.key)
               WHEN jsonb_typeof(dropped.value) = 'array'
                    AND jsonb_typeof(v_keep_row -> dropped.key) = 'array'
                   THEN (v_keep_row -> dropped.key) || COALESCE(
                       (SELECT jsonb_agg(elem) FROM jsonb_array_elements(dropped.value) AS elem
                         WHERE NOT (v_keep_row -> dropped.key) @> jsonb_build_array(elem)),
                       '[]'::jsonb)
               ELSE v_keep_row -> dropped.key
           END), '{}'::jsonb)
      INTO v_merged
      FROM jsonb_each(v_drop_row) AS dropped
     WHERE dropped.key <> ALL (ARRAY['id', 'game_id', 'name', 'label_suffix', 'created_at',
                                'updated_at', 'created_cycle', 'removed_cycle'])
       AND dropped.value <> 'null'::jsonb;
    SELECT string_agg(quote_ident(att.attname), ', ' ORDER BY att.attnum),
           string_agg('(jsonb_populate_record(NULL::' || v_table || ', $2)).'
                      || quote_ident(att.attname), ', ' ORDER BY att.attnum)
      INTO v_cols, v_vals
      FROM pg_attribute AS att
     WHERE att.attrelid = v_table AND att.attnum > 0 AND NOT att.attisdropped
       AND (v_merged -> att.attname::text) IS DISTINCT FROM (v_keep_row -> att.attname::text);
    IF v_cols IS NOT NULL THEN
        EXECUTE 'UPDATE ' || v_table || ' SET (' || v_cols || ') = ROW(' || v_vals || ')'
             || ' WHERE id = $1'
          USING p_keep, v_merged;
    END IF;
END $$;

-- Every edge of drop goes to keep (spec §4.7 effect 1); returns the moved row ids by
-- table.column. Relations: an open relation that keep already has (same other end, same
-- type) is closed (end_cycle, the entity_merges row tells why) rather than duplicated, a
-- relation between keep and drop is closed and left on the tombstone. Pivots: a row keep
-- already has is deleted. Inventory: quantities of the same object and owner are added up.
CREATE FUNCTION public.identity_merge_edges(p_keep uuid, p_drop uuid, p_entity_type text)
        RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_cycle integer;
    v_edges jsonb := '{}'::jsonb;
BEGIN
    SELECT gm.current_cycle INTO v_cycle
      FROM public.games AS gm JOIN public.entity_registry AS er ON er.game_id = gm.id
     WHERE er.id = p_keep;

    WITH closed AS (
        UPDATE public.relations AS rel SET end_cycle = v_cycle
         WHERE rel.end_cycle IS NULL AND p_drop IN (rel.source_id, rel.target_id)
           AND (p_keep IN (rel.source_id, rel.target_id)
                OR EXISTS (
                    SELECT 1 FROM public.relations AS dup
                     WHERE dup.end_cycle IS NULL AND dup.type = rel.type
                       AND dup.source_id = CASE WHEN rel.source_id = p_drop THEN p_keep
                                                ELSE rel.source_id END
                       AND dup.target_id = CASE WHEN rel.target_id = p_drop THEN p_keep
                                                ELSE rel.target_id END))
        RETURNING rel.id)
    SELECT v_edges || jsonb_build_object('relations.closed', array_agg(closed.id))
      INTO v_edges FROM closed;
    WITH moved AS (
        UPDATE public.relations AS rel SET source_id = p_keep
         WHERE rel.source_id = p_drop AND rel.target_id <> p_keep RETURNING rel.id)
    SELECT v_edges || jsonb_build_object('relations.source_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    WITH moved AS (
        UPDATE public.relations AS rel SET target_id = p_keep
         WHERE rel.target_id = p_drop AND rel.source_id <> p_keep RETURNING rel.id)
    SELECT v_edges || jsonb_build_object('relations.target_id', array_agg(moved.id))
      INTO v_edges FROM moved;

    DELETE FROM public.fact_participants AS fp
     WHERE fp.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.fact_participants AS kp
                    WHERE kp.fact_id = fp.fact_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.fact_participants AS fp SET entity_id = p_keep
         WHERE fp.entity_id = p_drop RETURNING fp.id)
    SELECT v_edges || jsonb_build_object('fact_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    DELETE FROM public.arc_participants AS ap
     WHERE ap.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.arc_participants AS kp
                    WHERE kp.arc_id = ap.arc_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.arc_participants AS ap SET entity_id = p_keep
         WHERE ap.entity_id = p_drop RETURNING ap.id)
    SELECT v_edges || jsonb_build_object('arc_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    DELETE FROM public.chronology_participants AS cp
     WHERE cp.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.chronology_participants AS kp
                    WHERE kp.chronology_id = cp.chronology_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.chronology_participants AS cp SET entity_id = p_keep
         WHERE cp.entity_id = p_drop RETURNING cp.id)
    SELECT v_edges
           || jsonb_build_object('chronology_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    DELETE FROM public.event_participants AS ep
     WHERE ep.entity_id = p_drop
       AND EXISTS (SELECT 1 FROM public.event_participants AS kp
                    WHERE kp.event_id = ep.event_id AND kp.entity_id = p_keep);
    WITH moved AS (
        UPDATE public.event_participants AS ep SET entity_id = p_keep
         WHERE ep.entity_id = p_drop RETURNING ep.id)
    SELECT v_edges || jsonb_build_object('event_participants.entity_id', array_agg(moved.id))
      INTO v_edges FROM moved;

    UPDATE public.inventory AS kept SET quantity = COALESCE(kept.quantity, 0)
                                                   + COALESCE(gone.quantity, 0)
      FROM public.inventory AS gone
     WHERE kept.owner_id = p_keep AND gone.owner_id = p_drop
       AND gone.object_id = kept.object_id;
    DELETE FROM public.inventory AS gone
     WHERE gone.owner_id = p_drop
       AND EXISTS (SELECT 1 FROM public.inventory AS kept
                    WHERE kept.owner_id = p_keep AND kept.object_id = gone.object_id);
    WITH moved AS (
        UPDATE public.inventory AS inv SET owner_id = p_keep
         WHERE inv.owner_id = p_drop RETURNING inv.id)
    SELECT v_edges || jsonb_build_object('inventory.owner_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    WITH moved AS (
        UPDATE public.narrative_arcs AS na SET owner_id = p_keep
         WHERE na.owner_id = p_drop RETURNING na.id)
    SELECT v_edges || jsonb_build_object('narrative_arcs.owner_id', array_agg(moved.id))
      INTO v_edges FROM moved;
    WITH moved AS (
        UPDATE public.director_commitments AS dc
           SET related_entities = CASE WHEN p_keep = ANY (dc.related_entities)
                                       THEN array_remove(dc.related_entities, p_drop)
                                       ELSE array_replace(dc.related_entities, p_drop, p_keep)
                                  END
         WHERE p_drop = ANY (dc.related_entities) RETURNING dc.id)
    SELECT v_edges
           || jsonb_build_object('director_commitments.related_entities', array_agg(moved.id))
      INTO v_edges FROM moved;

    IF p_entity_type = 'character' THEN
        WITH moved AS (
            UPDATE public.skills AS sk SET character_id = p_keep
             WHERE sk.character_id = p_drop RETURNING sk.id)
        SELECT v_edges || jsonb_build_object('skills.character_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        -- Engine rows (one per character): drop's only when keep has none.
        UPDATE public.npc_fate SET character_id = p_keep WHERE character_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.npc_fate WHERE character_id = p_keep);
        UPDATE public.npc_d6 SET character_id = p_keep WHERE character_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.npc_d6 WHERE character_id = p_keep);
        UPDATE public.npc_narrative SET character_id = p_keep WHERE character_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.npc_narrative WHERE character_id = p_keep);
    ELSIF p_entity_type = 'location' THEN
        -- facts_immutable lets a fact follow its location to the one it was merged into.
        WITH moved AS (
            UPDATE public.facts AS ft SET location_id = p_keep
             WHERE ft.location_id = p_drop RETURNING ft.id)
        SELECT v_edges || jsonb_build_object('facts.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.characters AS ch SET workplace_id = p_keep
             WHERE ch.workplace_id = p_drop RETURNING ch.id)
        SELECT v_edges || jsonb_build_object('characters.workplace_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.characters AS ch SET residence_id = p_keep
             WHERE ch.residence_id = p_drop RETURNING ch.id)
        SELECT v_edges || jsonb_build_object('characters.residence_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.messages AS mg SET location_id = p_keep
             WHERE mg.location_id = p_drop RETURNING mg.id)
        SELECT v_edges || jsonb_build_object('messages.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.games AS gm SET current_location_id = p_keep
             WHERE gm.current_location_id = p_drop RETURNING gm.id)
        SELECT v_edges
               || jsonb_build_object('games.current_location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.chronology AS cr SET location_id = p_keep
             WHERE cr.location_id = p_drop RETURNING cr.id)
        SELECT v_edges || jsonb_build_object('chronology.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.events AS ev SET location_id = p_keep
             WHERE ev.location_id = p_drop RETURNING ev.id)
        SELECT v_edges || jsonb_build_object('events.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.locations AS lc SET parent_id = p_keep
             WHERE lc.parent_id = p_drop AND lc.id <> p_keep RETURNING lc.id)
        SELECT v_edges || jsonb_build_object('locations.parent_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.organizations AS og SET headquarters_id = p_keep
             WHERE og.headquarters_id = p_drop RETURNING og.id)
        SELECT v_edges
               || jsonb_build_object('organizations.headquarters_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.protagonists AS pc SET residence_id = p_keep
             WHERE pc.residence_id = p_drop RETURNING pc.id)
        SELECT v_edges || jsonb_build_object('protagonists.residence_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        WITH moved AS (
            UPDATE public.narrative_seeds AS ns SET location_id = p_keep
             WHERE ns.location_id = p_drop RETURNING ns.id)
        SELECT v_edges
               || jsonb_build_object('narrative_seeds.location_id', array_agg(moved.id))
          INTO v_edges FROM moved;
    ELSIF p_entity_type = 'organization' THEN
        WITH moved AS (
            UPDATE public.protagonists AS pc SET employer_id = p_keep
             WHERE pc.employer_id = p_drop RETURNING pc.id)
        SELECT v_edges || jsonb_build_object('protagonists.employer_id', array_agg(moved.id))
          INTO v_edges FROM moved;
    ELSIF p_entity_type = 'object' THEN
        UPDATE public.inventory AS kept SET quantity = COALESCE(kept.quantity, 0)
                                                       + COALESCE(gone.quantity, 0)
          FROM public.inventory AS gone
         WHERE kept.object_id = p_keep AND gone.object_id = p_drop
           AND gone.owner_id IS NOT DISTINCT FROM kept.owner_id;
        DELETE FROM public.inventory AS gone
         WHERE gone.object_id = p_drop
           AND EXISTS (SELECT 1 FROM public.inventory AS kept
                        WHERE kept.object_id = p_keep
                          AND kept.owner_id IS NOT DISTINCT FROM gone.owner_id);
        WITH moved AS (
            UPDATE public.inventory AS inv SET object_id = p_keep
             WHERE inv.object_id = p_drop RETURNING inv.id)
        SELECT v_edges || jsonb_build_object('inventory.object_id', array_agg(moved.id))
          INTO v_edges FROM moved;
        UPDATE public.object_fate SET object_id = p_keep WHERE object_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.object_fate WHERE object_id = p_keep);
        UPDATE public.object_d6 SET object_id = p_keep WHERE object_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.object_d6 WHERE object_id = p_keep);
        UPDATE public.object_narrative SET object_id = p_keep WHERE object_id = p_drop
           AND NOT EXISTS (SELECT 1 FROM public.object_narrative WHERE object_id = p_keep);
    END IF;
    RETURN jsonb_strip_nulls(v_edges);
END $$;

-- Merge drop into keep without losing anything: 1. edges re-pointed; 2. drop's aliases
-- moved to keep, its label kept as an alias; 3. keep's empty fields filled from drop,
-- known = keep OR drop; 4. drop's registry row becomes a tombstone (merged_into = keep)
-- before its domain row is deleted; 5. an entity_merges row with the snapshots and an
-- identity_events 'merge'. Mentions are not rewritten: their reads follow merged_into.
-- Returns the entity_merges id.
CREATE FUNCTION public.merge_entities(p_keep uuid, p_drop uuid, p_reason text,
        p_evidence text) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_turn uuid := nullif(current_setting('ldvelh.turn_id', true), '')::uuid;
    v_keep public.entity_registry;
    v_drop public.entity_registry;
    v_drop_row jsonb;
    v_keep_norm text;
    v_character boolean;
    v_edges jsonb;
    v_merge_id uuid;
BEGIN
    SELECT * INTO v_keep FROM public.entity_registry WHERE id = p_keep;
    SELECT * INTO v_drop FROM public.entity_registry WHERE id = p_drop;
    IF v_keep.id IS NULL OR v_drop.id IS NULL THEN
        RAISE EXCEPTION 'merge_entities: entity missing (%, %)', p_keep, p_drop;
    END IF;
    -- Integrity, not policy (the policy guards live in the identity service): one entity
    -- with itself, two games, or a tombstone on either side would destroy or cross data.
    IF p_keep = p_drop THEN
        RAISE EXCEPTION 'merge_entities: keep = drop (%)', p_keep;
    END IF;
    IF v_keep.game_id <> v_drop.game_id THEN
        RAISE EXCEPTION 'merge_entities: entities in two games (%, %)', p_keep, p_drop;
    END IF;
    IF v_keep.merged_into IS NOT NULL OR v_drop.merged_into IS NOT NULL THEN
        RAISE EXCEPTION 'merge_entities: already merged (%, %)', p_keep, p_drop;
    END IF;
    IF v_keep.entity_type <> v_drop.entity_type THEN
        RAISE EXCEPTION 'merge_entities: entity types differ (%, %)',
            v_keep.entity_type, v_drop.entity_type;
    END IF;
    v_character := v_keep.entity_type = 'character';
    v_drop_row := public.identity_domain_row(v_drop.entity_type, p_drop);

    -- The tombstone first: keep may then take drop's name without a normalised collision.
    UPDATE public.entity_registry SET merged_into = p_keep WHERE id = p_drop;
    PERFORM public.identity_merge_fields(p_keep, p_drop, v_keep.entity_type);
    SELECT er.name_norm INTO v_keep_norm FROM public.entity_registry AS er WHERE er.id = p_keep;

    -- A label or true name of drop that is not keep's own becomes a former name.
    UPDATE public.entity_aliases AS al
       SET entity_id = p_keep,
           kind = CASE WHEN al.kind IN ('label', 'true_name') AND al.alias_norm <> v_keep_norm
                       THEN 'former_name' ELSE al.kind END
     WHERE al.entity_id = p_drop
       AND NOT EXISTS (SELECT 1 FROM public.entity_aliases AS ka
                        WHERE ka.entity_id = p_keep AND ka.alias_norm = al.alias_norm);
    INSERT INTO public.entity_aliases
           (game_id, entity_id, entity_type, alias, kind, known, source, turn_id)
    VALUES (v_keep.game_id, p_keep, v_keep.entity_type, v_drop.name,
            CASE WHEN v_character AND v_drop_row ->> 'true_name' IS NULL THEN 'descriptor'
                 WHEN v_drop.name_norm = v_keep_norm AND v_character THEN 'true_name'
                 WHEN v_drop.name_norm = v_keep_norm THEN 'label'
                 ELSE 'former_name' END,
            NOT v_character OR v_drop_row ->> 'true_name' IS NULL
                OR COALESCE((v_drop_row ->> 'known_by_protagonist')::boolean, false),
            'system', v_turn)
    ON CONFLICT DO NOTHING;

    v_edges := public.identity_merge_edges(p_keep, p_drop, v_keep.entity_type);

    CASE v_keep.entity_type
        WHEN 'character' THEN DELETE FROM public.characters WHERE id = p_drop;
        WHEN 'location' THEN DELETE FROM public.locations WHERE id = p_drop;
        WHEN 'organization' THEN DELETE FROM public.organizations WHERE id = p_drop;
        WHEN 'object' THEN DELETE FROM public.objects WHERE id = p_drop;
        WHEN 'protagonist' THEN DELETE FROM public.protagonists WHERE id = p_drop;
        WHEN 'companion' THEN DELETE FROM public.companions WHERE id = p_drop;
    END CASE;

    INSERT INTO public.entity_merges (game_id, kept_id, dropped_id, dropped_registry,
                                      dropped_row, moved_edges, reason, evidence, turn_id)
    VALUES (v_keep.game_id, p_keep, p_drop, to_jsonb(v_drop), v_drop_row, v_edges,
            p_reason, p_evidence, v_turn)
    RETURNING id INTO v_merge_id;
    INSERT INTO public.identity_events (game_id, turn_id, kind, entity_id, payload)
    VALUES (v_keep.game_id, v_turn, 'merge', p_keep,
            jsonb_build_object('merge_id', v_merge_id, 'dropped_id', p_drop));
    RETURN v_merge_id;
END $$;

-- 2.7 Views: participants by what the player may read (display_for_player), with their id
-- and handle. v_chronology and v_upcoming_events keep their name arrays (npcs_present,
-- participants: their readers are unchanged) and gain the same jsonb records
-- (npc_refs, participant_refs: name, entity_id, handle).
CREATE OR REPLACE VIEW public.v_active_arcs AS
 SELECT na.id,
    na.game_id,
    na.title,
    na.domain,
    na.description,
    na.intensity,
    array_agg(to_jsonb(part.*)) FILTER (WHERE er.id IS NOT NULL) AS participants
   FROM public.narrative_arcs na
     LEFT JOIN public.arc_participants ap ON ap.arc_id = na.id
     LEFT JOIN public.entity_registry er ON ap.entity_id = er.id
     LEFT JOIN LATERAL (SELECT public.display_for_player(er.id) AS name,
                               er.entity_type AS type, ap.role AS role,
                               er.id AS entity_id, er.handle AS handle) part ON true
  WHERE na.resolved = false
  GROUP BY na.id;

CREATE OR REPLACE VIEW public.v_recent_facts AS
 SELECT f.id,
    f.game_id,
    f.cycle,
    f."time",
    f.type,
    f.description,
    f.importance,
    f.semantic_key,
    l.name AS location_name,
    array_agg(to_jsonb(part.*)) FILTER (WHERE er.id IS NOT NULL) AS participants
   FROM public.facts f
     LEFT JOIN public.locations l ON f.location_id = l.id
     LEFT JOIN public.fact_participants fp ON fp.fact_id = f.id
     LEFT JOIN public.entity_registry er ON fp.entity_id = er.id
     LEFT JOIN LATERAL (SELECT public.display_for_player(er.id) AS name, fp.role AS role,
                               er.id AS entity_id, er.handle AS handle) part ON true
  GROUP BY f.id, l.name;

CREATE OR REPLACE VIEW public.v_chronology AS
 SELECT c.id,
    c.game_id,
    c.cycle,
    c."time",
    l.name AS location_name,
    c.summary,
    array_agg(part.name::character varying(255)) FILTER (WHERE er.id IS NOT NULL)
        AS npcs_present,
    array_agg(to_jsonb(part.*)) FILTER (WHERE er.id IS NOT NULL) AS npc_refs
   FROM public.chronology c
     LEFT JOIN public.locations l ON c.location_id = l.id
     LEFT JOIN public.chronology_participants cp ON cp.chronology_id = c.id
     LEFT JOIN public.entity_registry er ON cp.entity_id = er.id
     LEFT JOIN LATERAL (SELECT public.display_for_player(er.id) AS name,
                               er.id AS entity_id, er.handle AS handle) part ON true
  GROUP BY c.id, l.name;

CREATE OR REPLACE VIEW public.v_upcoming_events AS
 SELECT ev.id,
    ev.game_id,
    ev.type,
    ev.title,
    ev.description,
    ev.planned_cycle,
    ev."time",
    l.name AS location_name,
    array_agg(part.name::character varying(255)) FILTER (WHERE er.id IS NOT NULL)
        AS participants,
    array_agg(to_jsonb(part.*)) FILTER (WHERE er.id IS NOT NULL) AS participant_refs
   FROM public.events ev
     LEFT JOIN public.locations l ON ev.location_id = l.id
     LEFT JOIN public.event_participants ep ON ev.id = ep.event_id
     LEFT JOIN public.entity_registry er ON ep.entity_id = er.id
     LEFT JOIN LATERAL (SELECT public.display_for_player(er.id) AS name,
                               er.id AS entity_id, er.handle AS handle) part ON true
  WHERE ev.completed = false AND ev.cancelled = false
  GROUP BY ev.id, l.name;

-- Section 3: the existing data in the identity model (spec §5.2), in order; every step is
-- idempotent: run again, the section changes nothing (tests/identity/test_migration.py).
-- It is not a turn: nothing here is journaled. It names no word of any language: names are
-- compared through the pack of the game's language (ldvelh_norm_for_game), and the games
-- that exist when it first runs have none yet. For them, scripts/identity_backfill.py
-- finishes the work after this migration: it gives each the configured default language,
-- calls identity_legacy_normalise (norms, orphans, normalised collisions, mentions),
-- classifies the unknown characters' names with the pack's lexicon (step 3) and adds the
-- derived aliases. Until then their name_norm and alias_norm stay NULL (the startup check
-- refuses to serve): identity_norm_fill, which raises for a game without language, is off
-- while this section writes registry and alias rows. Until the backfill, characters keep
-- the provisional model of section 2 (true_name := name, descriptor := unknown_name).

ALTER TABLE public.entity_registry DISABLE TRIGGER identity_norm_fill;
ALTER TABLE public.entity_aliases DISABLE TRIGGER identity_norm_fill;

-- Alias D rows, in turn p_turn's journal, for an entity that turn deleted (p_row: its whole
-- domain row, or its registry row): the forms 3.2 gives a live entity (a character's true
-- name, descriptor, else its label; another entity's label; source 'migration'), so that
-- undoing the turn brings them back with it. alias_norm comes with the game's language
-- (here, or identity_legacy_normalise step d, which also keeps one form per norm).
CREATE OR REPLACE FUNCTION public.identity_journal_aliases(p_turn uuid, p_type text,
                                                           p_row jsonb) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_game uuid := (p_row ->> 'game_id')::uuid;
    v_known boolean := COALESCE((p_row ->> 'known_by_protagonist')::boolean, false);
    v_count integer;
BEGIN
    INSERT INTO public.world_changes (turn_id, table_name, row_id, op, old_row, new_row)
    SELECT p_turn, 'entity_aliases', forms.id, 'D',
           jsonb_build_object('id', forms.id, 'game_id', v_game, 'entity_id', p_row -> 'id',
                              'entity_type', p_type, 'alias', forms.alias,
                              'alias_norm', forms.norm, 'kind', forms.kind,
                              'known', forms.known, 'secret', forms.secret,
                              'source', 'migration', 'created_at', now()),
           NULL
      FROM (SELECT DISTINCT ON (COALESCE(f.norm, f.alias)) gen_random_uuid() AS id, f.*
              FROM (SELECT v.alias, v.kind, v.known, v.secret, v.rank,
                           CASE WHEN gm.language IS NOT NULL
                                THEN public.ldvelh_norm_for_game(v_game, v.alias) END AS norm
                      FROM public.games AS gm,
                           (VALUES
                               (CASE WHEN p_type = 'character' THEN p_row ->> 'true_name'
                                     ELSE p_row ->> 'name' END,
                                CASE WHEN p_type = 'character' THEN 'true_name'
                                     ELSE 'label' END,
                                p_type <> 'character' OR v_known,
                                p_type = 'character' AND NOT v_known
                                    AND COALESCE((p_row ->> 'is_mandatory')::boolean, false),
                                1),
                               (CASE WHEN p_type = 'character' THEN p_row ->> 'descriptor' END,
                                'descriptor', true, false, 2),
                               (CASE WHEN p_type = 'character'
                                          AND p_row ->> 'true_name' IS NULL
                                          AND p_row ->> 'descriptor' IS NULL
                                     THEN p_row ->> 'name' END,
                                'label', true, false, 3)) AS v (alias, kind, known, secret, rank)
                     WHERE gm.id = v_game AND btrim(COALESCE(v.alias, '')) <> '') AS f
             ORDER BY COALESCE(f.norm, f.alias), f.rank) AS forms;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END $$;

-- The alias D rows 3.3 and the backfill add to the journal (source 'migration') must
-- replay without a conflict on UNIQUE (game_id, entity_id, alias_norm), which the replay's
-- ON CONFLICT (id) does not cover: one row per norm in a turn for an entity, and none a
-- live alias of the entity already has. Run by step d and again at the end of each
-- backfill run (classification, exceptions and derived aliases add live aliases). Returns
-- the rows removed.
CREATE OR REPLACE FUNCTION public.identity_journal_alias_conflicts(p_game uuid)
        RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_count integer;
    v_total integer;
BEGIN
    WITH ranked AS (
        SELECT wc.id, row_number() OVER (
                   PARTITION BY wc.turn_id, wc.old_row ->> 'entity_id',
                                wc.old_row ->> 'alias_norm'
                   ORDER BY array_position(ARRAY['true_name', 'label', 'descriptor'],
                                           wc.old_row ->> 'kind'), wc.id) AS rank
          FROM public.world_changes AS wc JOIN public.turns AS tn ON tn.id = wc.turn_id
         WHERE tn.game_id = p_game AND wc.table_name = 'entity_aliases' AND wc.op = 'D'
           AND wc.old_row ->> 'source' = 'migration')
    DELETE FROM public.world_changes AS wc USING ranked
     WHERE wc.id = ranked.id AND ranked.rank > 1;
    GET DIAGNOSTICS v_total = ROW_COUNT;
    DELETE FROM public.world_changes AS wc USING public.turns AS tn
     WHERE tn.id = wc.turn_id AND tn.game_id = p_game AND wc.table_name = 'entity_aliases'
       AND wc.op = 'D' AND wc.old_row ->> 'source' = 'migration'
       AND EXISTS (SELECT 1 FROM public.entity_aliases AS al
                    WHERE al.entity_id::text = wc.old_row ->> 'entity_id'
                      AND al.alias_norm = wc.old_row ->> 'alias_norm');
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_total + v_count;
END $$;

-- A director_commitments journal row without p_id among its related entities.
CREATE OR REPLACE FUNCTION public.identity_drop_related(p_row jsonb, p_id uuid)
        RETURNS jsonb
    LANGUAGE sql IMMUTABLE
    AS $$
    SELECT CASE WHEN jsonb_typeof(p_row -> 'related_entities') = 'array'
                THEN jsonb_set(p_row, '{related_entities}',
                               COALESCE((SELECT jsonb_agg(rel.value ORDER BY rel.pos)
                                           FROM jsonb_array_elements(p_row -> 'related_entities')
                                                WITH ORDINALITY AS rel (value, pos)
                                          WHERE rel.value #>> '{}' <> p_id::text),
                                        '[]'::jsonb))
                ELSE p_row END
$$;

-- The steps of §5.2 that compare normalised names, for one game with a language: section 3
-- runs them for the games that have one, scripts/identity_backfill.py for the others once
-- it gave them one. Idempotent; returns what it changed, by step:
-- a. alias norms: the forms of an entity that normalise alike are kept once (the first by
--    kind: true name, label, descriptor, then derived forms), the others get their norm;
-- b. orphans (registry rows without domain row, step 2): their edges go to the one live
--    entity of the type whose label or alias has the orphan's norm (identity_merge_edges),
--    then the orphan is deleted; without such an entity its edges go with it (counted)
--    and its id leaves the director's commitments. The journal follows, so that undoing a
--    turn played before the migration still commits: the orphan's id becomes the entity's
--    in the rows of its edges and of the alias rows 3.3 added for it, or those rows go
--    when the edges went; its own registry rows go (an undo must not bring back a row the
--    model no longer has);
-- c. normalised collisions (step 6): of the live entities of a type sharing a norm, the
--    oldest keeps its name, the others get the suffix " (2)", " (3)"...: a character in its
--    internal label_suffix (never shown, ruling R9), another entity in its name;
-- d. registry norms, the name_norm of the registry's journal rows included (I7);
-- e. mentions (step 5): each narrator_context span [start, end, name, type] whose (name,
--    type) find_entity resolves to one entity becomes an entity_mentions row
--    ('deterministic'); the others are dropped and counted. narrator_context is kept.
CREATE OR REPLACE FUNCTION public.identity_legacy_normalise(p_game uuid) RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_counts jsonb := '{}'::jsonb;
    v_count integer;
    v_dropped integer;
    v_orphan record;
    v_clash record;
    v_norm text;
    v_targets uuid[];
    v_repointed integer := 0;
    v_deleted integer := 0;
    v_suffixed integer := 0;
    v_suffix integer;
    v_journal_moved integer := 0;
    v_journal_dropped integer := 0;
    v_commitments integer := 0;
    v_edge_tables text[] := ARRAY['relations', 'fact_participants', 'arc_participants',
                                  'chronology_participants', 'event_participants',
                                  'inventory', 'narrative_arcs', 'entity_aliases'];
BEGIN
    -- a.
    WITH ranked AS (
        SELECT al.id, al.alias_norm IS NULL AS missing,
               row_number() OVER (
                   PARTITION BY al.entity_id,
                                COALESCE(al.alias_norm,
                                         public.ldvelh_norm_for_game(p_game, al.alias))
                   ORDER BY al.alias_norm IS NULL,
                            array_position(ARRAY['true_name', 'label', 'descriptor', 'title',
                                                 'short', 'nickname', 'former_name'],
                                           al.kind),
                            al.created_at, al.id) AS rank
          FROM public.entity_aliases AS al
         WHERE al.game_id = p_game)
    DELETE FROM public.entity_aliases AS al USING ranked
     WHERE al.id = ranked.id AND ranked.missing AND ranked.rank > 1;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_counts := v_counts || jsonb_build_object('aliases_deduplicated', v_count);
    UPDATE public.entity_aliases AS al
       SET alias_norm = public.ldvelh_norm_for_game(p_game, al.alias)
     WHERE al.game_id = p_game AND al.alias_norm IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_counts := v_counts || jsonb_build_object('alias_norms', v_count);

    -- b.
    FOR v_orphan IN
        SELECT er.id, er.entity_type, er.name FROM public.entity_registry AS er
         WHERE er.game_id = p_game AND er.merged_into IS NULL
           AND public.identity_domain_row(er.entity_type, er.id) IS NULL
    LOOP
        v_norm := public.ldvelh_norm_for_game(p_game, v_orphan.name);
        SELECT array_agg(DISTINCT cand.id) INTO v_targets
          FROM (SELECT er.id FROM public.entity_registry AS er
                 WHERE er.game_id = p_game AND er.entity_type = v_orphan.entity_type
                   AND er.merged_into IS NULL
                   AND COALESCE(er.name_norm,
                                public.ldvelh_norm_for_game(p_game, er.name)) = v_norm
                UNION
                SELECT al.entity_id FROM public.entity_aliases AS al
                 WHERE al.game_id = p_game AND al.entity_type = v_orphan.entity_type
                   AND al.alias_norm = v_norm) AS cand
         WHERE cand.id <> v_orphan.id
           AND public.identity_domain_row(v_orphan.entity_type, cand.id) IS NOT NULL;
        IF cardinality(v_targets) = 1 THEN
            PERFORM public.identity_merge_edges(v_targets[1], v_orphan.id,
                                                v_orphan.entity_type);
            UPDATE public.world_changes AS wc
               SET old_row = replace(wc.old_row::text, v_orphan.id::text,
                                     v_targets[1]::text)::jsonb,
                   new_row = replace(wc.new_row::text, v_orphan.id::text,
                                     v_targets[1]::text)::jsonb
              FROM public.turns AS tn
             WHERE tn.id = wc.turn_id AND tn.game_id = p_game
               AND wc.table_name = ANY (v_edge_tables || 'director_commitments'::text)
               AND concat(wc.old_row::text, wc.new_row::text) LIKE '%' || v_orphan.id || '%';
            GET DIAGNOSTICS v_count = ROW_COUNT;
            v_journal_moved := v_journal_moved + v_count;
            v_repointed := v_repointed + 1;
        ELSE
            DELETE FROM public.world_changes AS wc USING public.turns AS tn
             WHERE tn.id = wc.turn_id AND tn.game_id = p_game
               AND wc.table_name = ANY (v_edge_tables)
               AND concat(wc.old_row::text, wc.new_row::text) LIKE '%' || v_orphan.id || '%';
            GET DIAGNOSTICS v_count = ROW_COUNT;
            v_journal_dropped := v_journal_dropped + v_count;
            UPDATE public.world_changes AS wc
               SET old_row = public.identity_drop_related(wc.old_row, v_orphan.id),
                   new_row = public.identity_drop_related(wc.new_row, v_orphan.id)
              FROM public.turns AS tn
             WHERE tn.id = wc.turn_id AND tn.game_id = p_game
               AND wc.table_name = 'director_commitments'
               AND concat(wc.old_row::text, wc.new_row::text) LIKE '%' || v_orphan.id || '%';
            UPDATE public.director_commitments AS dc
               SET related_entities = array_remove(dc.related_entities, v_orphan.id)
             WHERE dc.game_id = p_game AND v_orphan.id = ANY (dc.related_entities);
            GET DIAGNOSTICS v_count = ROW_COUNT;
            v_commitments := v_commitments + v_count;
            v_deleted := v_deleted + 1;
        END IF;
        DELETE FROM public.world_changes AS wc USING public.turns AS tn
         WHERE tn.id = wc.turn_id AND tn.game_id = p_game
           AND wc.table_name = 'entity_registry' AND wc.row_id = v_orphan.id;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_journal_dropped := v_journal_dropped + v_count;
        DELETE FROM public.entity_registry WHERE id = v_orphan.id;
    END LOOP;
    v_counts := v_counts || jsonb_build_object(
        'orphans_repointed', v_repointed, 'orphans_deleted', v_deleted,
        'orphan_journal_rows_repointed', v_journal_moved,
        'orphan_journal_rows_dropped', v_journal_dropped,
        'orphan_commitments_purged', v_commitments);

    -- c.
    FOR v_clash IN
        SELECT ranked.id, ranked.entity_type, ranked.name, ranked.rank FROM (
            SELECT er.id, er.entity_type, er.name,
                   row_number() OVER (
                       PARTITION BY er.entity_type,
                                    COALESCE(er.name_norm,
                                             public.ldvelh_norm_for_game(p_game, er.name))
                       ORDER BY (public.identity_domain_row(er.entity_type, er.id)
                                 ->> 'created_at')::timestamptz,
                                er.name COLLATE "C", er.id) AS rank
              FROM public.entity_registry AS er
             WHERE er.game_id = p_game AND er.merged_into IS NULL) AS ranked
         WHERE ranked.rank > 1
         ORDER BY ranked.entity_type, ranked.rank, ranked.id
    LOOP
        v_suffix := v_clash.rank;
        WHILE EXISTS (
            SELECT 1 FROM public.entity_registry AS er
             WHERE er.game_id = p_game AND er.entity_type = v_clash.entity_type
               AND er.merged_into IS NULL
               AND COALESCE(er.name_norm, public.ldvelh_norm_for_game(p_game, er.name))
                   = public.ldvelh_norm_for_game(p_game,
                                                 v_clash.name || ' (' || v_suffix || ')'))
        LOOP
            v_suffix := v_suffix + 1;
        END LOOP;
        IF v_clash.entity_type = 'character' THEN
            UPDATE public.characters SET label_suffix = v_suffix::text WHERE id = v_clash.id;
        ELSE
            EXECUTE 'UPDATE ' || public.identity_domain_table(v_clash.entity_type)::text
                    || ' SET name = name || $2 WHERE id = $1'
              USING v_clash.id, ' (' || v_suffix || ')';
        END IF;
        v_suffixed := v_suffixed + 1;
    END LOOP;
    v_counts := v_counts || jsonb_build_object('collisions_suffixed', v_suffixed);

    -- d.
    UPDATE public.entity_registry AS er
       SET name_norm = public.ldvelh_norm_for_game(p_game, er.name)
     WHERE er.game_id = p_game AND er.name_norm IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    v_counts := v_counts || jsonb_build_object('registry_norms', v_count);
    UPDATE public.world_changes AS wc
       SET old_row = CASE WHEN wc.old_row ? 'name' AND NOT wc.old_row ? 'name_norm'
                          THEN wc.old_row || jsonb_build_object('name_norm',
                                   public.ldvelh_norm_for_game(p_game, wc.old_row ->> 'name'))
                          ELSE wc.old_row END,
           new_row = CASE WHEN wc.new_row ? 'name' AND NOT wc.new_row ? 'name_norm'
                          THEN wc.new_row || jsonb_build_object('name_norm',
                                   public.ldvelh_norm_for_game(p_game, wc.new_row ->> 'name'))
                          ELSE wc.new_row END
      FROM public.turns AS tn
     WHERE tn.id = wc.turn_id AND tn.game_id = p_game AND wc.table_name = 'entity_registry'
       AND ((wc.old_row ? 'name' AND NOT wc.old_row ? 'name_norm')
            OR (wc.new_row ? 'name' AND NOT wc.new_row ? 'name_norm'));
    -- The alias rows 3.3 adds to the journal of an entity a turn deleted.
    UPDATE public.world_changes AS wc
       SET old_row = wc.old_row || jsonb_build_object('alias_norm',
                         public.ldvelh_norm_for_game(p_game, wc.old_row ->> 'alias'))
      FROM public.turns AS tn
     WHERE tn.id = wc.turn_id AND tn.game_id = p_game AND wc.table_name = 'entity_aliases'
       AND wc.old_row ? 'alias' AND (wc.old_row ->> 'alias_norm') IS NULL;
    PERFORM public.identity_journal_alias_conflicts(p_game);

    -- e.
    WITH spans AS (
        SELECT mg.id AS message_id, mg.turn_id, mg.content, span.value AS entry
          FROM public.messages AS mg
         CROSS JOIN LATERAL jsonb_array_elements(
                CASE WHEN jsonb_typeof(mg.narrator_context) = 'array'
                     THEN mg.narrator_context ELSE '[]'::jsonb END) AS span
         WHERE mg.game_id = p_game
           AND jsonb_typeof(span.value) = 'array' AND jsonb_array_length(span.value) >= 4
           AND (span.value ->> 0) ~ '^[0-9]+([.]0+)?$'
           AND (span.value ->> 1) ~ '^[0-9]+([.]0+)?$'
           AND jsonb_typeof(span.value -> 2) = 'string'
           AND jsonb_typeof(span.value -> 3) = 'string'),
    resolved AS (
        SELECT sp.message_id, sp.turn_id, sp.content, sp.entry ->> 2 AS name,
               (sp.entry ->> 0)::numeric::integer AS start_pos,
               (sp.entry ->> 1)::numeric::integer AS end_pos,
               public.find_entity(p_game, sp.entry ->> 2, sp.entry ->> 3) AS entity_id
          FROM spans AS sp),
    inserted AS (
        INSERT INTO public.entity_mentions
               (game_id, message_id, turn_id, start_pos, end_pos, surface, entity_id, decision)
        SELECT p_game, rs.message_id, rs.turn_id, rs.start_pos, rs.end_pos,
               COALESCE(NULLIF(substr(rs.content, rs.start_pos + 1, rs.end_pos - rs.start_pos),
                               ''), rs.name),
               rs.entity_id, 'deterministic'
          FROM resolved AS rs
         WHERE rs.entity_id IS NOT NULL AND rs.start_pos >= 0 AND rs.end_pos > rs.start_pos
        ON CONFLICT (message_id, start_pos, end_pos) DO NOTHING
        RETURNING 1)
    SELECT (SELECT count(*) FROM inserted),
           (SELECT count(*) FROM resolved WHERE resolved.entity_id IS NULL)
      INTO v_count, v_dropped;
    RETURN v_counts || jsonb_build_object('mentions', v_count, 'mentions_dropped', v_dropped);
END $$;

-- Helpers of this section, dropped at its end. The normalisation of a game's language, NULL
-- for a game without one.
CREATE OR REPLACE FUNCTION pg_temp.identity_norm_or_null(p_game_id uuid, p_text text)
        RETURNS text
    LANGUAGE sql STABLE
    AS $$
    SELECT CASE WHEN gm.language IS NOT NULL
                THEN public.ldvelh_norm_for_game(p_game_id, p_text) END
      FROM public.games AS gm WHERE gm.id = p_game_id
$$;

-- p_row with every old id of p_pairs ({old: new}) replaced by its new id: an id is a uuid,
-- so a text replacement only ever hits the id itself.
CREATE OR REPLACE FUNCTION pg_temp.identity_swap_ids(p_row jsonb, p_pairs jsonb)
        RETURNS jsonb
    LANGUAGE plpgsql IMMUTABLE
    AS $$
DECLARE
    v_text text := p_row::text;
    v_pair record;
BEGIN
    IF p_row IS NULL THEN
        RETURN NULL;
    END IF;
    FOR v_pair IN SELECT pair.key, pair.value FROM jsonb_each_text(p_pairs) AS pair LOOP
        v_text := replace(v_text, v_pair.key, v_pair.value);
    END LOOP;
    RETURN v_text::jsonb;
END $$;

-- A characters journal row of the previous schema in the new column set: unknown_name is
-- descriptor, the name is the provisional true name (as section 2 does for live rows). Such
-- a row has unknown_name (a whole row always has it), or a name without any of the columns
-- the name is now computed from: a row written since never has either.
CREATE OR REPLACE FUNCTION pg_temp.identity_character_change(p_row jsonb) RETURNS jsonb
    LANGUAGE plpgsql IMMUTABLE
    AS $$
DECLARE
    v_out jsonb := p_row;
BEGIN
    IF p_row IS NULL OR NOT (p_row ? 'unknown_name'
                             OR (p_row ? 'name'
                                 AND NOT p_row ?| ARRAY['true_name', 'descriptor',
                                                        'label_suffix'])) THEN
        RETURN p_row;
    END IF;
    IF p_row ? 'unknown_name' THEN
        v_out := (v_out - 'unknown_name')
                 || jsonb_build_object('descriptor', p_row -> 'unknown_name');
    END IF;
    IF p_row ? 'name' AND NOT p_row ? 'true_name' THEN
        v_out := v_out || jsonb_build_object('true_name', p_row -> 'name');
    END IF;
    RETURN v_out;
END $$;

-- Every domain row with its entity type.
CREATE OR REPLACE TEMPORARY VIEW identity_domain AS
    SELECT ch.game_id, 'character'::text AS entity_type, ch.id, ch.name::text AS name,
           ch.created_at
      FROM public.characters AS ch
    UNION ALL
    SELECT lc.game_id, 'location', lc.id, lc.name, lc.created_at FROM public.locations AS lc
    UNION ALL
    SELECT og.game_id, 'organization', og.id, og.name, og.created_at
      FROM public.organizations AS og
    UNION ALL
    SELECT ob.game_id, 'object', ob.id, ob.name, ob.created_at FROM public.objects AS ob
    UNION ALL
    SELECT pc.game_id, 'protagonist', pc.id, pc.name, pc.created_at
      FROM public.protagonists AS pc
    UNION ALL
    SELECT cm.game_id, 'companion', cm.id, cm.name, cm.created_at FROM public.companions AS cm;

-- 3.1 Re-identification (step 1). The old trigger gave each registry row its own id and the
-- old code joined by name: a registry row takes the id of the domain row of its type and
-- name (an UPDATE of the key, the foreign keys deferred while its 8 referencing columns
-- and the director's related entities follow), and a domain row without registry row (the
-- companions, never registered before) gets one. identity_reid keeps the pairs for 3.3.
DROP TABLE IF EXISTS pg_temp.identity_reid;
CREATE TEMPORARY TABLE identity_reid (
    game_id uuid NOT NULL,
    old_id uuid PRIMARY KEY,
    new_id uuid NOT NULL UNIQUE
);
INSERT INTO identity_reid (game_id, old_id, new_id)
SELECT DISTINCT ON (er.id) er.game_id, er.id, dom.id
  FROM public.entity_registry AS er
  JOIN identity_domain AS dom
    ON dom.game_id = er.game_id AND dom.entity_type = er.entity_type AND dom.name = er.name
 WHERE er.id <> dom.id AND er.merged_into IS NULL
   AND NOT EXISTS (SELECT 1 FROM public.entity_registry AS taken WHERE taken.id = dom.id)
 ORDER BY er.id, dom.created_at, dom.id;

SET CONSTRAINTS ALL DEFERRED;
UPDATE public.entity_registry AS er SET id = r.new_id
  FROM identity_reid AS r WHERE er.id = r.old_id;
UPDATE public.relations AS t SET source_id = r.new_id
  FROM identity_reid AS r WHERE t.source_id = r.old_id;
UPDATE public.relations AS t SET target_id = r.new_id
  FROM identity_reid AS r WHERE t.target_id = r.old_id;
UPDATE public.fact_participants AS t SET entity_id = r.new_id
  FROM identity_reid AS r WHERE t.entity_id = r.old_id;
UPDATE public.arc_participants AS t SET entity_id = r.new_id
  FROM identity_reid AS r WHERE t.entity_id = r.old_id;
UPDATE public.chronology_participants AS t SET entity_id = r.new_id
  FROM identity_reid AS r WHERE t.entity_id = r.old_id;
UPDATE public.event_participants AS t SET entity_id = r.new_id
  FROM identity_reid AS r WHERE t.entity_id = r.old_id;
UPDATE public.inventory AS t SET owner_id = r.new_id
  FROM identity_reid AS r WHERE t.owner_id = r.old_id;
UPDATE public.narrative_arcs AS t SET owner_id = r.new_id
  FROM identity_reid AS r WHERE t.owner_id = r.old_id;
UPDATE public.director_commitments AS dc
   SET related_entities = ARRAY(
           SELECT COALESCE(r.new_id, rel.id)
             FROM unnest(dc.related_entities) WITH ORDINALITY AS rel (id, pos)
             LEFT JOIN identity_reid AS r ON r.old_id = rel.id
            ORDER BY rel.pos)
 WHERE dc.related_entities && ARRAY(SELECT r.old_id FROM identity_reid AS r);
SET CONSTRAINTS ALL IMMEDIATE;

INSERT INTO public.entity_registry (id, game_id, entity_type, name, name_norm)
SELECT dom.id, dom.game_id, dom.entity_type, dom.name,
       pg_temp.identity_norm_or_null(dom.game_id, dom.name)
  FROM identity_domain AS dom
 WHERE NOT EXISTS (SELECT 1 FROM public.entity_registry AS er WHERE er.id = dom.id)
 ORDER BY dom.game_id, dom.created_at, dom.id;

-- 3.2 Aliases and knowledge flags (step 4). Each entity gets the aliases of its names, as
-- identity_name_aliases gives a new one, with source 'migration': a character's true name
-- (known when the PC knows it; secret when the character is mandatory and unknown, listed
-- in the dry-run report for the user to confirm), descriptor (known) and suffixed label;
-- another entity's label. A form the entity already has (same text or same norm) is
-- skipped; forms that only normalise alike are kept once by identity_legacy_normalise.
INSERT INTO public.entity_aliases
       (game_id, entity_id, entity_type, alias, alias_norm, kind, known, secret, source)
SELECT DISTINCT ON (forms.entity_id, forms.alias)
       forms.game_id, forms.entity_id, forms.entity_type, forms.alias,
       pg_temp.identity_norm_or_null(forms.game_id, forms.alias),
       forms.kind, forms.known, forms.secret, 'migration'
  FROM (SELECT ch.game_id, ch.id AS entity_id, 'character' AS entity_type,
               ch.true_name::text AS alias, 'true_name' AS kind,
               ch.known_by_protagonist AS known,
               COALESCE(ch.is_mandatory AND NOT ch.known_by_protagonist, false) AS secret,
               1 AS rank
          FROM public.characters AS ch
        UNION ALL
        SELECT ch.game_id, ch.id, 'character', ch.descriptor, 'descriptor', true, false, 2
          FROM public.characters AS ch
        UNION ALL
        SELECT ch.game_id, ch.id, 'character', ch.name, 'label',
               ch.true_name IS NULL OR COALESCE(ch.known_by_protagonist, false), false, 3
          FROM public.characters AS ch WHERE ch.label_suffix IS NOT NULL
        UNION ALL
        SELECT dom.game_id, dom.id, dom.entity_type, dom.name, 'label', true, false, 1
          FROM identity_domain AS dom WHERE dom.entity_type <> 'character') AS forms
 WHERE btrim(COALESCE(forms.alias, '')) <> ''
   AND NOT EXISTS (
        SELECT 1 FROM public.entity_aliases AS al
         WHERE al.entity_id = forms.entity_id
           AND (al.alias = forms.alias
                OR al.alias_norm = pg_temp.identity_norm_or_null(forms.game_id, forms.alias)))
 ORDER BY forms.entity_id, forms.alias, forms.rank
ON CONFLICT DO NOTHING;

-- An object's canonical key (dropped in section 4) becomes a label alias. Dynamic: the
-- column is gone when the section runs again.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'objects'
                  AND column_name = 'canonical_name') THEN
        EXECUTE $sql$
            INSERT INTO public.entity_aliases
                   (game_id, entity_id, entity_type, alias, alias_norm, kind, known, source)
            SELECT ob.game_id, ob.id, 'object', ob.canonical_name,
                   pg_temp.identity_norm_or_null(ob.game_id, ob.canonical_name), 'label', true,
                   'migration'
              FROM public.objects AS ob
             WHERE btrim(COALESCE(ob.canonical_name, '')) <> ''
               AND NOT EXISTS (
                    SELECT 1 FROM public.entity_aliases AS al
                     WHERE al.entity_id = ob.id
                       AND (al.alias = ob.canonical_name
                            OR al.alias_norm
                               = pg_temp.identity_norm_or_null(ob.game_id, ob.canonical_name)))
            ON CONFLICT DO NOTHING
        $sql$;
    END IF;
END $$;

-- Facts: known when the extraction wrote them (after the game's first message: the PC was
-- there) or the protagonist takes part, the other facts of the world generation unknown;
-- secret for the facts of type secret (listed in the dry-run report). Games without
-- language only: the facts of a game created since keep the flags they were given.
UPDATE public.facts AS ft
   SET known = flags.known, secret = flags.secret
  FROM (SELECT f.id,
               COALESCE(f.created_at >= (SELECT min(mg.created_at) FROM public.messages AS mg
                                          WHERE mg.game_id = f.game_id), false)
               OR EXISTS (SELECT 1 FROM public.fact_participants AS fp
                            JOIN public.entity_registry AS er ON er.id = fp.entity_id
                           WHERE fp.fact_id = f.id AND er.entity_type = 'protagonist')
                   AS known,
               f.type = 'secret' AS secret
          FROM public.facts AS f JOIN public.games AS gm ON gm.id = f.game_id
         WHERE gm.language IS NULL) AS flags
 WHERE ft.id = flags.id AND (ft.known, ft.secret) IS DISTINCT FROM (flags.known, flags.secret);

-- 3.3 The journal of the turns played before this migration (P5a, I7), rewritten so that
-- undoing such a turn after the deploy is exact:
-- * the ids: 3.1's pairs, plus those of an entity a journaled turn deleted, paired by type
--   and name with its domain row in the same turn (registry and domain rows of one I or D),
--   in the rows of the registry, of the tables of its 8 referencing columns and of the
--   director's commitments (row_id of the registry's rows included);
-- * the columns: a characters row in the new set (identity_character_change); an objects
--   row without canonical_name; a whole registry row (I, D) with its handle, a whole facts
--   row with its handle and flags: those of the live row, else (an entity or fact no
--   longer there) a handle past the game's last one, reserved by an identity_events row
--   ('handle_reserved', see identity_assign_handle), and for a fact the flags of 3.2's
--   rule. The registry
--   rows' name_norm comes with the game's language (identity_legacy_normalise, step d);
-- * the aliases of an entity a turn deleted: alias D rows in that turn (identity_journal_
--   aliases), so that undoing it brings the entity back with the aliases of its names.
-- An id that pairs ambiguously is left as it is (NOTICE with the count), never an abort.
DO $$
DECLARE
    v_left integer;
BEGIN
    WITH candidates AS (
        SELECT DISTINCT ON (reg.row_id) tn.game_id, reg.row_id, dom.row_id AS new_id
          FROM public.world_changes AS reg
          JOIN public.turns AS tn ON tn.id = reg.turn_id
          JOIN public.world_changes AS dom
            ON dom.turn_id = reg.turn_id AND dom.op = reg.op
           AND dom.table_name = CASE COALESCE(reg.old_row, reg.new_row) ->> 'entity_type'
                                    WHEN 'character' THEN 'characters'
                                    WHEN 'location' THEN 'locations'
                                    WHEN 'organization' THEN 'organizations'
                                    WHEN 'object' THEN 'objects'
                                    WHEN 'protagonist' THEN 'protagonists'
                                    WHEN 'companion' THEN 'companions' END
           AND COALESCE(dom.old_row, dom.new_row) ->> 'name'
               = COALESCE(reg.old_row, reg.new_row) ->> 'name'
         WHERE reg.table_name = 'entity_registry' AND reg.op <> 'U' AND reg.row_id <> dom.row_id
           AND NOT EXISTS (SELECT 1 FROM public.entity_registry AS er WHERE er.id = reg.row_id)
           AND NOT EXISTS (SELECT 1 FROM public.entity_registry AS er WHERE er.id = dom.row_id)
           AND NOT EXISTS (SELECT 1 FROM identity_reid AS r
                            WHERE r.old_id = reg.row_id OR r.new_id = dom.row_id)
         ORDER BY reg.row_id, dom.id),
    paired AS (
        INSERT INTO identity_reid (game_id, old_id, new_id)
        SELECT cd.game_id, cd.row_id, cd.new_id FROM candidates AS cd
        ON CONFLICT DO NOTHING
        RETURNING 1)
    SELECT (SELECT count(*) FROM candidates) - (SELECT count(*) FROM paired) INTO v_left;
    IF v_left > 0 THEN
        RAISE NOTICE 'identity migration: % journaled registry ids left unpaired', v_left;
    END IF;
END $$;

UPDATE public.world_changes AS wc
   SET old_row = pg_temp.identity_swap_ids(wc.old_row, pairs.ids),
       new_row = pg_temp.identity_swap_ids(wc.new_row, pairs.ids),
       row_id = CASE WHEN wc.table_name = 'entity_registry'
                     THEN COALESCE((pairs.ids ->> wc.row_id::text)::uuid, wc.row_id)
                     ELSE wc.row_id END
  FROM public.turns AS tn,
       (SELECT r.game_id, jsonb_object_agg(r.old_id::text, r.new_id::text) AS ids
          FROM identity_reid AS r GROUP BY r.game_id) AS pairs
 WHERE tn.id = wc.turn_id AND pairs.game_id = tn.game_id
   AND wc.table_name IN ('entity_registry', 'relations', 'fact_participants',
                         'arc_participants', 'chronology_participants', 'event_participants',
                         'inventory', 'narrative_arcs', 'director_commitments');

UPDATE public.world_changes AS wc
   SET old_row = pg_temp.identity_character_change(wc.old_row),
       new_row = pg_temp.identity_character_change(wc.new_row)
 WHERE wc.table_name = 'characters'
   AND (pg_temp.identity_character_change(wc.old_row) IS DISTINCT FROM wc.old_row
        OR pg_temp.identity_character_change(wc.new_row) IS DISTINCT FROM wc.new_row);

UPDATE public.world_changes AS wc
   SET old_row = wc.old_row - 'canonical_name', new_row = wc.new_row - 'canonical_name'
 WHERE wc.table_name = 'objects'
   AND (wc.old_row ? 'canonical_name' OR wc.new_row ? 'canonical_name');

DROP TABLE IF EXISTS pg_temp.identity_journal_fill;
CREATE TEMPORARY TABLE identity_journal_fill AS
WITH whole AS (
    SELECT DISTINCT ON (wc.table_name, wc.row_id) tn.game_id, wc.table_name, wc.row_id,
           COALESCE(wc.old_row, wc.new_row) AS whole_row
      FROM public.world_changes AS wc JOIN public.turns AS tn ON tn.id = wc.turn_id
     WHERE wc.table_name IN ('entity_registry', 'facts') AND wc.op <> 'U'
       AND NOT COALESCE(wc.old_row, wc.new_row) ? 'handle'
     ORDER BY wc.table_name, wc.row_id, wc.id),
gone AS (
    SELECT wh.game_id, wh.table_name, wh.row_id, wh.whole_row,
           GREATEST((SELECT COALESCE(max(ft.handle), 0) FROM public.facts AS ft
                      WHERE ft.game_id = wh.game_id AND wh.table_name = 'facts')
                    + (SELECT COALESCE(max(er.handle), 0) FROM public.entity_registry AS er
                        WHERE er.game_id = wh.game_id AND wh.table_name = 'entity_registry'),
                    (SELECT COALESCE(max((ev.payload ->> 'handle')::integer), 0)
                       FROM public.identity_events AS ev
                      WHERE ev.game_id = wh.game_id AND ev.kind = 'handle_reserved'
                        AND ev.payload ->> 'table' = wh.table_name))
           + row_number() OVER (PARTITION BY wh.game_id, wh.table_name ORDER BY wh.row_id)
               AS handle
      FROM whole AS wh
     WHERE NOT EXISTS (SELECT 1 FROM public.facts AS ft WHERE ft.id = wh.row_id)
       AND NOT EXISTS (SELECT 1 FROM public.entity_registry AS er WHERE er.id = wh.row_id))
SELECT wh.game_id, wh.table_name, wh.row_id, gn.handle AS reserved,
       CASE WHEN wh.table_name = 'facts' THEN
                COALESCE(
                    (SELECT jsonb_build_object('handle', ft.handle, 'known', ft.known,
                                               'secret', ft.secret)
                       FROM public.facts AS ft WHERE ft.id = wh.row_id),
                    jsonb_build_object(
                        'handle', gn.handle,
                        'known',
                        COALESCE((wh.whole_row ->> 'created_at')::timestamptz
                                 >= (SELECT min(mg.created_at) FROM public.messages AS mg
                                      WHERE mg.game_id = wh.game_id), false)
                        OR EXISTS (
                            SELECT 1 FROM public.world_changes AS fp
                              JOIN public.turns AS tp ON tp.id = fp.turn_id
                              JOIN public.entity_registry AS er
                                ON er.id::text = COALESCE(fp.old_row, fp.new_row) ->> 'entity_id'
                             WHERE tp.game_id = wh.game_id
                               AND fp.table_name = 'fact_participants'
                               AND COALESCE(fp.old_row, fp.new_row) ->> 'fact_id'
                                   = wh.row_id::text
                               AND er.entity_type = 'protagonist'),
                        'secret',
                        COALESCE((jsonb_populate_record(NULL::public.facts, wh.whole_row)).type
                                 = 'secret', false)))
            ELSE
                COALESCE((SELECT jsonb_build_object('handle', er.handle)
                            FROM public.entity_registry AS er WHERE er.id = wh.row_id),
                         jsonb_build_object('handle', gn.handle))
       END AS extra
  FROM whole AS wh LEFT JOIN gone AS gn
    ON gn.table_name = wh.table_name AND gn.row_id = wh.row_id;

INSERT INTO public.identity_events (game_id, kind, payload)
SELECT fl.game_id, 'handle_reserved',
       jsonb_build_object('table', fl.table_name, 'handle', fl.reserved,
                          'row_id', fl.row_id)
  FROM identity_journal_fill AS fl WHERE fl.reserved IS NOT NULL;

UPDATE public.world_changes AS wc
   SET old_row = CASE WHEN wc.old_row IS NULL THEN NULL ELSE wc.old_row || fl.extra END,
       new_row = CASE WHEN wc.new_row IS NULL THEN NULL ELSE wc.new_row || fl.extra END
  FROM identity_journal_fill AS fl
 WHERE wc.table_name = fl.table_name AND wc.row_id = fl.row_id AND wc.op <> 'U'
   AND NOT COALESCE(wc.old_row, wc.new_row) ? 'handle';

SELECT public.identity_journal_aliases(
           reg.turn_id, reg.old_row ->> 'entity_type', COALESCE(dom.old_row, reg.old_row))
  FROM public.world_changes AS reg
  LEFT JOIN public.world_changes AS dom
    ON dom.turn_id = reg.turn_id AND dom.op = 'D' AND dom.row_id = reg.row_id
   AND dom.table_name <> 'entity_registry'
 WHERE reg.table_name = 'entity_registry' AND reg.op = 'D'
   AND NOT EXISTS (SELECT 1 FROM public.entity_registry AS er WHERE er.id = reg.row_id)
   AND NOT EXISTS (SELECT 1 FROM public.world_changes AS al
                    WHERE al.turn_id = reg.turn_id AND al.table_name = 'entity_aliases'
                      AND al.old_row ->> 'entity_id' = reg.row_id::text);

-- A rename such a turn made: the alias of the former name comes back with the undo. Never
-- secret: the old schema shows nothing about it (the player may have read it); the
-- backfill turns it into a descriptor when the classification says so.
SELECT public.identity_journal_aliases(
           reg.turn_id, er.entity_type,
           CASE WHEN er.entity_type = 'character'
                THEN jsonb_build_object('id', reg.row_id, 'game_id', er.game_id,
                                        'true_name', reg.old_row ->> 'name',
                                        'known_by_protagonist', ch.known_by_protagonist)
                ELSE jsonb_build_object('id', reg.row_id, 'game_id', er.game_id,
                                        'name', reg.old_row ->> 'name') END)
  FROM public.world_changes AS reg
  JOIN public.entity_registry AS er ON er.id = reg.row_id
  LEFT JOIN public.characters AS ch ON ch.id = reg.row_id
 WHERE reg.table_name = 'entity_registry' AND reg.op = 'U' AND reg.old_row ? 'name'
   AND NOT EXISTS (SELECT 1 FROM public.world_changes AS al
                    WHERE al.turn_id = reg.turn_id AND al.table_name = 'entity_aliases'
                      AND COALESCE(al.old_row, al.new_row) ->> 'entity_id'
                          = reg.row_id::text);

ALTER TABLE public.entity_registry ENABLE TRIGGER identity_norm_fill;
ALTER TABLE public.entity_aliases ENABLE TRIGGER identity_norm_fill;
DROP VIEW pg_temp.identity_domain;
DROP FUNCTION pg_temp.identity_character_change(jsonb);
DROP FUNCTION pg_temp.identity_swap_ids(jsonb, jsonb);
DROP FUNCTION pg_temp.identity_norm_or_null(uuid, text);
DROP TABLE pg_temp.identity_reid;
DROP TABLE pg_temp.identity_journal_fill;

-- 3.4 The normalised steps (identity_legacy_normalise) of the games that have a language.
SELECT public.identity_legacy_normalise(gm.id) FROM public.games AS gm
 WHERE gm.language IS NOT NULL;


-- Section 4: constraints that need every existing row normalised. The normalised
-- uniqueness of live entities replaces UNIQUE (game_id, entity_type, name); name_norm is
-- set NOT NULL only when every row has one (games without a language are normalised by
-- the backfill; the PR 1b migration then sets it NOT NULL).
DROP INDEX public.idx_objects_canonical;
ALTER TABLE public.objects DROP COLUMN canonical_name;
CREATE UNIQUE INDEX entity_registry_game_type_norm_live_key
    ON public.entity_registry (game_id, entity_type, name_norm) WHERE merged_into IS NULL;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.entity_registry WHERE name_norm IS NULL) THEN
        ALTER TABLE public.entity_registry ALTER COLUMN name_norm SET NOT NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.entity_aliases WHERE alias_norm IS NULL) THEN
        ALTER TABLE public.entity_aliases ALTER COLUMN alias_norm SET NOT NULL;
    END IF;
END $$;

-- migrate:down
-- Section 4, then section 2, undone in reverse order. Views first: they use
-- display_for_player. Aliases, mentions, merges and identity events are dropped with their
-- tables; tombstones and companion registry rows, unknown to the previous schema, go.
DROP INDEX public.entity_registry_game_type_norm_live_key;
ALTER TABLE public.objects ADD COLUMN canonical_name character varying(100);
CREATE UNIQUE INDEX idx_objects_canonical ON public.objects
    USING btree (game_id, canonical_name)
    WHERE ((canonical_name IS NOT NULL) AND (removed_cycle IS NULL));

CREATE OR REPLACE VIEW public.v_active_arcs AS
 SELECT na.id,
    na.game_id,
    na.title,
    na.domain,
    na.description,
    na.intensity,
    array_agg(to_jsonb(part.*)) FILTER (WHERE er.name IS NOT NULL) AS participants
   FROM public.narrative_arcs na
     LEFT JOIN public.arc_participants ap ON ap.arc_id = na.id
     LEFT JOIN public.entity_registry er ON ap.entity_id = er.id
     LEFT JOIN LATERAL (SELECT er.name AS name, er.entity_type AS type,
                               ap.role AS role) part ON true
  WHERE na.resolved = false
  GROUP BY na.id;

CREATE OR REPLACE VIEW public.v_recent_facts AS
 SELECT f.id,
    f.game_id,
    f.cycle,
    f."time",
    f.type,
    f.description,
    f.importance,
    f.semantic_key,
    l.name AS location_name,
    array_agg(jsonb_build_object('name', er.name, 'role', fp.role))
        FILTER (WHERE er.name IS NOT NULL) AS participants
   FROM public.facts f
     LEFT JOIN public.locations l ON f.location_id = l.id
     LEFT JOIN public.fact_participants fp ON fp.fact_id = f.id
     LEFT JOIN public.entity_registry er ON fp.entity_id = er.id
  GROUP BY f.id, l.name;

DROP VIEW public.v_chronology;
CREATE VIEW public.v_chronology AS
 SELECT c.id,
    c.game_id,
    c.cycle,
    c."time",
    l.name AS location_name,
    c.summary,
    array_agg(er.name) FILTER (WHERE er.name IS NOT NULL) AS npcs_present
   FROM public.chronology c
     LEFT JOIN public.locations l ON c.location_id = l.id
     LEFT JOIN public.chronology_participants cp ON cp.chronology_id = c.id
     LEFT JOIN public.entity_registry er ON cp.entity_id = er.id
  GROUP BY c.id, l.name;

DROP VIEW public.v_upcoming_events;
CREATE VIEW public.v_upcoming_events AS
 SELECT ev.id,
    ev.game_id,
    ev.type,
    ev.title,
    ev.description,
    ev.planned_cycle,
    ev."time",
    l.name AS location_name,
    array_agg(er.name) FILTER (WHERE er.name IS NOT NULL) AS participants
   FROM public.events ev
     LEFT JOIN public.locations l ON ev.location_id = l.id
     LEFT JOIN public.event_participants ep ON ev.id = ep.event_id
     LEFT JOIN public.entity_registry er ON ep.entity_id = er.id
  WHERE ev.completed = false AND ev.cancelled = false
  GROUP BY ev.id, l.name;

DROP FUNCTION public.identity_legacy_normalise(uuid);
DROP FUNCTION public.identity_drop_related(jsonb, uuid);
DROP FUNCTION public.identity_journal_alias_conflicts(uuid);
DROP FUNCTION public.identity_journal_aliases(uuid, text, jsonb);
DROP FUNCTION public.merge_entities(uuid, uuid, text, text);
DROP FUNCTION public.identity_merge_edges(uuid, uuid, text);
DROP FUNCTION public.identity_merge_fields(uuid, uuid, text);
DROP FUNCTION public.identity_domain_row(text, uuid);
DROP FUNCTION public.identity_domain_table(text);

CREATE FUNCTION public.find_entity(p_game_id uuid, p_name text,
        p_type character varying DEFAULT NULL::character varying) RETURNS uuid
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
  v_id UUID;
  v_name TEXT := LOWER(BTRIM(p_name, E' \t\r\n'));
BEGIN
  IF v_name = 'protagonist' THEN
    SELECT id INTO v_id FROM entity_registry
    WHERE game_id = p_game_id
      AND entity_type = 'protagonist'
      AND (p_type IS NULL OR p_type = 'protagonist')
    LIMIT 1;
    RETURN v_id;
  END IF;
  SELECT id INTO v_id FROM entity_registry
  WHERE game_id = p_game_id
    AND (p_type IS NULL OR entity_type = p_type)
    AND LOWER(name) = v_name
  LIMIT 1;
  RETURN v_id;
END;
$$;

DROP FUNCTION public.end_relation(uuid, uuid, uuid, public.relation_type, integer, text);
CREATE FUNCTION public.end_relation(p_game_id uuid, p_source_name text, p_target_name text,
        p_type public.relation_type, p_cycle integer, p_reason text DEFAULT NULL::text)
        RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
  v_source_id UUID;
  v_target_id UUID;
BEGIN
  v_source_id := find_entity(p_game_id, p_source_name);
  v_target_id := find_entity(p_game_id, p_target_name);
  IF v_source_id IS NULL OR v_target_id IS NULL THEN RETURN false; END IF;
  UPDATE relations SET end_cycle = p_cycle, end_reason = p_reason
  WHERE game_id = p_game_id
    AND source_id = v_source_id
    AND target_id = v_target_id
    AND type = p_type
    AND end_cycle IS NULL;
  RETURN FOUND;
END;
$$;

-- Participants by name again: [{"name": "...", "role": "actor"}].
CREATE OR REPLACE FUNCTION public.create_fact(p_game_id uuid, p_cycle integer,
        p_type character varying, p_description text, p_location_id uuid DEFAULT NULL::uuid,
        p_time character varying DEFAULT NULL::character varying, p_importance integer DEFAULT 3,
        p_participants jsonb DEFAULT '[]'::jsonb,
        p_semantic_key character varying DEFAULT NULL::character varying) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
DECLARE
  v_fact_id UUID;
  v_participant JSONB;
  v_entity_id UUID;
BEGIN
  IF p_semantic_key IS NOT NULL THEN
    SELECT id INTO v_fact_id FROM facts
    WHERE game_id = p_game_id AND cycle = p_cycle AND semantic_key = p_semantic_key;
    IF v_fact_id IS NOT NULL THEN RETURN v_fact_id; END IF;
  END IF;
  INSERT INTO facts (game_id, cycle, type, description, location_id, time, importance, semantic_key)
  VALUES (p_game_id, p_cycle, p_type, p_description, p_location_id, p_time, p_importance, p_semantic_key)
  RETURNING id INTO v_fact_id;
  FOR v_participant IN SELECT * FROM jsonb_array_elements(p_participants)
  LOOP
    v_entity_id := find_entity(p_game_id, v_participant->>'name');
    IF v_entity_id IS NOT NULL THEN
      INSERT INTO fact_participants (fact_id, entity_id, role)
      VALUES (v_fact_id, v_entity_id, v_participant->>'role')
      ON CONFLICT (fact_id, entity_id) DO NOTHING;
    END IF;
  END LOOP;
  RETURN v_fact_id;
END;
$$;

DROP FUNCTION public.display_for_player(uuid);
DROP FUNCTION public.find_fact(uuid, text);
DROP FUNCTION public.find_entity(uuid, text, text);
DROP FUNCTION public.entity_follow_merge(uuid);

-- The previous logic; its message was French prose, which this file may not hold
-- (tests/identity/test_genericity.py): the same check with an English message.
CREATE OR REPLACE FUNCTION public.facts_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  -- Replay (#22): a location coming back restores the location_id SET NULL cleared.
  IF current_setting('ldvelh.replay', true) = 'on' THEN
    RETURN NEW;
  END IF;
  IF NEW.location_id IS NULL AND OLD.location_id IS NOT NULL
     AND (to_jsonb(NEW) - 'location_id') = (to_jsonb(OLD) - 'location_id') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'facts are immutable';
END;
$$;

DROP TRIGGER identity_handle ON public.facts;
DROP TRIGGER identity_handle ON public.entity_registry;
DROP TRIGGER identity_norm_fill ON public.entity_registry;
DROP TRIGGER identity_character_name ON public.characters;
DROP TRIGGER register_character ON public.characters;
DROP TRIGGER register_location ON public.locations;
DROP TRIGGER register_organization ON public.organizations;
DROP TRIGGER register_object ON public.objects;
DROP TRIGGER register_protagonist ON public.protagonists;
DROP TRIGGER register_companion ON public.companions;
DROP TRIGGER sync_registry_character ON public.characters;
DROP TRIGGER sync_registry_location ON public.locations;
DROP TRIGGER sync_registry_organization ON public.organizations;
DROP TRIGGER sync_registry_object ON public.objects;
DROP TRIGGER sync_registry_protagonist ON public.protagonists;
DROP TRIGGER sync_registry_companion ON public.companions;
DROP TRIGGER unregister_character ON public.characters;
DROP TRIGGER unregister_location ON public.locations;
DROP TRIGGER unregister_organization ON public.organizations;
DROP TRIGGER unregister_object ON public.objects;
DROP TRIGGER unregister_protagonist ON public.protagonists;
DROP TRIGGER unregister_companion ON public.companions;
DROP FUNCTION public.identity_unregister();
DROP FUNCTION public.identity_sync_name();
DROP FUNCTION public.identity_register();
DROP FUNCTION public.identity_name_aliases(text, jsonb, uuid);
DROP FUNCTION public.identity_character_name();
DROP FUNCTION public.identity_assign_handle();

DROP FUNCTION public.identity_event_is_state(text);
DROP TABLE public.identity_events;
DROP TABLE public.entity_merges;
DROP TABLE public.entity_mentions;
DROP TABLE public.entity_aliases;
DROP FUNCTION public.identity_norm_fill();

ALTER TABLE public.facts
    DROP CONSTRAINT facts_game_id_handle_key,
    DROP COLUMN handle,
    DROP COLUMN secret,
    DROP COLUMN known;

ALTER TABLE public.objects
    ADD CONSTRAINT objects_game_id_name_key UNIQUE (game_id, name);
ALTER TABLE public.organizations
    ADD CONSTRAINT organizations_game_id_name_key UNIQUE (game_id, name);
ALTER TABLE public.locations
    ADD CONSTRAINT locations_game_id_name_key UNIQUE (game_id, name);
ALTER TABLE public.characters
    DROP CONSTRAINT characters_true_name_or_descriptor,
    DROP COLUMN label_suffix,
    DROP COLUMN true_name,
    ADD CONSTRAINT characters_game_id_name_key UNIQUE (game_id, name);
ALTER TABLE public.characters RENAME COLUMN descriptor TO unknown_name;

DELETE FROM public.entity_registry
 WHERE merged_into IS NOT NULL OR entity_type = 'companion';
DROP INDEX public.idx_entity_registry_norm;
ALTER TABLE public.entity_registry
    DROP CONSTRAINT entity_registry_game_id_handle_key,
    DROP CONSTRAINT entity_registry_entity_type_check,
    DROP CONSTRAINT entity_registry_created_turn_id_fkey,
    DROP CONSTRAINT entity_registry_merged_into_fkey,
    DROP COLUMN created_turn_id,
    DROP COLUMN merged_into,
    DROP COLUMN handle,
    DROP COLUMN name_norm,
    ADD CONSTRAINT entity_registry_game_id_entity_type_name_key
        UNIQUE (game_id, entity_type, name);

CREATE FUNCTION public.register_entity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  -- Replay (#22): the registry row comes back from the journal.
  IF current_setting('ldvelh.replay', true) = 'on' THEN
    RETURN NEW;
  END IF;
  INSERT INTO entity_registry (game_id, entity_type, name)
  VALUES (NEW.game_id, TG_ARGV[0], NEW.name)
  ON CONFLICT (game_id, entity_type, name) DO NOTHING;
  RETURN NEW;
END;
$$;

CREATE FUNCTION public.update_entity_registry_name() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  -- Replay (#22): the registry name comes back from the journal.
  IF current_setting('ldvelh.replay', true) = 'on' THEN
    RETURN NEW;
  END IF;
  IF OLD.name != NEW.name THEN
    UPDATE entity_registry
    SET name = NEW.name
    WHERE game_id = NEW.game_id AND entity_type = TG_ARGV[0] AND name = OLD.name;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER register_character AFTER INSERT ON public.characters
    FOR EACH ROW EXECUTE FUNCTION public.register_entity('character');
CREATE TRIGGER register_location AFTER INSERT ON public.locations
    FOR EACH ROW EXECUTE FUNCTION public.register_entity('location');
CREATE TRIGGER register_object AFTER INSERT ON public.objects
    FOR EACH ROW EXECUTE FUNCTION public.register_entity('object');
CREATE TRIGGER register_organization AFTER INSERT ON public.organizations
    FOR EACH ROW EXECUTE FUNCTION public.register_entity('organization');
CREATE TRIGGER register_protagonist AFTER INSERT ON public.protagonists
    FOR EACH ROW EXECUTE FUNCTION public.register_entity('protagonist');
CREATE TRIGGER update_registry_character AFTER UPDATE OF name ON public.characters
    FOR EACH ROW EXECUTE FUNCTION public.update_entity_registry_name('character');
CREATE TRIGGER update_registry_location AFTER UPDATE OF name ON public.locations
    FOR EACH ROW EXECUTE FUNCTION public.update_entity_registry_name('location');
CREATE TRIGGER update_registry_object AFTER UPDATE OF name ON public.objects
    FOR EACH ROW EXECUTE FUNCTION public.update_entity_registry_name('object');
CREATE TRIGGER update_registry_organization AFTER UPDATE OF name ON public.organizations
    FOR EACH ROW EXECUTE FUNCTION public.update_entity_registry_name('organization');

-- Section 1 (normalisation) is undone last: the later sections use it.
DROP FUNCTION public.ldvelh_norm_for_game(uuid, text);
DROP FUNCTION public.ldvelh_lang_params(uuid);
ALTER TABLE public.games DROP COLUMN language;
DROP TABLE public.lang_packs;
DROP FUNCTION public.ldvelh_norm(text, jsonb);
DROP FUNCTION public.ldvelh_norm_fold(text, jsonb);
DROP FUNCTION public.ldvelh_unaccent(text);
DROP EXTENSION IF EXISTS fuzzystrmatch;
DROP EXTENSION IF EXISTS unaccent;
DROP EXTENSION IF EXISTS pg_trgm;
