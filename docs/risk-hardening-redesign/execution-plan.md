# Execution Plan: Risk Hardening Redesign

**Feature slug:** `risk-hardening-redesign`
**Date:** 2026-02-28
**Author:** Solution Architect

---

## 1. Work Breakdown Structure (WBS)

### Stream A — Mastery Threshold

| ID | Title | Description | Effort (days) | Dependencies | Component |
|----|-------|-------------|---------------|--------------|-----------|
| A-01 | Add MASTERY_THRESHOLD to config.py | Add `MASTERY_THRESHOLD: int = 60` to the new `── Mastery ──` section in `backend/src/config.py` | 0.25 | — | `config.py` |
| A-02 | Remove local constant from teaching_service.py | Delete `MASTERY_THRESHOLD = 70` (line 30). Add `MASTERY_THRESHOLD` to the `from config import ...` statement. Verify all three usages: `score >= MASTERY_THRESHOLD` in `handle_student_response()` and `if mastered` block | 0.25 | A-01 | `teaching_service.py` |
| A-03 | Update score bands in CompletionView.jsx | Change score thresholds from `>=70` / `>=50` to `>=60` / `>=40` in the `scoreColor` / `scoreConfig` logic | 0.25 | A-01 | `CompletionView.jsx` |
| A-04 | Unit tests for mastery threshold | Write `test_mastery_threshold_is_60`, `test_score_59_not_mastered`, `test_score_60_mastered` | 0.5 | A-01, A-02 | `tests/test_teaching_service.py` |

**Stream A total: 1.25 days**

---

### Stream B — Risk Hardening

| ID | Title | Description | Effort (days) | Dependencies | Component |
|----|-------|-------------|---------------|--------------|-----------|
| B-01 | Add 11 adaptive constants to config.py | Add `ADAPTIVE_CARD_MODEL`, `ADAPTIVE_CARD_CEILING`, `ADAPTIVE_MIN_HISTORY_CARDS`, `ADAPTIVE_ACUTE_HIGH_TIME_RATIO`, `ADAPTIVE_ACUTE_LOW_TIME_RATIO`, `ADAPTIVE_ACUTE_WRONG_RATIO`, `ADAPTIVE_ACUTE_CURRENT_WEIGHT`, `ADAPTIVE_ACUTE_HISTORY_WEIGHT`, `ADAPTIVE_NORMAL_CURRENT_WEIGHT`, `ADAPTIVE_NORMAL_HISTORY_WEIGHT` to `backend/src/config.py` | 0.5 | A-01 (shares config file) | `config.py` |
| B-02 | Refactor build_blended_analytics() to use config | Replace all 5 inline literals (`MIN_HISTORY_CARDS=5`, `2.0`, `0.4`, `3.0`, `0.9/0.1`, `0.6/0.4`) in `adaptive_engine.py:build_blended_analytics()` with config imports | 0.5 | B-01 | `adaptive_engine.py` |
| B-03 | Fix generate_next_card() model selection | Remove `from config import OPENAI_MODEL_MINI` local import at line 445. Replace `OPENAI_MODEL_MINI` at line 469 with `ADAPTIVE_CARD_MODEL` imported at module top-level | 0.25 | B-01 | `adaptive_engine.py` |
| B-04 | Cap load_student_history() at 200 rows | Refactor the aggregate query in `adaptive_engine.py:load_student_history()` to use a subquery with `.limit(200).order_by(completed_at.desc())` before aggregating. Verify `total_cards_completed` is capped at 200 | 0.5 | — | `adaptive_engine.py` |
| B-05 | Add UniqueConstraint to SpacedReview | Add `__table_args__ = (UniqueConstraint("student_id", "concept_id", "review_number", name="uq_spaced_review"),)` to `SpacedReview` class in `backend/src/db/models.py`. Flag to devops-engineer for Alembic migration | 0.25 | — | `db/models.py` |
| B-06 | ON CONFLICT DO NOTHING for SpacedReview inserts | In `teaching_service.py:handle_student_response()`, replace the loop of `db.add(SpacedReview(...))` calls with `pg_insert(SpacedReview).values(...).on_conflict_do_nothing(index_elements=["student_id","concept_id","review_number"])` followed by `await db.execute(stmt)`. Add `from sqlalchemy.dialects.postgresql import insert as pg_insert` import | 0.5 | B-05 | `teaching_service.py` |
| B-07 | Replace Date.now() with performance.now() in CardLearningView.jsx | Replace all 3 occurrences of `Date.now()` with `performance.now()`. Verify: (1) `cardStartTimeRef.current = performance.now()` in `useEffect([currentCardIndex])`, (2) `(performance.now() - cardStartTimeRef.current) / 1000` in `handleNextCard()`. Update the division from `/1000` if already present | 0.25 | — | `CardLearningView.jsx` |
| B-08 | Unit and integration tests for Stream B | Write: `test_adaptive_constants_in_config`, `test_generate_next_card_uses_adaptive_card_model`, `test_load_student_history_capped_at_200`, `test_spaced_review_on_conflict_do_nothing` | 1.0 | B-01 through B-06 | `tests/` |

