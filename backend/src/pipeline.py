"""
ADA Hybrid Engine Pipeline — Main Orchestrator

Two pipeline modes:

1. WHOLE-PDF (default, --whole-pdf):
   Submits entire PDF to Mathpix /v3/pdf. Gets back a Mathpix Markdown (MMD)
   document with text + formulas + images in exact reading order. Parses by
   section headings and stores each section in ChromaDB with inline image context.

2. LEGACY (--no-whole-pdf):
   Original per-page Mathpix /v3/text pipeline (page-by-page OCR + PyMuPDF
   section detection). Still available for testing or comparison.
"""

import asyncio
import logging
import sys
import os
import time
import argparse
from pathlib import Path

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
    CHROMA_DIR,
    BOOK_REGISTRY,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)
from models import PipelineOutput

from extraction.pdf_reader import extract_all_pages
from extraction.section_detector import detect_sections
from extraction.concept_builder import build_concept_blocks, build_concept_blocks_from_mmd
from extraction.mmd_parser import parse_mmd, MmdSection

from images.mathpix_client import submit_pdf, wait_for_pdf_completion, download_pdf_mmd_zip

from graph.dependency_builder import build_dependency_edges
from graph.graph_store import create_graph, validate_graph, save_graph_json, get_graph_stats

from storage.chroma_store import initialize_collection, store_concept_blocks, get_collection_stats
from storage.json_exporter import export_full_output, export_individual_files

from images.image_extractor import extract_image_decisions

from validation.validator import validate_all_blocks, get_validation_summary


# ── Whole-PDF pipeline helpers ────────────────────────────────────────────────

def _annotate_mmd_images(
    sections: list,
    image_dir: Path,
    out_dir: Path,
) -> dict[str, dict]:
    """
    Run vision annotation on every unique image referenced across all MMD sections.
    Reuses existing annotate_image() from vision_annotator.py (MD5-cached).
    R5: Explicitly defined here so it is never "called but not found".
    """
    from images.vision_annotator import annotate_image
    from openai import AsyncOpenAI

    llm_client = AsyncOpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL if OPENAI_BASE_URL else None,
    )
    cache_dir = out_dir / "vision_cache"
    annotations: dict[str, dict] = {}

    # Collect unique filenames across all sections
    all_filenames: set[str] = set()
    for sec in sections:
        all_filenames.update(sec.image_filenames)

    logger.info("Annotating %d unique images via GPT-4o vision...", len(all_filenames))

    async def _run_all() -> None:
        for filename in sorted(all_filenames):
            img_path = image_dir / filename
            if not img_path.exists():
                logger.warning("Image not found, skipping annotation: %s", img_path)
                continue
            ann = await annotate_image(
                image_bytes=img_path.read_bytes(),
                concept_title="",
                image_type="DIAGRAM",
                llm_client=llm_client,
                model=OPENAI_MODEL,
                cache_dir=cache_dir,
            )
            annotations[filename] = ann
            logger.debug("Annotated %s: educational=%s", filename, ann.get("is_educational"))

    asyncio.run(_run_all())
    educational = sum(1 for a in annotations.values() if a.get("is_educational"))
    logger.info(
        "Vision annotation complete: %d/%d images are educational",
        educational, len(annotations),
    )
    return annotations


def _load_source_pages(out_dir: Path) -> dict[str, list[int]]:
    """
    Load concept_id → source_pages mapping from full_output.json (built by old pipeline).
    Returns {concept_id: [1-indexed page numbers]}, or empty dict if file not found.
    """
    import json as _json
    full_output = out_dir / "full_output.json"
    if not full_output.exists():
        logger.warning("full_output.json not found at %s — image interleaving disabled", full_output)
        return {}
    data = _json.loads(full_output.read_text(encoding="utf-8"))
    result = {
        b["concept_id"]: b["source_pages"]
        for b in data.get("concept_blocks", [])
        if b.get("concept_id") and b.get("source_pages")
    }
    logger.info("Loaded source_pages for %d concepts from full_output.json", len(result))
    return result


