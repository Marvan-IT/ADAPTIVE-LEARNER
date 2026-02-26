"""
Mathpix Client — handles API communication with Mathpix for OCR.

Two modes:
  1. process_image_with_mathpix() — single formula image → LaTeX
  2. ocr_page_image() — full page image → Markdown with LaTeX math
"""

import base64
import time
import requests
from pathlib import Path
from typing import Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import MATHPIX_APP_ID, MATHPIX_APP_KEY, MATHPIX_RATE_LIMIT


MATHPIX_API_URL = "https://api.mathpix.com/v3/text"

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
