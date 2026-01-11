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
        print(f"[JSON] Contenu (200 derniers chars): ...{content[-200:]}")
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
    Tente de réparer un JSON tronqué.
    Gère :
    - Les strings non terminées (coupure au milieu d'une valeur string)
    - Les brackets non fermés ({, [)
    - Les backslashes orphelins en fin de string

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
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            brackets.append("}" if char == "{" else "]")
        elif char in "}]":
            if brackets and brackets[-1] == char:
                brackets.pop()

    # Construire la réparation
    repair = ""

    # 1. Si on termine sur un backslash, le retirer (échappement incomplet)
    if content.endswith("\\"):
        content = content[:-1]

    # 2. Si on est dans une string non terminée, la fermer
    if in_string:
        repair += '"'
        print("[JSON] Réparation: fermeture de string non terminée")

    # 3. Fermer les brackets ouverts
    if brackets:
        repair += "".join(reversed(brackets))
        print(f"[JSON] Réparation: fermeture de {len(brackets)} brackets")

    repaired = content + repair

    try:
        result = json.loads(repaired)
        print("[JSON] Réparation réussie!")
        return result
    except json.JSONDecodeError as e:
        print(f"[JSON] Échec réparation simple: {e}")
        # Tenter une stratégie de troncature
        return try_truncate_json(content)


def try_truncate_json(content: str) -> dict | None:
    """
    Stratégie alternative : tronquer jusqu'au dernier point valide.
    Cherche un point de coupure propre en reculant dans le contenu.
    """
    print("[JSON] Tentative de troncature...")

    # Chercher en reculant jusqu'à 1000 caractères
    for end_pos in range(len(content) - 1, max(0, len(content) - 1000), -1):
        truncated = content[:end_pos]

        # Analyser l'état des brackets et strings
        brackets = []
        in_string = False
        escape = False

        for char in truncated:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char in "{[":
                brackets.append("}" if char == "{" else "]")
            elif char in "}]":
                if brackets and brackets[-1] == char:
                    brackets.pop()

        # Si on n'est pas dans une string, tenter de fermer proprement
        if not in_string:
            repaired = truncated + "".join(reversed(brackets))
            try:
                result = json.loads(repaired)
                print(f"[JSON] Troncature réussie à la position {end_pos}")
                return result
            except json.JSONDecodeError:
                continue

    print("[JSON] Échec de toutes les tentatives de réparation")
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


def parse_json(value: Any) -> Any:
    """
    Parse JSON value if it's a string, otherwise return as-is.
    Handles PostgreSQL JSONB/JSON columns that may come as strings.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def parse_json_list(value: Any) -> list:
    """
    Parse JSON value and ensure it returns a list.
    """
    parsed = parse_json(value)
    if parsed is None:
        return []
    if isinstance(parsed, list):
        return parsed
    return [parsed]
