# High-Level Design: Adaptive Transparency

**Feature slug:** `adaptive-transparency`
**Date:** 2026-02-28
**Author:** Solution Architect
**Status:** Draft — pending stakeholder review

---

## 1. Executive Summary

### Feature Name and Purpose

Adaptive Transparency is a dual-group feature release for the ADA adaptive learning platform. It delivers two cohesive improvements in a single release cycle:

- **Group A — Premium Frontend Redesign:** A visual and interaction-quality uplift across all existing screens. The full specification resides in `docs/risk-hardening-redesign/DLD.md §9.1–§9.8` and is consumed without modification by the frontend-developer. This HLD records the group's scope and integration points only.

- **Group B — Adaptive Transparency:** A set of six new features that expose the adaptive engine's real-time reasoning to students in an actionable, trust-building way. Students see why the system is adapting, what their learning signals look like, and can influence difficulty directly.

### Business Problem Being Solved

The adaptive card loop (already implemented) silently adjusts card difficulty and type based on behavioral signals. This invisibility creates two problems:

1. Students do not understand why content changes — leading to confusion and reduced trust in the AI tutor.
2. Students have no mechanism to override an incorrect adaptation (e.g., when the system misreads a distraction as struggle).

Group B solves both problems by surfacing the adaptive engine's state in real time and providing explicit difficulty control.

### Key Stakeholders

| Role | Interest |
|------|----------|
| Students | Understand and trust the adaptive experience |
| Product | Feature differentiation and engagement metrics |
| Backend Developer | API additions, schema changes, prompt changes |
| Frontend Developer | Two groups of UI work with clear boundaries |
| Comprehensive Tester | Coverage of new endpoints and component behaviour |

### Scope

**Included:**
- Group A: All eight frontend redesign components as specified in `docs/risk-hardening-redesign/DLD.md §9.1–§9.8`
- Group B: Live Signal Tracker, Student History Page, Difficulty Badge, Explicit Difficulty Control, Mastery Readiness Bar, Wrong-Option Pattern Analysis, Session Arc Sparkline

**Explicitly excluded:**
- Group A backend changes (those are the risk-hardening-redesign backend streams A and B, already designed separately)
- Deployment pipeline changes — local dev only
- New database migrations — no new ORM columns needed (all `CardInteraction` columns already exist; `CardBehaviorSignals` is Pydantic-only)
- Multi-book support for history page — displays data from all books but no per-book filtering UI in v1

---

## 2. Functional Requirements

### Group A — Premium Frontend Redesign

All requirements are specified in `docs/risk-hardening-redesign/DLD.md §9.1–§9.8`. The frontend-developer consumes that document directly. This HLD records only the top-level user stories for traceability.

| ID | User Story | Priority |
|----|-----------|----------|
| A-1 | As a student, I see a polished card learning experience with pill-shaped MCQ buttons, shake animation on wrong answers, and a segmented progress bar | P0 |
| A-2 | As a student, the AI assistant panel slides in progressively — it does not occupy space until I answer my first card | P0 |
| A-3 | As a student, I see a ProgressRing animation and themed confetti when I complete a session | P0 |
| A-4 | As a student, the Socratic chat has a fixed input bar that never scrolls away | P0 |
| A-5 | As a student, I can click my name in the nav bar to see my profile details and switch students | P1 |
| A-6 | As a student, the concept map shows a slide-in panel rather than a tooltip when I click a node | P1 |
| A-7 | As a student, loading states show shimmer placeholders instead of blank screens | P1 |
| A-8 | As a student, the welcome page has a more compelling hero section | P2 |

### Group B — Adaptive Transparency

| ID | User Story | Priority |
|----|-----------|----------|
| B-1 | As a student, I can see my live behavioral signals (time on card, wrong attempts, hints used, idle triggers) updating in real time while I work through a card | P0 |
| B-2 | As a student, I can see my current learning profile classification (speed, comprehension, engagement) and confidence score after each card advances | P0 |
| B-3 | As a student, each card header shows a difficulty badge (1–5 stars) so I understand the challenge level at a glance | P0 |
| B-4 | As a student, I can click "Too Easy" or "Too Hard" to explicitly bias what the system generates next | P0 |
| B-5 | As a student, I see a "Readiness for Quiz" bar that reflects my current confidence score (0–100%) | P1 |
| B-6 | As a student, I can visit /history to see a table of all my card interactions across sessions | P1 |
| B-7 | As a student, on the history page I can see a session arc sparkline — an inline SVG showing my time-per-card within a session | P1 |
| B-8 | As the system, when a student selects the same wrong option 3 or more times on a concept, that pattern is fed into the next card's LLM prompt so the generated card addresses the misconception directly | P0 |

---

## 3. Non-Functional Requirements

