"""
LDVELH - JSON Utilities
Fonctions centralisées pour le parsing et la réparation de JSON
"""

import json
from typing import Any


def parse_json_response(content: str) -> dict | None:
    """
    Parse une réponse JSON, en gérant les cas courants :
    - Backticks markdown (```json ... ```)
    - Espaces en début/fin
    - JSON tronqué (tente une réparation)

    Returns:
        dict parsé ou None si échec
    """
    content = clean_json_string(content)

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"[JSON] Erreur parsing: {e}")
        print(f"[JSON] Contenu (500 premiers chars): {content[:500]}")
        return try_repair_json(content)


def clean_json_string(content: str) -> str:
    """
    Nettoie une string JSON des artefacts courants.
    - Retire les backticks markdown
    - Strip les espaces
    """
    content = content.strip()

    # Retirer les backticks markdown
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]

    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


def try_repair_json(content: str) -> dict | None:
    """
    Tente de réparer un JSON tronqué en fermant les brackets ouverts.
    Utile pour le streaming où le JSON peut être coupé.

    Returns:
        dict parsé ou None si la réparation échoue
    """
    brackets = []
    in_string = False
    escape = False

    for char in content:
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            brackets.append("}" if char == "{" else "]")
        elif char in "}]":
            if brackets and brackets[-1] == char:
                brackets.pop()

    # Fermer les brackets ouverts
    repaired = content + "".join(reversed(brackets))

    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        return None


def safe_json_dumps(data: Any, default: str = "{}") -> str:
    """
    Sérialise en JSON de façon sûre.

    Returns:
        JSON string ou default si échec
    """
    try:
        return json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        return default
