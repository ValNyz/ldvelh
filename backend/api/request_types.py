"""Bounded request field types, sized to the DB columns they end up in.
A test (tests/test_api_input_validation.py) reads the column widths from information_schema
and asserts these bounds equal them.

Unlike schema/core.py (which truncates LLM output), a client value over the bound is
rejected: the RequestValidationError handler (api/http_errors.py) answers 422 in French.
"""

import json
import re
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

# games.name varchar(255), users.email varchar(255), users.display_name varchar(100)
GameName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
DisplayName = Annotated[str, StringConstraints(max_length=100)]

# Shape check only (the verification email proves the address). email-validator is not
# a dependency and would pull dnspython for no extra guarantee.
_EMAIL_SHAPE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _check_email(value: str) -> str:
    if not _EMAIL_SHAPE.fullmatch(value):
        raise ValueError("adresse e-mail invalide")
    return value


Email = Annotated[str, StringConstraints(max_length=255), AfterValidator(_check_email)]

# One encrypted-at-rest key per provider; real keys are well under 512 characters.
API_KEY_MAX_LENGTH = 512
API_KEYS_MAX_ENTRIES = 10
# Whole preferences patch, serialized: a few UI settings, never a document store.
PREFERENCES_MAX_BYTES = 16_384
PREFERENCES_MAX_KEYS = 50


def check_preferences(value: dict) -> dict:
    """Cap the size of a preferences patch and require api_keys to be {provider: key|null}."""
    keys = value.get("api_keys")
    if keys is not None:
        if not isinstance(keys, dict):
            raise ValueError("api_keys doit être un objet {fournisseur: clé}")
        if len(keys) > API_KEYS_MAX_ENTRIES:
            raise ValueError("trop de clés d'API")
        for key in keys.values():
            if key is not None and (not isinstance(key, str) or len(key) > API_KEY_MAX_LENGTH):
                raise ValueError("clé d'API invalide ou trop longue")
    return check_preferences_size(value)


def check_preferences_size(value: dict) -> dict:
    """Size cap, applied to a patch and again to the merged result stored in the DB."""
    try:
        size = len(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        raise ValueError("préférences invalides") from None
    if len(value) > PREFERENCES_MAX_KEYS:
        raise ValueError(f"trop de préférences (max {PREFERENCES_MAX_KEYS})")
    if size > PREFERENCES_MAX_BYTES:
        raise ValueError(f"préférences trop volumineuses (max {PREFERENCES_MAX_BYTES} caractères)")
    return value


Preferences = Annotated[dict, AfterValidator(check_preferences)]


# Wizard form parts (world_config, character_data, manual_entities): sent to /world/enhance
# and with __INIT__, then stored on the game until its world exists (#88). Far above what
# the wizard produces: an oversized form is refused before any LLM call or write.
WIZARD_FORM_MAX_CHARS = 20_000
WIZARD_ENTITIES_MAX_PER_KIND = 20


def check_wizard_form_size(value: dict) -> dict:
    try:
        size = len(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        raise ValueError("formulaire invalide") from None
    if size > WIZARD_FORM_MAX_CHARS:
        raise ValueError(f"formulaire trop long (max {WIZARD_FORM_MAX_CHARS} caractères)")
    return value


def check_manual_entities(value: dict) -> dict:
    for items in value.values():
        if isinstance(items, list) and len(items) > WIZARD_ENTITIES_MAX_PER_KIND:
            raise ValueError(f"trop d'entités d'un même type (max {WIZARD_ENTITIES_MAX_PER_KIND})")
    return check_wizard_form_size(value)


WizardPart = Annotated[dict, AfterValidator(check_wizard_form_size)]
ManualEntities = Annotated[dict, AfterValidator(check_manual_entities)]
