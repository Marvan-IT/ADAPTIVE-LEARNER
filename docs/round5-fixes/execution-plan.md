# Round 5 Fixes — Execution Plan

## Branch Strategy

Single feature branch `round5-fixes` off `main`. Four commits, each shipped as its own PR to `main` so they can be reviewed and reverted independently. Merge order matches commit order below.

```
main
 └── round5-fixes
      ├── commit 1: P3 — CHUNK_EXAM_PASS_RATE live read
      ├── commit 2: P4 — OPENAI_MODEL live read
      ├── commit 3: P2 — per-language commit in translate_catalog
      └── commit 4: P1 — hide-section filter on student graph endpoints
```

---

## Work Breakdown Structure

### Commit 1 — P3: CHUNK_EXAM_PASS_RATE live AdminConfig

| ID | Task | File(s) | Effort |
|----|------|---------|--------|
| P3-1 | Create `admin_config_helper.py` with `get_admin_config` + `get_openai_model` stubs | `backend/src/services/admin_config_helper.py` (new) | 0.5d |
| P3-2 | Wire `get_admin_config` at teaching_router L1285 (chunk_progress) | `teaching_router.py` | 0.5d |
| P3-3 | Wire `get_admin_config` at teaching_router L1530 (evaluate-chunk) | `teaching_router.py` | 0.25d |
| P3-4 | Add unit test: mock AdminConfig row → assert new pass rate is used; no row → assert fallback to config.py default | new test file or existing `test_teaching_router.py` | 0.5d |
| P3-5 | Manual verification (see V3 below) | — | 0.25d |

**Total: ~2 dev-days**

### Commit 2 — P4: OPENAI_MODEL live AdminConfig

| ID | Task | File(s) | Effort |
|----|------|---------|--------|
| P4-1 | Implement `get_openai_model` in `admin_config_helper.py` (already stubbed in P3-1) | `admin_config_helper.py` | 0.25d |
| P4-2 | Refactor `TeachingService.__init__` — remove model capture; add `db` parameter to each public entry point | `teaching_service.py` | 1d |
| P4-3 | Update `teaching_router.py` (L1828) to pass `db` and resolve model | `teaching_router.py` | 0.25d |
| P4-4 | Refactor `adaptive_engine.py` entry points | `adaptive_engine.py` | 0.5d |
| P4-5 | Refactor `translation_helper.py` entry points | `translation_helper.py` | 0.25d |
| P4-6 | Refactor `translate_catalog.py` — resolve at top of `translate_book()`, pass through | `translate_catalog.py` | 0.25d |
| P4-7 | Defer `llm_extractor.py` / `graph_builder.py` to future patch (offline tools, no live db session) — document in code comment | `llm_extractor.py`, `graph_builder.py` | 0.1d |
| P4-8 | Unit test: AdminConfig row → assert resolved model used; no row → assert env var fallback | new test | 0.5d |
| P4-9 | Manual verification (see V4 below) | — | 0.25d |

**Total: ~3.5 dev-days**

### Commit 3 — P2: Per-language commit in translate_catalog

| ID | Task | File(s) | Effort |
|----|------|---------|--------|
| P2-1 | Add `await db.commit()` after `await db.flush()` inside `_translate_table` (guarded by `not dry_run`) | `translate_catalog.py` | 0.25d |
| P2-2 | Add structured INFO logging in `_needs_translate` for hash mismatch and missing langs | `translate_catalog.py` | 0.25d |
| P2-3 | Update `test_translate_catalog_script.py` — replace flush-only mock; add restart-simulation test | `test_translate_catalog_script.py` | 1d |
| P2-4 | Manual verification: stress test with mid-run kill (see V2 below) | — | 0.5d |

**Total: ~2 dev-days**

### Commit 4 — P1: Hide-section filter on student graph endpoints

| ID | Task | File(s) | Effort |
|----|------|---------|--------|
| P1-1 | Add `get_hidden_concept_ids(db, book_slug) -> set[str]` to `chunk_knowledge_service.py` | `chunk_knowledge_service.py` | 0.5d |
| P1-2 | Apply filter to `graph_full` (nodes + edges) | `main.py` | 0.25d |
| P1-3 | Apply filter to `topological_order` (concept list) | `main.py` | 0.25d |
| P1-4 | Apply 404 guard + filter to `get_concept` and `get_concept_images` | `main.py` | 0.25d |
| P1-5 | Apply filter to `get_prerequisites` | `main.py` | 0.25d |
| P1-6 | Apply filter to `next_concepts` (both ready_to_learn and locked) | `main.py` | 0.25d |
| P1-7 | Add `invalidate_graph_cache(book_slug)` in `admin_router.py` at toggle_section_visibility | `admin_router.py` | 0.25d |
| P1-8 | Unit tests: hide concept → assert absent from graph_full, topological, prerequisites; edge filter test; mastery row preserved | new test file | 1d |
| P1-9 | Manual verification (see V1 below) | — | 0.25d |

