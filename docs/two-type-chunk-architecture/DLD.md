# Two-Type Chunk Architecture — Detailed Low-Level Design

## 1. Component Breakdown

| Component | File | Change Type |
|---|---|---|
| Pipeline classifier | `backend/src/extraction/chunk_parser.py` | Type-emission fix (5 sites) |
| API fallback classifier | `backend/src/api/teaching_router.py` | `_get_chunk_type` rewrite (L77–126) |
| Complete-chunk pass rule | `backend/src/api/teaching_router.py` | Three-branch → two-branch (L1298–1312) |
| Schema docstring | `backend/src/api/teaching_schemas.py` | Comment update (L390) |
| Admin validator | `backend/src/api/admin_router.py` | Defensive guard (L1874 area) |
| Tests | `backend/tests/test_chunk_parser_bugs.py`, `test_mastery_flow.py`, `test_admin_content_controls.py` | Assertion updates |

---

## 2. Exact Code Changes

### 2.1 `backend/src/extraction/chunk_parser.py`

Five emission sites. All changes collapse to two return values: `"teaching"` or `"exercise"`.

**Site 1 — Line 276** (`ChapterReview` group-tag branch):
```python
# BEFORE
return "chapter_review", True

# AFTER
if raw_heading.endswith(" (ChapterReview)"):
    return "exercise", True   # review = practice problems, optional
```

**Site 2 — Line 278** (`Lab` group-tag branch):
```python
# BEFORE
return "lab", is_opt

# AFTER
if raw_heading.endswith(" (Lab)"):
    return "teaching", is_opt
```

**Site 3 — Line 284** (`is_lab` branch):
```python
# BEFORE
if is_lab:
    return "lab", is_opt

# AFTER
if is_lab:
    return "teaching", is_opt
```

**Site 4 — Line 937** (chapter intro emission in `_emit_chapter_intro_chunks`):
```python
# BEFORE
chunk_type="chapter_intro",

# AFTER
chunk_type="teaching",
```
`is_optional=False` remains unchanged.

**Site 5 — Line 1075** (review-zone override):
```python
# BEFORE
_ctype = "chapter_review"

# AFTER
_ctype = "exercise"
```
`_opt = True` remains unchanged.

**Post-change invariant:** `grep -nE '"chapter_intro"|"chapter_review"|"lab"' backend/src/extraction/chunk_parser.py` returns zero chunk_type assignment hits (the strings may still appear in comments or the `_find_chapter_intros` helper — only assignment lines count).

---

### 2.2 `backend/src/api/teaching_router.py` — `_get_chunk_type` (L77–126)

**Current docstring (L87):**
```
Returns: 'learning_objective' | 'section_review' | 'teaching' | 'exercise'
```

**Target docstring:**
```
Returns: 'teaching' | 'exercise'
```

**Changes to function body:**

- **Line 96** — `section_review` branch: remove the assignment `chunk_type = "section_review"`. The branch condition (section-title heading pattern `^\d+\.\d+\s+`) should fall through to the reclassification guard at L122–125, which already upgrades content-rich headings to `teaching`. Bare short headings with no text also become `teaching` (the default fallback at L120).
- **Line 100** — `learning_objective` branch: remove the assignment `chunk_type = "learning_objective"`. Long LO blocks flow to `teaching` (default); the function no longer emits `learning_objective`.
- **Lines 103–116** — four exercise-detection branches: keep intact, all return `"exercise"`.
- **Line 120** — default fallback: keep `chunk_type = "teaching"`.
- **Lines 122–125** — `section_review` reclassification guard: after removing `section_review` as an emitted type, this guard becomes dead code and should be removed.

Resulting function returns exactly `"teaching"` or `"exercise"`.

---

### 2.3 `backend/src/api/teaching_router.py` — `complete-chunk` pass rule (L1298–1312)

