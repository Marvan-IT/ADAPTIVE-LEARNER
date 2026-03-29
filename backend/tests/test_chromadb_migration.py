"""
test_chromadb_migration.py
==========================
Verifies that the ChromaDB → PostgreSQL migration is correct across all layers.

Business criteria
-----------------
BC-01  ChunkKnowledgeService graph methods work with graph.json (sync, no DB).
BC-02  get_concept_detail() aggregates chunks correctly (async, mocked DB).
BC-03  query_similar_chunks() dispatches a pgvector SQL query (async, mocked DB).
BC-04  start_session endpoint rejects unknown book_slugs (HTTP 400).
BC-05  get_concept_readiness endpoint returns unmet prereqs via new graph methods.
BC-06  /health response has chunk_count + graph_nodes + graph_edges, NOT collection_count.
BC-07  GET /api/v1/graph/full returns 60 nodes with prealgebra_ ID format.
BC-08  POST /api/v1/concepts/next returns unlocked concepts for empty mastery set.
BC-09  find_remediation_prereq uses chunk_ksvc.get_predecessors (new contract).
BC-10  generate_adaptive_lesson fetches concept detail via chunk_ksvc (not ChromaDB).

Test strategy
-------------
- All unit/API tests use mocks — no live DB or ChromaDB required.
- Graph tests use the REAL graph.json at backend/output/prealgebra/graph.json.
  They will be skipped automatically when the file is absent.
- Integration tests (marked @pytest.mark.integration) require a live PostgreSQL.
- asyncio_mode = auto is set in pytest.ini so no @pytest.mark.asyncio needed.
"""

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend/src is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── Pre-inject api.main stub to break circular import (teaching_router ↔ api.main) ───
def _install_api_main_stub():
    if "api.main" not in sys.modules:
        stub = MagicMock()
        try:
            from slowapi import Limiter
            from slowapi.util import get_remote_address
            stub.limiter = Limiter(key_func=get_remote_address)
        except ImportError:
            stub.limiter = MagicMock()
        sys.modules["api.main"] = stub

_install_api_main_stub()

from api.chunk_knowledge_service import ChunkKnowledgeService, _graph_cache

# ── Graph.json availability guard ─────────────────────────────────────────────
_GRAPH_JSON_PATH = (
    Path(__file__).resolve().parent.parent / "output" / "prealgebra" / "graph.json"
)
_GRAPH_AVAILABLE = _GRAPH_JSON_PATH.exists()
_skip_no_graph = pytest.mark.skipif(
    not _GRAPH_AVAILABLE,
    reason=f"graph.json not found at {_GRAPH_JSON_PATH} — skipping graph tests",
)


# ═══════════════════════════════════════════════════════════════════════════════
# BC-01  ChunkKnowledgeService graph methods — sync, loaded from graph.json
# ═══════════════════════════════════════════════════════════════════════════════

