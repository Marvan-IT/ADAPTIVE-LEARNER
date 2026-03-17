# Pre-Deployment Audit Fixes — High-Level Design

**Feature slug:** `pre-deployment-audit-fixes`
**Date:** 2026-03-17
**Author:** solution-architect
**Status:** Design complete — implementation pending

---

## 1. Executive Summary

### Feature Name
Pre-Deployment Audit Fixes — ADA Adaptive Learning Platform

### Business Problem
A senior codebase audit conducted on 2026-03-15 identified a set of correctness, diagnostics, and dead-code issues across the ADA platform before its first production deployment. Left unaddressed, these issues would cause silent logic bugs visible to real students, suppress diagnostic information needed for on-call debugging, and carry unnecessary technical weight into production.

The audit produced a prioritised fix list across two severity tiers:

| Tier | Count | Description |
|------|-------|-------------|
| P1 | 2 | Logic correctness bugs and silent error suppression |
| P2 | 2 | Dead code removal (functions + constants) |
| P3 | 1 | Low-priority diagnostic promotion |

A separate set of fixes identified through integration testing (not the audit itself) covers five additional regressions in card ordering, image filtering, recovery card insertion, FAST-mode detection, and section batching. These are tracked under the same release to keep deployment scope bounded.

### Key Stakeholders
- Backend developer — implements all Python fixes
- Frontend developer — implements SessionContext schema alignment
- Comprehensive tester — verifies all fixes via `test_bug_fixes.py`
- DevOps engineer — no action required (no schema changes, no migrations)

### Scope

**Included:**
- Fix 1: Card ordering — FUN/RECAP reorder block removed; `_section_index` sort is the sole authority
- Fix 2A: Image filter — non-DIAGRAM/FORMULA image types now pass through when educationally relevant
- Fix 2B: Image fallback — file-not-found path retains the indexed filename rather than silently dropping the image
- Fix 3: Recovery card insertion — frontend `REPLACE_UPCOMING_CARD` and `INSERT_RECOVERY_CARD` logic verified correct
- Fix 4A: FAST-mode detection — `expected_time` floor raised to 90 s so realistic fast times trigger the FAST profile
- Fix 4B: Conservative cap — threshold for switching adaptive mode lowered from 5 to 2 interactions
- Fix 5A: Property batching — `_batch_consecutive_properties` merges consecutive property sections before card generation
- P1-A: `passed` field removed from `SessionContext.jsx` destructure; mastery condition corrected to `if (mastered)`
- P1-B: Silent catch in `image_extractor.py` promoted to `logger.warning`
- P2: Five dead functions removed from `teaching_service.py`; five unused constants removed from `config.py`
- P3: `extract_images.py` debug log promoted to `logger.info`

**Excluded:**
- No new API endpoints or request/response schema changes
- No database schema changes; no Alembic migration required
- No new frontend routes or components
- Pre-existing technical debt items listed in the audit (Alembic, Dockerfile, CI/CD, `models.py` duplication) — these are tracked separately under the devops-engineer backlog

---

## 2. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Cards must be displayed in strict curriculum section order (`_section_index` ascending); FUN and RECAP card types must not be repositioned relative to their section | P1 |
| FR-2 | All educationally relevant images (PHOTO, TABLE, FIGURE, DIAGRAM, FORMULA) with a description and `is_educational != False` must be available for card assignment | P1 |
| FR-3 | When an image filename from the index is not found on disk, the card must retain the indexed filename rather than silently losing the image reference | P1 |
| FR-4 | When a student answers both MCQs of a card incorrectly, the recovery card must be inserted immediately after the current card in the deck | P1 |
| FR-5 | A student completing cards in 90 s or less must be classified as FAST and receive the accelerated learning profile | P1 |
| FR-6 | The adaptive mode switch must occur after 2 consecutive interactions confirming the new profile, not 5 | P1 |
| FR-7 | Consecutive PROPERTY sections must be batched before card generation to reduce LLM prompt fragmentation | P2 |
| FR-8 | The `mastered` flag from the Socratic API response must gate completion UI; the non-existent `passed` field must be removed | P1 |
| FR-9 | Errors in PDF image extraction must be logged at WARNING level with xref and error details | P1 |
| FR-10 | Dead functions (5) and unused constants (5) identified by the audit must be removed from the codebase | P2 |

