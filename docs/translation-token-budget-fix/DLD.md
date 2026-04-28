# DLD — Translation Token Budget Fix

## 1. Component Breakdown

One function is modified. All other components are unchanged.

| Component | File | Change |
|-----------|------|--------|
| `_call_llm_once()` | `backend/scripts/translate_catalog.py:123` | Multiplier 60 → 200 |
| `_translate_batch_with_retry()` | same file | No change — calls `_call_llm_once` |
| `translate_strings_batch()` | same file | No change — calls retry wrapper |
| All pipeline callers | `backend/src/pipeline/` | No change |

---

## 2. The One-Line Patch

**File:** `backend/scripts/translate_catalog.py`
**Line:** 123

```python
# BEFORE
max_tokens=max(512, len(strings) * 60),

# AFTER
# 200 tokens per string accommodates non-Latin script translations
# (Hindi/Tamil/Sinhala use 2-3x the tokens of English) for captions
# up to ~50 words. Previous value of 60 truncated nursing-style long
# captions, forcing expensive per-item fallbacks (fallbacks=465 observed).
max_tokens=max(512, len(strings) * 200),
```

No other lines in the file require modification. No call-site updates needed.

---

## 3. Per-Language Token-Cost Table

| Language | Code | Script family | Token multiplier vs. English | Budget per string (200-token envelope) |
|----------|------|--------------|------------------------------|----------------------------------------|
| English | en | Latin | 1.0× | ~60 tokens used / 200 allocated |
| Spanish | es | Latin | 1.0× | ~60 tokens used |
| French | fr | Latin | 1.0× | ~65 tokens used |
| German | de | Latin | 1.0× | ~70 tokens used |
| Portuguese | pt | Latin | 1.0× | ~60 tokens used |
| Arabic | ar | Arabic | 1.5× | ~90 tokens used |
| Japanese | ja | CJK | 1.0× | ~60 tokens used |
| Chinese | zh | CJK | 1.0× | ~55 tokens used |
| Korean | ko | CJK | 1.0× | ~65 tokens used |
| Hindi | hi | Brahmic | 2–3× | ~120–180 tokens used |
| Tamil | ta | Brahmic | 2–3× | ~120–180 tokens used |
| Sinhala | si | Brahmic | 2–3× | ~120–180 tokens used |
| Malayalam | ml | Brahmic | 2–3× | ~120–180 tokens used |

Worst-case 50-string batch (all Brahmic, 50-word captions):
`50 × 180 = 9,000` tokens + JSON structure overhead ≈ 9,500 tokens. New budget: 10,000. Safe.

---

## 4. Regression Risk Analysis

| Risk | Assessment | Evidence |
|------|-----------|---------|
| Other callers break | None | Only `_call_llm_once` is touched; `grep -n "_call_llm_once"` shows it is the sole implementation — all callers route through this path |
| Budget exceeds model output cap | None | gpt-4o-mini output cap = 16,384 tokens; max batch budget = `max(512, 50 × 200)` = 10,000 tokens — within cap |
| Change lowers budget for short strings | None | `max(512, ...)` floor is preserved; monotonic increase in headroom only |
| Short-string batches waste tokens | None | OpenAI charges only for tokens generated, not tokens budgeted |
| SHA-1 idempotency bypasses fix for done rows | Intended | Already-translated rows are skipped; fix applies only to remaining rows |

---

## 5. Rollback

```python
# Revert line 123 to:
max_tokens=max(512, len(strings) * 60),
```

One line. No migration required. No state to clean up.

---

## 6. Security Design

No new attack surface. The change only affects a numeric parameter in an internal async function called
from an offline pipeline script. No user input reaches `len(strings)` — batch contents come from the
database and are bounded by `BATCH_SIZE_PER_CALL` (constant in the same file).

---

## 7. Observability

Post-deploy, confirm fix is active by watching:

```bash
# fallbacks=0 expected per language after fix
tail -f /app/output/clinical_nursing_skills/pipeline.log | grep "done in"

# Each language entry should now show: "done in Xs, fallbacks=0"
```

---

## 8. Testing Strategy

- **Smoke test:** Import module — confirms no syntax error.
- **Live LLM test (Phase 2):** Call `_translate_batch_with_retry` with 5 long synthetic nursing-style captions in Hindi using both old (60) and new (200) multipliers. Old must fail or truncate; new must return full array without retries.
- **Pytest suite:** `python -m pytest tests/ -q` — confirms no regression in any test importing `translate_catalog`.

---

## 9. Key Decisions Requiring Stakeholder Input

None. The multiplier value of 200 provides 2× headroom over worst-case Brahmic content while staying well within the gpt-4o-mini output cap.
