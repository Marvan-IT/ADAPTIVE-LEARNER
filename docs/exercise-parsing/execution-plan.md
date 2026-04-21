# Exercise Pattern Parsing — Execution Plan

## 1. Work Breakdown Structure

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| S0 | Alembic migration — chunk_type CHECK constraint | New migration `016_chunk_type_check_constraint.py`; pre-check for invalid rows; upgrade adds constraint, downgrade removes it | 0.5d | — | `alembic/versions/` |
| 2A | Remove conflicting noise patterns | Remove 22 entries from `_NOISE_HEADING_PATTERNS` in `chunk_parser.py` (Self Check, Writing Exercises, Everyday Math, Mixed Practice, Review Exercises, Practice Test, Key Terms, Key Concepts, Chapter Review, Practice, Formula Review, Homework, Solutions, Bringing It Together, References, Check Your Understanding, Lesson Summary, Lesson Overview, Additional Resources, Cool Down, Warm Up, Verbal, Algebraic) | 0.5d | — | `chunk_parser.py` |
| 2B | Fix orphan content after zone dividers | In `_build_section_chunks()`: buffer content between a skipped zone_divider heading and the next subsection heading; prepend to first exercise chunk; fallback single exercise chunk if no subsection follows | 1.0d | 2A | `chunk_parser.py` |
| 2C | Extend ExerciseMarker with `group` field | Add `group: str = "zone_divider"` to `ExerciseMarker`; update `_PROFILER_JSON_SCHEMA` + system prompt rules; update `_llm_dict_to_profile()` to parse group; update `legacy_profile_from_config()` to emit correct groups for all EX-A markers | 1.5d | — | `book_profiler.py` |
| 2C2 | Update config.py vocabulary constants | Add `EXERCISE_GROUP_*` constants; expand `EXERCISE_SECTION_MARKERS`; add `BACK_MATTER_CHUNK_HEADINGS` list | 0.5d | 2C | `config.py` |
| 2D | Update chunk_parser zone logic to dispatch on group | Change `_build_parse_config()` to compile `(pattern, behavior, group)` triples; add `_match_exercise_marker_group()`; update zone tagging loop to dispatch on group → emit correct chunk_type; best-effort fallback for unknown headings | 1.5d | 2B, 2C | `chunk_parser.py` |
| 2E | Add back-matter re-assignment | Add `_reassign_back_matter()` helper; call it at the start of `_postprocess_chunks()` before deduplication | 1.0d | 2D | `chunk_parser.py` |
| 2F | OCR cleanup — `©` strip + Stats Lab normalization | In `_normalize_heading()`: add `re.sub(r"^©\s*", "", h)` and `re.sub(r"^[Ss]tats\s+hab\b", "Stats Lab", h)` | 0.25d | — | `chunk_parser.py` |
| 2G | Best-effort fallback logging | Log `warning` for unmatched headings in exercise zone; log `info` summaries per book after reprocess | 0.25d | 2D | `chunk_parser.py` |
| T1 | Create MMD fixtures | Extract 50–150 line MMD excerpts from each of the 5 book patterns; save to `backend/tests/fixtures/` | 1.0d | — | `tests/fixtures/` |
| T2 | Unit tests per pattern | `TestExAPrealgebra`, `TestExACollegeAlgebra`, `TestExBStatistics`, `TestExCAlgebra1`, `TestExDNursing` | 2.0d | T1, 2G | `tests/test_exercise_parsing.py` |
| T3 | Regression tests | 8 regression tests: teaching chunks unaffected, orphan content preserved, self check dedup, back matter re-assignment, Stats Lab normalization, OCR strip, unknown heading fallback | 1.5d | T1, 2G | `tests/test_exercise_parsing.py` |
| T4 | Integration tests | Full pipeline run on prealgebra2e; verify chunk counts by type; Stats lab count for statistics | 1.0d | T2, T3 | `tests/test_exercise_parsing.py` |
| R1 | Delete cached profiles for all 8 books | Delete `backend/output/{book_slug}/book_profile.json` for all 8 books to force re-profiling with updated prompt | 0.25d | 2C | pipeline admin |
| R2 | Reprocess all 8 books (in order) | Run `python -m src.pipeline --book {slug}` for each book in the required order | 2.0d | 2G, R1, S0 | pipeline |
| V1 | Post-reprocess verification | Admin UI spot-check for each book; SQL chunk counts by type; compare against recon data | 1.0d | R2 | QA |

