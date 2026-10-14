-- legacy game 3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9
-- schema version 20260419000000
--
-- PostgreSQL database dump
--


-- Dumped from database version 16.15 (Debian 16.15-1.pgdg13+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg13+2)


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.users (id, email, password_hash, display_name, created_at, preferences, email_verified, email_verification_token, email_verification_sent_at) VALUES ('e068a087-3a37-405f-bbc5-6853e778c626', 'test@example.com', '$2b$12$N5j1uDagMo8NxRGBN78.aODpJ.BAGWR0CRubsBD0uDc7IjnMqR/Iu', 'Test User', '2026-10-14 13:14:34.723035+00', '{}', false, 'f651bc1084fdca4489f8814de9549847ab573aa4208b382fe13a98f0699d6ba2', '2026-10-14 13:14:34.723035+00');


--
-- Data for Name: genres; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.genres (id, user_id, slug, label, is_preset, tone_style, friction_flavor, atmosphere_guidelines, world_type, location_types, npc_archetypes, arrival_prompt, world_gen_example, forbidden_ai_names, created_at) VALUES ('e5c1a175-a0ee-4187-9ab7-0e8960a36109', NULL, 'sci_fi', 'Science-Fiction', true, 'neutral', 'standard', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-10-14 13:14:34.726235+00');
INSERT INTO public.genres (id, user_id, slug, label, is_preset, tone_style, friction_flavor, atmosphere_guidelines, world_type, location_types, npc_archetypes, arrival_prompt, world_gen_example, forbidden_ai_names, created_at) VALUES ('27544e93-dee4-453f-93e0-885e115df15c', NULL, 'dark_fantasy', 'Dark Fantasy', true, 'neutral', 'standard', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-10-14 13:14:34.72692+00');
INSERT INTO public.genres (id, user_id, slug, label, is_preset, tone_style, friction_flavor, atmosphere_guidelines, world_type, location_types, npc_archetypes, arrival_prompt, world_gen_example, forbidden_ai_names, created_at) VALUES ('613c18f6-19e2-4227-a0d2-b0dd9d46666b', NULL, 'cosmic_horror', 'Horreur Cosmique', true, 'neutral', 'standard', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-10-14 13:14:34.727237+00');
INSERT INTO public.genres (id, user_id, slug, label, is_preset, tone_style, friction_flavor, atmosphere_guidelines, world_type, location_types, npc_archetypes, arrival_prompt, world_gen_example, forbidden_ai_names, created_at) VALUES ('31cca1da-d180-4986-8f84-616cf2b4338c', NULL, 'cyberpunk', 'Cyberpunk', true, 'neutral', 'standard', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-10-14 13:14:34.727447+00');


--
-- Data for Name: games; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.games (id, user_id, name, current_cycle, "current_date", "current_time", current_location_id, world_name, world_description, world_atmosphere, world_seed_words, world_founding_cycle, detail_requests, active, created_at, updated_at, last_extraction_time, engine, engine_locked, world_config, genre_id, game_duration, last_director_time) VALUES ('3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'e068a087-3a37-405f-bbc5-6853e778c626', 'Escale Méridienne', 1, 'Lundi 18 Juillet 2847', '10h15', '518eb35b-b347-4702-b88c-3057685a0a3d', 'Escale Méridienne', 'Ancienne station minière reconvertie. Infrastructure vieillissante, population blasée.', 'Station industrielle usée, indifférence ambiante', '{rouille,reconversion,isolement}', -4500, '{}', true, '2026-10-14 13:14:34.73138+00', '2026-10-14 13:14:35.049543+00', NULL, 'fate_core', true, '{"genre": "sci_fi", "difficulty": "moderate"}', 'e5c1a175-a0ee-4187-9ab7-0e8960a36109', 'medium', '10h15');


--
-- Data for Name: entity_registry; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('e24038ce-ede8-4829-be87-6e3f3e52304d', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'location', 'Escale Méridienne');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('87685f6f-4d8f-40db-b738-addd7793eb12', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'protagonist', 'Valentin');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('ef223522-0828-46eb-b1f1-a2cd3ab6dfab', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'organization', 'Symbiose Tech');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('861081ba-c705-481e-b7dc-ed62eccbe58f', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'location', 'Terminal Quai 7');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('9ff39366-0f46-4da7-a5ea-666f2dac07df', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'location', 'Bloc Tournesol');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('14876267-5d04-4422-9004-76998ded5454', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'location', 'Appartement 4-12');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('19c02dd0-edd9-4899-b583-7c25dfa6d5ff', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'location', 'Serres Hydro-7');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('1a25d84a-0da0-4f43-8fe4-7e8b36c933ee', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'location', 'Le Quart de Cycle');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('f942f7d4-6ca9-46c8-96ed-42b052d6cdf3', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'character', 'Justine Lépicier');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('2cf61d7d-0d5e-405a-ae6a-697d62289c95', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'character', 'Dr. Yuki Tanaka');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('bc1cfcf3-f620-487d-8516-b26e0a992de9', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'character', 'Ossek');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('4a197bdd-09d1-4c9b-a101-55579146bf68', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'object', 'Terminal personnel');
INSERT INTO public.entity_registry (id, game_id, entity_type, name) VALUES ('943470f0-f9f7-4971-9e90-4b0bdd244bc3', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'object', 'Valise cabine');


--
-- Data for Name: narrative_arcs; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.narrative_arcs (id, game_id, title, domain, description, intensity, resolved, resolved_cycle, resolution, created_at, updated_at, owner_id) VALUES ('b2edc754-6fc1-403b-9413-06d5f91d791a', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'La mère malade', 'family', 'Justine envoie la moitié de son salaire pour sa mère malade restée sur Kepler-22. Le coût du transfert médical est astronomique.', 5, false, NULL, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00', NULL);
INSERT INTO public.narrative_arcs (id, game_id, title, domain, description, intensity, resolved, resolved_cycle, resolution, created_at, updated_at, owner_id) VALUES ('968c42f3-f7dc-4710-a3bf-bc41241c8c06', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Burnout silencieux', 'health', 'Dr. Tanaka pousse l''équipe au-delà du raisonnable. 14h par jour depuis des mois. Refuse d''admettre le problème.', 5, false, NULL, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00', NULL);
INSERT INTO public.narrative_arcs (id, game_id, title, domain, description, intensity, resolved, resolved_cycle, resolution, created_at, updated_at, owner_id) VALUES ('fd910887-4188-436d-aa37-ec6552327df6', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Le mal du banc', 'health', 'Mélancolie keth chronique d''Ossek. Seul de son espèce sur la station.', 4, false, NULL, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00', NULL);
INSERT INTO public.narrative_arcs (id, game_id, title, domain, description, intensity, resolved, resolved_cycle, resolution, created_at, updated_at, owner_id) VALUES ('dd8155be-1d64-4de1-9a20-79146757f9d1', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Pression sur Symbiose', 'professional', 'Investisseur externe s''intéresse à Symbiose avec intentions floues.', 4, false, NULL, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00', NULL);


--
-- Data for Name: arc_participants; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.arc_participants (id, arc_id, entity_id, role) VALUES ('337c87cd-1de1-4ff4-8863-1767228140b6', 'b2edc754-6fc1-403b-9413-06d5f91d791a', 'f942f7d4-6ca9-46c8-96ed-42b052d6cdf3', 'involved');
INSERT INTO public.arc_participants (id, arc_id, entity_id, role) VALUES ('df90f0ee-c541-4d02-8830-58ee84a80a12', '968c42f3-f7dc-4710-a3bf-bc41241c8c06', '2cf61d7d-0d5e-405a-ae6a-697d62289c95', 'involved');
INSERT INTO public.arc_participants (id, arc_id, entity_id, role) VALUES ('4d77dd87-f596-4cb7-90e3-d416b3ad7316', '968c42f3-f7dc-4710-a3bf-bc41241c8c06', 'ef223522-0828-46eb-b1f1-a2cd3ab6dfab', 'involved');
INSERT INTO public.arc_participants (id, arc_id, entity_id, role) VALUES ('b3cf7cc3-d7b0-43e8-8d5b-ea9f6c17c948', 'fd910887-4188-436d-aa37-ec6552327df6', 'bc1cfcf3-f620-487d-8516-b26e0a992de9', 'involved');
INSERT INTO public.arc_participants (id, arc_id, entity_id, role) VALUES ('a6816685-2dce-4086-9229-fbe25cd362f0', 'dd8155be-1d64-4de1-9a20-79146757f9d1', 'ef223522-0828-46eb-b1f1-a2cd3ab6dfab', 'involved');
INSERT INTO public.arc_participants (id, arc_id, entity_id, role) VALUES ('a9a91fa9-8a6d-4ff4-9c73-f3b4ec171b0a', 'dd8155be-1d64-4de1-9a20-79146757f9d1', '2cf61d7d-0d5e-405a-ae6a-697d62289c95', 'involved');


--
-- Data for Name: character_d6; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: character_fate; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.character_fate (id, game_id, aspects, stunts, stress_physical, stress_mental, consequences, fate_points, refresh, created_at, updated_at) VALUES ('11f6eea3-871e-49c4-8289-4a7f1d83a65f', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '["Pilote déchu en quête de rédemption", "Je dois de l''argent à tout le monde", "Mon vieux cargo est ma maison"]', '[]', '{f,f,f,f}', '{f,f,f,f}', '{}', 3, 3, '2026-10-14 13:14:34.830507+00', '2026-10-14 13:14:34.830507+00');


--
-- Data for Name: character_narrative; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: locations; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.locations (id, game_id, name, parent_id, location_type, sector, description, atmosphere, accessible, notable_features, typical_crowd, operating_hours, price_range, ambient, details, created_cycle, removed_cycle, created_at, updated_at) VALUES ('0a00eb55-a33d-4aee-9561-781bf9f7ed70', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Escale Méridienne', NULL, 'station', NULL, 'Ancienne station minière reconvertie. Infrastructure vieillissante, population blasée.', 'Station industrielle usée, indifférence ambiante', true, '{"Quai Central","Serres Hautes","Quartier Ouvrier"}', NULL, NULL, NULL, NULL, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00');
INSERT INTO public.locations (id, game_id, name, parent_id, location_type, sector, description, atmosphere, accessible, notable_features, typical_crowd, operating_hours, price_range, ambient, details, created_cycle, removed_cycle, created_at, updated_at) VALUES ('7f2d0d48-605f-4ee2-a843-fa8627492cbd', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Terminal Quai 7', NULL, 'terminal', 'Quai Central', 'Hall bruyant aux plafonds tachés. Files d''attente permanentes.', 'transit impersonnel', true, '{"kiosque à café médiocre","sièges inconfortables"}', 'voyageurs fatigués, dockers indifférents', '24/7', NULL, NULL, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00');
INSERT INTO public.locations (id, game_id, name, parent_id, location_type, sector, description, atmosphere, accessible, notable_features, typical_crowd, operating_hours, price_range, ambient, details, created_cycle, removed_cycle, created_at, updated_at) VALUES ('3e20a17a-c5cb-4049-a0e3-ed56950e73da', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Bloc Tournesol', NULL, 'residential_building', 'Quartier Ouvrier', 'Immeuble de six étages, façade défraîchie. Ascenseur en panne un jour sur trois.', 'vétuste mais vivant', true, '{"hall mal éclairé","boîtes aux lettres cabossées"}', NULL, NULL, NULL, NULL, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00');
INSERT INTO public.locations (id, game_id, name, parent_id, location_type, sector, description, atmosphere, accessible, notable_features, typical_crowd, operating_hours, price_range, ambient, details, created_cycle, removed_cycle, created_at, updated_at) VALUES ('ef1df714-bed0-4e9d-ac7c-8befcae75481', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Serres Hydro-7', NULL, 'workplace', 'Serres Hautes', 'Serre industrielle. Humidité constante, éclairage agressif.', 'humide et bruyante', true, '{"bassins nutritifs","ventilation assourdissante"}', 'techniciens concentrés', '06h-22h', NULL, NULL, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00');
INSERT INTO public.locations (id, game_id, name, parent_id, location_type, sector, description, atmosphere, accessible, notable_features, typical_crowd, operating_hours, price_range, ambient, details, created_cycle, removed_cycle, created_at, updated_at) VALUES ('518eb35b-b347-4702-b88c-3057685a0a3d', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Le Quart de Cycle', NULL, 'cafe', 'Quai Central', 'Café correct, sans plus. Le proprio n''est pas du genre bavard.', 'fonctionnel', true, '{"comptoir usé","chaises dépareillées"}', 'habitués silencieux', '07h-23h', 'budget', NULL, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00');
INSERT INTO public.locations (id, game_id, name, parent_id, location_type, sector, description, atmosphere, accessible, notable_features, typical_crowd, operating_hours, price_range, ambient, details, created_cycle, removed_cycle, created_at, updated_at) VALUES ('e51176d2-aebe-4ba0-9a39-98e3933ae3c1', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Appartement 4-12', '3e20a17a-c5cb-4049-a0e3-ed56950e73da', 'apartment', 'Quartier Ouvrier', '28m², murs fins, vue sur conduit d''aération. Le minimum syndical.', 'exigu et impersonnel', true, '{"kitchenette vétuste","lit qui grince"}', NULL, NULL, NULL, NULL, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00');


--
-- Data for Name: characters; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.characters (id, game_id, name, known_by_protagonist, unknown_name, species, gender, pronouns, age, description, traits, mood, occupation, origin, workplace_id, residence_id, romantic_potential, is_mandatory, ambient, details, created_cycle, removed_cycle, created_at, updated_at) VALUES ('a7a0a5f2-8830-485f-9609-c5fcc1c81d45', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Justine Lépicier', false, NULL, 'human', 'femme', 'elle', '32', '1m54, courbes prononcées, blonde en désordre, yeux bleus cernés', '{pragmatique,"humour caustique",méfiante,épuisée}', 'fatiguée, sur la défensive', 'technicienne maintenance serres', 'Station Kepler-22', 'ef1df714-bed0-4e9d-ac7c-8befcae75481', '3e20a17a-c5cb-4049-a0e3-ed56950e73da', true, true, NULL, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00');
INSERT INTO public.characters (id, game_id, name, known_by_protagonist, unknown_name, species, gender, pronouns, age, description, traits, mood, occupation, origin, workplace_id, residence_id, romantic_potential, is_mandatory, ambient, details, created_cycle, removed_cycle, created_at, updated_at) VALUES ('7c178413-2abc-4841-bc29-59fd2da9924a', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Dr. Yuki Tanaka', false, NULL, 'human', 'femme', 'elle', '45', 'Petite, cheveux gris en chignon serré, posture rigide, regard dur', '{perfectionniste,impatiente,cassante,"méfiante envers les nouveaux"}', 'tendue, irritable', 'directrice technique Symbiose Tech', 'Mars-Cité', 'ef1df714-bed0-4e9d-ac7c-8befcae75481', '3e20a17a-c5cb-4049-a0e3-ed56950e73da', false, false, NULL, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00');
INSERT INTO public.characters (id, game_id, name, known_by_protagonist, unknown_name, species, gender, pronouns, age, description, traits, mood, occupation, origin, workplace_id, residence_id, romantic_potential, is_mandatory, ambient, details, created_cycle, removed_cycle, created_at, updated_at) VALUES ('7b474354-16c0-4f1a-a77a-1cce67c116a5', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Ossek', false, NULL, 'keth (semi-aquatique)', 'non-binaire', 'iel', NULL, 'Peau bleu-gris, branchies latérales, yeux sans pupilles, mouvements lents', '{calme,distant,mélancolique,"peu bavard"}', 'mélancolique, absent', 'propriétaire du café', 'Monde-Océan de Téthys', '518eb35b-b347-4702-b88c-3057685a0a3d', '518eb35b-b347-4702-b88c-3057685a0a3d', false, false, NULL, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00');


--
-- Data for Name: chronology; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.chronology (id, game_id, cycle, "time", location_id, summary, created_at) VALUES ('af411115-ef60-4f41-affe-b4d451b7227c', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 0, '11h42', '7f2d0d48-605f-4ee2-a843-fa8627492cbd', 'Arrivée via navette cargo, 3h de retard. Fatigué, nauséeux, décalé. Systèmes bagages en panne, attente indéterminée.', '2026-10-14 13:14:34.773323+00');


--
-- Data for Name: chronology_participants; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: companions; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.companions (id, game_id, name, voice, traits, quirk, substrate, details, created_at) VALUES ('0d64b450-d457-4736-a766-09707f4a8a39', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Célimène', 'voix rauque, débit lent', '{sarcastique,observatrice,"peu impressionnable"}', 'Note les contradictions des gens sans les commenter... sauf quand c''est drôle', 'personal_device', '{}', '2026-10-14 13:14:34.773323+00');


--
-- Data for Name: conversations; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.conversations (id, game_id, start_cycle, end_cycle, compacted, compacted_at, created_at) VALUES ('0faf4998-450d-4338-b885-8abdc6b686ed', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 1, NULL, false, NULL, '2026-10-14 13:14:34.894524+00');


--
-- Data for Name: director_plans; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.director_plans (id, game_id, cycle, ig_time, tension_level, narrator_guidance, planned_events, long_term_vision, created_at) VALUES ('dfc2cc73-b820-4c96-8ef7-e2a64517897c', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 1, '08h00', 3, 'Rythme calme, laisser le joueur explorer.', '[]', 'Rien de particulier.', '2026-10-14 13:14:34.860414+00');
INSERT INTO public.director_plans (id, game_id, cycle, ig_time, tension_level, narrator_guidance, planned_events, long_term_vision, created_at) VALUES ('c0d1418f-ff1d-4e19-b557-2c557e3977db', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 1, '10h15', 3, 'Rythme calme, laisser le joueur explorer.', '[]', 'Rien de particulier.', '2026-10-14 13:14:34.954248+00');
INSERT INTO public.director_plans (id, game_id, cycle, ig_time, tension_level, narrator_guidance, planned_events, long_term_vision, created_at) VALUES ('a0f371f2-82f0-4cff-b8df-86e27bee1b57', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 1, '10h15', 3, 'Rythme calme, laisser le joueur explorer.', '[]', 'Rien de particulier.', '2026-10-14 13:14:34.990724+00');
INSERT INTO public.director_plans (id, game_id, cycle, ig_time, tension_level, narrator_guidance, planned_events, long_term_vision, created_at) VALUES ('4d7c2dc0-99ba-4f9f-bf84-f65120292060', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 1, '10h15', 3, 'Rythme calme, laisser le joueur explorer.', '[]', 'Rien de particulier.', '2026-10-14 13:14:35.027732+00');
INSERT INTO public.director_plans (id, game_id, cycle, ig_time, tension_level, narrator_guidance, planned_events, long_term_vision, created_at) VALUES ('b2aeed54-1a53-4ddc-9ddd-56d119fb5421', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 1, '10h15', 3, 'Rythme calme, laisser le joueur explorer.', '[]', 'Rien de particulier.', '2026-10-14 13:14:35.068937+00');


--
-- Data for Name: events; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.events (id, game_id, type, title, description, planned_cycle, "time", location_id, completed, cancelled, created_at) VALUES ('647afd76-0d92-4e9a-ad19-52a6f1827085', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'milestone', 'Arrivée sur la station', 'Arrivée via navette cargo, 3h de retard', 1, '11h42', '7f2d0d48-605f-4ee2-a843-fa8627492cbd', true, false, '2026-10-14 13:14:34.773323+00');


--
-- Data for Name: event_participants; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.event_participants (id, event_id, entity_id) VALUES ('cd7a1bcc-f95a-45bd-bcab-81619cd9a32d', '647afd76-0d92-4e9a-ad19-52a6f1827085', '87685f6f-4d8f-40db-b738-addd7793eb12');


--
-- Data for Name: extraction_logs; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.extraction_logs (id, game_id, conversation_id, cycle, type, duration_ms, messages_processed, facts_created, entities_modified, errors, created_at) VALUES ('09935b9c-374f-4aaf-9ecf-3fa2690612cd', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', NULL, 0, NULL, NULL, NULL, 0, 13, NULL, '2026-10-14 13:14:34.773323+00');


--
-- Data for Name: facts; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.facts (id, game_id, cycle, "time", type, description, location_id, importance, semantic_key, created_at) VALUES ('7ed72440-55f7-4e36-805f-39dcde2f1385', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 1, '11h42', 'encounter', 'Arrivée sur la station via navette cargo, 3h de retard', '7f2d0d48-605f-4ee2-a843-fa8627492cbd', 4, 'valentin:arrival:station', '2026-10-14 13:14:34.773323+00');
INSERT INTO public.facts (id, game_id, cycle, "time", type, description, location_id, importance, semantic_key, created_at) VALUES ('af35a818-c412-4775-934f-8bd76c902cab', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 1, NULL, 'atmosphere', 'Premières impressions : Odeur de sueur et de métal recyclé. Annonce PA grésillante. Lumière crue après la pénombre de la navette. File d''attente interminable', '7f2d0d48-605f-4ee2-a843-fa8627492cbd', 2, 'valentin:arrival:sensory', '2026-10-14 13:14:34.773323+00');
INSERT INTO public.facts (id, game_id, cycle, "time", type, description, location_id, importance, semantic_key, created_at) VALUES ('7e5a867f-b3a9-40c6-a9f0-4149b335a3eb', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 1, NULL, 'action', 'Systèmes bagages en panne, attente indéterminée', '7f2d0d48-605f-4ee2-a843-fa8627492cbd', 3, 'valentin:arrival:incident', '2026-10-14 13:14:34.773323+00');
INSERT INTO public.facts (id, game_id, cycle, "time", type, description, location_id, importance, semantic_key, created_at) VALUES ('400ff777-6885-442c-b7fc-ebb6460db4fc', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 1, NULL, 'state_change', 'État à l''arrivée : fatigué, nauséeux, décalé', NULL, 2, 'valentin:arrival:mood', '2026-10-14 13:14:34.773323+00');
INSERT INTO public.facts (id, game_id, cycle, "time", type, description, location_id, importance, semantic_key, created_at) VALUES ('6c566b45-7d18-46f4-b4ef-888cc6649e0d', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 1, NULL, 'observation', 'Besoin immédiat : Trouver l''appartement et dormir', NULL, 2, 'valentin:arrival:need', '2026-10-14 13:14:34.773323+00');


--
-- Data for Name: fact_participants; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.fact_participants (id, fact_id, entity_id, role) VALUES ('62e42f35-cb50-4574-b060-3519580cc89d', '7ed72440-55f7-4e36-805f-39dcde2f1385', '87685f6f-4d8f-40db-b738-addd7793eb12', 'actor');
INSERT INTO public.fact_participants (id, fact_id, entity_id, role) VALUES ('210046f7-a2b7-4daa-9c6f-fb20c5d8706d', '7e5a867f-b3a9-40c6-a9f0-4149b335a3eb', '87685f6f-4d8f-40db-b738-addd7793eb12', 'actor');
INSERT INTO public.fact_participants (id, fact_id, entity_id, role) VALUES ('4d0f0c21-1de2-4419-b2d5-d5bf644f02ea', '400ff777-6885-442c-b7fc-ebb6460db4fc', '87685f6f-4d8f-40db-b738-addd7793eb12', 'actor');
INSERT INTO public.fact_participants (id, fact_id, entity_id, role) VALUES ('8b322dfa-9031-4620-a449-f74fcd600168', '6c566b45-7d18-46f4-b4ef-888cc6649e0d', '87685f6f-4d8f-40db-b738-addd7793eb12', 'actor');


--
-- Data for Name: objects; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.objects (id, game_id, name, category, description, transportable, stackable, base_value, details, created_cycle, removed_cycle, created_at, canonical_name) VALUES ('03141f92-bbc1-4961-9c29-a44bb838c18e', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Terminal personnel', 'tech', 'Modèle standard usé, héberge Célimène', true, false, 300, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', NULL);
INSERT INTO public.objects (id, game_id, name, category, description, transportable, stackable, base_value, details, created_cycle, removed_cycle, created_at, canonical_name) VALUES ('820e0502-521e-47db-9cac-a11089b4938b', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Valise cabine', 'baggage', 'Plastique rayé, fermeture capricieuse', true, false, 40, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', NULL);


--
-- Data for Name: inventory; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.inventory (id, game_id, object_id, owner_id, quantity, acquired_cycle, origin) VALUES ('1f24757d-076c-4fa3-94cb-46c1e1d51aa8', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '03141f92-bbc1-4961-9c29-a44bb838c18e', NULL, 1, 1, 'initial');
INSERT INTO public.inventory (id, game_id, object_id, owner_id, quantity, acquired_cycle, origin) VALUES ('9b0c1209-c8c8-4307-94d9-5c6711482897', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '820e0502-521e-47db-9cac-a11089b4938b', NULL, 1, 1, 'initial');


--
-- Data for Name: messages; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.messages (id, game_id, conversation_id, role, content, cycle, "time", location_id, chronology_id, narrator_deltas, sequence, created_at, game_date, engine_snapshot, narrator_context) VALUES ('d6c1fe4d-512f-41ca-9de2-cebe6a3bf3af', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '0faf4998-450d-4338-b885-8abdc6b686ed', 'user', '__ARRIVEE__', 1, '10h15', '518eb35b-b347-4702-b88c-3057685a0a3d', NULL, NULL, 1, '2026-10-14 13:14:34.896742+00', 'Lundi 18 Juillet 2847', NULL, NULL);
INSERT INTO public.messages (id, game_id, conversation_id, role, content, cycle, "time", location_id, chronology_id, narrator_deltas, sequence, created_at, game_date, engine_snapshot, narrator_context) VALUES ('00962157-e8b9-43cf-8b0d-7ce0ddde7036', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '0faf4998-450d-4338-b885-8abdc6b686ed', 'assistant', 'Le **Quart de Cycle** est à moitié vide à cette heure. Quelques habitués, le nez dans leur terminal. Personne ne lève la tête quand tu entres.

Ossek est au comptoir, occupé à nettoyer la machine à café avec une concentration excessive. Iel ne t''a pas vu, ou fait semblant.', 1, '10h15', '518eb35b-b347-4702-b88c-3057685a0a3d', NULL, '{"cost": {"model": "scripted-model", "cost_usd": 0.0, "provider": "scripted", "input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "entity_reveals": [], "inventory_hints": [], "extraction_triggers": []}', 2, '2026-10-14 13:14:34.898555+00', 'Lundi 18 Juillet 2847', '{"skills": [{"name": "Athlétisme", "label": "Excellent", "level": 4, "custom": false}, {"name": "Empathie", "label": "Bon", "level": 3, "custom": false}, {"name": "Pilotage", "label": "Bon", "level": 3, "custom": false}, {"name": "Combat", "label": "Correct", "level": 2, "custom": false}, {"name": "Discrétion", "label": "Correct", "level": 2, "custom": false}, {"name": "Volonté", "label": "Correct", "level": 2, "custom": false}, {"name": "Contacts", "label": "Moyen", "level": 1, "custom": false}, {"name": "Physique", "label": "Moyen", "level": 1, "custom": false}, {"name": "Ressources", "label": "Moyen", "level": 1, "custom": false}, {"name": "Tromperie", "label": "Moyen", "level": 1, "custom": false}], "stunts": [], "aspects": ["Pilote déchu en quête de rédemption", "Je dois de l''argent à tout le monde", "Mon vieux cargo est ma maison"], "refresh": 3, "fate_points": 3, "consequences": {}, "stress_mental": [false, false, false, false], "stress_physical": [false, false, false, false]}', NULL);
INSERT INTO public.messages (id, game_id, conversation_id, role, content, cycle, "time", location_id, chronology_id, narrator_deltas, sequence, created_at, game_date, engine_snapshot, narrator_context) VALUES ('ac112a56-537c-4cc0-a554-cd5a8fe155fa', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '0faf4998-450d-4338-b885-8abdc6b686ed', 'user', 'Je regarde autour.', 1, '10h15', '518eb35b-b347-4702-b88c-3057685a0a3d', NULL, NULL, 3, '2026-10-14 13:14:34.978917+00', 'Lundi 18 Juillet 2847', NULL, NULL);
INSERT INTO public.messages (id, game_id, conversation_id, role, content, cycle, "time", location_id, chronology_id, narrator_deltas, sequence, created_at, game_date, engine_snapshot, narrator_context) VALUES ('eb3e51cc-2eb2-4cf2-aa8b-03d5c467fdb5', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '0faf4998-450d-4338-b885-8abdc6b686ed', 'assistant', 'Le **Quart de Cycle** est à moitié vide à cette heure. Quelques habitués, le nez dans leur terminal. Personne ne lève la tête quand tu entres.

Ossek est au comptoir, occupé à nettoyer la machine à café avec une concentration excessive. Iel ne t''a pas vu, ou fait semblant.', 1, '10h15', '518eb35b-b347-4702-b88c-3057685a0a3d', NULL, '{"cost": {"model": "scripted-model", "cost_usd": 0.0, "provider": "scripted", "input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "entity_reveals": [], "inventory_hints": [], "extraction_triggers": []}', 4, '2026-10-14 13:14:34.979834+00', 'Lundi 18 Juillet 2847', '{"skills": [{"name": "Athlétisme", "label": "Excellent", "level": 4, "custom": false}, {"name": "Empathie", "label": "Bon", "level": 3, "custom": false}, {"name": "Pilotage", "label": "Bon", "level": 3, "custom": false}, {"name": "Combat", "label": "Correct", "level": 2, "custom": false}, {"name": "Discrétion", "label": "Correct", "level": 2, "custom": false}, {"name": "Volonté", "label": "Correct", "level": 2, "custom": false}, {"name": "Contacts", "label": "Moyen", "level": 1, "custom": false}, {"name": "Physique", "label": "Moyen", "level": 1, "custom": false}, {"name": "Ressources", "label": "Moyen", "level": 1, "custom": false}, {"name": "Tromperie", "label": "Moyen", "level": 1, "custom": false}], "stunts": [], "aspects": ["Pilote déchu en quête de rédemption", "Je dois de l''argent à tout le monde", "Mon vieux cargo est ma maison"], "refresh": 3, "fate_points": 3, "consequences": {}, "stress_mental": [false, false, false, false], "stress_physical": [false, false, false, false]}', NULL);
INSERT INTO public.messages (id, game_id, conversation_id, role, content, cycle, "time", location_id, chronology_id, narrator_deltas, sequence, created_at, game_date, engine_snapshot, narrator_context) VALUES ('f3061910-864e-4a53-a5c1-5b0d7fae08a5', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '0faf4998-450d-4338-b885-8abdc6b686ed', 'user', 'Je parle au barman.', 1, '10h15', '518eb35b-b347-4702-b88c-3057685a0a3d', NULL, NULL, 5, '2026-10-14 13:14:35.015433+00', 'Lundi 18 Juillet 2847', NULL, NULL);
INSERT INTO public.messages (id, game_id, conversation_id, role, content, cycle, "time", location_id, chronology_id, narrator_deltas, sequence, created_at, game_date, engine_snapshot, narrator_context) VALUES ('90639c1a-d388-4922-98f2-2693bdf6ef6f', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '0faf4998-450d-4338-b885-8abdc6b686ed', 'assistant', 'Le **Quart de Cycle** est à moitié vide à cette heure. Quelques habitués, le nez dans leur terminal. Personne ne lève la tête quand tu entres.

Ossek est au comptoir, occupé à nettoyer la machine à café avec une concentration excessive. Iel ne t''a pas vu, ou fait semblant.', 1, '10h15', '518eb35b-b347-4702-b88c-3057685a0a3d', NULL, '{"cost": {"model": "scripted-model", "cost_usd": 0.0, "provider": "scripted", "input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "entity_reveals": [], "inventory_hints": [], "extraction_triggers": []}', 6, '2026-10-14 13:14:35.016265+00', 'Lundi 18 Juillet 2847', '{"skills": [{"name": "Athlétisme", "label": "Excellent", "level": 4, "custom": false}, {"name": "Empathie", "label": "Bon", "level": 3, "custom": false}, {"name": "Pilotage", "label": "Bon", "level": 3, "custom": false}, {"name": "Combat", "label": "Correct", "level": 2, "custom": false}, {"name": "Discrétion", "label": "Correct", "level": 2, "custom": false}, {"name": "Volonté", "label": "Correct", "level": 2, "custom": false}, {"name": "Contacts", "label": "Moyen", "level": 1, "custom": false}, {"name": "Physique", "label": "Moyen", "level": 1, "custom": false}, {"name": "Ressources", "label": "Moyen", "level": 1, "custom": false}, {"name": "Tromperie", "label": "Moyen", "level": 1, "custom": false}], "stunts": [], "aspects": ["Pilote déchu en quête de rédemption", "Je dois de l''argent à tout le monde", "Mon vieux cargo est ma maison"], "refresh": 3, "fate_points": 3, "consequences": {}, "stress_mental": [false, false, false, false], "stress_physical": [false, false, false, false]}', NULL);
INSERT INTO public.messages (id, game_id, conversation_id, role, content, cycle, "time", location_id, chronology_id, narrator_deltas, sequence, created_at, game_date, engine_snapshot, narrator_context) VALUES ('d581518f-5844-4b6f-bcde-14e141f8f89a', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '0faf4998-450d-4338-b885-8abdc6b686ed', 'user', 'Je sors.', 1, '10h15', '518eb35b-b347-4702-b88c-3057685a0a3d', NULL, NULL, 7, '2026-10-14 13:14:35.054599+00', 'Lundi 18 Juillet 2847', NULL, NULL);
INSERT INTO public.messages (id, game_id, conversation_id, role, content, cycle, "time", location_id, chronology_id, narrator_deltas, sequence, created_at, game_date, engine_snapshot, narrator_context) VALUES ('53d17d89-da4a-4a39-80d6-1e1c299c80d8', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '0faf4998-450d-4338-b885-8abdc6b686ed', 'assistant', 'Le **Quart de Cycle** est à moitié vide à cette heure. Quelques habitués, le nez dans leur terminal. Personne ne lève la tête quand tu entres.

Ossek est au comptoir, occupé à nettoyer la machine à café avec une concentration excessive. Iel ne t''a pas vu, ou fait semblant.', 1, '10h15', '518eb35b-b347-4702-b88c-3057685a0a3d', NULL, '{"cost": {"model": "scripted-model", "cost_usd": 0.0, "provider": "scripted", "input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "entity_reveals": [], "inventory_hints": [], "extraction_triggers": []}', 8, '2026-10-14 13:14:35.05527+00', 'Lundi 18 Juillet 2847', '{"skills": [{"name": "Athlétisme", "label": "Excellent", "level": 4, "custom": false}, {"name": "Empathie", "label": "Bon", "level": 3, "custom": false}, {"name": "Pilotage", "label": "Bon", "level": 3, "custom": false}, {"name": "Combat", "label": "Correct", "level": 2, "custom": false}, {"name": "Discrétion", "label": "Correct", "level": 2, "custom": false}, {"name": "Volonté", "label": "Correct", "level": 2, "custom": false}, {"name": "Contacts", "label": "Moyen", "level": 1, "custom": false}, {"name": "Physique", "label": "Moyen", "level": 1, "custom": false}, {"name": "Ressources", "label": "Moyen", "level": 1, "custom": false}, {"name": "Tromperie", "label": "Moyen", "level": 1, "custom": false}], "stunts": [], "aspects": ["Pilote déchu en quête de rédemption", "Je dois de l''argent à tout le monde", "Mon vieux cargo est ma maison"], "refresh": 3, "fate_points": 3, "consequences": {}, "stress_mental": [false, false, false, false], "stress_physical": [false, false, false, false]}', NULL);


--
-- Data for Name: mechanic_rolls; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.mechanic_rolls (id, game_id, message_id, engine, skill_used, roll_details, outcome, complication, cycle, created_at) VALUES ('e42c8b5e-a84f-4218-9305-c7df85ed2e6c', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '53d17d89-da4a-4a39-80d6-1e1c299c80d8', 'fate_core', 'Athlétisme', '{"dice": [1, 1, 1, 1], "total": 4, "shifts": 5, "details": {"reason": "Action risquée.", "difficulty": 1, "skill_name": "Athlétisme", "skill_label": "Correct", "skill_value": 2, "difficulty_label": "Correct"}, "outcome": "success_with_style", "skill_total": 6, "complication": false, "opposition_total": null}', 'success_with_style', false, 1, '2026-10-14 13:14:35.056273+00');


--
-- Data for Name: narrative_seeds; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: npc_d6; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: npc_fate; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: npc_narrative; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: object_d6; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: object_fate; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: object_narrative; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: organizations; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.organizations (id, game_id, name, org_type, domain, size, description, reputation, headquarters_id, founding_cycle, ambient, details, created_cycle, removed_cycle, created_at, updated_at) VALUES ('5e87319d-f1c8-4b08-ba7a-efc81e1c1b55', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Symbiose Tech', 'company', 'IA agricole', 'medium', 'Startup en difficulté. Ambiance tendue, deadlines impossibles.', 'innovants mais désorganisés, turnover élevé', 'ef1df714-bed0-4e9d-ac7c-8befcae75481', -2920, NULL, '{}', 1, NULL, '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00');


--
-- Data for Name: protagonists; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.protagonists (id, game_id, name, energy, morale, health, credits, occupation, employer_id, residence_id, origin, departure_reason, backstory, hobbies, description, details, created_at, updated_at, gender) VALUES ('16a5892d-e432-4b00-ab09-602cfc1a84fb', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Valentin', 4.0, 3.0, 5.0, 1650, 'développeur IA senior', '5e87319d-f1c8-4b08-ba7a-efc81e1c1b55', 'e51176d2-aebe-4ba0-9a39-98e3933ae3c1', 'Cité-Dôme de Vega III', 'fresh_start', 'Huit ans dans une startup qui a implosé. Burnout. Besoin de partir. Développeur compétent mais fatigué. Idéalisme érodé par les déceptions.', '{cuisine,lecture,"course à pied"}', NULL, '{}', '2026-10-14 13:14:34.773323+00', '2026-10-14 13:14:34.773323+00', NULL);


--
-- Data for Name: relations; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.relations (id, game_id, type, source_id, target_id, level, context, known_by_protagonist, start_cycle, end_cycle, end_reason, created_at) VALUES ('87880d42-83b1-4076-a964-936971f9ee0c', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'lives_at', '87685f6f-4d8f-40db-b738-addd7793eb12', '14876267-5d04-4422-9004-76998ded5454', NULL, NULL, true, 1, NULL, NULL, '2026-10-14 13:14:34.773323+00');
INSERT INTO public.relations (id, game_id, type, source_id, target_id, level, context, known_by_protagonist, start_cycle, end_cycle, end_reason, created_at) VALUES ('45e67b9f-0900-4e4f-9b7d-358aa5fca87f', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'employed_by', '87685f6f-4d8f-40db-b738-addd7793eb12', 'ef223522-0828-46eb-b1f1-a2cd3ab6dfab', NULL, NULL, true, 1, NULL, NULL, '2026-10-14 13:14:34.773323+00');
INSERT INTO public.relations (id, game_id, type, source_id, target_id, level, context, known_by_protagonist, start_cycle, end_cycle, end_reason, created_at) VALUES ('8417fecd-f815-4e17-98b5-2f248719d87c', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'works_at', 'f942f7d4-6ca9-46c8-96ed-42b052d6cdf3', '19c02dd0-edd9-4899-b583-7c25dfa6d5ff', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:14:34.773323+00');
INSERT INTO public.relations (id, game_id, type, source_id, target_id, level, context, known_by_protagonist, start_cycle, end_cycle, end_reason, created_at) VALUES ('9886a7cb-1230-45f7-9cca-8586b59811a5', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'lives_at', 'f942f7d4-6ca9-46c8-96ed-42b052d6cdf3', '9ff39366-0f46-4da7-a5ea-666f2dac07df', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:14:34.773323+00');
INSERT INTO public.relations (id, game_id, type, source_id, target_id, level, context, known_by_protagonist, start_cycle, end_cycle, end_reason, created_at) VALUES ('a677a936-b2e5-48c5-9d88-0516f3c25295', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'works_at', '2cf61d7d-0d5e-405a-ae6a-697d62289c95', '19c02dd0-edd9-4899-b583-7c25dfa6d5ff', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:14:34.773323+00');
INSERT INTO public.relations (id, game_id, type, source_id, target_id, level, context, known_by_protagonist, start_cycle, end_cycle, end_reason, created_at) VALUES ('1f8f6fa5-75ae-4d39-99cc-427246fe2787', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'manages', '2cf61d7d-0d5e-405a-ae6a-697d62289c95', 'ef223522-0828-46eb-b1f1-a2cd3ab6dfab', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:14:34.773323+00');
INSERT INTO public.relations (id, game_id, type, source_id, target_id, level, context, known_by_protagonist, start_cycle, end_cycle, end_reason, created_at) VALUES ('2d7c0af5-d273-45a6-a5ef-3db93a77f97c', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'owns', 'bc1cfcf3-f620-487d-8516-b26e0a992de9', '1a25d84a-0da0-4f43-8fe4-7e8b36c933ee', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:14:34.773323+00');
INSERT INTO public.relations (id, game_id, type, source_id, target_id, level, context, known_by_protagonist, start_cycle, end_cycle, end_reason, created_at) VALUES ('651a8d4c-9cd4-4864-a100-26751a3ed689', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'located_in', '14876267-5d04-4422-9004-76998ded5454', '9ff39366-0f46-4da7-a5ea-666f2dac07df', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:14:34.773323+00');
INSERT INTO public.relations (id, game_id, type, source_id, target_id, level, context, known_by_protagonist, start_cycle, end_cycle, end_reason, created_at) VALUES ('6e805ca0-363c-4bfd-80ca-683a59c4a44b', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'located_in', 'ef223522-0828-46eb-b1f1-a2cd3ab6dfab', '19c02dd0-edd9-4899-b583-7c25dfa6d5ff', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:14:34.773323+00');


--
-- Data for Name: skills; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.skills (id, game_id, protagonist_id, character_id, name, level, start_cycle, end_cycle, created_at) VALUES ('61861071-7b97-4c5d-a53c-fcf1b93cf3ff', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '16a5892d-e432-4b00-ab09-602cfc1a84fb', NULL, 'architecture_systemes', 4, 1, NULL, '2026-10-14 13:14:34.773323+00');
INSERT INTO public.skills (id, game_id, protagonist_id, character_id, name, level, start_cycle, end_cycle, created_at) VALUES ('1558f8b2-4c10-45af-84f4-1c5a7015b154', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', '16a5892d-e432-4b00-ab09-602cfc1a84fb', NULL, 'programmation_ia', 4, 1, NULL, '2026-10-14 13:14:34.773323+00');


--
-- Data for Name: skills_d6; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: skills_fate; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.skills_fate (id, game_id, name, level, custom) VALUES ('db4ef83b-6e9a-4648-aa58-c8c4e750c90c', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Athlétisme', 4, false);
INSERT INTO public.skills_fate (id, game_id, name, level, custom) VALUES ('7999e9fe-3a92-4619-9d90-b4aa24a4d7b0', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Pilotage', 3, false);
INSERT INTO public.skills_fate (id, game_id, name, level, custom) VALUES ('b74ff743-8257-4754-8c6d-85def2c3bfe5', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Empathie', 3, false);
INSERT INTO public.skills_fate (id, game_id, name, level, custom) VALUES ('07ab77cd-2db9-40a2-99bb-17f6d97cc70f', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Combat', 2, false);
INSERT INTO public.skills_fate (id, game_id, name, level, custom) VALUES ('0cea4e26-f5da-4d5f-bbe0-c123124f4525', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Discrétion', 2, false);
INSERT INTO public.skills_fate (id, game_id, name, level, custom) VALUES ('f8306d71-54e4-4a0e-be2d-a65cfc2d6ac2', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Volonté', 2, false);
INSERT INTO public.skills_fate (id, game_id, name, level, custom) VALUES ('5855d187-93ed-4769-8e1a-59f8bd2135bf', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Contacts', 1, false);
INSERT INTO public.skills_fate (id, game_id, name, level, custom) VALUES ('3809cddc-27b6-4486-9aad-c9b350bab7c1', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Ressources', 1, false);
INSERT INTO public.skills_fate (id, game_id, name, level, custom) VALUES ('f7e7c45b-5484-4c1f-a9e9-fc1ab816aa0f', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Physique', 1, false);
INSERT INTO public.skills_fate (id, game_id, name, level, custom) VALUES ('ea705bf7-8b4a-47f9-ae54-5c91a438abbe', '3ae11cca-36ef-46cc-8544-9e5cbcaf1aa9', 'Tromperie', 1, false);


--
-- Data for Name: traits_narrative; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- PostgreSQL database dump complete
--