def _load_source_pages_from_pdf(
    pdf_path: Path,
    config: dict,
) -> dict[str, list[int]]:
    """
    Build concept_id → page_numbers mapping directly from the PDF's table of contents.

    Uses PyMuPDF doc.get_toc() to read PDF bookmarks (which include section titles and
    their starting page numbers). Each section spans from its bookmark page to one page
    before the next section's bookmark page.

    This is the primary source of page ranges for the whole-pdf pipeline — no dependency
    on full_output.json which loses source_pages data on each run.
    """
    import re as _re
    import fitz
    from extraction.concept_builder import _generate_concept_name

    book_code = config["book_code"]
    section_re = _re.compile(config["section_pattern"])

    try:
        doc = fitz.open(str(pdf_path))
        toc = doc.get_toc()   # list of [level, title, 1-indexed page_number]
        total_pages = len(doc)
        doc.close()
    except Exception as e:
        logger.warning("Could not read PDF TOC: %s — image interleaving disabled", e)
        return {}

    if not toc:
        logger.warning("PDF has no bookmarks/TOC — cannot determine section page ranges")
        return {}

    # Extract section entries whose titles match the section_pattern (e.g. "1.1 Title")
    toc_sections = []
    for _level, title, page_num in toc:
        title = title.strip()
        m = section_re.match(title)
        if not m:
            continue
        chapter_num = int(m.group(1))
        section_in_chapter = int(m.group(2))
        if section_in_chapter > 20:
            continue  # skip figure/equation numbers (1.52, 7.87, etc.)
        concept_name = _generate_concept_name(m.group(3).strip())
        concept_id = f"{book_code}.C{chapter_num}.S{section_in_chapter}.{concept_name}"
        toc_sections.append((concept_id, page_num))

    logger.info("Found %d section entries in PDF TOC", len(toc_sections))
    if not toc_sections:
        return {}

    # Each section spans from its start page to one before the next section starts
    result = {}
    for i, (concept_id, start_page) in enumerate(toc_sections):
        end_page = toc_sections[i + 1][1] - 1 if i + 1 < len(toc_sections) else total_pages
        result[concept_id] = list(range(start_page, end_page + 1))

    logger.info(
        "Built source_pages for %d sections from PDF TOC (total pages: %d)",
        len(result), total_pages,
    )
    return result


def _insert_at_positions(
    text: str,
    page_nums: list[int],
    annotated_images: list[dict],
) -> str:
    """
    Insert image descriptions at their proportional positions within the section text.
    Uses paragraph boundaries as insertion points for clean output.
    """
    import re as _re
    if not annotated_images or not page_nums:
        return text
    total_chars = len(text)
    total_pages = max(len(page_nums), 1)
    # Find paragraph break positions — best insertion points
    para_breaks = sorted(set(
        [0] + [m.end() for m in _re.finditer(r'\n\n+', text)] + [total_chars]
    ))
    insertions = []  # (char_pos, fig_text)
    for img in sorted(annotated_images, key=lambda x: (x["page_num"], x["y_frac"])):
        page_idx = page_nums.index(img["page_num"]) if img["page_num"] in page_nums else 0
        overall_frac = (page_idx + img["y_frac"]) / total_pages
        target = int(overall_frac * total_chars)
        nearest = min(para_breaks, key=lambda p: abs(p - target))
        desc = img["description"][:300]
        img_ref = img.get("filename", "figure")
        insertions.append((nearest, f"\n\n![{desc}]({img_ref})\n\n"))
    # Insert from end to start to preserve earlier character offsets
    result = text
    for pos, fig_text in sorted(insertions, key=lambda x: x[0], reverse=True):
        result = result[:pos] + fig_text + result[pos:]
    return result