**Total estimated effort: ~16 dev-days**

---

## 2. Phased Delivery Plan

### Phase 0 — Infrastructure (0.5d)

**Tasks:** S0

- Create Alembic migration `016_chunk_type_check_constraint.py`
- Pre-check query ensures no existing rows have unknown `chunk_type` values
- Apply migration to development database: `alembic upgrade head`

**Gate:** Migration applied; `alembic current` shows `016` as head.

---

### Phase 2A — Fix Noise Pattern Conflict (0.5d)

**Tasks:** 2A

**File:** `backend/src/extraction/chunk_parser.py`

Remove the following entries from `_NOISE_HEADING_PATTERNS` (lines ~74–130). These headings must survive to the zone tagging step.

Entries to remove (exact compile lines):
```python
re.compile(r"^Self Check\b", re.IGNORECASE),
re.compile(r"^Writing Exercises\b", re.IGNORECASE),
re.compile(r"^Everyday Math\b", re.IGNORECASE),
re.compile(r"^Mixed Practice\b", re.IGNORECASE),
re.compile(r"^Review Exercises\b", re.IGNORECASE),
re.compile(r"^Practice Test\b", re.IGNORECASE),
re.compile(r"^Key Terms\b", re.IGNORECASE),
re.compile(r"^Key Concepts\b", re.IGNORECASE),
re.compile(r"^Formula Review\b", re.IGNORECASE),
re.compile(r"^Homework\b", re.IGNORECASE),
re.compile(r"^Solutions\b", re.IGNORECASE),
re.compile(r"^Bringing It Together\b", re.IGNORECASE),
re.compile(r"^Chapter Review\b", re.IGNORECASE),
re.compile(r"^Practice\b", re.IGNORECASE),
re.compile(r"^References\b", re.IGNORECASE),
re.compile(r"^Check Your Understanding\b", re.IGNORECASE),
re.compile(r"^Lesson Summary\b", re.IGNORECASE),
re.compile(r"^Lesson Overview\b", re.IGNORECASE),
re.compile(r"^Additional Resources\b", re.IGNORECASE),
re.compile(r"^Cool Down\b", re.IGNORECASE),
re.compile(r"^Warm Up\b", re.IGNORECASE),
re.compile(r"^Verbal\b", re.IGNORECASE),
re.compile(r"^Algebraic\b", re.IGNORECASE),
```

**DoD:** None of the above headings appear in `_NOISE_HEADING_PATTERNS`; existing teaching chunk tests still pass.

---

### Phase 2B — Fix Orphan Content After Zone Dividers (1.0d)

**Tasks:** 2B

**File:** `backend/src/extraction/chunk_parser.py`, function `_build_section_chunks()`

Track and re-attach content that appears between a zone_divider heading and the next subsection heading. See DLD section 9.3 for pseudo-code.

**DoD:** Unit test `test_orphan_content_preserved` passes; content between "SECTION 1.1 EXERCISES" and first PMP topic is included in the first exercise chunk's text.

---

### Phase 2C — Extend ExerciseMarker with `group` field (1.5d + 0.5d)

**Tasks:** 2C, 2C2

**Files:** `backend/src/extraction/book_profiler.py`, `backend/src/config.py`

1. Add `group: str = "zone_divider"` field to `ExerciseMarker` Pydantic model
2. Update `_PROFILER_JSON_SCHEMA` to include `"group"` in the exercise_markers schema
3. Update system prompt rule #4 with group definitions (see DLD section 9.6)
4. Update `_llm_dict_to_profile()` to read `raw_ex.get("group", "zone_divider")`
5. Update `legacy_profile_from_config()` to emit correct group for all existing markers (see DLD section 9.7)
6. Add `EXERCISE_GROUP_*` constants and `BACK_MATTER_CHUNK_HEADINGS` list to `config.py`

