# High-Level Design: Exam Gate

**Feature slug:** `exam-gate`
**Date:** 2026-04-03
**Status:** Ready for implementation

---

## 1. Executive Summary

### Feature name and purpose
The Exam Gate is the final evaluation step that every student must pass before a concept is marked mastered. It presents a set of open-ended, typed-answer questions — one per teaching chunk — that are evaluated by the LLM. A pass awards `StudentMastery`; a fail routes the student back through targeted or full-redo remediation.

### Business problem being solved
Three distinct problems are addressed together because they share the same files and must ship as a single coherent change:

| # | Problem | Impact |
|---|---------|--------|
| 1 | **Exam gate missing from frontend** | The backend has complete `/exam/start`, `/exam/submit`, and `/exam/retry` endpoints plus an injected `exercise_gate` chunk, but there is zero frontend UI. Students who complete all study chunks arrive at the `exercise_gate` row with no button that does anything useful. Concept mastery is therefore unreachable through the UI. |
| 2 | **Subsection completion resets on navigation** | The `RESET` reducer case (`SessionContext.jsx:521`) removes `ada_session_{conceptId}` from localStorage unconditionally. This fires on any navigation away from the lesson — including navigating back to the subsection picker after a partial session — erasing progress. |
| 3 | **Images underutilised in per-card generation** | The prompt instruction `"if the card content directly references that image"` is too strict. Cards that teach a topic covered by a chunk image frequently omit the image because the instruction text does not verbatim mention the image. The fix is topic-match distribution instead of verbatim-reference gating. |

### Key stakeholders
- Students (primary users — currently blocked at exam gate)
- Tutor/platform operators (concept mastery data is incomplete without exam passage)
- Backend developer (exam endpoints already exist; no schema changes required)
- Frontend developer (ExamView component + context wiring is the bulk of the work)

### Scope

**Included:**
- `ExamView.jsx` — new component (not yet in codebase)
- `SessionContext.jsx` — 2 new reducer cases, 3 new callbacks, 3 new state fields, exam API wiring
- `sessions.js` — 3 new API wrapper exports
- `LearningPage.jsx` — exam gate row click handling, `EXAM` phase rendering
- `CompletionView.jsx` — swap `reset()` for `dispatch({ type: "SESSION_COMPLETED" })`
- `prompt_builder.py` — one-line string replacement for image instruction
- `teaching_router.py` — mark exam gate `completed` correctly when session is already past exam phase
- Locale keys — `exam.*` namespace in all 13 language files

**Excluded:**
- Backend exam endpoint logic (already correct and tested)
- Alembic migrations (no new columns needed — `exam_phase`, `exam_attempt`, `exam_scores`, `failed_chunk_ids`, `concept_mastered` already exist in `TeachingSession`)
- New DB tables
- Changes to the Socratic check flow (`CHECKING`, `REMEDIATING`, etc.)

---

## 2. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Student can click the `exercise_gate` row in the subsection picker to start the exam when all study chunks are complete | Critical |
| FR-2 | Exam presents one open-ended typed-answer question per teaching chunk, streamed from `POST /exam/start` | Critical |
| FR-3 | Student types answers and submits all at once via `POST /exam/submit` | Critical |
| FR-4 | On pass: concept marked mastered, XP awarded, `CompletionView` rendered | Critical |
| FR-5 | On fail: per-chunk score shown, student offered "Study failed chunks" (targeted) or "Redo all" (full_redo) | Critical |
| FR-6 | After retry choice, `POST /exam/retry` returns the chunks to re-study; student is returned to the subsection picker showing only the retry chunks | High |
| FR-7 | After retry study is complete, student can re-enter the exam via the gate row | High |
| FR-8 | After 3 failed attempts, targeted retry is disabled; only full_redo is offered | High |
| FR-9 | Navigating back to the subsection picker mid-session does NOT erase localStorage progress | High |
| FR-10 | Only a deliberate "start over" action (`CompletionView` reset buttons) clears localStorage | High |
| FR-11 | Chunk images appear on cards whenever topic relevance exists, not only when the card text verbatim mentions the image | Medium |
| FR-12 | The `exercise_gate` row shows a "passed" tick and the exam score once the exam is passed | Medium |

---

## 3. Non-Functional Requirements

