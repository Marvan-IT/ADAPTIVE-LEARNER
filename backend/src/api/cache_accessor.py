"""
CacheAccessor — per-language slice management for TeachingSession.presentation_text.

presentation_text stores a JSON string in the following shape:

    {
        "cache_version": 3,
        "by_language": {
            "en": {"presentation": "...", "cards": [...], "concepts_queue": [...],
                   "concepts_covered": [...], ...},
            "ml": {"presentation": "...", "cards": [...], "concepts_queue": [...],
                   "concepts_covered": [...], ...}
        }
    }

Legacy (flat) shape is transparently upgraded on first read:

    {"cache_version": 3, "cards": [...], "concepts_queue": [...], ...}

This module is the ONLY place that reads or writes session.presentation_text as JSON.
All other application code must go through CacheAccessor.
"""

import json
import logging

logger = logging.getLogger(__name__)

# LRU cap: max language slices stored per session.
_CACHE_MAX_LANGUAGES = 5
# Hard size cap per presentation_text row (bytes, UTF-8 encoded).
_CACHE_MAX_BYTES = 512 * 1024  # 512 KB


def _try_parse(raw: str) -> dict | None:
    """Attempt JSON parse with json-repair fallback. Returns None on total failure."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        from json_repair import repair_json  # project dependency
        return json.loads(repair_json(raw))
    except Exception:
        return None


class CacheAccessor:
    """
    Read/write per-language slices of TeachingSession.presentation_text.

    Thread-safety: each HTTP request owns its own session object — no shared state.

    Usage pattern:
        cache = CacheAccessor(session.presentation_text, language=student.preferred_language)
        sl = cache.get_slice()          # dict; never None
        sl["cards"].append(new_card)
        cache.set_slice(sl)
        session.presentation_text = cache.to_json()
    """

    def __init__(self, raw: str | None, language: str) -> None:
        """
        Parse raw JSON (or default to empty), normalise to new by_language shape.

        Args:
            raw: The current value of session.presentation_text (may be None/empty).
            language: The student's current preferred language code (e.g. "en", "ml").
        """
        self.language: str = language or "en"
        self._data: dict = self._normalise(raw, self.language)

    # ── Normalisation ────────────────────────────────────────────────────────

    @staticmethod
    def _normalise(raw: str | None, language: str) -> dict:
        """Parse and normalise to the by_language shape. Never raises."""
        empty = {"cache_version": 0, "by_language": {}}

        if not raw or not raw.strip():
            return empty

        parsed = _try_parse(raw)
        if not isinstance(parsed, dict):
            return empty

        # Already in new shape.
        if "by_language" in parsed:
            return parsed

        # bust-sentinel shortcut — only when cache_version is *explicitly* -1.
        # An empty dict {} has no cache_version key and must NOT trigger the sentinel.
        cache_version = parsed.get("cache_version", 0)
        if cache_version == -1:
            return {"cache_version": -1, "by_language": {}}

        # A truly empty dict (no legacy content keys) → fresh empty cache.
        if not parsed:
            return {"cache_version": 0, "by_language": {}}

        # Legacy flat shape — has no "by_language" key but has content.
        # Wrap the flat keys under the student's current language.
        slice_data = {
            "presentation": parsed.get("presentation", ""),
            "cards": parsed.get("cards", []),
            "concepts_queue": parsed.get("concepts_queue", []),
            "concepts_covered": parsed.get("concepts_covered", []),
        }
        # Carry through any extra keys that generate_per_card appends (e.g.
        # "concepts_total", "assigned_image_indices", "current_mode").
        for k, v in parsed.items():
            if k not in ("cache_version", "presentation", "cards",
                         "concepts_queue", "concepts_covered"):
                slice_data[k] = v

        logger.info(
            "[cache] legacy_cache_shape_wrapped: lang=%s cache_version=%s",
            language, cache_version,
        )
        return {
            "cache_version": cache_version,
            "by_language": {language: slice_data},
        }

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def cache_version(self) -> int:
        return self._data.get("cache_version", 0)

    @cache_version.setter
    def cache_version(self, v: int) -> None:
        self._data["cache_version"] = v

    # ── Slice access ─────────────────────────────────────────────────────────

    def get_slice(self, lang: str | None = None) -> dict:
        """
        Return the per-language slice dict for *lang* (defaults to self.language).
        Creates an empty slice if absent so callers never receive None.

        Returns an empty dict when cache_version == -1 (cache bust sentinel) so
        generate_per_card reinitialises from scratch.
        """
        target = lang or self.language
        if self.cache_version == -1:
            # Bust sentinel: treat as cache miss — return empty slice.
            return {}
        by_lang: dict = self._data.setdefault("by_language", {})
        if target not in by_lang:
            by_lang[target] = {}
        return by_lang[target]

    def set_slice(self, data: dict, lang: str | None = None) -> None:
        """
        Overwrite a language's slice.

        Enforces:
        - LRU eviction when > _CACHE_MAX_LANGUAGES distinct languages are stored.
          Eviction removes the language with the fewest cards (least complete).
        - Size cap: if to_json() would exceed _CACHE_MAX_BYTES, evict slices until
          under the cap. Falls back to truncating the current slice's cards to 5
          as a last resort.
        """
        target = lang or self.language
        by_lang: dict = self._data.setdefault("by_language", {})

        # LRU eviction: if adding a NEW language would breach the cap, remove the
        # least-complete one.
        if target not in by_lang and len(by_lang) >= _CACHE_MAX_LANGUAGES:
            victim = min(by_lang, key=lambda k: len(by_lang[k].get("cards", [])))
            del by_lang[victim]
            logger.info(
                "[cache] i18n_session_cache_eviction_total: evicted lang=%s "
                "(fewest cards) to make room for lang=%s",
                victim, target,
            )

        by_lang[target] = data

        # Size cap enforcement.
        serialised = json.dumps(self._data, ensure_ascii=False, separators=(",", ":"))
        if len(serialised.encode("utf-8")) > _CACHE_MAX_BYTES:
            logger.warning(
                "[cache] i18n_session_cache_eviction_total: presentation_text "
                "exceeds %d bytes; evicting other language slices for lang=%s",
                _CACHE_MAX_BYTES, target,
            )
            other_keys = [k for k in list(by_lang.keys()) if k != target]
            for k in other_keys:
                del by_lang[k]
            serialised = json.dumps(
                self._data, ensure_ascii=False, separators=(",", ":")
            )
            if len(serialised.encode("utf-8")) > _CACHE_MAX_BYTES:
                # Truncate current slice's cards as last resort.
                if data.get("cards"):
                    data["cards"] = data["cards"][:5]
                    by_lang[target] = data
                logger.warning(
                    "[cache] session_cache_truncated: cards truncated to 5 "
                    "for lang=%s",
                    target,
                )

    def mark_stale(self, lang: str | None = None) -> None:
        """
        Clear a single language's slice (forces regeneration for that language).
        Other languages are untouched.

        Called by PATCH /students/{id}/language when the student switches language.
        """
        target = lang or self.language
        by_lang = self._data.get("by_language", {})
        if target in by_lang:
            del by_lang[target]
            logger.info("[cache] mark_stale: cleared slice for lang=%s", target)

    def invalidate_all(self) -> None:
        """
        Invalidate the entire cache across all languages.
        Sets top-level cache_version to -1 (bust sentinel).
        Used when cache_version bumps (prompts changed).
        """
        self._data["cache_version"] = -1
        self._data["by_language"] = {}

    # ── Exam question cache ──────────────────────────────────────────────────────

    def get_exam_questions(self, chunk_id: str, lang: str | None = None) -> list[dict] | None:
        """Return cached exam questions for chunk_id in lang (defaults to self.language).

        Returns None if the slice does not exist or the chunk has no cached questions.
        Callers should treat None as a cache miss and generate via LLM.
        """
        sl = self.get_slice(lang)
        return sl.get("exam_questions_by_chunk", {}).get(str(chunk_id))

    def set_exam_questions(
        self, chunk_id: str, questions: list[dict], lang: str | None = None
    ) -> None:
        """Store exam questions for chunk_id in lang slice (defaults to self.language).

        The slice is written back via set_slice() so size-cap eviction applies.
        """
        sl = self.get_slice(lang)
        eq = sl.setdefault("exam_questions_by_chunk", {})
        eq[str(chunk_id)] = questions
        self.set_slice(sl, lang=lang)

    def clear_exam_questions(self, chunk_id: str | None = None) -> None:
        """Remove exam questions from every language slice.

        Args:
            chunk_id: If provided, clear only this chunk's entry from every language
                      slice. If None, clear the entire exam_questions_by_chunk dict
                      from every language slice (full wipe for the current language,
                      safe to call after mark_stale which already deletes the slice).
        """
        for _lang_code, sl in self._data.get("by_language", {}).items():
            if chunk_id is None:
                sl.pop("exam_questions_by_chunk", None)
            else:
                sl.get("exam_questions_by_chunk", {}).pop(str(chunk_id), None)

    def to_json(self) -> str:
        """Serialise for DB write. Compact (no extra whitespace)."""
        return json.dumps(self._data, ensure_ascii=False, separators=(",", ":"))
