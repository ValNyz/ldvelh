"""
LDVELH - Entity column widths

One truncating type per varchar column of the characters, locations and organizations
tables (db/migrations/20260413000000_baseline.sql; no later migration changes them).
Both the creation models (entities.py) and the update models (entity_changes.py) use
these types, so a value written through either path always fits its column.
`text` columns have no width: the models keep their product caps (Text, ShortText).
"""

from typing import Annotated

from pydantic import BeforeValidator, StringConstraints

from .core import _truncate


Varchar30 = Annotated[str, BeforeValidator(_truncate(30)), StringConstraints(max_length=30)]
Varchar50 = Annotated[str, BeforeValidator(_truncate(50)), StringConstraints(max_length=50)]
Varchar100 = Annotated[str, BeforeValidator(_truncate(100)), StringConstraints(max_length=100)]
Varchar255 = Annotated[str, BeforeValidator(_truncate(255)), StringConstraints(max_length=255)]


# characters
CharacterUnknownName = Varchar255
CharacterSpecies = Varchar100
CharacterGender = Varchar50
CharacterPronouns = Varchar30
CharacterAge = Varchar30
CharacterMood = Varchar255
CharacterOccupation = Varchar255
CharacterOrigin = Varchar255

# locations
LocationType = Varchar100
LocationSector = Varchar255
LocationAtmosphere = Varchar255
LocationTypicalCrowd = Varchar255
LocationOperatingHours = Varchar50
LocationPriceRange = Varchar50

# organizations
OrganizationType = Varchar100
OrganizationDomain = Varchar255
OrganizationSize = Varchar50
OrganizationReputation = Varchar255
