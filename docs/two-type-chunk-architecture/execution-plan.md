# Two-Type Chunk Architecture — Execution Plan

## Phase Overview

| Phase | Agent | Goal | Effort |
|---|---|---|---|
| 0 | solution-architect | Design docs | 0.5 d |
| 1 | backend-developer | Code changes per DLD | 1.0 d |
| 2 | comprehensive-tester | Test updates + green suite | 0.5 d |
| 3 | devops-engineer | DEPLOY.md + server ops | 0.5 d |

Total estimated effort: 2.5 engineer-days, ~2 calendar days (Phases 1–2 can overlap).

---

## Phase 0 — solution-architect (this document)

**Deliverables:**
- `docs/two-type-chunk-architecture/HLD.md`
- `docs/two-type-chunk-architecture/DLD.md`
- `docs/two-type-chunk-architecture/execution-plan.md`

**Acceptance criteria:**
- All three files exist and cover the full change surface per the plan file.
- Server-confirmed evidence table reproduced in HLD.
- Exact file/line references from plan reproduced in DLD.

---

## Phase 1 — backend-developer

### WBS

| ID | Task | File | Lines | Effort |
|---|---|---|---|---|
| P1-1 | Collapse `(ChapterReview)` tag to `"exercise"` | `extraction/chunk_parser.py` | L276 | 0.1 d |
| P1-2 | Collapse `(Lab)` tag to `"teaching"` | `extraction/chunk_parser.py` | L278 | 0.1 d |
| P1-3 | Collapse `is_lab` branch to `"teaching"` | `extraction/chunk_parser.py` | L284 | 0.1 d |
| P1-4 | Change chapter-intro emission to `"teaching"` | `extraction/chunk_parser.py` | L937 | 0.1 d |
| P1-5 | Change review-zone override to `"exercise"` | `extraction/chunk_parser.py` | L1075 | 0.1 d |
| P1-6 | Rewrite `_get_chunk_type` to return only `teaching`/`exercise` | `teaching_router.py` | L77–126 | 0.2 d |
| P1-7 | Replace three-branch pass rule with two-branch | `teaching_router.py` | L1298–1312 | 0.2 d |
| P1-8 | Apply same two-branch to `evaluate-chunk` if applicable | `teaching_router.py` | ~L1555 | 0.1 d |
| P1-9 | Update schema docstring comment | `teaching_schemas.py` | L390 | 0.05 d |
| P1-10 | Add `chunk_type` guard to `update_chunk` handler | `admin_router.py` | L1874 area | 0.1 d |

**Acceptance criteria:**

```bash
# Zero chunk_type assignment hits for legacy types:
grep -nE 'chunk_type\s*=\s*"chapter_intro"|chunk_type\s*=\s*"chapter_review"|chunk_type\s*=\s*"lab"' \
  backend/src/extraction/chunk_parser.py
# Expected: no output

# _get_chunk_type returns only two values:
grep -nE '"section_review"|"learning_objective"' \
  backend/src/api/teaching_router.py | grep "chunk_type\s*="
# Expected: no output

# Three-branch comment removed:
grep -n "informational chunks" backend/src/api/teaching_router.py
# Expected: no output

# Admin guard present:
grep -n "must be.*teaching.*exercise" backend/src/api/admin_router.py
# Expected: one hit
```

Backend must start cleanly: `python -m uvicorn src.api.main:app --port 8889` with no import errors.

---

## Phase 2 — comprehensive-tester

### WBS

| ID | Task | File | Effort |
|---|---|---|---|
| P2-1 | Update `chunk_type == "chapter_review"` assertions to `"exercise"` | `test_chunk_parser_bugs.py` | 0.1 d |
| P2-2 | Update `chunk_type == "lab"` assertions to `"teaching"` | `test_chunk_parser_bugs.py` | 0.1 d |
| P2-3 | Add `test_chapter_review_emits_exercise`, `test_lab_emits_teaching`, `test_chapter_intro_emits_teaching` | `test_chunk_parser_bugs.py` | 0.1 d |
| P2-4 | Drop `chapter_intro auto-pass` test | `test_mastery_flow.py` | 0.05 d |
| P2-5 | Add `test_teaching_chunk_mcq_below_threshold` (no auto-pass) | `test_mastery_flow.py` | 0.1 d |
| P2-6 | Add `test_admin_chunk_type_invalid` (400 on legacy type) | `test_admin_content_controls.py` | 0.1 d |
| P2-7 | Run full backend test suite | — | 0.05 d |
| P2-8 | Run `npm run build` (frontend smoke check) | — | 0.05 d |

**Acceptance criteria:**
- `pytest` exits 0 with no skipped mastery tests.
- `npm run build` exits 0.
- No test references `chunk_type == "chapter_review"`, `"chapter_intro"`, or `"lab"` as an expected value.

