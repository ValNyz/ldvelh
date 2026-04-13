"""
LDVELH - JSON Utilities
Fonctions centralisées pour le parsing et la réparation de JSON
"""

import ast
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def parse_json_response(content: str) -> dict | None:
    """
    Parse une réponse JSON, en gérant les cas courants :
    - Backticks markdown (```json ... ```)
    - Espaces en début/fin
    - Unescaped double quotes inside string values
    - JSON tronqué (tente une réparation)

    Returns:
        dict parsé ou None si échec
    """
    content = clean_json_string(content)

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        # Try fixing unescaped quotes inside string values (common with Hermes/Qwen)
        fixed = _fix_unescaped_quotes(content)
        if fixed != content:
            try:
                result = json.loads(fixed)
                logger.info("[JSON] Fixed unescaped quotes in string values")
                return result
            except json.JSONDecodeError:
                pass

        # Try Python literal eval (handles single quotes, True/False/None from Mistral)
        py_result = _try_python_literal(content)
        if py_result is not None:
            return py_result

        logger.warning(f"[JSON] Parse error: {e}")
        logger.debug(f"[JSON] First 500 chars: {content[:500]}")
        logger.debug(f"[JSON] Last 200 chars: ...{content[-200:]}")
        return try_repair_json(content)


def clean_json_string(content: str) -> str:
    """
    Nettoie une string JSON des artefacts courants.
    - Retire les backticks markdown
    - Replace NaN/Infinity with null (common LLM output)
    - Remove trailing commas before } or ]
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

    content = content.strip()

    # Escape literal control characters inside JSON strings (common with Mistral/Qwen)
    content = _escape_control_chars_in_strings(content)

    # Replace NaN/Infinity outside of strings (common with non-Claude models)
    content = _replace_invalid_values(content)

    # Remove trailing commas before } or ] (outside strings)
    content = re.sub(r',\s*([}\]])', r'\1', content)

    return content


def _fix_unescaped_quotes(content: str) -> str:
    """Fix unescaped double quotes inside JSON string values.

    Hermes/Qwen models output things like: "Elle a dit "non" et "risqué"."
    which should be: "Elle a dit \"non\" et \"risqué\"."

    Strategy: walk the string tracking in_string state. When inside a string
    and we hit a '"', look at the next non-whitespace char. If it's a
    structural JSON token (,  }  ]  :) or end-of-string, treat it as a real
    closing quote. Otherwise escape it.
    """
    result = []
    in_string = False
    escape = False
    i = 0
    length = len(content)

    while i < length:
        char = content[i]

        if escape:
            result.append(char)
            escape = False
            i += 1
            continue

        if char == '\\' and in_string:
            result.append(char)
            escape = True
            i += 1
            continue

        if char == '"':
            if not in_string:
                # Opening a string
                in_string = True
                result.append(char)
                i += 1
                continue

            # We're inside a string and hit a quote — is it closing or content?
            # Look at the next non-whitespace character
            j = i + 1
            while j < length and content[j] in ' \t\r\n':
                j += 1

            if j >= length:
                # End of content — treat as closing quote
                in_string = False
                result.append(char)
            elif content[j] == '"':
                # Next char is another quote — likely unescaped quote in content
                # e.g. ..."text"", or ..."word""next"
                # Escape this one, let the next iteration handle the next quote
                result.append('\\"')
            elif content[j] in ',}]:':
                # Structural JSON follows — this is a real closing quote
                in_string = False
                result.append(char)
            else:
                # Non-structural follows — this quote is content, escape it
                result.append('\\"')

            i += 1
            continue

        result.append(char)
        i += 1

    return ''.join(result)


def _try_python_literal(content: str) -> dict | None:
    """Try parsing as Python dict literal (single quotes, True/False/None).

    Mistral sometimes outputs Python dict syntax instead of JSON.
    """
    try:
        result = ast.literal_eval(content)
        if isinstance(result, dict):
            logger.info("[JSON] Parsed as Python dict literal (single quotes/Python booleans)")
            return result
    except (ValueError, SyntaxError):
        pass
    return None


def _escape_control_chars_in_strings(content: str) -> str:
    """Escape literal newlines/tabs/control chars inside JSON string values.

    LLMs (especially Mistral) output real newlines inside JSON strings
    instead of \\n, which is invalid JSON.
    """
    result = []
    in_string = False
    escape = False

    for char in content:
        if escape:
            result.append(char)
            escape = False
            continue
        if char == '\\' and in_string:
            result.append(char)
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            result.append(char)
            continue

        if in_string:
            # Replace control characters with their JSON escape sequences
            if char == '\n':
                result.append('\\n')
            elif char == '\r':
                result.append('\\r')
            elif char == '\t':
                result.append('\\t')
            elif ord(char) < 0x20:
                result.append(f'\\u{ord(char):04x}')
            else:
                result.append(char)
        else:
            result.append(char)

    return ''.join(result)


def _replace_invalid_values(content: str) -> str:
    """Replace NaN, Infinity, -Infinity with null; strip leading + on numbers (outside strings)."""
    result = []
    in_string = False
    escape = False
    i = 0

    while i < len(content):
        char = content[i]
        if escape:
            result.append(char)
            escape = False
            i += 1
            continue
        if char == '\\' and in_string:
            result.append(char)
            escape = True
            i += 1
            continue
        if char == '"':
            in_string = not in_string
            result.append(char)
            i += 1
            continue
        if in_string:
            result.append(char)
            i += 1
            continue

        # Outside a string — strip leading + before numbers (invalid JSON, common LLM output)
        if char == '+' and i + 1 < len(content) and content[i + 1] in '0123456789':
            i += 1  # skip the +, digit will be appended next iteration
            continue

        # Outside a string — check for NaN, Infinity, -Infinity
        for pattern, replacement in [
            ('NaN', 'null'),
            ('-Infinity', 'null'),
            ('Infinity', 'null'),
        ]:
            if content[i:i + len(pattern)] == pattern:
                # Ensure it's not part of a longer word
                before = content[i - 1] if i > 0 else ' '
                after = content[i + len(pattern)] if i + len(pattern) < len(content) else ' '
                if not before.isalnum() and not after.isalnum():
                    result.append(replacement)
                    i += len(pattern)
                    break
        else:
            result.append(char)
            i += 1

    return ''.join(result)


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
        logger.info("[JSON] Repair: closing unterminated string")

    # 3. Fermer les brackets ouverts
    if brackets:
        repair += "".join(reversed(brackets))
        logger.info(f"[JSON] Repair: closing {len(brackets)} brackets")

    repaired = content + repair

    try:
        result = json.loads(repaired)
        logger.info("[JSON] Repair successful")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"[JSON] Simple repair failed: {e}")
        # Tenter une stratégie de troncature
        return try_truncate_json(content)


def try_truncate_json(content: str) -> dict | None:
    """
    Stratégie alternative : tronquer jusqu'au dernier point valide.
    Cherche un point de coupure propre en reculant dans le contenu.
    """
    logger.info("[JSON] Attempting truncation...")

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
                logger.info(f"[JSON] Truncation successful at position {end_pos}")
                return result
            except json.JSONDecodeError:
                continue

    logger.error("[JSON] All repair attempts failed")
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