**DoD:** `ExerciseMarker` has `group` field; existing cached profiles (without `group`) deserialize without error (Pydantic default); `legacy_profile_from_config()` emits group for all markers.

---

### Phase 2D — Update Chunk Parser Zone Logic (1.5d)

**Tasks:** 2D

**File:** `backend/src/extraction/chunk_parser.py`

1. Update `_build_parse_config()` to compile `(pattern, behavior, group)` triples
2. Add `_match_exercise_marker_group()` function
3. Update zone tagging loop in `_build_section_chunks()` to dispatch on group:
   - `zone_divider` → set `in_exercises_zone=True`, skip heading, buffer orphan (2B)
   - `back_matter` → emit `chunk_type="chapter_review"`
   - `lab` → emit `chunk_type="lab"`
   - `standalone_exercise`, `pmp_topic`, `chapter_pool`, or `in_exercises_zone=True` → emit `chunk_type="exercise"`
   - no match in exercise zone → emit `chunk_type="exercise"` + `logger.warning()`
4. Remove the existing `"(Exercises)"` suffix tagging (line 896-904) — replaced by group dispatch
5. Remove the existing `_REVIEW_ZONE_RE` block (lines 868-876) — replaced by group dispatch for `back_matter`

**DoD:** EX-A prealgebra unit test passes; EX-B statistics unit test passes; no "(Exercises)" suffixes appear in chunk headings.

---

### Phase 2E — Back Matter Re-Assignment (1.0d)

**Tasks:** 2E

**File:** `backend/src/extraction/chunk_parser.py`

1. Add `_reassign_back_matter(raw_chunks, book_slug)` function (see DLD section 9.5)
2. Call it at the start of `_postprocess_chunks()` before the dedup step

**DoD:** Unit test `test_back_matter_reassignment` passes; Key Terms and Practice Test chunks have `concept_id` equal to the last section in their chapter.

---

### Phase 2F — OCR Cleanup (0.25d)

**Tasks:** 2F

**File:** `backend/src/extraction/chunk_parser.py`, function `_normalize_heading()`

Add two lines:
```python
h = re.sub(r"^©\s*", "", h)
h = re.sub(r"^[Ss]tats\s+hab\b", "Stats Lab", h)
```

**DoD:** Unit tests `test_stats_lab_normalization` and `test_ocr_copyright_strip` pass.

---

### Phase 2G — Fallback Logging (0.25d)

**Tasks:** 2G

**File:** `backend/src/extraction/chunk_parser.py`

Add structured log calls for:
- Unmatched heading in exercise zone → `logger.warning()`
- Back matter re-assignment count → `logger.info()`
- Per-book chunk type summary after `_postprocess_chunks()` → `logger.info()`

**DoD:** Log messages appear at correct level; no silent failures.

---

### Phase T — Testing (4.5d)

**Tasks:** T1, T2, T3, T4

1. **T1 (1.0d):** Extract MMD fixtures from real book files; validate they contain the expected patterns manually
2. **T2 (2.0d):** Write unit tests per pattern class (5 test classes, ~20 assertions)
3. **T3 (1.5d):** Write regression tests (8 tests)
4. **T4 (1.0d):** Full integration test run on prealgebra2e; verify chunk counts match recon data

**DoD:** All tests pass; coverage report shows exercise_parsing module ≥80% covered.

---

### Phase R — Reprocessing (2.25d)

**Tasks:** R1, R2

**Order is mandatory** — do not skip books, do not run in parallel (shared DB).

**Step 1 — Delete cached profiles (R1, 0.25d):**
```bash
# For each book slug:
rm backend/output/{book_slug}/book_profile.json
```
Book slugs requiring deletion:
- `prealgebra2e_0qbw93r_(1)` (or local slug)
- `elementary_algebra`
- `intermediate_algebra`
- `college_algebra`
- `statistics`
- `business_statistics`
- `algebra_1`
- `clinical_nursing_skills`

**Step 2 — Reprocess in order (R2, 2.0d):**

