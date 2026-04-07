# ruff: noqa: E402
"""
ADA Hybrid Engine Pipeline — Main Orchestrator

Two pipeline modes:

1. WHOLE-PDF (default, --whole-pdf):
   Submits entire PDF to Mathpix /v3/pdf. Gets back a Mathpix Markdown (MMD)
   document with text + formulas + images in exact reading order. Parses by
   section headings and stores each section with inline image context.

2. LEGACY (--no-whole-pdf):
   Original per-page Mathpix /v3/text pipeline (page-by-page OCR + PyMuPDF
   section detection). Still available for testing or comparison.
"""

import logging
import sys
import os
import time
import argparse

# Ensure src is on the Python path
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from config import (
    get_book_config,
    get_pdf_path,
    OUTPUT_DIR,
    BOOK_REGISTRY,
)
from extraction.domain_models import PipelineOutput

from extraction.pdf_reader import extract_all_pages
from extraction.section_detector import detect_sections
from extraction.concept_builder import build_concept_blocks, build_concept_blocks_from_mmd
from extraction.mmd_parser import parse_mmd

from images.mathpix_client import submit_pdf, wait_for_pdf_completion, download_pdf_mmd_zip

from graph.dependency_builder import build_dependency_edges
from graph.graph_store import create_graph, validate_graph, save_graph_json, get_graph_stats

from storage.json_exporter import export_full_output, export_individual_files


from validation.validator import validate_all_blocks, get_validation_summary