**Current three-branch (verbatim from codebase):**
```python
# Three-branch pass rule:
#   1. exam_disabled OR exercise → decide immediately from MCQ score
#   2. teaching (exam gate enabled) → wait for evaluate-chunk to set passed=True
#   3. everything else (chapter_intro, learning_objective, lab, …) →
#      informational chunks have no exam questions; auto-pass on study completion
_cc_passed: bool | None
if _cc_exam_disabled or _cc_is_exercise:
    _cc_passed = score >= round(CHUNK_EXAM_PASS_RATE * 100)
elif _cc_chunk_type == "teaching":
    # Exam-gate required; passed=False until evaluate-chunk fires
    _cc_passed = False
else:
    # chapter_intro / learning_objective / lab / section_review / etc.
    # Informational chunks never receive exam questions — auto-pass on completion.
    _cc_passed = True
```

**Target two-branch:**
```python
# Two-branch pass rule (two-type architecture):
#   1. exam_disabled OR exercise → decide immediately from MCQ score
#   2. teaching (exam gate enabled) → wait for evaluate-chunk to set passed=True
_cc_passed: bool | None
if _cc_exam_disabled or _cc_is_exercise:
    _cc_passed = score >= round(CHUNK_EXAM_PASS_RATE * 100)
else:  # teaching — exam-gate required
    _cc_passed = False
```

The `else` branch (formerly auto-pass for informational types) is removed entirely. Post-Round-4 all non-exercise chunks are `teaching` — they wait for the exam gate.

**Also check `evaluate-chunk`** (around L1555): if it has a symmetric three-branch referencing legacy types, apply the same two-branch simplification. The `_cc_is_exercise` detection logic at L1290–1296 does not need to change.

---

### 2.4 `backend/src/api/teaching_schemas.py` — L390

```python
# BEFORE
chunk_type:  str = "teaching"  # "teaching"|"exercise"|"chapter_review"|"learning_objective"

# AFTER
chunk_type:  str = "teaching"  # "teaching"|"exercise"
```

---

### 2.5 `backend/src/api/admin_router.py` — `update_chunk` handler (L1874 area)

Insert immediately after the `_allowed` field-set check, before the UPDATE executes:

```python
if "chunk_type" in payload and payload["chunk_type"] not in ("teaching", "exercise"):
    raise HTTPException(
        status_code=400,
        detail="chunk_type must be 'teaching' or 'exercise'"
    )
```

`payload` here is whatever dict is extracted from the request body after the `_allowed` intersection. Confirm exact variable name against the handler at L1874 before inserting.

---

## 3. DB Invariant

No migration required. The `chunk_type` column is unconstrained VARCHAR; the pipeline is the sole writer during ingest.

**Post-ingest verification query:**
```sql
SELECT DISTINCT chunk_type
FROM concept_chunks
WHERE book_slug = 'prealgebra_2e';
```
Expected result: exactly two rows — `teaching` and `exercise`. Any third row is a regression.

**Full distribution check:**
```sql
SELECT chunk_type, COUNT(*)
FROM concept_chunks
WHERE book_slug = 'prealgebra_2e'
GROUP BY chunk_type;
```

---

## 4. API Contract

All endpoints that return a chunk object must emit `chunk_type` ∈ `{"teaching", "exercise"}` after re-ingest. Affected endpoints:

| Endpoint | chunk_type field location |
|---|---|
| `GET /api/v2/sessions/{id}/next-chunk` | `ChunkResponse.chunk_type` |
| `GET /api/v2/students/{id}/progress` | nested chunk objects |
| `PATCH /admin/chunks/{id}` | response body `chunk_type` |
| `GET /admin/books/{slug}/chunks` | list items `chunk_type` |

Clients that store `chunk_type` locally and branch on legacy values will work correctly — `chapter_intro` rows no longer exist post-ingest, so the branch is never reached.

---

## 5. Sequence: complete-chunk (post-Round-4)

