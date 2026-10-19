"""
LDVELH - Entity field bounds

One bounded type per varchar column of the characters, locations and organizations
tables: min(product limit on LLM output, column width). The product limits of
schema/core.py are all at or below their column, so each type is the core type. The
column widths live in the DB only (db/migrations); a test reads them from
information_schema and asserts every bound <= its column. Both the creation models
(entities.py) and the update models (entity_changes.py) use these types, so the two paths
cannot drift. `text` columns have no width: the models keep their product caps.
"""

from .core import Label, Mood, Name, ShortText, Tag

# characters
CharacterDescriptor = Name
CharacterSpecies = Tag
CharacterGender = Label
CharacterPronouns = Label
CharacterAge = Label
CharacterMood = Mood
CharacterOccupation = Name
CharacterOrigin = Name

# locations
LocationType = Tag
LocationSector = Tag
LocationAtmosphere = Mood
LocationTypicalCrowd = ShortText
LocationOperatingHours = Tag
LocationPriceRange = Tag

# organizations
OrganizationType = Tag
OrganizationDomain = Tag
OrganizationSize = Tag
OrganizationReputation = ShortText
