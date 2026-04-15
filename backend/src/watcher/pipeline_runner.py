"""
5-stage pipeline runner for a single book.
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
from src.extraction.calibrate import calibrate_book, derive_slug, derive_code

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


async def run_pipeline(pdf_path: Path, subject: str) -> None:
    from src.pipeline import run_whole_pdf_pipeline
    from src.extraction.chunk_builder import build_chunks, validate_and_clean_images
    from src.db.connection import async_session_factory

    slug = derive_slug(pdf_path.name)
    code = derive_code(slug)  # may collide; resolved from books.yaml after Stage 1
    _setup_file_log(slug)

    logger.info("[%s] Waiting for file to stabilise...", slug)
    await asyncio.to_thread(_wait_for_stable_file, pdf_path)
    logger.info("[%s] File stable, starting pipeline.", slug)

    logger.info("[%s] Pipeline started", slug)

    try:
        # Stage 1 — Calibrate + register in books.yaml
        logger.info("[%s] Stage 1/7: Calibrating fonts...", slug)
        entry = calibrate_book(pdf_path, slug, subject)
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
        logger.info("[%s] Stage 1/7: Done", slug)

        # Stage 2 — Mathpix whole-PDF extraction (sync → thread so we don't block)
        logger.info("[%s] Stage 2/7: Mathpix PDF extraction (30–60 min)...", slug)
        await asyncio.to_thread(run_whole_pdf_pipeline, code)
        logger.info("[%s] Stage 2/7: Done", slug)

        # Stage 3 — Structure analysis (TOC parsing, boundary candidates, frequencies)
        logger.info("[%s] Stage 3/7: Analyzing book structure...", slug)
        mmd_path = OUTPUT_DIR / slug / "book.mmd"
        mmd_text = mmd_path.read_text(encoding="utf-8")
        from src.extraction.ocr_validator import validate_and_analyze
        quality_report = validate_and_analyze(mmd_text, slug)
        logger.info(
            "[%s] Stage 3/7: Done. quality=%.3f toc_entries=%d signal_types=%d",
            slug, quality_report.quality_score, len(quality_report.toc_entries), len(quality_report.signal_stats),
        )

        # Stage 4 — Book Profiler (LLM, one-time, cached — ~$0.003 first run, $0 thereafter)
        logger.info("[%s] Stage 4/7: Profiling book structure (LLM)...", slug)
        from src.extraction.book_profiler import load_or_create_profile
        profile = await load_or_create_profile(mmd_text, slug, quality_report)
        logger.info(
            "[%s] Stage 4/7: Done. subject=%s boundary_signals=%d exercise_markers=%d noise_patterns=%d",
            slug, profile.subject,
            sum(1 for s in profile.subsection_signals if s.is_boundary),
            len(profile.exercise_markers),
            len(profile.noise_patterns),
        )

        # Stage 5 — Chunk pipeline (parse with profile + embed + persist + image validation)
        logger.info("[%s] Stage 5/7: Building chunks & embeddings...", slug)
        async with async_session_factory() as db:
            await build_chunks(slug, mmd_path, db, rebuild=False, profile=profile)
            removed = await validate_and_clean_images(slug, db)
        logger.info("[%s] Stage 5/7: Done. Removed %d orphan image rows.", slug, removed)

        # Stage 6 — Dependency graph
        logger.info("[%s] Stage 6/7: Building dependency graph...", slug)
        graph_path = OUTPUT_DIR / slug / "graph.json"
        from src.extraction.graph_builder import build_graph
        async with async_session_factory() as db:
            await build_graph(db, slug, graph_path)
        logger.info("[%s] Stage 6/7: Done", slug)

        # Stage 7 — Hot-load into running server
        logger.info("[%s] Stage 7/7: Hot-loading into server...", slug)
        api_base = os.getenv("API_BASE_URL", "http://localhost:8889")
        api_key = os.getenv("API_SECRET_KEY", "")
        try:
            resp = requests.post(
                f"{api_base}/api/admin/load-book/{slug}",
                headers={"X-API-Key": api_key},
                timeout=30,
            )
            resp.raise_for_status()
            logger.info("[%s] Stage 7/7: Hot-load successful", slug)
        except Exception as exc:
            logger.error("[%s] Stage 7/7: Hot-load failed: %s", slug, exc)

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
    args = parser.parse_args()
    asyncio.run(run_pipeline(args.pdf, args.subject))


if __name__ == "__main__":
    main()
