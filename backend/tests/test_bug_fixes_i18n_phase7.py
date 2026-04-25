"""
test_bug_fixes_i18n_phase7.py
Regression tests for the five bug fixes shipped in i18n-rework phase 7.

Bug 1: get_concept_detail did not accept a lang parameter — headings always
       returned in English regardless of student preference.
Bug 2: _language_instruction permitted keeping "proper nouns" in English —
       the mandate was too weak, allowing technical vocabulary to leak.
Bug 3: cache_version was not bumped after the prompt change, meaning stale
       English cards survived in the cache for non-English students.
Bug 4: call sites of get_concept_detail / get_chunks_for_concept lacked the
       lang= keyword — student language was silently ignored at the DB layer.
"""

import ast
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from api.dependencies import resolve_translation
from api.prompts import _language_instruction


# ── Test 1: get_concept_detail respects the lang parameter ───────────────────

class TestGetConceptDetailTranslation:
    """Bug 1: get_concept_detail must apply resolve_translation to the primary chunk heading."""

    def _make_mock_db(self, chunks: list, images: list | None = None) -> AsyncMock:
        """Build a minimal AsyncSession mock that returns *chunks* for the first query
        and *images* for the image query."""
        mock_db = AsyncMock()
        chunks_result = MagicMock()
        chunks_result.scalars.return_value.all.return_value = chunks
        images_result = MagicMock()
        images_result.scalars.return_value.all.return_value = images or []
        mock_db.execute = AsyncMock(side_effect=[chunks_result, images_result])
        return mock_db

    def _make_chunk(self, heading: str, heading_translations: dict, text: str = "x" * 200) -> MagicMock:
        chunk = MagicMock()
        chunk.id = "test-chunk-id"
        chunk.concept_id = "prealgebra_1.1"
        chunk.book_slug = "prealgebra"
        chunk.heading = heading
        chunk.heading_translations = heading_translations
        chunk.text = text
        chunk.latex = []
        chunk.order_index = 0
        chunk.is_hidden = False
        chunk.section = "1.1"
        chunk.type = "text"
        chunk.images = []
        return chunk

    async def test_returns_translated_heading_for_non_english_lang(self):
        """Bug 1: get_concept_detail(lang='ml') must return the Malayalam heading."""
        from api.chunk_knowledge_service import ChunkKnowledgeService
        chunk = self._make_chunk(
            heading="Introduction",
            heading_translations={"ml": "പരിചയം"},
        )
        ksvc = ChunkKnowledgeService()
        # Patch _load_graph to avoid file I/O
        ksvc.get_predecessors = MagicMock(return_value=[])
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "api.chunk_knowledge_service._load_graph"
        ) as mock_graph:
            mock_g = MagicMock()
            mock_g.successors.return_value = []
            mock_g.__contains__ = MagicMock(return_value=True)
            mock_graph.return_value = mock_g
            db = self._make_mock_db([chunk])
            result = await ksvc.get_concept_detail(db, "prealgebra_1.1", "prealgebra", lang="ml")

        assert result is not None
        assert result["concept_title"] == "പരിചയം", (
            f"Expected Malayalam heading, got: {result['concept_title']!r}"
        )
        assert result["title"] == "പരിചയം"

    async def test_falls_back_to_english_when_translation_missing(self):
        """Bug 1 / fallback: lang='hi' with no Hindi translation must return English heading."""
        from api.chunk_knowledge_service import ChunkKnowledgeService
        chunk = self._make_chunk(
            heading="Introduction",
            heading_translations={"ml": "പരിചയം"},  # Hindi absent
        )
        ksvc = ChunkKnowledgeService()
        ksvc.get_predecessors = MagicMock(return_value=[])
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "api.chunk_knowledge_service._load_graph"
        ) as mock_graph:
            mock_g = MagicMock()
            mock_g.successors.return_value = []
            mock_g.__contains__ = MagicMock(return_value=True)
            mock_graph.return_value = mock_g
            db = self._make_mock_db([chunk])
            result = await ksvc.get_concept_detail(db, "prealgebra_1.1", "prealgebra", lang="hi")

        assert result["concept_title"] == "Introduction"

    async def test_english_lang_returns_english_heading_unchanged(self):
        """Bug 1 / baseline: lang='en' must return the English heading as-is."""
        from api.chunk_knowledge_service import ChunkKnowledgeService
        chunk = self._make_chunk(
            heading="Introduction",
            heading_translations={"ml": "പരിചയം"},
        )
        ksvc = ChunkKnowledgeService()
        ksvc.get_predecessors = MagicMock(return_value=[])
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "api.chunk_knowledge_service._load_graph"
        ) as mock_graph:
            mock_g = MagicMock()
            mock_g.successors.return_value = []
            mock_g.__contains__ = MagicMock(return_value=True)
            mock_graph.return_value = mock_g
            db = self._make_mock_db([chunk])
            result = await ksvc.get_concept_detail(db, "prealgebra_1.1", "prealgebra", lang="en")

        assert result["concept_title"] == "Introduction"


# ── Test 2: _language_instruction contains the hardened mandate ──────────────

