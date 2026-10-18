"""
LDVELH - Entity column widths and field bounds

COLUMN_WIDTHS is the source of truth for the varchar widths of the characters, locations
and organizations tables (db/migrations/20260413000000_baseline.sql; no later migration
changes them; a test checks it against information_schema).

Each bounded type below is min(product limit on LLM output, column width): the product
limits of schema/core.py are all tighter than their columns, so each type is the core
type, and a test asserts bound <= COLUMN_WIDTHS for every field. Both the creation models
(entities.py) and the update models (entity_changes.py) use these types, so the two paths
cannot drift. `text` columns have no width: the models keep their product caps.
"""

from .core import Label, Mood, Name, ShortText, Tag

COLUMN_WIDTHS: dict[tuple[str, str], int] = {
    ("characters", "unknown_name"): 255,
    ("characters", "species"): 100,
    ("characters", "gender"): 50,
    ("characters", "pronouns"): 30,
    ("characters", "age"): 30,
    ("characters", "mood"): 255,
    ("characters", "occupation"): 255,
    ("characters", "origin"): 255,
    ("locations", "location_type"): 100,
    ("locations", "sector"): 255,
    ("locations", "atmosphere"): 255,
    ("locations", "typical_crowd"): 255,
    ("locations", "operating_hours"): 50,
    ("locations", "price_range"): 50,
    ("organizations", "org_type"): 100,
    ("organizations", "domain"): 255,
    ("organizations", "size"): 50,
    ("organizations", "reputation"): 255,
}

# characters            bound (product limit) <= column width
CharacterUnknownName = Name      # 100 <= 255
CharacterSpecies = Tag           # 50 <= 100
CharacterGender = Label          # 30 <= 50
CharacterPronouns = Label        # 30 <= 30
CharacterAge = Label             # 30 <= 30
CharacterMood = Mood             # 80 <= 255
CharacterOccupation = Name       # 100 <= 255
CharacterOrigin = Name           # 100 <= 255

# locations
LocationType = Tag               # 50 <= 100
LocationSector = Tag             # 50 <= 255
LocationAtmosphere = Mood        # 80 <= 255
LocationTypicalCrowd = ShortText  # 200 <= 255
LocationOperatingHours = Tag     # 50 <= 50
LocationPriceRange = Tag         # 50 <= 50

# organizations
OrganizationType = Tag           # 50 <= 100
OrganizationDomain = Tag         # 50 <= 255
OrganizationSize = Tag           # 50 <= 50
OrganizationReputation = ShortText  # 200 <= 255
