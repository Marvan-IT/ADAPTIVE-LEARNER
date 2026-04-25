"""One-shot: translate newly-added i18n keys in frontend/src/locales/*.json.

Reads `en.json` as the source of truth, translates `tutorStyles.*`, `interests.*`,
`adminContent.*`, `adminReview.*` keys into the 12 non-English locales via OpenAI,
writes back. Preserves existing keys in each locale file (never overwrites).

Idempotent: a key whose non-English value already differs from the English
value is treated as already translated and skipped. Missing keys are filled in.

Usage (from repo root, venv active, OPENAI_API_KEY set in backend/.env):
    python frontend/scripts/translate_locales.py             # whitelisted prefixes only
    python frontend/scripts/translate_locales.py --full-sync # every key in en.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from config import OPENAI_API_KEY  # noqa: E402  (loads from backend/.env)
from openai import OpenAI  # noqa: E402

LOCALES_DIR = REPO_ROOT / "frontend" / "src" / "locales"
TARGETS = ["ar", "de", "es", "fr", "hi", "ja", "ko", "ml", "pt", "si", "ta", "zh"]
LANG_NAMES = {
    "ar": "Arabic", "de": "German", "es": "Spanish", "fr": "French",
    "hi": "Hindi", "ja": "Japanese", "ko": "Korean", "ml": "Malayalam",
    "pt": "Portuguese", "si": "Sinhala", "ta": "Tamil", "zh": "Chinese (Simplified)",
}
KEY_PREFIXES = ("tutorStyles.", "interests.", "adminContent.", "adminReview.")
BATCH_SIZE = 40
MODEL = "gpt-4o-mini"


def flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def unflatten(flat: dict) -> dict:
    """Unflatten dotted keys into nested objects. If a key conflict arises
    (both a flat dotted key and a nested object exist for the same path),
    keep the dotted key as-is to avoid a TypeError."""
    out: dict = {}
    for k, v in flat.items():
        parts = k.split(".")
        cur = out
        ok = True
        for p in parts[:-1]:
            existing = cur.get(p)
            if existing is None:
                cur[p] = {}
                cur = cur[p]
            elif isinstance(existing, dict):
                cur = existing
            else:
                # Conflict: a leaf already lives at this path. Keep the dotted
                # form rather than overwriting.
                ok = False
                break
        if ok:
            existing_leaf = cur.get(parts[-1])
            if isinstance(existing_leaf, dict):
                # Conflict: nested object lives at this path. Keep as-is.
                out[k] = v
            else:
                cur[parts[-1]] = v
        else:
            out[k] = v
    return out


def _is_flat_format(d: dict) -> bool:
    """Return True if this locale file uses dotted top-level keys (no nesting)."""
    return all(not isinstance(v, dict) for v in d.values())


def translate_batch(client: OpenAI, items: list[tuple[str, str]], lang_code: str) -> dict[str, str]:
    """Translate {key: english} → {key: translated}. Preserves interpolation markers like {{name}}."""
    lang_name = LANG_NAMES[lang_code]
    keys_payload = {k: v for k, v in items}
    system = (
        f"You translate UI strings for a math learning app from English to {lang_name}. "
        "Rules: preserve any {{variable}} or {variable} interpolation markers EXACTLY. "
        "Keep proper nouns like 'Adaptive Learner' untranslated. "
        "For single-word tutor style names (Default, Pirate, Space, Gamer) and interest names "
        "(Sports, Gaming, Music, ...), produce a natural, short, culturally-appropriate word. "
        "Return ONLY valid JSON mapping each input key to the translated string, no commentary."
    )
    user = json.dumps({"strings": keys_payload}, ensure_ascii=False)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    content = resp.choices[0].message.content or "{}"
    parsed = json.loads(content)
    # Accept either {"strings": {...}} or flat {...}
    if "strings" in parsed and isinstance(parsed["strings"], dict):
        return parsed["strings"]
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full-sync",
        action="store_true",
        help="Translate every key in en.json (not just whitelisted prefixes).",
    )
    args = parser.parse_args()

    assert OPENAI_API_KEY, "OPENAI_API_KEY missing — cannot translate"
    client = OpenAI(api_key=OPENAI_API_KEY)

    en_flat = flatten(json.loads((LOCALES_DIR / "en.json").read_text()))
    if args.full_sync:
        target_keys = sorted(en_flat.keys())
        print(f"[FULL SYNC] all {len(target_keys)} keys eligible")
    else:
        target_keys = sorted(k for k in en_flat if k.startswith(KEY_PREFIXES))
        print(f"Source keys to translate (prefixes): {len(target_keys)}")

    for lang in TARGETS:
        path = LOCALES_DIR / f"{lang}.json"
        raw = json.loads(path.read_text())
        flat_format = _is_flat_format(raw)
        existing_flat = flatten(raw)

        pending: list[tuple[str, str]] = []
        for k in target_keys:
            en_val = en_flat[k]
            existing = existing_flat.get(k)
            # Skip keys already translated (value differs from English placeholder).
            if existing is not None and existing != en_val:
                continue
            pending.append((k, en_val))

        if not pending:
            print(f"[{lang}] all {len(target_keys)} keys already translated — skip")
            continue

        print(f"[{lang}] translating {len(pending)} keys in batches of {BATCH_SIZE}")
        translated: dict[str, str] = {}
        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i : i + BATCH_SIZE]
            result = translate_batch(client, batch, lang)
            for k, _ in batch:
                if k in result and isinstance(result[k], str):
                    translated[k] = result[k]
            print(f"  batch {i // BATCH_SIZE + 1}: {len(result)} returned")

        # Merge translated values into existing flat map
        merged = dict(existing_flat)
        merged.update(translated)
        # Preserve the file's original structure: flat (dotted top-level keys)
        # for files like en.json, nested objects for the others.
        if flat_format:
            output = {k: merged[k] for k in sorted(merged.keys())}
        else:
            output = unflatten(merged)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
        print(f"[{lang}] wrote {len(translated)} translated keys → {path.name}")


if __name__ == "__main__":
    main()