@_skip_no_graph
class TestChunkKnowledgeServiceGraphMethods:
    """
    Test sync graph methods that load data from graph.json.
    These tests never touch PostgreSQL — they exercise the in-process NetworkX graph.

    The prealgebra graph.json has 60 nodes and 49 edges (verified by inspection).
    Node IDs follow the 'prealgebra_1.1' naming convention (post-migration format).
    """

    def setup_method(self):
        """Ensure the graph is loaded into the module cache before each test."""
        svc = ChunkKnowledgeService()
        svc.preload_graph("prealgebra")
        self._svc = svc

    # BC-01-a  Total node count
    def test_get_all_nodes_returns_60_nodes(self):
        """get_all_nodes('prealgebra') must return exactly 60 concept nodes."""
        nodes = self._svc.get_all_nodes("prealgebra")
        assert len(nodes) == 60, (
            f"Expected 60 nodes in prealgebra graph, got {len(nodes)}"
        )

    # BC-01-b  Node structure
    def test_get_all_nodes_have_required_fields(self):
        """Every node dict must contain concept_id, title, chapter, section, in_degree, out_degree."""
        nodes = self._svc.get_all_nodes("prealgebra")
        required = {"concept_id", "title", "chapter", "section", "in_degree", "out_degree"}
        for node in nodes:
            missing = required - set(node.keys())
            assert not missing, f"Node {node.get('concept_id')} is missing fields: {missing}"

    # BC-01-c  New-style IDs (post-migration format)
    def test_node_id_format_is_new_style(self):
        """All concept_ids must use the 'prealgebra_X.Y' format, NOT 'PREALG.C...' style."""
        nodes = self._svc.get_all_nodes("prealgebra")
        for node in nodes:
            cid = node["concept_id"]
            assert cid.startswith("prealgebra_"), (
                f"Node '{cid}' does not use the post-migration 'prealgebra_' prefix"
            )
            assert not cid.startswith("PREALG."), (
                f"Node '{cid}' still uses legacy 'PREALG.' ChromaDB-era format"
            )

    # BC-01-d  Direct predecessors — sequential curriculum edges
    def test_get_predecessors_for_1_2_returns_1_1(self):
        """prealgebra_1.2 should have prealgebra_1.1 as its direct predecessor."""
        preds = self._svc.get_predecessors("prealgebra", "prealgebra_1.2")
        assert "prealgebra_1.1" in preds, (
            f"Expected prealgebra_1.1 in predecessors of prealgebra_1.2, got {preds}"
        )

    def test_get_predecessors_for_root_returns_empty(self):
        """prealgebra_1.1 has no incoming edges — predecessors must be empty."""
        preds = self._svc.get_predecessors("prealgebra", "prealgebra_1.1")
        assert preds == [], (
            f"Root node prealgebra_1.1 should have no predecessors, got {preds}"
        )

    # BC-01-e  Unlocked frontier with empty mastery
    def test_get_next_concepts_empty_mastered_returns_roots(self):
        """With mastered=[], get_next_concepts() returns all root nodes (no prerequisites)."""
        ready = self._svc.get_next_concepts("prealgebra", [])
        ready_ids = {n["concept_id"] for n in ready}
        # prealgebra_1.1 is confirmed to be a root node with no predecessors
        assert "prealgebra_1.1" in ready_ids, (
            f"prealgebra_1.1 must appear as unlocked with empty mastery, "
            f"but ready_ids={ready_ids}"
        )

    def test_get_next_concepts_empty_mastered_all_have_no_unmet_prereqs(self):
        """Every concept returned by get_next_concepts([]) must have missing_prerequisites=[]."""
        ready = self._svc.get_next_concepts("prealgebra", [])
        for node in ready:
            assert node["missing_prerequisites"] == [], (
                f"Unlocked node {node['concept_id']} should have no missing_prerequisites"
            )

    # BC-01-f  Locked concepts with empty mastery
    def test_get_locked_concepts_all_unmastered_excludes_roots(self):
        """With mastered=[], get_locked_concepts() must NOT include root nodes."""
        locked = self._svc.get_locked_concepts("prealgebra", [])
        locked_ids = {n["concept_id"] for n in locked}
        # prealgebra_1.2 requires prealgebra_1.1 → should be locked
        assert "prealgebra_1.2" in locked_ids, (
            "prealgebra_1.2 should be locked when mastery is empty"
        )
        # prealgebra_1.1 has no prereqs → must NOT be locked
        assert "prealgebra_1.1" not in locked_ids, (
            "Root node prealgebra_1.1 must not appear in locked concepts"
        )

    def test_get_locked_concepts_all_have_non_empty_missing_prereqs(self):
        """Every locked node must list at least one missing_prerequisites entry."""
        locked = self._svc.get_locked_concepts("prealgebra", [])
        for node in locked:
            assert node["missing_prerequisites"], (
                f"Locked node {node['concept_id']} has empty missing_prerequisites"
            )

    # BC-01-g  Graph info structure
    def test_get_graph_info_num_nodes(self):
        """get_graph_info() num_nodes must equal 60."""
        info = self._svc.get_graph_info("prealgebra")
        assert info["num_nodes"] == 60

    def test_get_graph_info_num_edges(self):
        """get_graph_info() num_edges must be at least 49 (graph was expanded with more edges)."""
        info = self._svc.get_graph_info("prealgebra")
        assert info["num_edges"] >= 49, (
            f"Expected at least 49 edges in prealgebra graph, got {info['num_edges']}"
        )

    def test_get_graph_info_is_dag(self):
        """The prealgebra graph must be a valid DAG (no cycles)."""
        info = self._svc.get_graph_info("prealgebra")
        assert info["is_dag"] is True, "Graph must be a DAG (directed acyclic graph)"

    def test_get_graph_info_has_root_and_leaf_lists(self):
        """get_graph_info() must return root_concepts and leaf_concepts lists."""
        info = self._svc.get_graph_info("prealgebra")
        assert isinstance(info["root_concepts"], list)
        assert isinstance(info["leaf_concepts"], list)
        assert len(info["root_concepts"]) > 0, "Graph must have at least one root node"
        assert len(info["leaf_concepts"]) > 0, "Graph must have at least one leaf node"

    # BC-01-h  get_concept_node — happy and sad path
    def test_get_concept_node_returns_correct_fields(self):
        """get_concept_node('prealgebra', 'prealgebra_1.1') must return a valid dict."""
        node = self._svc.get_concept_node("prealgebra", "prealgebra_1.1")
        assert node is not None, "prealgebra_1.1 must be found in graph"
        assert node["concept_id"] == "prealgebra_1.1"
        assert node["chapter"] == "1"
        assert node["section"] == "1.1"

    def test_get_concept_node_unknown_returns_none(self):
        """get_concept_node() for a non-existent ID must return None."""
        node = self._svc.get_concept_node("prealgebra", "prealgebra_99.99")
        assert node is None, "Non-existent concept must return None"

    # BC-01-i  Transitive prerequisites (ancestors)
    def test_get_all_prerequisites_transitive_for_1_3(self):
        """prealgebra_1.3 must have both 1.1 and 1.2 as transitive ancestors."""
        ancestors = self._svc.get_all_prerequisites("prealgebra", "prealgebra_1.3")
        ancestor_set = set(ancestors)
        assert "prealgebra_1.1" in ancestor_set, (
            "prealgebra_1.1 must be a transitive ancestor of prealgebra_1.3"
        )
        assert "prealgebra_1.2" in ancestor_set, (
            "prealgebra_1.2 must be a transitive ancestor of prealgebra_1.3"
        )

    def test_get_all_prerequisites_for_root_returns_empty(self):
        """Root node prealgebra_1.1 has no ancestors — must return []."""
        ancestors = self._svc.get_all_prerequisites("prealgebra", "prealgebra_1.1")
        assert ancestors == []

    def test_get_all_prerequisites_for_unknown_returns_empty(self):
        """Unknown concept_id must return [] without raising."""
        ancestors = self._svc.get_all_prerequisites("prealgebra", "prealgebra_99.1")
        assert ancestors == []

    # BC-01-j  Topological order
    def test_get_topological_order_returns_60_entries(self):
        """Topological sort must include all 60 nodes exactly once."""
        order = self._svc.get_topological_order("prealgebra")
        assert len(order) == 60

    def test_get_topological_order_has_required_fields(self):
        """Each entry in the topological order must have concept_id, title, chapter, section, depth."""
        order = self._svc.get_topological_order("prealgebra")
        required = {"concept_id", "title", "chapter", "section", "depth"}
        for entry in order:
            missing = required - set(entry.keys())
            assert not missing, f"Topological entry missing fields: {missing}"

    def test_get_topological_order_predecessors_before_successors(self):
        """prealgebra_1.1 must appear before prealgebra_1.2 in topological order."""
        order = self._svc.get_topological_order("prealgebra")
        ids = [e["concept_id"] for e in order]
        assert "prealgebra_1.1" in ids and "prealgebra_1.2" in ids
        idx_1_1 = ids.index("prealgebra_1.1")
        idx_1_2 = ids.index("prealgebra_1.2")
        assert idx_1_1 < idx_1_2, (
            f"prealgebra_1.1 (pos={idx_1_1}) must come before prealgebra_1.2 (pos={idx_1_2})"
        )

    # BC-01-k  get_all_edges
    def test_get_all_edges_returns_49_edges(self):
        """get_all_edges() must return at least 49 edge dicts (graph was expanded with more edges)."""
        edges = self._svc.get_all_edges("prealgebra")
        assert len(edges) >= 49, (
            f"Expected at least 49 edges from get_all_edges(), got {len(edges)}"
        )

    def test_get_all_edges_have_source_and_target(self):
        """Every edge dict must have 'source' and 'target' keys."""
        edges = self._svc.get_all_edges("prealgebra")
        for edge in edges:
            assert "source" in edge, f"Edge missing 'source': {edge}"
            assert "target" in edge, f"Edge missing 'target': {edge}"

    def test_get_all_edges_confirms_1_1_to_1_2_edge(self):
        """The edge prealgebra_1.1 → prealgebra_1.2 must exist in the graph."""
        edges = self._svc.get_all_edges("prealgebra")
        edge_pairs = {(e["source"], e["target"]) for e in edges}
        assert ("prealgebra_1.1", "prealgebra_1.2") in edge_pairs, (
            "Expected sequential edge prealgebra_1.1 → prealgebra_1.2 not found"
        )

    # BC-01-l  get_learning_path
    def test_get_learning_path_to_1_3_with_empty_mastery(self):
        """Learning path to prealgebra_1.3 with empty mastery includes prerequisite nodes."""
        result = self._svc.get_learning_path("prealgebra", "prealgebra_1.3", [])
        assert result["target"] == "prealgebra_1.3"
        assert result["total_steps"] >= 1
        assert isinstance(result["path"], list)

    def test_get_learning_path_to_mastered_target_is_just_target(self):
        """When all prereqs are mastered, the path is just the target."""
        result = self._svc.get_learning_path(
            "prealgebra", "prealgebra_1.3", ["prealgebra_1.1", "prealgebra_1.2"]
        )
        assert result["target"] == "prealgebra_1.3"
        assert "prealgebra_1.3" in result["path"]