def _interleave_section_images(
    sections: list,
    config: dict,
    pdf_path: Path,
    source_pages_map: dict[str, list[int]],
    out_dir: Path,
) -> None:
    """
    For each section: extract images by page range from the PDF (via fitz),
    vision-annotate each image, then insert descriptions at their y-proportional
    positions within section.content_mmd (in-place modification).

    This gives images at their correct reading-order positions without requiring
    the Mathpix mmd/ZIP format.
    """
    import fitz
    from images.vision_annotator import annotate_image
    from openai import AsyncOpenAI
    from extraction.concept_builder import _generate_concept_name

    book_code = config["book_code"]
    llm_client = AsyncOpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL if OPENAI_BASE_URL else None,
    )
    cache_dir = out_dir / "vision_cache"
    doc = fitz.open(str(pdf_path))
    seen_xrefs: set[int] = set()

    # Phase 1: Extract raw images with y-positions for each section
    tasks = []
    for sec in sections:
        concept_name = _generate_concept_name(sec.section_title)
        concept_id = f"{book_code}.C{sec.chapter_number}.S{sec.section_in_chapter}.{concept_name}"
        page_nums = source_pages_map.get(concept_id, [])
        raw_images = []
        for page_num in page_nums:  # 1-indexed
            if page_num < 1 or page_num > len(doc):
                continue
            page = doc[page_num - 1]
            page_height = page.rect.height or 1.0
            try:
                img_infos = page.get_image_info(xrefs=True)
            except Exception:
                continue
            for info in img_infos:
                xref = info.get("xref", 0)
                if xref == 0 or xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                bbox = info.get("bbox", (0, 0, 0, page_height))
                y_frac = ((bbox[1] + bbox[3]) / 2) / page_height
                try:
                    img_data = doc.extract_image(xref)
                    # Skip tiny images (icons, decorative lines < 1KB)
                    if img_data and len(img_data.get("image", b"")) > 1000:
                        raw_images.append({
                            "page_num": page_num,
                            "y_frac": y_frac,
                            "image_bytes": img_data["image"],
                        })
                except Exception:
                    pass
        tasks.append((sec, page_nums, raw_images))

    doc.close()

    total_raw = sum(len(t[2]) for t in tasks)
    logger.info("Extracted %d raw images across %d sections", total_raw, len(tasks))

    # Phase 2: Vision-annotate and interleave
    async def _run() -> None:
        for sec, page_nums, raw_images in tasks:
            if not raw_images or not page_nums:
                continue
            annotated = []
            for img in raw_images:
                try:
                    ann = await annotate_image(
                        image_bytes=img["image_bytes"],
                        concept_title=sec.section_title,
                        image_type="DIAGRAM",
                        llm_client=llm_client,
                        model=OPENAI_MODEL,
                        cache_dir=cache_dir,
                    )
                    if ann.get("is_educational") and ann.get("description"):
                        annotated.append({
                            "page_num": img["page_num"],
                            "y_frac": img["y_frac"],
                            "description": ann["description"],
                        })
                except Exception as e:
                    logger.warning("Vision annotation failed for image: %s", e)
            if annotated:
                sec.content_mmd = _insert_at_positions(
                    sec.content_mmd, page_nums, annotated
                )

    asyncio.run(_run())
    interleaved = sum(1 for sec in sections if "![" in sec.content_mmd)
    logger.info("Interleaved image descriptions into %d sections", interleaved)