```
Frontend                  teaching_router             DB
   |                           |                       |
   |-- POST complete-chunk --> |                       |
   |                           | resolve chunk_type    |
   |                           | (from DB or fallback) |
   |                           |                       |
   |                           |-- "exercise" or       |
   |                           |   exam_disabled?      |
   |                           |   YES: passed = MCQ   |
   |                           |   NO (teaching):      |
   |                           |   passed = False      |
   |                           |                       |
   |                           |-- UPDATE session ---> |
   |                           |   chunk_progress      |
   |<-- 200 {passed, ...} ---- |                       |
   |                           |                       |
   |  (if teaching, passed=False)                      |
   |-- POST evaluate-chunk --> |                       |
   |                           |-- exam score >= 50%?  |
   |                           |   YES: passed = True  |
   |                           |   NO:  passed = False |
   |<-- 200 {passed, ...} ---- |                       |
```

---

## 6. Security Design

No new attack surface introduced. The admin guard (section 2.5) closes an unvalidated string field — it prevents legacy type strings being re-introduced via direct API calls or stale clients.

---

## 7. Observability

No new metrics needed. The existing `[_check_concept_mastered]` log line already emits `xp` and `score`. After this change, any `score=None` mastery log is a regression signal — alert on it if log monitoring exists.

---

## 8. Test Matrix

### `backend/tests/test_chunk_parser_bugs.py`

Update assertions at line 192 and any line asserting `chunk_type == "chapter_review"` or `chunk_type == "lab"`:

| Legacy assertion | New assertion |
|---|---|
| `assert chunk["chunk_type"] == "chapter_review"` | `assert chunk["chunk_type"] == "exercise"` |
| `assert chunk["chunk_type"] == "lab"` | `assert chunk["chunk_type"] == "teaching"` |
| `assert chunk["chunk_type"] == "chapter_intro"` | `assert chunk["chunk_type"] == "teaching"` |

Add new tests:
- `test_chapter_review_emits_exercise`: parse a `(ChapterReview)` heading → expect `"exercise"`.
- `test_lab_emits_teaching`: parse a `(Lab)` heading → expect `"teaching"`.
- `test_chapter_intro_emits_teaching`: synthetic chapter-intro zone → expect `"teaching"`.

### `backend/tests/test_mastery_flow.py`

Drop test: `chapter_intro auto-pass` (the third branch no longer exists).

Keep / update:
- `test_exercise_chunk_mcq_gate`: exercise chunk, MCQ ≥ 50% → `passed=True`.
- `test_teaching_chunk_exam_gate`: teaching chunk, exam score ≥ 50% → `passed=True`.
- `test_teaching_chunk_exam_disabled`: teaching chunk + `exam_disabled=True` → MCQ gate decides.
- `test_multi_chunk_concept_gate`: all required chunks passed → MASTERED + real score.
- `test_teaching_chunk_mcq_below_threshold`: teaching chunk, MCQ < 50% → `passed=False`, no auto-pass.

### `backend/tests/test_admin_content_controls.py`

Add:
- `test_admin_chunk_type_valid`: PATCH with `chunk_type="exercise"` → 200.
- `test_admin_chunk_type_invalid`: PATCH with `chunk_type="chapter_review"` → 400.
- `test_admin_chunk_type_invalid_lab`: PATCH with `chunk_type="lab"` → 400.

---

## 9. Rollback

No Alembic migration to undo.

1. `git revert <Round-4-commit-sha>` (or reset to prior commit on the branch).
2. Redeploy backend.
3. Re-ingest prealgebra_2e from backup or re-run `python -m src.pipeline --book prealgebra_2e` against the old code — the old pipeline will re-emit `chapter_intro` and `chapter_review` rows.

The DB does not enforce the two-type constraint, so old rows are accepted immediately.

---

## Key Decisions Requiring Stakeholder Input

1. Should the `evaluate-chunk` endpoint have a symmetric two-branch patch applied in this round, or only `complete-chunk`? (Recommend: yes, same round for consistency.)
2. Confirm the exact variable name for `payload` at `admin_router.py:1874` before inserting the guard — backend-developer to verify.