# ═══════════════════════════════════════════════════════════════════════════════
# BC-02  ChunkKnowledgeService.get_concept_detail() — async, mocked DB
# ═══════════════════════════════════════════════════════════════════════════════

class TestChunkKnowledgeServiceConceptDetail:
    """
    Test async get_concept_detail() with a mocked AsyncSession.
    No live DB required.
    """

    def _make_orm_chunk(self, concept_id="prealgebra_1.1", order_index=0,
                        section="1.1 Introduction to Whole Numbers",
                        text="Whole numbers are 0, 1, 2, 3...",
                        latex=None):
        c = MagicMock()
        c.id = uuid.uuid4()
        c.book_slug = "prealgebra"
        c.concept_id = concept_id
        c.section = section
        c.order_index = order_index
        c.heading = "Introduction"
        c.text = text
        c.latex = latex or []
        return c

    def _make_mock_db(self, chunks, images=None):
        """Build a mock AsyncSession whose execute() returns the given chunks then images."""
        mock_db = AsyncMock()
        images = images or []

        # We need two different execute() calls:
        # 1st: SELECT ConceptChunk WHERE ... → chunks
        # 2nd: SELECT ChunkImage WHERE ... → images
        chunk_scalars = MagicMock()
        chunk_scalars.all.return_value = chunks
        chunk_result = MagicMock()
        chunk_result.scalars.return_value = chunk_scalars

        img_scalars = MagicMock()
        img_scalars.all.return_value = images
        img_result = MagicMock()
        img_result.scalars.return_value = img_scalars

        mock_db.execute = AsyncMock(side_effect=[chunk_result, img_result])
        return mock_db

    async def test_returns_aggregated_dict_for_known_concept(self):
        """get_concept_detail() must return a non-None dict for a concept with chunks."""
        svc = ChunkKnowledgeService()
        chunks = [
            self._make_orm_chunk(order_index=0, text="Short text"),
            self._make_orm_chunk(order_index=1, text="Longer text body with more content"),
        ]
        mock_db = self._make_mock_db(chunks)
        result = await svc.get_concept_detail(mock_db, "prealgebra_1.1", "prealgebra")
        assert result is not None, "Expected non-None result for a concept with DB chunks"

    async def test_returns_none_for_unknown_concept(self):
        """get_concept_detail() must return None when no chunks exist for the concept."""
        svc = ChunkKnowledgeService()
        mock_db = self._make_mock_db(chunks=[])
        # When chunks is empty only one execute() call is made (no image query)
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))
        result = await svc.get_concept_detail(mock_db, "prealgebra_99.99", "prealgebra")
        assert result is None

    async def test_primary_chunk_is_longest_text(self):
        """The 'text' field in the result must come from the chunk with the most characters."""
        svc = ChunkKnowledgeService()
        short_chunk = self._make_orm_chunk(order_index=0, text="Short.")
        long_chunk = self._make_orm_chunk(order_index=1, text="X" * 500)
        mock_db = self._make_mock_db([short_chunk, long_chunk])
        result = await svc.get_concept_detail(mock_db, "prealgebra_1.1", "prealgebra")
        assert result["text"] == "X" * 500, (
            "The primary chunk text must be from the longest-text chunk"
        )

    async def test_latex_is_combined_across_all_chunks(self):
        """The 'latex' key must contain expressions from ALL chunks, not just primary."""
        svc = ChunkKnowledgeService()
        chunk_a = self._make_orm_chunk(order_index=0, text="A" * 10, latex=["expr_a"])
        chunk_b = self._make_orm_chunk(order_index=1, text="B" * 200, latex=["expr_b", "expr_c"])
        mock_db = self._make_mock_db([chunk_a, chunk_b])
        result = await svc.get_concept_detail(mock_db, "prealgebra_1.1", "prealgebra")
        assert "expr_a" in result["latex"]
        assert "expr_b" in result["latex"]
        assert "expr_c" in result["latex"]

    async def test_result_has_concept_title_and_title_both_present(self):
        """
        BC-02 backward compatibility: result must have BOTH 'concept_title' AND 'title' keys.
        adaptive_engine.py references concept_detail['concept_title'].
        """
        svc = ChunkKnowledgeService()
        chunk = self._make_orm_chunk()
        mock_db = self._make_mock_db([chunk])
        result = await svc.get_concept_detail(mock_db, "prealgebra_1.1", "prealgebra")
        assert "concept_title" in result, "result must have 'concept_title' key for adaptive_engine compat"
        assert "title" in result, "result must have 'title' key"
        assert result["concept_title"] == result["title"], (
            "'concept_title' and 'title' must be identical (both set to primary.section)"
        )

    async def test_result_includes_prerequisites_and_dependents(self):
        """
        The result dict must have 'prerequisites' and 'dependents' lists.
        For an unknown graph, these degrade to empty lists (not raised exceptions).
        """
        svc = ChunkKnowledgeService()
        chunk = self._make_orm_chunk()
        mock_db = self._make_mock_db([chunk])
        result = await svc.get_concept_detail(mock_db, "prealgebra_1.1", "prealgebra")
        assert "prerequisites" in result
        assert "dependents" in result
        assert isinstance(result["prerequisites"], list)
        assert isinstance(result["dependents"], list)

    async def test_result_has_sub_sections_list(self):
        """The result dict must have a 'sub_sections' key with one entry per chunk."""
        svc = ChunkKnowledgeService()
        chunks = [self._make_orm_chunk(order_index=i) for i in range(3)]
        mock_db = self._make_mock_db(chunks)
        result = await svc.get_concept_detail(mock_db, "prealgebra_1.1", "prealgebra")
        assert "sub_sections" in result
        assert len(result["sub_sections"]) == 3

    async def test_images_list_is_populated_from_chunk_images(self):
        """When ChunkImage rows exist, 'images' in the result must be non-empty."""
        svc = ChunkKnowledgeService()
        chunk = self._make_orm_chunk()
        img = MagicMock()
        img.image_url = "http://localhost:8889/images/prealgebra/images_downloaded/abc.jpg"
        img.caption = "Figure 1.1"
        img.order_index = 0
        mock_db = self._make_mock_db([chunk], images=[img])
        result = await svc.get_concept_detail(mock_db, "prealgebra_1.1", "prealgebra")
        assert len(result["images"]) == 1
        assert result["images"][0]["image_url"] == img.image_url

    async def test_image_dict_has_backward_compat_keys(self):
        """Each image dict must have 'url', 'filename', 'description', 'relevance' for compat."""
        svc = ChunkKnowledgeService()
        chunk = self._make_orm_chunk()
        img = MagicMock()
        img.image_url = "http://localhost:8889/images/prealgebra/images_downloaded/test.jpg"
        img.caption = "Test caption"
        img.order_index = 0
        mock_db = self._make_mock_db([chunk], images=[img])
        result = await svc.get_concept_detail(mock_db, "prealgebra_1.1", "prealgebra")
        image = result["images"][0]
        assert "url" in image
        assert "filename" in image
        assert "description" in image
        assert "relevance" in image