**Stream B total: 3.75 days**

---

### Stream C — Premium Frontend Redesign

#### C-Phase 1: Foundation (tokens + primitives)

| ID | Title | Description | Effort (days) | Dependencies | Component |
|----|-------|-------------|---------------|--------------|-----------|
| C-01 | Extend CSS design tokens | Add `--shadow-*`, `--radius-*`, `--motion-*`, `--shimmer-*` tokens to `frontend/src/index.css` (or theme file). Include dark mode overrides. Add `@keyframes` for: `ada-shake`, `ada-confetti-fall`, `ada-skeleton-shimmer`, `ada-slide-in-right`, `ada-ring-fill`, `ada-dot-pulse` | 0.5 | — | `index.css` |
| C-02 | Button primitive | `frontend/src/components/ui/Button.jsx`. Props: `variant` (primary/secondary/ghost/danger), `size` (sm/md/lg), `disabled`, `loading` (shows spinner), `icon` (leading Lucide icon), `fullWidth`. Uses CSS custom properties and inline styles to stay in project convention | 0.5 | C-01 | `components/ui/Button.jsx` |
| C-03 | Card primitive | `frontend/src/components/ui/Card.jsx`. Props: `padding`, `shadow` (xs/sm/md/lg), `radius` (sm/md/lg), `header` (ReactNode slot), `className`. Renders a surface container | 0.25 | C-01 | `components/ui/Card.jsx` |
| C-04 | Badge primitive | `frontend/src/components/ui/Badge.jsx`. Props: `variant` (success/primary/warning/danger/neutral), `size` (sm/md). Pill-shaped label using semantic colour tokens | 0.25 | C-01 | `components/ui/Badge.jsx` |
| C-05 | Skeleton primitive | `frontend/src/components/ui/Skeleton.jsx`. Props: `width`, `height`, `rounded`, `className`. Shimmer using `ada-skeleton-shimmer` keyframe and `--shimmer-*` tokens | 0.25 | C-01 | `components/ui/Skeleton.jsx` |
| C-06 | ProgressRing primitive | `frontend/src/components/ui/ProgressRing.jsx`. SVG ring with `stroke-dashoffset` animation via `ada-ring-fill` keyframe. Props: `score` (0-100), `size`, `strokeWidth`, `animate`, `label`. Score-band colour mapping: >=90 success, >=60 primary, >=40 amber, <40 danger | 0.75 | C-01 | `components/ui/ProgressRing.jsx` |
| C-07 | Toast primitive | `frontend/src/components/ui/Toast.jsx`. Props: `message`, `visible`, `onDismiss`, `duration` (default 3000ms). Fixed position top-right, fade-in/out animation. Auto-dismiss via `useEffect` timeout | 0.5 | C-01 | `components/ui/Toast.jsx` |
| C-08 | UI barrel index | `frontend/src/components/ui/index.js`. Exports all 6 primitives | 0.1 | C-02 through C-07 | `components/ui/index.js` |

**C-Phase 1 total: 3.1 days**

#### C-Phase 2: Page Redesigns