**Total: ~3 dev-days**

---

## Phased Delivery

| Phase | Commit | Key deliverable | Gate before next |
|-------|--------|-----------------|-----------------|
| 1 | P3 | `admin_config_helper.py` + live pass rate | `pytest backend/tests` green + V3 manual |
| 2 | P4 | Live model resolution across service layer | `pytest backend/tests` green + V4 manual |
| 3 | P2 | Per-language commit + idempotency logging | `pytest backend/tests` green + V2 stress test |
| 4 | P1 | Graph filter + cache invalidation | `pytest backend/tests` green + V1 manual |

---

## Test Gates

Before marking any PR ready for review:

1. `pytest backend/tests` — full suite, zero failures.
2. No regression in existing tests (especially `test_translate_catalog_script.py` after P2, and any teaching_router tests after P3/P4).
3. New tests added for the patch (listed in WBS above).

---

## Definition of Done (per PR)

- [ ] New tests pass and cover the happy path + the fallback case (AdminConfig row absent).
- [ ] No `print()` / `console.log` debug residue.
- [ ] All new constants reference `config.py` (no magic literals).
- [ ] Code review approved by at least one other engineer.
- [ ] Manual verification steps completed and signed off.

---

## Manual Verification Checklist

**V1 (P1):** Admin hides section → `curl /api/v1/graph/full?book_slug=X` returns no node for that concept_id and no edges referencing it. Student who mastered that section still has `StudentMastery` row in DB (`SELECT * FROM student_mastery WHERE concept_id = 'X'`).

**V2 (P2):** Run `python -m src.pipeline --book <slug>` → kill backend mid-language (`Ctrl+C`) → restart → observe log: `[translate_catalog] _needs_translate: missing langs=[]` for already-committed languages. No duplicate API calls.

**V3 (P3):** Set `CHUNK_EXAM_PASS_RATE=0.60` in Admin UI → student scores 55% on chunk exam → result is FAIL. Set back to `0.50` → next attempt at 55% PASSES.

**V4 (P4):** Set `OPENAI_MODEL_MINI=gpt-4o` in Admin UI → run a translate_catalog or card generation → confirm `model=gpt-4o` in backend INFO log or OpenAI dashboard.

---

## Effort Summary

| PR | Commits | Est. Effort | Notes |
|----|---------|-------------|-------|
| PR-1: P3 | 1 | 2d | Creates admin_config_helper.py |
| PR-2: P4 | 1 | 3.5d | Largest service refactor; defers extraction scripts |
| PR-3: P2 | 1 | 2d | Independent; includes test rewrite |
| PR-4: P1 | 1 | 3d | Most endpoints touched; all in main.py + chunk_knowledge_service.py |
| **Total** | **4** | **~10.5d** | With 2 engineers in parallel on P1+P2 after P3/P4: ~6 calendar days |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| P4 TeachingService refactor breaks existing callers | All entry points accept `db: AsyncSession` already (FastAPI Depends pattern) — no interface break |
| P1 DB query on every graph request adds latency | Single grouped aggregate on indexed `(book_slug, is_hidden)` columns — <1ms. Add composite index if query plan shows seq scan |
| P2 mid-language commit changes error recovery semantics | Acceptable: crash mid-language, next restart re-does that language only. No partial-language rows exist (flush then commit) |
| PR review bottleneck with 4 open PRs | Open sequentially after gate passes; unblock next PR while previous is in review |

---

## Key Decisions Requiring Stakeholder Input

1. Confirm `llm_extractor.py` and `graph_builder.py` (offline pipeline tools) are **deferred** from P4 scope. They require architectural work to obtain a db session at entry, which is out of scope for this round.
2. Confirm P2 `dry_run` flag is False in all production call paths before adding the guarded commit.
3. Confirm 4-PR strategy is preferred over a single bundled PR for this round.