| Category | Target |
|----------|--------|
| Latency — exam start | `POST /exam/start` generates N LLM questions sequentially; budget is `N × 3s` on `gpt-4o-mini`. For a typical concept with 4–6 teaching chunks this is 12–18 s. A progress spinner with estimated time is mandatory. |
| Latency — exam submit | `POST /exam/submit` evaluates N answers; budget is `N × 3s`. Spinner required. |
| Availability | Inherits the platform SLA; no new infrastructure. |
| State persistence | `ada_session_{conceptId}` must survive browser navigation events except on deliberate reset. |
| Accessibility | Exam textarea inputs must have visible labels; submit button must be disabled (not hidden) until all fields are filled. |
| i18n | All user-visible strings in `ExamView.jsx` must use `useTranslation()`. Zero hardcoded English strings. 13 locale files must be updated. |
| Security | No XSS risk — exam question text rendered via `textContent`/`{variable}` JSX, not `dangerouslySetInnerHTML`. |
| Maintainability | `ExamView.jsx` must be a single self-contained component with no direct `useSession` side effects beyond the callbacks provided as props. |

---

## 4. System Context Diagram

```
Browser (Student)
  │
  │  1. Click "Section Exam" row
  ▼
LearningPage.jsx  ──  dispatch(START_EXAM)
  │
  │  2. startExam(sessionId, conceptId)
  ▼
POST /api/v2/sessions/{id}/exam/start
  │
  │  3. LLM generates one question per teaching chunk
  │     Questions stored in session.exam_scores JSONB
  │     session.exam_phase = "exam"
  ▼
ExamView.jsx  ←  questions array, pass_threshold
  │
  │  4. Student types answers, clicks Submit
  ▼
POST /api/v2/sessions/{id}/exam/submit
  │
  │  5a. PASS  →  StudentMastery row inserted
  │              session.concept_mastered = True
  │              session.phase = "COMPLETED"
  │  5b. FAIL  →  session.failed_chunk_ids set
  │              session.exam_attempt incremented
  ▼
ExamView.jsx  ←  score, passed, failed_chunks, retry_options
  │
  │  6a. PASS  →  dispatch(EXAM_PASSED)  →  CompletionView
  │  6b. FAIL  →  student picks retry type
  ▼
POST /api/v2/sessions/{id}/exam/retry
  │
  │  7. Returns retry_chunks list
  │     session.exam_phase = "retry_study"
  ▼
dispatch(EXAM_RETRY)
  │
  └──  LearningPage returns to SELECTING_CHUNK
       showing only the retry chunks (or all if full_redo)
       Student re-studies, then gate row becomes clickable again
```

---

## 5. Architectural Style and Patterns

**Selected style:** Incremental UI addition to existing reducer-based state machine.

The existing `SessionContext.jsx` implements a phase-based state machine (`IDLE` → `LOADING` → `SELECTING_CHUNK` → `CARDS` → `CHUNK_QUESTIONS` → `COMPLETED` etc.). The exam gate adds a new phase value `"EXAM"` to this machine.

This is consistent with every prior feature addition to the context (e.g. `REMEDIATING`, `RECHECKING`, `CHUNK_QUESTIONS` were all added the same way). No architectural departure is justified or needed.

**Persistence fix pattern:** Split `RESET` into two cases — a memory-only reset (`RESET`) and a localStorage-clearing reset (`SESSION_COMPLETED`). The existing `CompletionView` reset buttons are the only callers that should clear localStorage. The `RESET` case retains the same `initialState` return but drops the `localStorage.removeItem` side effect.

**Image distribution pattern:** Replace one sentence in the `build_next_card_prompt()` system prompt. No structural change to the prompt builder is required.

**Trade-offs considered:**

| Alternative | Reason rejected |
|-------------|-----------------|
| New ExamContext separate from SessionContext | Over-engineering — exam is one phase of a session, not a separate concern. Adding it to SessionContext (as `CHUNK_QUESTIONS` already was) keeps all session state co-located. |
| Server-side rendered exam results page | React SPA pattern is established; no server rendering is used anywhere in the project. |
| Persist exam state to `ada_session_*` localStorage | Exam state is persisted in `session.exam_scores` JSONB on the backend. Frontend state is ephemeral within the session page. |

---

## 6. Technology Stack

No new technologies are introduced. All changes use the existing stack:

| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend framework | React | 19 |
| State management | `useReducer` + Context | React built-in |
| HTTP client | Axios | 1.13 |
| i18n | i18next | 25 |
| Backend | FastAPI | 0.128+ |
| LLM | OpenAI `gpt-4o-mini` | via AsyncOpenAI client |
| DB | PostgreSQL 15 via SQLAlchemy 2.0 async | existing |