| ID | Title | Description | Effort (days) | Dependencies | Component |
|----|-------|-------------|---------------|--------------|-----------|
| C-09 | WelcomePage redesign | Hero layout: large gradient heading, tagline, animated language chip grid. Replace the current card-centred layout with a 2-column hero (left: copy, right: form card) on desktop, single-column on mobile. Use `Skeleton` for loading state. Language chips: 13 language buttons in a responsive 4-col grid with flag emoji, selected = primary fill | 1.0 | C-02, C-03, C-05 | `WelcomePage.jsx` |
| C-10 | ConceptPanel component | New `frontend/src/components/conceptmap/ConceptPanel.jsx`. Slide-in panel with `ada-slide-in-right` animation. Contains: StatusBadge, concept title, chapter/section, style selector grid, interest chips, CTA button. Extracted from the absolute overlay in `ConceptMapPage.jsx` | 0.75 | C-01, C-02, C-04 | `ConceptPanel.jsx` |
| C-11 | ConceptMapPage split-panel | Integrate `ConceptPanel` into `ConceptMapPage` as a third flex column (width: 320px, animates in). Remove the absolute-positioned tooltip div. Update `ConceptTooltip.jsx` to render nothing (deprecated wrapper kept for one release cycle) | 0.5 | C-10 | `ConceptMapPage.jsx` |
| C-12 | CardLearningView redesign | (1) Pill MCQ buttons with `ada-shake` on wrong. (2) Segmented ProgressDots — 4px height bar, pulse on current. (3) Focus-mode: AssistantPanel hidden on card load, slides in after first wrong answer via width transition. (4) Inline hint Toast when assistant updates. (5) Card header: gradient preserved, number bubble redesigned as solid filled circle | 1.5 | C-01, C-05, C-07, B-07 | `CardLearningView.jsx` |
| C-13 | SocraticChat redesign | (1) Flex column layout: header / scroll area / fixed input bar. (2) `TypingIndicator` component (3 bouncing dots). (3) Change `<input>` to `<textarea>` with `rows=1` auto-grow. (4) `onKeyDown` handler: Enter = send, Shift+Enter = newline. (5) `useLayoutEffect` for scroll reliability | 1.0 | C-01 | `SocraticChat.jsx` |
| C-14 | CompletionView redesign | (1) Replace bordered circle with `<ProgressRing score={score} />`. (2) CSS confetti (20 spans, random delays, `ada-confetti-fall`). (3) Score band config updated to 60-threshold. (4) Banner background derived from score band colour. (5) Action buttons use `Button` primitive | 1.0 | C-06, C-02, A-03 | `CompletionView.jsx` |
| C-15 | AppShell student dropdown | Replace centered student name `<span>` with dropdown button. `useState` for open/close. Popover with student info and "Switch Student" button. Close on outside click via `useEffect`. Use `var(--shadow-lg)` for popover elevation | 0.75 | C-01, C-02 | `AppShell.jsx` |

**C-Phase 2 total: 6.5 days**

---

**Grand total estimated effort: 14.6 days**

---

## 2. Phased Delivery Plan

### Phase 1: Foundation (Days 1–2)
**Goal:** All config changes, ORM model change, and CSS token/primitive library complete. No user-visible changes in production.

Tasks in this phase:
- A-01, A-02 (config + service constant migration)
- B-01, B-02, B-03, B-04, B-05 (config + model fix + history cap + UniqueConstraint)
- C-01, C-02, C-03, C-04, C-05, C-06, C-07, C-08 (tokens + all 6 primitives + barrel)

**Acceptance criteria:**
- `from config import MASTERY_THRESHOLD` succeeds and returns 60
- `from config import ADAPTIVE_CARD_MODEL` succeeds and returns `"gpt-4o-mini"`
- All 11 adaptive constants importable from `config`
- `SpacedReview` model has `__table_args__` with `UniqueConstraint`
- All 6 `components/ui/` files exist and render without errors
- CSS keyframes present in `index.css`

### Phase 2: Core Backend Changes (Days 2–3)
**Goal:** Backend risk items fully resolved. SpacedReview idempotency live. History cap live.

Tasks in this phase:
- B-06 (ON CONFLICT DO NOTHING)
- A-04 (mastery threshold unit tests)
- B-08 (all Stream B tests)

**Acceptance criteria:**
- `test_score_60_mastered` passes
- `test_spaced_review_on_conflict_do_nothing` passes (in-memory SQLite or test PostgreSQL)
- `test_load_student_history_capped_at_200` passes
- `test_generate_next_card_uses_adaptive_card_model` passes

DevOps trigger: At end of Phase 2, flag devops-engineer to run `SELECT student_id, concept_id, review_number, COUNT(*) FROM spaced_reviews GROUP BY 1,2,3 HAVING COUNT(*) > 1` on production, resolve any duplicates, and apply the Alembic migration for `uq_spaced_review`.

### Phase 3: Frontend Signal Fix (Day 3)
**Goal:** `performance.now()` fix merged. Low-risk, single-file change.