def run_whole_pdf_pipeline(
    book_code: str,
    force: bool = False,
    pdf_id: str | None = None,
    max_sections: int | None = None,
) -> PipelineOutput:
    """
    Whole-PDF pipeline using Mathpix /v3/pdf endpoint.

    Stages:
      A. Submit PDF to Mathpix → get back one MMD document + extracted images
      B. Parse MMD into per-section MmdSection objects (last-occurrence TOC dedup)
      C. Vision-annotate all images referenced in the MMD
      D. Build ConceptBlock objects (images embedded as alt-text descriptions)
      E. Build dependency graph
      F. Validate
      G. Export JSON outputs

    Args:
        book_code: Book code, e.g. "PREALG"
        force: If True, re-submit to Mathpix even if a cached MMD exists
        pdf_id: Optional pre-existing Mathpix pdf_id — skips the upload step.
                Useful when the upload fails on Windows (WinError 10053).
                Get this by uploading the PDF manually at https://snip.mathpix.com
    """
    start_time = time.time()

    print(f"\n{'='*60}")
    print("ADA Whole-PDF Pipeline (Mathpix /v3/pdf)")
    print(f"Processing: {book_code}")
    print(f"{'='*60}\n")

    config = get_book_config(book_code)
    slug = config["book_slug"]
    pdf_path = get_pdf_path(book_code)
    out_dir = OUTPUT_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    mmd_cache = out_dir / "book.mmd"
    image_dir = out_dir / "mathpix_extracted"

    print(f"Book: {config['title']}")
    print(f"PDF:  {pdf_path}")
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # ── Stage A: Mathpix whole-PDF submission ────────────────────────
    print("\n[Stage A] Submitting PDF to Mathpix /v3/pdf...")
    if mmd_cache.exists() and not force:
        logger.info("Using cached MMD: %s", mmd_cache)
        print(f"  Using cached MMD: {mmd_cache}")
        mmd_text = mmd_cache.read_text(encoding="utf-8")
    else:
        if pdf_id:
            # User supplied a pre-existing pdf_id — skip the upload entirely
            print(f"  Using supplied pdf_id: {pdf_id}")
            print("  Skipping upload — polling until Mathpix job is complete...")
        else:
            logger.info("Submitting %s to Mathpix /v3/pdf ...", slug)
            pdf_id = submit_pdf(pdf_path)
            print(f"  pdf_id: {pdf_id}")
            print("  Polling Mathpix (may take 10–30 min for large books)...")
        wait_for_pdf_completion(pdf_id)
        mmd_text = download_pdf_mmd_zip(pdf_id, image_dir)
        mmd_cache.write_text(mmd_text, encoding="utf-8")
        logger.info("Saved book.mmd and %d images", len(list(image_dir.iterdir())) if image_dir.exists() else 0)
        print(f"  MMD cached to: {mmd_cache}")

    print(f"  MMD size: {len(mmd_text):,} characters")

    # ── Stage B: Parse MMD into sections ────────────────────────────
    print("\n[Stage B] Parsing MMD into sections...")
    sections = parse_mmd(
        mmd_text,
        section_pattern=config["section_pattern"],
        exercise_marker_pattern=config["exercise_marker_pattern"],
    )                                             # R4: last-occurrence dedup inside
    print(f"  Parsed {len(sections)} instructional sections")
    if sections:
        print(f"  First: {sections[0].section_number} — {sections[0].section_title}")
        print(f"  Last:  {sections[-1].section_number} — {sections[-1].section_title}")
        chapters: dict[int, int] = {}
        for s in sections:
            chapters[s.chapter_number] = chapters.get(s.chapter_number, 0) + 1
        print(f"  Chapters: {dict(sorted(chapters.items()))}")

    if max_sections is not None:
        sections = sections[:max_sections]
        print(f"  [--max-sections] Limiting to first {len(sections)} sections")

    # ── Stage C: Images ─────────────────────────────────────────────
    # Images are Mathpix CDN URLs embedded inline in book.mmd.
    # chunk_builder.py downloads them and stores ChunkImage rows in PostgreSQL.
    print("\n[Stage C] Images embedded in book.mmd by Mathpix.")

    # ── Stage D: Build concept blocks ───────────────────────────────
    print("\n[Stage D] Building concept blocks...")
    concept_blocks = build_concept_blocks_from_mmd(sections, config)
    print(f"  Built {len(concept_blocks)} concept blocks")
    if concept_blocks:
        total_words = sum(len(b.text.split()) for b in concept_blocks)
        avg_words = total_words // len(concept_blocks)
        print(f"  Total words: {total_words:,}  (avg {avg_words}/block)")

    # ── Stage E: Build dependency graph ─────────────────────────────
    print("\n[Stage E] Building dependency graph...")
    dependency_edges = build_dependency_edges(concept_blocks)
    total_edges = sum(len(e.prerequisites) for e in dependency_edges)
    graph = create_graph(concept_blocks, dependency_edges)
    graph_issues = validate_graph(graph)
    graph_stats = get_graph_stats(graph)
    print(f"  Graph: {graph_stats['num_nodes']} nodes, {graph_stats['num_edges']} edges")
    print(f"  Is DAG: {graph_stats['is_dag']}  |  Root nodes: {graph_stats['num_root_nodes']}")
    if graph_issues:
        print(f"  Issues: {len(graph_issues)}")

    # ── Stage F: Validate ────────────────────────────────────────────
    print("\n[Stage F] Validating concept blocks...")
    validation_results = validate_all_blocks(concept_blocks)
    summary = get_validation_summary(validation_results)
    print(f"  Valid: {summary['valid_blocks']}/{summary['total_blocks']} ({summary['validation_rate']}%)")

    # ── Stage G: Export outputs ──────────────────────────────────────
    print("\n[Stage G] Exporting outputs...")
    output = PipelineOutput(
        concept_blocks=concept_blocks,
        dependency_edges=dependency_edges,
        validation_report=validation_results,
    )
    export_full_output(output, out_dir / "full_output.json")
    export_individual_files(output, out_dir)
    save_graph_json(graph, out_dir / "dependency_graph.json")

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"Whole-PDF pipeline complete for {book_code}")
    print(f"{'='*60}")
    print(f"  Concept blocks:   {len(concept_blocks)}")
    print(f"  Dependency edges: {total_edges}")
    print(f"  Valid blocks:     {summary['valid_blocks']}/{summary['total_blocks']}")
    print(f"  Output directory: {out_dir}")
    print(f"  Time elapsed:     {elapsed:.1f}s")
    print()

    return output


