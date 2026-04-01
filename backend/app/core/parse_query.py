from __future__ import annotations

import json
import logging
import re
from typing import Optional

from app.core.ai_client import call_ai

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a movie query parser. "
    "Extract filters from any movie-related query in ANY language (Telugu, Hindi, Tamil, etc.). "
    "IMPORTANT: Always return field values in ENGLISH regardless of input language. "
    "For example: if input is in Telugu, still return genres in English like 'action', languages in English like 'Telugu'. "
    "Return ONLY valid JSON with these optional fields: "
    "genres (list of English genre names like action/comedy/romance/thriller/drama/horror), "
    "languages (list of English language names like Telugu/Tamil/Hindi/Malayalam/English/Korean), "
    "mood (string in English like feel-good/romantic/thrilling/scary/inspiring), "
    "era_start (int year), era_end (int year), min_rating (float 0-10), "
    "similar_to (movie title in original language is ok), "
    "keywords (list), dubbed (bool), cast (list of names), director (string name). "
    "No explanation, just JSON."
)


async def parse_query(query: str) -> dict:
    """Parse a natural-language movie query into a structured filter dict.

    Sends *query* to the AI fallback chain (Groq → Gemini → OpenRouter) with a
    strict system prompt that constrains the model to return only JSON.  The raw
    response is cleaned and parsed; any failure returns an empty dict so the
    caller can still attempt an unfiltered recommendation.

    Args:
        query: A free-form, possibly multilingual movie request such as
               "Telugu action movies like RRR" or "90s horror with good ratings".

    Returns:
        A dict containing zero or more of the following optional keys:

        - genres       (list[str])   e.g. ["action", "thriller"]
        - languages    (list[str])   e.g. ["Telugu", "Hindi"]
        - mood         (str)         e.g. "feel-good"
        - era_start    (int)         earliest release year, e.g. 1990
        - era_end      (int)         latest  release year, e.g. 1999
        - min_rating   (float)       minimum TMDB/IMDb rating, e.g. 7.5
        - similar_to   (str)         reference movie title, e.g. "RRR"
        - keywords     (list[str])   e.g. ["heist", "time travel"]
        - dubbed       (bool)        True if the user wants a dubbed version
        - cast         (list[str])   actor names, e.g. ["Prabhas"]
        - director     (str)         director name, e.g. "S. S. Rajamouli"

        Returns {} if the AI call fails or the response cannot be parsed.

    Example:
        >>> filters = await parse_query("Telugu action movies like RRR")
        >>> # {"genres": ["action"], "languages": ["Telugu"], "similar_to": "RRR"}
    """
    logger.info("[parse_query] Parsing query: %r", query)

    raw = await call_ai(prompt=query, system=_SYSTEM_PROMPT)

    if not raw or raw.strip() == "{}":
        logger.warning("[parse_query] AI returned empty/fallback response")
        return {}

    cleaned = _strip_markdown_fences(raw)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Second attempt: extract the first {...} block in case the model
        # prepended/appended any stray text despite the strict system prompt.
        extracted = _extract_first_json_object(cleaned)
        if extracted is None:
            logger.warning(
                "[parse_query] Could not parse AI response as JSON: %r", raw[:200]
            )
            return {}
        try:
            parsed = json.loads(extracted)
        except json.JSONDecodeError:
            logger.warning(
                "[parse_query] Second-pass JSON parse also failed: %r", extracted[:200]
            )
            return {}

    if not isinstance(parsed, dict):
        logger.warning("[parse_query] Parsed value is not a dict: %r", parsed)
        return {}

    result = _validate_fields(parsed)
    logger.info("[parse_query] Parsed filters: %s", result)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers the model may add."""
    text = text.strip()
    # Remove opening fence (```json or ```)
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    # Remove closing fence
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_first_json_object(text: str) -> Optional[str]:
    """Return the substring spanning the first top-level { ... } block."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


_ALLOWED_FIELDS: dict = {
    "genres":     list,
    "languages":  list,
    "mood":       str,
    "era_start":  int,
    "era_end":    int,
    "min_rating": (int, float),
    "similar_to": str,
    "keywords":   list,
    "dubbed":     bool,
    "cast":       list,
    "director":   str,
}


def _validate_fields(data: dict) -> dict:
    """Keep only recognised fields whose values have the expected type."""
    result: dict = {}
    for field, expected_type in _ALLOWED_FIELDS.items():
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, expected_type):
            logger.debug(
                "[parse_query] Dropping field %r — expected %s, got %s",
                field, expected_type, type(value).__name__,
            )
            continue
        # Coerce numeric fields so era_start/era_end are always int
        if field in ("era_start", "era_end"):
            value = int(value)
        if field == "min_rating":
            value = float(value)
        result[field] = value
    return result