Tasks in this phase:
- B-07 (performance.now replacement)

**Acceptance criteria:**
- `cardStartTimeRef.current = performance.now()` confirmed in code review
- `timeOnCardSec` in `goToNextCard()` call is computed as `(performance.now() - ...) / 1000`
- No `Date.now()` remaining in `CardLearningView.jsx` signal tracking

### Phase 4: Frontend Redesign (Days 4–8)
**Goal:** All Stream C page redesigns complete.

Tasks in this phase:
- C-09 (WelcomePage)
- C-10, C-11 (ConceptPanel + ConceptMapPage)
- C-12 (CardLearningView)
- C-13 (SocraticChat)
- C-14 (CompletionView)
- C-15 (AppShell)
- A-03 (score bands update — can be done in C-14)

**Acceptance criteria:**
- All 4 themes render correctly on all redesigned pages
- No layout breakage at 375px, 768px, 1440px viewports
- `ada-shake` animation fires on MCQ wrong answer
- Confetti renders on mastered completion
- ProgressRing animates from 0 to score on mount
- Typing indicator dots appear when `loading=true` in SocraticChat
- Enter key submits in SocraticChat; Shift+Enter adds newline
- ConceptPanel slides in/out smoothly on node select/deselect
- AppShell dropdown opens and closes; logout works

### Phase 5: Release (Day 9)
**Goal:** Final review, documentation, merge.

Tasks:
- Visual regression review: all 4 themes, 3 breakpoints
- Code review of all three streams
- Verify Alembic migration applied in staging
- Merge to main
- Post-deploy: verify `mastered: true` for a session scoring 60 in staging
- Post-deploy: verify `spaced_reviews` has no duplicates after two rapid session completions

---

## 3. Dependencies and Critical Path

```
A-01 (config MASTERY_THRESHOLD)
  └─ A-02 (remove local constant)
       └─ A-04 (tests)

A-01 + B-01 (both config.py changes, single file, do together)
  └─ B-02 (build_blended_analytics refactor)
  └─ B-03 (model fix)
  └─ B-06 (ON CONFLICT)
       └─ B-08 (tests)

B-04 (history cap) — independent, no dependencies
B-05 (UniqueConstraint) — prerequisite for B-06 and Alembic migration
B-07 (performance.now) — fully independent frontend-only change

C-01 (CSS tokens) — foundation for all Stream C
  └─ C-02 through C-08 (primitives) — can be parallelised
       └─ C-09 (WelcomePage)
       └─ C-10 → C-11 (ConceptPanel → ConceptMapPage)
       └─ C-12 (CardLearningView) — also depends on B-07
       └─ C-13 (SocraticChat)
       └─ C-14 (CompletionView) — also depends on A-03
       └─ C-15 (AppShell)
```

**Critical Path:**
`A-01/B-01` → `B-05` → `B-06` → `B-08` → devops Alembic migration

The Alembic migration is a **blocking external dependency** on the devops-engineer agent. It must be applied before the `ON CONFLICT DO NOTHING` constraint is effective in production. The `on_conflict_do_nothing()` code is safe to deploy before the migration — it simply has no effect until the constraint exists.

**Parallelisation opportunities:**
- Stream C (frontend) work is entirely parallel with Streams A+B (backend)
- Within Stream B: B-04 (history cap) and B-07 (performance.now) are independent of all other tasks
- Within Stream C primitives (C-02 through C-08): all can be done in parallel by one developer

---

## 4. Definition of Done

### Phase 1 (Foundation)
- [ ] `config.py` contains `MASTERY_THRESHOLD = 60` and all 11 adaptive constants
- [ ] No local `MASTERY_THRESHOLD` in `teaching_service.py`
- [ ] No inline literal constants in `build_blended_analytics()` (`MIN_HISTORY_CARDS`, ratio thresholds, weights)
- [ ] `SpacedReview.__table_args__` contains `UniqueConstraint("student_id","concept_id","review_number")`
- [ ] All 6 `components/ui/` files created and exported via barrel
- [ ] CSS `@keyframes` and token extensions in `index.css`
- [ ] No `console.log` or `print()` statements in any new/modified code
- [ ] All modified files pass existing linting rules