| Order | Book Slug | Pattern | Expected New chunk_type counts |
|-------|-----------|---------|-------------------------------|
| 1 | `prealgebra2e` | EX-A | exercise ≥396, chapter_review ≥60 |
| 2 | `elementary_algebra` | EX-A | exercise ≥470, chapter_review ≥60 |
| 3 | `intermediate_algebra` | EX-A (+ © prefix) | exercise ≥225, chapter_review ≥60 |
| 4 | `college_algebra` | EX-A-alt | exercise ≥310, chapter_review ≥60 |
| 5 | `statistics` | EX-B | exercise ≥65, lab ≥17, chapter_review ≥65 |
| 6 | `business_statistics` | EX-B | exercise ≥55, lab = 0, chapter_review ≥50 |
| 7 | `algebra_1` | EX-C | exercise ≥117, chapter_review = 0 |
| 8 | `clinical_nursing_skills` | EX-D | exercise ≥116, chapter_review = 0 |

```bash
cd backend
python -m src.pipeline --book {slug}
```

---

### Phase V — Verification (1.0d)

**Tasks:** V1

**Per-book verification checklist:**

After each book reprocess:

1. **SQL count check:**
   ```sql
   SELECT chunk_type, COUNT(*)
   FROM concept_chunks
   WHERE book_slug = '{slug}'
   GROUP BY chunk_type ORDER BY chunk_type;
   ```
   Verify non-zero counts for `exercise` and `chapter_review`. Verify `teaching` count is within ±5% of pre-reprocess count.

2. **Admin UI spot-check (2–3 sections per book):**
   - Section 1.1 (or equivalent) shows exercise subsections under teaching content
   - Chapter 1's last section shows back matter chunks (Key Terms, Practice Test)
   - No chunk has a `heading` ending in "(Exercises)" (the old suffix is gone)
   - `chunk_type` labels are correct in the Admin content UI

3. **Back matter spot-check:**
   ```sql
   SELECT concept_id, heading, chunk_type
   FROM concept_chunks
   WHERE book_slug = '{slug}' AND chunk_type = 'chapter_review'
   LIMIT 10;
   ```
   Verify all `chapter_review` chunks have a `concept_id` ending in `.{N}` where N > 0 (not a fake chapter-review ID).

4. **Stats Lab spot-check (statistics only):**
   ```sql
   SELECT heading, chunk_type FROM concept_chunks
   WHERE book_slug = 'statistics' AND chunk_type = 'lab'
   ORDER BY heading;
   ```
   Expect 17 rows; all headings contain "Lab" (not "hab").

---

## 3. Dependencies and Critical Path

```
S0 ──────────────────────────────────────────────────────────► R2
     ↓
2A ──► 2B ──► 2D ──► 2E ──► 2F ──► 2G ──► T2 ──► T3 ──► T4 ──► R1 ──► R2 ──► V1
              ↑
2C ──► 2C2 ──┘

T1 ──► T2
T1 ──► T3
```

**Critical path:** 2A → 2B → 2D → 2E → 2F → 2G → T1 → T2 → T3 → T4 → R1 → R2 → V1

**Phases that can run in parallel:**
- 2C / 2C2 can run in parallel with 2A / 2B
- 2F can run at any time (isolated normalization change)
- S0 (migration) can run in parallel with all 2X phases

**Blocking dependencies:**
- 2D requires both 2B (orphan content) and 2C (group field in ExerciseMarker)
- R1 (profile deletion) requires 2C to be merged and deployed
- R2 requires S0, 2G, and R1

---

## 4. Definition of Done

### Per Phase

| Phase | Acceptance Criteria |
|-------|-------------------|
| S0 | `alembic upgrade head` runs clean; invalid chunk_type insert raises `CheckViolation`; `alembic downgrade -1` removes constraint without data loss |
| 2A | No entry in `_NOISE_HEADING_PATTERNS` matches Self Check, Writing Exercises, Everyday Math, Mixed Practice, Review Exercises, Practice Test, Key Terms, Key Concepts; existing tests pass |
| 2B | `test_orphan_content_preserved` passes; no orphan content reported as lost in logs for prealgebra test fixture |
| 2C | `ExerciseMarker` has `group` with default `"zone_divider"`; old `book_profile.json` (without group) loads without error; `legacy_profile_from_config()` emits correct groups |
| 2D | EX-A and EX-B unit tests pass; no chunk headings end in "(Exercises)"; `chunk_type` values are correct |
| 2E | `test_back_matter_reassignment` passes; `chapter_review` chunks have valid section concept_ids |
| 2F | `test_stats_lab_normalization` and `test_ocr_copyright_strip` pass |
| 2G | `logger.warning` appears for unmatched heading in test fixture; summary log appears after reprocess |
| T (all) | All unit + regression + integration tests pass; no pytest failures; coverage ≥80% for new code |
| R | All 8 books reprocessed; chunk type counts meet minimums in the table above |
| V | SQL spot-checks pass; Admin UI shows correct chunk labels for 2+ sections per book |

