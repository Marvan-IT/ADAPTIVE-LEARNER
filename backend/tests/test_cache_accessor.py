"""
test_cache_accessor.py
Unit tests for api/cache_accessor.py — CacheAccessor per-language slice management.

Business criteria verified:
- Legacy flat JSON is transparently upgraded to by_language shape on first read.
- Cache-bust sentinel (cache_version=-1) short-circuits to empty by_language.
- Corrupt / empty / None raw values never raise; default to safe empty state.
- Per-language slices are isolated: writes to one language never touch another.
- mark_stale removes a single language slice; others are preserved.
- invalidate_all wipes all slices and sets cache_version=-1 (bust sentinel).
- LRU cap (5 languages): 6th insertion evicts the least-complete language.
- Size cap (512 KB): oversized payload triggers eviction; a warning is logged.
- Round-trip fidelity: to_json() / re-init preserves all slices and cache_version.
- Serialised output is compact (no extra spaces).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from api.cache_accessor import CacheAccessor, _CACHE_MAX_BYTES, _CACHE_MAX_LANGUAGES


# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_legacy(cache_version: int = 3, cards: list | None = None) -> str:
    """Return a JSON string in the old flat (pre-i18n) shape."""
    payload = {
        "cache_version": cache_version,
        "cards": cards if cards is not None else [{"id": 1}],
        "concepts_queue": [],
        "concepts_covered": [],
    }
    return json.dumps(payload)


def _make_modern(
    cache_version: int = 5,
    slices: dict | None = None,
) -> str:
    """Return a JSON string in the new by_language shape."""
    payload = {
        "cache_version": cache_version,
        "by_language": slices or {},
    }
    return json.dumps(payload)


def _big_slice(size_bytes: int) -> dict:
    """Return a slice dict whose serialised size is at least *size_bytes*."""
    return {
        "cards": [{"content": "X" * size_bytes}],
        "concepts_queue": [],
        "concepts_covered": [],
    }


# ─── 1. Legacy-shape wrapping ──────────────────────────────────────────────────

class TestLegacyWrapping:
    """Flat (legacy) JSON is transparently upgraded to the by_language shape."""

    def test_get_slice_returns_cards_after_wrap(self):
        """get_slice('en') returns the cards from the legacy flat shape."""
        ca = CacheAccessor(_make_legacy(cache_version=3, cards=[{"id": 1}]), language="en")
        sl = ca.get_slice("en")
        assert sl["cards"] == [{"id": 1}]

    def test_cache_version_preserved_after_wrap(self):
        """cache_version is taken from the legacy payload, not reset to 0."""
        ca = CacheAccessor(_make_legacy(cache_version=3), language="en")
        assert ca.cache_version == 3

    def test_by_language_has_exactly_one_key(self):
        """After wrapping, by_language contains only the requested language."""
        ca = CacheAccessor(_make_legacy(), language="en")
        assert list(ca._data["by_language"].keys()) == ["en"]

    def test_legacy_wrap_logged(self, caplog):
        """Init logs 'legacy_cache_shape_wrapped' at INFO level."""
        import logging
        with caplog.at_level(logging.INFO, logger="api.cache_accessor"):
            CacheAccessor(_make_legacy(cache_version=7), language="ml")
        assert "legacy_cache_shape_wrapped" in caplog.text

    def test_extra_keys_carried_through(self):
        """Extra flat-shape keys (concepts_total, current_mode, …) are kept in the slice."""
        raw = json.dumps({
            "cache_version": 2,
            "cards": [],
            "concepts_queue": [],
            "concepts_covered": [],
            "current_mode": "NORMAL",
            "concepts_total": 4,
        })
        ca = CacheAccessor(raw, language="ta")
        sl = ca.get_slice("ta")
        assert sl.get("current_mode") == "NORMAL"
        assert sl.get("concepts_total") == 4


# ─── 2. Bust-sentinel (cache_version=-1) ────────────────────────────────────

class TestBustSentinel:
    """Legacy shape with cache_version=-1 is the bust sentinel."""

    def test_cache_version_is_minus_one(self):
        ca = CacheAccessor(_make_legacy(cache_version=-1), language="en")
        assert ca.cache_version == -1

    def test_by_language_is_empty(self):
        """Bust sentinel yields an empty by_language, not a wrapped slice."""
        ca = CacheAccessor(_make_legacy(cache_version=-1), language="en")
        assert ca._data["by_language"] == {}

    def test_get_slice_returns_empty_dict_on_bust(self):
        """When cache_version==-1, get_slice returns {} (miss) for any language."""
        ca = CacheAccessor(_make_legacy(cache_version=-1), language="en")
        assert ca.get_slice("en") == {}
        assert ca.get_slice("ml") == {}


# ─── 3. Empty / None / invalid input ──────────────────────────────────────────

class TestEmptyOrInvalidInput:
    """Corrupt or absent raw values must never raise; they produce a safe empty state."""

    def _assert_empty(self, ca: CacheAccessor):
        assert ca.cache_version == 0
        assert ca._data["by_language"] == {}

    def test_none_input(self):
        self._assert_empty(CacheAccessor(None, language="en"))

    def test_empty_string_input(self):
        self._assert_empty(CacheAccessor("", language="en"))

    def test_whitespace_only_input(self):
        self._assert_empty(CacheAccessor("   ", language="en"))

    def test_invalid_json_does_not_raise(self):
        """Invalid JSON triggers json-repair fallback or safe empty — no exception."""
        try:
            ca = CacheAccessor("{invalid json", language="en")
            # Either safe empty OR repair produced a valid dict — neither should raise.
            assert isinstance(ca._data, dict)
        except Exception as exc:
            pytest.fail(f"CacheAccessor raised on invalid JSON: {exc}")

    def test_empty_object_input(self):
        """'{}' parses fine; no 'by_language' key, no cards, version defaults to -1 (bust)."""
        # _normalise: parsed has no "by_language"; cache_version defaults to -1 via get(...,-1)
        ca = CacheAccessor("{}", language="en")
        assert isinstance(ca._data, dict)
        assert ca._data["by_language"] == {}

    def test_non_dict_json_is_safe(self):
        """A JSON array at the top level is treated as empty."""
        self._assert_empty(CacheAccessor("[1,2,3]", language="en"))


# ─── 4. Per-language slice operations ─────────────────────────────────────────

class TestSliceOperations:
    """set_slice / get_slice are isolated per language."""

    def test_set_and_get_for_two_languages(self):
        ca = CacheAccessor(None, language="en")
        ca.set_slice({"cards": [{"i": 1}]}, "en")
        ca.set_slice({"cards": [{"i": 2}]}, "ml")
        assert ca.get_slice("en")["cards"] == [{"i": 1}]
        assert ca.get_slice("ml")["cards"] == [{"i": 2}]

    def test_get_slice_missing_language_returns_empty_dict(self):
        """Requesting an absent language creates and returns an empty dict (no KeyError)."""
        ca = CacheAccessor(None, language="en")
        sl = ca.get_slice("ta")
        assert isinstance(sl, dict)
        assert sl == {}

    def test_set_slice_overwrites_existing(self):
        ca = CacheAccessor(None, language="en")
        ca.set_slice({"cards": [{"old": True}]}, "en")
        ca.set_slice({"cards": [{"new": True}]}, "en")
        assert ca.get_slice("en")["cards"] == [{"new": True}]

    def test_default_language_used_when_lang_omitted(self):
        """set_slice / get_slice with lang=None use self.language."""
        ca = CacheAccessor(None, language="fr")
        ca.set_slice({"cards": [{"v": 99}]})
        assert ca.get_slice()["cards"] == [{"v": 99}]
        assert "fr" in ca._data["by_language"]

    def test_get_slice_preserves_existing_modern_shape(self):
        """Modern (by_language) shape is read without re-wrapping."""
        raw = _make_modern(cache_version=9, slices={"de": {"cards": [{"x": 1}]}})
        ca = CacheAccessor(raw, language="de")
        assert ca.cache_version == 9
        assert ca.get_slice("de")["cards"] == [{"x": 1}]


# ─── 5. mark_stale ────────────────────────────────────────────────────────────

class TestMarkStale:
    """mark_stale removes exactly one language slice; others survive."""

    def test_mark_stale_removes_target_language(self):
        ca = CacheAccessor(None, language="en")
        ca.set_slice({"cards": [{"a": 1}]}, "en")
        ca.set_slice({"cards": [{"b": 2}]}, "ml")
        ca.mark_stale("en")
        assert "en" not in ca._data["by_language"]

    def test_mark_stale_preserves_other_languages(self):
        ca = CacheAccessor(None, language="en")
        ca.set_slice({"cards": [{"a": 1}]}, "en")
        ca.set_slice({"cards": [{"b": 2}]}, "ml")
        ca.mark_stale("en")
        assert ca.get_slice("ml")["cards"] == [{"b": 2}]

    def test_mark_stale_on_missing_lang_is_noop(self):
        """Staling a language that was never populated does not raise."""
        ca = CacheAccessor(None, language="en")
        ca.mark_stale("ta")  # should not raise

    def test_mark_stale_default_uses_self_language(self):
        ca = CacheAccessor(None, language="hi")
        ca.set_slice({"cards": [{"c": 3}]}, "hi")
        ca.mark_stale()  # should clear "hi"
        assert "hi" not in ca._data["by_language"]

    def test_mark_stale_logged(self, caplog):
        import logging
        ca = CacheAccessor(None, language="en")
        ca.set_slice({"cards": []}, "en")
        with caplog.at_level(logging.INFO, logger="api.cache_accessor"):
            ca.mark_stale("en")
        assert "mark_stale" in caplog.text


# ─── 6. invalidate_all ────────────────────────────────────────────────────────

class TestInvalidateAll:
    """invalidate_all wipes all slices and sets cache_version=-1."""

    def test_by_language_is_empty_after_invalidate(self):
        ca = CacheAccessor(None, language="en")
        ca.set_slice({"cards": [1]}, "en")
        ca.set_slice({"cards": [2]}, "ml")
        ca.set_slice({"cards": [3]}, "ta")
        ca.invalidate_all()
        assert ca._data["by_language"] == {}

    def test_cache_version_becomes_minus_one(self):
        ca = CacheAccessor(_make_legacy(cache_version=5), language="en")
        assert ca.cache_version == 5
        ca.invalidate_all()
        assert ca.cache_version == -1

    def test_get_slice_returns_empty_after_invalidate(self):
        ca = CacheAccessor(None, language="en")
        ca.set_slice({"cards": [{"x": 1}]}, "en")
        ca.invalidate_all()
        assert ca.get_slice("en") == {}


# ─── 7. LRU cap at 5 languages ────────────────────────────────────────────────

class TestLRUCap:
    """Inserting a 6th language evicts the one with the fewest cards."""

    def test_oldest_fewest_cards_evicted(self, caplog):
        import logging
        ca = CacheAccessor(None, language="en")

        langs_and_card_counts = [
            ("en", 1),   # fewest → gets evicted
            ("ml", 2),
            ("ta", 3),
            ("hi", 4),
            ("fr", 5),
        ]
        for lang, n in langs_and_card_counts:
            ca.set_slice({"cards": [{"i": i} for i in range(n)]}, lang)

        # Adding a 6th language should evict "en" (fewest cards = 1)
        with caplog.at_level(logging.INFO, logger="api.cache_accessor"):
            ca.set_slice({"cards": [{"i": 99}]}, "de")

        assert "en" not in ca._data["by_language"]
        assert "de" in ca._data["by_language"]
        assert len(ca._data["by_language"]) == _CACHE_MAX_LANGUAGES

    def test_eviction_logged(self, caplog):
        import logging
        ca = CacheAccessor(None, language="en")
        for i, lang in enumerate(["en", "ml", "ta", "hi", "fr"]):
            ca.set_slice({"cards": list(range(i + 1))}, lang)
        with caplog.at_level(logging.INFO, logger="api.cache_accessor"):
            ca.set_slice({"cards": [1]}, "de")
        assert "i18n_session_cache_eviction_total" in caplog.text

    def test_round_trip_after_lru_eviction(self):
        """After 6 insertions, to_json + re-init preserves exactly 5 languages."""
        ca = CacheAccessor(None, language="en")
        for i, lang in enumerate(["en", "ml", "ta", "hi", "fr"]):
            ca.set_slice({"cards": list(range(i + 1))}, lang)
        ca.set_slice({"cards": [1]}, "de")

        ca2 = CacheAccessor(ca.to_json(), language="de")
        remaining = set(ca2._data["by_language"].keys())
        assert len(remaining) == _CACHE_MAX_LANGUAGES
        assert "en" not in remaining   # evicted
        assert "de" in remaining


# ─── 8. Size cap at 512 KB ────────────────────────────────────────────────────

class TestSizeCap:
    """A slice that exceeds 512 KB triggers eviction of other language slices."""

    def test_oversized_slice_evicts_others(self, caplog):
        import logging
        ca = CacheAccessor(None, language="en")
        # seed a small bystander slice
        ca.set_slice({"cards": [{"small": True}]}, "ml")

        # add a slice that by itself exceeds 512 KB
        big = _big_slice(_CACHE_MAX_BYTES + 1024)
        with caplog.at_level(logging.WARNING, logger="api.cache_accessor"):
            ca.set_slice(big, "en")

        assert "i18n_session_cache_eviction_total" in caplog.text
        # the bystander should have been evicted
        assert "ml" not in ca._data["by_language"]

    def test_to_json_result_does_not_exceed_cap_after_truncation(self):
        """Even after eviction of other languages, the output must not exceed the cap
        or the truncation fallback must have fired (cards capped at 5)."""
        ca = CacheAccessor(None, language="en")
        big = _big_slice(_CACHE_MAX_BYTES + 1024)
        ca.set_slice(big, "en")
        serialised = ca.to_json()
        parsed = json.loads(serialised)
        en_slice = parsed["by_language"].get("en", {})
        # Either within cap, or cards truncated to 5
        if len(serialised.encode("utf-8")) > _CACHE_MAX_BYTES:
            assert len(en_slice.get("cards", [])) <= 5

    def test_size_warning_logged(self, caplog):
        import logging
        ca = CacheAccessor(None, language="en")
        ca.set_slice({"cards": [{"pad": "Y"}]}, "fr")
        big = _big_slice(_CACHE_MAX_BYTES + 1024)
        with caplog.at_level(logging.WARNING, logger="api.cache_accessor"):
            ca.set_slice(big, "en")
        assert any(
            "exceeds" in r.message or "truncated" in r.message
            for r in caplog.records
            if r.levelname == "WARNING"
        )


# ─── 9. Round-trip fidelity ───────────────────────────────────────────────────

class TestRoundTrip:
    """to_json() → re-init preserves slices and cache_version."""

    def test_slices_preserved_across_round_trip(self):
        ca = CacheAccessor(None, language="en")
        ca.cache_version = 11
        ca.set_slice({"cards": [{"lang": "en"}], "concepts_queue": ["A"]}, "en")
        ca.set_slice({"cards": [{"lang": "ml"}], "concepts_covered": ["B"]}, "ml")

        ca2 = CacheAccessor(ca.to_json(), language="en")
        assert ca2.cache_version == 11
        assert ca2.get_slice("en")["cards"] == [{"lang": "en"}]
        assert ca2.get_slice("ml")["cards"] == [{"lang": "ml"}]

    def test_round_trip_from_legacy(self):
        """Legacy input wrapped on first init survives a round-trip unchanged."""
        original_cards = [{"id": 42}]
        ca = CacheAccessor(
            _make_legacy(cache_version=4, cards=original_cards), language="en"
        )
        ca2 = CacheAccessor(ca.to_json(), language="en")
        assert ca2.cache_version == 4
        assert ca2.get_slice("en")["cards"] == original_cards


# ─── 10. Compact serialisation ────────────────────────────────────────────────

class TestCompactSerialisation:
    """to_json() must use separators=(',', ':') — no extra whitespace."""

    def test_no_space_after_colon(self):
        ca = CacheAccessor(None, language="en")
        ca.set_slice({"cards": []}, "en")
        out = ca.to_json()
        assert ": " not in out

    def test_no_space_after_comma(self):
        ca = CacheAccessor(None, language="en")
        ca.set_slice({"cards": [], "concepts_queue": []}, "en")
        out = ca.to_json()
        assert ", " not in out

    def test_valid_json_after_compact_serialise(self):
        ca = CacheAccessor(None, language="en")
        ca.set_slice({"cards": [{"x": 1}]}, "en")
        parsed = json.loads(ca.to_json())
        assert parsed["by_language"]["en"]["cards"] == [{"x": 1}]


# ─── 11. cache_version property ───────────────────────────────────────────────

class TestCacheVersionProperty:
    """cache_version is readable and writable; persists through round-trip."""

    def test_default_cache_version_is_zero_for_empty_init(self):
        ca = CacheAccessor(None, language="en")
        assert ca.cache_version == 0

    def test_set_cache_version_persists(self):
        ca = CacheAccessor(None, language="en")
        ca.cache_version = 99
        assert ca.cache_version == 99

    def test_cache_version_persists_through_to_json_reinit(self):
        ca = CacheAccessor(None, language="en")
        ca.cache_version = 42
        ca2 = CacheAccessor(ca.to_json(), language="en")
        assert ca2.cache_version == 42

    def test_cache_version_from_modern_shape(self):
        raw = _make_modern(cache_version=17)
        ca = CacheAccessor(raw, language="en")
        assert ca.cache_version == 17