### Phase 2 (Core Backend)
- [ ] `test_score_60_mastered` passes
- [ ] `test_score_59_not_mastered` passes
- [ ] `test_mastery_threshold_from_config` passes
- [ ] `test_adaptive_constants_in_config` passes (all 11 constants)
- [ ] `test_generate_next_card_uses_adaptive_card_model` passes
- [ ] `test_load_student_history_capped_at_200` passes
- [ ] `test_spaced_review_on_conflict_do_nothing` passes
- [ ] DevOps notified of `uq_spaced_review` migration requirement

### Phase 3 (Frontend Signal Fix)
- [ ] Zero occurrences of `Date.now()` in `CardLearningView.jsx` signal tracking refs
- [ ] `performance.now()` confirmed in all 3 locations (start ref, `handleNextCard`, useEffect reset)
- [ ] Confirmed that `time_on_card_sec` is a float in seconds (not milliseconds)

### Phase 4 (Frontend Redesign)
- [ ] All redesigned pages render in all 4 themes: default, pirate, astronaut, gamer
- [ ] No Tailwind class references to hardcoded colours (`text-blue-500`, etc.) — all uses of semantic CSS vars
- [ ] No inline styles that hardcode colours which should come from design tokens
- [ ] `ada-shake` animation visible on MCQ wrong answer (manual test)
- [ ] Confetti animation visible on mastered completion (manual test)
- [ ] ProgressRing animates correctly from 0 to score (manual test)
- [ ] Typing indicator visible during SocraticChat loading (manual test)
- [ ] Enter sends message in SocraticChat; Shift+Enter creates newline (manual test)
- [ ] ConceptPanel slide-in/out at 375px, 768px, 1440px (manual test)
- [ ] AppShell dropdown opens/closes; closing on outside click works (manual test)
- [ ] No `ConceptTooltip` rendering in production path (deprecated, renders null)
- [ ] No new npm packages added to `package.json`
- [ ] `npm run build` exits with code 0 (no TypeScript/lint errors — project uses JSX, so lint only)

### Phase 5 (Release)
- [ ] Code review approved by at least one other developer for each stream
- [ ] Alembic migration `uq_spaced_review` applied to staging and verified
- [ ] Staging smoke test: create student, start lesson, complete at score 60 → `mastered: true`
- [ ] Staging smoke test: complete same session twice → `spaced_reviews` has exactly 5 rows per session
- [ ] No regressions in existing comprehensive-tester suite (all tests green)
- [ ] `MEMORY.md` updated with new constants and design decisions

---

## 5. Rollout Strategy

### Deployment Approach
**Direct deploy to main branch** (no feature flag required).

Rationale:
- Streams A and B are backend-only risk mitigations. There is no partial state — either the fix is deployed or it is not. Feature flags add complexity without benefit here.
- Stream C is additive visual change. If the redesign has issues, a rollback reverts the entire visual change cleanly.
- The mastery threshold change (60 vs 70) is intentional and product-approved. No gradual rollout is needed.

The exception is the Alembic migration: it must be applied **after** the application code is deployed (the ORM change is additive; the migration adds the constraint). Deploy order:
1. Deploy application code (Streams A, B, C)
2. Apply Alembic migration `uq_spaced_review`

### Rollback Plan
If a critical issue is discovered post-deploy:

1. **Stream A (threshold):** Revert `config.py` to `MASTERY_THRESHOLD = 70`. This requires a single-line config change and redeploy. No data migration needed — `student_mastery` rows written at score 60-69 remain and are valid.

2. **Stream B (risk hardening):** Revert `adaptive_engine.py`, `teaching_service.py`, `db/models.py` to pre-release state. If the Alembic migration was already applied, **do not roll back the migration** — the `UniqueConstraint` is safe to keep. `ON CONFLICT DO NOTHING` is safe with or without the constraint.

3. **Stream C (redesign):** Full `frontend/` revert. Visual changes only; no data is affected.

### Monitoring and Alerting for Launch
The following should be watched for 24 hours post-deploy:

| Signal | How to Monitor | Threshold for Action |
|--------|----------------|---------------------|
| Session completion rate (mastered=true) | Log query on `teaching_sessions.concept_mastered = true` | Significant increase expected; spike > 3x baseline warrants investigation |
| `spaced_reviews` row count per student | SQL: `SELECT COUNT(*) FROM spaced_reviews GROUP BY student_id` | Should not exceed 5 × number of mastered concepts per student |
| `generate_next_card` LLM cost | OpenAI usage dashboard (model = gpt-4o-mini confirmed) | No cost increase expected; may decrease if model was previously gpt-4o |
| `load_student_history` query latency | Backend logs (structured log line) | P95 should be < 50ms; alert if > 200ms |
| Frontend JS errors | Browser console / PostHog error tracking | Any new error type introduced by redesign warrants investigation |