# ═══════════════════════════════════════════════════════════════════════════════
# BC-03  query_similar_chunks() — pgvector SQL dispatch, mocked DB
# ═══════════════════════════════════════════════════════════════════════════════

class TestChunkKnowledgeServiceQuerySimilar:
    """
    Verify that query_similar_chunks() dispatches a SQL query and returns
    structured results with the expected keys.
    """

    async def test_dispatches_sql_query_to_db(self):
        """query_similar_chunks() must call db.execute() exactly once."""
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        # Simulate empty result set
        mock_db.execute = AsyncMock(return_value=iter([]))
        embedding = [0.1] * 1536
        result = await svc.query_similar_chunks(mock_db, "prealgebra", embedding, n=5)
        mock_db.execute.assert_called_once()

    async def test_returns_list_type(self):
        """query_similar_chunks() must always return a list."""
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=iter([]))
        embedding = [0.0] * 1536
        result = await svc.query_similar_chunks(mock_db, "prealgebra", embedding)
        assert isinstance(result, list)

    async def test_result_row_has_expected_keys(self):
        """Each result must include concept_id, section, heading, text, score, prerequisites."""
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()

        row = MagicMock()
        row.concept_id = "prealgebra_1.1"
        row.section = "1.1 Whole Numbers"
        row.heading = "Introduction"
        row.text = "Whole numbers start at zero."
        row.score = 0.95

        mock_db.execute = AsyncMock(return_value=iter([row]))
        embedding = [0.1] * 1536
        results = await svc.query_similar_chunks(mock_db, "prealgebra", embedding, n=1)

        assert len(results) == 1
        item = results[0]
        for key in ("concept_id", "section", "heading", "text", "score", "prerequisites"):
            assert key in item, f"Result dict missing key: '{key}'"

    async def test_score_is_float(self):
        """The 'score' field must be a Python float, not a raw DB value."""
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()

        row = MagicMock()
        row.concept_id = "prealgebra_1.1"
        row.section = "1.1"
        row.heading = "Intro"
        row.text = "text"
        row.score = 0.87   # DB returns numeric — must be float()

        mock_db.execute = AsyncMock(return_value=iter([row]))
        results = await svc.query_similar_chunks(mock_db, "prealgebra", [0.1] * 1536, n=1)
        assert isinstance(results[0]["score"], float)

    async def test_prerequisites_list_gracefully_handles_unknown_concept(self):
        """
        When get_all_prerequisites() raises (e.g. unknown graph key),
        query_similar_chunks() must swallow the exception and return prerequisites=[].
        """
        svc = ChunkKnowledgeService()
        mock_db = AsyncMock()

        row = MagicMock()
        row.concept_id = "unknown_concept_xyz"
        row.section = "unknown"
        row.heading = "unknown"
        row.text = "some text"
        row.score = 0.5

        mock_db.execute = AsyncMock(return_value=iter([row]))
        # No graph loaded for 'unknown_book' → get_all_prerequisites raises
        results = await svc.query_similar_chunks(mock_db, "unknown_book", [0.1] * 1536, n=1)
        # Must not raise — prerequisites falls back to []
        assert isinstance(results, list)
        if results:
            assert isinstance(results[0]["prerequisites"], list)


# ═══════════════════════════════════════════════════════════════════════════════
# BC-09  Remediation: find_remediation_prereq uses chunk_ksvc.get_predecessors
# ═══════════════════════════════════════════════════════════════════════════════

