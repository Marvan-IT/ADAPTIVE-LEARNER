# High-Level Design: Risk Hardening Redesign

**Feature slug:** `risk-hardening-redesign`
**Date:** 2026-02-28
**Author:** Solution Architect

---

## 1. Executive Summary

### Feature Name and Purpose
Risk Hardening Redesign is a three-stream release that addresses operational risk accumulated since the Adaptive Real Tutor launch, lowers the mastery threshold to match observed student success patterns, and elevates the entire frontend to Apple/Google-tier visual quality.

### Business Problem Being Solved
Three distinct problems are addressed in a single coordinated release:

- **Stream A (Mastery Threshold):** The current 70-point mastery threshold is too high relative to observed student completion rates; it creates frustration and drop-off. Lowering to 60 aligns with curriculum research for introductory mathematics. The constant is also dangerously hardcoded as a module-level variable inside `teaching_service.py` rather than sourced from `config.py`, making it impossible to tune without a code deployment.

- **Stream B (Risk Hardening):** Eleven tuning constants scattered across `adaptive_engine.py` are defined inline, the wrong OpenAI model is used in `generate_next_card()`, the `load_student_history()` aggregate query has no row cap (unbounded full-table scan risk at scale), `SpacedReview` has no composite uniqueness constraint (duplicate review rows possible under concurrent writes), inserts to `spaced_reviews` have no idempotency guard, and the frontend timer for card signal tracking uses `Date.now()` (wall-clock, monotonic drift risk) instead of `performance.now()`.

- **Stream C (Premium Frontend Redesign):** The current UI is functional but visually generic. It does not meet the quality bar expected by students accustomed to modern learning applications. A comprehensive redesign to an Apple/Google aesthetic will reduce cognitive load, improve emotional engagement, and reduce churn — all without adding new npm dependencies.

### Key Stakeholders
- Product: approve mastery threshold change and score-band semantics
- Backend engineering: implement Streams A and B
- Frontend engineering: implement Stream C
- DevOps: Alembic migration for `SpacedReview` unique constraint + index (flagged separately)

### Scope

**Included:**
- Mastery threshold change from 70 to 60 and migration of constant to `config.py`
- Migration of 11 adaptive constants to `config.py`
- Fix `generate_next_card()` model selection bug
- Cap `load_student_history()` query at 200 rows
- Add `UniqueConstraint` to `SpacedReview` ORM model
- Add `ON CONFLICT DO NOTHING` to `SpacedReview` inserts in `teaching_service.py`
- Replace `Date.now()` with `performance.now()` in `CardLearningView.jsx`
- Full visual redesign of: WelcomePage, ConceptMapPage, CardLearningView, SocraticChat, CompletionView, AppShell
- New `frontend/src/components/ui/` primitive library: Button, Card, Badge, Skeleton, ProgressRing, Toast
- CSS design token extension for semantic surfaces, shadows, radius, motion, skeleton shimmer

**Explicitly Excluded:**
- Changes to API contracts, route paths, or DB column types
- New npm packages
- Backend prompt changes or LLM model upgrades (separate concern)
- Alembic migration file (delegated to devops-engineer agent)
- i18n key additions beyond score-band copy already present in translation files
- Multi-book support or book-slug generalisation

---

## 2. Functional Requirements

| ID | Priority | Requirement |
|----|----------|-------------|
| FR-01 | P0 | Mastery threshold is 60; all comparisons use `config.MASTERY_THRESHOLD` |
| FR-02 | P0 | `teaching_service.py` does not define `MASTERY_THRESHOLD` locally |
| FR-03 | P0 | All 11 adaptive tuning constants live in `config.py` only |
| FR-04 | P0 | `generate_next_card()` calls `_call_llm` with `ADAPTIVE_CARD_MODEL` (gpt-4o-mini) |
| FR-05 | P0 | `load_student_history()` aggregate query carries `.limit(200)` on `CardInteraction` |
| FR-06 | P0 | `SpacedReview` ORM has `UniqueConstraint("student_id","concept_id","review_number")` |
| FR-07 | P0 | `SpacedReview` inserts use `pg_insert().on_conflict_do_nothing()` |
| FR-08 | P0 | `cardStartTimeRef.current` uses `performance.now()` at all 3 sites in `CardLearningView.jsx` |
| FR-09 | P1 | WelcomePage: hero layout, animated language chips, Skeleton loader |
| FR-10 | P1 | ConceptMapPage: slide-in ConceptPanel replaces absolute tooltip; split-panel layout preserved |
| FR-11 | P1 | CardLearningView: pill MCQ buttons, shake-on-wrong animation, segmented ProgressDots, focus-mode, inline hints |
| FR-12 | P1 | SocraticChat: fixed input bar, typing indicator dots, reliable auto-scroll, Enter sends |
| FR-13 | P1 | CompletionView: SVG ProgressRing, CSS confetti, score bands at >=90/>=60/>=40/<40 |
| FR-14 | P1 | AppShell: student name as dropdown popover (student info + logout); simplified nav |
| FR-15 | P2 | New `frontend/src/components/ui/` exports: Button, Card, Badge, Skeleton, ProgressRing, Toast |
| FR-16 | P2 | CSS design tokens extended with `--shadow-*`, `--radius-*`, `--motion-*`, `--shimmer-*` |