### Overall Feature DoD

- [ ] All 23 tasks complete
- [ ] All tests pass (pytest exit code 0)
- [ ] All 8 books reprocessed and verified
- [ ] No chunk heading ends in "(Exercises)" suffix
- [ ] `chapter_review` chunks appear under the last section in Admin UI
- [ ] Stats Lab chunks appear as `lab` type in Admin UI
- [ ] Alembic migration applied to all environments
- [ ] Cached profiles regenerated for all 8 books

---

## 5. Rollout Strategy

**Deployment approach:** Offline pipeline change — no API or frontend changes. Backend service does not need to restart.

**Sequence:**
1. Deploy backend code changes (2A–2G) to server
2. Apply Alembic migration: `alembic upgrade head`
3. Delete cached book profiles (R1) — ensures re-profiling uses updated prompt
4. Reprocess books in order (R2)
5. Verify results (V1)

**Rollback plan:**
- Code rollback: revert git commit; re-deploy; run `alembic downgrade -1` to remove CHECK constraint
- Data rollback: re-run pipeline with the previous code to restore original chunk data
- No user-facing features are affected — the Admin UI reads whatever is in `concept_chunks`

**Post-reprocess monitoring:**
- Run SQL chunk count queries (see V1) after each book
- Check server logs for `[back_matter]` re-assignment counts and `[exercise]` unmatched warnings
- If unexpected counts: inspect `book_profile.json` for the affected book and verify `group` fields are correct

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|-------------------|
| Phase 0 (Infrastructure) | S0: Alembic migration | 0.5d | devops-engineer |
| Phase 2A (Noise fix) | Remove 22 noise entries | 0.5d | backend-developer |
| Phase 2B (Orphan content) | Buffer + prepend zone divider content | 1.0d | backend-developer |
| Phase 2C (ExerciseMarker) | Add group field, update profiler prompt | 2.0d | backend-developer |
| Phase 2D (Zone logic) | Group dispatch in chunk_parser | 1.5d | backend-developer |
| Phase 2E (Back matter) | `_reassign_back_matter()` helper | 1.0d | backend-developer |
| Phase 2F + 2G (OCR + logging) | Normalization + structured logs | 0.5d | backend-developer |
| Phase T (Testing) | Fixtures + unit + regression + integration | 4.5d | comprehensive-tester |
| Phase R (Reprocessing) | Delete profiles + reprocess 8 books | 2.25d | backend-developer |
| Phase V (Verification) | SQL checks + Admin UI spot-check | 1.0d | backend-developer / QA |
| **Total** | | **~14.75d** | backend-developer + tester |

With one backend developer and one tester working in parallel on independent phases, calendar time is approximately **8–9 days**.

---

## Key Decisions Requiring Stakeholder Input

1. **Reprocessing timing:** All 8 books must be reprocessed after the code ships. This will briefly make exercise content unavailable in the Admin UI during the pipeline run for each book. Confirm whether this is acceptable during a maintenance window or if it can run during off-peak hours.
2. **Profile cache invalidation automation:** The plan requires manually deleting 8 `book_profile.json` files. Consider adding a `--clear-profile` flag to the pipeline CLI to automate this.
3. **Test fixture extraction:** Fixtures must be extracted from real book MMD files (`backend/output/{book_slug}/book.mmd`). These files must be present on the developer's machine. Confirm they are available in the development environment.
4. **Parallel reprocessing:** The plan requires sequential reprocessing to avoid DB conflicts. If the pipeline supports per-chapter parallelism, books could be reprocessed concurrently. Confirm whether this is safe.