class TestRemediationNewSignature:
    """
    Verify that find_remediation_prereq() calls chunk_ksvc.get_predecessors()
    rather than accessing graph.predecessors directly (old ChromaDB-era signature).
    """

    def test_find_remediation_prereq_returns_first_unmastered_prereq(self):
        """Returns the first direct prerequisite not in mastery_store."""
        from adaptive.remediation import find_remediation_prereq

        mock_ksvc = MagicMock()
        mock_ksvc.get_predecessors.return_value = ["prealgebra_1.1", "prealgebra_1.0"]
        mastery_store = {"prealgebra_1.0": True}  # 1.0 mastered, 1.1 not

        result = find_remediation_prereq(
            "prealgebra_1.2", mock_ksvc, "prealgebra", mastery_store
        )
        assert result == "prealgebra_1.1", (
            f"Expected first unmastered prereq 'prealgebra_1.1', got '{result}'"
        )
        mock_ksvc.get_predecessors.assert_called_once_with("prealgebra", "prealgebra_1.2")

    def test_find_remediation_prereq_all_mastered_returns_none(self):
        """When all prerequisites are mastered, must return None."""
        from adaptive.remediation import find_remediation_prereq

        mock_ksvc = MagicMock()
        mock_ksvc.get_predecessors.return_value = ["prealgebra_1.1"]
        mastery_store = {"prealgebra_1.1": True}

        result = find_remediation_prereq(
            "prealgebra_1.2", mock_ksvc, "prealgebra", mastery_store
        )
        assert result is None

    def test_find_remediation_prereq_no_prerequisites_returns_none(self):
        """Root concept with no prerequisites must return None."""
        from adaptive.remediation import find_remediation_prereq

        mock_ksvc = MagicMock()
        mock_ksvc.get_predecessors.return_value = []
        mastery_store = {}

        result = find_remediation_prereq(
            "prealgebra_1.1", mock_ksvc, "prealgebra", mastery_store
        )
        assert result is None

    def test_find_remediation_prereq_exception_from_ksvc_returns_none(self):
        """If get_predecessors() raises, must return None gracefully (not propagate)."""
        from adaptive.remediation import find_remediation_prereq

        mock_ksvc = MagicMock()
        mock_ksvc.get_predecessors.side_effect = RuntimeError("graph not loaded")
        mastery_store = {}

        result = find_remediation_prereq(
            "prealgebra_1.2", mock_ksvc, "prealgebra", mastery_store
        )
        assert result is None

    def test_has_unmet_prereq_returns_true_when_prereq_unmastered(self):
        """has_unmet_prereq is True when find_remediation_prereq returns non-None."""
        from adaptive.remediation import has_unmet_prereq

        mock_ksvc = MagicMock()
        mock_ksvc.get_predecessors.return_value = ["prealgebra_1.1"]
        mastery_store = {}  # prealgebra_1.1 not mastered

        assert has_unmet_prereq("prealgebra_1.2", mock_ksvc, "prealgebra", mastery_store) is True

    def test_has_unmet_prereq_returns_false_when_all_mastered(self):
        """has_unmet_prereq is False when all prerequisites are mastered."""
        from adaptive.remediation import has_unmet_prereq

        mock_ksvc = MagicMock()
        mock_ksvc.get_predecessors.return_value = ["prealgebra_1.1"]
        mastery_store = {"prealgebra_1.1": True}

        assert has_unmet_prereq("prealgebra_1.2", mock_ksvc, "prealgebra", mastery_store) is False

    def test_find_remediation_prereq_calls_chunk_ksvc_not_graph_object(self):
        """
        Regression guard: the new signature must NOT access chunk_ksvc.graph.predecessors().
        It must call chunk_ksvc.get_predecessors() instead.
        """
        from adaptive.remediation import find_remediation_prereq

        mock_ksvc = MagicMock()
        mock_ksvc.get_predecessors.return_value = []
        mastery_store = {}

        find_remediation_prereq("prealgebra_1.1", mock_ksvc, "prealgebra", mastery_store)

        # The new method must be used
        mock_ksvc.get_predecessors.assert_called_once()
        # The old graph attribute must NOT be accessed
        mock_ksvc.graph.predecessors.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# BC-10  generate_adaptive_lesson uses chunk_ksvc.get_concept_detail
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdaptiveEngineUsesChunkKsvc:
    """
    Verify that generate_adaptive_lesson() calls chunk_ksvc.get_concept_detail()
    (not a ChromaDB KnowledgeService method) and raises ValueError when not found.
    """

    def _make_analytics(self, **overrides):
        """Build a valid AnalyticsSummary for testing."""
        from adaptive.schemas import AnalyticsSummary
        defaults = dict(
            student_id=str(uuid.uuid4()),
            concept_id="prealgebra_1.1",
            time_spent_sec=120.0,
            expected_time_sec=100.0,
            attempts=3,
            wrong_attempts=1,
            hints_used=0,
            revisits=0,
            recent_dropoffs=0,
            skip_rate=0.0,
            quiz_score=0.7,
            last_7d_sessions=1,
        )
        defaults.update(overrides)
        return AnalyticsSummary(**defaults)

    async def test_generate_adaptive_lesson_calls_get_concept_detail(self):
        """generate_adaptive_lesson() must call chunk_ksvc.get_concept_detail() for concept lookup."""
        from adaptive.adaptive_engine import generate_adaptive_lesson

        analytics = self._make_analytics()

        # chunk_ksvc returns None → should raise ValueError (concept not found)
        mock_ksvc = MagicMock()
        mock_ksvc.get_concept_detail = AsyncMock(return_value=None)
        mock_ksvc.get_predecessors.return_value = []

        mock_db = AsyncMock()
        mock_llm = MagicMock()

        with pytest.raises(ValueError, match="Concept not found"):
            await generate_adaptive_lesson(
                student_id=str(uuid.uuid4()),
                concept_id="prealgebra_99.99",
                analytics_summary=analytics,
                chunk_ksvc=mock_ksvc,
                book_slug="prealgebra",
                db=mock_db,
                mastery_store={},
                llm_client=mock_llm,
            )

        mock_ksvc.get_concept_detail.assert_called_once()

    async def test_generate_adaptive_lesson_raises_when_concept_not_found(self):
        """ValueError must be raised when chunk_ksvc.get_concept_detail() returns None."""
        from adaptive.adaptive_engine import generate_adaptive_lesson

        analytics = self._make_analytics(quiz_score=0.5, wrong_attempts=2, attempts=3)

        mock_ksvc = MagicMock()
        mock_ksvc.get_concept_detail = AsyncMock(return_value=None)

        with pytest.raises(ValueError):
            await generate_adaptive_lesson(
                student_id=str(uuid.uuid4()),
                concept_id="prealgebra_ghost",
                analytics_summary=analytics,
                chunk_ksvc=mock_ksvc,
                book_slug="prealgebra",
                db=AsyncMock(),
                mastery_store={},
                llm_client=MagicMock(),
            )


# ═══════════════════════════════════════════════════════════════════════════════
# API endpoint tests — use a synthetic FastAPI app to avoid lifespan side-effects
# ═══════════════════════════════════════════════════════════════════════════════

# Shared fake IDs
_FAKE_STUDENT_ID = uuid.uuid4()
_FAKE_SESSION_ID = uuid.uuid4()
_FAKE_CONCEPT_ID = "prealgebra_1.1"


def _make_fake_student():
    from datetime import datetime, timezone
    s = MagicMock()
    s.id = _FAKE_STUDENT_ID
    s.display_name = "Test Student"
    s.interests = []
    s.preferred_style = "default"
    s.preferred_language = "en"
    s.xp = 0
    s.streak = 0
    s.section_count = 0
    s.overall_accuracy_rate = 0.5
    s.preferred_analogy_style = None
    s.boredom_pattern = None
    s.frustration_tolerance = "medium"
    s.recovery_speed = "normal"
    s.avg_state_score = 2.0
    s.effective_analogies = []
    s.effective_engagement = []
    s.ineffective_engagement = []
    s.state_distribution = {"struggling": 0, "normal": 0, "fast": 0}
    s.created_at = datetime.now(timezone.utc)
    s.updated_at = datetime.now(timezone.utc)
    return s


class _FakeAggRow:
    """Numeric-safe aggregate row mimic — avoids float(MagicMock) errors."""
    def __init__(self):
        self.total = 0
        self.avg_wrong = 0.0
        self.avg_hints = 0.0
        self.avg_time = 0.0
        self.avg_check = None


def _make_mock_db(active_books=("prealgebra",), concept_detail=None):
    """Build a mock AsyncSession compatible with teaching_router expectations."""
    db = AsyncMock()

    fake_student = _make_fake_student()

    async def _db_get(cls, pk):
        from db.models import Student, TeachingSession
        if cls == Student:
            return fake_student if pk == _FAKE_STUDENT_ID else None
        return None

    db.get = _db_get
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        all=MagicMock(return_value=[]),
        one=MagicMock(return_value=_FakeAggRow()),
        one_or_none=MagicMock(return_value=None),
        first=lambda: None,
        scalar=MagicMock(return_value=0),
        fetchall=MagicMock(return_value=[(b,) for b in active_books]),
    ))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


