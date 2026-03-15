# ADA Platform — Senior Codebase Audit Report
**Date:** 2026-03-15
**Scope:** Full backend + frontend dead code, schema mismatches, silent catches, unused constants
**Files Analyzed:** 47 Python modules, 52 frontend JSX/JS files, 2 Pydantic schema files

---

## 1. Dead Code — `teaching_service.py`

5 functions are defined but have **no call sites anywhere in the codebase**:

| Line | Function | Description | Action |
|------|----------|-------------|--------|
| 1555 | `_find_missing_sections()` | Checks which sections are missing from cards | Remove |
| 1929 | `_split_into_n_chunks()` | Splits text into n equal chunks (old fallback) | Remove — superseded by `_parse_sub_sections()` |
| 1946 | `_group_sub_sections()` | Groups sub-sections with max-char/max-card limits | Remove — superseded by `_group_by_major_topic()` |
| 2116 | `_extract_inline_image_filenames()` | Extracts image filenames from content | Remove |
| 2216 | `_get_checking_messages()` | Retrieves checking-phase messages | Remove — replaced by `_get_phase_messages()` (line 2227) |

**All other 35 functions in `teaching_service.py` are actively called.**

---

## 2. Schema Mismatches

### P1 — `passed` field (SessionContext.jsx vs SocraticResponse) — **SILENT BUG**

**Backend** (`backend/src/api/teaching_schemas.py:96–109`):
```python
class SocraticResponse(BaseModel):
    session_id: UUID
    response: str
    phase: str
    check_complete: bool
    score: int | None = None
    mastered: bool | None = None
    # ... other fields
    # NO `passed` field
```

**Frontend** (`frontend/src/context/SessionContext.jsx:269`):
```jsx
const { passed, mastered, remediation_needed, score, attempt, locked, best_score } = action.payload;
// line ~272:
if (passed || mastered) {  // `passed` is always undefined
```

**Risk:** `passed` is always `undefined`. The condition `(passed || mastered)` always falls back to `mastered` only. Silent logic bug — masked by the `||` fallback.

**Fix (P1-A):** Remove `passed` from the destructure and update the condition to `if (mastered)`.

---

### Safe — `image_indices` field (LessonCard)

`backend/src/api/teaching_schemas.py:161` defines `image_indices: list[int]`.
`frontend/src/components/learning/CardLearningView.jsx:731–732` uses it with optional chaining:
```jsx
{(!card.images || card.images.length === 0) && card.image_indices?.length > 0 && (
  <SessionImagesByIndex indices={card.image_indices} cards={cards} />
)}
```
**Status:** Safe — properly guarded. No action needed.

---

## 3. Silent Catches

### P1 — `image_extractor.py:42` — No logging (HIGH risk)

```python
try:
    img_info = doc.extract_image(xref)
    if not img_info:
        continue
except Exception:
    continue  # ← silently discards ALL errors
```

**Risk:** Any error (PDF corruption, memory, permissions) is swallowed invisibly. Debugging impossible.
**Fix (P1-B):** Add `logger.warning("Failed to extract image xref %d: %s", xref, e)`.

---

### Low — `extract_images.py:159` — `logger.debug` (acceptable)

```python
except Exception:
    logger.debug("Pillow validation failed for xref %d — skipping", xref)
    skipped += 1
    continue
```

**Status:** Acceptable — logged at DEBUG. Consider promoting to `logger.info` for production visibility, but not a blocking issue.

---

## 4. Unused Constants — `config.py`

5 constants are defined but **never referenced** anywhere:

| Constant | Value | Action |
|----------|-------|--------|
| `EMBEDDING_DIMENSIONS` | 1536 | Remove (ChromaDB infers this from the model) |
| `XP_CARD_ADVANCE` | 5 | Remove (comment says "informational for frontend" but frontend never uses it) |
| `ADAPTIVE_NUMERIC_STATE_STRUGGLING_MAX` | 1.5 | Remove (not used in scoring logic) |
| `ADAPTIVE_NUMERIC_STATE_FAST_MIN` | 2.5 | Remove (not used in scoring logic) |
| `BOOK_ORDER` | progression list | Remove (not used in pipeline or elsewhere) |

---

## 5. Frontend Dead Components

All 29 `.jsx` component files are imported from at least one other file. **No dead components found.**

Two components require spot-verification before confirming:
- `StyleSwitcher.jsx` — confirmed imported in `AppShell.jsx`
- `ConceptTooltip.jsx` — confirmed imported in `ConceptGraph.jsx`

**All 16 functions in `frontend/src/api/sessions.js` are actively called.**

---

## 6. Technical Debt (Pre-existing — Out of Scope for This Audit)

| Item | File | Priority |
|------|------|----------|
| `Base.metadata.create_all()` instead of Alembic | `db/connection.py:29` | Critical |
| `backend/src/models.py` duplicates `backend/src/db/models.py` | `backend/src/models.py` | Low |
| No Dockerfile / docker-compose / CI | — | Critical |

---

## 7. Prioritized Fix List

### P1 — Fix Now (logic correctness, diagnostics)
- **P1-A:** Remove `passed` field from `SessionContext.jsx:269` destructure; fix condition on ~line 272
- **P1-B:** Add `logger.warning(...)` to `image_extractor.py:42` silent catch
- **P1-C:** `image_indices` — no action needed (safe)

### P2 — Dead Code Removal
- Remove 5 dead functions from `teaching_service.py` (lines 1555, 1929, 1946, 2116, 2216)
- Remove 5 unused constants from `config.py`

### P3 — Low Priority
- Promote `extract_images.py:159` from `logger.debug` to `logger.info`
- Consolidate `backend/src/models.py` into `backend/src/db/models.py` (technical debt)

---

## 8. No Dead Code In

- `adaptive/adaptive_engine.py` — all functions active
- `adaptive/prompt_builder.py` — all functions active
- `api/knowledge_service.py` — all functions active
- `api/teaching_router.py` — all endpoints active
- `frontend/src/api/sessions.js` — all 16 exports called
- All 52 frontend JSX/JS files — no unused exports