```bash
grep -rn '"chapter_review"\|"chapter_intro"\|"lab"' backend/tests/ | grep "assert\|==\|expected"
# Expected: no output
```

---

## Phase 3 — devops-engineer

### WBS

| ID | Task | Effort |
|---|---|---|
| P3-1 | Add pre-deploy wipe SQL block to `DEPLOY.md` | 0.1 d |
| P3-2 | Add re-ingest command to `DEPLOY.md` | 0.05 d |
| P3-3 | Add post-ingest verification SQL to `DEPLOY.md` | 0.05 d |
| P3-4 | SSH to server, `git pull`, execute wipe SQL | 0.1 d |
| P3-5 | Run `python -m src.pipeline --book prealgebra_2e` inside backend container | 0.1 d |
| P3-6 | Run verification SQL; confirm only `teaching` + `exercise` rows | 0.05 d |
| P3-7 | Restart backend container | 0.05 d |

**DEPLOY.md additions (verbatim for devops-engineer):**

```markdown
## Round 4: Two-Type Chunk Architecture Deploy

### Pre-deploy: wipe prealgebra_2e
```bash
docker compose exec db psql -U postgres -d AdaptiveLearner -c "
DELETE FROM teaching_sessions WHERE book_slug='prealgebra_2e';
DELETE FROM concept_chunks WHERE book_slug='prealgebra_2e';
DELETE FROM concepts WHERE book_slug='prealgebra_2e';
DELETE FROM books WHERE slug='prealgebra_2e';
"
```

### Re-ingest
```bash
docker compose exec backend python -m src.pipeline --book prealgebra_2e
```

### Verify
```sql
SELECT chunk_type, COUNT(*)
FROM concept_chunks
WHERE book_slug = 'prealgebra_2e'
GROUP BY chunk_type;
-- Expected: exactly two rows (teaching, exercise)
```

### Post-ingest smoke test
As a Malayalam student, walk through prealgebra_2e_1.0:
1. Cards generate (presentation_text not NULL)
2. After all cards on a teaching chunk, exam-gate questions appear
3. Pass exam → chunk passed=True → eventually MASTERED + 50 XP (score is real, not None)
4. Fail exam → chunk stays passed=False → no mastery granted
```

**Acceptance criteria:**
- Verification SQL returns exactly 2 rows: `teaching` and `exercise`.
- No row with `chunk_type = 'chapter_intro'` or `'chapter_review'` or `'lab'` exists in `concept_chunks`.
- Backend container healthy: `docker compose ps` shows backend `Up`.

---

## Critical Path

```
P1-1..P1-5 (chunk_parser) → P1-6..P1-8 (teaching_router) → P1-9, P1-10 (schemas, admin)
                                                               ↓
                                                          P2-1..P2-8 (tests)
                                                               ↓
                                                     P3-1..P3-3 (DEPLOY.md)
                                                               ↓
                                                     P3-4..P3-7 (server ops)
```

P1 tasks have no internal dependencies — P1-1 through P1-10 can be committed in a single PR.

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Re-ingest wipes admin edits on prealgebra_2e | Low | Low | Book not in production; no real users affected |
| LLM interprets some teaching chunks as exercises during card generation | Medium | Low | Admin toggle available post-ingest; no data integrity issue |
| `chapter_review` chunks contain mixed content (some prose sections) | Low | Low | Admin can flip individual chunks to `teaching` post-ingest |
| `evaluate-chunk` still has a legacy third branch after Phase 1 | Medium | Medium | DLD explicitly calls out ~L1555 check; P1-8 covers it |
| Image-on-cards bug surfaces after re-ingest | High | Medium | Explicitly Round 5 — do not scope creep here |
| Stuck-loading skeleton repros post-deploy | Medium | Medium | Explicitly Round 5 — fresh repro needed after clean ingest |

---

## Definition of Done (full initiative)

- [ ] `grep -nE '"chapter_intro"|"chapter_review"|"lab"' backend/src/extraction/chunk_parser.py` — zero chunk_type assignment hits
- [ ] `_get_chunk_type` docstring reads `Returns: 'teaching' | 'exercise'`
- [ ] `complete-chunk` pass rule has no third branch
- [ ] `teaching_schemas.py:390` comment lists only `"teaching"|"exercise"`
- [ ] `admin_router.py` rejects `chunk_type` outside `{teaching, exercise}` with HTTP 400
- [ ] `pytest` exits 0, all mastery and chunk-parser tests pass
- [ ] `npm run build` exits 0
- [ ] Verification SQL on server returns exactly 2 distinct chunk_types
- [ ] Malayalam student smoke test: exam-gate appears, MASTERED only with real score

---

## Out of Scope (Round 5)

- Image-on-cards: `images=` arg tracing in `teaching_service.py` + `[IMAGE:N]` post-processor
- Stuck-loading skeleton: requires fresh repro after Round 4 deploy with non-NULL `presentation_text`