### Performance

| Requirement | Target |
|-------------|--------|
| `GET /api/v2/students/{id}/card-history` p95 latency | < 200ms for limit=50 (indexed query on `student_id`) |
| Live Signal Tracker rendering | Zero additional re-renders — signals tracked via `useRef` not state |
| Sparkline SVG rendering | Client-side inline SVG; no network request; < 2ms render |
| Difficulty bias overhead per card generation | 0ms — bias is a string field on the existing `CardBehaviorSignals` Pydantic model |

### Scalability

Current load: single-user local dev. The card-history endpoint query is O(limit) with a `student_id` index already provided by the foreign key. No new indices are required beyond what exist.

### Availability and Reliability

- Same availability target as the rest of the API (local dev: best-effort)
- No new external dependencies introduced
- Wrong-option pattern analysis is a read-only query on `CardInteraction`; if it fails, the next card is generated without the pattern context (graceful degradation)

### Security and Compliance

- Card history endpoint scoped to `student_id` path parameter — no cross-student data leakage is possible given the WHERE clause
- `difficulty_bias` is a server-validated `Literal["TOO_EASY", "TOO_HARD"] | None` — invalid values rejected by Pydantic at the boundary
- No new secrets or API keys required

### Maintainability and Observability

- All new constants added to `config.py` — no magic numbers in service or router files
- New query in teaching router follows the existing SQLAlchemy async pattern
- Frontend components follow existing functional component + Tailwind convention
- All new backend logic has structured log entries following the `key=value` pattern established in `adaptive_engine.py`

---

## 4. System Context Diagram

```
                         ┌─────────────────────────────────────────────┐
                         │               ADA Frontend (React 19)        │
                         │                                              │
                         │  ┌──────────────────────────────────────┐   │
                         │  │  CardLearningView                    │   │
                         │  │  ┌─────────────────────────────────┐ │   │
                         │  │  │ AdaptiveSignalTracker (NEW)      │ │   │
                         │  │  │ - Live signals via useRef        │ │   │
                         │  │  │ - Engagement emoji               │ │   │
                         │  │  │ - LearningProfile display        │ │   │
                         │  │  └─────────────────────────────────┘ │   │
                         │  │  ┌─────────────────────────────────┐ │   │
                         │  │  │ Difficulty Badge (NEW)           │ │   │
                         │  │  │ - Stars from card.difficulty     │ │   │
                         │  │  └─────────────────────────────────┘ │   │
                         │  │  ┌─────────────────────────────────┐ │   │
                         │  │  │ "Too Easy" / "Too Hard" (NEW)    │ │   │
                         │  │  │ - Sets difficultyBias in state   │ │   │
                         │  │  │ - Sent with next card signals    │ │   │
                         │  │  └─────────────────────────────────┘ │   │
                         │  │  ┌─────────────────────────────────┐ │   │
                         │  │  │ Mastery Readiness Bar (NEW)      │ │   │
                         │  │  │ - confidence_score from profile  │ │   │
                         │  │  └─────────────────────────────────┘ │   │
                         │  └──────────────────────────────────────┘   │
                         │                                              │
                         │  ┌──────────────────────────────────────┐   │
                         │  │  StudentHistoryPage /history (NEW)   │   │
                         │  │  - Interaction table                 │   │
                         │  │  - Session arc sparkline SVG         │   │
                         │  └──────────────────────────────────────┘   │
                         └────────────┬────────────────────────────────┘
                                      │  HTTP / Axios
                         ┌────────────▼────────────────────────────────┐
                         │            FastAPI Backend                   │
                         │                                              │
                         │  teaching_router.py (/api/v2)               │
                         │  ┌──────────────────────────────────────┐   │
                         │  │ GET /students/{id}/card-history (NEW) │   │
                         │  │ POST /sessions/{id}/complete-card     │   │
                         │  │  - difficulty_bias now accepted       │   │
                         │  │  - wrong-option pattern query added   │   │
                         │  └──────────────────────────────────────┘   │
                         │                                              │
                         │  adaptive_engine.py                         │
                         │  ┌──────────────────────────────────────┐   │
                         │  │ generate_next_card()                  │   │
                         │  │  - difficulty_bias → overrides        │   │
                         │  │    recommended_next_step              │   │
                         │  │  - wrong_option_pattern → injected    │   │
                         │  │    into build_next_card_prompt()      │   │
                         │  └──────────────────────────────────────┘   │
                         │                                              │
                         │  prompt_builder.py                          │
                         │  ┌──────────────────────────────────────┐   │
                         │  │ build_next_card_prompt()              │   │
                         │  │  - accepts wrong_option_pattern       │   │
                         │  │  - accepts difficulty_bias            │   │
                         │  └──────────────────────────────────────┘   │
                         └────────────┬────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                  │
          ┌─────────▼──────┐  ┌──────▼──────┐  ┌──────▼──────────┐
          │  PostgreSQL 15  │  │  ChromaDB   │  │   OpenAI API    │
          │  card_inter-    │  │  (knowledge │  │   gpt-4o-mini   │
          │  actions table  │  │   service)  │  │   (card gen)    │
          └────────────────┘  └─────────────┘  └─────────────────┘
```

