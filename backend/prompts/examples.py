"""
LDVELH - Exemples JSON pour les prompts
Centralisés ici pour être utilisés à la fois dans les prompts ET les tests.
"""

# =============================================================================
# WORLD GENERATION - Exemple complet
# =============================================================================

WORLD_GENERATION_EXAMPLE = """{
    "generation_seed_words": ["rouille", "reconversion", "isolement"],
    "world": {
        "name": "Escale Méridienne",
        "attributes": [
            {
                "key": "location_type",
                "value": "station orbitale reconvertie",
                "known": true
            },
            {
                "key": "atmosphere",
                "value": "Station industrielle usée, indifférence ambiante",
                "known": true
            },
            {
                "key": "description",
                "value": "Ancienne station minière reconvertie. Infrastructure vieillissante, population blasée.",
                "known": true
            },
            {
                "key": "notable_features",
                "value": "[\\"Quai Central\\", \\"Serres Hautes\\", \\"Quartier Ouvrier\\"]",
                "known": true
            }
        ],
        "sectors": ["Quai Central", "Serres Hautes", "Quartier Ouvrier"],
        "founding_cycle": -4500
    },
    "locations": [
        {
            "name": "Terminal Quai 7",
            "parent_location_ref": null,
            "attributes": [
                {"key": "location_type", "value": "terminal", "known": true},
                {"key": "sector", "value": "Quai Central", "known": true},
                {
                    "key": "description",
                    "value": "Hall bruyant aux plafonds tachés. Files d'attente permanentes.",
                    "known": true
                },
                {"key": "atmosphere", "value": "transit impersonnel", "known": true},
                {"key": "accessible", "value": "true", "known": true},
                {
                    "key": "notable_features",
                    "value": "[\\"kiosque à café médiocre\\", \\"sièges inconfortables\\"]",
                    "known": true
                },
                {
                    "key": "typical_crowd",
                    "value": "voyageurs fatigués, dockers indifférents",
                    "known": true
                },
                {"key": "operating_hours", "value": "24/7", "known": true}
            ]
        },
        {
            "name": "Bloc Tournesol",
            "parent_location_ref": null,
            "attributes": [
                {
                    "key": "location_type",
                    "value": "residential_building",
                    "known": false
                },
                {"key": "sector", "value": "Quartier Ouvrier", "known": false},
                {
                    "key": "description",
                    "value": "Immeuble de six étages, façade défraîchie. Ascenseur en panne un jour sur trois.",
                    "known": false
                },
                {"key": "atmosphere", "value": "vétuste mais vivant", "known": false},
                {"key": "accessible", "value": "true", "known": false},
                {
                    "key": "notable_features",
                    "value": "[\\"hall mal éclairé\\", \\"boîtes aux lettres cabossées\\"]",
                    "known": false
                }
            ]
        },
        {
            "name": "Appartement 4-12",
            "parent_location_ref": "Bloc Tournesol",
            "attributes": [
                {"key": "location_type", "value": "apartment", "known": false},
                {"key": "sector", "value": "Quartier Ouvrier", "known": false},
                {
                    "key": "description",
                    "value": "28m², murs fins, vue sur conduit d'aération. Le minimum syndical.",
                    "known": false
                },
                {"key": "atmosphere", "value": "exigu et impersonnel", "known": false},
                {"key": "accessible", "value": "true", "known": false},
                {
                    "key": "notable_features",
                    "value": "[\\"kitchenette vétuste\\", \\"lit qui grince\\"]",
                    "known": false
                }
            ]
        },
        {
            "name": "Serres Hydro-7",
            "parent_location_ref": null,
            "attributes": [
                {"key": "location_type", "value": "workplace", "known": true},
                {"key": "sector", "value": "Serres Hautes", "known": false},
                {
                    "key": "description",
                    "value": "Serre industrielle. Humidité constante, éclairage agressif.",
                    "known": false
                },
                {"key": "atmosphere", "value": "humide et bruyante", "known": false},
                {"key": "accessible", "value": "true", "known": false},
                {
                    "key": "notable_features",
                    "value": "[\\"bassins nutritifs\\", \\"ventilation assourdissante\\"]",
                    "known": false
                },
                {
                    "key": "typical_crowd",
                    "value": "techniciens concentrés",
                    "known": false
                },
                {"key": "operating_hours", "value": "06h-22h", "known": false}
            ]
        },
        {
            "name": "Le Quart de Cycle",
            "parent_location_ref": null,
            "attributes": [
                {"key": "location_type", "value": "cafe", "known": false},
                {"key": "sector", "value": "Quai Central", "known": false},
                {
                    "key": "description",
                    "value": "Café correct, sans plus. Le proprio n'est pas du genre bavard.",
                    "known": false
                },
                {"key": "atmosphere", "value": "fonctionnel", "known": false},
                {"key": "accessible", "value": "true", "known": false},
                {
                    "key": "notable_features",
                    "value": "[\\"comptoir usé\\", \\"chaises dépareillées\\"]",
                    "known": false
                },
                {
                    "key": "typical_crowd",
                    "value": "habitués silencieux",
                    "known": false
                },
                {"key": "operating_hours", "value": "07h-23h", "known": false},
                {"key": "price_range", "value": "budget", "known": false}
            ]
        }
    ],
    "organizations": [
        {
            "name": "Symbiose Tech",
            "headquarters_ref": "Serres Hydro-7",
            "attributes": [
                {"key": "org_type", "value": "company", "known": true},
                {"key": "domain", "value": "IA agricole", "known": true},
                {"key": "size", "value": "medium", "known": true},
                {
                    "key": "description",
                    "value": "Startup en difficulté. Ambiance tendue, deadlines impossibles.",
                    "known": false
                },
                {
                    "key": "reputation",
                    "value": "innovants mais désorganisés, turnover élevé",
                    "known": false
                },
                {"key": "founding_cycle", "value": "-2920", "known": false},
                {"key": "is_employer", "value": "true", "known": true},
                {
                    "key": "true_purpose",
                    "value": "Rentabilité à court terme, peu importe les conséquences",
                    "known": false
                }
            ]
        }
    ],
    "protagonist": {
        "name": "Valentin",
        "attributes": [
            {"key": "origin", "value": "Cité-Dôme de Vega III", "known": true},
            {"key": "departure_reason", "value": "fresh_start", "known": true},
            {
                "key": "backstory",
                "value": "Huit ans dans une startup qui a implosé. Burnout. Besoin de partir. Développeur compétent mais fatigué. Idéalisme érodé par les déceptions.",
                "known": true
            },
            {"key": "occupation", "value": "développeur IA senior", "known": true},
            {
                "key": "hobbies",
                "value": "[\\"cuisine\\", \\"lecture\\", \\"course à pied\\"]",
                "known": true
            },
            {"key": "credits", "value": "1650", "known": true},
            {"key": "energy", "value": "2.5", "known": true},
            {"key": "morale", "value": "2.5", "known": true},
            {"key": "health", "value": "4.0", "known": true}
        ],
        "skills": [
            {"name": "architecture_systemes", "level": 4},
            {"name": "programmation_ia", "level": 4}
        ]
    },
    "personal_ai": {
        "name": "Célimène",
        "creator_ref": null,
        "attributes": [
            {"key": "voice", "value": "voix rauque, débit lent", "known": true},
            {
                "key": "traits",
                "value": "[\\"sarcastique\\", \\"observatrice\\", \\"peu impressionnable\\"]",
                "known": true
            },
            {"key": "substrate", "value": "personal_device", "known": true},
            {
                "key": "quirk",
                "value": "Note les contradictions des gens sans les commenter... sauf quand c'est drôle",
                "known": false
            }
        ]
    },
    "characters": [
        {
            "name": "Justine Lépicier",
            "workplace_ref": "Serres Hydro-7",
            "residence_ref": "Bloc Tournesol",
            "known_by_protagonist": false,
            "unknown_name": null,
            "attributes": [
                {"key": "species", "value": "human", "known": false},
                {"key": "gender", "value": "femme", "known": false},
                {"key": "pronouns", "value": "elle", "known": false},
                {"key": "age", "value": "32", "known": false},
                {
                    "key": "description",
                    "value": "1m54, courbes prononcées, blonde en désordre, yeux bleus cernés",
                    "known": false
                },
                {
                    "key": "traits",
                    "value": "[\\"pragmatique\\", \\"humour caustique\\", \\"méfiante\\", \\"épuisée\\"]",
                    "known": false
                },
                {
                    "key": "occupation",
                    "value": "technicienne maintenance serres",
                    "known": false
                },
                {"key": "mood", "value": "fatiguée, sur la défensive", "known": false},
                {"key": "origin", "value": "Station Kepler-22", "known": false},
                {"key": "arrival_cycle", "value": "-730", "known": false},
                {
                    "key": "motivation",
                    "value": "Protéger sa mère malade, survivre",
                    "known": false
                },
                {
                    "key": "arcs",
                    "value": "[{\\"domain\\": \\"family\\", \\"title\\": \\"La mère malade\\", \\"situation\\": \\"Mère malade, envoie la moitié de son salaire\\", \\"desire\\": \\"Faire venir sa mère ici\\", \\"obstacle\\": \\"Coût du transfert médical astronomique\\", \\"intensity\\": 5}, {\\"domain\\": \\"romantic\\", \\"title\\": \\"Cœur fermé\\", \\"situation\\": \\"Rupture difficile il y a deux ans\\", \\"desire\\": \\"La paix\\", \\"obstacle\\": \\"Se protège derrière le sarcasme\\", \\"intensity\\": 2}]",
                    "known": false
                },
                {"key": "romantic_potential", "value": "true", "known": false},
                {"key": "is_mandatory", "value": "true", "known": false}
            ]
        },
        {
            "name": "Dr. Yuki Tanaka",
            "workplace_ref": "Serres Hydro-7",
            "residence_ref": "Bloc Tournesol",
            "known_by_protagonist": false,
            "unknown_name": null,
            "attributes": [
                {"key": "species", "value": "human", "known": false},
                {"key": "gender", "value": "femme", "known": false},
                {"key": "pronouns", "value": "elle", "known": false},
                {"key": "age", "value": "45", "known": false},
                {
                    "key": "description",
                    "value": "Petite, cheveux gris en chignon serré, posture rigide, regard dur",
                    "known": false
                },
                {
                    "key": "traits",
                    "value": "[\\"perfectionniste\\", \\"impatiente\\", \\"cassante\\", \\"méfiante envers les nouveaux\\"]",
                    "known": false
                },
                {
                    "key": "occupation",
                    "value": "directrice technique Symbiose Tech",
                    "known": false
                },
                {"key": "mood", "value": "tendue, irritable", "known": false},
                {"key": "origin", "value": "Mars-Cité", "known": false},
                {"key": "arrival_cycle", "value": "-2800", "known": false},
                {
                    "key": "motivation",
                    "value": "Prouver sa valeur, ne jamais échouer",
                    "known": false
                },
                {
                    "key": "arcs",
                    "value": "[{\\"domain\\": \\"professional\\", \\"title\\": \\"Standards impossibles\\", \\"situation\\": \\"Pousse l'équipe trop fort\\", \\"desire\\": \\"Projet parfait\\", \\"obstacle\\": \\"Son exigence fait fuir les talents\\", \\"intensity\\": 4}, {\\"domain\\": \\"health\\", \\"title\\": \\"Burnout silencieux\\", \\"situation\\": \\"14h/jour depuis des mois\\", \\"desire\\": \\"Prouver qu'elle gère\\", \\"obstacle\\": \\"Refuse d'admettre le problème\\", \\"intensity\\": 5}]",
                    "known": false
                },
                {"key": "romantic_potential", "value": "false", "known": false},
                {"key": "is_mandatory", "value": "false", "known": false}
            ]
        },
        {
            "name": "Ossek",
            "workplace_ref": "Le Quart de Cycle",
            "residence_ref": "Le Quart de Cycle",
            "known_by_protagonist": false,
            "unknown_name": null,
            "attributes": [
                {"key": "species", "value": "keth (semi-aquatique)", "known": false},
                {"key": "gender", "value": "non-binaire", "known": false},
                {"key": "pronouns", "value": "iel", "known": false},
                {
                    "key": "description",
                    "value": "Peau bleu-gris, branchies latérales, yeux sans pupilles, mouvements lents",
                    "known": false
                },
                {
                    "key": "traits",
                    "value": "[\\"calme\\", \\"distant\\", \\"mélancolique\\", \\"peu bavard\\"]",
                    "known": false
                },
                {"key": "occupation", "value": "propriétaire du café", "known": false},
                {"key": "mood", "value": "mélancolique, absent", "known": false},
                {"key": "origin", "value": "Monde-Océan de Téthys", "known": false},
                {"key": "arrival_cycle", "value": "-1825", "known": false},
                {
                    "key": "motivation",
                    "value": "Retrouver un sens d'appartenance",
                    "known": false
                },
                {
                    "key": "arcs",
                    "value": "[{\\"domain\\": \\"health\\", \\"title\\": \\"Le mal du banc\\", \\"situation\\": \\"Mélancolie keth chronique\\", \\"desire\\": \\"Équilibre émotionnel\\", \\"obstacle\\": \\"Aucun traitement connu\\", \\"intensity\\": 4}, {\\"domain\\": \\"social\\", \\"title\\": \\"L'exil\\", \\"situation\\": \\"Seul de son espèce ici\\", \\"desire\\": \\"Trouver une famille choisie\\", \\"obstacle\\": \\"Les Keth isolés se replient\\", \\"intensity\\": 3}]",
                    "known": false
                },
                {"key": "romantic_potential", "value": "false", "known": false},
                {"key": "is_mandatory", "value": "false", "known": false}
            ]
        }
    ],
    "inventory": [
        {
            "name": "Terminal personnel",
            "attributes": [
                {"key": "category", "value": "tech", "known": true},
                {
                    "key": "description",
                    "value": "Modèle standard usé, héberge Célimène",
                    "known": true
                },
                {"key": "transportable", "value": "true", "known": true},
                {"key": "stackable", "value": "false", "known": true},
                {"key": "base_value", "value": "300", "known": true}
            ],
            "quantity": 1
        },
        {
            "name": "Valise cabine",
            "attributes": [
                {"key": "category", "value": "baggage", "known": true},
                {
                    "key": "description",
                    "value": "Plastique rayé, fermeture capricieuse",
                    "known": true
                },
                {"key": "transportable", "value": "true", "known": true},
                {"key": "stackable", "value": "false", "known": true},
                {"key": "base_value", "value": "40", "known": true}
            ],
            "quantity": 1
        }
    ],
    "narrative_arcs": [
        {
            "title": "Pression sur Symbiose",
            "arc_type": "foreshadowing",
            "domain": "professional",
            "description": "Investisseur externe s'intéresse à Symbiose avec intentions floues.",
            "involved_entities": ["Symbiose Tech", "Dr. Yuki Tanaka"],
            "potential_triggers": ["réunion générale", "rumeurs"],
            "stakes": "Indépendance de l'entreprise",
            "deadline_cycle": 180
        }
    ],
    "initial_relations": [
        {
            "source_ref": "Valentin",
            "target_ref": "Appartement 4-12",
            "relation_type": "lives_at",
            "known_by_protagonist": true
        },
        {
            "source_ref": "Valentin",
            "target_ref": "Symbiose Tech",
            "relation_type": "employed_by",
            "known_by_protagonist": true
        },
        {
            "source_ref": "Justine Lépicier",
            "target_ref": "Serres Hydro-7",
            "relation_type": "works_at",
            "known_by_protagonist": false
        },
        {
            "source_ref": "Justine Lépicier",
            "target_ref": "Bloc Tournesol",
            "relation_type": "lives_at",
            "known_by_protagonist": false
        },
        {
            "source_ref": "Dr. Yuki Tanaka",
            "target_ref": "Serres Hydro-7",
            "relation_type": "works_at",
            "known_by_protagonist": false
        },
        {
            "source_ref": "Dr. Yuki Tanaka",
            "target_ref": "Symbiose Tech",
            "relation_type": "manages",
            "known_by_protagonist": false
        },
        {
            "source_ref": "Ossek",
            "target_ref": "Le Quart de Cycle",
            "relation_type": "owns",
            "known_by_protagonist": false
        },
        {
            "source_ref": "Appartement 4-12",
            "target_ref": "Bloc Tournesol",
            "relation_type": "located_in",
            "known_by_protagonist": false
        },
        {
            "source_ref": "Symbiose Tech",
            "target_ref": "Serres Hydro-7",
            "relation_type": "located_in",
            "known_by_protagonist": false
        }
    ],
    "arrival_event": {
        "arrival_method": "navette cargo, 3h de retard",
        "arrival_location_ref": "Terminal Quai 7",
        "arrival_date": "Lundi 18 Juillet 2847",
        "time": "11h42",
        "immediate_sensory_details": [
            "Odeur de sueur et de métal recyclé",
            "Annonce PA grésillante",
            "Lumière crue après la pénombre de la navette",
            "File d'attente interminable"
        ],
        "first_npc_encountered": null,
        "initial_mood": "fatigué, nauséeux, décalé",
        "immediate_need": "Trouver l'appartement et dormir",
        "optional_incident": "Systèmes bagages en panne, attente indéterminée"
    }
}"""


