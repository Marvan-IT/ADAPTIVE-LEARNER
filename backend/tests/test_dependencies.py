"""
test_dependencies.py
Unit tests for language resolution helpers in api/dependencies.py.

Tests cover:
  - get_request_language: student profile wins over Accept-Language header
  - get_request_language: parses complex Accept-Language values
  - get_request_language: unknown codes fall back to 'en'
  - get_request_language: returns 'en' when no student, no header
  - resolve_translation: returns translation when present
  - resolve_translation: falls back to English when lang key missing
  - resolve_translation: falls back to English when translations is None
  - resolve_translation: falls back to English when translations[lang] is empty string
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from starlette.requests import Request as StarletteRequest

from api.dependencies import get_request_language, resolve_translation


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_request(accept_language: str | None = None) -> StarletteRequest:
    """Build a minimal Starlette Request with the given Accept-Language header."""
    headers = []
    if accept_language is not None:
        headers.append((b"accept-language", accept_language.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/books",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 0),
    }
    return StarletteRequest(scope)


def _make_student(preferred_language: str) -> MagicMock:
    student = MagicMock()
    student.preferred_language = preferred_language
    return student


# ── get_request_language ─────────────────────────────────────────────────────

class TestGetRequestLanguage:
    """Unit tests for get_request_language()."""

    async def test_student_preferred_language_wins_over_header(self):
        """student.preferred_language overrides Accept-Language header."""
        req = _make_request(accept_language="hi")
        student = _make_student("ml")
        result = await get_request_language(req, student)
        assert result == "ml"

    async def test_parses_complex_accept_language_header(self):
        """Accept-Language: ml-IN,en;q=0.9 resolves to 'ml' (strip region + q-value)."""
        req = _make_request(accept_language="ml-IN,en;q=0.9")
        result = await get_request_language(req, student=None)
        assert result == "ml"

    async def test_unknown_accept_language_falls_back_to_en(self):
        """Accept-Language: xx (unsupported code) falls back to 'en'."""
        req = _make_request(accept_language="xx")
        result = await get_request_language(req, student=None)
        assert result == "en"

    async def test_no_student_no_header_returns_en(self):
        """No student and no Accept-Language header returns 'en'."""
        req = _make_request(accept_language=None)
        result = await get_request_language(req, student=None)
        assert result == "en"

    async def test_unknown_student_language_falls_back_to_en(self):
        """A student with an unsupported language code is treated as 'en'."""
        req = _make_request(accept_language="ml")
        student = _make_student("zz")  # unsupported
        result = await get_request_language(req, student)
        assert result == "en"

    async def test_known_language_codes_all_accepted(self):
        """All 12 non-English LANGUAGE_NAMES codes are accepted without fallback."""
        from api.prompts import LANGUAGE_NAMES
        req = _make_request()
        for code in LANGUAGE_NAMES:
            if code == "en":
                continue
            student = _make_student(code)
            result = await get_request_language(req, student)
            assert result == code, f"Expected {code!r}, got {result!r}"


# ── resolve_translation ──────────────────────────────────────────────────────

class TestResolveTranslation:
    """Unit tests for resolve_translation()."""

    def test_returns_translation_when_present(self):
        """Returns the translated value when the lang key exists and is non-empty."""
        result = resolve_translation("Book", {"ml": "പുസ്തകം"}, "ml")
        assert result == "പുസ്തകം"

    def test_falls_back_to_english_when_lang_key_missing(self):
        """Returns english_value when the lang key is absent from translations."""
        result = resolve_translation("Book", {"ta": "புத்தகம்"}, "ml")
        assert result == "Book"

    def test_falls_back_to_english_when_translations_is_none(self):
        """Returns english_value when translations dict is None."""
        result = resolve_translation("Book", None, "ml")
        assert result == "Book"

    def test_falls_back_to_english_when_translation_is_empty_string(self):
        """Returns english_value when translations[lang] is an empty string."""
        result = resolve_translation("Book", {"ml": ""}, "ml")
        assert result == "Book"

    def test_falls_back_to_english_when_translations_is_empty_dict(self):
        """Returns english_value when translations is {} (no translations at all)."""
        result = resolve_translation("Book", {}, "ml")
        assert result == "Book"

    def test_en_lang_always_returns_english_value(self):
        """When lang='en', returns english_value even if translations has an 'en' entry."""
        result = resolve_translation("Book", {"en": "Book-EN", "ml": "പുസ്തകം"}, "en")
        assert result == "Book"

    def test_whitespace_only_translation_falls_back(self):
        """A translation consisting only of whitespace is treated as absent."""
        result = resolve_translation("Book", {"ml": "   "}, "ml")
        assert result == "Book"