---

## 3. Non-Functional Requirements

### Performance
- `load_student_history()` must complete in < 50 ms at P95 on a table with 10,000 `CardInteraction` rows (enforced by 200-row cap + existing index on `student_id`)
- Frontend bundle size must not increase by more than 5 KB gzipped (zero new npm dependencies)
- ProgressRing SVG animation must run at 60 fps on mid-range hardware (CSS-only, no JS RAF loop)
- Confetti animation must not block the main thread; must be CSS `@keyframes` only

### Scalability
- The 200-row history cap means the aggregate query is O(1) with respect to total `CardInteraction` table growth beyond 200 rows per student
- `SpacedReview` unique constraint prevents row explosion under retry storms or duplicate calls

### Availability and Reliability
- `ON CONFLICT DO NOTHING` on `SpacedReview` inserts ensures idempotency; duplicate session completion calls are safe
- Config centralisation means threshold changes require only a config redeploy, not a code deploy

### Security
- No new API surface is introduced; no change to authentication or authorisation
- No secrets or keys added to config

### Maintainability
- All constants in one place (`config.py`) reduces the cognitive load of threshold tuning
- New `components/ui/` primitives reduce JSX duplication across pages
- CSS design tokens follow the existing `var(--color-*)` convention; no inline style proliferation

### Observability
- Existing structured logging in backend is unaffected
- `performance.now()` provides sub-millisecond precision for card timing signals; improves `time_on_card_sec` fidelity in `CardInteraction` records

---

## 4. System Context Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        ADA Platform                             │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Frontend (React 19 + Vite 7)                            │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐ │   │
│  │  │ WelcomePage  │  │ConceptMapPage│  │  LearningPage  │ │   │
│  │  │  [Stream C]  │  │  [Stream C]  │  │  [Stream C]    │ │   │
│  │  └──────────────┘  └──────────────┘  └────────────────┘ │   │
│  │  ┌───────────────────────────────────────────────────┐   │   │
│  │  │  components/ui/  [Stream C — new primitives]      │   │   │
│  │  └───────────────────────────────────────────────────┘   │   │
│  │  CardLearningView.jsx — performance.now() [Stream B]      │   │
│  └──────────────────────────────────────────────────────────┘   │
│            │ Axios (unchanged)                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Backend (FastAPI)                                       │   │
│  │  teaching_service.py — MASTERY_THRESHOLD [Stream A]      │   │
│  │  teaching_service.py — pg_insert().on_conflict [Stream B]│   │
│  │  adaptive_engine.py  — constants + model fix [Stream B]  │   │
│  │  config.py            — all constants [Streams A+B]      │   │
│  └──────────────────────────────────────────────────────────┘   │
│            │ SQLAlchemy async                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  PostgreSQL 15                                           │   │
│  │  spaced_reviews — UniqueConstraint [Stream B]            │   │
│  │  card_interactions — query cap [Stream B]                │   │
│  └──────────────────────────────────────────────────────────┘   │
│            │ AsyncOpenAI                                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  OpenAI API                                              │   │
│  │  gpt-4o-mini: generate_next_card() [Stream B fix]        │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Architectural Style and Patterns

### Selected Style
**Layered monolith (frontend + backend) with targeted surgical changes.** This is not a new system; it is a risk-reduction and quality improvement release on an existing architecture. The design deliberately avoids introducing new services, message queues, or architectural layers.

### Key Patterns Applied

**Config-as-single-source-of-truth** (Streams A + B): All tuning constants centralised in `config.py`. This is already the project convention for paths, model names, and book registry. The threshold and adaptive constants are outliers being corrected.

**Idempotent writes via database-level constraints** (Stream B): `UniqueConstraint` + `ON CONFLICT DO NOTHING` is the standard PostgreSQL upsert idiom. It is preferable to application-level duplicate detection because it survives concurrent requests.

**Design token system** (Stream C): CSS custom properties are already used throughout the project (`var(--color-primary)`, etc.). Stream C extends the token vocabulary rather than replacing it. This is a zero-risk extension pattern.