# =============================================================================
# NARRATION - Exemples de sortie du narrateur
# =============================================================================

NARRATION_EXAMPLE_NEUTRAL = {
    "narrative_text": "Le **Quart de Cycle** est à moitié vide à cette heure. Quelques habitués, le nez dans leur terminal. Personne ne lève la tête quand tu entres.\n\nOssek est au comptoir, occupé à nettoyer la machine à café avec une concentration excessive. Iel ne t'a pas vu, ou fait semblant.",
    "time": {"new_time": "10h15", "ellipse": False, "ellipse_summary": None},
    "day_transition": None,
    "current_location": "Le Quart de Cycle",
    "npcs_present": ["Ossek"],
    "suggested_actions": [
        "Commander un café",
        "S'installer dans un coin",
        "Partir",
    ],
    "hints": {
        "new_entities_mentioned": [],
        "relationships_changed": False,
        "protagonist_state_changed": False,
        "information_learned": False,
        "commitment_advanced": [],
        "commitment_resolved": [],
        "new_commitment_created": False,
        "event_scheduled": False,
        "event_occurred": False,
    },
    "scene_mood": "banal et indifférent",
    "narrator_notes": None,
}

NARRATION_EXAMPLE_PNJ_UNAVAILABLE = {
    "narrative_text": "Tu t'approches du comptoir. Ossek lève les yeux, mais son regard est ailleurs.\n\n— Ah. Salut.\n\nLe ton est plat. Pas hostile, juste... absent. Iel repose le verre qu'iel essuyait, en prend un autre, recommence le même geste.\n\n*Clairement pas le bon moment.*",
    "time": {"new_time": "10h20", "ellipse": False, "ellipse_summary": None},
    "day_transition": None,
    "current_location": "Le Quart de Cycle",
    "npcs_present": ["Ossek"],
    "suggested_actions": [
        "Commander sans insister",
        "Demander si tout va bien",
        "S'installer et observer",
        "Partir",
    ],
    "hints": {
        "new_entities_mentioned": [],
        "relationships_changed": False,
        "protagonist_state_changed": False,
        "information_learned": False,
        "commitment_advanced": ["L'exil du banc"],
        "commitment_resolved": [],
        "new_commitment_created": False,
        "event_scheduled": False,
        "event_occurred": False,
    },
    "scene_mood": "distant",
    "narrator_notes": "Ossek: mauvaise journée (mal du banc)",
}

