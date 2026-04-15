"""
book_profiler.py — LLM-powered structural profiler for the Universal PDF Extraction Pipeline.

This module runs AFTER ocr_validator.py (Stage 1) and BEFORE chunk_parser.py (Stage 3).
It uses gpt-4o-mini to analyze a book's structure once, caches the result as
{OUTPUT_DIR}/{book_slug}/book_profile.json, and exposes a simple public API:

    profile = await load_or_create_profile(mmd_text, book_slug, quality_report)

The resulting BookProfile drives all downstream chunking decisions in chunk_parser.py,
replacing hardcoded constants (_MAX_REAL_SECTION_IN_CHAPTER, _NOISE_HEADING_PATTERNS, etc.)
with book-specific values inferred from the book's own TOC and signal statistics.

Cost: ~$0.003 per book (one gpt-4o-mini call, ~5 K input tokens, cached thereafter).
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Union

from pydantic import BaseModel

# Ensure config is importable when running standalone
_src_dir = Path(__file__).resolve().parent.parent
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from config import (
    BACK_MATTER_MARKERS,
    BOILERPLATE_PATTERNS,
    DEFAULT_MAX_CHUNK_WORDS,
    DEFAULT_MIN_CHUNK_WORDS,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL_MINI,
    OUTPUT_DIR,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class HeadingLevel(BaseModel):
    """One level in the heading hierarchy."""

    level: str           # "part", "chapter", "section", "subsection"
    md_pattern: str      # regex matching this heading in normalized MMD
    id_extractor: str | None = None  # regex with capture groups for numbering
    examples: list[str] = []


class SubsectionSignal(BaseModel):
    """Classification of a signal type for subsection boundary detection."""

    signal_type: str   # "heading_h2", "heading_h3", "heading_h4", "bold_line", "caps_line", "numbered"
    is_boundary: bool  # True = this signal type creates subsection splits
    examples: list[str] = []


class ExerciseMarker(BaseModel):
    """An auto-detected exercise heading pattern."""

    pattern: str    # the heading text or regex
    behavior: str   # "zone_section_end" | "zone_chapter_end" | "inline_single"


class BookProfile(BaseModel):
    """Complete structural profile for one book — drives all chunking decisions."""

    book_slug: str
    subject: str

    # Section-level
    heading_hierarchy: list[HeadingLevel] = []
    section_id_format: str = "{book_slug}_{chapter}.{section}"
    toc_sections: list[dict] = []

    # Subsection-level
    subsection_signals: list[SubsectionSignal] = []
    feature_box_patterns: list[str] = []
    noise_patterns: list[str] = []

    # Exercise detection
    exercise_markers: list[ExerciseMarker] = []

    # Quality controls
    min_chunk_words: int = DEFAULT_MIN_CHUNK_WORDS
    max_chunk_words: int = DEFAULT_MAX_CHUNK_WORDS
    max_sections_per_chapter: int = 99  # Match parser cap; TOC whitelist is the real filter
    back_matter_markers: list[str] = []
    boilerplate_patterns: list[str] = []

    # OCR heading corrections: garbled body text → corrected TOC title.
    # Populated from quality_report.corrected_headings on every pipeline run.
    # Persisted in book_profile.json; old cached profiles without this key
    # deserialize safely to {} (Pydantic default).
    corrected_headings: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Internal: chapter sample extraction
# ---------------------------------------------------------------------------


def _extract_chapter_samples(
    mmd_text: str,
    toc_entries: list,
    n_samples: int = 3,
) -> list[str]:
    """
    Extract n_samples representative chapter slices from the MMD body.

    Strategy:
      - Identify chapter boundary positions using the TOC chapter numbers.
      - Pick chapters at indices: 0 (start), len//2 (middle), len-1 (end).
      - Slice the MMD between consecutive chapter boundaries.
      - Truncate each slice to at most 700 lines.

    Args:
        mmd_text:    Normalized MMD text.
        toc_entries: TocEntry list from ocr_validator.parse_toc().
        n_samples:   Number of samples to return (default 3).

    Returns:
        List of MMD text slices (at most n_samples entries).
        Returns a single full-document sample if no TOC is available.
    """
    if not toc_entries:
        # No TOC — return a single truncated sample from the document body
        lines = mmd_text.splitlines()
        return ["\n".join(lines[:700])]

    # Collect distinct chapter numbers in document order
    seen_chapters: list[int] = []
    for entry in toc_entries:
        if entry.chapter not in seen_chapters:
            seen_chapters.append(entry.chapter)

    if not seen_chapters:
        lines = mmd_text.splitlines()
        return ["\n".join(lines[:700])]

    # Locate chapter start positions in the MMD text
    chapter_positions: dict[int, int] = {}
    for ch in seen_chapters:
        # Match "## Chapter N", "CHAPTER N", "# N | Title" patterns
        pattern = re.compile(
            rf"(?:^#{'{1,4}'}\s+.*?(?:chapter|unit|part)\s+{ch}\b"
            rf"|^(?:chapter|unit|part)\s+{ch}\b"
            rf"|^#{'{1,4}'}\s+{ch}\s*[|:]\s+\S)",
            re.IGNORECASE | re.MULTILINE,
        )
        m = pattern.search(mmd_text)
        if m:
            chapter_positions[ch] = m.start()

    # Fallback: if fewer than 2 chapters found, use whole-doc sample
    if len(chapter_positions) < 2:
        lines = mmd_text.splitlines()
        return ["\n".join(lines[:700])]

    # Sort chapters by their detected positions
    sorted_chapters = sorted(chapter_positions.keys(), key=lambda c: chapter_positions[c])

    # Pick sample indices: start, middle, end
    total = len(sorted_chapters)
    indices = sorted({0, total // 2, total - 1})
    sample_chapters = [sorted_chapters[i] for i in indices][:n_samples]

    samples: list[str] = []
    for ch in sample_chapters:
        ch_start = chapter_positions[ch]

        # Find next chapter's start (for slice end)
        ch_idx = sorted_chapters.index(ch)
        if ch_idx + 1 < len(sorted_chapters):
            next_ch = sorted_chapters[ch_idx + 1]
            ch_end = chapter_positions[next_ch]
        else:
            ch_end = len(mmd_text)

        slice_text = mmd_text[ch_start:ch_end]
        lines = slice_text.splitlines()
        samples.append("\n".join(lines[:700]))

    return samples


# ---------------------------------------------------------------------------
# Internal: prompt construction
# ---------------------------------------------------------------------------

_PROFILER_JSON_SCHEMA = """{
  "subject": "<subject area, e.g. mathematics, nursing, biology>",
  "subsection_signals": [
    {
      "signal_type": "<heading_h2 | heading_h3 | heading_h4 | bold_line | caps_line | numbered>",
      "is_boundary": <true | false>,
      "examples": ["<example text>", "..."]
    }
  ],
  "feature_box_patterns": ["<regex or heading text that marks a feature/callout box>", "..."],
  "noise_patterns": ["<regex for headings to skip — not pedagogical subsection boundaries>", "..."],
  "exercise_markers": [
    {
      "pattern": "<heading text or regex>",
      "behavior": "<zone_section_end | zone_chapter_end | inline_single>"
    }
  ],
  "back_matter_markers": ["<heading text marking appendix/answer-key/index>", "..."],
  "boilerplate_patterns": ["<regex for lines to strip as boilerplate>", "..."],
  "min_chunk_words": <integer, minimum words per instructional chunk>,
  "max_sections_per_chapter": <integer, max real instructional sections per chapter>
}"""


def _build_profiler_prompt(
    toc_entries: list,
    signal_stats: list,
    chapter_samples: list[str],
) -> tuple[str, str]:
    """
    Build system and user prompts for the LLM book profiler.

    Args:
        toc_entries:     List of TocEntry from ocr_validator.
        signal_stats:    List of SignalStats from ocr_validator.
        chapter_samples: List of MMD text slices (start/middle/end of book).

    Returns:
        (system_prompt, user_prompt) tuple — ready for the OpenAI chat completions API.
    """
    system_prompt = (
        "You are a document-structure analyst specializing in educational textbooks.\n"
        "Your task: analyze the provided Table of Contents, heading statistics, and chapter samples "
        "from a Mathpix-converted textbook (MMD format), then classify the book's structural patterns.\n\n"
        "RULES:\n"
        "1. Return ONLY valid JSON — no markdown fences, no prose, no trailing commas.\n"
        "2. All regex patterns must be valid Python re patterns.\n"
        "3. noise_patterns: headings that are NOT pedagogical subsections "
        "(examples, exercise headers, solution labels, navigational boilerplate).\n"
        "4. exercise_markers behavior values:\n"
        "   - 'zone_section_end': heading starts an exercise zone that runs to section end\n"
        "   - 'zone_chapter_end': heading starts an exercise zone that runs to chapter end\n"
        "   - 'inline_single': heading is a one-off exercise item, not a zone\n"
        "5. feature_box_patterns: recurring pedagogical boxes (Learning Objectives, Key Terms, "
        "   Try It, How To, Media, Link to Learning, etc.) that appear many times.\n"
        "6. min_chunk_words: minimum meaningful instructional body word count "
        "(typically 30–120; use 30 for concise technical books, 80 for prose-heavy).\n"
        "7. max_sections_per_chapter: across all 16 OpenStax math books, real sections "
        "   stay at most 10–12; nursing/science books may go to 20–25.\n"
        "8. subsection_signals: for each signal_type, set is_boundary=true if that type "
        "   reliably marks a new pedagogical subsection (not noise/boilerplate).\n"
        "9. Be specific — use real examples from the samples, not generic placeholders.\n"
    )

    # Format TOC
    toc_lines: list[str] = []
    for i, entry in enumerate(toc_entries[:80], 1):  # cap at 80 entries to limit tokens
        toc_lines.append(f"  {i:3d}. {entry.section_number}  {entry.title}")
    toc_block = "\n".join(toc_lines) if toc_lines else "  (no TOC entries found)"

    # Format signal stats table
    stats_rows: list[str] = []
    stats_rows.append(f"  {'Heading Text':<45}  {'Count':>5}  {'AvgPos':>6}  {'StdPos':>6}  Signal Types")
    stats_rows.append("  " + "-" * 85)
    for stat in signal_stats[:40]:  # cap at 40 rows
        text_col = stat.text[:44]
        types_col = ", ".join(stat.signal_types)
        stats_rows.append(
            f"  {text_col:<45}  {stat.count:>5}  {stat.avg_position:>6.3f}  {stat.std_position:>6.3f}  {types_col}"
        )
    stats_block = "\n".join(stats_rows) if signal_stats else "  (no recurring headings detected)"

    # Format chapter samples
    sample_blocks: list[str] = []
    for idx, sample in enumerate(chapter_samples):
        label = ["START", "MIDDLE", "END"][idx] if idx < 3 else f"SAMPLE_{idx}"
        sample_blocks.append(f"=== CHAPTER SAMPLE ({label}) ===\n{sample}\n=== END SAMPLE ===")
    samples_block = "\n\n".join(sample_blocks)

    user_prompt = (
        "Analyze this textbook and return a JSON profile matching the schema below.\n\n"
        "## TABLE OF CONTENTS\n"
        f"{toc_block}\n\n"
        "## RECURRING HEADING STATISTICS (headings appearing >5 times)\n"
        f"{stats_block}\n\n"
        "## CHAPTER SAMPLES (up to 700 lines each from start/middle/end)\n"
        f"{samples_block}\n\n"
        "## REQUIRED JSON OUTPUT SCHEMA\n"
        f"{_PROFILER_JSON_SCHEMA}\n\n"
        "Return ONLY the JSON object. No other text."
    )

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Internal: LLM call
# ---------------------------------------------------------------------------


async def _call_llm_profiler(system_prompt: str, user_prompt: str) -> dict:
    """
    Call gpt-4o-mini with the profiler prompts and return the parsed JSON dict.

    Uses json_repair as a fallback for minor JSON formatting issues from the LLM.
    Returns an empty dict on failure — callers build a default profile in that case.
    """
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.error("openai package not installed — cannot call LLM profiler")
        return {}

    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    for attempt in range(1, 4):
        try:
            response = await client.chat.completions.create(
                model=OPENAI_MODEL_MINI,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=4000,
                temperature=0.2,
                response_format={"type": "json_object"},
                timeout=60.0,
            )
            raw = (response.choices[0].message.content or "").strip()
            if not raw:
                logger.warning("LLM profiler returned empty response (attempt %d)", attempt)
                continue

            # Primary parse
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass

            # json_repair fallback
            try:
                from json_repair import repair_json
                repaired = repair_json(raw)
                result = json.loads(repaired)
                logger.info("LLM profiler JSON repaired via json_repair (attempt %d)", attempt)
                return result
            except Exception as repair_exc:
                logger.warning("json_repair also failed (attempt %d): %s", attempt, repair_exc)

        except Exception as exc:
            logger.warning("LLM profiler call failed (attempt %d): %s", attempt, exc)
            if attempt < 3:
                import asyncio
                await asyncio.sleep(2 * attempt)

    logger.error("LLM profiler failed after 3 attempts — returning empty dict")
    return {}


# ---------------------------------------------------------------------------
# Internal: merge LLM response into BookProfile
# ---------------------------------------------------------------------------


def _llm_dict_to_profile(
    llm_data: dict,
    book_slug: str,
    toc_entries: list,
) -> BookProfile:
    """
    Merge the raw LLM JSON response with TOC-derived data into a BookProfile.

    The LLM response is used for subsection signals, noise patterns, exercise markers,
    feature box patterns, and quality controls. TOC data is used for the heading
    hierarchy and toc_sections list.

    Args:
        llm_data:    Parsed JSON dict from the LLM (may be empty on failure).
        book_slug:   Book identifier string.
        toc_entries: Parsed TocEntry list from ocr_validator.

    Returns:
        Fully populated BookProfile.
    """
    subject = llm_data.get("subject", "mathematics")

    # ── Subsection signals ────────────────────────────────────────────────────
    subsection_signals: list[SubsectionSignal] = []
    for raw_sig in llm_data.get("subsection_signals", []):
        if not isinstance(raw_sig, dict):
            continue
        signal_type = raw_sig.get("signal_type", "")
        if not signal_type:
            continue
        subsection_signals.append(SubsectionSignal(
            signal_type=signal_type,
            is_boundary=bool(raw_sig.get("is_boundary", False)),
            examples=raw_sig.get("examples", []),
        ))

    # Default: treat h2 as boundary if LLM gave no guidance
    if not subsection_signals:
        subsection_signals = [
            SubsectionSignal(signal_type="heading_h2", is_boundary=True),
            SubsectionSignal(signal_type="heading_h3", is_boundary=False),
            SubsectionSignal(signal_type="bold_line", is_boundary=False),
        ]

    # ── Exercise markers ──────────────────────────────────────────────────────
    exercise_markers: list[ExerciseMarker] = []
    for raw_ex in llm_data.get("exercise_markers", []):
        if not isinstance(raw_ex, dict):
            continue
        pattern = raw_ex.get("pattern", "")
        behavior = raw_ex.get("behavior", "zone_section_end")
        if not pattern:
            continue
        if behavior not in ("zone_section_end", "zone_chapter_end", "inline_single"):
            behavior = "zone_section_end"
        exercise_markers.append(ExerciseMarker(pattern=pattern, behavior=behavior))

    # ── Heading hierarchy: derive from TOC structure ──────────────────────────
    heading_hierarchy: list[HeadingLevel] = [
        HeadingLevel(
            level="chapter",
            md_pattern=r"^#{1,2}\s+(?:chapter|unit|part)\s+\d+",
            id_extractor=r"(?:chapter|unit|part)\s+(\d+)",
            examples=["## Chapter 1: Introduction"],
        ),
        HeadingLevel(
            level="section",
            md_pattern=r"^#{1,4}\s+\d+\.\d+\s+\S",
            id_extractor=r"(\d+)\.(\d+)\s+(.+)",
            examples=["### 1.1 Introduction to Whole Numbers"],
        ),
        HeadingLevel(
            level="subsection",
            md_pattern=r"^##\s+[A-Z].+",
            examples=["## Identify Whole Numbers"],
        ),
    ]

    # ── TOC sections: flatten TocEntry list to dicts ──────────────────────────
    toc_sections = [
        {
            "section_number": e.section_number,
            "title": e.title,
            "chapter": e.chapter,
        }
        for e in toc_entries
    ]

    # ── Quality controls ──────────────────────────────────────────────────────
    min_chunk_words = int(llm_data.get("min_chunk_words", DEFAULT_MIN_CHUNK_WORDS))
    min_chunk_words = max(10, min(500, min_chunk_words))  # sanity clamp

    max_sections = int(llm_data.get("max_sections_per_chapter", 20))
    max_sections = max(5, min(40, max_sections))  # sanity clamp

    # ── Merge back-matter and boilerplate with config defaults ────────────────
    llm_back_matter = [m for m in llm_data.get("back_matter_markers", []) if isinstance(m, str)]
    merged_back_matter = list(dict.fromkeys(BACK_MATTER_MARKERS + llm_back_matter))

    llm_boilerplate = [p for p in llm_data.get("boilerplate_patterns", []) if isinstance(p, str)]
    merged_boilerplate = list(dict.fromkeys(BOILERPLATE_PATTERNS + llm_boilerplate))

    return BookProfile(
        book_slug=book_slug,
        subject=subject,
        heading_hierarchy=heading_hierarchy,
        section_id_format="{book_slug}_{chapter}.{section}",
        toc_sections=toc_sections,
        subsection_signals=subsection_signals,
        feature_box_patterns=[
            p for p in llm_data.get("feature_box_patterns", []) if isinstance(p, str)
        ],
        noise_patterns=[
            p for p in llm_data.get("noise_patterns", []) if isinstance(p, str)
        ],
        exercise_markers=exercise_markers,
        min_chunk_words=min_chunk_words,
        max_chunk_words=DEFAULT_MAX_CHUNK_WORDS,
        max_sections_per_chapter=max_sections,
        back_matter_markers=merged_back_matter,
        boilerplate_patterns=merged_boilerplate,
    )


# ---------------------------------------------------------------------------
# Public: profile_book
# ---------------------------------------------------------------------------


async def profile_book(
    mmd_text: str,
    book_slug: str,
    quality_report,  # ocr_validator.QualityReport
) -> BookProfile:
    """
    Analyze a book's structure using the LLM and return a BookProfile.

    Steps:
      1. Extract chapter samples (start / middle / end).
      2. Build system + user prompts from TOC, signal stats, and samples.
      3. Call gpt-4o-mini (JSON mode, max_tokens=4000, temperature=0.2).
      4. Parse response, merge with TOC data, return BookProfile.

    Falls back to sensible defaults if the LLM call fails entirely.

    Args:
        mmd_text:       Full MMD text (normalized or raw — normalization is applied internally).
        book_slug:      Short book identifier (e.g. "prealgebra").
        quality_report: QualityReport from ocr_validator.validate_and_analyze().

    Returns:
        BookProfile with all fields populated.
    """
    logger.info("Profiling book '%s' via LLM (%d chars MMD)", book_slug, len(mmd_text))

    toc_entries = quality_report.toc_entries
    signal_stats = quality_report.signal_stats

    # Step 1: extract chapter samples
    chapter_samples = _extract_chapter_samples(mmd_text, toc_entries, n_samples=3)
    logger.info("Extracted %d chapter samples", len(chapter_samples))

    # Step 2: build prompts
    system_prompt, user_prompt = _build_profiler_prompt(toc_entries, signal_stats, chapter_samples)
    logger.debug(
        "Profiler prompts built: system=%d chars, user=%d chars",
        len(system_prompt),
        len(user_prompt),
    )

    # Step 3: call LLM
    llm_data = await _call_llm_profiler(system_prompt, user_prompt)

    if llm_data:
        logger.info(
            "LLM profiler succeeded for '%s': subject=%s, noise_patterns=%d, exercise_markers=%d",
            book_slug,
            llm_data.get("subject", "?"),
            len(llm_data.get("noise_patterns", [])),
            len(llm_data.get("exercise_markers", [])),
        )
    else:
        logger.warning(
            "LLM profiler returned no data for '%s' — building default profile",
            book_slug,
        )

    # Step 4: merge and return
    profile = _llm_dict_to_profile(llm_data, book_slug, toc_entries)

    # Wire corrected_headings from quality_report into profile
    profile.corrected_headings = quality_report.corrected_headings
    logger.info(
        "[profiler] Wired %d corrected headings into profile for '%s'",
        len(profile.corrected_headings),
        book_slug,
    )

    return profile


# ---------------------------------------------------------------------------
# Public: save / load profile
# ---------------------------------------------------------------------------


def save_profile(profile: BookProfile, book_slug: str) -> Path:
    """
    Serialize a BookProfile to {OUTPUT_DIR}/{book_slug}/book_profile.json.

    Creates the output directory if it does not exist.

    Args:
        profile:   Populated BookProfile to persist.
        book_slug: Used to build the output path (should match profile.book_slug).

    Returns:
        Absolute Path to the saved JSON file.
    """
    output_dir = OUTPUT_DIR / book_slug
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_path = output_dir / "book_profile.json"

    profile_path.write_text(
        profile.model_dump_json(indent=2),
        encoding="utf-8",
    )
    logger.info("BookProfile saved: %s", profile_path)
    return profile_path


def load_profile(book_slug: str) -> Union[BookProfile, None]:
    """
    Load a cached BookProfile from {OUTPUT_DIR}/{book_slug}/book_profile.json.

    Args:
        book_slug: Book identifier (must match the directory name under OUTPUT_DIR).

    Returns:
        BookProfile if the file exists and parses successfully, None otherwise.
    """
    profile_path = OUTPUT_DIR / book_slug / "book_profile.json"
    if not profile_path.exists():
        logger.debug("No cached profile for '%s' at %s", book_slug, profile_path)
        return None

    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        profile = BookProfile.model_validate(data)
        logger.info("Loaded cached BookProfile for '%s' from %s", book_slug, profile_path)
        return profile
    except Exception as exc:
        logger.warning(
            "Failed to load cached profile for '%s' (%s: %s) — will regenerate",
            book_slug,
            type(exc).__name__,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Public: main entry point
# ---------------------------------------------------------------------------


async def load_or_create_profile(
    mmd_text: str,
    book_slug: str,
    quality_report,  # ocr_validator.QualityReport
) -> BookProfile:
    """
    Main public API. Return a BookProfile for the given book.

    If a valid cached profile exists on disk it is returned immediately (no LLM call).
    Otherwise the LLM profiler is invoked, the result is saved to disk, and returned.

    Args:
        mmd_text:       Full MMD text (used only when the cache is cold).
        book_slug:      Short book identifier.
        quality_report: QualityReport from ocr_validator.validate_and_analyze().

    Returns:
        BookProfile — always returns a usable profile (falls back to defaults on LLM failure).
    """
    cached = load_profile(book_slug)
    if cached is not None:
        # Always refresh corrected_headings and toc_sections from the live
        # quality_report, even on cache hit.  This ensures:
        #  - OCR corrections stay current without a full re-profile.
        #  - TOC sections reflect the latest parse_toc() output (e.g. after
        #    the adaptive-window fix captures more chapters).
        cached.corrected_headings = quality_report.corrected_headings
        cached.toc_sections = [
            {
                "section_number": e.section_number,
                "title": e.title,
                "chapter": e.chapter,
            }
            for e in quality_report.toc_entries
        ]
        save_profile(cached, book_slug)  # persist refreshed data
        logger.info(
            "[profiler] Cache hit for '%s'; refreshed %d corrected headings, %d TOC sections",
            book_slug,
            len(cached.corrected_headings),
            len(cached.toc_sections),
        )
        return cached

    logger.info("No cached profile for '%s' — invoking LLM profiler", book_slug)
    profile = await profile_book(mmd_text, book_slug, quality_report)
    save_profile(profile, book_slug)
    return profile


# ---------------------------------------------------------------------------
# Public: legacy compatibility
# ---------------------------------------------------------------------------


def legacy_profile_from_config(book_config: dict) -> BookProfile:
    """
    Build a BookProfile from an existing books.yaml / BOOK_REGISTRY entry.

    This provides backward compatibility so the 16 existing math books can run
    through the new chunk_parser code path with identical behaviour to the old
    hardcoded constants in chunk_parser.py.

    Mapping:
      chunk_parser._NOISE_HEADING_PATTERNS → noise_patterns
      chunk_parser._EXERCISE_ZONE_PATTERN  → exercise_markers (zone_chapter_end)
      chunk_parser._EXERCISE_HEADING_PATTERN → exercise_markers (inline_single)
      chunk_parser._MAX_REAL_SECTION_IN_CHAPTER → max_sections_per_chapter
      chunk_parser.MIN_SECTION_BODY_WORDS  → min_chunk_words
      config.BACK_MATTER_MARKERS           → back_matter_markers
      config.BOILERPLATE_PATTERNS          → boilerplate_patterns

    Args:
        book_config: A single entry from BOOK_REGISTRY (the dict returned by
                     config.get_book_config() or config.BOOK_REGISTRY[code]).

    Returns:
        BookProfile that reproduces the hardcoded chunk_parser behaviour exactly.
    """
    book_slug = book_config.get("book_slug", "unknown")
    subject = book_config.get("subject", "mathematics")

    # ── Noise patterns (from chunk_parser._NOISE_HEADING_PATTERNS) ───────────
    # These are the exact pattern strings the compiled regexes match on.
    # We convert them to anchored regex strings for the profile.
    noise_patterns: list[str] = [
        r"^EXAMPLE\b",
        r"^TRY IT\b",
        r"^Solution\b",
        r"^HOW TO\b",
        r"^MANIPULATIVE\b",
        r"^Self Check\b",
        r"^In the following exercises\b",
        r"^Access for free\b",
        r"^\([a-z0-9]\)\s+Solution\b",
        r"^\(\s*[A-Z]\s*\)?\s+Solution\b",
        r"^[A-Z]{2,}$",
        r"^\d+\.\s",
        r"^LINK TO LEARNING\b",
        r"^CHAPTER OUTLINE\b",
        r"^INTRODUCTION$",
        r"^LEARNING OBJECTIVES?\b",
        # config.CONTENT_EXCLUDE_MARKERS mapped to anchored patterns
        r"^BE PREPARED\b",
        r"^ACCESS ADDITIONAL ONLINE RESOURCES\b",
    ]

    # ── Exercise markers (from chunk_parser._EXERCISE_ZONE_PATTERN and
    #                       chunk_parser._EXERCISE_HEADING_PATTERN) ─────────────
    # _EXERCISE_ZONE_PATTERN alternatives — these start an exercise zone
    exercise_zone_patterns = [
        r"^section\s+\d+\.\d+",  # SECTION 1.1 EXERCISES
        r"^review exercises?",
        r"^chapter\s+review",
        r"^practice\s+test",
        r"^chapter\s+test",
    ]
    # books.yaml may provide a custom exercise_marker_pattern
    custom_exercise = book_config.get("exercise_marker_pattern")
    if custom_exercise:
        exercise_zone_patterns.insert(0, custom_exercise)

    exercise_markers: list[ExerciseMarker] = [
        ExerciseMarker(pattern=p, behavior="zone_section_end")
        for p in exercise_zone_patterns
    ]

    # _EXERCISE_HEADING_PATTERN alternatives — inline exercise headings
    inline_exercise_patterns = [
        r"^practice makes perfect?",
        r"^mixed practice",
        r"^everyday math",
        r"^writing exercises?",
    ]
    exercise_markers += [
        ExerciseMarker(pattern=p, behavior="inline_single")
        for p in inline_exercise_patterns
    ]

    # ── Heading hierarchy (OpenStax math book standard) ───────────────────────
    heading_hierarchy: list[HeadingLevel] = [
        HeadingLevel(
            level="chapter",
            md_pattern=r"^#{1,2}\s+(?:chapter|unit|part)\s+\d+",
            id_extractor=r"(?:chapter|unit|part)\s+(\d+)",
            examples=["## Chapter 1"],
        ),
        HeadingLevel(
            level="section",
            md_pattern=r"^#{1,4}\s+\d+\.\d+\s+\S",
            id_extractor=r"(\d+)\.(\d+)\s+(.+)",
            examples=["### 1.1 Introduction to Whole Numbers"],
        ),
        HeadingLevel(
            level="subsection",
            md_pattern=r"^##\s+[A-Z].+",
            examples=["## Identify Whole Numbers"],
        ),
    ]

    # ── Subsection signals (OpenStax math books use ## for subsections) ───────
    subsection_signals: list[SubsectionSignal] = [
        SubsectionSignal(signal_type="heading_h2", is_boundary=True),
        SubsectionSignal(signal_type="heading_h3", is_boundary=False),
        SubsectionSignal(signal_type="heading_h4", is_boundary=False),
        SubsectionSignal(signal_type="bold_line", is_boundary=False),
        SubsectionSignal(signal_type="caps_line", is_boundary=False),
        SubsectionSignal(signal_type="numbered", is_boundary=False),
    ]

    return BookProfile(
        book_slug=book_slug,
        subject=subject,
        heading_hierarchy=heading_hierarchy,
        section_id_format="{book_slug}_{chapter}.{section}",
        toc_sections=[],  # populated at runtime from graph.json
        subsection_signals=subsection_signals,
        feature_box_patterns=[
            r"^HOW TO\b",
            r"^TRY IT\b",
            r"^MEDIA\b",
            r"^LINK TO LEARNING\b",
            r"^LEARNING OBJECTIVES?\b",
        ],
        noise_patterns=noise_patterns,
        exercise_markers=exercise_markers,
        # chunk_parser.MIN_SECTION_BODY_WORDS = 30 (intentionally lower than DEFAULT_MIN_CHUNK_WORDS)
        min_chunk_words=30,
        max_chunk_words=DEFAULT_MAX_CHUNK_WORDS,
        # chunk_parser._MAX_REAL_SECTION_IN_CHAPTER = 10
        max_sections_per_chapter=10,
        back_matter_markers=list(BACK_MATTER_MARKERS),
        boilerplate_patterns=list(BOILERPLATE_PATTERNS),
        corrected_headings={},  # backward compat: no corrections in legacy config path
    )


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    import sys as _sys
    from pathlib import Path as _Path

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    book_slug_arg = _sys.argv[1] if len(_sys.argv) > 1 else "prealgebra"
    force_regen = "--force" in _sys.argv

    mmd_path = OUTPUT_DIR / book_slug_arg / "book.mmd"
    if not mmd_path.exists():
        print(f"ERROR: {mmd_path} not found")
        _sys.exit(1)

    # If force flag, delete cached profile
    if force_regen:
        cached_path = OUTPUT_DIR / book_slug_arg / "book_profile.json"
        if cached_path.exists():
            cached_path.unlink()
            print(f"Deleted cached profile: {cached_path}")

    # Import ocr_validator here to avoid circular imports at module level
    _src_extraction = _Path(__file__).resolve().parent
    if str(_src_extraction.parent) not in _sys.path:
        _sys.path.insert(0, str(_src_extraction.parent))

    from extraction.ocr_validator import validate_and_analyze

    mmd_text = mmd_path.read_text(encoding="utf-8")
    quality_report = validate_and_analyze(mmd_text, book_slug_arg)

    print(f"\nOCR quality score: {quality_report.quality_score:.3f}")
    print(f"TOC entries: {len(quality_report.toc_entries)}")
    print(f"Signal stats (recurring headings): {len(quality_report.signal_stats)}")

    profile = asyncio.run(load_or_create_profile(mmd_text, book_slug_arg, quality_report))

    print(f"\n{'='*60}")
    print(f"BookProfile for '{profile.book_slug}'")
    print(f"  subject:                {profile.subject}")
    print(f"  heading_hierarchy:      {len(profile.heading_hierarchy)} levels")
    print(f"  toc_sections:           {len(profile.toc_sections)}")
    print(f"  subsection_signals:     {len(profile.subsection_signals)}")
    print(f"  feature_box_patterns:   {len(profile.feature_box_patterns)}")
    print(f"  noise_patterns:         {len(profile.noise_patterns)}")
    print(f"  exercise_markers:       {len(profile.exercise_markers)}")
    print(f"  min_chunk_words:        {profile.min_chunk_words}")
    print(f"  max_chunk_words:        {profile.max_chunk_words}")
    print(f"  max_sections_per_chapter: {profile.max_sections_per_chapter}")
    print(f"  back_matter_markers:    {len(profile.back_matter_markers)}")
    print(f"  boilerplate_patterns:   {len(profile.boilerplate_patterns)}")

    if profile.subsection_signals:
        print("\nSubsection signals:")
        for sig in profile.subsection_signals:
            boundary_str = "BOUNDARY" if sig.is_boundary else "body content"
            print(f"  {sig.signal_type:<20} → {boundary_str}")

    if profile.exercise_markers:
        print("\nExercise markers:")
        for em in profile.exercise_markers[:8]:
            print(f"  [{em.behavior}]  {em.pattern[:60]}")

    if profile.noise_patterns:
        print("\nNoise patterns (first 8):")
        for p in profile.noise_patterns[:8]:
            print(f"  {p}")
