"""
Custom-interest validation service.

Validation pipeline (cheapest-first, short-circuit on failure):
  1. Format check  — trim, length bounds, Unicode-letter regex.
  2. Dedupe check  — case-insensitive against predefined IDs and existing custom interests.
  3. Limit check   — enforces CUSTOM_INTERESTS_MAX cap.
  4. LLM semantic check — cheap model, JSON response_format, fail-closed.
  5. In-process TTL cache — keyed on (normalized.lower(), language), avoids re-billing.

Reason codes are stable English strings; the frontend maps them to localised messages.
"""

import logging
import re
import time
from dataclasses import dataclass

from openai import AsyncOpenAI

from config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    INTEREST_VALIDATOR_MODEL,
    INTEREST_MIN_LENGTH,
    INTEREST_MAX_LENGTH,
    CUSTOM_INTERESTS_MAX,
    INTEREST_VALIDATOR_CACHE_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

# ── In-process TTL cache ────────────────────────────────────────────────────
# Structure: {(normalized_lower, language): (ok: bool, expiry_ts: float)}
# Only positive (ok=True) LLM results and confirmed-bad (ok=False, "unrecognized")
# results are cached.  "validator_unavailable" is transient and must NOT be cached.
_cache: dict[tuple[str, str], tuple[bool, float]] = {}


def _cache_get(key: tuple[str, str]) -> bool | None:
    """Return cached ok value, or None if missing/expired."""
    entry = _cache.get(key)
    if entry is None:
        return None
    ok, expiry = entry
    if time.monotonic() > expiry:
        del _cache[key]
        return None
    return ok


def _cache_set(key: tuple[str, str], ok: bool) -> None:
    """Store result in the TTL cache."""
    _cache[key] = (ok, time.monotonic() + INTEREST_VALIDATOR_CACHE_TTL_SECONDS)


# ── Format regex ───────────────────────────────────────────────────────────
# Matches Unicode letters with optional single spaces or hyphens between words.
# No leading/trailing separator characters allowed.
_FORMAT_RE = re.compile(
    r"^[^\W\d_]+(?:[\s\-][^\W\d_]+)*$",
    re.UNICODE,
)


# ── Return type ────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    ok: bool
    reason: str | None  # stable reason code (not translated); None when ok=True
    normalized: str     # trimmed text; always present regardless of ok


# ── Public validator ────────────────────────────────────────────────────────

async def validate_custom_interest(
    text: str,
    language: str,
    existing_custom: list[str],
    predefined_ids: list[str],
) -> ValidationResult:
    """
    Validate a single custom interest text.

    Args:
        text:           Raw user input.
        language:       Preferred language code (e.g. "en", "ar") for LLM error message locale.
        existing_custom: Student's current custom_interests list (server-side truth).
        predefined_ids:  Canonical predefined interest IDs (e.g. ["Sports", "Gaming", ...]).

    Returns:
        ValidationResult with ok, reason code, and normalized text.
    """

    # ── Stage 1: Format check ───────────────────────────────────────────────
    normalized = text.strip()

    if len(normalized) < INTEREST_MIN_LENGTH:
        return ValidationResult(ok=False, reason="too_short", normalized=normalized)

    if len(normalized) > INTEREST_MAX_LENGTH:
        return ValidationResult(ok=False, reason="too_long", normalized=normalized)

    if not _FORMAT_RE.match(normalized):
        return ValidationResult(ok=False, reason="invalid_chars", normalized=normalized)

    # ── Stage 2: Dedupe check ────────────────────────────────────────────────
    normalized_lower = normalized.lower()

    if any(pid.lower() == normalized_lower for pid in predefined_ids):
        return ValidationResult(ok=False, reason="duplicate_predefined", normalized=normalized)

    if any(ec.lower() == normalized_lower for ec in existing_custom):
        return ValidationResult(ok=False, reason="duplicate_custom", normalized=normalized)

    # ── Stage 3: Limit check ─────────────────────────────────────────────────
    if len(existing_custom) >= CUSTOM_INTERESTS_MAX:
        return ValidationResult(ok=False, reason="limit_reached", normalized=normalized)

    # ── Stage 4: LLM semantic check (cache first) ───────────────────────────
    cache_key = (normalized_lower, language)
    cached_ok = _cache_get(cache_key)
    if cached_ok is not None:
        if cached_ok:
            return ValidationResult(ok=True, reason=None, normalized=normalized)
        else:
            return ValidationResult(ok=False, reason="unrecognized", normalized=normalized)

    llm_ok = await _llm_check(normalized, language)
    if llm_ok is None:
        # Transient failure — fail closed, do not cache
        return ValidationResult(ok=False, reason="validator_unavailable", normalized=normalized)

    # Cache the definitive LLM result (both True and False)
    _cache_set(cache_key, llm_ok)

    if llm_ok:
        return ValidationResult(ok=True, reason=None, normalized=normalized)
    return ValidationResult(ok=False, reason="unrecognized", normalized=normalized)


# ── LLM helper ───────────────────────────────────────────────────────────────

async def _llm_check(text: str, language: str) -> bool | None:
    """
    Ask the LLM whether the text is a recognizable personal interest.

    Returns:
        True   — recognized interest
        False  — not a recognizable interest (gibberish, profanity, etc.)
        None   — transient failure (LLM unavailable, bad JSON, timeout)
    """
    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    system_msg = (
        "You are a strict validator. Given a single word or short phrase in any language, "
        "decide whether it names a real personal interest, hobby, subject, or topic a student "
        "could care about (e.g. sports, cooking, fractals, anime, music, history). "
        "Reject random keyboard mashing, gibberish, profanity, brand names without obvious "
        "interest context, and empty concepts. "
        f'Respond ONLY with JSON: {{"ok": boolean, "reason": string}}. '
        f'The reason should be a short human-friendly sentence in language="{language}".'
    )
    user_msg = text

    try:
        response = await client.chat.completions.create(
            model=INTEREST_VALIDATOR_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            max_tokens=80,
            temperature=0.0,
            timeout=10.0,
        )
        raw = (response.choices[0].message.content or "").strip()
        import json as _json
        parsed = _json.loads(raw)
        ok = parsed.get("ok")
        if not isinstance(ok, bool):
            logger.warning(
                "[interest_validator] llm_bad_ok_type: text=%r raw=%r", text, raw
            )
            return None
        if not ok:
            llm_reason = parsed.get("reason", "")
            logger.info(
                "[interest_validator] llm_rejected: text=%r reason=%r", text, llm_reason
            )
        return bool(ok)

    except Exception as exc:
        logger.warning(
            "[interest_validator] llm_error: text=%r error=%s", text, exc
        )
        return None