**Primitive component library** (Stream C): Extracting Button, Card, Badge, etc. into `components/ui/` follows the established project structure where `components/` holds reusable elements. This reduces JSX duplication without changing any state management, routing, or API patterns.

### Trade-offs Considered

| Alternative | Why Rejected |
|-------------|--------------|
| Feature flag for mastery threshold | Unnecessary complexity; threshold is a calibration value, not a user-facing feature toggle |
| Environment variable for MASTERY_THRESHOLD | Already supported by `config.py` pattern via `os.getenv`; the constant should be added there but need not be env-overridable unless product requests it |
| CSS-in-JS (e.g., emotion) for redesign | Would add a new dependency and break the existing Tailwind + CSS custom property system |
| Headless UI / Radix for primitives | Would add npm dependencies; spec explicitly prohibits this |
| Separate releases for each stream | Three changes are tightly coupled: score bands depend on the 60-threshold; frontend redesign is a single coordinated effort |

---

## 6. Technology Stack

All technologies are inherited from the existing project. No new dependencies are added.

| Layer | Technology | Version | Reason for Choice |
|-------|-----------|---------|-------------------|
| Backend framework | FastAPI | 0.128+ | Existing |
| Backend ORM | SQLAlchemy 2.0 async | 2.0 | Existing |
| DB | PostgreSQL 15 | 15 | Existing |
| DB upsert dialect | `sqlalchemy.dialects.postgresql.insert` | bundled with SA | pg-specific `ON CONFLICT` support |
| LLM client | AsyncOpenAI | existing | Existing |
| Frontend framework | React 19 + Vite 7 | 19 / 7 | Existing |
| Styling | Tailwind CSS 4 + CSS custom properties | 4 | Existing |
| Animations | CSS `@keyframes` | — | Zero-dependency; performant |
| Timer precision | `window.performance.now()` | Web API | Already in browser; monotonic |
| Math rendering | KaTeX via remark/rehype | existing | Existing |
| i18n | i18next | 25 | Existing |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-01: Mastery threshold lowered to 60 and moved to config.py

**Decision:** Change `MASTERY_THRESHOLD` from 70 to 60 and define it exclusively in `config.py`. Remove the local constant from `teaching_service.py`.

**Options considered:**
1. Keep at 70, only move to config
2. Lower to 60 and move to config (chosen)
3. Make threshold per-student or per-concept

**Rationale:** Product has determined 60 matches observed student success rates. Option 3 is out of scope for this release. Centralising in `config.py` is a prerequisite for any future env-var override.

**Trade-offs:** Students who previously failed at 68/69 will now be marked as mastered. This is intentional and acceptable.

---

### ADR-02: 200-row cap on load_student_history()

**Decision:** Add `.limit(200)` to the `CardInteraction` aggregate subquery in `load_student_history()`.

**Options considered:**
1. No cap (current state — unbounded)
2. Cap at 200 rows (chosen)
3. Time-window cap (e.g. last 90 days)

**Rationale:** 200 cards represents approximately 20-40 learning sessions, far more than needed for a meaningful personal baseline. A fixed row cap is simpler to reason about and index-friendly. A time-window cap is more complex and could return 0 rows for inactive students. The existing index on `(student_id)` means the 200-row limit will be applied after an efficient index scan.

**Trade-offs:** Extremely active students with > 200 cards will have their baseline computed from their 200 most recent interactions only. This is the desired behaviour (recency weighting).

---

### ADR-03: UniqueConstraint on SpacedReview at the ORM and DB layer

**Decision:** Add `__table_args__ = (UniqueConstraint("student_id", "concept_id", "review_number", name="uq_spaced_review"),)` to the `SpacedReview` ORM model, and use `pg_insert().on_conflict_do_nothing()` for all inserts.

**Options considered:**
1. Application-level check-before-insert (SELECT then INSERT)
2. DB-level UniqueConstraint + ON CONFLICT (chosen)
3. UPSERT with `on_conflict_do_update`

**Rationale:** Check-before-insert has a TOCTOU race condition. Option 3 would silently update `due_at`, which is undesirable if a review schedule was already sent to the student. `DO NOTHING` is the correct semantic: if a schedule row already exists, leave it unchanged.

**Trade-offs:** Alembic migration is required to add the constraint to an existing database. This is flagged to the devops-engineer agent.

---

### ADR-04: ADAPTIVE_CARD_MODEL fixed to use config constant

**Decision:** `generate_next_card()` in `adaptive_engine.py` currently passes `OPENAI_MODEL_MINI` directly via a local import at call time (line 469). The correct approach is to pass the dedicated `ADAPTIVE_CARD_MODEL` constant from config.

