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
    "OpenStax mathematics textbooks. Your task is to describe the mathematical "
    "content of the image and explain its pedagogical purpose so that a "
    "teaching AI can reference it accurately when tutoring a student.\n\n"
    "Respond ONLY with a JSON object in this exact format — no markdown, no "
    "code blocks, no extra text:\n"
    '{"description": "<concise description of what the image shows>", '
    '"relevance": "<one sentence explaining why this image matters for understanding the concept>", '
    '"is_educational": <true if this is genuine math content such as a formula, equation, '
    "number line, graph, or diagram that helps a student learn; "
    "false if it is a logo, icon, institutional photo, or decorative illustration>}"
)


def _user_prompt(concept_title: str, image_type: str) -> str:
    """Build the user-turn message for the vision API call."""
    return (
        f"This image was extracted from a section titled '{concept_title}'. "
        f"It has been classified as a {image_type} image. "
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
) -> dict:
    """
    Annotate a single image using GPT-4o Vision.

    Args:
        image_bytes:   Raw binary image data.
        concept_title: Title of the concept this image belongs to.
        image_type:    "FORMULA" or "DIAGRAM" (DECORATIVE is skipped).
        llm_client:    Shared AsyncOpenAI client instance.
        model:         OpenAI model to use (defaults to OPENAI_MODEL from config).
        cache_dir:     Directory for caching annotation results. If None,
                       caching is disabled.

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
                            "text": _user_prompt(concept_title, image_type),
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
            "relevance": parsed.get("relevance") or None,
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