---

## 7. Key Architectural Decisions (ADRs)

### ADR-1: Add `"EXAM"` as a phase value in SessionContext rather than a separate component rendered from `allStudyComplete`

- **Options considered:**
  - (A) Add `"EXAM"` phase to existing state machine
  - (B) Render `ExamView` when `allStudyComplete === true` and no exam result in state
- **Chosen:** (A)
- **Rationale:** The `phase` field is the single source of truth for what LearningPage renders. Option B introduces a second conditional branch orthogonal to `phase`, creating ambiguity when `allStudyComplete` is true but the student has already passed the exam (and is in `COMPLETED`). Option A keeps the state machine clean.

### ADR-2: `SESSION_COMPLETED` replaces the localStorage clear in `RESET`; `RESET` becomes memory-only

- **Options considered:**
  - (A) Keep `RESET` as-is; add a separate `resetAndClearStorage` callback
  - (B) Add `SESSION_COMPLETED` case that clears storage; make `RESET` memory-only
- **Chosen:** (B)
- **Rationale:** Option A requires three call sites in `CompletionView` to be updated to use `resetAndClearStorage`, which is equivalent in effort. Option B is semantically cleaner: `SESSION_COMPLETED` is the event that signals the student is genuinely done with a concept; `RESET` is used for page-level cleanup (navigation away, unmount) and should be non-destructive.

### ADR-3: Exercise gate `completed` field reflects `session.concept_mastered`

- **Current bug:** The injected `exercise_gate` chunk has `completed=False` hardcoded. If the student passed the exam in a prior session visit and reloads the page, the gate will show as incomplete even though `concept_mastered=True` on the session.
- **Fix:** Change the hardcoded `completed=False` to `completed=session.concept_mastered or False` at line 1697 of `teaching_router.py`.
- **Rationale:** This is a one-character backend change; without it, the gate row will never show a "passed" tick on page reload.

### ADR-4: Exam gate is locked until all non-gate, non-optional, non-info study chunks are complete

- **Rationale:** Mirrors the existing locking logic for regular chunks. The frontend `isLocked` derivation in `LearningPage.jsx` must treat `exercise_gate` chunks specially: they are locked until every non-gate, non-optional, non-info chunk in the list has a `chunkProgress` entry.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `POST /exam/start` timeout for concepts with many chunks | Low-Medium | High | Show estimated time to student (`~3s × question count`); backend already has 3-attempt retry with exponential back-off in `_call_llm_json`; frontend LLM_TIMEOUT is 180 s which is sufficient. |
| Student submits partial answers | Low | Medium | Submit button disabled until all textareas have at least 1 non-whitespace character. |
| Race condition: student double-taps Submit | Low | Low | `examLoading` state flag in `ExamView` disables the button after first submission. |
| localStorage key not cleared on genuine completion | Low | Medium | `SESSION_COMPLETED` case explicitly removes the key; `CompletionView` three call sites are all updated. |
| Locale files missing `exam.*` keys causing `t()` to return key strings | Medium | Medium | All 13 locale files are updated in Stage 4; keys fall back to English string default values in `t()` calls as a secondary guard. |
| `exercise_gate` chunk injected multiple times | None | — | Backend already has `already_has_gate` guard at line 1684. |

---

## Key Decisions Requiring Stakeholder Input

1. **Pass threshold display:** `CHUNK_EXAM_PASS_RATE` is defined in `config.py`. Should the UI display the exact threshold as a percentage (e.g., "Pass threshold: 70%") or a qualitative label ("Pass most questions to unlock")? The DLD assumes percentage display.

2. **Retry flow UX:** After a failed exam the student sees "Study failed chunks" (targeted) and "Redo all". Should the failed-chunk headings be listed in the fail result screen, or only in the retry view? The DLD assumes they are listed on the fail screen.

3. **XP for exam pass:** The existing `sendAnswer` callback calls `useAdaptiveStore.getState().awardXP(xp_awarded)` when mastered. The exam submit response does not include an `xp_awarded` field. Confirm whether exam pass should award XP; if yes, backend must add `xp_awarded` to `ExamSubmitResponse` (a one-field schema addition) and call `PATCH /api/v2/students/{id}/progress` in the submit handler.