### Post-Launch Validation Steps

1. Immediately post-deploy:
   - Confirm `config.MASTERY_THRESHOLD == 60` via a `python -c "from src.config import MASTERY_THRESHOLD; print(MASTERY_THRESHOLD)"` health check in the deployment pipeline
   - Confirm `ADAPTIVE_CARD_MODEL` is `gpt-4o-mini` in the first `generate_next_card` log line
   - Open the app in all 4 themes and verify no visual regressions on WelcomePage and ConceptMapPage

2. 1 hour post-deploy:
   - Query: `SELECT concept_mastered, COUNT(*) FROM teaching_sessions WHERE completed_at > now() - interval '1 hour' GROUP BY concept_mastered` — expect higher mastered count than historical baseline

3. 24 hours post-deploy:
   - Confirm `uq_spaced_review` constraint exists: `SELECT constraint_name FROM information_schema.table_constraints WHERE table_name='spaced_reviews'`
   - Confirm no `spaced_reviews` duplicates: `SELECT student_id, concept_id, review_number, COUNT(*) FROM spaced_reviews GROUP BY 1,2,3 HAVING COUNT(*) > 1` — expect 0 rows

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 1 — Foundation | Config constants (A+B), ORM UniqueConstraint, CSS tokens, all 6 UI primitives | 3.35 days | 1 backend dev + 1 frontend dev (parallel) |
| Phase 2 — Core Backend | ON CONFLICT insert, all backend tests | 1.5 days | 1 backend dev |
| Phase 3 — Frontend Signal Fix | performance.now() replacement (3 sites) | 0.25 days | 1 frontend dev |
| Phase 4 — Frontend Redesign | 6 page/component redesigns using primitives | 6.5 days | 1 frontend dev |
| Phase 5 — Release | Visual QA, code review, staging verification | 3 days | 1 frontend dev + 1 backend dev + 1 QA |
| **Total** | | **~14.6 days** | **2 engineers** |

Note: Phases 1, 2, and 3 (backend) can be executed in parallel with Phases 1 and 4 (frontend). Realistic wall-clock time with two engineers working in parallel is approximately 8–9 working days.

---

## 7. External Delegation Checklist

The following items are **not** in scope for the backend-developer or frontend-developer agents and must be actioned separately:

| Item | Delegated To | When Needed |
|------|-------------|-------------|
| Alembic migration: add `uq_spaced_review` UniqueConstraint + composite index to `spaced_reviews` table | devops-engineer | After Phase 2 backend deploy; before Phase 5 release |
| Pre-migration duplicate row detection: `SELECT student_id, concept_id, review_number, COUNT(*) FROM spaced_reviews GROUP BY 1,2,3 HAVING COUNT(*) > 1` and cleanup | devops-engineer | Before Alembic migration |
| Add `MASTERY_THRESHOLD` and `ADAPTIVE_CARD_MODEL` to `.env.example` (if env-var override is approved by product) | devops-engineer | Phase 1, if env-var override is approved |

---

## Key Decisions Requiring Stakeholder Input

1. **Env-var override for MASTERY_THRESHOLD:** Should the threshold be tunable via environment variable without a code deploy (`MASTERY_THRESHOLD = int(os.getenv("MASTERY_THRESHOLD", "60"))`)? If yes, add to Phase 1 scope and `.env.example` in Phase 5.

2. **Retroactive mastery backfill:** Students who scored 60-69 in previous sessions are not retroactively marked as mastered by this release. If product wants a backfill, a one-time migration script is required. This is out of scope for the current plan unless explicitly approved.

3. **ConceptTooltip deprecation timeline:** The plan marks `ConceptTooltip.jsx` as deprecated (renders null) in this release. Confirm whether it should be deleted immediately or retained for one release cycle.

4. **Frontend test framework:** The project currently has no frontend test runner (no Vitest per CLAUDE.md technical debt). The `performance.now()` change and ProgressRing behaviour cannot be automatically verified without a test framework. If the devops-engineer sets up Vitest in parallel (recommended), add unit tests for `CardLearningView` time calculation and `ProgressRing` offset computation to Phase 3 and Phase 4 scope respectively.
