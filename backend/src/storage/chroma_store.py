"""
ChromaDB Store — manages the vector database for concept block storage and retrieval.
Uses OpenAI embeddings for vector representation.

Embedding strategy: LaTeX-heavy math sections can exceed the 8192-token embedding limit.
We pre-compute embeddings from a 3000-word truncation of each text (safe: ~6300 tokens)
but store the FULL text as the ChromaDB document — no data loss. When `embeddings=` is
passed to collection.upsert(), ChromaDB skips its own embedding call and stores the
documents as-is.
"""

import json
import logging
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
import openai

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    EMBEDDING_MODEL,
    CHROMA_COLLECTION_NAME,
    CHROMA_DIR,
    LATEX_METADATA_SIZE_WARN_THRESHOLD,
)
from models import ConceptBlock, DependencyEdge

logger = logging.getLogger(__name__)

# Max words used when computing the embedding (not for storage).
# LaTeX math can run 3–4 tokens/word in dense sections; 2000w × 4 = 8000 tokens < 8192-token limit.
_EMBED_MAX_WORDS = 2000

# Max texts per single embeddings API call.
# 20 texts × 6300 tokens ≈ 126,000 tokens — well under the 300,000-token request limit.
_EMBED_API_BATCH = 20


def _compute_embeddings(texts: list[str]) -> list[list[float]]:
    """Call the OpenAI embeddings API, sub-batching to stay under the 300k-token limit."""
    client = openai.OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL or None,
    )
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_API_BATCH):
        sub = texts[i : i + _EMBED_API_BATCH]
        response = client.embeddings.create(input=sub, model=EMBEDDING_MODEL)
        all_embeddings.extend(
            item.embedding for item in sorted(response.data, key=lambda d: d.index)
        )
    return all_embeddings


def initialize_collection(
    persist_directory: Optional[Path] = None,
    collection_name: Optional[str] = None,
) -> chromadb.Collection:
    """
    Create or get a ChromaDB collection with OpenAI embedding function.
    Uses PersistentClient for disk persistence.
    """
    persist_dir = str(persist_directory or CHROMA_DIR)
    coll_name = collection_name or CHROMA_COLLECTION_NAME

    # Create persistent client
    client = chromadb.PersistentClient(path=persist_dir)

    # Create OpenAI embedding function
    embedding_fn = OpenAIEmbeddingFunction(
        api_key=OPENAI_API_KEY,
        api_base=OPENAI_BASE_URL,
        model_name=EMBEDDING_MODEL,
    )

    # Get or create collection
    collection = client.get_or_create_collection(
        name=coll_name,
        embedding_function=embedding_fn,
        metadata={"description": "OpenStax Math concept blocks for adaptive learning"},
    )

    return collection


def store_concept_blocks(
    collection: chromadb.Collection,
    concept_blocks: list[ConceptBlock],
    dependency_edges: Optional[list[DependencyEdge]] = None,
    batch_size: int = 50,
) -> int:
    """
    Upsert all concept blocks into ChromaDB.
    Returns the number of blocks stored.

    Each document:
      - id: concept_id
      - document: instructional text
      - metadata: flat key-value pairs for filtering, including prerequisites/dependents
    """
    if not concept_blocks:
        return 0

    # Build prerequisite and dependent maps from dependency edges
    prereq_map = {}
    dependent_map = {}
    if dependency_edges:
        for edge in dependency_edges:
            prereq_map[edge.concept_id] = edge.prerequisites
            for prereq_id in edge.prerequisites:
                dependent_map.setdefault(prereq_id, []).append(edge.concept_id)

    stored = 0

    # Process in batches
    for i in range(0, len(concept_blocks), batch_size):
        batch = concept_blocks[i:i + batch_size]

        ids = []
        documents = []
        metadatas = []

        embed_inputs = []  # truncated text for embedding (token-safe)

        for block in batch:
            prereqs = prereq_map.get(block.concept_id, [])
            dependents = dependent_map.get(block.concept_id, [])

            latex_json = json.dumps(block.latex, ensure_ascii=False)
            latex_byte_len = len(latex_json.encode("utf-8"))
            if latex_byte_len > LATEX_METADATA_SIZE_WARN_THRESHOLD:
                logger.warning(
                    "latex_expressions for concept %s is %d bytes — approaching metadata limit",
                    block.concept_id,
                    latex_byte_len,
                )

            # Embed only the first _EMBED_MAX_WORDS words (token-safe for LaTeX-heavy text),
            # but store block.text in full — no data loss for the LLM context.
            words = block.text.split()
            embed_inputs.append(
                " ".join(words[:_EMBED_MAX_WORDS]) if len(words) > _EMBED_MAX_WORDS else block.text
            )

            ids.append(block.concept_id)
            documents.append(block.text)  # full text — no truncation
            metadatas.append({
                "book_slug": block.book_slug,
                "book": block.book,
                "chapter": block.chapter,
                "section": block.section,
                "concept_title": block.concept_title,
                "word_count": len(block.text.split()),
                "source_pages_start": block.source_pages[0] if block.source_pages else 0,
                "source_pages_end": block.source_pages[-1] if block.source_pages else 0,
                "latex_count": len(block.latex),
                "latex_expressions": latex_json,
                "prerequisites": ", ".join(prereqs) if prereqs else "",
                "dependents": ", ".join(dependents) if dependents else "",
                "prerequisite_count": len(prereqs),
            })

        # Pre-compute embeddings from truncated text, then upsert with full documents.
        # Passing embeddings= tells ChromaDB to skip its own embedding call and store
        # documents as-is — so the full text is persisted without token-limit errors.
        embeddings = _compute_embeddings(embed_inputs)
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        stored += len(batch)
        logger.info("Stored batch %d: %d concepts", i // batch_size + 1, len(batch))

    return stored


def query_similar_concepts(
    collection: chromadb.Collection,
    query_text: str,
    n_results: int = 5,
    where_filter: Optional[dict] = None,
) -> list[dict]:
    """
    Query ChromaDB for similar concept blocks.
    Returns list of result dicts with id, document, metadata, distance.
    """
    kwargs = {
        "query_texts": [query_text],
        "n_results": n_results,
    }
    if where_filter:
        kwargs["where"] = where_filter

    results = collection.query(**kwargs)

    output = []
    if results and results["ids"]:
        for i, cid in enumerate(results["ids"][0]):
            output.append({
                "id": cid,
                "document": results["documents"][0][i] if results["documents"] else "",
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0,
            })

    return output


def get_collection_stats(collection: chromadb.Collection) -> dict:
    """Return stats about the ChromaDB collection."""
    return {
        "name": collection.name,
        "count": collection.count(),
    }
