"""
Vision Annotator — generates semantic descriptions for extracted math images
using GPT-4o Vision. Results are cached to disk by MD5(image_bytes).

Only processes FORMULA and DIAGRAM image types. DECORATIVE images are
returned immediately with null fields without any API call.

Cache location: {cache_dir}/vision_{md5_hex}.json
Cache key:      MD5(image_bytes)
"""

import asyncio
import base64
import hashlib
import json
import logging
import sys
import os
from pathlib import Path

from openai import AsyncOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import OPENAI_MODEL

logger = logging.getLogger(__name__)

# ── Prompt templates ──────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an expert mathematics educator analysing images extracted from "
    "OpenStax mathematics textbooks.\n\n"
    "Respond ONLY with a JSON object in this exact format — no markdown, no "
    "code blocks, no extra text:\n"
    '{"description": "<2-4 sentences describing exactly what mathematical objects are shown '
    "and how they help a student understand the concept in the section. "
    "Be concrete — name the objects (axes, number line, triangle, graph, equation, etc.) and "
    "explain the insight. Write as if pointing to it while tutoring: "
    "'The number line here goes from 0 to 6 with tick marks at every integer. "
    "Moving right means getting bigger, so you can see at a glance that 4 > 2 because "
    "4 is further right — this makes the abstract idea of ordering numbers completely concrete.'\", "
    '"is_educational": <true ONLY if a teacher would explicitly point to this image during a lesson '
    "to explain a mathematical concept — e.g. a number line, coordinate graph, geometric figure, "
    "worked-out equation, labelled diagram, or table of numerical data showing a mathematical pattern. "
    "Set to false for ALL of the following: logos, icons, photos of people or places, "
    "decorative borders, colour swatches, small bullets or arrows, chapter/section heading art, "
    "page number ornaments, self-assessment checklists, rubrics, learning-objective boxes, "
    "'try it' or 'be prepared' boxes without mathematical diagrams, "
    "or any image whose primary purpose is decoration or navigation rather than "
    "explaining a mathematical idea directly>}\n\n"
    "DESCRIPTION QUALITY STANDARD — every description MUST include:\n"
    "1. The EXACT visual math objects present (e.g., 'a number line from −5 to 5 with tick marks "
    "at each integer', 'a fraction bar divided into 8 equal parts with 3 parts shaded in blue')\n"
    "2. Any NUMBERS, LABELS, or ANNOTATIONS visible in the image — read them exactly as shown\n"
    "3. The TYPE of visual aid — choose one: number line / fraction bar / area model / coordinate grid "
    "/ geometric figure / place value chart / balance scale / bar model / percent bar / pie chart "
    "/ step-by-step diagram / table / other\n"
    "4. ONE sentence on how this visual specifically helps a student understand the concept\n\n"
    "BAD description (too vague): 'A diagram showing numbers.'\n"
    "GOOD description: 'A horizontal number line from 0 to 10 with integer tick marks. The point at 7 "
    "is marked with a red dot labeled \"7\". An arrow sweeps right from 0 to 7 labeled \"+7\", "
    "illustrating counting forward on the number line to find a sum.'\n\n"
    "Be STRICT: when in doubt, set is_educational to false. "
    "Only mark true if the image would genuinely help a student understand or visualise "
    "the mathematics described in the section title."
)


def _user_prompt(concept_title: str, image_type: str, concept_context: str = "") -> str:
    """Build the user-turn message for the vision API call."""
    context_line = (
        f"\nConcept context (first lines of textbook explanation): {concept_context[:400]}"
        if concept_context
        else ""
    )
    return (
        f"This image was extracted from a section titled '{concept_title}'.\n"
        f"It has been classified as a {image_type} image.{context_line}\n"
        "Describe its mathematical content and pedagogical relevance."
    )


