"""
Mathpix Client — handles API communication with Mathpix for OCR.

Two modes:
  1. process_image_with_mathpix() — single formula image → LaTeX
  2. ocr_page_image() — full page image → Markdown with LaTeX math

Whole-PDF mode (new):
  3. submit_pdf() — submit entire PDF to Mathpix /v3/pdf (requests mmd.zip)
  4. wait_for_pdf_completion() — poll until done (with timeout)
  5. download_pdf_mmd_zip() — download mmd.zip, extract images + MMD text
"""

import base64
import json
import logging
import time
import zipfile
import requests
from pathlib import Path
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import MATHPIX_APP_ID, MATHPIX_APP_KEY, MATHPIX_RATE_LIMIT

logger = logging.getLogger(__name__)

MATHPIX_API_URL = "https://api.mathpix.com/v3/text"
MATHPIX_PDF_URL = "https://api.mathpix.com/v3/pdf"

# Track last request time for rate limiting
_last_request_time = 0.0


def _rate_limit():
    """Enforce rate limiting between Mathpix API calls."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MATHPIX_RATE_LIMIT:
        time.sleep(MATHPIX_RATE_LIMIT - elapsed)
    _last_request_time = time.time()


def ocr_page_image(image_bytes: bytes, retries: int = 1) -> Optional[str]:
    """
    Send a full page image to Mathpix and return Markdown text with
    inline math as $...$ and display math as $$...$$.

    Returns None on failure after retries.
    """
    if not MATHPIX_APP_ID or not MATHPIX_APP_KEY:
        print("Warning: Mathpix credentials not configured. Skipping OCR.")
        return None

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    headers = {
        "app_id": MATHPIX_APP_ID,
        "app_key": MATHPIX_APP_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "src": f"data:image/jpeg;base64,{b64_image}",
        "formats": ["text"],
        "math_inline_delimiters": ["$", "$"],
        "math_display_delimiters": ["$$", "$$"],
        "rm_spaces": True,
    }

    for attempt in range(1 + retries):
        try:
            _rate_limit()
            response = requests.post(
                MATHPIX_API_URL, json=payload, headers=headers, timeout=60
            )
            response.raise_for_status()
            result = response.json()

            # Check for error in response
            if "error" in result:
                print(f"  Mathpix error: {result['error']}")
                if attempt < retries:
                    time.sleep(2)
                    continue
                return None

            return result.get("text", "")

        except requests.RequestException as e:
            if attempt < retries:
                print(f"  Mathpix request failed (attempt {attempt+1}): {e}")
                time.sleep(2)
                continue
            print(f"  Mathpix API error after {1+retries} attempts: {e}")
            return None

    return None


def process_image_with_mathpix(image_bytes: bytes) -> Optional[str]:
    """
    Send an image to Mathpix API and return the LaTeX string.
    Returns None on failure.
    """
    if not MATHPIX_APP_ID or not MATHPIX_APP_KEY:
        print("Warning: Mathpix credentials not configured. Skipping.")
        return None

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    headers = {
        "app_id": MATHPIX_APP_ID,
        "app_key": MATHPIX_APP_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "src": f"data:image/png;base64,{b64_image}",
        "formats": ["latex_simplified"],
        "data_options": {
            "include_asciimath": True,
        },
    }

    try:
        _rate_limit()
        response = requests.post(MATHPIX_API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result.get("latex_simplified", result.get("text", ""))
    except requests.RequestException as e:
        print(f"Mathpix API error: {e}")
        return None


def check_mathpix_credentials() -> bool:
    """Verify that Mathpix credentials are configured."""
    return bool(MATHPIX_APP_ID and MATHPIX_APP_KEY)


# ── Whole-PDF extraction (Mathpix /v3/pdf) ────────────────────────────────────

def submit_pdf(pdf_path: Path) -> str:
    """
    Submit entire PDF to Mathpix /v3/pdf endpoint.
    Returns pdf_id to use for polling and download.
    Uses httpx for large-file uploads (avoids WinError 10053 SSL abort on Windows).
    """
    import httpx

    if not MATHPIX_APP_ID or not MATHPIX_APP_KEY:
        raise RuntimeError("Mathpix credentials not configured (MATHPIX_APP_ID / MATHPIX_APP_KEY).")

    headers = {"app_id": MATHPIX_APP_ID, "app_key": MATHPIX_APP_KEY}
    options = {
        "conversion_formats": {"mmd.zip": True},
        "math_inline_delimiters": ["$", "$"],
        "math_display_delimiters": ["$$", "$$"],
        "rm_spaces": True,
        "enable_spell_check": False,
    }

    logger.info("Submitting PDF to Mathpix /v3/pdf: %s", pdf_path)
    with open(pdf_path, "rb") as f:
        with httpx.Client(timeout=600) as client:
            response = client.post(
                MATHPIX_PDF_URL,
                headers=headers,
                files={"file": (pdf_path.name, f, "application/pdf")},
                data={"options_json": json.dumps(options)},
            )
    response.raise_for_status()
    data = response.json()
    if "pdf_id" not in data:
        raise RuntimeError(
            f"Mathpix /v3/pdf did not return a pdf_id. Response: {data}"
        )
    pdf_id = data["pdf_id"]
    logger.info("Mathpix accepted PDF — pdf_id=%s", pdf_id)
    return pdf_id


def wait_for_pdf_completion(
    pdf_id: str,
    poll_interval: float = 10.0,
    max_wait_seconds: int = 3600,
) -> None:
    """
    Poll Mathpix until PDF processing is complete.
    R2: Raises TimeoutError after max_wait_seconds (default 60 min).
    Raises RuntimeError if Mathpix reports an error status.
    """
    headers = {"app_id": MATHPIX_APP_ID, "app_key": MATHPIX_APP_KEY}
    elapsed = 0.0
    while elapsed < max_wait_seconds:
        r = requests.get(
            f"{MATHPIX_PDF_URL}/{pdf_id}",
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        status = data.get("status", "")
        percent = data.get("percent_done", 0)
        logger.info(
            "Mathpix pdf_id=%s status=%s percent=%s%% (%.0fs elapsed)",
            pdf_id, status, percent, elapsed,
        )
        if status == "completed":
            return
        if status == "error":
            raise RuntimeError(f"Mathpix PDF processing failed for pdf_id={pdf_id}: {data}")
        time.sleep(poll_interval)
        elapsed += poll_interval
    raise TimeoutError(
        f"Mathpix PDF processing timed out after {max_wait_seconds}s for pdf_id={pdf_id}"
    )


def download_pdf_mmd_zip(pdf_id: str, images_dir: Path) -> str:
    """
    Download the mmd.zip from Mathpix for a completed PDF job.
    Extracts the .mmd text and saves bundled images to images_dir.
    Returns the MMD text content.
    """
    import io
    headers = {"app_id": MATHPIX_APP_ID, "app_key": MATHPIX_APP_KEY}
    images_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading Mathpix mmd.zip for pdf_id=%s", pdf_id)
    r = requests.get(
        f"{MATHPIX_PDF_URL}/{pdf_id}.mmd.zip",
        headers=headers,
        stream=True,
        timeout=300,
    )
    r.raise_for_status()
    zip_bytes = b"".join(r.iter_content(chunk_size=8192))

    mmd_text = None
    image_count = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            data = zf.read(name)
            basename = Path(name).name
            if not basename:
                continue  # skip directory entries
            if basename.lower().endswith(".mmd") or (basename.lower().endswith(".md") and mmd_text is None):
                mmd_text = data.decode("utf-8")
            else:
                img_path = images_dir / basename
                img_path.write_bytes(data)
                image_count += 1

    if mmd_text is None:
        raise ValueError(f"No .mmd file found in mmd.zip for pdf_id={pdf_id}")

    logger.info(
        "mmd.zip extracted: %d chars MMD, %d images → %s",
        len(mmd_text), image_count, images_dir,
    )
    return mmd_text
