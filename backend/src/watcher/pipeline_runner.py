"""
6-stage pipeline runner for a single book.
Spawned as subprocess by book_watcher.py.

Usage:
    python -m src.watcher.pipeline_runner --pdf /path/to/book.pdf --subject physics
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import OUTPUT_DIR, BACKEND_DIR
from src.extraction.calibrate import derive_slug, derive_code

logger = logging.getLogger(__name__)


def _wait_for_stable_file(path: Path, stable_secs: int = 5, poll_interval: int = 1, timeout: int = 300) -> None:
    """Block until the file size stops changing (file fully written) or raise RuntimeError on timeout."""
    import os as _os
    deadline = time.monotonic() + timeout
    stable_count = 0
    last_size = -1
    while time.monotonic() < deadline:
        try:
            size = _os.path.getsize(path)
        except OSError:
            size = -1
        if size == last_size and size >= 0:
            stable_count += 1
            if stable_count >= stable_secs:
                return
        else:
            stable_count = 0
            last_size = size
        time.sleep(poll_interval)
    raise RuntimeError(f"File did not stabilise within {timeout}s: {path}")


def _append_to_books_yaml(entry: dict) -> None:
    """Append a new book entry to books.yaml if not already present."""
    import yaml
    yaml_path = BACKEND_DIR / "books.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {"books": []}
    existing = {b["book_slug"] for b in data.get("books", [])}
    if entry["book_slug"] in existing:
        logger.info("'%s' already in books.yaml — skipping", entry["book_slug"])
        return
    data["books"].append(entry)
    yaml_path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    logger.info("Registered '%s' in books.yaml", entry["book_slug"])


def _setup_file_log(slug: str) -> None:
    log_path = OUTPUT_DIR / slug / "pipeline.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(str(log_path))
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(fh)


async def run_pipeline(pdf_path: Path, subject: str, slug_override: str | None = None) -> None:
    from src.pipeline import run_mathpix_extraction
    from src.extraction.chunk_builder import build_chunks, validate_and_clean_images
    from src.db.connection import async_session_factory
    from src.validators.post_parse_validator import PipelineValidationError

    slug = slug_override or derive_slug(pdf_path.name)
    code = derive_code(slug)  # may collide; resolved from books.yaml after Stage 1
    _setup_file_log(slug)

    logger.info("[%s] Waiting for file to stabilise...", slug)
    await asyncio.to_thread(_wait_for_stable_file, pdf_path)
    logger.info("[%s] File stable, starting pipeline.", slug)

    logger.info("[%s] Pipeline started", slug)

    try:
        # Stage 1 — Register book metadata in books.yaml + BOOK_REGISTRY
        logger.info("[%s] Stage 1/6: Registering book metadata...", slug)
        entry = {
            "book_code": code,
            "book_slug": slug,
            "pdf_filename": f"{subject}/{pdf_path.name}",
            "title": slug.replace("_", " ").title(),
            "subject": subject,
        }
        _append_to_books_yaml(entry)
        # Resolve authoritative book_code from books.yaml (derive_code can collide)
        import yaml as _yaml
        _bk_data = _yaml.safe_load((BACKEND_DIR / "books.yaml").read_text(encoding="utf-8"))
        for _b in _bk_data.get("books", []):
            if _b["book_slug"] == slug:
                code = _b["book_code"]
                break
        # Hot-register into ALL in-memory BOOK_REGISTRY instances so stage 2 can find it.
        import sys as _sys
        from src.config import BookConfig as _BookConfig
        _cfg_entry = _BookConfig(**entry).model_dump()
        for _mod_name in ("src.config", "config"):
            _mod = _sys.modules.get(_mod_name)
            if _mod and hasattr(_mod, "BOOK_REGISTRY"):
                _mod.BOOK_REGISTRY[code] = _cfg_entry
                if hasattr(_mod, "BOOK_CODE_MAP"):
                    _mod.BOOK_CODE_MAP[slug] = code
                logger.info("[%s] Hot-registered '%s' into %s.BOOK_REGISTRY", slug, code, _mod_name)
        logger.info("[%s] Stage 1/6: Done", slug)

        # Stage 2 — Mathpix whole-PDF extraction (sync → thread so we don't block)
        logger.info("[%s] Stage 2/6: Mathpix PDF extraction (30–60 min)...", slug)
        await asyncio.to_thread(run_mathpix_extraction, code)
        logger.info("[%s] Stage 2/6: Done", slug)

        # Stage 3 — Chunk pipeline (universal parser + embed + persist + image validation)
        logger.info("[%s] Stage 3/6: Building chunks & embeddings...", slug)
        mmd_path = OUTPUT_DIR / slug / "book.mmd"
        # Load book profile so exercise vocabulary groups are used (not just hardcoded math defaults)
        from src.extraction.book_profiler import load_or_create_profile
        from src.extraction.ocr_validator import validate_and_analyze
        _mmd_text = mmd_path.read_text(encoding="utf-8")
        _quality = validate_and_analyze(_mmd_text, slug)
        _profile = await load_or_create_profile(_mmd_text, slug, _quality)
        logger.info("[%s] Loaded book profile (subject=%s, exercise_markers=%d)",
                     slug, _profile.subject, len(_profile.exercise_markers))
        async with async_session_factory() as db:
            await build_chunks(slug, mmd_path, db, rebuild=False, profile=_profile)
            removed = await validate_and_clean_images(slug, db)
        logger.info("[%s] Stage 3/6: Done. Removed %d orphan image rows.", slug, removed)

        # Stage 4 — Post-parse validation (blocks pipeline on critical quality failures)
        logger.info("[%s] Stage 4/6: Validating parsed chunks...", slug)
        from src.validators.post_parse_validator import validate_parsed_book
        from src.extraction.chunk_parser import parse_book_mmd, _normalize_mmd_format
        mmd_text = mmd_path.read_text(encoding="utf-8")
        normalized = _normalize_mmd_format(mmd_text)
        # Re-parse to get chunks for validation (build_chunks already saved to DB)
        validation_chunks = parse_book_mmd(mmd_path, slug)
        result = validate_parsed_book(slug, validation_chunks, normalized)
        if not result.passed:
            logger.error("[%s] Validation FAILED: %s", slug, result.errors)
            raise PipelineValidationError(result.errors)
        logger.info("[%s] Stage 4/6: Validation passed: %s", slug, result.stats)

        # Stage 5 — Dependency graph
        logger.info("[%s] Stage 5/6: Building dependency graph...", slug)
        graph_path = OUTPUT_DIR / slug / "graph.json"
        from src.extraction.graph_builder import build_graph
        async with async_session_factory() as db:
            await build_graph(db, slug, graph_path)
        logger.info("[%s] Stage 5/6: Done", slug)

        # Stage 6 — Hot-load into running server
        logger.info("[%s] Stage 6/6: Hot-loading into server...", slug)
        api_base = os.getenv("API_BASE_URL", "http://localhost:8889")
        api_key = os.getenv("API_SECRET_KEY", "")
        try:
            resp = requests.post(
                f"{api_base}/api/admin/load-book/{slug}",
                headers={"X-API-Key": api_key},
                timeout=30,
            )
            resp.raise_for_status()
            logger.info("[%s] Stage 6/6: Hot-load successful", slug)
        except Exception as exc:
            logger.error("[%s] Stage 6/6: Hot-load failed: %s", slug, exc)

        # Stage 7 — Auto-translate catalog to all non-English locales.
        # Non-blocking: failures do not abort publishing; book remains usable in English.
        if os.getenv("SKIP_TRANSLATION", "").lower() not in ("1", "true", "yes"):
            logger.info("[%s] Stage 7/7: Auto-translating catalog to all languages...", slug)
            try:
                from src.db.connection import async_session_factory as _asf_t
                # translate_catalog.py lives under backend/scripts — add to path once.
                _scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
                if str(_scripts_dir) not in sys.path:
                    sys.path.insert(0, str(_scripts_dir))
                from translate_catalog import translate_book  # type: ignore[import-not-found]
                async with _asf_t() as _trans_db:
                    summary = await translate_book(slug, db=_trans_db)
                logger.info(
                    "[%s] Stage 7/7: Translated %d rows across %d languages (%d LLM calls)",
                    slug,
                    summary.get("rows_translated", 0),
                    len(summary.get("languages_succeeded", [])),
                    summary.get("llm_calls", 0),
                )
            except Exception:
                logger.exception("[%s] Stage 7/7: Translation failed — book remains English-only", slug)
        else:
            logger.info("[%s] Stage 7/7: Skipped (SKIP_TRANSLATION set)", slug)

        logger.info("[%s] Pipeline complete", slug)

        # Update books table status to READY_FOR_REVIEW
        try:
            from src.db.connection import async_session_factory as _asf
            from sqlalchemy import text as _text
            async with _asf() as _status_db:
                await _status_db.execute(
                    _text("UPDATE books SET status='READY_FOR_REVIEW' WHERE book_slug=:slug"),
                    {"slug": slug},
                )
                await _status_db.commit()
            logger.info("[%s] Updated books status → READY_FOR_REVIEW", slug)
        except Exception:
            logger.exception("[%s] Could not update books status to READY_FOR_REVIEW", slug)

    except PipelineValidationError as exc:
        logger.error("[%s] Pipeline VALIDATION FAILED: %s", slug, exc.errors)
        try:
            from src.db.connection import async_session_factory as _asf
            from sqlalchemy import text as _text
            async with _asf() as _status_db:
                await _status_db.execute(
                    _text("UPDATE books SET status='VALIDATION_FAILED' WHERE book_slug=:slug"),
                    {"slug": slug},
                )
                await _status_db.commit()
            logger.error("[%s] Updated books status → VALIDATION_FAILED", slug)
        except Exception:
            logger.exception("[%s] Could not update books status to VALIDATION_FAILED", slug)
    except Exception as exc:
        logger.error("[%s] Pipeline FAILED: %s", slug, exc, exc_info=True)
        try:
            from src.db.connection import async_session_factory as _asf
            from sqlalchemy import text as _text
            async with _asf() as _status_db:
                await _status_db.execute(
                    _text("UPDATE books SET status='FAILED' WHERE book_slug=:slug"),
                    {"slug": slug},
                )
                await _status_db.commit()
            logger.error("[%s] Updated books status → FAILED", slug)
        except Exception:
            logger.exception("[%s] Could not update books status to FAILED", slug)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Run full pipeline for a single PDF")
    parser.add_argument("--pdf", required=True, type=Path, help="Path to the PDF file")
    parser.add_argument("--subject", required=True, help="Subject name (from folder name)")
    parser.add_argument("--slug", required=False, default=None, help="Pre-derived slug (from upload title)")
    args = parser.parse_args()
    asyncio.run(run_pipeline(args.pdf, args.subject, slug_override=args.slug))


if __name__ == "__main__":
    main()
