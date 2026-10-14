-- legacy game 528d441c-8e2e-4fd7-9ccc-04585e211356
--
-- PostgreSQL database dump
--


-- Dumped from database version 16.15 (Debian 16.15-1.pgdg13+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg13+2)


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.users VALUES ('42cbb73b-fd58-440f-9540-929b09605277', 'test@example.com', '$2b$12$wqM8Olp8Gb97eS28.ffvB.ln3gibTN94D3pWs7ZDFW.SOYJmfOdsW', 'Test User', '2026-10-14 13:05:52.580593+00', '{}', false, '1ab1923967a6b88b6380d8e427f6ada230d5e2ce1a5b39ac781ba8cd4dc51196', '2026-10-14 13:05:52.580593+00');


--
-- Data for Name: genres; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.genres VALUES ('e4b048e7-3e48-4a91-8a54-528b463384f5', NULL, 'sci_fi', 'Science-Fiction', true, 'neutral', 'standard', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-10-14 13:05:52.590555+00');
INSERT INTO public.genres VALUES ('ff9f510f-f93e-430e-b953-57db2c591d6b', NULL, 'dark_fantasy', 'Dark Fantasy', true, 'neutral', 'standard', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-10-14 13:05:52.5939+00');
INSERT INTO public.genres VALUES ('730ec9c2-64cd-4b68-a2ea-e42bc6373b6c', NULL, 'cosmic_horror', 'Horreur Cosmique', true, 'neutral', 'standard', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-10-14 13:05:52.594871+00');
INSERT INTO public.genres VALUES ('045d4dfb-a019-4c8e-b994-20eec5b5baca', NULL, 'cyberpunk', 'Cyberpunk', true, 'neutral', 'standard', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-10-14 13:05:52.595514+00');


--
-- Data for Name: games; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.games VALUES ('528d441c-8e2e-4fd7-9ccc-04585e211356', '42cbb73b-fd58-440f-9540-929b09605277', 'Escale Méridienne', 1, 'Lundi 18 Juillet 2847', '10h15', '1587f86c-80ba-4594-9df3-5091253891b2', 'Escale Méridienne', 'Ancienne station minière reconvertie. Infrastructure vieillissante, population blasée.', 'Station industrielle usée, indifférence ambiante', '{rouille,reconversion,isolement}', -4500, '{}', true, '2026-10-14 13:05:52.613302+00', '2026-10-14 13:05:53.349223+00', NULL, 'fate_core', true, '{"genre": "sci_fi", "difficulty": "moderate"}', 'e4b048e7-3e48-4a91-8a54-528b463384f5', 'medium', '10h15');


--
-- Data for Name: entity_registry; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.entity_registry VALUES ('a1b84a1e-8d14-4bf5-b004-2495a8cd1572', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'location', 'Escale Méridienne');
INSERT INTO public.entity_registry VALUES ('e0631e55-664c-4a25-81ac-c7c1a6787c84', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'protagonist', 'Valentin');
INSERT INTO public.entity_registry VALUES ('88f76d44-65a9-4b82-9348-f7610cddd0c9', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'organization', 'Symbiose Tech');
INSERT INTO public.entity_registry VALUES ('185b77fc-2e56-4d30-b1be-3a32a2c40017', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'location', 'Terminal Quai 7');
INSERT INTO public.entity_registry VALUES ('40239d4d-04f7-4138-8d8d-53a6eee4d2d8', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'location', 'Bloc Tournesol');
INSERT INTO public.entity_registry VALUES ('931af6ef-c838-475a-b827-2c3b3e034d99', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'location', 'Appartement 4-12');
INSERT INTO public.entity_registry VALUES ('73fe0655-22cf-4a0a-9a93-d5c1cf73e8c8', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'location', 'Serres Hydro-7');
INSERT INTO public.entity_registry VALUES ('6d72136f-46e5-408a-9522-33c2971c14c8', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'location', 'Le Quart de Cycle');
INSERT INTO public.entity_registry VALUES ('52d8418e-5125-4e0e-8afc-967057301a66', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'character', 'Justine Lépicier');
INSERT INTO public.entity_registry VALUES ('682ac81d-ab9b-40a1-a3eb-94ace936dd42', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'character', 'Dr. Yuki Tanaka');
INSERT INTO public.entity_registry VALUES ('211a506b-ba40-484c-9080-93162a01a988', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'character', 'Ossek');
INSERT INTO public.entity_registry VALUES ('a20987de-a679-42f1-9b35-15c8dc5cd62a', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'object', 'Terminal personnel');
INSERT INTO public.entity_registry VALUES ('951542e3-bcf0-4f8f-854f-44eea457e7fa', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'object', 'Valise cabine');


--
-- Data for Name: narrative_arcs; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.narrative_arcs VALUES ('b00861e1-94c0-422d-9fa0-de2453df1fcc', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'La mère malade', 'family', 'Justine envoie la moitié de son salaire pour sa mère malade restée sur Kepler-22. Le coût du transfert médical est astronomique.', 5, false, NULL, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00', NULL);
INSERT INTO public.narrative_arcs VALUES ('fab0528d-bb66-47c6-a614-6bdd717b1f43', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Burnout silencieux', 'health', 'Dr. Tanaka pousse l''équipe au-delà du raisonnable. 14h par jour depuis des mois. Refuse d''admettre le problème.', 5, false, NULL, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00', NULL);
INSERT INTO public.narrative_arcs VALUES ('9132dc0f-1c1b-4ae0-aaeb-de31fbe292c0', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Le mal du banc', 'health', 'Mélancolie keth chronique d''Ossek. Seul de son espèce sur la station.', 4, false, NULL, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00', NULL);
INSERT INTO public.narrative_arcs VALUES ('5d04b9d3-6a65-4993-8f04-4779ef5bba4e', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Pression sur Symbiose', 'professional', 'Investisseur externe s''intéresse à Symbiose avec intentions floues.', 4, false, NULL, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00', NULL);


--
-- Data for Name: arc_participants; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.arc_participants VALUES ('d42cf768-026b-4ca1-b231-2677e708f07a', 'b00861e1-94c0-422d-9fa0-de2453df1fcc', '52d8418e-5125-4e0e-8afc-967057301a66', 'involved');
INSERT INTO public.arc_participants VALUES ('bc6f8261-f347-4d95-bf14-699a4a8bf319', 'fab0528d-bb66-47c6-a614-6bdd717b1f43', '682ac81d-ab9b-40a1-a3eb-94ace936dd42', 'involved');
INSERT INTO public.arc_participants VALUES ('3b1ffd18-d5cd-4f71-9f29-823e42eecfdb', 'fab0528d-bb66-47c6-a614-6bdd717b1f43', '88f76d44-65a9-4b82-9348-f7610cddd0c9', 'involved');
INSERT INTO public.arc_participants VALUES ('41b7ab3c-cf42-4685-a203-212cdff89a3f', '9132dc0f-1c1b-4ae0-aaeb-de31fbe292c0', '211a506b-ba40-484c-9080-93162a01a988', 'involved');
INSERT INTO public.arc_participants VALUES ('5646e1da-3cad-4b9f-adc9-d2b3e04fc161', '5d04b9d3-6a65-4993-8f04-4779ef5bba4e', '88f76d44-65a9-4b82-9348-f7610cddd0c9', 'involved');
INSERT INTO public.arc_participants VALUES ('03a233b6-7d5c-4cfc-82c4-5aa7fa2f9136', '5d04b9d3-6a65-4993-8f04-4779ef5bba4e', '682ac81d-ab9b-40a1-a3eb-94ace936dd42', 'involved');


--
-- Data for Name: character_d6; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: character_fate; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.character_fate VALUES ('0584909c-88e3-4c1d-96f1-f8d2dde41ca4', '528d441c-8e2e-4fd7-9ccc-04585e211356', '["Pilote déchu en quête de rédemption", "Je dois de l''argent à tout le monde", "Mon vieux cargo est ma maison"]', '[]', '{f,f,f,f}', '{f,f,f,f}', '{}', 3, 3, '2026-10-14 13:05:52.866022+00', '2026-10-14 13:05:52.866022+00');


--
-- Data for Name: character_narrative; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: locations; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.locations VALUES ('d7f2b00c-74bd-4d86-9a6b-7b72c5b89534', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Escale Méridienne', NULL, 'station', NULL, 'Ancienne station minière reconvertie. Infrastructure vieillissante, population blasée.', 'Station industrielle usée, indifférence ambiante', true, '{"Quai Central","Serres Hautes","Quartier Ouvrier"}', NULL, NULL, NULL, NULL, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00');
INSERT INTO public.locations VALUES ('07e83172-2f30-4f8f-9506-2b6d4cde470d', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Terminal Quai 7', NULL, 'terminal', 'Quai Central', 'Hall bruyant aux plafonds tachés. Files d''attente permanentes.', 'transit impersonnel', true, '{"kiosque à café médiocre","sièges inconfortables"}', 'voyageurs fatigués, dockers indifférents', '24/7', NULL, NULL, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00');
INSERT INTO public.locations VALUES ('9ded8222-eb18-4513-8425-111ba698c0f8', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Bloc Tournesol', NULL, 'residential_building', 'Quartier Ouvrier', 'Immeuble de six étages, façade défraîchie. Ascenseur en panne un jour sur trois.', 'vétuste mais vivant', true, '{"hall mal éclairé","boîtes aux lettres cabossées"}', NULL, NULL, NULL, NULL, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00');
INSERT INTO public.locations VALUES ('62ec0e83-c23d-42b7-b579-278eaa5f5386', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Serres Hydro-7', NULL, 'workplace', 'Serres Hautes', 'Serre industrielle. Humidité constante, éclairage agressif.', 'humide et bruyante', true, '{"bassins nutritifs","ventilation assourdissante"}', 'techniciens concentrés', '06h-22h', NULL, NULL, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00');
INSERT INTO public.locations VALUES ('1587f86c-80ba-4594-9df3-5091253891b2', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Le Quart de Cycle', NULL, 'cafe', 'Quai Central', 'Café correct, sans plus. Le proprio n''est pas du genre bavard.', 'fonctionnel', true, '{"comptoir usé","chaises dépareillées"}', 'habitués silencieux', '07h-23h', 'budget', NULL, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00');
INSERT INTO public.locations VALUES ('2bf53139-52bf-466b-9044-562d1a3bbe32', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Appartement 4-12', '9ded8222-eb18-4513-8425-111ba698c0f8', 'apartment', 'Quartier Ouvrier', '28m², murs fins, vue sur conduit d''aération. Le minimum syndical.', 'exigu et impersonnel', true, '{"kitchenette vétuste","lit qui grince"}', NULL, NULL, NULL, NULL, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00');


--
-- Data for Name: characters; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.characters VALUES ('ae924163-d7eb-463f-a7ac-3ebe18f40da9', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Justine Lépicier', false, NULL, 'human', 'femme', 'elle', '32', '1m54, courbes prononcées, blonde en désordre, yeux bleus cernés', '{pragmatique,"humour caustique",méfiante,épuisée}', 'fatiguée, sur la défensive', 'technicienne maintenance serres', 'Station Kepler-22', '62ec0e83-c23d-42b7-b579-278eaa5f5386', '9ded8222-eb18-4513-8425-111ba698c0f8', true, true, NULL, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00');
INSERT INTO public.characters VALUES ('24a884ba-49a7-4b18-8c16-00b948c26e99', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Dr. Yuki Tanaka', false, NULL, 'human', 'femme', 'elle', '45', 'Petite, cheveux gris en chignon serré, posture rigide, regard dur', '{perfectionniste,impatiente,cassante,"méfiante envers les nouveaux"}', 'tendue, irritable', 'directrice technique Symbiose Tech', 'Mars-Cité', '62ec0e83-c23d-42b7-b579-278eaa5f5386', '9ded8222-eb18-4513-8425-111ba698c0f8', false, false, NULL, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00');
INSERT INTO public.characters VALUES ('a3b21b54-c084-450f-8ca8-106e941a7d7a', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Ossek', false, NULL, 'keth (semi-aquatique)', 'non-binaire', 'iel', NULL, 'Peau bleu-gris, branchies latérales, yeux sans pupilles, mouvements lents', '{calme,distant,mélancolique,"peu bavard"}', 'mélancolique, absent', 'propriétaire du café', 'Monde-Océan de Téthys', '1587f86c-80ba-4594-9df3-5091253891b2', '1587f86c-80ba-4594-9df3-5091253891b2', false, false, NULL, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00');


--
-- Data for Name: chronology; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.chronology VALUES ('0a96e361-5c76-447b-979a-8e0fda82c475', '528d441c-8e2e-4fd7-9ccc-04585e211356', 0, '11h42', '07e83172-2f30-4f8f-9506-2b6d4cde470d', 'Arrivée via navette cargo, 3h de retard. Fatigué, nauséeux, décalé. Systèmes bagages en panne, attente indéterminée.', '2026-10-14 13:05:52.694102+00');


--
-- Data for Name: chronology_participants; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: companions; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.companions VALUES ('75a3fb0f-2703-4364-a404-899c3154c9b9', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Célimène', 'voix rauque, débit lent', '{sarcastique,observatrice,"peu impressionnable"}', 'Note les contradictions des gens sans les commenter... sauf quand c''est drôle', 'personal_device', '{}', '2026-10-14 13:05:52.694102+00');


--
-- Data for Name: conversations; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.conversations VALUES ('5a1ee8ef-a7d3-4e27-a6e3-f2e2662af956', '528d441c-8e2e-4fd7-9ccc-04585e211356', 1, NULL, false, NULL, '2026-10-14 13:05:53.027798+00');


--
-- Data for Name: director_plans; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.director_plans VALUES ('ad07cbdc-ec40-42ee-97ff-bfe9ee95b73a', '528d441c-8e2e-4fd7-9ccc-04585e211356', 1, '08h00', 3, 'Rythme calme, laisser le joueur explorer.', '[]', 'Rien de particulier.', '2026-10-14 13:05:52.943741+00');
INSERT INTO public.director_plans VALUES ('1f63ad10-9e2c-4791-be0a-0aa11a1265b1', '528d441c-8e2e-4fd7-9ccc-04585e211356', 1, '10h15', 3, 'Rythme calme, laisser le joueur explorer.', '[]', 'Rien de particulier.', '2026-10-14 13:05:53.114527+00');
INSERT INTO public.director_plans VALUES ('3213f27e-9c74-48b9-a76e-9da52db7f909', '528d441c-8e2e-4fd7-9ccc-04585e211356', 1, '10h15', 3, 'Rythme calme, laisser le joueur explorer.', '[]', 'Rien de particulier.', '2026-10-14 13:05:53.196772+00');
INSERT INTO public.director_plans VALUES ('ac8a4017-855b-4a6d-9627-f423cd1d2b30', '528d441c-8e2e-4fd7-9ccc-04585e211356', 1, '10h15', 3, 'Rythme calme, laisser le joueur explorer.', '[]', 'Rien de particulier.', '2026-10-14 13:05:53.287537+00');
INSERT INTO public.director_plans VALUES ('93ad6647-c030-4a8e-9007-135b63fd9029', '528d441c-8e2e-4fd7-9ccc-04585e211356', 1, '10h15', 3, 'Rythme calme, laisser le joueur explorer.', '[]', 'Rien de particulier.', '2026-10-14 13:05:53.408631+00');


--
-- Data for Name: events; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.events VALUES ('9dee5b27-858f-4d93-8b60-87bef1adafa1', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'milestone', 'Arrivée sur la station', 'Arrivée via navette cargo, 3h de retard', 1, '11h42', '07e83172-2f30-4f8f-9506-2b6d4cde470d', true, false, '2026-10-14 13:05:52.694102+00');


--
-- Data for Name: event_participants; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.event_participants VALUES ('8443ccc7-4f8b-40a0-bf42-3ec61057cdf4', '9dee5b27-858f-4d93-8b60-87bef1adafa1', 'e0631e55-664c-4a25-81ac-c7c1a6787c84');


--
-- Data for Name: extraction_logs; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.extraction_logs VALUES ('999a98d8-277b-4f25-9280-f682b7c37b93', '528d441c-8e2e-4fd7-9ccc-04585e211356', NULL, 0, NULL, NULL, NULL, 0, 13, NULL, '2026-10-14 13:05:52.694102+00');


--
-- Data for Name: facts; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.facts VALUES ('bbfcc6f6-1256-4510-a26f-04446b4b1534', '528d441c-8e2e-4fd7-9ccc-04585e211356', 1, '11h42', 'encounter', 'Arrivée sur la station via navette cargo, 3h de retard', '07e83172-2f30-4f8f-9506-2b6d4cde470d', 4, 'valentin:arrival:station', '2026-10-14 13:05:52.694102+00');
INSERT INTO public.facts VALUES ('e19c7b41-766b-4cf2-9985-446e943d7e88', '528d441c-8e2e-4fd7-9ccc-04585e211356', 1, NULL, 'atmosphere', 'Premières impressions : Odeur de sueur et de métal recyclé. Annonce PA grésillante. Lumière crue après la pénombre de la navette. File d''attente interminable', '07e83172-2f30-4f8f-9506-2b6d4cde470d', 2, 'valentin:arrival:sensory', '2026-10-14 13:05:52.694102+00');
INSERT INTO public.facts VALUES ('559f24b2-3d7d-45c3-a7d7-86bf28f58baa', '528d441c-8e2e-4fd7-9ccc-04585e211356', 1, NULL, 'action', 'Systèmes bagages en panne, attente indéterminée', '07e83172-2f30-4f8f-9506-2b6d4cde470d', 3, 'valentin:arrival:incident', '2026-10-14 13:05:52.694102+00');
INSERT INTO public.facts VALUES ('e26098a3-960d-4da9-a7f8-5bc688c2a437', '528d441c-8e2e-4fd7-9ccc-04585e211356', 1, NULL, 'state_change', 'État à l''arrivée : fatigué, nauséeux, décalé', NULL, 2, 'valentin:arrival:mood', '2026-10-14 13:05:52.694102+00');
INSERT INTO public.facts VALUES ('5407e06f-b723-4fca-8495-e3aaf63d2fda', '528d441c-8e2e-4fd7-9ccc-04585e211356', 1, NULL, 'observation', 'Besoin immédiat : Trouver l''appartement et dormir', NULL, 2, 'valentin:arrival:need', '2026-10-14 13:05:52.694102+00');


--
-- Data for Name: fact_participants; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.fact_participants VALUES ('9c07bd61-7bca-48b4-aff0-0425311432f8', 'bbfcc6f6-1256-4510-a26f-04446b4b1534', 'e0631e55-664c-4a25-81ac-c7c1a6787c84', 'actor');
INSERT INTO public.fact_participants VALUES ('35abfd50-b4cd-4b61-90b5-61ee1a39d496', '559f24b2-3d7d-45c3-a7d7-86bf28f58baa', 'e0631e55-664c-4a25-81ac-c7c1a6787c84', 'actor');
INSERT INTO public.fact_participants VALUES ('0d933da6-be3c-4e91-ab2c-4969661f9930', 'e26098a3-960d-4da9-a7f8-5bc688c2a437', 'e0631e55-664c-4a25-81ac-c7c1a6787c84', 'actor');
INSERT INTO public.fact_participants VALUES ('3b84d047-5053-4f60-a12a-9dbc0ec43c6a', '5407e06f-b723-4fca-8495-e3aaf63d2fda', 'e0631e55-664c-4a25-81ac-c7c1a6787c84', 'actor');


--
-- Data for Name: objects; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.objects VALUES ('ce221868-8c1e-42ab-a9bc-5a85a30000dc', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Terminal personnel', 'tech', 'Modèle standard usé, héberge Célimène', true, false, 300, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', NULL);
INSERT INTO public.objects VALUES ('3856f729-543d-45ff-81c5-b9cd1066a90a', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Valise cabine', 'baggage', 'Plastique rayé, fermeture capricieuse', true, false, 40, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', NULL);


--
-- Data for Name: inventory; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.inventory VALUES ('f3490736-a188-4f0f-9546-97bb86566d9a', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'ce221868-8c1e-42ab-a9bc-5a85a30000dc', NULL, 1, 1, 'initial');
INSERT INTO public.inventory VALUES ('f2dc7597-f6c6-4548-a61d-dff01294abbb', '528d441c-8e2e-4fd7-9ccc-04585e211356', '3856f729-543d-45ff-81c5-b9cd1066a90a', NULL, 1, 1, 'initial');


--
-- Data for Name: messages; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.messages VALUES ('41d6773b-6dee-44a9-b5ee-7220b6ecfce5', '528d441c-8e2e-4fd7-9ccc-04585e211356', '5a1ee8ef-a7d3-4e27-a6e3-f2e2662af956', 'user', '__ARRIVEE__', 1, '10h15', '1587f86c-80ba-4594-9df3-5091253891b2', NULL, NULL, 1, '2026-10-14 13:05:53.031153+00', 'Lundi 18 Juillet 2847', NULL, NULL);
INSERT INTO public.messages VALUES ('06291a73-9c8b-46a4-b847-e25bb7328d51', '528d441c-8e2e-4fd7-9ccc-04585e211356', '5a1ee8ef-a7d3-4e27-a6e3-f2e2662af956', 'assistant', 'Le **Quart de Cycle** est à moitié vide à cette heure. Quelques habitués, le nez dans leur terminal. Personne ne lève la tête quand tu entres.

Ossek est au comptoir, occupé à nettoyer la machine à café avec une concentration excessive. Iel ne t''a pas vu, ou fait semblant.', 1, '10h15', '1587f86c-80ba-4594-9df3-5091253891b2', NULL, '{"cost": {"model": "scripted-model", "cost_usd": 0.0, "provider": "scripted", "input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "entity_reveals": [], "inventory_hints": [], "extraction_triggers": []}', 2, '2026-10-14 13:05:53.037986+00', 'Lundi 18 Juillet 2847', '{"skills": [{"name": "Athlétisme", "label": "Excellent", "level": 4, "custom": false}, {"name": "Empathie", "label": "Bon", "level": 3, "custom": false}, {"name": "Pilotage", "label": "Bon", "level": 3, "custom": false}, {"name": "Combat", "label": "Correct", "level": 2, "custom": false}, {"name": "Discrétion", "label": "Correct", "level": 2, "custom": false}, {"name": "Volonté", "label": "Correct", "level": 2, "custom": false}, {"name": "Contacts", "label": "Moyen", "level": 1, "custom": false}, {"name": "Physique", "label": "Moyen", "level": 1, "custom": false}, {"name": "Ressources", "label": "Moyen", "level": 1, "custom": false}, {"name": "Tromperie", "label": "Moyen", "level": 1, "custom": false}], "stunts": [], "aspects": ["Pilote déchu en quête de rédemption", "Je dois de l''argent à tout le monde", "Mon vieux cargo est ma maison"], "refresh": 3, "fate_points": 3, "consequences": {}, "stress_mental": [false, false, false, false], "stress_physical": [false, false, false, false]}', NULL);
INSERT INTO public.messages VALUES ('371a3927-3be3-44d3-81ef-e43555eea938', '528d441c-8e2e-4fd7-9ccc-04585e211356', '5a1ee8ef-a7d3-4e27-a6e3-f2e2662af956', 'user', 'Je regarde autour.', 1, '10h15', '1587f86c-80ba-4594-9df3-5091253891b2', NULL, NULL, 3, '2026-10-14 13:05:53.173083+00', 'Lundi 18 Juillet 2847', NULL, NULL);
INSERT INTO public.messages VALUES ('ec62ede1-52ea-4d53-b1e4-40410d36fd14', '528d441c-8e2e-4fd7-9ccc-04585e211356', '5a1ee8ef-a7d3-4e27-a6e3-f2e2662af956', 'assistant', 'Le **Quart de Cycle** est à moitié vide à cette heure. Quelques habitués, le nez dans leur terminal. Personne ne lève la tête quand tu entres.

Ossek est au comptoir, occupé à nettoyer la machine à café avec une concentration excessive. Iel ne t''a pas vu, ou fait semblant.', 1, '10h15', '1587f86c-80ba-4594-9df3-5091253891b2', NULL, '{"cost": {"model": "scripted-model", "cost_usd": 0.0, "provider": "scripted", "input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "entity_reveals": [], "inventory_hints": [], "extraction_triggers": []}', 4, '2026-10-14 13:05:53.174901+00', 'Lundi 18 Juillet 2847', '{"skills": [{"name": "Athlétisme", "label": "Excellent", "level": 4, "custom": false}, {"name": "Empathie", "label": "Bon", "level": 3, "custom": false}, {"name": "Pilotage", "label": "Bon", "level": 3, "custom": false}, {"name": "Combat", "label": "Correct", "level": 2, "custom": false}, {"name": "Discrétion", "label": "Correct", "level": 2, "custom": false}, {"name": "Volonté", "label": "Correct", "level": 2, "custom": false}, {"name": "Contacts", "label": "Moyen", "level": 1, "custom": false}, {"name": "Physique", "label": "Moyen", "level": 1, "custom": false}, {"name": "Ressources", "label": "Moyen", "level": 1, "custom": false}, {"name": "Tromperie", "label": "Moyen", "level": 1, "custom": false}], "stunts": [], "aspects": ["Pilote déchu en quête de rédemption", "Je dois de l''argent à tout le monde", "Mon vieux cargo est ma maison"], "refresh": 3, "fate_points": 3, "consequences": {}, "stress_mental": [false, false, false, false], "stress_physical": [false, false, false, false]}', NULL);
INSERT INTO public.messages VALUES ('0fe4d49b-a654-4f0d-a922-37eba16b8a47', '528d441c-8e2e-4fd7-9ccc-04585e211356', '5a1ee8ef-a7d3-4e27-a6e3-f2e2662af956', 'user', 'Je parle au barman.', 1, '10h15', '1587f86c-80ba-4594-9df3-5091253891b2', NULL, NULL, 5, '2026-10-14 13:05:53.255257+00', 'Lundi 18 Juillet 2847', NULL, NULL);
INSERT INTO public.messages VALUES ('b2055266-2608-446e-8d03-f08e12aa0c04', '528d441c-8e2e-4fd7-9ccc-04585e211356', '5a1ee8ef-a7d3-4e27-a6e3-f2e2662af956', 'assistant', 'Le **Quart de Cycle** est à moitié vide à cette heure. Quelques habitués, le nez dans leur terminal. Personne ne lève la tête quand tu entres.

Ossek est au comptoir, occupé à nettoyer la machine à café avec une concentration excessive. Iel ne t''a pas vu, ou fait semblant.', 1, '10h15', '1587f86c-80ba-4594-9df3-5091253891b2', NULL, '{"cost": {"model": "scripted-model", "cost_usd": 0.0, "provider": "scripted", "input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "entity_reveals": [], "inventory_hints": [], "extraction_triggers": []}', 6, '2026-10-14 13:05:53.256924+00', 'Lundi 18 Juillet 2847', '{"skills": [{"name": "Athlétisme", "label": "Excellent", "level": 4, "custom": false}, {"name": "Empathie", "label": "Bon", "level": 3, "custom": false}, {"name": "Pilotage", "label": "Bon", "level": 3, "custom": false}, {"name": "Combat", "label": "Correct", "level": 2, "custom": false}, {"name": "Discrétion", "label": "Correct", "level": 2, "custom": false}, {"name": "Volonté", "label": "Correct", "level": 2, "custom": false}, {"name": "Contacts", "label": "Moyen", "level": 1, "custom": false}, {"name": "Physique", "label": "Moyen", "level": 1, "custom": false}, {"name": "Ressources", "label": "Moyen", "level": 1, "custom": false}, {"name": "Tromperie", "label": "Moyen", "level": 1, "custom": false}], "stunts": [], "aspects": ["Pilote déchu en quête de rédemption", "Je dois de l''argent à tout le monde", "Mon vieux cargo est ma maison"], "refresh": 3, "fate_points": 3, "consequences": {}, "stress_mental": [false, false, false, false], "stress_physical": [false, false, false, false]}', NULL);
INSERT INTO public.messages VALUES ('59128a51-3c90-4253-a337-83254172a32d', '528d441c-8e2e-4fd7-9ccc-04585e211356', '5a1ee8ef-a7d3-4e27-a6e3-f2e2662af956', 'user', 'Je sors.', 1, '10h15', '1587f86c-80ba-4594-9df3-5091253891b2', NULL, NULL, 7, '2026-10-14 13:05:53.369864+00', 'Lundi 18 Juillet 2847', NULL, NULL);
INSERT INTO public.messages VALUES ('62cc9796-2ac9-4cf0-9d17-c074985745aa', '528d441c-8e2e-4fd7-9ccc-04585e211356', '5a1ee8ef-a7d3-4e27-a6e3-f2e2662af956', 'assistant', 'Le **Quart de Cycle** est à moitié vide à cette heure. Quelques habitués, le nez dans leur terminal. Personne ne lève la tête quand tu entres.

Ossek est au comptoir, occupé à nettoyer la machine à café avec une concentration excessive. Iel ne t''a pas vu, ou fait semblant.', 1, '10h15', '1587f86c-80ba-4594-9df3-5091253891b2', NULL, '{"cost": {"model": "scripted-model", "cost_usd": 0.0, "provider": "scripted", "input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "entity_reveals": [], "inventory_hints": [], "extraction_triggers": []}', 8, '2026-10-14 13:05:53.372081+00', 'Lundi 18 Juillet 2847', '{"skills": [{"name": "Athlétisme", "label": "Excellent", "level": 4, "custom": false}, {"name": "Empathie", "label": "Bon", "level": 3, "custom": false}, {"name": "Pilotage", "label": "Bon", "level": 3, "custom": false}, {"name": "Combat", "label": "Correct", "level": 2, "custom": false}, {"name": "Discrétion", "label": "Correct", "level": 2, "custom": false}, {"name": "Volonté", "label": "Correct", "level": 2, "custom": false}, {"name": "Contacts", "label": "Moyen", "level": 1, "custom": false}, {"name": "Physique", "label": "Moyen", "level": 1, "custom": false}, {"name": "Ressources", "label": "Moyen", "level": 1, "custom": false}, {"name": "Tromperie", "label": "Moyen", "level": 1, "custom": false}], "stunts": [], "aspects": ["Pilote déchu en quête de rédemption", "Je dois de l''argent à tout le monde", "Mon vieux cargo est ma maison"], "refresh": 3, "fate_points": 3, "consequences": {}, "stress_mental": [false, false, false, false], "stress_physical": [false, false, false, false]}', NULL);


--
-- Data for Name: mechanic_rolls; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.mechanic_rolls VALUES ('2590f988-529d-4303-8238-4cdcc503e17b', '528d441c-8e2e-4fd7-9ccc-04585e211356', '62cc9796-2ac9-4cf0-9d17-c074985745aa', 'fate_core', 'Athlétisme', '{"dice": [1, 1, 1, 1], "total": 4, "shifts": 5, "details": {"reason": "Action risquée.", "difficulty": 1, "skill_name": "Athlétisme", "skill_label": "Correct", "skill_value": 2, "difficulty_label": "Correct"}, "outcome": "success_with_style", "skill_total": 6, "complication": false, "opposition_total": null}', 'success_with_style', false, 1, '2026-10-14 13:05:53.375013+00');


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

INSERT INTO public.organizations VALUES ('76069acb-3c68-41f9-b0fa-0142ffb301f5', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Symbiose Tech', 'company', 'IA agricole', 'medium', 'Startup en difficulté. Ambiance tendue, deadlines impossibles.', 'innovants mais désorganisés, turnover élevé', '62ec0e83-c23d-42b7-b579-278eaa5f5386', -2920, NULL, '{}', 1, NULL, '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00');


--
-- Data for Name: protagonists; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.protagonists VALUES ('c3c0e91d-b898-430a-901c-a187fb823b93', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Valentin', 4.0, 3.0, 5.0, 1650, 'développeur IA senior', '76069acb-3c68-41f9-b0fa-0142ffb301f5', '2bf53139-52bf-466b-9044-562d1a3bbe32', 'Cité-Dôme de Vega III', 'fresh_start', 'Huit ans dans une startup qui a implosé. Burnout. Besoin de partir. Développeur compétent mais fatigué. Idéalisme érodé par les déceptions.', '{cuisine,lecture,"course à pied"}', NULL, '{}', '2026-10-14 13:05:52.694102+00', '2026-10-14 13:05:52.694102+00', NULL);


--
-- Data for Name: relations; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.relations VALUES ('d73306a0-9db2-4de0-8827-840904174a95', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'lives_at', 'e0631e55-664c-4a25-81ac-c7c1a6787c84', '931af6ef-c838-475a-b827-2c3b3e034d99', NULL, NULL, true, 1, NULL, NULL, '2026-10-14 13:05:52.694102+00');
INSERT INTO public.relations VALUES ('80269fdb-ae09-4ad0-80d4-257e7630b2ce', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'employed_by', 'e0631e55-664c-4a25-81ac-c7c1a6787c84', '88f76d44-65a9-4b82-9348-f7610cddd0c9', NULL, NULL, true, 1, NULL, NULL, '2026-10-14 13:05:52.694102+00');
INSERT INTO public.relations VALUES ('33543022-20f9-49fd-88e1-0ae7292fedbd', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'works_at', '52d8418e-5125-4e0e-8afc-967057301a66', '73fe0655-22cf-4a0a-9a93-d5c1cf73e8c8', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:05:52.694102+00');
INSERT INTO public.relations VALUES ('757c886f-9d12-447c-9954-4829b8746ede', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'lives_at', '52d8418e-5125-4e0e-8afc-967057301a66', '40239d4d-04f7-4138-8d8d-53a6eee4d2d8', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:05:52.694102+00');
INSERT INTO public.relations VALUES ('30f32310-cf98-4514-b22e-6b0b8f709d76', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'works_at', '682ac81d-ab9b-40a1-a3eb-94ace936dd42', '73fe0655-22cf-4a0a-9a93-d5c1cf73e8c8', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:05:52.694102+00');
INSERT INTO public.relations VALUES ('883ea309-60b9-4dd7-88e1-e5f47fade733', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'manages', '682ac81d-ab9b-40a1-a3eb-94ace936dd42', '88f76d44-65a9-4b82-9348-f7610cddd0c9', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:05:52.694102+00');
INSERT INTO public.relations VALUES ('a859652f-2d7f-40bc-8941-aae982a14044', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'owns', '211a506b-ba40-484c-9080-93162a01a988', '6d72136f-46e5-408a-9522-33c2971c14c8', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:05:52.694102+00');
INSERT INTO public.relations VALUES ('6380ac9b-6189-4690-9bd1-59623427c4a3', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'located_in', '931af6ef-c838-475a-b827-2c3b3e034d99', '40239d4d-04f7-4138-8d8d-53a6eee4d2d8', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:05:52.694102+00');
INSERT INTO public.relations VALUES ('bc4dbf69-55b5-4c07-b3f1-f86b449fd745', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'located_in', '88f76d44-65a9-4b82-9348-f7610cddd0c9', '73fe0655-22cf-4a0a-9a93-d5c1cf73e8c8', NULL, NULL, false, 1, NULL, NULL, '2026-10-14 13:05:52.694102+00');


--
-- Data for Name: skills; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.skills VALUES ('5d11dfc4-6eb2-476a-afd2-dacfa480a08a', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'c3c0e91d-b898-430a-901c-a187fb823b93', NULL, 'architecture_systemes', 4, 1, NULL, '2026-10-14 13:05:52.694102+00');
INSERT INTO public.skills VALUES ('2943b45b-7033-441f-b0c7-3c575b45b548', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'c3c0e91d-b898-430a-901c-a187fb823b93', NULL, 'programmation_ia', 4, 1, NULL, '2026-10-14 13:05:52.694102+00');


--
-- Data for Name: skills_d6; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- Data for Name: skills_fate; Type: TABLE DATA; Schema: public; Owner: test
--

INSERT INTO public.skills_fate VALUES ('98bda54b-e43f-49e1-bec1-3e66d407f070', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Athlétisme', 4, false);
INSERT INTO public.skills_fate VALUES ('d47ae5d6-1f88-4c9c-8560-444c14c3bcca', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Pilotage', 3, false);
INSERT INTO public.skills_fate VALUES ('e5835db7-7c5c-47d0-b422-66350efea625', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Empathie', 3, false);
INSERT INTO public.skills_fate VALUES ('2e08e35d-7990-43df-8714-27e47422dcb5', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Combat', 2, false);
INSERT INTO public.skills_fate VALUES ('133c556e-13c3-415e-82f3-d085721358b3', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Discrétion', 2, false);
INSERT INTO public.skills_fate VALUES ('1085b0a5-96be-4b75-adb8-b1dd1f7924d0', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Volonté', 2, false);
INSERT INTO public.skills_fate VALUES ('b957891f-4414-4270-9b42-3fe78462f8b3', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Contacts', 1, false);
INSERT INTO public.skills_fate VALUES ('0f8e9ea4-bbed-4f91-af1a-9faf5b5c00a8', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Ressources', 1, false);
INSERT INTO public.skills_fate VALUES ('7bda41a9-0fd5-4acd-9a71-788fbd718ccb', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Physique', 1, false);
INSERT INTO public.skills_fate VALUES ('6024e6a2-fa4c-4cb3-92c1-39b86264331f', '528d441c-8e2e-4fd7-9ccc-04585e211356', 'Tromperie', 1, false);


--
-- Data for Name: traits_narrative; Type: TABLE DATA; Schema: public; Owner: test
--



--
-- PostgreSQL database dump complete
--