NARRATION_EXAMPLE_DAY_TRANSITION = {
    "narrative_text": "La fatigue finit par avoir raison de toi. Tu t'écroules sur le lit étroit, sans même prendre la peine de te déshabiller.",
    "time": {"new_time": "23h45", "ellipse": False, "ellipse_summary": None},
    "day_transition": {
        "new_cycle": 5,
        "new_date": "Samedi 18 Mars 2847",
        "night_summary": "Nuit agitée, rêves confus.",
    },
    "current_location": "Appartement 4-12",
    "npcs_present": [],
    "suggested_actions": [
        "Se lever",
        "Rester au lit encore un peu",
    ],
    "hints": {
        "new_entities_mentioned": [],
        "relationships_changed": False,
        "protagonist_state_changed": False,
        "information_learned": False,
        "commitment_advanced": [],
        "commitment_resolved": [],
        "new_commitment_created": False,
        "event_scheduled": False,
        "event_occurred": False,
    },
    "scene_mood": "fatigué",
    "narrator_notes": None,
}

# Template pour le prompt (avec placeholders)
NARRATION_OUTPUT_TEMPLATE = {
    "narrative_text": "Texte Markdown de la scène. Le narrateur décrit l'environnement, les personnages présents, et les interactions possibles avec suffisamment de détails pour immerger le joueur.",
    "time": {"new_time": "14h45", "ellipse": False, "ellipse_summary": None},
    "day_transition": None,
    "current_location": "Nom EXACT du lieu",
    "npcs_present": ["Nom EXACT PNJ1", "Nom EXACT PNJ2"],
    "suggested_actions": [
        "Action courte 1",
        "Action courte 2",
        "Action courte 3",
    ],
    "hints": {
        "new_entities_mentioned": [],
        "relationships_changed": False,
        "protagonist_state_changed": False,
        "information_learned": False,
        "commitment_advanced": [],
        "commitment_resolved": [],
        "new_commitment_created": False,
        "event_scheduled": False,
        "event_occurred": False,
    },
    "scene_mood": "2-4 mots max",
    "narrator_notes": "Notes techniques courtes",
}