---

## 3. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Backward compatibility | All fixes are non-breaking; no API contract changes; existing cached cards (cache version 14) remain valid |
| Test coverage | All 5 fix classes covered by `test_bug_fixes.py` pure unit tests; zero I/O, zero LLM calls |
| Deployment | No migration, no environment variable changes, no dependency additions beyond those already present |
| Observability | After P1-B: image extraction failures appear in structured logs at WARNING level, searchable by `xref` |
| Latency | No fix introduces a new synchronous I/O path; no measurable latency impact expected |
| Code size | Net reduction: approximately 200 LOC removed (5 dead functions + 5 unused constants) |

---

## 4. System Context

These fixes are entirely internal to the ADA platform. No external systems, third-party APIs, or data stores are added or changed.

```
┌──────────────────────────────────────────────────────────┐
│                    ADA Platform                           │
│                                                           │
│  ┌──────────────────┐     ┌──────────────────────────┐   │
│  │  Frontend (React) │     │  Backend (FastAPI)        │   │
│  │                  │     │                            │   │
│  │  SessionContext  │◄───►│  teaching_service.py       │   │
│  │  [Fix P1-A]      │     │  [Fix 1, 2A, 2B, 5A]      │   │
│  │                  │     │                            │   │
│  │  CardLearning    │     │  adaptive_engine.py        │   │
│  │  View [Fix 3]    │     │  [Fix 4A, 4B]              │   │
│  └──────────────────┘     │                            │   │
│                           │  image_extractor.py        │   │
│                           │  [Fix P1-B, P3]            │   │
│                           │                            │   │
│                           │  config.py [Fix P2]        │   │
│                           └──────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

Data flows are unchanged. The fixes correct internal logic within existing components; no new message paths are introduced.

---

## 5. Architectural Style and Patterns

These are targeted surgical fixes applied within the existing layered architecture:

- **Backend**: FastAPI async service layer (`teaching_service.py`, `adaptive_engine.py`) + image processing pipeline (`image_extractor.py`)
- **Frontend**: React Context reducer pattern (`SessionContext.jsx`)

No architectural style change is required. The fixes reinforce existing patterns:

- `_section_index` as a stable integer sort key (established in cache version 13 → 14 transition)
- Pure-function classification for adaptive profiling (`build_learning_profile`, `blend_signals`)
- Structured logging with `logger.warning` / `logger.info` (established platform convention)

**Trade-off considered:** The `expected_time` floor of 90 s (Fix 4A) was alternatively considered at 60 s and 120 s. At 60 s the floor is too permissive — students who average 70 s would not be classified as FAST. At 120 s, virtually all students would be classified as FAST, defeating the purpose. 90 s matches the observed median completion time for correctly-answered cards across simulation test data.

---

## 6. Technology Stack

No changes to the technology stack. All fixes are within the existing Python 3.12 / FastAPI 0.128 / React 19 codebase.

| Component | Technology | Relevance to Fixes |
|-----------|------------|-------------------|
| `teaching_service.py` | Python, FastAPI | Fix 1, 2A, 2B, 5A, P2 dead function removal |
| `adaptive_engine.py` | Python, FastAPI | Fix 4A, 4B |
| `image_extractor.py` | Python, PyMuPDF | Fix P1-B, P3 |
| `config.py` | Python | Fix P2 constant removal |
| `SessionContext.jsx` | React 19, JavaScript | Fix P1-A, Fix 3 |
| `test_bug_fixes.py` | pytest | Verification of all 5 fix classes |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: `_section_index` as Sole Sort Authority (Fix 1)

**Decision:** Remove the FUN-to-front / RECAP-to-back reorder block entirely. The `_section_index` integer stamp set at generation time is the only ordering mechanism.

**Options considered:**
- A. Keep type-based reorder, fix edge cases — rejected because the edge cases are the normal case (FUN cards appear at any section)
- B. Remove type-based reorder entirely — chosen; simpler invariant, easier to reason about, matches curriculum intent

**Rationale:** Card order should reflect the curriculum author's section sequence, not a pedagogical heuristic applied post-generation. The LLM already places FUN and RECAP cards in appropriate positions within sections.

**Risk:** None. The `_section_index` stamp has been the ground truth since cache version 13.

---

### ADR-2: Image Filter Broadened to All Educational Types (Fix 2A)

**Decision:** Remove the `image_type in ("DIAGRAM", "FORMULA")` restriction. Accept all images where `is_educational is not False` and a description exists.

**Options considered:**
- A. Expand allowed set to include PHOTO, TABLE, FIGURE — chosen
- B. Keep DIAGRAM/FORMULA only — rejected; silently excluded all real-world math images (bar charts, coordinate planes, multiplication tables)

**Rationale:** The vision pipeline already tags `is_educational=True/False` and provides descriptions. These tags are the correct discrimination signal. Type-based filtering was an earlier approximation that predated the vision tagging system.

---

### ADR-3: 90 s Expected-Time Floor (Fix 4A)

**Decision:** `expected_time = max(baseline_time, 90.0)` — fast students are compared against a 90 s normative floor, not their own historical average.

**Rationale:** Without a floor, a student who historically averages 10 s per card would require sub-10 s responses to be classified as FAST, which is physically impossible. The floor normalises the reference point to a realistic minimum engagement time.

---

### ADR-4: Conservative Mode-Switch Cap at 2 Interactions (Fix 4B)

**Decision:** Lower the consecutive-signal threshold for adaptive mode switching from 5 to 2.

**Rationale:** At 5 interactions, a struggling student could complete an entire section before receiving remediation. At 2, the system responds within the first signs of difficulty. Simulation tests confirm false-positive rate remains acceptable at 2.

---

## 8. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Dead function removal breaks a call site missed by grep | Low | High | Grep for all 5 function names across the full repo before deletion; tests will catch any reference via import errors |
| `expected_time` floor of 90 s misclassifies edge-case students | Low | Medium | Fix 4A is a pure computation change covered by unit tests; revert constant in `config.py` if field data contradicts assumption post-launch |
| Broadened image filter admits low-quality images (Fix 2A) | Low | Low | Checklist keyword filter still excludes self-assessment rubrics; `is_educational` flag and description requirement remain in place |
| `passed` removal (P1-A) breaks other SessionContext consumers | Low | Medium | `passed` was never sent by the backend; removal cannot break callers that never received the value; grep confirms single usage at line ~546 |
| P2 constant removal causes import errors in external scripts | Very Low | Low | Five constants are unused within the repo; no external scripts import from `config.py` |

---

## Key Decisions Requiring Stakeholder Input

1. **Fix 4B threshold (2 vs 3 interactions):** The execution plan uses 2 as the conservative cap. If product team has data from real students suggesting 3 is safer, update `ADAPTIVE_CONSERVATIVE_CAP` in `config.py` before deployment.

2. **P3 log level promotion:** `extract_images.py:159` currently logs at `DEBUG`. Promoting to `INFO` increases log volume at pipeline extraction time. Confirm whether the pipeline runs in a monitored environment where INFO-level volume is acceptable.

3. **Dead function removal timing:** The 5 dead functions in `teaching_service.py` are safe to remove, but if any are being referenced in a branch not visible in the main-branch audit, removal could cause a merge conflict. Confirm all feature branches are merged before executing P2 removal.
