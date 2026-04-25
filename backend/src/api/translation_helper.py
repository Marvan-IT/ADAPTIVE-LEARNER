"""Single-string translation helper for on-demand admin operations.

Provides ``translate_one_string`` — an async function that translates a short
English string into all 12 non-English locales supported by the platform.

Design notes:
- Uses ``asyncio.gather`` so all 12 language calls execute concurrently; wall
  time is approximately the slowest individual call (~1–2 s for gpt-4o-mini).
- Stores ``en_source_hash`` alongside the language translations so that a
  future run of ``translate_catalog.py`` can detect stale renames and skip rows
  that have already been translated.
- Graceful on total failure: returns ``{}`` so callers can continue with
  English-only display.
- Caller is responsible for wrapping in ``asyncio.timeout`` if a hard deadline
  is required (the ``rename_section`` handler uses 10 s).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

import openai

from api.prompts import LANGUAGE_NAMES
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL_MINI

logger = logging.getLogger(__name__)

# All non-English locale codes the platform supports.
_ALL_TARGET_LANGS: list[str] = [code for code in LANGUAGE_NAMES if code != "en"]

# Back-off delays (seconds) between successive retry attempts.
_RETRY_DELAYS: list[int] = [2, 4, 8, 16, 32]


def _sha1(text: str) -> str:
    """Return the SHA-1 hex digest of *text* encoded as UTF-8."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _build_system_prompt(lang: str) -> str:
    """Return a concise system prompt for translating a single string into *lang*."""
    lang_name = LANGUAGE_NAMES.get(lang, lang)
    return (
        f"You are a mathematics education translator. "
        f"Translate each item in the JSON array into {lang_name}. "
        f"Return a JSON array of the same length in the same order. "
        f"Keep mathematical notation ($...$) and proper nouns unchanged. "
        f"Do NOT add explanations."
    )


async def _call_llm_once(
    client: openai.AsyncOpenAI,
    text: str,
    lang: str,
) -> str:
    """Send a single OpenAI request translating *text* into *lang*.

    Returns the translated string.
    Raises ``ValueError`` when the response list length does not match (1).
    Raises openai / httpx exceptions on network / API errors.
    """
    payload = json.dumps([text], ensure_ascii=False)
    system_prompt = _build_system_prompt(lang)

    resp = await client.chat.completions.create(
        model=OPENAI_MODEL_MINI,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": payload},
        ],
        max_tokens=256,
        temperature=0.1,
    )
    raw = (resp.choices[0].message.content or "").strip()
    # Strip markdown code fences if the model wraps the response.
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or len(parsed) != 1:
        got = len(parsed) if isinstance(parsed, list) else -1
        raise ValueError(
            f"LLM returned {got} items for lang={lang}, expected 1"
        )
    return str(parsed[0])


async def _translate_one_lang_with_retry(
    client: openai.AsyncOpenAI,
    text: str,
    lang: str,
) -> str | None:
    """Translate *text* into *lang* with up to 5 retry attempts.

    Returns the translated string on success, or ``None`` after all retries are
    exhausted.  Logs a warning on final failure.
    """
    last_exc: Exception | None = None

    for attempt_idx in range(len(_RETRY_DELAYS) + 1):  # attempts 0..5
        if attempt_idx > 0:
            delay = _RETRY_DELAYS[attempt_idx - 1]
            logger.warning(
                "[translation_helper] retry %d/%d for lang=%s after %ds (prev: %s)",
                attempt_idx, len(_RETRY_DELAYS), lang, delay, last_exc,
            )
            await asyncio.sleep(delay)

        try:
            return await _call_llm_once(client, text, lang)
        except (
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.RateLimitError,
        ) as exc:
            last_exc = exc
        except ValueError as exc:
            # Length mismatch — worth retrying
            last_exc = exc
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    logger.warning(
        "[translation_helper] all retries exhausted for lang=%s text=%r: %s",
        lang, text[:60], last_exc,
    )
    return None


async def translate_one_string(
    text: str,
    target_langs: list[str] | None = None,
    openai_client: openai.AsyncOpenAI | None = None,
) -> dict[str, str]:
    """Translate *text* into all 12 non-English locales (or *target_langs* if given).

    Returns a dict with one entry per language code plus an ``en_source_hash``
    key (SHA-1 of the English source) for staleness detection.  Any language
    whose translation fails is omitted from the dict.  On total failure (empty
    string input, exception from gather) returns ``{}``.

    Caller should wrap in ``asyncio.timeout(10.0)`` if a hard deadline is needed.

    Args:
        text: The English string to translate.
        target_langs: List of BCP-47 language codes to translate into.  Defaults
            to all 12 non-English codes supported by the platform.
        openai_client: An existing ``AsyncOpenAI`` client.  If ``None``, a new
            client is instantiated from ``config.OPENAI_API_KEY`` /
            ``config.OPENAI_BASE_URL``.

    Returns:
        Dict mapping language code → translated string, plus ``en_source_hash``.
        May be empty on total failure.
    """
    if not text or not text.strip():
        return {}

    langs = target_langs if target_langs is not None else _ALL_TARGET_LANGS

    client = openai_client or openai.AsyncOpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
    )

    try:
        results: list[str | None] = await asyncio.gather(
            *[_translate_one_lang_with_retry(client, text, lang) for lang in langs],
            return_exceptions=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[translation_helper] asyncio.gather failed for text=%r: %s",
            text[:60], exc,
        )
        return {}

    out: dict[str, str] = {"en_source_hash": _sha1(text)}
    for lang, translated in zip(langs, results):
        if translated is not None:
            out[lang] = translated
        else:
            logger.warning(
                "[translation_helper] lang=%s omitted from result (translation returned None)",
                lang,
            )

    return out
