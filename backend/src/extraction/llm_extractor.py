"""
LLM Extractor — uses GPT to extract clean instructional content
from raw Mathpix OCR text.

Replaces the regex-based content_filter for higher-quality extraction.
Results are cached to disk to avoid re-calling the LLM for the same section.
"""

import json
import re
import time
import hashlib
from pathlib import Path
from typing import Optional

from openai import OpenAI

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL


# ── Rate limiting ────────────────────────────────────────────────────
_last_request_time = 0.0
LLM_RATE_LIMIT_SECONDS = 1.0


def _rate_limit():
    """Enforce minimum delay between OpenAI API calls."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < LLM_RATE_LIMIT_SECONDS:
        time.sleep(LLM_RATE_LIMIT_SECONDS - elapsed)
    _last_request_time = time.time()


# ── System prompt ────────────────────────────────────────────────────
EXTRACTION_SYSTEM_PROMPT = r"""You are the ADA Curriculum Extraction Engine.

Your task is to extract and CLEAN UP ONE complete concept block
from the provided textbook instructional subsection.

This is a CONTENT EXTRACTION + FORMATTING task.

==================================================
PRIMARY OBJECTIVE
==================================================

Produce ONE concept block that captures the COMPLETE instructional
content of the given section. ONE section = ONE concept block.

- Is mathematically valid.
- Includes ALL definitions, explanations, worked examples, and
  formal statements from this section.
- Is independently teachable.
- Contains real mathematical substance.
- Is clean, well-organized, and database-ready.

IMPORTANT: Do NOT pick a single sub-topic from the section.
Include ALL instructional paragraphs, ALL definitions, ALL worked
examples with their solutions, and ALL mathematical properties
taught in this section. The concept block should represent the
ENTIRE section's teaching content.

==================================================
FORMATTING AND ENHANCEMENT RULES
==================================================

You MUST:

1. Keep ALL the same concepts, topics, definitions, and
   mathematical content — do NOT change the meaning.
2. Organize the content clearly with headings, subheadings,
   and logical structure.
3. Format step-by-step procedures as numbered steps.
4. Format definitions and properties in clear, labeled blocks.
5. Format worked examples with clear "Example" labels and
   step-by-step solutions.
6. Fill in missing or broken mathematical expressions where
   the OCR failed to capture them (infer from context).
7. Add clear example values where the original text had blanks
   or placeholders due to OCR issues.
8. Make explanations smoother and easier to read while
   preserving the original teaching intent.
9. Use proper formatting: headings for sub-topics, bold for
   key terms, numbered lists for procedures.
10. DO NOT add new concepts or topics not in the original text.
11. DO NOT remove any concepts or topics from the original text.
12. DO NOT change the mathematical correctness of any statement.

==================================================
CONTENT TO REMOVE
==================================================

Remove the following non-instructional content:

- Headers and footers.
- Page numbers.
- Repeated boilerplate (e.g., "Access for free at openstax.org").
- Figure captions and image references.
- Table formatting artifacts.
- Marketing text.
- Chapter outlines.
- Learning objectives lists.
- TRY IT sections (practice prompts without solutions).
- Self-check sections.
- Readiness quizzes.
- Navigation artifacts.
- Front matter and table of contents.
- Practice problems without solutions.
- Exercises without solutions.
- Review questions.
- Orphan headings with no content.
- Meta-text referencing other sections without standalone substance.

==================================================
MATHEMATICAL SUBSTANCE REQUIREMENT
==================================================

The concept block MUST contain at least one of:

- A mathematical definition.
- A mathematical explanation.
- A numeric example.
- An equation.
- A worked example.
- A place value analysis.
- A formal mathematical statement.
- Symbolic expressions that students can study.

If, after cleaning, the subsection contains only meta-discussion
and no real mathematical content:

RETURN:

{
  "status": "INVALID",
  "reason": "<explain why insufficient mathematical substance>"
}

==================================================
CONCEPT SCOPE RULE
==================================================

- ONE textbook section = ONE concept block.
- Include ALL instructional content from this section:
  all definitions, all explanations, all worked examples
  with solutions, all mathematical properties and rules.
- Do NOT cherry-pick a single sub-topic. Extract EVERYTHING
  that teaches the student within this section.
- Remove only non-instructional content listed above.
- The concept block should be COMPREHENSIVE for this section.
- Do not leave incomplete ideas.
- Do not include partial explanations.

==================================================
LATEX HANDLING
==================================================

- Preserve all LaTeX expressions from the Mathpix OCR.
- Fix broken or incomplete LaTeX where OCR failed.
- Fill in missing LaTeX expressions that are clearly implied
  by the surrounding text.
- Return LaTeX expressions in a separate array.
- Remove LaTeX delimiters ($...$ and $$...$$) from the main
  text body and place the expressions in the latex array.

==================================================
DIAGRAM HANDLING
==================================================

- Do NOT embed diagrams inside text.
- Maintain the provided ordered diagram references.
- Associate them with this concept only if page-overlapping.
- Return diagram references in the output metadata.

==================================================
OUTPUT FORMAT (STRICT JSON)
==================================================

Return ONLY valid JSON.

If valid:

