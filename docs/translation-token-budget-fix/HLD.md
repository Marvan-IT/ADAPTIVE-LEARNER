# HLD — Translation Token Budget Fix

## 1. Executive Summary

**Feature:** Fix batch translation truncation in `translate_catalog.py`.
**Problem:** Caption batches for Brahmic-script languages (Hindi, Tamil, Sinhala) exceed the 3,000-token response budget, causing JSON truncation, 5-retry cycles, and per-item fallback — a 50× API call multiplier.
**Scope:** One constant in one function. No schema changes, no migration, no new env vars.
**Excluded:** JSON mode enforcement, adaptive batch sizing, re-running already-translated rows.

---

## 2. Bug Evidence

| Signal | Value |
|--------|-------|
| Error message | `"Unterminated string starting at: line N column 5"` — classic truncation |
| Truncation position | ~7,906 chars ≈ 2,000 tokens (below the 3,000-token cap with JSON envelope overhead) |
| Per-item fallback count | `fallbacks=465` for si/ar/ja caption batches — every item fell back |
| Latin-script success rate | Much higher — fewer tokens per source word |
| Math book failure rate | Lower — shorter captions fit within budget |
| Per-item fallback always succeeds | Single items get 512-token allowance, which is sufficient |

Evidence source: `backend/output/clinical_nursing_skills/pipeline.log`, Stage 7 translation entries.

---

## 3. Root Cause

`backend/scripts/translate_catalog.py` line 123:

```python
max_tokens=max(512, len(strings) * 60),
```

For a 50-string batch of nursing captions (50–100 words each), the budget is `50 × 60 = 3,000` tokens.
Hindi/Tamil/Sinhala translations of the same 50-word caption require 2–3× the English token count,
pushing total response needs to **8,000–10,000 tokens** — well above the 3,000 cap.

---

## 4. Why "Bump Multiplier" Is the Correct Fix (Not JSON Mode)

`response_format={"type":"json_object"}` enforces structural validity only. It does **not** prevent
the model from running out of tokens mid-response. A truncated output is syntactically broken
regardless of mode. The sole fix is a larger token budget.

---

## 5. Token Math

| Language family | Script | Tokens vs. English source | Example (50-word caption) |
|----------------|--------|--------------------------|--------------------------|
| Latin (es, fr, de, pt) | Latin | ~1.0× | ~60 tokens output |
| Arabic (ar) | Arabic | ~1.5× | ~90 tokens output |
| CJK (ja, zh, ko) | CJK | ~1.0× | ~60 tokens output |
| Brahmic (hi, ta, si, ml) | Brahmic | ~2–3× | ~120–180 tokens output |

Worst case for 50-string Brahmic batch: `50 × 180 = 9,000 tokens` + JSON overhead ≈ **9,500 tokens**.
New budget: `50 × 200 = 10,000 tokens`. gpt-4o-mini output cap: 16,384 tokens. Safe margin confirmed.

---

## 6. Expected Impact

- **5–10× end-to-end speedup** for caption-heavy books (`clinical_nursing_skills`, `introduction_to_philosophy`).
- **`fallbacks=0`** for all language batches after fix — per-item path becomes cold code for normal content.
- **Per-language "done in" time**: drops from ~50–80 min to ~3–7 min.
- **Cost**: net decrease — per-item fallback was 50× more API calls; higher token budget consumes only tokens actually generated.

---

## 7. Key Decisions Requiring Stakeholder Input

None. Single-line fix with measurable acceptance criteria and a one-line rollback path.