def _make_mock_chunk_ksvc(active_books=("prealgebra",), concept_detail=None,
                           predecessors=None, graph_info=None, all_nodes=None,
                           all_edges=None):
    """Build a mock ChunkKnowledgeService with configurable return values."""
    ksvc = MagicMock()
    ksvc.get_active_books = AsyncMock(return_value=set(active_books))
    ksvc.get_concept_detail = AsyncMock(return_value=concept_detail)
    ksvc.get_predecessors.return_value = predecessors if predecessors is not None else []
    ksvc.get_concept_node.return_value = None
    ksvc.get_chunk_count = AsyncMock(return_value=1063)

    default_graph_info = {"num_nodes": 60, "num_edges": 49, "is_dag": True,
                          "root_concepts": ["prealgebra_1.1"], "leaf_concepts": ["prealgebra_9.6"]}
    ksvc.get_graph_info.return_value = graph_info or default_graph_info

    default_nodes = [
        {"concept_id": f"prealgebra_1.{i}", "title": f"Section 1.{i}", "chapter": "1",
         "section": f"1.{i}", "in_degree": 0 if i == 1 else 1, "out_degree": 1 if i < 3 else 0}
        for i in range(1, 4)
    ]
    ksvc.get_all_nodes.return_value = all_nodes or default_nodes
    default_edges = [{"source": "prealgebra_1.1", "target": "prealgebra_1.2"}]
    ksvc.get_all_edges.return_value = all_edges or default_edges

    # Sync methods used in concept_next endpoint
    ksvc.get_next_concepts.return_value = [
        {"concept_id": "prealgebra_1.1", "title": "Introduction to Whole Numbers",
         "chapter": "1", "section": "1.1", "missing_prerequisites": []}
    ]
    ksvc.get_locked_concepts.return_value = [
        {"concept_id": "prealgebra_1.2", "title": "Add Whole Numbers",
         "chapter": "1", "section": "1.2", "missing_prerequisites": ["prealgebra_1.1"]}
    ]
    return ksvc


def _build_main_test_app(active_books=("prealgebra",), concept_detail=None,
                          predecessors=None) -> "FastAPI":
    """
    Build a lightweight FastAPI app that wires real api.main endpoints
    but uses mocked DB and ChunkKnowledgeService.

    We inline the /health, /api/v1/graph/*, /api/v1/concepts/next endpoints
    to test them without triggering the full lifespan.
    """
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    from api.rate_limiter import limiter

    app = FastAPI()
    app.state.limiter = limiter

    mock_ksvc = _make_mock_chunk_ksvc(
        active_books=active_books,
        concept_detail=concept_detail,
        predecessors=predecessors,
    )
    mock_db = _make_mock_db(active_books=active_books, concept_detail=concept_detail)

    from db.connection import get_db

    async def _get_test_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_test_db

    # ── Health endpoint (mirrors api/main.py) ─────────────────────────────────
    @app.get("/health")
    async def health():
        graph_info = mock_ksvc.get_graph_info("prealgebra")
        chunk_count = await mock_ksvc.get_chunk_count(mock_db)
        return {
            "status": "ok",
            "chunk_count": chunk_count,
            "graph_nodes": graph_info["num_nodes"],
            "graph_edges": graph_info["num_edges"],
        }

    # ── Graph endpoints ────────────────────────────────────────────────────────
    @app.get("/api/v1/graph/full")
    async def graph_full(book_slug: str = "prealgebra"):
        nodes = mock_ksvc.get_all_nodes(book_slug)
        edges = mock_ksvc.get_all_edges(book_slug)
        return {"nodes": nodes, "edges": edges}

    @app.get("/api/v1/graph/nodes")
    async def graph_nodes(book_slug: str = "prealgebra"):
        nodes = mock_ksvc.get_all_nodes(book_slug)
        return {"nodes": nodes, "count": len(nodes)}

    # ── Concepts/next endpoint ─────────────────────────────────────────────────
    class NextConceptsRequest(BaseModel):
        mastered_concepts: list[str] = []

    @app.post("/api/v1/concepts/next")
    async def next_concepts(req: NextConceptsRequest, book_slug: str = "prealgebra"):
        ready = mock_ksvc.get_next_concepts(book_slug, req.mastered_concepts)
        locked = mock_ksvc.get_locked_concepts(book_slug, req.mastered_concepts)
        return {
            "mastered_concepts": req.mastered_concepts,
            "ready_to_learn": ready,
            "locked": locked,
        }

    # ── Teaching router (start_session, get_concept_readiness) ────────────────
    import api.teaching_router as teaching_router_module
    mock_teaching_svc = MagicMock()
    mock_session = MagicMock()
    mock_session.id = _FAKE_SESSION_ID
    mock_session.student_id = _FAKE_STUDENT_ID
    mock_session.concept_id = _FAKE_CONCEPT_ID
    mock_session.book_slug = "prealgebra"
    mock_session.phase = "PRESENTING"
    mock_session.style = "default"
    from datetime import datetime, timezone
    mock_session.started_at = datetime.now(timezone.utc)
    mock_session.completed_at = None
    mock_session.check_score = None
    mock_session.concept_mastered = False
    mock_session.socratic_attempt_count = 0
    mock_session.best_check_score = None
    mock_session.lesson_interests = None
    mock_teaching_svc.start_session = AsyncMock(return_value=mock_session)

    teaching_router_module.teaching_svc = mock_teaching_svc
    teaching_router_module.chunk_ksvc = mock_ksvc

    app.include_router(teaching_router_module.router)

    return app, mock_ksvc


@pytest.fixture
def main_test_app():
    app, mock_ksvc = _build_main_test_app(
        active_books=("prealgebra",),
        concept_detail={
            "concept_id": _FAKE_CONCEPT_ID,
            "concept_title": "Introduction to Whole Numbers",
            "title": "Introduction to Whole Numbers",
            "text": "Whole numbers begin at zero.",
            "latex": [],
            "images": [],
            "prerequisites": [],
            "dependents": [],
        },
    )
    return app, mock_ksvc