def _extract_and_index_pdf_images(
    sections: list,
    config: dict,
    pdf_path: Path,
    source_pages_map: dict[str, list[int]],
    out_dir: Path,
) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """
    Extract images from PDF via PyMuPDF, save to out_dir/images/{concept_id}/,
    annotate with GPT-4o Vision, and insert ![description](filename) into
    section.content_mmd at y-proportional paragraph positions.

    Returns:
        image_annotations: {filename: annotation} — for build_concept_blocks_from_mmd
        image_index: {concept_id: [image metadata]} — written to image_index.json
    """
    import fitz
    from images.vision_annotator import annotate_image
    from openai import AsyncOpenAI
    from extraction.concept_builder import _generate_concept_name

    book_code = config["book_code"]
    images_root = out_dir / "images"
    cache_dir = out_dir / "vision_cache"
    llm_client = AsyncOpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL if OPENAI_BASE_URL else None,
    )

    doc = fitz.open(str(pdf_path))
    seen_xrefs: set[int] = set()

    # Phase 1: collect raw images per section with page + y-position metadata
    tasks = []
    for sec in sections:
        concept_name = _generate_concept_name(sec.section_title)
        concept_id = f"{book_code}.C{sec.chapter_number}.S{sec.section_in_chapter}.{concept_name}"
        page_nums = source_pages_map.get(concept_id, [])
        raw_images = []
        for page_num in page_nums:
            if page_num < 1 or page_num > len(doc):
                continue
            page = doc[page_num - 1]
            page_height = page.rect.height or 1.0
            try:
                img_infos = page.get_image_info(xrefs=True)
            except Exception:
                continue
            for info in img_infos:
                xref = info.get("xref", 0)
                if xref == 0 or xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                bbox = info.get("bbox", (0, 0, 0, page_height))
                y_frac = ((bbox[1] + bbox[3]) / 2) / page_height
                try:
                    img_data = doc.extract_image(xref)
                    if img_data and len(img_data.get("image", b"")) > 1000:
                        w = img_data.get("width", 0)
                        h = img_data.get("height", 0)
                        # Skip tiny images (icons, bullets, decorative borders)
                        if w < 100 or h < 40 or w * h < 8000:
                            continue
                        raw_images.append({
                            "page_num": page_num,
                            "y_frac": y_frac,
                            "image_bytes": img_data["image"],
                            "ext": img_data.get("ext", "png"),
                            "width": w,
                            "height": h,
                        })
                except Exception:
                    pass
        tasks.append((sec, concept_id, page_nums, raw_images))

    doc.close()
    total_raw = sum(len(t[3]) for t in tasks)
    logger.info("Extracted %d raw images across %d sections (PyMuPDF)", total_raw, len(tasks))

    image_annotations: dict[str, dict] = {}
    image_index: dict[str, list[dict]] = {}

    async def _run() -> None:
        for sec, concept_id, page_nums, raw_images in tasks:
            if not raw_images or not page_nums:
                continue
            concept_dir = images_root / concept_id
            concept_dir.mkdir(parents=True, exist_ok=True)
            annotated = []

            # First 400 chars of section text grounds the vision description in context.
            section_text_snippet = (
                getattr(sec, "content_mmd", None) or getattr(sec, "text", None) or ""
            )[:400]
            for idx, img in enumerate(raw_images):
                filename = f"{concept_id}_{idx:03d}.{img['ext']}"
                img_path = concept_dir / filename
                img_path.write_bytes(img["image_bytes"])
                try:
                    ann = await annotate_image(
                        image_bytes=img["image_bytes"],
                        concept_title=sec.section_title,
                        image_type="DIAGRAM",
                        llm_client=llm_client,
                        model=OPENAI_MODEL,
                        cache_dir=cache_dir,
                        concept_context=section_text_snippet,
                    )
                except Exception as e:
                    logger.warning("Vision annotation failed for %s: %s", filename, e)
                    ann = {"is_educational": False, "description": None, "relevance": None}

                image_annotations[filename] = ann

                if ann.get("is_educational") and ann.get("description"):
                    annotated.append({
                        "filename": f"/images/{concept_id}/{filename}",  # Full URL for inline insertion
                        "page_num": img["page_num"],
                        "y_frac": img["y_frac"],
                        "description": ann["description"],
                    })
                    image_index.setdefault(concept_id, []).append({
                        "filename": filename,
                        "width": img["width"],
                        "height": img["height"],
                        "image_type": "DIAGRAM",
                        "page": img["page_num"],
                        "description": ann["description"],
                        "relevance": ann.get("relevance"),
                    })

            # Insert ![description](filename) at y-proportional paragraph positions in MMD
            if annotated:
                sec.content_mmd = _insert_at_positions(sec.content_mmd, page_nums, annotated)

    asyncio.run(_run())
    edu = sum(len(v) for v in image_index.values())
    logger.info(
        "Image extraction complete: %d/%d educational images across %d concepts",
        edu, len(image_annotations), len(image_index),
    )
    return image_annotations, image_index


