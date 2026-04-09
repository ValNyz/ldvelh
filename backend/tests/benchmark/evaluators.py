"""
LLM judge helpers for semantic evaluation in benchmark tests.
Uses fresh LLM calls (Haiku) to evaluate narrative quality, compliance, etc.
"""

from __future__ import annotations

import logging

from services.llm_providers import get_provider, LLMProvider

logger = logging.getLogger(__name__)


class LLMJudge:
    """Wraps LLM evaluation calls for benchmark scoring.

    Uses the configured provider (defaults to wandb).
    Pass provider_name/api_key to override, or provide a pre-built provider.
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        provider_name: str = "wandb",
        api_key: str | None = None,
    ):
        self.provider = provider or get_provider(provider_name, api_key=api_key)

    async def judge_yes_no(self, question: str, context: str) -> bool:
        """Ask the LLM a yes/no question about a piece of text.

        Returns True if the answer is 'yes', False if 'no'.
        """
        prompt = (
            f"Based on the following text, answer this question with ONLY 'yes' or 'no'.\n\n"
            f"Question: {question}\n\n"
            f"Text:\n{context}\n\n"
            f"Answer (yes/no):"
        )
        try:
            result = await self.provider.complete(
                system_prompt="You are a precise evaluator. Answer only 'yes' or 'no'.",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=10,
            )
            if not result or not result.content:
                logger.warning("LLM judge returned empty — defaulting to False")
                return False
            answer = result.content.strip().lower()
            return answer.startswith("yes")
        except Exception as e:
            logger.warning(f"LLM judge error: {e} — defaulting to False")
            return False

    async def judge_entity_recall(
        self, context_prompt: str, entity_name: str
    ) -> int:
        """Judge whether an entity can be recalled from a narrator context.

        Returns:
            0 = not recalled at all
            1 = recalled with errors
            2 = recalled correctly
        """
        prompt = (
            f"Given the following narrator context, can you identify and describe "
            f"the entity named '{entity_name}'?\n\n"
            f"Context:\n{context_prompt}\n\n"
            f"Instructions: If {entity_name} appears in the context, describe them briefly. "
            f"If they don't appear, say 'NOT FOUND'.\n"
            f"Then rate your confidence: EXACT (name and details match), "
            f"PARTIAL (name found but details unclear), or ABSENT (not found)."
        )
        try:
            result = await self.provider.complete(
                system_prompt="You are evaluating entity recall from a game context.",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
            )
            if not result or not result.content:
                return 0
            text = result.content.upper()
            if "EXACT" in text:
                return 2
            if "PARTIAL" in text:
                return 1
            return 0
        except Exception as e:
            logger.warning(f"LLM judge error: {e}")
            return 0

    async def judge_score(self, question: str, context: str) -> int:
        """Ask the LLM to rate something on a 0-5 scale.

        Returns the score (0-5), or 0 on error.
        """
        prompt = (
            f"Based on the following text, answer this question with ONLY a single number from 0 to 5.\n"
            f"0 = not at all, 5 = perfectly.\n\n"
            f"Question: {question}\n\n"
            f"Text:\n{context}\n\n"
            f"Score (0-5):"
        )
        try:
            result = await self.provider.complete(
                system_prompt="You are a precise evaluator. Answer only with a single digit 0-5.",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=10,
            )
            if not result or not result.content:
                return 0
            for c in result.content.strip():
                if c.isdigit():
                    return min(int(c), 5)
            return 0
        except Exception as e:
            logger.warning(f"LLM judge score error: {e}")
            return 0

    async def judge_names_present(self, narrative: str, names: list[str]) -> dict:
        """Check which entity names from a list appear in the narrative.

        Uses both exact string match and LLM semantic match.
        Returns dict with found/missing names and coverage ratio.
        """
        narrative_lower = narrative.lower()
        found = [n for n in names if n.lower() in narrative_lower]
        missing = [n for n in names if n.lower() not in narrative_lower]

        # For missing names, check with LLM if they're referenced indirectly
        semantically_found = []
        for name in missing[:3]:  # Limit LLM calls
            is_ref = await self.judge_yes_no(
                f"Is the character '{name}' mentioned, referenced, or described in this text "
                f"(even indirectly, by role, title, or description)?",
                narrative,
            )
            if is_ref:
                semantically_found.append(name)

        all_found = found + semantically_found
        return {
            "found": all_found,
            "missing": [n for n in names if n not in all_found],
            "coverage": len(all_found) / len(names) if names else 1.0,
        }

    async def judge_compliance(
        self, narrative_text: str, expected_outcome: str
    ) -> bool:
        """Judge whether a narrative respects a mechanical outcome.

        Args:
            narrative_text: The narrator's response
            expected_outcome: "failure", "success", "tie", "success_with_style"

        Returns True if the narrative is compliant with the expected outcome.
        """
        outcome_descriptions = {
            "failure": "a clear failure — the action did NOT succeed",
            "success": "a success — the action succeeded",
            "tie": "a partial or costly result — success at a price or barely making it",
            "success_with_style": "an emphatic, impressive success",
        }
        desc = outcome_descriptions.get(expected_outcome, expected_outcome)
        question = (
            f"Does the following narrative describe {desc}? "
            f"Answer 'yes' if the narrative matches, 'no' if it contradicts."
        )
        return await self.judge_yes_no(question, narrative_text)


def keyword_scan(text: str, positive_keywords: list[str], negative_keywords: list[str]) -> dict:
    """Scan text for positive and negative keyword matches.

    Returns dict with counts and matched keywords.
    """
    text_lower = text.lower()
    pos_matches = [kw for kw in positive_keywords if kw.lower() in text_lower]
    neg_matches = [kw for kw in negative_keywords if kw.lower() in text_lower]
    return {
        "positive_count": len(pos_matches),
        "negative_count": len(neg_matches),
        "positive_matches": pos_matches,
        "negative_matches": neg_matches,
    }


# Common keyword sets for French narrative evaluation
SUCCESS_KEYWORDS_FR = [
    "réussit", "parvient", "s'ouvre", "fonctionne", "succès",
    "brillamment", "parfaitement", "sans difficulté", "avec brio",
]

FAILURE_KEYWORDS_FR = [
    "échoue", "rate", "manque", "impossible", "refuse",
    "ne parvient pas", "ne fonctionne pas", "bloqué", "coincé",
]

PARTIAL_KEYWORDS_FR = [
    "difficilement", "de justesse", "à peine", "mais", "cependant",
    "malgré", "au prix de", "non sans mal",
]
