"""
LDVELH - Engine Data
Canonical skill/attribute lists per engine+genre.
Used by world gen prompts and character creation validation.
"""

# =============================================================================
# FATE CORE — Skills (French, based on official Fate Core SRD)
# =============================================================================

FATE_SKILLS_BASE = [
    "Athlétisme",
    "Cambriolage",
    "Combat",
    "Commandement",
    "Conduite",
    "Contacts",
    "Discrétion",
    "Empathie",
    "Érudition",
    "Intimidation",
    "Investigation",
    "Métiers",
    "Perception",
    "Persuasion",
    "Physique",
    "Provocation",
    "Ressources",
    "Tir",
    "Tromperie",
    "Volonté",
]

FATE_SKILLS_BY_GENRE: dict[str, dict[str, list[str]]] = {
    "fantasy": {
        "add": ["Magie", "Équitation", "Survie"],
        "remove": [],
    },
    "sci-fi": {
        "add": ["Pilotage", "Technologie", "Piratage"],
        "remove": ["Équitation"],
    },
    "cthulhu": {
        "add": ["Occultisme", "Santé Mentale", "Langues Anciennes"],
        "remove": ["Commandement"],
    },
    "historical": {
        "add": ["Équitation", "Survie", "Artisanat"],
        "remove": ["Pilotage", "Technologie"],
    },
    "contemporary": {
        "add": ["Informatique", "Réseau Social"],
        "remove": [],
    },
}

# Fate Core difficulty ladder
FATE_DIFFICULTY_LADDER = {
    0: "Médiocre",
    1: "Moyen",
    2: "Correct",
    3: "Bon",
    4: "Excellent",
    5: "Superbe",
    6: "Fantastique",
    7: "Épique",
    8: "Légendaire",
}

# Fate aspect types
FATE_ASPECT_TYPES = ["high_concept", "trouble", "other"]

# Default skill pyramid (columns = skill cap)
# Cap +4: 1 at +4, 2 at +3, 3 at +2, 4 at +1
FATE_DEFAULT_PYRAMID = {4: 1, 3: 2, 2: 3, 1: 4}

# Max custom skills per game
FATE_MAX_CUSTOM_SKILLS = 3


# =============================================================================
# D6 SYSTEM — Attributes & Skills
# =============================================================================

D6_ATTRIBUTES = [
    "Dextérité",
    "Connaissance",
    "Mécanique",
    "Perception",
    "Force",
    "Technique",
]

D6_SKILLS_BASE: dict[str, list[str]] = {
    "Dextérité": [
        "Acrobaties",
        "Armes blanches",
        "Bagarre",
        "Corps à corps",
        "Esquive",
        "Lancer",
    ],
    "Connaissance": [
        "Bureaucratie",
        "Culture",
        "Droit",
        "Langues",
        "Sciences",
        "Stratégie",
    ],
    "Mécanique": [
        "Armurerie",
        "Démolition",
        "Premiers secours",
        "Réparation",
        "Sécurité",
    ],
    "Perception": [
        "Baratin",
        "Commandement",
        "Dissimulation",
        "Investigation",
        "Marchandage",
        "Recherche",
    ],
    "Force": [
        "Endurance",
        "Escalade",
        "Natation",
        "Soulever",
    ],
    "Technique": [
        "Informatique",
        "Médecine",
        "Navigation",
        "Programmation",
    ],
}

D6_SKILLS_BY_GENRE: dict[str, dict[str, dict[str, list[str]]]] = {
    "fantasy": {
        "add": {
            "Connaissance": ["Arcanes", "Herboristerie", "Théologie"],
            "Dextérité": ["Équitation", "Tir à l'arc"],
            "Force": ["Survie en milieu sauvage"],
        },
        "remove": {
            "Technique": ["Informatique", "Programmation"],
        },
    },
    "sci-fi": {
        "add": {
            "Dextérité": ["Blasters", "Pilotage"],
            "Technique": ["Astrogation", "Capteurs", "Droïdes"],
            "Mécanique": ["Transpondeurs"],
        },
        "remove": {},
    },
    "cthulhu": {
        "add": {
            "Connaissance": ["Occultisme", "Mythes de Cthulhu", "Archéologie"],
            "Perception": ["Psychologie"],
        },
        "remove": {
            "Technique": ["Programmation"],
        },
    },
    "contemporary": {
        "add": {
            "Technique": ["Réseau Social", "Conduite"],
            "Dextérité": ["Armes à feu"],
        },
        "remove": {},
    },
}

# D6 difficulty numbers
D6_DIFFICULTY_SCALE = {
    "very_easy": 5,
    "easy": 10,
    "moderate": 15,
    "difficult": 20,
    "very_difficult": 25,
    "heroic": 30,
    "legendary": 35,
}

# D6 starting attribute dice (18D to distribute across 6 attributes)
D6_STARTING_ATTRIBUTE_DICE = 18

# D6 starting skill dice (7D to distribute)
D6_STARTING_SKILL_DICE = 7

# D6 wound levels (ascending severity)
D6_WOUND_LEVELS = [
    "stunned",
    "wounded",
    "severely_wounded",
    "incapacitated",
    "mortally_wounded",
]

# Max custom skills per game
D6_MAX_CUSTOM_SKILLS = 3


# =============================================================================
# HELPERS
# =============================================================================


def get_fate_skills(genre: str | None = None) -> list[str]:
    """Get the full Fate skill list for a genre."""
    skills = list(FATE_SKILLS_BASE)
    if genre and genre in FATE_SKILLS_BY_GENRE:
        mods = FATE_SKILLS_BY_GENRE[genre]
        for s in mods.get("remove", []):
            if s in skills:
                skills.remove(s)
        skills.extend(mods.get("add", []))
    return sorted(skills)


def get_d6_skills(genre: str | None = None) -> dict[str, list[str]]:
    """Get the full D6 skill list (by attribute) for a genre."""
    skills = {attr: list(s) for attr, s in D6_SKILLS_BASE.items()}
    if genre and genre in D6_SKILLS_BY_GENRE:
        mods = D6_SKILLS_BY_GENRE[genre]
        for attr, to_remove in mods.get("remove", {}).items():
            if attr in skills:
                for s in to_remove:
                    if s in skills[attr]:
                        skills[attr].remove(s)
        for attr, to_add in mods.get("add", {}).items():
            if attr not in skills:
                skills[attr] = []
            skills[attr].extend(to_add)
    # Sort each attribute's skills
    return {attr: sorted(s) for attr, s in skills.items()}