**Options considered:**
1. Continue using OPENAI_MODEL_MINI inline import (current — bug)
2. Define ADAPTIVE_CARD_MODEL = OPENAI_MODEL_MINI in config and use it (chosen)
3. Make model a parameter on generate_next_card()

**Rationale:** `ADAPTIVE_CARD_MODEL` and `OPENAI_MODEL_MINI` happen to have the same default value today, but they represent different concerns. Keeping them separate in config allows independent tuning. The bug is that the original code used `OPENAI_MODEL` (gpt-4o) via the `model` parameter default on the function signature — see adaptive_engine.py line 435 — and the inline import of `OPENAI_MODEL_MINI` was a partial fix that is now being formalised.

---

### ADR-05: performance.now() for card timing

**Decision:** Replace all three `Date.now()` calls in `CardLearningView.jsx` signal tracking with `performance.now()`, converting milliseconds to seconds at the collection point.

**Options considered:**
1. Keep `Date.now()` (current)
2. Use `performance.now()` (chosen)
3. Use a server-side timestamp delta

**Rationale:** `performance.now()` is monotonic and not subject to system clock adjustments (NTP slews, DST). Since `time_on_card_sec` is used for adaptive blending comparisons against a baseline, a monotonic source produces cleaner signal. The conversion from milliseconds to seconds is: `(performance.now() - cardStartTimeRef.current) / 1000`.

---

### ADR-06: CSS-only animations for Stream C

**Decision:** All animations (confetti, shake-on-wrong, skeleton shimmer, fade-in) are implemented as CSS `@keyframes`. No JS animation library, no `requestAnimationFrame` loops.

**Options considered:**
1. CSS @keyframes (chosen)
2. Framer Motion
3. React Spring

**Rationale:** Zero new dependencies is a hard constraint from the spec. CSS @keyframes are GPU-composited for `transform` and `opacity` properties and will run at 60 fps without JS involvement. The shake-on-wrong effect requires only a 300ms keyframe on `transform: translateX`.

---

## 8. Risks and Mitigations

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| Alembic migration for UniqueConstraint fails on existing rows with duplicates | High | Low | Pre-migration: run `SELECT student_id, concept_id, review_number, COUNT(*) FROM spaced_reviews GROUP BY 1,2,3 HAVING COUNT(*) > 1` to detect duplicates before applying migration. DevOps resolves duplicates by keeping the earliest row. |
| Lowering threshold to 60 retroactively marks students who scored 60-69 as mastered | Medium | Certain | This is intentional. Product has approved it. No backfill of `student_mastery` is performed for historical sessions — only new completions use the new threshold. |
| Stream C CSS token additions break existing 4 themes | Medium | Low | Extend only; never rename existing tokens. New tokens (`--shadow-*`, `--radius-*`, `--motion-*`) have sensible defaults for all themes. Run visual regression in dev/staging with all 4 themes before merge. |
| `performance.now()` value overflows after ~49 days uptime | Low | Very Low | `performance.now()` returns DOMHighResTimeStamp in ms since navigation start. Cards are completed in seconds/minutes. No overflow risk in practice. |
| 200-row cap causes degraded baseline for very active students | Low | Very Low | 200 cards is approximately 1+ year of daily use. Recency weighting is a feature, not a bug. |
| ConceptPanel slide-in breaks mobile layout on narrow viewports | Medium | Medium | ConceptPanel must be tested at 375px viewport width. Fallback: full-width bottom sheet on mobile (< 640px breakpoint). |
| Duplicate SpacedReview rows exist in production before migration | Medium | Low | Same as first risk above. Detect and clean before migration. |

---

## Key Decisions Requiring Stakeholder Input

1. **Mastery threshold 60 — confirmed by product?** If the threshold is subject to future A/B testing, it should be made env-var overridable: `MASTERY_THRESHOLD = int(os.getenv("MASTERY_THRESHOLD", "60"))`. Confirm whether this level of configurability is required now or deferred.

2. **Score bands for CompletionView redesign:** The spec defines >=90 green, >=60 blue, >=40 amber, <40 red. The existing code uses >=90 green, >=70 primary, >=50 amber, <50 red. Confirm whether the 60 and 40 breakpoints are final and whether i18n copy changes are needed for band labels.

3. **ConceptPanel mobile behaviour:** Should the slide-in panel become a bottom sheet drawer on mobile, or should it overlay the graph on all viewport sizes? This affects the CSS implementation significantly.

4. **AppShell student dropdown — logout placement:** The current "Switch Student" logout button is visible in the nav bar. Moving it into a dropdown popover may reduce discoverability. Confirm whether this UX change is approved before implementation.