# =============================================================================
# EXTRACTION - Exemples par extracteur
# =============================================================================

EXTRACTION_PROTAGONIST_STATE_EXAMPLE = {
    "gauge_changes": [
        {"gauge": "energy", "delta": -0.5, "reason": "Conversation épuisante"}
    ],
    "credit_transactions": [{"amount": -15, "description": "Café au Quart de Cycle"}],
    "inventory_changes": [
        {
            "action": "acquire",
            "object_ref": None,
            "object_hint": "Carte d'accès temporaire",
            "quantity_delta": 1,
            "reason": "Donnée par l'accueil",
        }
    ],
}

EXTRACTION_ENTITIES_EXAMPLE = {
    "entities_created": [
        {
            "entity_type": "character",
            "name": "Elena Vasquez",
            "known_by_protagonist": True,
            "unknown_name": None,
            "attributes": [
                {
                    "key": "description",
                    "value": "Grande, cheveux courts",
                    "known": True,
                },
                {"key": "mood", "value": "anxieuse mais déterminée", "known": True},
                {"key": "origin", "value": "Colonie de Mars", "known": False},
                {"key": "arcs", "value": "[{...}]", "known": False},
            ],
        }
    ],
    "entities_updated": [
        {
            "entity_ref": "La femme mystérieuse",
            "now_known": True,
            "real_name": "Dr. Sarah Chen",
            "attributes_changed": [
                {"key": "reputation", "value": "Xénobiologiste renommée", "known": True}
            ],
        }
    ],
}

