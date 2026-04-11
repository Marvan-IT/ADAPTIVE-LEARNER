"""
One-time bootstrap: trigger the pipeline for all PDFs in backend/data/
that are not yet registered in books.yaml.

Run once after deploying the watcher service:
    docker compose exec book-watcher python scripts/bootstrap_existing.py
"""
from __future__ import annotations
import logging
import subprocess
import sys
from pathlib import Path

import yaml

# Make src importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.config import DATA_DIR, BACKEND_DIR
from src.extraction.calibrate import derive_slug

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    yaml_path = BACKEND_DIR / "books.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {"books": []}
    registered = {b["book_slug"] for b in data.get("books", [])}

    triggered = 0
    skipped = 0
    for pdf in sorted(DATA_DIR.rglob("*.pdf")):
        slug = derive_slug(pdf.name)
        if slug in registered:
            logger.info("SKIP  %s (already registered as '%s')", pdf.name, slug)
            skipped += 1
            continue
        subject = pdf.parent.name.lower()
        if subject == "maths":
            subject = "mathematics"
        logger.info("QUEUE %s -> slug='%s', subject='%s'", pdf.name, slug, subject)
        subprocess.Popen([
            sys.executable, "-m", "src.watcher.pipeline_runner",
            "--pdf", str(pdf),
            "--subject", subject,
        ])
        triggered += 1

    logger.info("Bootstrap done: %d triggered, %d skipped", triggered, skipped)


if __name__ == "__main__":
    main()