# Sentinel results — used as return values to avoid constructing new dicts
# on every call while keeping the values clearly named.
# is_educational=False ensures logos/icons/errors are filtered by the caller.
SKIP_RESULT: dict = {"description": None, "relevance": None, "is_educational": False}
ERROR_RESULT: dict = {"description": None, "relevance": None, "is_educational": False}


# ── Public API ────────────────────────────────────────────────────────

async def annotate_image(
    image_bytes: bytes,
    concept_title: str,
    image_type: str,
    llm_client: AsyncOpenAI,
    model: str = OPENAI_MODEL,
    cache_dir: Path | None = None,
    concept_context: str = "",
) -> dict:
    """
    Annotate a single image using GPT-4o Vision.

    Args:
        image_bytes:     Raw binary image data.
        concept_title:   Title of the concept this image belongs to.
        image_type:      "FORMULA" or "DIAGRAM" (DECORATIVE is skipped).
        llm_client:      Shared AsyncOpenAI client instance.
        model:           OpenAI model to use (defaults to OPENAI_MODEL from config).
        cache_dir:       Directory for caching annotation results. If None,
                         caching is disabled.
        concept_context: Optional first ~400 chars of the section's textbook text.
                         Included in the user message to ground the description.
                         Note: changing this value changes the user prompt and
                         therefore will not hit the MD5-keyed cache from prior
                         runs that lacked context.

    Returns:
        {"description": str | None, "relevance": str | None}
        Returns None values without API call for DECORATIVE images.
        Returns None values on API or parse error (logged as WARNING).
    """
    # DECORATIVE images are not worth annotating — skip immediately.
    if image_type not in ("FORMULA", "DIAGRAM"):
        logger.debug("Skipping annotation for %s image type", image_type)
        return SKIP_RESULT

    # ── Cache lookup ──────────────────────────────────────────────────
    md5_hash = hashlib.md5(image_bytes).hexdigest()
    cache_path: Path | None = None

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"vision_{md5_hash}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                logger.debug("Cache hit for image hash %s", md5_hash)
                return cached
            except Exception as exc:
                logger.warning("Cache read failed for %s: %s", cache_path, exc)
                # Fall through to a fresh API call.

    # ── Build base64 payload ──────────────────────────────────────────
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Detect MIME type from magic bytes so the API receives the correct header.
    mime = "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif image_bytes[:4] == b"GIF8":
        mime = "image/gif"

    # ── Vision API call ───────────────────────────────────────────────
    try:
        response = await llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{b64}",
                                "detail": "high",
                            },
                        },
                        {
                            "type": "text",
                            "text": _user_prompt(concept_title, image_type, concept_context),
                        },
                    ],
                },
            ],
            temperature=0.2,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning(
            "Vision API call failed for image hash %s (concept: %s): %s",
            md5_hash,
            concept_title,
            exc,
        )
        return ERROR_RESULT

    # ── Parse response ────────────────────────────────────────────────
    raw = (response.choices[0].message.content or "").strip()
    try:
        parsed = json.loads(raw)
        annotation = {
            # Coerce empty strings to None so callers can use a simple truthiness check.
            "description": parsed.get("description") or None,
            # relevance field removed from prompt — kept as None for schema compatibility
            "relevance": None,
            "is_educational": bool(parsed.get("is_educational", True)),
        }
    except json.JSONDecodeError as exc:
        logger.warning(
            "Vision response parse failed for image hash %s: %s — raw: %r",
            md5_hash,
            exc,
            raw[:200],
        )
        return ERROR_RESULT

    # ── Write cache ───────────────────────────────────────────────────
    if cache_path is not None:
        try:
            cache_path.write_text(
                json.dumps(annotation, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug("Cached annotation for image hash %s", md5_hash)
        except Exception as exc:
            logger.warning("Cache write failed for %s: %s", cache_path, exc)

    logger.info(
        "Annotated %s image for concept '%s': %s",
        image_type,
        concept_title,
        annotation["description"],
    )
    return annotation
