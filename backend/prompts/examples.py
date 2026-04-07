"""
LDVELH - Exemples JSON pour les prompts
Centralisés ici pour être utilisés à la fois dans les prompts ET les tests.
Format : colonnes directes (pas d'EAV attributes).
"""

# =============================================================================
# WORLD GENERATION - Exemple complet
# =============================================================================

WORLD_GENERATION_EXAMPLE = """{
    "generation_seed_words": ["rouille", "reconversion", "isolement"],
    "world": {
        "name": "Escale Méridienne",
        "description": "Ancienne station minière reconvertie. Infrastructure vieillissante, population blasée.",
        "atmosphere": "Station industrielle usée, indifférence ambiante",
        "sectors": ["Quai Central", "Serres Hautes", "Quartier Ouvrier"],
        "founding_cycle": -4500
    },
    "locations": [
        {
            "name": "Terminal Quai 7",
            "parent_location_ref": null,
            "location_type": "terminal",
            "sector": "Quai Central",
            "description": "Hall bruyant aux plafonds tachés. Files d'attente permanentes.",
            "atmosphere": "transit impersonnel",
            "accessible": true,
            "notable_features": ["kiosque à café médiocre", "sièges inconfortables"],
            "typical_crowd": "voyageurs fatigués, dockers indifférents",
            "operating_hours": "24/7"
        },
        {
            "name": "Bloc Tournesol",
            "parent_location_ref": null,
            "location_type": "residential_building",
            "sector": "Quartier Ouvrier",
            "description": "Immeuble de six étages, façade défraîchie. Ascenseur en panne un jour sur trois.",
            "atmosphere": "vétuste mais vivant",
            "accessible": true,
            "notable_features": ["hall mal éclairé", "boîtes aux lettres cabossées"]
        },
        {
            "name": "Appartement 4-12",
            "parent_location_ref": "Bloc Tournesol",
            "location_type": "apartment",
            "sector": "Quartier Ouvrier",
            "description": "28m², murs fins, vue sur conduit d'aération. Le minimum syndical.",
            "atmosphere": "exigu et impersonnel",
            "accessible": true,
            "notable_features": ["kitchenette vétuste", "lit qui grince"]
        },
        {
            "name": "Serres Hydro-7",
            "parent_location_ref": null,
            "location_type": "workplace",
            "sector": "Serres Hautes",
            "description": "Serre industrielle. Humidité constante, éclairage agressif.",
            "atmosphere": "humide et bruyante",
            "accessible": true,
            "notable_features": ["bassins nutritifs", "ventilation assourdissante"],
            "typical_crowd": "techniciens concentrés",
            "operating_hours": "06h-22h"
        },
        {
            "name": "Le Quart de Cycle",
            "parent_location_ref": null,
            "location_type": "cafe",
            "sector": "Quai Central",
            "description": "Café correct, sans plus. Le proprio n'est pas du genre bavard.",
            "atmosphere": "fonctionnel",
            "accessible": true,
            "notable_features": ["comptoir usé", "chaises dépareillées"],
            "typical_crowd": "habitués silencieux",
            "operating_hours": "07h-23h",
            "price_range": "budget"
        }
    ],
    "organizations": [
        {
            "name": "Symbiose Tech",
            "headquarters_ref": "Serres Hydro-7",
            "org_type": "company",
            "domain": "IA agricole",
            "size": "medium",
            "description": "Startup en difficulté. Ambiance tendue, deadlines impossibles.",
            "reputation": "innovants mais désorganisés, turnover élevé",
            "founding_cycle": -2920
        }
    ],
    "protagonist": {
        "name": "Valentin",
        "origin": "Cité-Dôme de Vega III",
        "departure_reason": "fresh_start",
        "backstory": "Huit ans dans une startup qui a implosé. Burnout. Besoin de partir. Développeur compétent mais fatigué. Idéalisme érodé par les déceptions.",
        "occupation": "développeur IA senior",
        "hobbies": ["cuisine", "lecture", "course à pied"],
        "credits": 1650,
        "employer_ref": "Symbiose Tech",
        "residence_ref": "Appartement 4-12",
        "skills": [
            {"name": "architecture_systemes", "level": 4},
            {"name": "programmation_ia", "level": 4}
        ]
    },
    "personal_assistant": {
        "name": "Célimène",
        "voice": "voix rauque, débit lent",
        "traits": ["sarcastique", "observatrice", "peu impressionnable"],
        "substrate": "personal_device",
        "quirk": "Note les contradictions des gens sans les commenter... sauf quand c'est drôle"
    },
    "characters": [
        {
            "name": "Justine Lépicier",
            "workplace_ref": "Serres Hydro-7",
            "residence_ref": "Bloc Tournesol",
            "known_by_protagonist": false,
            "unknown_name": null,
            "species": "human",
            "gender": "femme",
            "pronouns": "elle",
            "age": "32",
            "description": "1m54, courbes prononcées, blonde en désordre, yeux bleus cernés",
            "traits": ["pragmatique", "humour caustique", "méfiante", "épuisée"],
            "occupation": "technicienne maintenance serres",
            "mood": "fatiguée, sur la défensive",
            "origin": "Station Kepler-22",
            "romantic_potential": true,
            "is_mandatory": true
        },
        {
            "name": "Dr. Yuki Tanaka",
            "workplace_ref": "Serres Hydro-7",
            "residence_ref": "Bloc Tournesol",
            "known_by_protagonist": false,
            "unknown_name": null,
            "species": "human",
            "gender": "femme",
            "pronouns": "elle",
            "age": "45",
            "description": "Petite, cheveux gris en chignon serré, posture rigide, regard dur",
            "traits": ["perfectionniste", "impatiente", "cassante", "méfiante envers les nouveaux"],
            "occupation": "directrice technique Symbiose Tech",
            "mood": "tendue, irritable",
            "origin": "Mars-Cité",
            "romantic_potential": false,
            "is_mandatory": false
        },
        {
            "name": "Ossek",
            "workplace_ref": "Le Quart de Cycle",
            "residence_ref": "Le Quart de Cycle",
            "known_by_protagonist": false,
            "unknown_name": null,
            "species": "keth (semi-aquatique)",
            "gender": "non-binaire",
            "pronouns": "iel",
            "description": "Peau bleu-gris, branchies latérales, yeux sans pupilles, mouvements lents",
            "traits": ["calme", "distant", "mélancolique", "peu bavard"],
            "occupation": "propriétaire du café",
            "mood": "mélancolique, absent",
            "origin": "Monde-Océan de Téthys",
            "romantic_potential": false,
            "is_mandatory": false
        }
    ],
    "inventory": [
        {
            "name": "Terminal personnel",
            "category": "tech",
            "description": "Modèle standard usé, héberge Célimène",
            "transportable": true,
            "stackable": false,
            "base_value": 300,
            "quantity": 1
        },
        {
            "name": "Valise cabine",
            "category": "baggage",
            "description": "Plastique rayé, fermeture capricieuse",
            "transportable": true,
            "stackable": false,
            "base_value": 40,
            "quantity": 1
        }
    ],
    "narrative_arcs": [
        {
            "title": "La mère malade",
            "domain": "family",
            "description": "Justine envoie la moitié de son salaire pour sa mère malade restée sur Kepler-22. Le coût du transfert médical est astronomique.",
            "involved_entities": ["Justine Lépicier"],
            "intensity": 5,
            "situation": "Mère malade, envoie la moitié de son salaire",
            "desire": "Faire venir sa mère ici",
            "obstacle": "Coût du transfert médical astronomique",
            "potential_triggers": ["discussion sur la famille", "nouvelles de Kepler-22"],
            "stakes": "Santé de sa mère"
        },
        {
            "title": "Burnout silencieux",
            "domain": "health",
            "description": "Dr. Tanaka pousse l'équipe au-delà du raisonnable. 14h par jour depuis des mois. Refuse d'admettre le problème.",
            "involved_entities": ["Dr. Yuki Tanaka", "Symbiose Tech"],
            "intensity": 5,
            "situation": "14h/jour depuis des mois",
            "desire": "Prouver qu'elle gère",
            "obstacle": "Refuse d'admettre le problème",
            "potential_triggers": ["incident au travail", "confrontation"],
            "stakes": "Santé de Tanaka et survie de l'équipe"
        },
        {
            "title": "Le mal du banc",
            "domain": "health",
            "description": "Mélancolie keth chronique d'Ossek. Seul de son espèce sur la station.",
            "involved_entities": ["Ossek"],
            "intensity": 4,
            "situation": "Mélancolie chronique, isolement",
            "desire": "Équilibre émotionnel",
            "obstacle": "Aucun traitement connu",
            "potential_triggers": ["conversation sincère", "rappel de Téthys"],
            "stakes": "Santé mentale d'Ossek"
        },
        {
            "title": "Pression sur Symbiose",
            "domain": "professional",
            "description": "Investisseur externe s'intéresse à Symbiose avec intentions floues.",
            "involved_entities": ["Symbiose Tech", "Dr. Yuki Tanaka"],
            "intensity": 4,
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
    "credit_delta": None,
    "inventory_hints": [],
    "entity_reveals": [],
    "events_mentioned": [],
    "info_requests": [],
    "extraction_triggers": [],
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
    "credit_delta": None,
    "inventory_hints": [],
    "entity_reveals": [],
    "events_mentioned": [],
    "info_requests": [],
    "extraction_triggers": ["narrative_arcs"],
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
    "credit_delta": None,
    "inventory_hints": [],
    "entity_reveals": [],
    "events_mentioned": [],
    "info_requests": [],
    "extraction_triggers": [],
    "scene_mood": "fatigué",
    "narrator_notes": None,
}

# Exemple avec deltas (achat + fatigue)
NARRATION_EXAMPLE_WITH_DELTAS = {
    "narrative_text": "Tu t'installes au comptoir et commandes le premier café de la journée. Le liquide est tiède et amer — la machine a connu des jours meilleurs.\n\nOssek dépose la tasse sans un mot, puis retourne à son éternel nettoyage. Au moins iel ne fait pas de small talk.\n\n*Le café est mauvais, mais il fait le travail.*",
    "time": {"new_time": "07h30", "ellipse": False, "ellipse_summary": None},
    "day_transition": None,
    "current_location": "Le Quart de Cycle",
    "npcs_present": ["Ossek"],
    "suggested_actions": [
        "Commander un deuxième café",
        "Consulter le terminal personnel",
        "Partir travailler",
    ],
    "credit_delta": {"amount": -8, "description": "Café au Quart de Cycle"},
    "inventory_hints": [],
    "entity_reveals": [],
    "events_mentioned": [],
    "info_requests": [],
    "extraction_triggers": [],
    "scene_mood": "morne, fonctionnel",
    "narrator_notes": None,
}

# Exemple avec révélation d'identité PNJ
NARRATION_EXAMPLE_WITH_REVEAL = {
    "narrative_text": "La femme à la capuche relève la tête. Tu la reconnais — enfin, tu ne l'as jamais vraiment vue sans ses lunettes de soudure.\n\n— Justine, dit-elle en tendant la main. Justine Lépicier. On travaille dans le même secteur, techniquement.\n\nSon sourire est franc, sans arrière-pensée. Première personne sur cette station à ne pas avoir l'air de t'évaluer.\n\n*Ah. C'est donc elle, la technicienne dont parlait le superviseur.*",
    "time": {"new_time": "12h40", "ellipse": False, "ellipse_summary": None},
    "day_transition": None,
    "current_location": "Serres Hydro-7",
    "npcs_present": ["Justine Lépicier"],
    "suggested_actions": [
        "Discuter de votre travail commun",
        "Demander depuis quand elle est sur la station",
        "S'excuser et continuer sa route",
    ],
    "credit_delta": None,
    "inventory_hints": [],
    "entity_reveals": [
        {"entity_type": "character", "current_name": "La technicienne", "real_name": "Justine Lépicier"}
    ],
    "events_mentioned": [],
    "info_requests": ["Justine Lépicier"],
    "extraction_triggers": ["characters", "narrative_arcs"],
    "scene_mood": "ouvert, curieux",
    "narrator_notes": "First real meeting with Justine, known_by_protagonist now true",
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
    "credit_delta": None,
    "inventory_hints": [],
    "entity_reveals": [],
    "events_mentioned": [],
    "info_requests": [],
    "extraction_triggers": [],
    "scene_mood": "2-4 mots max",
    "narrator_notes": "Notes techniques courtes",
}


# =============================================================================
# EXTRACTION - Exemples par extracteur
# =============================================================================

EXTRACTION_PROTAGONIST_STATE_EXAMPLE = {
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
            "data": {
                "description": "Grande, cheveux courts",
                "mood": "anxieuse mais déterminée",
                "origin": "Colonie de Mars",
                "species": "human",
                "gender": "femme",
                "occupation": "ingénieure réseau",
            },
        }
    ],
    "entities_updated": [
        {
            "entity_ref": "La femme mystérieuse",
            "now_known": True,
            "real_name": "Dr. Sarah Chen",
            "changes": {
                "occupation": "Xénobiologiste renommée",
            },
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
                "level": 3,
                "context": "Collègues de travail",
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

EXTRACTION_ARCS_EXAMPLE = {
    "arcs_created": [
        {
            "title": "Les rumeurs de rachat",
            "domain": "professional",
            "description": "Marie mentionne des rumeurs sur un rachat de Symbiose par un investisseur externe.",
            "involved_entities": ["Marie", "Symbiose Tech"],
            "intensity": 3,
        }
    ],
    "arcs_resolved": [
        {
            "arc_title": "Promesse d'aide sur le rapport",
            "resolution": "Rapport terminé ensemble, Marie reconnaissante",
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
            "category": "tech",
            "description": "Carte magnétique bleue avec puce intégrée",
            "transportable": True,
            "stackable": False,
            "base_value": 50,
            "from_hint": "Carte d'accès temporaire",
        }
    ],
}