{
  "concept_title": "<Section title>",
  "text": "<Clean, well-formatted instructional text>",
  "latex": ["<latex expression>", "..."],
  "diagrams": ["<diagram_id_1>", "<diagram_id_2>"],
  "source_pages": [<page numbers>]
}

If invalid:

{
  "status": "INVALID",
  "reason": "<why>"
}

NO extra text.
NO commentary.
NO markdown.
ONLY JSON."""


# ── Singleton OpenAI client ──────────────────────────────────────────
_client: Optional[OpenAI] = None


def _get_client() -> Optional[OpenAI]:
    """Get or create a singleton OpenAI client."""
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            return None
        _client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    return _client


def extract_concept_with_llm(
    combined_text: str,
    section_title: str,
    section_id: str,
    book_slug: str,
    source_pages: list[int],
    cache_dir: Optional[Path] = None,
) -> Optional[dict]:
    """
    Send combined Mathpix OCR text for one section to GPT and get
    cleaned instructional text + LaTeX array.

    Args:
        combined_text: The joined Mathpix OCR text for all pages in the section.
        section_title: e.g., "Introduction to Whole Numbers"
        section_id: e.g., "PREALG.C1.S1" (for cache key only)
        book_slug: e.g., "prealgebra"
        source_pages: list of 1-indexed page numbers
        cache_dir: directory for caching LLM results

    Returns:
        dict with keys "text", "latex", "diagrams", "_cached"
        or None on failure
    """
    if not combined_text.strip():
        return None

    # ── Check cache ──────────────────────────────────────────────
    cache_file = None
    if cache_dir:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        text_hash = hashlib.md5(combined_text.encode("utf-8")).hexdigest()[:12]
        cache_file = cache_dir / f"{section_id}_{text_hash}.json"
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                cached["_cached"] = True
                return cached
            except (json.JSONDecodeError, IOError):
                pass  # corrupted cache, re-extract

    # ── Extract LaTeX from raw text for the prompt ───────────────
    latex_in_text = _extract_latex_from_raw(combined_text)

    # ── Build user message ───────────────────────────────────────
    user_message = (
        f"SECTION: {section_id.split('.')[-0]} {section_title}\n"
        f"PAGE NUMBERS: {source_pages}\n\n"
        f"MATHPIX-EXTRACTED LATEX EXPRESSIONS:\n"
        f"{json.dumps(latex_in_text, indent=2)}\n\n"
        f"DIAGRAM REFERENCES: []\n\n"
        f"RAW TEXTBOOK SUBSECTION TEXT:\n{combined_text}"
    )

    # ── Call OpenAI API ──────────────────────────────────────────
    client = _get_client()
    if client is None:
        print("  Warning: OPENAI_API_KEY not set. Cannot use LLM extraction.")
        return None

    _rate_limit()

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_completion_tokens=16384,
            temperature=0.0,
        )
    except Exception as e:
        print(f"  LLM API error for {section_id}: {e}")
        return None

    # ── Parse response ───────────────────────────────────────────
    raw_content = response.choices[0].message.content
    if not raw_content:
        print(f"  LLM returned empty response for {section_id}")
        return None

    result = _parse_llm_response(raw_content, section_id)
    if result is None:
        return None

    # Check if LLM returned INVALID status
    if result.get("status") == "INVALID":
        print(f"  LLM marked {section_id} as INVALID: {result.get('reason', 'unknown')}")
        return None

    result["_cached"] = False

    # ── Cache the result ─────────────────────────────────────────
    if cache_file:
        try:
            cache_file.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except IOError as e:
            print(f"  Warning: Could not cache LLM result for {section_id}: {e}")

    return result


def _extract_latex_from_raw(text: str) -> list[str]:
    """Extract LaTeX expressions from Mathpix markdown to include in the prompt."""
    latex = []
    # Display math: $$...$$
    for match in re.finditer(r"\$\$(.+?)\$\$", text, re.DOTALL):
        expr = match.group(1).strip()
        if expr and len(expr) > 1:
            latex.append(expr)
    # Inline math: $...$ (not $$)
    for match in re.finditer(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", text):
        expr = match.group(1).strip()
        if expr and len(expr) > 1:
            latex.append(expr)
    return list(set(latex))


def _parse_llm_response(raw_content: str, section_id: str) -> Optional[dict]:
    """
    Parse the LLM JSON response, handling code fences and minor issues.
    """
    content = raw_content.strip()

    # Strip markdown code fences
    if content.startswith("```"):
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)

    # Try parsing JSON
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        # Try fixing trailing commas
        try:
            cleaned = re.sub(r",\s*([}\]])", r"\1", content)
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"  JSON parse error for {section_id}: {e}")
            print(f"  First 200 chars: {content[:200]}")
            return None

    # Handle INVALID status from LLM
    if data.get("status") == "INVALID":
        return data

    # Validate required fields
    if "text" not in data:
        print(f"  LLM response missing 'text' field for {section_id}")
        return None

    # Normalize
    result = {
        "text": data.get("text", ""),
        "latex": data.get("latex", []),
        "diagrams": data.get("diagrams", []),
    }

    # Ensure latex is a list of strings
    if not isinstance(result["latex"], list):
        result["latex"] = []
    result["latex"] = [str(expr) for expr in result["latex"] if expr]

    return result
