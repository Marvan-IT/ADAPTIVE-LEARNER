"""
Knowledge Service — integrates ChromaDB (RAG) with NetworkX (Graph)
for concept retrieval with prerequisite awareness.

This is the core Week 1 deliverable: fusing semantic search with
dependency graph traversal in a single query.
"""

import json
import sys
import os
from pathlib import Path
from typing import Optional

import networkx as nx

# Ensure src is on the path (follows existing convention in the codebase)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.chroma_store import initialize_collection, query_similar_concepts, get_collection_stats
from graph.graph_store import load_graph_json, get_graph_stats, get_topological_order, get_learning_path, get_concept_depth
from config import OUTPUT_DIR


class KnowledgeService:
    """
    Loads ChromaDB collection and NetworkX graph for a given book.
    Provides methods that combine RAG retrieval with graph traversal.
    """

    def __init__(self, book_slug: str = "prealgebra"):
        self.book_slug = book_slug
        self._book_output_dir = OUTPUT_DIR / book_slug

        # Load ChromaDB collection (matching pipeline.py's naming convention)
        chroma_dir = self._book_output_dir / "chroma_db"
        collection_name = f"concepts_{book_slug}"
        self.collection = initialize_collection(
            persist_directory=chroma_dir,
            collection_name=collection_name,
        )

        # Load NetworkX graph
        graph_path = self._book_output_dir / "dependency_graph.json"
        self.graph = load_graph_json(graph_path)

        # Load LaTeX data from concept_blocks.json
        # (ChromaDB only stores latex_count, not the actual array)
        self._latex_map: dict[str, list[str]] = {}
        concept_blocks_path = self._book_output_dir / "concept_blocks.json"
        if concept_blocks_path.exists():
            with open(concept_blocks_path, "r", encoding="utf-8") as f:
                blocks = json.load(f)
            for block in blocks:
                cid = block.get("concept_id", "")
                self._latex_map[cid] = block.get("latex", [])
            print(f"  LaTeX: loaded for {len(self._latex_map)} concepts")

        # Load image index from image_index.json
        self._image_map: dict[str, list[dict]] = {}
        image_index_path = self._book_output_dir / "image_index.json"
        if image_index_path.exists():
            with open(image_index_path, "r", encoding="utf-8") as f:
                self._image_map = json.load(f)
            total_images = sum(len(v) for v in self._image_map.values())
            print(f"  Images: {total_images} across {len(self._image_map)} concepts")

        print(f"  ChromaDB: {self.collection.count()} concepts in '{collection_name}'")
        print(f"  Graph: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")

    # ── The core RAG + Graph method ───────────────────────────────

    def query_concept_with_prerequisites(
        self,
        query_text: str,
        mastered_concepts: list[str],
        n_results: int = 3,
    ) -> list[dict]:
        """
        THE integrated RAG + Graph query:
        1. ChromaDB semantic search finds matching concepts (RAG)
        2. NetworkX checks prerequisites for each result (Graph)
        3. Returns enriched results with readiness information
        """
        # Step 1: RAG retrieval
        raw_results = query_similar_concepts(
            self.collection,
            query_text,
            n_results=n_results,
            where_filter={"book_slug": self.book_slug},
        )

        mastered_set = set(mastered_concepts)
        enriched = []

        for result in raw_results:
            concept_id = result["id"]
            metadata = result["metadata"]

            # Step 2: Get prerequisites from graph
            prerequisites = []
            if concept_id in self.graph:
                for prereq_id in self.graph.predecessors(concept_id):
                    prereq_data = self.graph.nodes.get(prereq_id, {})
                    prerequisites.append({
                        "concept_id": prereq_id,
                        "concept_title": prereq_data.get("title", prereq_id),
                        "mastered": prereq_id in mastered_set,
                    })

            # Step 3: Determine readiness
            all_met = all(p["mastered"] for p in prerequisites) if prerequisites else True

            # Extract latex from the concept text
            latex = self._get_latex(concept_id)

            enriched.append({
                "concept_id": concept_id,
                "concept_title": metadata.get("concept_title", ""),
                "chapter": str(metadata.get("chapter", "")),
                "section": str(metadata.get("section", "")),
                "text": result["document"],
                "latex": latex,
                "images": self.get_concept_images(concept_id),
                "distance": result["distance"],
                "prerequisites": prerequisites,
                "all_prerequisites_met": all_met,
                "ready_to_learn": all_met,
            })

        return enriched

    # ── Single concept lookup ─────────────────────────────────────

    def get_concept_by_id(self, concept_id: str) -> Optional[dict]:
        """Retrieve a specific concept by ID from ChromaDB."""
        try:
            result = self.collection.get(ids=[concept_id])
            if result and result["ids"]:
                return {
                    "concept_id": result["ids"][0],
                    "text": result["documents"][0] if result["documents"] else "",
                    "metadata": result["metadatas"][0] if result["metadatas"] else {},
                }
        except Exception:
            pass
        return None

    def get_concept_detail(self, concept_id: str) -> Optional[dict]:
        """Full concept data with prerequisites and dependents from graph."""
        concept = self.get_concept_by_id(concept_id)
        if not concept:
            return None

        metadata = concept["metadata"]

        # Get prerequisites (parents) and dependents (children) from graph
        prerequisites = []
        dependents = []
        if concept_id in self.graph:
            prerequisites = sorted(self.graph.predecessors(concept_id))
            dependents = sorted(self.graph.successors(concept_id))

        return {
            "concept_id": concept_id,
            "concept_title": metadata.get("concept_title", ""),
            "chapter": str(metadata.get("chapter", "")),
            "section": str(metadata.get("section", "")),
            "text": concept["text"],
            "latex": self._get_latex(concept_id),
            "images": self.get_concept_images(concept_id),
            "prerequisites": prerequisites,
            "dependents": dependents,
        }

    # ── Frontier / next concepts ──────────────────────────────────

    def get_next_concepts(self, mastered_concepts: list[str]) -> list[dict]:
        """
        Find all concepts that are now "ready to learn":
        all prerequisites met, but the concept itself is not yet mastered.
        """
        mastered_set = set(mastered_concepts)
        ready = []

        for node in self.graph.nodes:
            if node in mastered_set:
                continue
            prereqs = list(self.graph.predecessors(node))
            if all(p in mastered_set for p in prereqs):
                node_data = self.graph.nodes[node]
                ready.append({
                    "concept_id": node,
                    "concept_title": node_data.get("title", ""),
                    "chapter": str(node_data.get("chapter", "")),
                    "section": str(node_data.get("section", "")),
                })

        return ready

    # ── Transitive prerequisites ──────────────────────────────────

    def get_all_prerequisites(self, concept_id: str) -> list[str]:
        """All prerequisites (transitive closure) via nx.ancestors()."""
        if concept_id not in self.graph:
            return []
        return sorted(nx.ancestors(self.graph, concept_id))

    # ── Graph info ────────────────────────────────────────────────

    def get_graph_info(self) -> dict:
        """Graph statistics including root and leaf concepts."""
        stats = get_graph_stats(self.graph)
        root_concepts = sorted(
            n for n in self.graph.nodes if self.graph.in_degree(n) == 0
        )
        leaf_concepts = sorted(
            n for n in self.graph.nodes if self.graph.out_degree(n) == 0
        )
        stats["root_concepts"] = root_concepts
        stats["leaf_concepts"] = leaf_concepts
        return stats

    def get_all_nodes(self) -> list[dict]:
        """List all concept nodes with their graph properties."""
        nodes = []
        for node in sorted(self.graph.nodes):
            data = self.graph.nodes[node]
            nodes.append({
                "concept_id": node,
                "title": data.get("title", ""),
                "chapter": str(data.get("chapter", "")),
                "section": str(data.get("section", "")),
                "in_degree": self.graph.in_degree(node),
                "out_degree": self.graph.out_degree(node),
            })
        return nodes

    # ── Graph traversal ──────────────────────────────────────────

    def get_learning_path(self, target_concept_id: str, mastered_concepts: list[str]) -> dict:
        """
        Compute the optimal learning path to reach a target concept.
        Returns ordered list of concepts to learn, skipping mastered ones.
        """
        if target_concept_id not in self.graph:
            return {"target": target_concept_id, "path": [], "total_steps": 0}

        mastered_set = set(mastered_concepts)
        path_ids = get_learning_path(self.graph, target_concept_id, mastered_set)

        path = []
        for cid in path_ids:
            node_data = self.graph.nodes.get(cid, {})
            path.append({
                "concept_id": cid,
                "concept_title": node_data.get("title", ""),
                "chapter": str(node_data.get("chapter", "")),
                "section": str(node_data.get("section", "")),
            })

        return {
            "target": target_concept_id,
            "path": path,
            "total_steps": len(path),
        }

    def get_topological_order(self) -> list[dict]:
        """Return all concepts in valid learning sequence (topological order)."""
        order = get_topological_order(self.graph)
        depths = get_concept_depth(self.graph)

        result = []
        for cid in order:
            node_data = self.graph.nodes.get(cid, {})
            result.append({
                "concept_id": cid,
                "concept_title": node_data.get("title", ""),
                "chapter": str(node_data.get("chapter", "")),
                "section": str(node_data.get("section", "")),
                "depth": depths.get(cid, 0),
            })
        return result

    def get_locked_concepts(self, mastered_concepts: list[str]) -> list[dict]:
        """
        Find all concepts that are NOT ready to learn:
        at least one prerequisite is not mastered.
        """
        mastered_set = set(mastered_concepts)
        locked = []

        for node in self.graph.nodes:
            if node in mastered_set:
                continue
            prereqs = list(self.graph.predecessors(node))
            unmet = [p for p in prereqs if p not in mastered_set]
            if unmet:
                node_data = self.graph.nodes[node]
                locked.append({
                    "concept_id": node,
                    "concept_title": node_data.get("title", ""),
                    "chapter": str(node_data.get("chapter", "")),
                    "section": str(node_data.get("section", "")),
                    "missing_prerequisites": unmet,
                })

        return locked

    # ── Images ────────────────────────────────────────────────────

    def get_concept_images(self, concept_id: str) -> list[dict]:
        """Get image metadata with URLs for a concept."""
        raw_images = self._image_map.get(concept_id, [])
        return [
            {
                "filename": img["filename"],
                "url": f"/images/{concept_id}/{img['filename']}",
                "width": img["width"],
                "height": img["height"],
                "image_type": img["image_type"],
                "page": img["page"],
            }
            for img in raw_images
        ]

    # ── Internal helpers ──────────────────────────────────────────

    def _get_latex(self, concept_id: str) -> list[str]:
        """Get LaTeX expressions for a concept from the preloaded map."""
        return self._latex_map.get(concept_id, [])
