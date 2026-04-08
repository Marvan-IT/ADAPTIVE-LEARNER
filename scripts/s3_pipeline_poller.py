#!/usr/bin/env python3
"""
ADA S3 Pipeline Poller
======================
Polls an SQS queue for S3 ObjectCreated events. For each message:
  1. Downloads the PDF from S3 to ./backend/data/
  2. Runs the extraction pipeline inside the running backend container
  3. Calls the hot-reload endpoint to activate the new book
  4. Deletes the SQS message on success

Required environment variables (set via /home/ubuntu/ADA/scripts/.pipeline.env):
  ADA_SQS_QUEUE_URL    Full SQS queue URL
  ADA_S3_BUCKET        S3 bucket name
  ADA_API_SECRET_KEY   Must match backend API_SECRET_KEY
  ADA_PROJECT_PATH     Path to ADA project on EC2 (default: /home/ubuntu/ADA)
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import boto3
import requests

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ada-poller")

# ---------------------------------------------------------------------------
# Book code → book slug mapping
# Mirrors the mapping used in frontend/src/api/sessions.js
# ---------------------------------------------------------------------------
BOOK_CODE_TO_SLUG = {
    "PREALG": "prealgebra",
    "ELEMALG": "elementary_algebra",
    "INTERALG": "intermediate_algebra",
    "COLALG": "college_algebra",
    "COLALGCRQ": "college_algebra_coreq",
    "ALGTRIG": "algebra_trigonometry",
    "PRECALC": "precalculus",
    "CALC1": "calculus_1",
    "CALC2": "calculus_2",
    "CALC3": "calculus_3",
    "INSTATS": "intro_statistics",
    "STATS": "statistics",
    "BUSTATS": "business_statistics",
    "CONTMATH": "contemporary_math",
    "PDS": "principles_data_science",
    # ALG1/ prefix supported directly
    "ALG1": "algebra_1",
}

# ---------------------------------------------------------------------------
# Config (read from environment — validated at startup)
# ---------------------------------------------------------------------------
POLL_INTERVAL_SECONDS = 60
BACKEND_PORT = 8889


def _require_env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        log.error("Required environment variable %s is not set. Exiting.", name)
        sys.exit(1)
    return value


def load_config() -> dict:
    return {
        "sqs_queue_url": _require_env("ADA_SQS_QUEUE_URL"),
        "s3_bucket": _require_env("ADA_S3_BUCKET"),
        "api_secret_key": _require_env("ADA_API_SECRET_KEY"),
        "project_path": _require_env("ADA_PROJECT_PATH", "/home/ubuntu/ADA"),
    }


# ---------------------------------------------------------------------------
# S3 key parsing
# ---------------------------------------------------------------------------
def parse_s3_key(s3_key: str) -> tuple[str, str] | None:
    """
    Parse an S3 key of the form {BOOK_CODE}/{filename}.pdf.

    Returns (book_code, book_slug) or None if the key cannot be mapped.

    Example:
        "ALG1/Algebra1.pdf"  ->  ("ALG1", "algebra_1")
        "PREALG/prealgebra.pdf"  ->  ("PREALG", "prealgebra")
    """
    parts = s3_key.strip("/").split("/")
    if len(parts) < 2:
        log.warning("S3 key '%s' has no folder prefix — skipping.", s3_key)
        return None

    book_code = parts[0].upper()
    book_slug = BOOK_CODE_TO_SLUG.get(book_code)
    if not book_slug:
        log.warning(
            "Unknown book code '%s' (from key '%s') — no slug mapping. Skipping.",
            book_code,
            s3_key,
        )
        return None

    return book_code, book_slug


# ---------------------------------------------------------------------------
# S3 download
# ---------------------------------------------------------------------------
def download_pdf(s3_client, s3_bucket: str, s3_key: str, project_path: str) -> Path:
    """Download the PDF from S3 into backend/data/{book_code}/."""
    filename = Path(s3_key).name
    book_code = s3_key.split("/")[0]
    dest_dir = Path(project_path) / "backend" / "data" / book_code
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    log.info("Downloading s3://%s/%s -> %s", s3_bucket, s3_key, dest_path)
    s3_client.download_file(s3_bucket, s3_key, str(dest_path))
    log.info("Download complete: %s (%.1f MB)", dest_path, dest_path.stat().st_size / 1_048_576)
    return dest_path


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------
def run_docker_compose_exec(project_path: str, command: list[str]) -> None:
    """
    Run `docker compose exec -T backend {command}` in the project directory.
    Raises subprocess.CalledProcessError on non-zero exit.
    """
    full_cmd = ["docker", "compose", "exec", "-T", "backend"] + command
    log.info("Running: %s", " ".join(full_cmd))
    result = subprocess.run(
        full_cmd,
        cwd=project_path,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            log.info("[container] %s", line)
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            log.warning("[container stderr] %s", line)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, full_cmd)


def run_pipeline(project_path: str, book_code: str, book_slug: str) -> None:
    """Run both pipeline stages inside the backend container."""
    log.info("--- Stage 1: extraction pipeline (--book %s) ---", book_code)
    run_docker_compose_exec(
        project_path,
        ["python", "-m", "src.pipeline", "--book", book_code],
    )
    log.info("--- Stage 2: chunk pipeline (--chunks --book %s) ---", book_slug)
    run_docker_compose_exec(
        project_path,
        ["python", "-m", "src.pipeline", "--chunks", "--book", book_slug],
    )


# ---------------------------------------------------------------------------
# Hot-reload webhook
# ---------------------------------------------------------------------------
def call_hot_reload(book_slug: str, api_secret_key: str) -> None:
    """POST to the admin load-book endpoint to activate the new book at runtime."""
    url = f"http://localhost:{BACKEND_PORT}/api/admin/load-book/{book_slug}"
    log.info("Calling hot-reload endpoint: POST %s", url)
    resp = requests.post(
        url,
        headers={"X-API-Key": api_secret_key},
        timeout=30,
    )
    if resp.ok:
        log.info("Hot-reload succeeded: %s %s", resp.status_code, resp.text[:200])
    else:
        # Non-fatal — the container already has the data; next restart will pick it up.
        log.warning(
            "Hot-reload returned non-2xx status %s: %s",
            resp.status_code,
            resp.text[:200],
        )


# ---------------------------------------------------------------------------
# SQS message processing
# ---------------------------------------------------------------------------
def extract_s3_event(message_body: str) -> list[dict]:
    """
    Parse the SQS message body and return a list of S3 event records.

    S3 → SQS notifications wrap the S3 event JSON in the SQS body directly.
    Some setups also wrap it in an SNS envelope — handled transparently.
    """
    body = json.loads(message_body)

    # SNS envelope: body has a "Message" key containing the real JSON string
    if "Message" in body and isinstance(body["Message"], str):
        body = json.loads(body["Message"])

    return body.get("Records", [])


def process_message(
    message: dict,
    sqs_client,
    s3_client,
    config: dict,
) -> bool:
    """
    Process a single SQS message. Returns True if the message should be deleted.
    """
    receipt_handle = message["ReceiptHandle"]
    body = message.get("Body", "")

    try:
        records = extract_s3_event(body)
    except (json.JSONDecodeError, KeyError) as exc:
        log.error("Failed to parse SQS message body: %s — body: %.300s", exc, body)
        # Delete the unparseable message to avoid poison-pill loop
        return True

    if not records:
        log.info("SQS message contained no S3 Records — skipping (will delete).")
        return True

    all_ok = True
    for record in records:
        event_name = record.get("eventName", "")
        if not event_name.startswith("ObjectCreated"):
            log.info("Ignoring non-create event '%s'.", event_name)
            continue

        s3_key = record.get("s3", {}).get("object", {}).get("key", "")
        if not s3_key.lower().endswith(".pdf"):
            log.info("Ignoring non-PDF object '%s'.", s3_key)
            continue

        parsed = parse_s3_key(s3_key)
        if parsed is None:
            all_ok = False
            continue

        book_code, book_slug = parsed
        log.info(
            "Processing book: code=%s slug=%s key=%s",
            book_code,
            book_slug,
            s3_key,
        )

        try:
            download_pdf(s3_client, config["s3_bucket"], s3_key, config["project_path"])
            run_pipeline(config["project_path"], book_code, book_slug)
            call_hot_reload(book_slug, config["api_secret_key"])
            log.info("Successfully processed book '%s'.", book_slug)
        except subprocess.CalledProcessError as exc:
            log.error("Pipeline command failed (exit %s) for book '%s'.", exc.returncode, book_slug)
            all_ok = False
        except Exception as exc:
            log.exception("Unexpected error processing book '%s': %s", book_slug, exc)
            all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------
def poll_forever(config: dict) -> None:
    sqs = boto3.client("sqs")
    s3 = boto3.client("s3")

    queue_url = config["sqs_queue_url"]
    log.info("Starting ADA S3 pipeline poller.")
    log.info("  SQS queue : %s", queue_url)
    log.info("  S3 bucket : %s", config["s3_bucket"])
    log.info("  Project   : %s", config["project_path"])
    log.info("  Poll interval: %ds", POLL_INTERVAL_SECONDS)

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20,  # long polling — reduces empty responses
                VisibilityTimeout=600,  # 10 min: allow for slow pipeline runs
            )
        except Exception as exc:
            log.error("SQS receive_message failed: %s — retrying in %ds.", exc, POLL_INTERVAL_SECONDS)
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        messages = response.get("Messages", [])
        if not messages:
            log.debug("No messages in queue. Sleeping %ds.", POLL_INTERVAL_SECONDS)
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        log.info("Received %d message(s) from SQS.", len(messages))
        for msg in messages:
            success = process_message(msg, sqs, s3, config)
            if success:
                try:
                    sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=msg["ReceiptHandle"],
                    )
                    log.info("Deleted SQS message (ReceiptHandle: ...%s).", msg["ReceiptHandle"][-8:])
                except Exception as exc:
                    log.error("Failed to delete SQS message: %s", exc)
            else:
                log.warning(
                    "Message processing had errors — leaving in queue for retry "
                    "(will become visible again after VisibilityTimeout)."
                )


def main() -> None:
    config = load_config()
    poll_forever(config)


if __name__ == "__main__":
    main()
