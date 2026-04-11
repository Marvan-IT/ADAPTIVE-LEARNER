"""
File watcher: monitors backend/data/ for new PDF files and triggers
the pipeline_runner subprocess automatically.

Run as: python -m src.watcher.book_watcher
"""
from __future__ import annotations
import logging
import queue
import subprocess
import sys
import threading
from pathlib import Path

import yaml as _yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.config import DATA_DIR, OUTPUT_DIR, BACKEND_DIR
from src.extraction.calibrate import derive_slug

logger = logging.getLogger(__name__)


_pdf_queue: queue.Queue = queue.Queue()


def _queue_worker() -> None:
    """Single worker — blocks until one pipeline finishes before starting the next."""
    while True:
        pdf_path, subject = _pdf_queue.get()
        try:
            logger.info("Processing: %s (subject=%s, remaining=%d)",
                        pdf_path.name, subject, _pdf_queue.qsize())
            proc = subprocess.run([
                sys.executable, "-m", "src.watcher.pipeline_runner",
                "--pdf", str(pdf_path),
                "--subject", subject,
            ])
            if proc.returncode != 0:
                logger.error("Pipeline failed for %s (exit %d)", pdf_path.name, proc.returncode)
        except Exception:
            logger.exception("Unexpected error processing %s", pdf_path.name)
        finally:
            _pdf_queue.task_done()


def _enqueue(pdf_path: Path, subject: str) -> None:
    logger.info("Queued: %s (subject=%s, queue_size=%d)",
                pdf_path.name, subject, _pdf_queue.qsize())
    _pdf_queue.put((pdf_path, subject))


def _subject_from_path(pdf: Path) -> str:
    """Derive normalised subject name from the PDF's parent folder."""
    subject = pdf.parent.name.lower()
    if subject == "maths":
        subject = "mathematics"
    return subject


class PDFHandler(FileSystemEventHandler):
    """Triggers the full pipeline when a new PDF is dropped into a subject folder."""

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".pdf":
            return
        subject = _subject_from_path(path)
        logger.info("New PDF detected: %s (subject=%s)", path.name, subject)
        _enqueue(path, subject)

    def on_moved(self, event) -> None:
        """Handle atomic renames (e.g. from scp)."""
        if event.is_directory:
            return
        path = Path(event.dest_path)
        if path.suffix.lower() != ".pdf":
            return
        subject = _subject_from_path(path)
        logger.info("PDF moved/renamed into place: %s (subject=%s)", path.name, subject)
        _enqueue(path, subject)


def _rescan_incomplete() -> None:
    """Re-enqueue any PDFs that are not yet registered or have no graph.json."""
    yaml_path = BACKEND_DIR / "books.yaml"
    registered: set[str] = set()
    if yaml_path.exists():
        try:
            registered = {b["book_slug"] for b in (_yaml.safe_load(yaml_path.read_text()) or {}).get("books", [])}
        except Exception:
            logger.warning("Could not read books.yaml for rescan check")
    for pdf in DATA_DIR.rglob("*.pdf"):
        slug = derive_slug(pdf.name)
        graph_ok = (OUTPUT_DIR / slug / "graph.json").exists()
        if slug not in registered or not graph_ok:
            subject = _subject_from_path(pdf)
            logger.info("Rescan: re-enqueuing incomplete PDF %s (slug=%s)", pdf.name, slug)
            _enqueue(pdf, subject)


def start_watcher() -> None:
    worker = threading.Thread(target=_queue_worker, daemon=True)
    worker.start()
    _rescan_incomplete()
    observer = Observer()
    observer.schedule(PDFHandler(), path=str(DATA_DIR), recursive=True)
    observer.start()
    logger.info("Book watcher started, monitoring: %s", DATA_DIR)
    try:
        observer.join()
    except KeyboardInterrupt:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    start_watcher()
