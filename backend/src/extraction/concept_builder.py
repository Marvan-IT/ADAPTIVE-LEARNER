"""
Concept Builder — assembles cleaned, filtered text into ConceptBlock objects.
ONE instructional section = ONE concept block.

Supports three text extraction modes:
  - LLM extraction (--use-llm): sends Mathpix OCR text to GPT for
    high-quality instructional content extraction. Best quality.
  - Regex extraction (default): uses content_filter.py regex rules.
  - PyMuPDF fallback (--no-mathpix): raw text extraction (no math).
"""

import re
import fitz
from pathlib import Path

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from extraction.domain_models import PageText, SectionBoundary, ConceptBlock
from config import MATHPIX_DPI, OUTPUT_DIR
from extraction.text_cleaner import clean_section_text
from extraction.content_filter import filter_section_content
from extraction.mmd_parser import MmdSection


def build_concept_blocks(
    sections: list[SectionBoundary],
    pages: list[PageText],
    book_config: dict,
    use_mathpix: bool = True,
    pdf_path: Path = None,
    use_llm: bool = False,
) -> list[ConceptBlock]:
    """
    For each detected section, build a ConceptBlock.

    When use_llm=True:
      - Gathers Mathpix OCR text, then sends to GPT for extraction.
      - Falls back to regex if LLM fails for a section.

    When use_mathpix=True (default):
      - Renders each page as an image
      - Sends to Mathpix API for OCR (with caching)
      - Gets Markdown text with $...$ and $$...$$ math delimiters

    When use_mathpix=False:
      - Uses PyMuPDF raw text extraction (fallback)
    """
    book_code = book_config["book_code"]
    book_slug = book_config["book_slug"]
    book_title = book_config["title"]

    concept_blocks = []

    # Set up Mathpix OCR if enabled
    doc = None
    cache_dir = None
    mathpix_stats = {"api_calls": 0, "cache_hits": 0, "failures": 0}

    if use_mathpix and pdf_path:
        from extraction.pdf_reader import render_page_to_image
        from images.mathpix_client import ocr_page_image, check_mathpix_credentials

        if not check_mathpix_credentials():
            print("  Warning: Mathpix credentials not set. Falling back to PyMuPDF.")
            use_mathpix = False
        else:
            doc = fitz.open(str(pdf_path))
            cache_dir = OUTPUT_DIR / book_slug / "mathpix_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)

    # Set up LLM extraction if enabled
    llm_cache_dir = None
    llm_stats = {"api_calls": 0, "cache_hits": 0, "failures": 0}
    if use_llm:
        from extraction.llm_extractor import extract_concept_with_llm
        llm_cache_dir = OUTPUT_DIR / book_slug / "llm_cache"
        llm_cache_dir.mkdir(parents=True, exist_ok=True)

    for section in sections:
        # Gather page range
        page_indices = list(range(section.start_page_index, section.end_page_index))
        if not page_indices:
            continue

        source_pages = [idx + 1 for idx in page_indices if idx < len(pages)]

        if use_mathpix and doc:
            # ── Mathpix path: render pages → OCR → join ──────────
            from extraction.pdf_reader import render_page_to_image
            from images.mathpix_client import ocr_page_image

            page_texts_ocr = []
            for idx in page_indices:
                if idx >= len(doc):
                    continue

                # Check cache first
                cache_file = cache_dir / f"page_{idx+1:04d}.md"
                if cache_file.exists():
                    page_text = cache_file.read_text(encoding="utf-8")
                    mathpix_stats["cache_hits"] += 1
                else:
                    # Render and OCR
                    image_bytes = render_page_to_image(doc, idx, dpi=MATHPIX_DPI)
                    page_text = ocr_page_image(image_bytes)
                    mathpix_stats["api_calls"] += 1

                    if page_text is None:
                        mathpix_stats["failures"] += 1
                        # Fall back to PyMuPDF for this page
                        page_text = pages[idx].raw_text if idx < len(pages) else ""
                    else:
                        # Cache the result
                        cache_file.write_text(page_text, encoding="utf-8")

                if page_text.strip():
                    # Apply same boilerplate/footer cleaning as PyMuPDF path
                    from extraction.text_cleaner import clean_page_text
                    cleaned = clean_page_text(page_text)
                    if cleaned.strip():
                        page_texts_ocr.append(cleaned)

            combined_text = "\n\n".join(page_texts_ocr)
        else:
            # ── PyMuPDF fallback path ─────────────────────────────
            raw_pages = []
            for idx in page_indices:
                if idx < len(pages):
                    raw_pages.append(pages[idx].raw_text)
            combined_text = clean_section_text(raw_pages)

        if not combined_text.strip():
            continue

        # Extract instructional content
        if use_llm:
            # ── LLM extraction path ──────────────────────────────
            section_id = f"{book_code}.C{section.chapter_number}.S{section.section_in_chapter}"
            llm_result = extract_concept_with_llm(
                combined_text=combined_text,
                section_title=section.section_title,
                section_id=section_id,
                book_slug=book_slug,
                source_pages=source_pages,
                cache_dir=llm_cache_dir,
            )
            if llm_result is not None:
                if llm_result.get("_cached"):
                    llm_stats["cache_hits"] += 1
                else:
                    llm_stats["api_calls"] += 1
                instructional_text = llm_result["text"]
                latex_expressions = llm_result["latex"]
            else:
                # Fall back to regex for this section
                llm_stats["failures"] += 1
                print(f"    Falling back to regex for {section.section_number}")
                filtered = filter_section_content(combined_text, section)
                instructional_text = filtered["instructional_text"]
                latex_expressions = filtered["latex_expressions"]
        else:
            # ── Regex extraction path (original) ─────────────────
            filtered = filter_section_content(combined_text, section)
            instructional_text = filtered["instructional_text"]
            latex_expressions = filtered["latex_expressions"]

        if not instructional_text.strip():
            continue

        # Generate concept_id
        concept_name = _generate_concept_name(section.section_title)
        concept_id = f"{book_code}.C{section.chapter_number}.S{section.section_in_chapter}.{concept_name}"

        # Assemble the ConceptBlock
        block = ConceptBlock(
            concept_id=concept_id,
            concept_title=section.section_title,
            book_slug=book_slug,
            book=book_title,
            chapter=str(section.chapter_number),
            section=section.section_number,
            text=instructional_text,
            latex=latex_expressions,
            source_pages=source_pages,
        )
        concept_blocks.append(block)

    # Close PDF doc
    if doc:
        doc.close()

    # Print Mathpix stats
    if use_mathpix and pdf_path:
        total = mathpix_stats["api_calls"] + mathpix_stats["cache_hits"]
        print(f"  Mathpix OCR: {mathpix_stats['api_calls']} API calls, "
              f"{mathpix_stats['cache_hits']} cache hits, "
              f"{mathpix_stats['failures']} failures "
              f"({total} total pages)")

    # Print LLM stats
    if use_llm:
        total = llm_stats["api_calls"] + llm_stats["cache_hits"]
        print(f"  LLM extraction: {llm_stats['api_calls']} API calls, "
              f"{llm_stats['cache_hits']} cache hits, "
              f"{llm_stats['failures']} failures "
              f"({total} total sections)")

    return concept_blocks