def run_whole_pdf_pipeline(
    book_code: str,
    force: bool = False,
    skip_chroma: bool = False,
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
      F. Store in ChromaDB
      G. Validate
      H. Export JSON outputs

    Args:
        book_code: Book code, e.g. "PREALG"
        force: If True, re-submit to Mathpix even if a cached MMD exists
        skip_chroma: If True, skip ChromaDB storage
        pdf_id: Optional pre-existing Mathpix pdf_id — skips the upload step.
                Useful when the upload fails on Windows (WinError 10053).
                Get this by uploading the PDF manually at https://snip.mathpix.com
    """
    start_time = time.time()

    print(f"\n{'='*60}")
    print(f"ADA Whole-PDF Pipeline (Mathpix /v3/pdf)")
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
    print(f"\n[Stage A] Submitting PDF to Mathpix /v3/pdf...")
    if mmd_cache.exists() and not force:
        logger.info("Using cached MMD: %s", mmd_cache)
        print(f"  Using cached MMD: {mmd_cache}")
        mmd_text = mmd_cache.read_text(encoding="utf-8")
    else:
        if pdf_id:
            # User supplied a pre-existing pdf_id — skip the upload entirely
            print(f"  Using supplied pdf_id: {pdf_id}")
            print(f"  Skipping upload — polling until Mathpix job is complete...")
        else:
            logger.info("Submitting %s to Mathpix /v3/pdf ...", slug)
            pdf_id = submit_pdf(pdf_path)
            print(f"  pdf_id: {pdf_id}")
            print(f"  Polling Mathpix (may take 10–30 min for large books)...")
        wait_for_pdf_completion(pdf_id)
        mmd_text = download_pdf_mmd_zip(pdf_id, image_dir)
        mmd_cache.write_text(mmd_text, encoding="utf-8")
        logger.info("Saved book.mmd and %d images", len(list(image_dir.iterdir())) if image_dir.exists() else 0)
        print(f"  MMD cached to: {mmd_cache}")

    print(f"  MMD size: {len(mmd_text):,} characters")

    # ── Stage B: Parse MMD into sections ────────────────────────────
    print(f"\n[Stage B] Parsing MMD into sections...")
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

    # ── Stage C: Extract & annotate images (PyMuPDF + GPT-4o Vision) ─
    print(f"\n[Stage C] Extracting & annotating images (PyMuPDF + GPT-4o vision)...")
    source_pages_map = _load_source_pages_from_pdf(pdf_path, config)
    if source_pages_map and pdf_path.exists():
        image_annotations, image_index = _extract_and_index_pdf_images(
            sections, config, pdf_path, source_pages_map, out_dir,
        )
        import json as _json
        image_index_path = out_dir / "image_index.json"
        image_index_path.write_text(
            _json.dumps(image_index, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        edu = sum(len(v) for v in image_index.values())
        inline_count = sum(1 for sec in sections if "![" in sec.content_mmd)
        print(f"  Educational images: {edu} across {len(image_index)} concepts")
        print(f"  Sections with inline images: {inline_count}")
        print(f"  Written: {image_index_path}")
    else:
        print(f"  No PDF TOC found — skipping image extraction")
        image_annotations = {}
        image_index = {}

    # ── Stage D: Build concept blocks ───────────────────────────────
    print(f"\n[Stage D] Building concept blocks...")
    concept_blocks = build_concept_blocks_from_mmd(sections, config, image_annotations)
    print(f"  Built {len(concept_blocks)} concept blocks")
    if concept_blocks:
        total_words = sum(len(b.text.split()) for b in concept_blocks)
        avg_words = total_words // len(concept_blocks)
        print(f"  Total words: {total_words:,}  (avg {avg_words}/block)")

    # ── Stage E: Build dependency graph ─────────────────────────────
    print(f"\n[Stage E] Building dependency graph...")
    dependency_edges = build_dependency_edges(concept_blocks)
    total_edges = sum(len(e.prerequisites) for e in dependency_edges)
    graph = create_graph(concept_blocks, dependency_edges)
    graph_issues = validate_graph(graph)
    graph_stats = get_graph_stats(graph)
    print(f"  Graph: {graph_stats['num_nodes']} nodes, {graph_stats['num_edges']} edges")
    print(f"  Is DAG: {graph_stats['is_dag']}  |  Root nodes: {graph_stats['num_root_nodes']}")
    if graph_issues:
        print(f"  Issues: {len(graph_issues)}")

    # ── Stage F: Store in ChromaDB ───────────────────────────────────
    if not skip_chroma:
        print(f"\n[Stage F] Storing in ChromaDB...")
        try:
            chroma_dir = out_dir / "chroma_db"
            collection = initialize_collection(
                persist_directory=chroma_dir,
                collection_name=f"concepts_{slug}",
            )
            stored_count = store_concept_blocks(collection, concept_blocks, dependency_edges)
            stats = get_collection_stats(collection)
            print(f"  Stored {stored_count} concepts — collection has {stats['count']} docs")
        except Exception as e:
            print(f"  ChromaDB storage failed: {e}")
            print(f"  Continuing without ChromaDB...")
    else:
        print(f"\n[Stage F] Skipping ChromaDB (--skip-chroma)")

    # ── Stage G: Validate ────────────────────────────────────────────
    print(f"\n[Stage G] Validating concept blocks...")
    validation_results = validate_all_blocks(concept_blocks)
    summary = get_validation_summary(validation_results)
    print(f"  Valid: {summary['valid_blocks']}/{summary['total_blocks']} ({summary['validation_rate']}%)")

    # ── Stage H: Export outputs ──────────────────────────────────────
    print(f"\n[Stage H] Exporting outputs...")
    output = PipelineOutput(
        concept_blocks=concept_blocks,
        dependency_edges=dependency_edges,
        validation_report=validation_results,
        mathpix_plan=[],
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
    args = parser.parse_args()

    if args.list_books:
        print("Available book codes:")
        for code, config in BOOK_REGISTRY.items():
            print(f"  {code:12s} -> {config['title']}")
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
                        book_code, force=args.force, skip_chroma=args.skip_chroma,
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
            run_whole_pdf_pipeline(args.book, force=args.force, skip_chroma=args.skip_chroma, pdf_id=args.pdf_id, max_sections=args.max_sections)
    else:
        # ── Legacy pipeline (opt-in via --legacy) ────────────────────
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