---

## 5. Architectural Style and Patterns

### Selected Style

**Incremental layered enhancement** — all new Group B features are additive. No existing contracts are broken. The backend adds one new endpoint and enriches one existing endpoint. The frontend adds new components within the existing structure.

### Key Pattern Decisions

| Pattern | Application | Justification |
|---------|-------------|---------------|
| `useRef` for live signals | Signal Tracker reads `cardStartTimeRef`, `wrongAttemptsRef`, `hintsUsedRef`, `idleTriggersRef` from `CardLearningView` | Zero re-render cost; signals already exist as refs in the codebase |
| Pure Pydantic field addition | `difficulty_bias: Literal["TOO_EASY", "TOO_HARD"] | None = None` appended to `CardBehaviorSignals` | No migration, no ORM change, backward compatible (defaults to None) |
| Read-only aggregation endpoint | `GET /api/v2/students/{id}/card-history` | Follows existing `/mastery` and `/review-due` GET pattern in teaching_router.py |
| Inline SVG sparkline | Session arc on history page | No chart library dependency; data is simple (N floats); SVG is 100% accessible and printable |
| Wrong-option frequency query | DB aggregate on `selected_wrong_option` WHERE concept | Stateless per-request query; no new table or cached state needed |

### Alternatives Considered

| Alternative | Reason Rejected |
|-------------|----------------|
| WebSocket for live signals | Signals are already tracked client-side via refs; real-time push from backend is unnecessary and would add infrastructure complexity |
| State (useState) for Signal Tracker | Would cause re-renders on every timer tick; refs are the correct React primitive for non-display values |
| Separate analytics service for history | Premature separation; the data is already in PostgreSQL and the existing router pattern handles it cleanly |
| Chart.js / Recharts for sparkline | Heavy dependency for a 20-point sparkline; inline SVG requires zero additional packages |

---

## 6. Technology Stack

All choices align with the existing project stack. No new dependencies are introduced.

| Layer | Technology | Notes |
|-------|-----------|-------|
| Backend framework | FastAPI 0.128+ async | Existing; new endpoint follows router pattern |
| ORM | SQLAlchemy 2.0 async | Existing; new query uses existing `CardInteraction` model |
| Database | PostgreSQL 15 | Existing; `card_interactions.student_id` FK index already present |
| Schema validation | Pydantic v2 | Existing; `CardBehaviorSignals` extended with one optional field |
| LLM | OpenAI `gpt-4o-mini` via `ADAPTIVE_CARD_MODEL` | Existing; `build_next_card_prompt()` extended with two optional arguments |
| Frontend framework | React 19 + Vite 7 | Existing |
| Styling | Tailwind CSS 4 | Existing |
| SVG | Inline JSX SVG | No library; see §5 |
| State management | React Context + useReducer | Existing `SessionContext` extended with three new state fields |
| HTTP client | Axios via `frontend/src/api/students.js` | New `getCardHistory()` function added to existing file |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: No new ORM models or Alembic migration for Group B

**Decision:** All Group B features read from existing `card_interactions` columns. No new columns are added to any ORM model.

**Options considered:**
- A: Add a `difficulty_bias` column to `card_interactions` to persist student preferences across sessions
- B: Keep `difficulty_bias` as a transient per-request signal only (selected)

**Rationale:** The bias is a momentary correction, not a persistent preference. The student's long-term difficulty calibration emerges from the blending algorithm using historical data. Persisting a transient signal would add noise to the baseline. If a persistent preference model is desired in a future version, it belongs in a separate `StudentPreferences` table.

**Trade-off:** The bias is lost when the page refreshes. This is acceptable given the feature's scope as a within-session signal.

---

### ADR-2: Wrong-option pattern threshold is 3, query is per-request

**Decision:** Query `CardInteraction.selected_wrong_option` WHERE `student_id` AND `concept_id`, group by option value, filter count >= 3. This query runs synchronously inside `generate_next_card()` before the LLM call.

**Options considered:**
- A: Cache wrong-option patterns in `load_student_history()` and carry them through (selected in modified form — added as a separate targeted query)
- B: Compute during history load (risks inflating the history dict with per-concept data)
- C: Precompute and store in a separate table

**Rationale:** The query is a simple aggregate over a small result set (at most 8 cards per concept session). A separate query is cleaner than embedding per-concept data in the global history dict, and simpler than a new table.