def run_pipeline(book_code: str, no_mathpix: bool = False, use_llm: bool = False) -> PipelineOutput:
    """
    Run the complete pipeline for one book.

    Args:
        book_code: The book code (e.g., "PREALG")
        no_mathpix: If True, skip Mathpix OCR and use PyMuPDF text only

    Returns:
        PipelineOutput with all results
    """
    start_time = time.time()

    # ── Step 0: Load configuration ──────────────────────────────────
    print(f"\n{'='*60}")
    print("ADA Hybrid Engine Pipeline")
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
    print("\n[Step 1/7] Extracting pages from PDF...")
    pages = extract_all_pages(pdf_path)
    print(f"  Extracted {len(pages)} pages")

    # ── Step 2: Detect section boundaries ───────────────────────────
    print("\n[Step 2/7] Detecting section boundaries...")
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
    print(f"\n[Step 3/7] Building concept blocks ({mathpix_label}{llm_label})...")
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
    print("\n[Step 4/7] Building dependency graph...")
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

    # ── Step 5: Validate concept blocks ─────────────────────────────
    print("\n[Step 5/6] Validating concept blocks...")
    validation_results = validate_all_blocks(concept_blocks)
    summary = get_validation_summary(validation_results)
    print(f"  Valid:   {summary['valid_blocks']}/{summary['total_blocks']} ({summary['validation_rate']}%)")
    print(f"  Invalid: {summary['invalid_blocks']}")
    if summary['issue_counts']:
        print("  Issues:")
        for issue_type, count in summary['issue_counts'].items():
            print(f"    - {issue_type}: {count}")

    # ── Step 6: Export outputs ──────────────────────────────────────
    print("\n[Step 6/6] Exporting outputs...")

    output = PipelineOutput(
        concept_blocks=concept_blocks,
        dependency_edges=dependency_edges,
        validation_report=validation_results,
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
    print(f"  Output directory:  {book_output_dir}")
    print(f"  Time elapsed:      {elapsed:.1f}s")
    print()

    return output


def run_all_books(no_mathpix: bool = False, use_llm: bool = False) -> dict:
    """Run the pipeline for all 16 books."""
    results = {}
    for book_code in BOOK_REGISTRY:
        try:
            print(f"\n{'#'*60}")
            print(f"# Processing {book_code}")
            print(f"{'#'*60}")
            output = run_pipeline(book_code, no_mathpix=no_mathpix, use_llm=use_llm)
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
    parser.add_argument(
        "--whole-pdf",
        action="store_true",
        default=True,
        help="Use Mathpix /v3/pdf whole-PDF extraction (default; one API call per book)",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        default=False,
        help="Use legacy per-page Mathpix pipeline instead of whole-PDF (not recommended)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force re-submission to Mathpix even if cached MMD exists (used with whole-pdf pipeline)",
    )
    parser.add_argument(
        "--pdf-id",
        default=None,
        dest="pdf_id",
        help=(
            "Skip PDF upload and use this Mathpix pdf_id directly. "
            "Useful when the upload fails on Windows (WinError 10053). "
            "Upload the PDF manually at https://snip.mathpix.com to get a pdf_id."
        ),
    )
    parser.add_argument(
        "--max-sections",
        type=int,
        default=None,
        dest="max_sections",
        help="Limit processing to the first N sections (useful for testing image extraction).",
    )
    parser.add_argument(
        "--chunks",
        action="store_true",
        default=False,
        help=(
            "Run chunk-based extraction pipeline (new architecture). "
            "Reads book.mmd, embeds subsection chunks, and saves to PostgreSQL concept_chunks table. "
            "Requires OPENAI_API_KEY and DATABASE_URL in backend/.env."
        ),
    )
    args = parser.parse_args()

    if args.list_books:
        print("Available book codes:")
        for code, config in BOOK_REGISTRY.items():
            print(f"  {code:12s} -> {config['title']}")
        sys.exit(0)

    # ── Chunk-based extraction pipeline (new architecture) ────────────────────
    if args.chunks:
        import asyncio as _asyncio
        from config import OUTPUT_DIR as _OUTPUT_DIR, BOOK_CODE_MAP as _BOOK_CODE_MAP
        from extraction.chunk_builder import build_chunks as _build_chunks
        from db.connection import async_session_factory as _async_session_factory

        # Resolve book slug: accept either book_code (e.g. PREALG) or book_slug (e.g. prealgebra)
        raw_book = args.book
        if raw_book in BOOK_REGISTRY:
            _book_slug = BOOK_REGISTRY[raw_book]["book_slug"]
        elif raw_book in _BOOK_CODE_MAP:
            _book_slug = raw_book  # already a slug
        else:
            # Try matching as a slug value
            matched = [slug for slug in _BOOK_CODE_MAP if slug == raw_book]
            if matched:
                _book_slug = matched[0]
            else:
                print(f"ERROR: Unknown book code or slug: {raw_book!r}. Use --list-books to see options.")
                sys.exit(1)

        _mmd_path = _OUTPUT_DIR / _book_slug / "book.mmd"
        if not _mmd_path.exists():
            print(f"ERROR: {_mmd_path} not found.")
            print("Run the whole-PDF Mathpix pipeline first (without --chunks) to generate book.mmd.")
            sys.exit(1)

        logger.info("Starting chunk pipeline for book_slug=%s, mmd=%s", _book_slug, _mmd_path)

        async def _run_chunks():
            async with _async_session_factory() as session:
                await _build_chunks(_book_slug, _mmd_path, session, rebuild=True)

        _asyncio.run(_run_chunks())
        sys.exit(0)

    # Clear Mathpix cache if requested (legacy pipeline only)
    if args.clear_mathpix_cache and args.book != "ALL":
        book_config = get_book_config(args.book)
        cache_dir = OUTPUT_DIR / book_config["book_slug"] / "mathpix_cache"
        if cache_dir.exists():
            import shutil
            shutil.rmtree(cache_dir)
            print(f"Cleared Mathpix cache: {cache_dir}")

    if not args.legacy:
        # ── Whole-PDF pipeline (default) ─────────────────────────────
        if args.book == "ALL":
            results = {}
            for book_code in BOOK_REGISTRY:
                try:
                    print(f"\n{'#'*60}\n# Processing {book_code}\n{'#'*60}")
                    output = run_whole_pdf_pipeline(
                        book_code, force=args.force,
                    )
                    results[book_code] = {
                        "status": "SUCCESS",
                        "concept_count": len(output.concept_blocks),
                        "edge_count": sum(len(e.prerequisites) for e in output.dependency_edges),
                    }
                except Exception as e:
                    logger.error("FAILED: %s: %s", book_code, e)
                    results[book_code] = {"status": "FAILED", "error": str(e)}
            print("\n\nFinal Summary:")
            for code, result in results.items():
                status = result["status"]
                if status == "SUCCESS":
                    print(f"  {code:12s}: {status} — {result['concept_count']} concepts, {result['edge_count']} edges")
                else:
                    print(f"  {code:12s}: {status} — {result.get('error', 'unknown')}")
        else:
            run_whole_pdf_pipeline(args.book, force=args.force, pdf_id=args.pdf_id, max_sections=args.max_sections)
    else:
        # ── Legacy pipeline (opt-in via --legacy) ────────────────────
        if args.book == "ALL":
            results = run_all_books(no_mathpix=args.no_mathpix, use_llm=args.use_llm)
            print("\n\nFinal Summary:")
            for code, result in results.items():
                status = result["status"]
                if status == "SUCCESS":
                    print(f"  {code:12s}: {status} — {result['concept_count']} concepts, {result['edge_count']} edges")
                else:
                    print(f"  {code:12s}: {status} — {result.get('error', 'unknown')}")
        else:
            run_pipeline(args.book, no_mathpix=args.no_mathpix, use_llm=args.use_llm)
