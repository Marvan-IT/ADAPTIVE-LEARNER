"""
ADA Hybrid Engine Pipeline — Main Orchestrator

Processes a single textbook PDF through the complete pipeline:
  1. Extract pages (text + fonts + images)
  2. Detect section boundaries
  3. Build concept blocks (one per section)
  4. Build dependency graph
  5. Store in ChromaDB
  6. Validate concept blocks
  7. Build Mathpix image plan
  8. Export all outputs to JSON
"""

import sys
import os
import time
import argparse
from pathlib import Path

# Ensure src is on the Python path
sys.path.insert(0, os.path.dirname(__file__))

from config import (
    get_book_config,
    get_pdf_path,
    OUTPUT_DIR,
    CHROMA_DIR,
    BOOK_REGISTRY,
)
from models import PipelineOutput

from extraction.pdf_reader import extract_all_pages
from extraction.section_detector import detect_sections
from extraction.concept_builder import build_concept_blocks

from graph.dependency_builder import build_dependency_edges
from graph.graph_store import create_graph, validate_graph, save_graph_json, get_graph_stats

from storage.chroma_store import initialize_collection, store_concept_blocks, get_collection_stats
from storage.json_exporter import export_full_output, export_individual_files

from images.image_extractor import extract_image_decisions

from validation.validator import validate_all_blocks, get_validation_summary


def run_pipeline(book_code: str, skip_chroma: bool = False, no_mathpix: bool = False, use_llm: bool = False) -> PipelineOutput:
    """
    Run the complete pipeline for one book.

    Args:
        book_code: The book code (e.g., "PREALG")
        skip_chroma: If True, skip ChromaDB storage (for testing without OpenAI key)
        no_mathpix: If True, skip Mathpix OCR and use PyMuPDF text only

    Returns:
        PipelineOutput with all results
    """
    start_time = time.time()

    # ── Step 0: Load configuration ──────────────────────────────────
    print(f"\n{'='*60}")
    print(f"ADA Hybrid Engine Pipeline")
    print(f"Processing: {book_code}")
    print(f"{'='*60}\n")

    book_config = get_book_config(book_code)
    pdf_path = get_pdf_path(book_code)
    print(f"Book: {book_config['title']}")
    print(f"PDF:  {pdf_path}")
    print(f"PDF exists: {pdf_path.exists()}")

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # ── Step 1: Extract all pages ───────────────────────────────────
    print(f"\n[Step 1/8] Extracting pages from PDF...")
    pages = extract_all_pages(pdf_path)
    print(f"  Extracted {len(pages)} pages")

    # ── Step 2: Detect section boundaries ───────────────────────────
    print(f"\n[Step 2/8] Detecting section boundaries...")
    sections = detect_sections(pages, book_config)
    print(f"  Found {len(sections)} instructional sections")

    if sections:
        print(f"  First: {sections[0].section_number} — {sections[0].section_title}")
        print(f"  Last:  {sections[-1].section_number} — {sections[-1].section_title}")

        # Show chapter breakdown
        chapters = {}
        for s in sections:
            ch = s.chapter_number
            chapters[ch] = chapters.get(ch, 0) + 1
        print(f"  Chapters: {dict(sorted(chapters.items()))}")

    # ── Step 3: Build concept blocks ────────────────────────────────
    use_mathpix = not no_mathpix
    mathpix_label = "with Mathpix OCR" if use_mathpix else "with PyMuPDF only"
    llm_label = " + LLM extraction" if use_llm else ""
    print(f"\n[Step 3/8] Building concept blocks ({mathpix_label}{llm_label})...")
    concept_blocks = build_concept_blocks(
        sections, pages, book_config,
        use_mathpix=use_mathpix,
        pdf_path=pdf_path,
        use_llm=use_llm,
    )
    print(f"  Built {len(concept_blocks)} concept blocks")

    if concept_blocks:
        total_words = sum(len(b.text.split()) for b in concept_blocks)
        avg_words = total_words // len(concept_blocks)
        print(f"  Total words: {total_words:,}")
        print(f"  Average words per block: {avg_words}")
        print(f"  Total LaTeX expressions: {sum(len(b.latex) for b in concept_blocks)}")

    # ── Step 4: Build dependency graph ──────────────────────────────
    print(f"\n[Step 4/8] Building dependency graph...")
    dependency_edges = build_dependency_edges(concept_blocks)
    total_edges = sum(len(e.prerequisites) for e in dependency_edges)
    print(f"  Created {len(dependency_edges)} edge entries ({total_edges} total prerequisite links)")

    # Create and validate NetworkX graph
    graph = create_graph(concept_blocks, dependency_edges)
    graph_issues = validate_graph(graph)
    graph_stats = get_graph_stats(graph)
    print(f"  Graph: {graph_stats['num_nodes']} nodes, {graph_stats['num_edges']} edges")
    print(f"  Is DAG: {graph_stats['is_dag']}")
    print(f"  Root nodes: {graph_stats['num_root_nodes']}")
    print(f"  Max depth: {graph_stats['max_depth']}")
    if graph_issues:
        print(f"  Issues: {len(graph_issues)}")
        for issue in graph_issues[:5]:
            print(f"    - {issue}")

    # ── Step 5: Store in ChromaDB ───────────────────────────────────
    if not skip_chroma:
        print(f"\n[Step 5/8] Storing in ChromaDB...")
        try:
            book_output_dir = OUTPUT_DIR / book_config["book_slug"]
            chroma_dir = book_output_dir / "chroma_db"
            collection = initialize_collection(
                persist_directory=chroma_dir,
                collection_name=f"concepts_{book_config['book_slug']}",
            )
            stored_count = store_concept_blocks(collection, concept_blocks, dependency_edges)
            stats = get_collection_stats(collection)
            print(f"  Stored {stored_count} concepts in ChromaDB")
            print(f"  Collection '{stats['name']}' has {stats['count']} documents")
        except Exception as e:
            print(f"  ChromaDB storage failed: {e}")
            print(f"  Continuing without ChromaDB...")
    else:
        print(f"\n[Step 5/8] Skipping ChromaDB (--skip-chroma flag)")

    # ── Step 6: Validate concept blocks ─────────────────────────────
    print(f"\n[Step 6/8] Validating concept blocks...")
    validation_results = validate_all_blocks(concept_blocks)
    summary = get_validation_summary(validation_results)
    print(f"  Valid:   {summary['valid_blocks']}/{summary['total_blocks']} ({summary['validation_rate']}%)")
    print(f"  Invalid: {summary['invalid_blocks']}")
    if summary['issue_counts']:
        print(f"  Issues:")
        for issue_type, count in summary['issue_counts'].items():
            print(f"    - {issue_type}: {count}")

    # ── Step 7: Build Mathpix image plan ────────────────────────────
    print(f"\n[Step 7/8] Building Mathpix image plan...")
    image_decisions = extract_image_decisions(pdf_path, pages, sections)
    mathpix_count = sum(1 for d in image_decisions if d.action == "SEND_TO_MATHPIX")
    skip_count = sum(1 for d in image_decisions if d.action == "SKIP")
    print(f"  Total images found: {len(image_decisions)}")
    print(f"  To send to Mathpix: {mathpix_count}")
    print(f"  To skip: {skip_count}")

    # ── Step 8: Export outputs ──────────────────────────────────────
    print(f"\n[Step 8/8] Exporting outputs...")

    output = PipelineOutput(
        concept_blocks=concept_blocks,
        dependency_edges=dependency_edges,
        validation_report=validation_results,
        mathpix_plan=image_decisions,
    )

    book_output_dir = OUTPUT_DIR / book_config["book_slug"]

    # Export full combined JSON
    export_full_output(output, book_output_dir / "full_output.json")

    # Export individual files
    export_individual_files(output, book_output_dir)

    # Save dependency graph
    save_graph_json(graph, book_output_dir / "dependency_graph.json")

    # ── Summary ─────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"Pipeline complete for {book_code}")
    print(f"{'='*60}")
    print(f"  Concept blocks:    {len(concept_blocks)}")
    print(f"  Dependency edges:  {total_edges}")
    print(f"  Valid blocks:      {summary['valid_blocks']}/{summary['total_blocks']}")
    print(f"  Mathpix images:    {mathpix_count}")
    print(f"  Output directory:  {book_output_dir}")
    print(f"  Time elapsed:      {elapsed:.1f}s")
    print()

    return output


