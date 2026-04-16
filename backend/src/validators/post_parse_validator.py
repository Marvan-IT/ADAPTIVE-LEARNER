"""
Post-parse validator — runs between chunk parsing and graph building.
Blocks the pipeline if critical quality thresholds are not met.
"""
import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def validate_parsed_book(
    book_slug: str,
    chunks: list,  # list[ParsedChunk]
    mmd_text: str,
) -> ValidationResult:
    """
    Validate parsed chunks against quality thresholds.
    Returns ValidationResult with pass/fail, errors, warnings, and stats.
    """
    errors = []
    warnings = []

    # ── Check 1: TOC coverage ──
    # Parse TOC from MMD, verify each TOC section has chunks
    toc_sections = set()
    for m in re.finditer(r'^(\d+\.\d+)\s+.+?\.{3,}\s*\d+', mmd_text, re.MULTILINE):
        toc_sections.add(m.group(1))

    if toc_sections:
        parsed_sections = set()
        for c in chunks:
            parts = c.section.split()
            if parts:
                nums = parts[0]
                if re.match(r'\d+\.\d+', nums):
                    parsed_sections.add(nums)

        missing = toc_sections - parsed_sections
        if missing:
            miss_pct = len(missing) / len(toc_sections)
            if miss_pct > 0.50:
                # More than half missing = hard error (Mathpix likely failed)
                errors.append(
                    f"TOC coverage: {len(missing)}/{len(toc_sections)} ({miss_pct:.0%}) sections missing: {sorted(missing)[:10]}"
                )
            else:
                # Some missing = warning (Mathpix formatting gaps, not critical)
                warnings.append(
                    f"TOC coverage: {len(missing)}/{len(toc_sections)} ({miss_pct:.0%}) sections missing: {sorted(missing)[:5]}"
                )

        # Check for phantom sections (in chunks but not in TOC)
        phantom = parsed_sections - toc_sections
        if phantom:
            warnings.append(
                f"Phantom sections (in chunks but not TOC): {sorted(phantom)[:10]}"
            )
    else:
        warnings.append("No TOC found in MMD — cannot verify section coverage")

    # ── Check 2: Chunk count sanity ──
    if len(chunks) == 0:
        errors.append("Zero chunks produced — pipeline produced no output")
    elif len(chunks) < 10:
        errors.append(f"Only {len(chunks)} chunks produced — suspiciously low")

    # ── Check 3: Chunk size distribution ──
    word_counts = [len(c.text.split()) for c in chunks]
    mean_wc = 0.0
    p10 = p50 = p90 = 0
    if word_counts:
        sorted_wc = sorted(word_counts)
        p10 = sorted_wc[len(word_counts) // 10]
        p50 = statistics.median(word_counts)
        p90 = sorted_wc[9 * len(word_counts) // 10]
        mean_wc = statistics.mean(word_counts)

        if p10 < 30:
            warnings.append(f"P10 chunk size is {p10} words — many tiny fragments")
        if p50 < 100:
            warnings.append(f"P50 chunk size is {p50:.0f} words — median too small")

        tiny_count = sum(1 for w in word_counts if w < 50)
        if tiny_count > len(chunks) * 0.1:
            warnings.append(
                f"{tiny_count} chunks under 50 words ({tiny_count / len(chunks):.0%})"
            )

    # ── Check 4: Section ordering ──
    prev = (0, 0)
    prev_sec = ""
    out_of_order = 0
    for c in chunks:
        parts = c.section.split()
        if parts:
            nums = parts[0].split(".")
            if len(nums) == 2:
                try:
                    curr = (int(nums[0]), int(nums[1]))
                    if c.section != prev_sec:
                        if curr < prev:
                            out_of_order += 1
                        prev = curr
                        prev_sec = c.section
                except ValueError:
                    pass
    if out_of_order > 0:
        errors.append(
            f"Section ordering: {out_of_order} sections out of numeric order"
        )

    # ── Check 5: Image accounting ──
    mmd_images = (
        len(re.findall(r'!\[\]\([^)]+\)', mmd_text))
        + len(re.findall(re.escape('\\') + r'includegraphics[^{]*\{[^}]+\}', mmd_text))
    )
    chunk_images = sum(len(c.image_urls) for c in chunks)
    if mmd_images > 0:
        retention = chunk_images / mmd_images
        if retention < 0.5:
            warnings.append(
                f"Image retention {retention:.0%} — {chunk_images}/{mmd_images} images in chunks"
            )

    # ── Check 6: Word retention ──
    # Approximate: total words in chunks vs total words in body sections of MMD
    total_chunk_words = sum(word_counts) if word_counts else 0

    # ── Build stats ──
    stats = {
        "chunks": len(chunks),
        "sections": len(set(c.section for c in chunks)),
        "toc_sections": len(toc_sections),
        "total_words": total_chunk_words,
        "avg_chunk_words": round(mean_wc, 1) if word_counts else 0,
        "p10_words": p10 if word_counts else 0,
        "p50_words": round(p50, 1) if word_counts else 0,
        "p90_words": p90 if word_counts else 0,
        "images_in_mmd": mmd_images,
        "images_in_chunks": chunk_images,
        "out_of_order": out_of_order,
    }

    passed = len(errors) == 0

    # Log results
    if passed:
        logger.info(
            "[validator] %s PASSED — %d chunks, %d sections, %d words",
            book_slug, len(chunks), stats["sections"], total_chunk_words,
        )
    else:
        logger.error(
            "[validator] %s FAILED — %d errors: %s",
            book_slug, len(errors), "; ".join(errors),
        )
    for w in warnings:
        logger.warning("[validator] %s: %s", book_slug, w)

    return ValidationResult(passed=passed, errors=errors, warnings=warnings, stats=stats)


class PipelineValidationError(Exception):
    """Raised when post-parse validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Pipeline validation failed: {'; '.join(errors)}")
