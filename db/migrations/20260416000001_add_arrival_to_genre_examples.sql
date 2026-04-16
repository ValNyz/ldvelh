-- migrate:up
-- Add arrival_event to genre world_gen_examples so the LLM generates one (with genre-appropriate dates)

-- SCI-FI: append arrival_event before closing brace
UPDATE genres SET world_gen_example = regexp_replace(
    world_gen_example::text,
    '\]\s*\}\s*$',
    E'],\n  "arrival_event": {\n    "arrival_method": "navette de transport",\n    "arrival_location_ref": "Terminal Quai 7",\n    "arrival_date": "Lundi 14 Mars 2847",\n    "time": "08h00",\n    "immediate_sensory_details": ["L''air recyclé de la station", "Le bourdonnement des systèmes", "La lumière artificielle"],\n    "first_npc_encountered": null,\n    "initial_mood": "Appréhension et curiosité",\n    "immediate_need": "Trouver ses quartiers"\n  }\n}'
) WHERE slug = 'sci_fi';

-- DARK FANTASY
UPDATE genres SET world_gen_example = regexp_replace(
    world_gen_example::text,
    '\]\s*\}\s*$',
    E'],\n  "arrival_event": {\n    "arrival_method": "à pied, par la route de l''est",\n    "arrival_location_ref": "La Couronne Fendue",\n    "arrival_date": "Troisième jour de la Lune des Brumes",\n    "time": "17h00",\n    "immediate_sensory_details": ["Le vent froid sur les murailles", "L''odeur de fumée et de boue", "Le grincement d''un chariot"],\n    "first_npc_encountered": null,\n    "initial_mood": "Épuisement du voyage, méfiance",\n    "immediate_need": "Trouver un toit avant la nuit"\n  }\n}'
) WHERE slug = 'dark_fantasy';

-- COSMIC HORROR
UPDATE genres SET world_gen_example = regexp_replace(
    world_gen_example::text,
    '\]\s*\}\s*$',
    E'],\n  "arrival_event": {\n    "arrival_method": "train de nuit",\n    "arrival_location_ref": "Pension du Goéland",\n    "arrival_date": "Jeudi 3 Octobre 1923",\n    "time": "22h30",\n    "immediate_sensory_details": ["Le brouillard qui colle à la peau", "L''odeur de sel et de vase", "Le silence du quai désert"],\n    "first_npc_encountered": null,\n    "initial_mood": "Malaise diffus",\n    "immediate_need": "Trouver sa pension et déposer ses affaires"\n  }\n}'
) WHERE slug = 'cosmic_horror';

-- CYBERPUNK
UPDATE genres SET world_gen_example = regexp_replace(
    world_gen_example::text,
    '\]\s*\}\s*$',
    E'],\n  "arrival_event": {\n    "arrival_method": "transport automatisé",\n    "arrival_location_ref": "Le Byte Bar",\n    "arrival_date": "Mercredi 7 Novembre 2089",\n    "time": "23h00",\n    "immediate_sensory_details": ["Le néon qui pulse sur les murs humides", "L''odeur d''ozone et de friture", "Le bruit sourd des basses"],\n    "first_npc_encountered": null,\n    "initial_mood": "Tension nerveuse",\n    "immediate_need": "Trouver un endroit sûr"\n  }\n}'
) WHERE slug = 'cyberpunk';

-- migrate:down
-- Remove arrival_event from genre examples (revert to previous state)
-- Not practical with regexp — would need to store originals. Skip.