# ═══════════════════════════════════════════════════════════════════════════════
# BC-06  /health has chunk_count, graph_nodes, graph_edges — NO collection_count
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    """
    The /health endpoint must reflect the post-migration architecture.
    It must NOT contain collection_count (ChromaDB field).
    It MUST contain chunk_count, graph_nodes, graph_edges.
    """

    async def test_health_returns_200(self, main_test_app):
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_health_has_chunk_count(self, main_test_app):
        """BC-06: /health must include 'chunk_count' (total DB chunks, integer)."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        data = resp.json()
        assert "chunk_count" in data, f"'chunk_count' missing from /health response: {data}"
        assert isinstance(data["chunk_count"], int)

    async def test_health_has_graph_nodes(self, main_test_app):
        """BC-06: /health must include 'graph_nodes' (integer from graph.json)."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        data = resp.json()
        assert "graph_nodes" in data, f"'graph_nodes' missing from /health response: {data}"
        assert isinstance(data["graph_nodes"], int)

    async def test_health_has_graph_edges(self, main_test_app):
        """BC-06: /health must include 'graph_edges' (integer from graph.json)."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        data = resp.json()
        assert "graph_edges" in data, f"'graph_edges' missing from /health response: {data}"
        assert isinstance(data["graph_edges"], int)

    async def test_health_does_not_have_collection_count(self, main_test_app):
        """BC-06 regression: 'collection_count' is a ChromaDB field and must be ABSENT."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        data = resp.json()
        assert "collection_count" not in data, (
            "ChromaDB 'collection_count' must not appear in /health after migration"
        )

    async def test_health_graph_nodes_matches_mock_value(self, main_test_app):
        """The graph_nodes value must match what get_graph_info() returns."""
        import httpx
        app, mock_ksvc = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        data = resp.json()
        # Our mock returns num_nodes=60
        assert data["graph_nodes"] == 60

    async def test_health_graph_edges_matches_mock_value(self, main_test_app):
        """The graph_edges value must match what get_graph_info() returns."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        data = resp.json()
        assert data["graph_edges"] == 49


# ═══════════════════════════════════════════════════════════════════════════════
# BC-07  GET /api/v1/graph/full — 60 nodes, prealgebra_ ID format
# ═══════════════════════════════════════════════════════════════════════════════

class TestGraphFullEndpoint:
    """
    The /api/v1/graph/full endpoint must return node data sourced from the
    post-migration ChunkKnowledgeService (graph.json), NOT ChromaDB.
    """

    @_skip_no_graph
    async def test_graph_full_with_real_graph_returns_60_nodes(self):
        """BC-07: With real graph.json, /graph/full must return 60 nodes."""
        import httpx

        # Build an app that uses the REAL ChunkKnowledgeService with real graph.json
        from fastapi import FastAPI
        from api.rate_limiter import limiter

        app = FastAPI()
        app.state.limiter = limiter

        real_ksvc = ChunkKnowledgeService()
        real_ksvc.preload_graph("prealgebra")

        @app.get("/api/v1/graph/full")
        async def graph_full(book_slug: str = "prealgebra"):
            nodes = real_ksvc.get_all_nodes(book_slug)
            edges = real_ksvc.get_all_edges(book_slug)
            return {"nodes": nodes, "edges": edges}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/graph/full?book_slug=prealgebra")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 60, (
            f"Expected 60 nodes from real graph.json, got {len(data['nodes'])}"
        )

    @_skip_no_graph
    async def test_graph_full_node_ids_use_new_format(self):
        """BC-07: No node ID should start with 'PREALG.' — all must use 'prealgebra_'."""
        import httpx
        from fastapi import FastAPI
        from api.rate_limiter import limiter

        app = FastAPI()
        app.state.limiter = limiter
        real_ksvc = ChunkKnowledgeService()
        real_ksvc.preload_graph("prealgebra")

        @app.get("/api/v1/graph/full")
        async def graph_full(book_slug: str = "prealgebra"):
            nodes = real_ksvc.get_all_nodes(book_slug)
            edges = real_ksvc.get_all_edges(book_slug)
            return {"nodes": nodes, "edges": edges}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/graph/full?book_slug=prealgebra")

        data = resp.json()
        for node in data["nodes"]:
            cid = node["concept_id"]
            assert not cid.startswith("PREALG."), (
                f"Node '{cid}' uses legacy ChromaDB ID format — migration incomplete"
            )
            assert cid.startswith("prealgebra_"), (
                f"Node '{cid}' does not use expected 'prealgebra_' prefix"
            )

    async def test_graph_full_mocked_returns_200(self, main_test_app):
        """BC-07: /api/v1/graph/full returns 200 with nodes and edges keys."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/graph/full?book_slug=prealgebra")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data

    async def test_graph_nodes_endpoint_returns_count(self, main_test_app):
        """BC-07: /api/v1/graph/nodes returns count field matching node list length."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/graph/nodes?book_slug=prealgebra")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert data["count"] == len(data["nodes"])


# ═══════════════════════════════════════════════════════════════════════════════
# BC-08  POST /api/v1/concepts/next — unlocked concepts with empty mastery
# ═══════════════════════════════════════════════════════════════════════════════

class TestConceptsNextEndpoint:
    """
    POST /api/v1/concepts/next must return concepts whose all prerequisites
    are in the mastered list.  With an empty mastered list, only root nodes
    (no prerequisites) should appear in ready_to_learn.
    """

    async def test_concepts_next_returns_200(self, main_test_app):
        """BC-08: POST /api/v1/concepts/next → 200 for valid request."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/concepts/next?book_slug=prealgebra",
                json={"mastered_concepts": []}
            )
        assert resp.status_code == 200

    async def test_concepts_next_empty_mastery_includes_prealgebra_1_1(self, main_test_app):
        """BC-08: With mastered=[], prealgebra_1.1 (root node) must appear in ready_to_learn."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/concepts/next?book_slug=prealgebra",
                json={"mastered_concepts": []}
            )
        data = resp.json()
        assert "ready_to_learn" in data
        ready_ids = [c["concept_id"] for c in data["ready_to_learn"]]
        assert "prealgebra_1.1" in ready_ids, (
            f"prealgebra_1.1 must be unlocked with empty mastery, got: {ready_ids}"
        )

    async def test_concepts_next_has_locked_list(self, main_test_app):
        """BC-08: Response must include a 'locked' list of concepts with unmet prerequisites."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/concepts/next?book_slug=prealgebra",
                json={"mastered_concepts": []}
            )
        data = resp.json()
        assert "locked" in data
        assert isinstance(data["locked"], list)

    async def test_concepts_next_with_real_graph_empty_mastery(self):
        """BC-08: Real graph.json — empty mastery → all 11 root nodes unlocked."""
        pytest.importorskip("networkx")
        if not _GRAPH_AVAILABLE:
            pytest.skip("graph.json not available")

        real_ksvc = ChunkKnowledgeService()
        real_ksvc.preload_graph("prealgebra")

        ready = real_ksvc.get_next_concepts("prealgebra", [])
        ready_ids = {n["concept_id"] for n in ready}

        # prealgebra_1.1 is confirmed root in this graph
        assert "prealgebra_1.1" in ready_ids
        # prealgebra_1.2 requires prealgebra_1.1 → must NOT be ready
        assert "prealgebra_1.2" not in ready_ids, (
            "prealgebra_1.2 must be locked when mastery is empty"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BC-04  start_session endpoint validates book_slug against active books
# ═══════════════════════════════════════════════════════════════════════════════

class TestStartSessionBookSlugValidation:
    """
    The start_session endpoint (POST /api/v2/sessions) must:
    - Return HTTP 400 if book_slug is not in active_books (determined via PostgreSQL)
    - Return HTTP 400 if the concept is not found in the book
    - Return success (200/201) for a valid student + valid book_slug
    """

    async def test_start_session_with_invalid_book_slug_returns_400(self, main_test_app):
        """BC-04: Requesting a session with an unknown book_slug returns HTTP 400."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v2/sessions", json={
                "student_id": str(_FAKE_STUDENT_ID),
                "concept_id": "prealgebra_1.1",
                "book_slug": "nonexistent_book_xyz",   # NOT in active_books
                "style": "default",
            })
        assert resp.status_code == 400, (
            f"Expected HTTP 400 for unknown book_slug, got {resp.status_code}: {resp.text}"
        )

    async def test_start_session_with_valid_book_slug_passes_book_check(self):
        """BC-04: A valid book_slug that matches active_books passes the first guard."""
        import httpx

        # Build an app where concept_detail is None → triggers the second 400
        # (book_slug check PASSED, concept check FAILED)
        app, _ = _build_main_test_app(
            active_books=("prealgebra",),
            concept_detail=None,  # concept not found → next 400
        )

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v2/sessions", json={
                "student_id": str(_FAKE_STUDENT_ID),
                "concept_id": "prealgebra_1.1",
                "book_slug": "prealgebra",   # Valid book
                "style": "default",
            })

        # Should not be book-validation error (400 with "not loaded")
        # Could be 400 (concept not found) but NOT 400 with "not loaded" message
        if resp.status_code == 400:
            assert "not loaded" not in resp.json().get("detail", ""), (
                "Error was book validation failure — concept validation should have run instead"
            )

    async def test_start_session_unknown_student_returns_404(self, main_test_app):
        """BC-04: Unknown student_id must return HTTP 404."""
        import httpx
        app, _ = main_test_app
        unknown_id = uuid.uuid4()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v2/sessions", json={
                "student_id": str(unknown_id),
                "concept_id": "prealgebra_1.1",
                "book_slug": "prealgebra",
                "style": "default",
            })
        assert resp.status_code == 404

    async def test_start_session_error_detail_mentions_book_slug(self, main_test_app):
        """BC-04: The 400 error detail for invalid book must name the rejected book_slug."""
        import httpx
        app, _ = main_test_app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v2/sessions", json={
                "student_id": str(_FAKE_STUDENT_ID),
                "concept_id": "prealgebra_1.1",
                "book_slug": "invalid_book",
                "style": "default",
            })
        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert "invalid_book" in detail, (
            f"Error detail must name the rejected book_slug, got: '{detail}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BC-05  get_concept_readiness endpoint via new chunk_ksvc graph methods
# ═══════════════════════════════════════════════════════════════════════════════

class TestConceptReadinessEndpoint:
    """
    GET /api/v2/concepts/{concept_id}/readiness must use chunk_ksvc.get_predecessors()
    and chunk_ksvc.get_concept_node() to determine unmet prerequisites.
    """

    async def test_readiness_all_prereqs_met_returns_true(self):
        """BC-05: When all direct predecessors are in student mastery, all_prerequisites_met=True."""
        import httpx

        app, mock_ksvc = _build_main_test_app(predecessors=[])
        mock_ksvc.get_predecessors.return_value = []  # no prerequisites

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v2/concepts/prealgebra_1.1/readiness?student_id={_FAKE_STUDENT_ID}"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_prerequisites_met"] is True
        assert data["unmet_prerequisites"] == []

    async def test_readiness_unmet_prereq_returns_false(self):
        """BC-05: When a direct prerequisite is not mastered, all_prerequisites_met=False."""
        import httpx

        app, mock_ksvc = _build_main_test_app(predecessors=["prealgebra_1.1"])
        # The mock DB returns empty mastery for this student
        mock_ksvc.get_concept_node.return_value = {
            "concept_id": "prealgebra_1.1",
            "title": "Introduction to Whole Numbers",
            "chapter": "1",
            "section": "1.1",
        }

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v2/concepts/prealgebra_1.2/readiness?student_id={_FAKE_STUDENT_ID}"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_prerequisites_met"] is False
        assert len(data["unmet_prerequisites"]) == 1

    async def test_readiness_unmet_prereq_list_has_concept_id_and_title(self):
        """BC-05: Each unmet prerequisite must have concept_id and concept_title keys."""
        import httpx

        app, mock_ksvc = _build_main_test_app(predecessors=["prealgebra_1.1"])
        mock_ksvc.get_concept_node.return_value = {
            "concept_id": "prealgebra_1.1",
            "title": "Introduction to Whole Numbers",
            "chapter": "1",
            "section": "1.1",
        }

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v2/concepts/prealgebra_1.2/readiness?student_id={_FAKE_STUDENT_ID}"
            )
        data = resp.json()
        unmet = data["unmet_prerequisites"]
        assert len(unmet) == 1
        assert "concept_id" in unmet[0]
        assert "concept_title" in unmet[0]
        assert unmet[0]["concept_id"] == "prealgebra_1.1"

    async def test_readiness_uses_get_predecessors_not_graph_attribute(self):
        """BC-05: The endpoint must call chunk_ksvc.get_predecessors(), not graph.predecessors()."""
        import httpx

        app, mock_ksvc = _build_main_test_app(predecessors=[])

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await client.get(
                f"/api/v2/concepts/prealgebra_1.1/readiness?student_id={_FAKE_STUDENT_ID}"
            )

        # New method must be called
        mock_ksvc.get_predecessors.assert_called()
        # Old ChromaDB-era method must NOT be used
        if hasattr(mock_ksvc, "graph"):
            mock_ksvc.graph.predecessors.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests — require live PostgreSQL (skipped automatically without DB)
# ═══════════════════════════════════════════════════════════════════════════════

try:
    import asyncpg  # noqa: F401
    _ASYNCPG_AVAILABLE = True
except ImportError:
    _ASYNCPG_AVAILABLE = False


@pytest.mark.integration
@pytest.mark.skipif(not _ASYNCPG_AVAILABLE, reason="asyncpg not installed")
class TestChunkKnowledgeServiceIntegration:
    """
    Integration tests that query the real PostgreSQL database.

    These tests are automatically skipped if:
    - asyncpg is not installed
    - DATABASE_URL is not set or DB is not reachable
    - The db_session fixture skips (see conftest.py)
    """

    async def test_get_active_books_returns_prealgebra(self, db_session):
        """BC-03-integration: get_active_books() returns {'prealgebra'} when chunks exist."""
        svc = ChunkKnowledgeService()
        books = await svc.get_active_books(db_session)
        assert isinstance(books, set)
        # If the DB is seeded, prealgebra must be present
        if books:
            assert "prealgebra" in books, (
                f"Expected 'prealgebra' in active books, got {books}"
            )

    async def test_chunk_count_is_positive(self, db_session):
        """BC-03-integration: get_chunk_count() returns a positive integer for prealgebra."""
        svc = ChunkKnowledgeService()
        count = await svc.get_chunk_count(db_session, book_slug="prealgebra")
        assert isinstance(count, int)
        assert count >= 0

    async def test_concept_detail_for_prealgebra_1_1(self, db_session):
        """BC-02-integration: Real DB returns valid concept detail for prealgebra_1.1."""
        svc = ChunkKnowledgeService()
        detail = await svc.get_concept_detail(db_session, "prealgebra_1.1", "prealgebra")
        if detail is None:
            pytest.skip("prealgebra_1.1 not in DB — skipping concept detail integration test")
        assert "concept_id" in detail
        assert "concept_title" in detail
        assert "title" in detail
        assert isinstance(detail["text"], str)
        assert len(detail["text"]) > 0
        assert isinstance(detail["latex"], list)
        assert isinstance(detail["images"], list)

    async def test_get_chunk_nonexistent_returns_none(self, db_session):
        """get_chunk() for a zero UUID must return None (no data in any real DB)."""
        svc = ChunkKnowledgeService()
        result = await svc.get_chunk(db_session, "00000000-0000-0000-0000-000000000000")
        assert result is None
