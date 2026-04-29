# Round 5 Fixes — High-Level Design

## Executive Summary

Four independent backend-only patches closing systemic gaps identified after the Stage 7 / Patches A+B deploy. No frontend changes. No schema migrations. Target: deploy as 4 separate PRs from branch `round5-fixes`, each independently revertible.

| Patch | Classification | Criticality |
|-------|---------------|-------------|
| P1 — Hide-section filter on student graph endpoints | Data leakage fix | CRITICAL |
| P2 — Per-language commit in translate_catalog | Idempotency / cost fix | CRITICAL |
| P3 — CHUNK_EXAM_PASS_RATE from live AdminConfig | Config live-read fix | MEDIUM |
| P4 — OPENAI_MODEL from live AdminConfig | Config live-read fix | MEDIUM |

---

## Patch Dependency Map

All four patches are **independent** — no runtime data dependency between them. P3 and P4 share a single new helper module (`admin_config_helper.py`); P4 must be implemented after P3 only because P3 validates the helper pattern first.

```
P1 (graph filter)        ──── independent
P2 (translation commit)  ──── independent
P3 (pass rate config)    ──┐
P4 (model config)        ──┘ share admin_config_helper.py; P3 written first, P4 extends it
```

Recommended commit order: **P3 → P4 → P2 → P1** (smallest change first to validate helper, then independent, then largest).

---

## Shared Concern: AdminConfig Live-Read Pattern

P3 and P4 both move hardcoded constants to live DB reads. The existing pattern in `xp_engine.py` (`_get_config`) is the established model; a new shared module `backend/src/services/admin_config_helper.py` exposes it for use outside the gamification package, avoiding a circular import.

```
AdminConfig table
      │
      ▼
admin_config_helper.get_admin_config(db, key, fallback)   ← new shared helper
admin_config_helper.get_openai_model(db, slot)            ← thin wrapper for P4
      │
      ├── teaching_router.py  (P3: CHUNK_EXAM_PASS_RATE)
      └── teaching_service.py / 6 other files  (P4: OPENAI_MODEL*)
```

**Caching policy:** no memoization. AdminConfig reads are single-column PK lookups — sub-millisecond. Memoization would require cache invalidation logic and introduces the same stale-value problem being fixed.

---

## System Context

```
[Admin UI] ──PATCH /api/admin/config──► [AdminConfig table]
                                               │
                      ┌────────────────────────┘
                      ▼
          admin_config_helper.py (P3, P4)
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
  teaching_router.py        teaching_service.py
  (CHUNK_EXAM_PASS_RATE)    (OPENAI_MODEL, OPENAI_MODEL_MINI)

[concept_chunks table] ──get_hidden_concept_ids()──► [6 student graph endpoints] (P1)

[translate_catalog.py] ──await session.commit() per language──► idempotent restarts (P2)
```

---

## Rollback Strategy

Each patch ships as its own PR and commit. Rollback is:

```bash
git revert <sha>   # creates a new revert commit, no force-push needed
# redeploy backend (docker rebuild + restart, ~2 min)
```

**Safe to revert in any order** — patches do not depend on each other at runtime.

Revert side-effects:
- P1 revert: hidden sections re-appear in student map until next deploy.
- P2 revert: per-language idempotency lost again; translate_catalog wasted work on crash.
- P3 revert: CHUNK_EXAM_PASS_RATE falls back to `config.py` constant (0.50).
- P4 revert: model selection falls back to `config.py` module-load constants.

None of the reverts destroy data or require a migration rollback.

---

## Deploy Constraints

- **Backend-only rebuild + restart.** No frontend deploy, no static asset push.
- **Not safe to deploy while a long-running pipeline is active** (translate_catalog, ingest). Coordinate with any running pipeline jobs before restarting.
- No new environment variables required. Existing `OPENAI_MODEL` / `OPENAI_MODEL_MINI` env vars remain as the ultimate fallback if AdminConfig has no row.

---

## Key Decisions Requiring Stakeholder Input

1. **P1 edge filter policy:** An edge where only one endpoint is hidden is dropped. Is there a case where a hidden concept should still appear as a prerequisite label in the UI (e.g., "mastered but hidden")? Current design: drop both node and all connected edges.
2. **P4 scope:** 7 files are refactored. Extraction scripts (`llm_extractor.py`, `graph_builder.py`) are offline pipeline tools — their model is less critical to live-read. Should those be deferred to avoid scope creep?
3. **P2 dry-run guard:** The new `await session.commit()` is guarded by `if not dry_run:`. Confirm dry-run flag semantics are correct in all call paths before merge.