**Trade-off:** One extra DB round-trip per card generation. Given the subsequent LLM call takes 1–3 seconds, the DB query adds negligible latency.

---

### ADR-3: `difficulty_bias` overrides `recommended_next_step` after LearningProfile classification

**Decision:** After `build_learning_profile()` produces a profile, `generate_next_card()` checks `signals.difficulty_bias` and, if set, overrides `profile.recommended_next_step` before passing the profile to `build_next_card_prompt()`.

**Options considered:**
- A: Pass bias directly to prompt builder and let the LLM interpret it (selected alternative — rejected because prompt injection risk)
- B: Override `recommended_next_step` in the profile before it reaches the prompt (selected)
- C: Add a separate field to `GenerationProfile` for bias

**Rationale:** `recommended_next_step` already controls card difficulty direction in the prompt. Overriding it at the service layer keeps the prompt builder pure and ensures the bias is applied consistently whether or not the profile is passed to other consumers.

**Trade-off:** The override is silent — the profile log will show the overridden value, not the original. The original `adaptation_applied` string returned to the client will include the bias label so the override is traceable.

---

### ADR-4: History page at /history uses a new top-level route

**Decision:** `StudentHistoryPage` is mounted at `/history` in `App.jsx`. It shares `StudentContext` for student identity.

**Options considered:**
- A: Route at `/profile/history` (requires a new `/profile` parent route)
- B: Route at `/history` (flat, simpler, consistent with existing `/map` and `/learn/:conceptId`)

**Rationale:** The existing routing is flat (`/`, `/map`, `/learn/:conceptId`). Adding `/history` follows the same pattern. A `/profile` sub-route would be meaningful if a profile page existed, but it does not.

---

### ADR-5: `learningProfileSummary` and `adaptationApplied` stored in SessionContext state

**Decision:** `SessionContext` gains three new fields: `learningProfileSummary`, `adaptationApplied`, and `difficultyBias`. The first two are populated on `ADAPTIVE_CARD_LOADED`; `difficultyBias` is set/cleared by user action.

**Rationale:** These values are currently PostHog-logged but not stored in state, meaning no component can display them. Storing them in context (not component state) allows `AdaptiveSignalTracker` and `MasteryReadinessBar` to consume them without prop drilling.

**Trade-off:** Slightly larger context value object. Given the values are scalars and one small dict, this is negligible.

---

## 8. Risks and Mitigations

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| Wrong-option query returns no data for new students (no history) | Low | High | Query returns empty list; `build_next_card_prompt()` skips the pattern block when list is empty |
| `difficulty_bias` override produces an unexpected card type | Medium | Low | The override sets `recommended_next_step` to a valid enum value (`CHALLENGE` or `REMEDIATE_PREREQ`); the prompt builder already handles both |
| History page loads slowly for students with thousands of interactions | Low | Low (local dev only) | `LIMIT 50` is enforced at the query level; pagination can be added in v2 |
| Signal Tracker reads stale ref values | Low | Low | Refs are read at display-time via a `requestAnimationFrame` loop (1-second refresh); staleness is bounded at 1 second |
| `AdaptiveLessonCard.difficulty` not forwarded in next-card response | Medium | Low | The `generate_next_card()` response is a free-form dict; the DLD specifies that the `difficulty` key must be included in the normalised card dict |
| Group A and Group B frontend changes conflict on `CardLearningView` | Medium | Medium | Group A redesigns the card frame; Group B adds inner components. Implementation order: Group A first on `CardLearningView`, then Group B inner components are slotted in. The DLD specifies exact insertion points. |

---

## Key Decisions Requiring Stakeholder Input

1. **Signal Tracker visibility:** Should `AdaptiveSignalTracker` be shown by default or collapsed by default? The design below shows it as an always-visible sidebar row in the card learning view. If it is perceived as distracting, a toggle/collapse affordance should be added.

2. **Difficulty bias reset:** Should `difficultyBias` reset to `null` after one card (one-shot correction) or persist until the student changes it again (sticky preference)? The DLD specifies one-shot (reset in `ADAPTIVE_CARD_LOADED` reducer case). Confirm this behaviour is desired.

3. **History page student scoping:** The `/history` page reads `student.id` from `StudentContext`. If no student is selected (fresh load), should the page redirect to `/` or show an empty state? The DLD specifies redirect.

4. **Wrong-option pattern display:** Should the pattern be shown to the student (e.g., "You've selected option B on this concept 3 times — the next card will address this") or remain invisible? The current design keeps it invisible (backend-only). Confirm.

5. **Mastery Readiness Bar placement:** The bar is specified inside `AdaptiveSignalTracker`. Alternatively it could be in the `AssistantPanel`. Confirm placement.
