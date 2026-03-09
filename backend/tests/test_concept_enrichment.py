"""
Comprehensive unit tests for the ADA concept-enrichment feature.

Covers:
  Group 1 — LaTeX storage in ChromaDB (chroma_store.store_concept_blocks)
  Group 2 — Vision annotator (images/vision_annotator.annotate_image)
  Group 3 — knowledge_service enrichment (get_concept_detail / get_concept_images)

Test infrastructure:
  - sys.path inserted so tests are importable without conftest.
  - All external dependencies (ChromaDB, OpenAI, filesystem) replaced with
    unittest.mock objects — zero I/O in any test.
  - pytest.ini sets asyncio_mode = auto, so no @pytest.mark.asyncio needed.
"""

import sys
import json
import hashlib
from pathlib import Path

# Ensure backend/src is importable regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call

from storage.chroma_store import store_concept_blocks
from images.vision_annotator import annotate_image
from models import ConceptBlock


# =============================================================================
# Shared helpers
# =============================================================================

def _make_block(
    concept_id: str = "PREALG.C1.S1",
    concept_title: str = "Introduction to Whole Numbers",
    latex: list[str] | None = None,
    text: str = "A whole number is a non-negative integer.",
) -> ConceptBlock:
    """Construct a minimal ConceptBlock for storage tests."""
    return ConceptBlock(
        concept_id=concept_id,
        concept_title=concept_title,
        book_slug="prealgebra",
        book="Prealgebra 2e",
        chapter="1",
        section="1.1",
        text=text,
        latex=latex if latex is not None else [],
        source_pages=[1, 2],
    )


def _make_mock_collection() -> MagicMock:
    """Return a mock chromadb.Collection with a spy on upsert."""
    mock_coll = MagicMock()
    mock_coll.upsert = MagicMock()
    return mock_coll