EXTRACTION_FACTS_EXAMPLE = {
    "facts": [
        {
            "fact_type": "revelation",
            "description": "Marie révèle qu'elle envoie de l'argent à sa mère malade",
            "semantic_key": "marie:revele:mere_malade",
            "importance": 4,
            "participants": [
                {"entity_ref": "Marie", "role": "actor"},
                {"entity_ref": "Valentin", "role": "witness"},
            ],
        }
    ],
}

EXTRACTION_RELATIONS_EXAMPLE = {
    "relations_created": [
        {
            "cycle": 5,
            "relation": {
                "source_ref": "Valentin",
                "target_ref": "Marie",
                "relation_type": "knows",
                "known_by_protagonist": True,
                "social": {"level": 3, "context": "Collègues de travail"},
            },
        }
    ],
    "relations_updated": [
        {
            "source_ref": "Valentin",
            "target_ref": "Marie",
            "relation_type": "knows",
            "new_level": 4,
            "new_context": "Confidents",
            "now_known": True,
        }
    ],
}

EXTRACTION_COMMITMENTS_EXAMPLE = {
    "commitments_created": [
        {
            "commitment_type": "foreshadowing",
            "description": "Marie mentionne des rumeurs sur un rachat de Symbiose",
            "involved_entities": ["Marie", "Symbiose Tech"],
            "deadline_cycle": None,
        }
    ],
    "commitments_resolved": [
        {
            "commitment_description": "Promesse d'aider avec le rapport",
            "resolution_description": "Rapport terminé ensemble",
        }
    ],
    "events_scheduled": [
        {
            "event_type": "appointment",
            "title": "Déjeuner avec Marie",
            "description": "RDV informel au Quart de Cycle",
            "planned_cycle": 7,
            "time": "12h30",
            "location_ref": "Le Quart de Cycle",
            "participants": ["Marie"],
        }
    ],
}

EXTRACTION_OBJECTS_EXAMPLE = {
    "objects_created": [
        {
            "name": "Carte d'accès niveau 2",
            "attributes": [
                {
                    "key": "description",
                    "value": "Carte magnétique bleue avec puce intégrée",
                    "known": True,
                    "details": {
                        "category": "tech",
                        "transportable": True,
                        "stackable": False,
                        "base_value": 50,
                    },
                },
            ],
            "from_hint": "Carte d'accès temporaire",
        }
    ],
}
