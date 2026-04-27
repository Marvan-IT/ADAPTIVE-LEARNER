# Two-Type Chunk Architecture — High-Level Design

## 1. Executive Summary

**Feature:** Collapse `chunk_type` alphabet from 5 pipeline types + 2 API-fallback types → 2 canonical types: `teaching` and `exercise`.

**Business problem:** The pipeline emits `chapter_intro`, `chapter_review`, `lab`, `teaching`, `exercise` (5 types). The mastery logic in `teaching_router.py` only honours `chunk_type == "teaching"` for the exam-gate path. Every other type falls into a third "informational auto-pass" branch that grants `MASTERED + 50 XP` with `score=None` — with no exam questions generated and no real assessment. Observed live on session `bc9577aa` for a Malayalam student.

**Scope in:** pipeline type emission, API fallback function, complete-chunk pass-rule, admin endpoint validation, schema docstring.
**Scope out:** image-on-cards bug, stuck-loading skeleton (Round 5). No DB migration, no frontend changes.

---

## 2. Server-Confirmed Evidence

| Check | Result | Implication |
|---|---|---|
| `chunk_type` distribution for prealgebra_2e | 4 types: `chapter_intro` 11, `chapter_review` 161, `exercise` 277, `teaching` 402 | Pipeline emits 5 types, contradicts two-type architecture. **Round 4 fixes.** |
| `chapter_review` chunk text sample | Numbered practice problems (`504. $40-15$`, `505. $351-249$`, "model the subtraction") | Should map to `exercise`, not teaching. |
| `chapter_intro` chunk text sample | Prose ("Mount Everest stands as the tallest peak...") + section list | Should map to `teaching`. |
| Latest session `bc9577aa` log trace | cards=5 generated, complete-cards 200, complete-chunk 200, **`[_check_concept_mastered] MASTERED` + `xp-mastery xp=50 score=None`** | Auto-mastery-without-exam bug. Round 4 closes it. |
| Image URLs, cached card content | `presentation_text` NULL on latest sessions; no `image_url` fields | Round 5 territory — separate from this change. |

---

## 3. Two-Type Alphabet Definition

| Canonical Type | Mastery Gate | Description |
|---|---|---|
| `teaching` | Exam-gate required (≥50% on `chunk_questions`) | Prose explanation, concept introduction, labs, objectives |
| `exercise` | MCQ score gate (≥50% across cards) | Numbered practice problems, review drills, writing exercises |

### Legacy-to-Canonical Mapping

| Legacy Type | Source | Canonical | Rationale |
|---|---|---|---|
| `teaching` | pipeline | `teaching` | Already canonical — no change |
| `exercise` | pipeline | `exercise` | Already canonical — no change |
| `chapter_intro` | pipeline | `teaching` | Prose content; exam-gate should decide mastery |
| `chapter_review` | pipeline | `exercise` | Contains numbered practice problems (verified from DB sample) |
| `lab` | pipeline | `teaching` | Default teaching format; `is_optional` flag preserved |
| `section_review` | API fallback only | `teaching` | Section-title headings reclassified to teaching when content > 200 chars |
| `learning_objective` | API fallback only | `teaching` | LO blocks are informational teaching content |

---

## 4. Mastery State Machine

```
                         Student studies chunk cards
                                    |
                         complete-chunk fires
                                    |
              +---------------------+---------------------+
              |                                           |
     chunk_type == "exercise"               chunk_type == "teaching"
     OR exam_disabled == True                 (exam enabled)
              |                                           |
    MCQ score >= 50%?                     exam-gate questions generated
       YES        NO                               |
        |          |                    evaluate-chunk fires
    passed=True  passed=False           exam score >= 50%?
                                          YES         NO
                                           |           |
                                       passed=True  passed=False
                                                        |
                                                  chunk stays open

              All required chunks passed?
      (is_hidden=False AND is_optional=False AND passed=True)
                          |
                   YES → concept MASTERED
                          |
                   +50 XP (real score, not None)
```

**Key invariant:** `passed=True` with `score=None` is impossible after this change. The third "informational auto-pass" branch is removed entirely.

---

## 5. Admin Override Semantics

The existing admin UI toggle in `AdminBookContentPage.jsx:774-785` and `AdminReviewPage.jsx:816-826` already emits only `teaching` or `exercise` to `PATCH /admin/chunks/{id}`. No frontend change needed.

Post-Round-4, the admin endpoint (`admin_router.py:1874`) will validate incoming `chunk_type` values. Any attempt to write a legacy type via direct API call returns HTTP 400. This is defensive — the UI is already compliant.

Admins can flip any chunk post-ingest. Example use case: a borderline review section the pipeline classified as `exercise` but the instructor wants assessed via exam-gate can be toggled to `teaching`.

---

## 6. Architectural Style

Pure data-layer reclassification. No new services, no new tables, no new endpoints. Changes are confined to:
1. Pipeline classification logic (chunk_parser.py)
2. API fallback heuristic (teaching_router.py `_get_chunk_type`)
3. Pass-rule branch reduction (teaching_router.py `complete-chunk`)
4. Defensive validation (admin_router.py)
5. Schema documentation (teaching_schemas.py)

After re-ingest, the DB will enforce the invariant by construction — no migration needed because the `chunk_type` column is unconstrained VARCHAR and the pipeline is the sole writer.

---

## 7. Key Architectural Decisions

| Decision | Options | Chosen | Rationale |
|---|---|---|---|
| Backfill stale rows | UPDATE existing rows in DB | Re-ingest from scratch | Avoids partial-state where pipeline logic and DB rows diverge mid-ingest; prealgebra_2e is not yet live for production users |
| DB constraint on chunk_type | Add CHECK constraint via migration | No migration; validate at API layer | Simpler rollback (revert commit); constraint would block rollback if old pipeline code re-runs |
| `chapter_review` target type | `teaching` (exam) or `exercise` (MCQ) | `exercise` | Server-sampled content is numbered practice problems, not prose explanation |
| `lab` target type | `exercise` or `teaching` | `teaching` | Labs are exploratory/instructional; `is_optional` flag already handles optional mastery |

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Re-ingest wipes admin edits on prealgebra_2e | Low | Low | Book not yet in production; re-ingest acceptable |
| LLM may generate exercise-style cards for teaching chunks (or vice versa) | Medium | Low | Admin toggle available post-ingest; no data loss |
| `chapter_review` chunks contain mixed content (some prose) | Low | Low | Admin can reclassify individual chunks; design allows per-chunk override |
| Round 5 image/loading bugs resurface post-deploy | High | Medium | Explicitly deferred; fresh repro needed after Round 4 deploy |
| stale frontend sessions with `chunk_type=chapter_intro` cached in browser | Low | Low | Re-ingest creates new chunk UUIDs; stale sessions are invalidated |

---

## Key Decisions Requiring Stakeholder Input

1. Should any book other than prealgebra_2e be re-ingested as part of this round? (Current plan: prealgebra_2e only.)
2. Are there `lab` chunks in any book that should map to `exercise` rather than `teaching`? (Current plan: all labs → teaching.)
