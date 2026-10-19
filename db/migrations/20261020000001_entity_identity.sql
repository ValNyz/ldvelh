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

-- Steps 1-2 of ldvelh_norm, also applied to the pack entries before comparing: lower case,
-- unaccent, every Unicode space as a plain space, every pack apostrophe as a plain one.
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

-- 3. drop an ordinal marker before a number; 4. drop every character that is not a letter,
-- a digit, a space, an apostrophe or a hyphen; 5. keep a hyphen only between two letters,
-- collapse spaces; 6. drop one leading elision (prefix) or article (whole word) when
-- something follows it; 7. drop apostrophes, collapse spaces.
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
    v_out := public.ldvelh_norm_fold(p_text, p_params);

    SELECT string_agg(regexp_replace(mrk.folded, '([^[:alnum:] ])', '\\\1', 'g'), '|'
                      ORDER BY length(mrk.folded) DESC)
      INTO v_markers
      FROM (SELECT btrim(public.ldvelh_norm_fold(entry, p_params), ' ') AS folded
              FROM jsonb_array_elements_text(p_params -> 'ordinal_markers') AS entry) AS mrk
     WHERE mrk.folded <> '';
    IF v_markers IS NOT NULL THEN
        v_out := regexp_replace(v_out, '(^|[^[:alnum:]])(' || v_markers || ') *(?=[0-9])',
                                '\1', 'g');
    END IF;

    v_out := regexp_replace(v_out, '[^[:alnum:] ''-]', '', 'g');
    v_out := regexp_replace(v_out, '(?<![[:alpha:]])-|-(?![[:alpha:]])', '', 'g');
    v_out := btrim(regexp_replace(v_out, ' +', ' ', 'g'), ' ');

    FOR v_prefix IN
        SELECT eli.folded
          FROM (SELECT btrim(public.ldvelh_norm_fold(entry, p_params), ' ') AS folded
                  FROM jsonb_array_elements_text(p_params -> 'elisions') AS entry) AS eli
         WHERE eli.folded <> ''
         ORDER BY length(eli.folded) DESC
    LOOP
        IF length(v_out) > length(v_prefix) AND left(v_out, length(v_prefix)) = v_prefix THEN
            v_out := ltrim(substr(v_out, length(v_prefix) + 1), ' ');
            v_stripped := true;
            EXIT;
        END IF;
    END LOOP;
    IF NOT v_stripped AND position(' ' IN v_out) > 0 THEN
        v_head := split_part(v_out, ' ', 1);
        IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(p_params -> 'articles') AS entry
                    WHERE btrim(public.ldvelh_norm_fold(entry, p_params), ' ') = v_head) THEN
            v_out := substr(v_out, length(v_head) + 2);
        END IF;
    END IF;

    RETURN btrim(regexp_replace(replace(v_out, '''', ''), ' +', ' ', 'g'), ' ');
END $$;

CREATE TABLE public.lang_packs (
    lang text PRIMARY KEY,
    version text NOT NULL,
    params jsonb NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

-- The normalisation of a game's language; raises when the game has no language or its
-- pack is not synchronised. The language is read through to_jsonb so that this function
-- stays valid whatever the order in which games.language is created.
CREATE FUNCTION public.ldvelh_norm_for_game(p_game_id uuid, p_text text) RETURNS text
    LANGUAGE plpgsql STABLE PARALLEL SAFE
    AS $$
DECLARE
    v_lang text;
    v_params jsonb;
BEGIN
    SELECT to_jsonb(gm) ->> 'language' INTO v_lang
      FROM public.games AS gm WHERE gm.id = p_game_id;
    SELECT lp.params INTO v_params FROM public.lang_packs AS lp WHERE lp.lang = v_lang;
    IF v_params IS NULL THEN
        RAISE EXCEPTION 'missing lang pack %', v_lang;
    END IF;
    RETURN public.ldvelh_norm(p_text, v_params);
END $$;

-- migrate:down
-- Section 1 (normalisation) is undone last: the later sections use it.
DROP FUNCTION public.ldvelh_norm_for_game(uuid, text);
DROP TABLE public.lang_packs;
DROP FUNCTION public.ldvelh_norm(text, jsonb);
DROP FUNCTION public.ldvelh_norm_fold(text, jsonb);
DROP FUNCTION public.ldvelh_unaccent(text);
DROP EXTENSION IF EXISTS fuzzystrmatch;
DROP EXTENSION IF EXISTS unaccent;
DROP EXTENSION IF EXISTS pg_trgm;