def build_concept_blocks_from_mmd(
    sections: list[MmdSection],
    book_config: dict,
    image_annotations: dict[str, dict],
) -> list[ConceptBlock]:
    """
    Build ConceptBlock objects from pre-parsed MMD sections (whole-PDF pipeline).

    Images in the MMD are already inline as ![]( filename). We replace each
    image reference with its vision-annotated description as alt text so the
    LLM card generator receives a coherent text document with image context
    at the correct reading positions.

    Non-educational images (checklists, decorative) are removed entirely.

    Args:
        sections: Parsed MmdSection objects from mmd_parser.parse_mmd()
        book_config: Book entry from BOOK_REGISTRY (book_code, book_slug, title)
        image_annotations: filename → {description, is_educational} from vision_annotator

    Returns:
        List of ConceptBlock objects ready for ChromaDB storage.
    """
    book_code = book_config["book_code"]
    book_title = book_config["title"]
    book_slug = book_config["book_slug"]
    blocks = []

    for sec in sections:
        content = sec.content_mmd

        # Replace ![]( filename) placeholders with annotated alt text or remove
        for filename in sec.image_filenames:
            ann = image_annotations.get(filename, {})
            is_educational = ann.get("is_educational", True)
            description = ann.get("description", "")

            if not is_educational or not description:
                # Remove non-educational or unannotated images
                content = content.replace(f"![]({filename})", "")
                content = content.replace(f"![image]({filename})", "")
                content = content.replace(f"![Image]({filename})", "")
            else:
                # Embed description as alt text so LLM sees image content
                desc = description[:200]
                content = content.replace(
                    f"![]({filename})",
                    f"![{desc}]({filename})"
                )

        if not content.strip():
            continue

        concept_name = _generate_concept_name(sec.section_title)
        concept_id = (
            f"{book_code}.C{sec.chapter_number}"
            f".S{sec.section_in_chapter}.{concept_name}"
        )

        blocks.append(ConceptBlock(
            concept_id=concept_id,
            concept_title=sec.section_title,
            book_slug=book_slug,
            book=book_title,
            chapter=str(sec.chapter_number),
            section=sec.section_number,
            text=content,
            latex=[],          # Mathpix already embeds $...$ inline in the text
            source_pages=[],   # Not tracked in whole-PDF approach
        ))

    return blocks


def _generate_concept_name(section_title: str) -> str:
    """
    Convert a section title to a concept name for use in concept_id.

    Examples:
      "Introduction to Whole Numbers" -> "INTRODUCTION_TO_WHOLE_NUMBERS"
      "Add and Subtract Fractions" -> "ADD_AND_SUBTRACT_FRACTIONS"
    """
    # Remove special characters except spaces and alphanumeric
    name = re.sub(r"[^a-zA-Z0-9\s]", " ", section_title)
    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name).strip()
    # Uppercase and replace spaces with underscores
    name = name.upper().replace(" ", "_")
    return name