def run_all_books(skip_chroma: bool = False, no_mathpix: bool = False, use_llm: bool = False) -> dict:
    """Run the pipeline for all 16 books."""
    results = {}
    for book_code in BOOK_REGISTRY:
        try:
            print(f"\n{'#'*60}")
            print(f"# Processing {book_code}")
            print(f"{'#'*60}")
            output = run_pipeline(book_code, skip_chroma=skip_chroma, no_mathpix=no_mathpix, use_llm=use_llm)
            results[book_code] = {
                "status": "SUCCESS",
                "concept_count": len(output.concept_blocks),
                "edge_count": sum(len(e.prerequisites) for e in output.dependency_edges),
            }
        except Exception as e:
            print(f"FAILED: {book_code}: {e}")
            results[book_code] = {
                "status": "FAILED",
                "error": str(e),
            }
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ADA Hybrid Engine Pipeline")
    parser.add_argument(
        "--book",
        default="PREALG",
        help="Book code to process (e.g., PREALG, ELEMALG, ALL)",
    )
    parser.add_argument(
        "--skip-chroma",
        action="store_true",
        help="Skip ChromaDB storage (useful for testing without OpenAI API key)",
    )
    parser.add_argument(
        "--no-mathpix",
        action="store_true",
        help="Skip Mathpix OCR; use PyMuPDF text only (faster but no math extraction)",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        default=False,
        help="Use GPT LLM extraction instead of regex content filter (higher quality)",
    )
    parser.add_argument(
        "--clear-mathpix-cache",
        action="store_true",
        help="Clear Mathpix cache before processing (forces re-OCR of all pages)",
    )
    parser.add_argument(
        "--list-books",
        action="store_true",
        help="List all available book codes and exit",
    )
    args = parser.parse_args()

    if args.list_books:
        print("Available book codes:")
        for code, config in BOOK_REGISTRY.items():
            print(f"  {code:12s} -> {config['title']}")
        sys.exit(0)

    # Clear Mathpix cache if requested
    if args.clear_mathpix_cache and args.book != "ALL":
        book_config = get_book_config(args.book)
        cache_dir = OUTPUT_DIR / book_config["book_slug"] / "mathpix_cache"
        if cache_dir.exists():
            import shutil
            shutil.rmtree(cache_dir)
            print(f"Cleared Mathpix cache: {cache_dir}")

    if args.book == "ALL":
        results = run_all_books(skip_chroma=args.skip_chroma, no_mathpix=args.no_mathpix, use_llm=args.use_llm)
        print("\n\nFinal Summary:")
        for code, result in results.items():
            status = result["status"]
            if status == "SUCCESS":
                print(f"  {code:12s}: {status} — {result['concept_count']} concepts, {result['edge_count']} edges")
            else:
                print(f"  {code:12s}: {status} — {result.get('error', 'unknown')}")
    else:
        run_pipeline(args.book, skip_chroma=args.skip_chroma, no_mathpix=args.no_mathpix, use_llm=args.use_llm)