class TestLanguageInstruction:
    """Bug 2: _language_instruction must mandate translating ALL content including
    technical terms, and must NOT contain the old permissive 'proper nouns' phrase."""

    def test_non_english_contains_translate_all_mandate(self):
        """Bug 2: instruction for 'ml' must include 'Translate ALL content'."""
        result = _language_instruction("ml")
        assert "Translate ALL content" in result, (
            "'Translate ALL content' mandate missing from language instruction"
        )

    def test_non_english_contains_technical_terminology(self):
        """Bug 2: instruction must explicitly include 'technical terminology'."""
        result = _language_instruction("ml")
        assert "technical terminology" in result, (
            "'technical terminology' missing — students would see English vocab"
        )

    def test_non_english_contains_only_exceptions_clause(self):
        """Bug 2: instruction must state 'The ONLY exceptions' to limit carve-outs."""
        result = _language_instruction("ml")
        assert "The ONLY exceptions" in result

    def test_non_english_does_not_contain_old_proper_nouns_phrase(self):
        """Bug 2: 'proper nouns' was the old permissive loophole — must be gone."""
        result = _language_instruction("ml")
        assert "proper nouns" not in result, (
            "Old 'proper nouns' exception still present — reverts the fix"
        )

    def test_english_returns_empty_string(self):
        """Bug 2 / short-circuit: _language_instruction('en') must return ''."""
        assert _language_instruction("en") == ""

    def test_empty_string_returns_empty_string(self):
        """Bug 2 / short-circuit: _language_instruction('') must return ''."""
        assert _language_instruction("") == ""

    def test_all_supported_non_english_codes_produce_non_empty_output(self):
        """Bug 2 / coverage: every supported code except 'en' must yield an instruction."""
        from api.prompts import LANGUAGE_NAMES
        for code in LANGUAGE_NAMES:
            if code == "en":
                continue
            result = _language_instruction(code)
            assert result, f"Empty instruction for supported language code '{code}'"


# ── Test 3: cache_version is 3 ───────────────────────────────────────────────

class TestCacheVersion:
    """Bug 3: cache_version must be 3 after the prompt change; a revert to 2
    would leave stale English cards in cache for non-English students."""

    def test_cache_version_constant_is_3(self):
        """Bug 3: Both hard-coded cache_version literals in teaching_service.py must be 3."""
        src = Path(__file__).resolve().parent.parent / "src" / "api" / "teaching_service.py"
        text = src.read_text(encoding="utf-8")
        # Find all lines that assign or set cache_version to a number
        hits = re.findall(r"cache_version\s*[=:]\s*(\d+)", text)
        assert hits, "No cache_version assignments found in teaching_service.py"
        non_three = [v for v in hits if v != "3"]
        assert not non_three, (
            f"cache_version regression: found value(s) {non_three!r}, expected all to be 3"
        )


# ── Test 4: all call sites pass lang= keyword ────────────────────────────────

class TestCallSitesPassLang:
    """Bug 4: any call site without lang= will silently use lang='en' default,
    meaning non-English students get un-translated headings/chunks.
    This AST-based lint test enumerates every call to these two functions and
    asserts that the lang keyword argument is present."""

    _SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "api"
    _TARGET_FILES = ["teaching_router.py", "teaching_service.py"]
    _CALL_NAMES = {"get_concept_detail", "get_chunks_for_concept"}

    # These call sites intentionally use lang="en" (image-fallback / structural
    # queries that do not need translation).  Track them here so they remain
    # auditable rather than silently passing.
    _KNOWN_EN_HARDCODED = {
        # (filename, lineno)  — update when intentional hardcoded sites change.
        # teaching_router.py:691 — start_session: lang="en" (concept validation only)
        ("teaching_router.py", 691),
        # teaching_router.py:1289 — chunk-ownership check; no student UX impact
        ("teaching_router.py", 1290),
        # teaching_router.py:1479 — all_study_complete guard
        ("teaching_router.py", 1480),
        # teaching_service.py:1187 — image fallback path
        ("teaching_service.py", 1188),
    }

    def _collect_calls(self, filepath: Path) -> list[tuple[str, int, bool]]:
        """Return [(func_name, lineno, has_lang_kwarg)] for every matching call."""
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
        results = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Match obj.method(...) call patterns
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in self._CALL_NAMES:
                continue
            has_lang = any(kw.arg == "lang" for kw in node.keywords)
            results.append((node.func.attr, node.lineno, has_lang))
        return results

    def test_all_call_sites_have_lang_keyword(self):
        """Bug 4: every call to get_concept_detail / get_chunks_for_concept must
        pass lang= explicitly so that new call sites cannot silently drop it."""
        missing: list[str] = []
        for fname in self._TARGET_FILES:
            fpath = self._SRC_ROOT / fname
            for func_name, lineno, has_lang in self._collect_calls(fpath):
                if not has_lang:
                    missing.append(f"{fname}:{lineno} {func_name}()")
        assert not missing, (
            "Call sites missing lang= keyword (will silently use 'en' default):\n"
            + "\n".join(f"  {m}" for m in missing)
        )

    def test_call_sites_are_present_in_target_files(self):
        """Sanity: target files must contain at least one call each so the
        previous test cannot pass vacuously after a rename."""
        for fname in self._TARGET_FILES:
            fpath = self._SRC_ROOT / fname
            calls = self._collect_calls(fpath)
            assert calls, (
                f"{fname} has no calls to get_concept_detail / get_chunks_for_concept "
                f"— either the functions were renamed or the file was moved"
            )