def _make_mock_llm_client(response_content: str = '{"description": "test desc", "relevance": "test rel", "is_educational": true}') -> AsyncMock:
    """Return a mock AsyncOpenAI client whose chat.completions.create returns *response_content*."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = response_content
    mock_client = AsyncMock()
    mock_client.chat = AsyncMock()
    mock_client.chat.completions = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock_client


def _captured_metadata(mock_collection: MagicMock) -> dict:
    """Extract the first metadata dict from the first collection.upsert call."""
    args, kwargs = mock_collection.upsert.call_args
    # upsert is called as keyword args: upsert(ids=..., documents=..., metadatas=...)
    metadatas = kwargs.get("metadatas") or args[2]
    return metadatas[0]


# =============================================================================
# Group 1 — LaTeX storage in ChromaDB
# =============================================================================

class TestLatexStorageInChromaDB:
    """store_concept_blocks must serialise LaTeX into ChromaDB metadata correctly."""

    def test_latex_expressions_stored_as_json_string(self):
        """latex_expressions key in upserted metadata must be a valid JSON string."""
        # Arrange
        mock_coll = _make_mock_collection()
        block = _make_block(latex=["x + 1"])

        # Act
        store_concept_blocks(mock_coll, [block])

        # Assert
        meta = _captured_metadata(mock_coll)
        assert "latex_expressions" in meta
        # Must be parseable JSON — not a list, not missing
        parsed = json.loads(meta["latex_expressions"])
        assert isinstance(parsed, list)

    def test_latex_expressions_correct_values(self):
        """Stored latex_expressions must round-trip to the exact original list."""
        # Arrange
        original = ["x+1", r"\frac{a}{b}"]
        mock_coll = _make_mock_collection()
        block = _make_block(latex=original)

        # Act
        store_concept_blocks(mock_coll, [block])

        # Assert
        meta = _captured_metadata(mock_coll)
        recovered = json.loads(meta["latex_expressions"])
        assert recovered == original

    def test_latex_empty_list_stored_as_json_string(self):
        """A block with no LaTeX must store '[]' string — not an absent key."""
        # Arrange
        mock_coll = _make_mock_collection()
        block = _make_block(latex=[])

        # Act
        store_concept_blocks(mock_coll, [block])

        # Assert
        meta = _captured_metadata(mock_coll)
        assert "latex_expressions" in meta
        assert meta["latex_expressions"] == "[]"
        assert json.loads(meta["latex_expressions"]) == []

    def test_latex_count_still_stored_alongside_expressions(self):
        """latex_count must still be present in metadata after the enrichment change."""
        # Arrange
        mock_coll = _make_mock_collection()
        block = _make_block(latex=["a", "b", "c"])

        # Act
        store_concept_blocks(mock_coll, [block])

        # Assert
        meta = _captured_metadata(mock_coll)
        assert "latex_count" in meta
        assert meta["latex_count"] == 3

    def test_large_latex_list_does_not_crash(self):
        """Storing 100 LaTeX expressions must complete without raising an exception."""
        # Arrange — generate a large but valid list to trigger the warning path
        large_latex = [rf"\frac{{{i}}}{{{i+1}}}" for i in range(100)]
        mock_coll = _make_mock_collection()
        block = _make_block(latex=large_latex)

        # Act — must not raise; warning threshold check is internal to store_concept_blocks
        store_concept_blocks(mock_coll, [block])

        # Assert — upsert was called once for the single-block batch
        mock_coll.upsert.assert_called_once()
        meta = _captured_metadata(mock_coll)
        stored_list = json.loads(meta["latex_expressions"])
        assert len(stored_list) == 100


# =============================================================================
# Group 2 — vision_annotator.annotate_image
# =============================================================================

class TestVisionAnnotator:
    """annotate_image must handle all image types, caching, and error paths correctly."""

    # ── DECORATIVE skip ───────────────────────────────────────────────────

    async def test_decorative_image_returns_none_without_api_call(self):
        """DECORATIVE images must return null fields immediately — no LLM call made."""
        # Arrange
        mock_client = _make_mock_llm_client()
        image_bytes = b"\x89PNG dummy data"

        # Act
        result = await annotate_image(
            image_bytes=image_bytes,
            concept_title="Introduction to Fractions",
            image_type="DECORATIVE",
            llm_client=mock_client,
        )

        # Assert
        assert result["description"] is None
        assert result["relevance"] is None
        assert result["is_educational"] is False
        mock_client.chat.completions.create.assert_not_called()

    # ── API call for processable types ───────────────────────────────────

    async def test_formula_image_calls_vision_api(self):
        """FORMULA images must trigger an LLM API call with the base64-encoded bytes."""
        # Arrange
        mock_client = _make_mock_llm_client()
        image_bytes = b"\x89PNG\r\nformula image data"

        # Act
        result = await annotate_image(
            image_bytes=image_bytes,
            concept_title="Multiply Fractions",
            image_type="FORMULA",
            llm_client=mock_client,
            cache_dir=None,  # disable cache so no disk I/O
        )

        # Assert — API must have been called exactly once
        mock_client.chat.completions.create.assert_called_once()
        assert result["description"] == "test desc"
        assert result["relevance"] is None  # relevance field removed from prompt, kept as None for schema compat
        assert result["is_educational"] is True

    async def test_diagram_image_calls_vision_api(self):
        """DIAGRAM images must trigger an LLM API call just like FORMULA images."""
        # Arrange
        mock_client = _make_mock_llm_client()
        image_bytes = b"\xff\xd8\xff JPEG diagram data"

        # Act
        result = await annotate_image(
            image_bytes=image_bytes,
            concept_title="Number Line",
            image_type="DIAGRAM",
            llm_client=mock_client,
            cache_dir=None,
        )

        # Assert
        mock_client.chat.completions.create.assert_called_once()
        assert result["description"] == "test desc"
        assert result["is_educational"] is True

    # ── Disk caching ──────────────────────────────────────────────────────

    async def test_annotation_cached_to_disk(self, tmp_path):
        """After a successful annotation, a JSON cache file must be written under cache_dir."""
        # Arrange
        mock_client = _make_mock_llm_client()
        image_bytes = b"\x89PNG cached image"
        md5_hex = hashlib.md5(image_bytes).hexdigest()
        expected_cache_file = tmp_path / f"vision_{md5_hex}.json"

        # Pre-condition: file does not exist
        assert not expected_cache_file.exists()

        # Act
        await annotate_image(
            image_bytes=image_bytes,
            concept_title="Fractions",
            image_type="FORMULA",
            llm_client=mock_client,
            cache_dir=tmp_path,
        )

        # Assert — cache file created and is valid JSON
        assert expected_cache_file.exists()
        cached_data = json.loads(expected_cache_file.read_text(encoding="utf-8"))
        assert cached_data["description"] == "test desc"
        assert cached_data["relevance"] is None  # relevance field removed from prompt, kept as None
        assert cached_data["is_educational"] is True

    async def test_cached_annotation_returned_on_second_call(self, tmp_path):
        """A second call with identical image bytes must return cached data without an API call."""
        # Arrange — first call populates the cache
        mock_client = _make_mock_llm_client()
        image_bytes = b"\x89PNG identical bytes"

        await annotate_image(
            image_bytes=image_bytes,
            concept_title="Fractions",
            image_type="FORMULA",
            llm_client=mock_client,
            cache_dir=tmp_path,
        )
        # Verify first call was an API call
        assert mock_client.chat.completions.create.call_count == 1

        # Act — second call with same bytes
        result = await annotate_image(
            image_bytes=image_bytes,
            concept_title="Fractions",
            image_type="FORMULA",
            llm_client=mock_client,
            cache_dir=tmp_path,
        )

        # Assert — no additional API call (still 1 total)
        assert mock_client.chat.completions.create.call_count == 1
        assert result["description"] == "test desc"

    # ── Graceful degradation ──────────────────────────────────────────────

    async def test_api_error_returns_empty_dict_gracefully(self):
        """When the LLM API raises an exception, annotate_image must not propagate it."""
        # Arrange
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock()
        mock_client.chat.completions = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Network timeout")
        )
        image_bytes = b"\x89PNG error case"

        # Act — must not raise
        result = await annotate_image(
            image_bytes=image_bytes,
            concept_title="Limits",
            image_type="FORMULA",
            llm_client=mock_client,
            cache_dir=None,
        )

        # Assert — graceful fallback with null values; is_educational=False so caller skips it
        assert result["description"] is None
        assert result["relevance"] is None
        assert result["is_educational"] is False

    async def test_json_parse_error_returns_empty_dict_gracefully(self):
        """When the LLM returns non-JSON, annotate_image must degrade gracefully."""
        # Arrange — API returns a plain English string instead of JSON
        mock_client = _make_mock_llm_client(
            response_content="This is a bar chart showing growth over time."
        )
        image_bytes = b"\x89PNG non-json response case"

        # Act — must not raise
        result = await annotate_image(
            image_bytes=image_bytes,
            concept_title="Statistics",
            image_type="DIAGRAM",
            llm_client=mock_client,
            cache_dir=None,
        )

        # Assert — description and relevance are both None on parse failure; filtered by caller
        assert result["description"] is None
        assert result["relevance"] is None
        assert result["is_educational"] is False

    # ── is_educational filtering ───────────────────────────────────────────

    async def test_logo_image_returns_is_educational_false(self):
        """When GPT-4o classifies an image as non-educational, is_educational must be False."""
        # Arrange — simulate GPT-4o returning false for a logo
        mock_client = _make_mock_llm_client(
            response_content='{"description": "An institutional logo", "relevance": "N/A", "is_educational": false}'
        )
        image_bytes = b"\x89PNG logo bytes"

        # Act
        result = await annotate_image(
            image_bytes=image_bytes,
            concept_title="Introduction to Fractions",
            image_type="DIAGRAM",
            llm_client=mock_client,
            cache_dir=None,
        )

        # Assert
        assert result["is_educational"] is False

    async def test_math_diagram_returns_is_educational_true(self):
        """When GPT-4o classifies an image as genuine math content, is_educational must be True."""
        # Arrange — simulate GPT-4o returning true for a number line diagram
        mock_client = _make_mock_llm_client(
            response_content='{"description": "A number line from 0 to 10", "relevance": "Illustrates integer spacing", "is_educational": true}'
        )
        image_bytes = b"\x89PNG number line bytes"

        # Act
        result = await annotate_image(
            image_bytes=image_bytes,
            concept_title="Whole Numbers",
            image_type="DIAGRAM",
            llm_client=mock_client,
            cache_dir=None,
        )

        # Assert
        assert result["is_educational"] is True
        assert result["description"] == "A number line from 0 to 10"


# =============================================================================
# Group 3 — knowledge_service enrichment
# =============================================================================

class TestKnowledgeServiceEnrichment:
    """get_concept_detail must correctly return latex and images enrichment data."""

    def _make_ks_with_mocked_internals(
        self,
        chroma_metadata: dict | None = None,
        latex_map: dict | None = None,
        image_map: dict | None = None,
    ):
        """
        Build a KnowledgeService instance without invoking __init__ at all.

        We use object.__new__ to allocate the instance and then manually assign
        every attribute that the methods under test actually read.  This gives
        perfectly isolated unit tests with zero filesystem or network access and
        no dependency on patching library internals.
        """
        from api.knowledge_service import KnowledgeService

        # Bypass __init__ entirely — no I/O, no imports of ChromaDB/NetworkX clients
        ks = object.__new__(KnowledgeService)
        ks.book_slug = "prealgebra"

        # Internal data maps
        ks._latex_map = latex_map or {}
        ks._image_map = image_map or {}

        # Mock graph: concept IS in graph; no predecessors/successors.
        # Use a simple object whose `in` operator always returns True and whose
        # predecessors/successors always return a fresh empty iterator on each call.
        class _FakeGraph:
            def __contains__(self_inner, item):
                return True
            def predecessors(self_inner, node):
                return iter([])
            def successors(self_inner, node):
                return iter([])

        ks.graph = _FakeGraph()

        # Mock collection.get to return the given chroma_metadata
        mock_collection = MagicMock()
        if chroma_metadata is not None:
            mock_collection.get.return_value = {
                "ids": ["PREALG.C1.S1"],
                "documents": ["Sample instructional text."],
                "metadatas": [chroma_metadata],
            }
        else:
            mock_collection.get.return_value = {
                "ids": [],
                "documents": [],
                "metadatas": [],
            }
        ks.collection = mock_collection

        return ks

    # ── LaTeX from ChromaDB metadata ──────────────────────────────────────

    def test_get_concept_detail_returns_latex_from_chroma_metadata(self):
        """latex list in get_concept_detail response should come from ChromaDB metadata."""
        # Arrange — metadata contains a JSON-serialised latex_expressions field
        meta = {
            "concept_title": "Introduction to Fractions",
            "chapter": "4",
            "section": "4.1",
            "latex_expressions": '["x+1", "\\\\frac{a}{b}"]',
        }
        ks = self._make_ks_with_mocked_internals(chroma_metadata=meta)

        # Act
        result = ks.get_concept_detail("PREALG.C1.S1")

        # Assert
        assert result is not None
        assert result["latex"] == ["x+1", "\\frac{a}{b}"]

    def test_get_concept_detail_falls_back_to_latex_map(self):
        """When ChromaDB metadata has no latex_expressions, fall back to _latex_map."""
        # Arrange — metadata missing latex_expressions key entirely
        meta = {
            "concept_title": "Introduction to Fractions",
            "chapter": "4",
            "section": "4.1",
            # latex_expressions intentionally absent
        }
        fallback_latex = [r"\frac{1}{2}", r"\sqrt{x}"]
        ks = self._make_ks_with_mocked_internals(
            chroma_metadata=meta,
            latex_map={"PREALG.C1.S1": fallback_latex},
        )

        # Act
        result = ks.get_concept_detail("PREALG.C1.S1")

        # Assert — fallback map values are returned
        assert result is not None
        assert result["latex"] == fallback_latex

    # ── Images from image_index ────────────────────────────────────────────

    def test_get_concept_detail_returns_images_with_description(self):
        """Images in get_concept_detail must include description from image_index.json."""
        # Arrange
        meta = {
            "concept_title": "Multiply Fractions",
            "chapter": "4",
            "section": "4.2",
            "latex_expressions": "[]",
        }
        image_map = {
            "PREALG.C1.S1": [
                {
                    "filename": "15593.png",
                    "xref": 15593,
                    "width": 300,
                    "height": 150,
                    "image_type": "FORMULA",
                    "page": 42,
                    "description": "A fraction bar showing 1 over 2.",
                    "relevance": "Illustrates the concept of half.",
                }
            ]
        }
        ks = self._make_ks_with_mocked_internals(
            chroma_metadata=meta,
            image_map=image_map,
        )

        # Act
        result = ks.get_concept_detail("PREALG.C1.S1")

        # Assert
        assert result is not None
        assert len(result["images"]) == 1
        assert result["images"][0]["description"] == "A fraction bar showing 1 over 2."

    def test_get_concept_images_includes_description_and_relevance(self):
        """get_concept_images must pass both description and relevance through."""
        # Arrange
        image_map = {
            "PREALG.C2.S3": [
                {
                    "filename": "99999.png",
                    "xref": 99999,
                    "width": 200,
                    "height": 100,
                    "image_type": "DIAGRAM",
                    "page": 77,
                    "description": "A number line from 0 to 10.",
                    "relevance": "Shows integer spacing visually.",
                }
            ]
        }
        ks = self._make_ks_with_mocked_internals(image_map=image_map)

        # Act
        images = ks.get_concept_images("PREALG.C2.S3")

        # Assert
        assert len(images) == 1
        img = images[0]
        assert "description" in img
        assert "relevance" in img
        assert img["description"] == "A number line from 0 to 10."
        assert img["relevance"] == "Shows integer spacing visually."

    def test_get_concept_detail_images_empty_when_no_index(self):
        """When there is no image_index.json entry for a concept, images must be [] not an error."""
        # Arrange — image_map does not contain the queried concept
        meta = {
            "concept_title": "Whole Numbers",
            "chapter": "1",
            "section": "1.1",
            "latex_expressions": "[]",
        }
        ks = self._make_ks_with_mocked_internals(
            chroma_metadata=meta,
            image_map={},  # empty — no images for any concept
        )

        # Act
        result = ks.get_concept_detail("PREALG.C1.S1")

        # Assert — images key present and is an empty list, no KeyError raised
        assert result is not None
        assert result["images"] == []
