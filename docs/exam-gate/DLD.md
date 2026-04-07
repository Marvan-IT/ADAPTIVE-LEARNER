# Detailed Low-Level Design: Exam Gate

**Feature slug:** `exam-gate`
**Date:** 2026-04-03
**Status:** Ready for implementation

---

## 1. Component Breakdown

| Component | Location | Responsibility | Change type |
|-----------|----------|---------------|-------------|
| `SessionContext.jsx` | `frontend/src/context/` | Holds all session phase state; owns exam API calls as callbacks; exposes `examState`, `startExam`, `submitExam`, `retryExam` | Modify |
| `sessions.js` | `frontend/src/api/` | HTTP wrappers for exam endpoints | Modify (add 3 exports) |
| `ExamView.jsx` | `frontend/src/components/learning/` | Renders exam questions, collects typed answers, shows results and retry options | Create (new file) |
| `LearningPage.jsx` | `frontend/src/pages/` | Routes `phase === "EXAM"` to `ExamView`; locks/unlocks the gate row; handles click on `exercise_gate` | Modify |
| `CompletionView.jsx` | `frontend/src/components/learning/` | 3 `reset()` call sites changed to `dispatch({ type: "SESSION_COMPLETED" })` | Modify |
| `teaching_router.py` | `backend/src/api/` | Fix hardcoded `completed=False` for the injected exam gate chunk | Modify (1 line) |
| `prompt_builder.py` | `backend/src/adaptive/` | Loosen image assignment instruction from verbatim-reference to topic-match | Modify (1 line) |
| `en.json` + 12 locale files | `frontend/src/locales/` | Add `exam.*` namespace | Modify (13 files) |

---

## 2. Data Design

### 2.1 New state fields in `SessionContext` `initialState`

```js
// Add to initialState object (after existing chunkEvalResult field):
examQuestions: [],         // ExamQuestion[] from /exam/start response
examAnswers: {},           // { [question_index]: string } — keyed by question_index
examResult: null,          // ExamSubmitResponse | null
examLoading: false,        // true while /exam/start or /exam/submit in flight
examAttempt: 0,            // mirrors session.exam_attempt from last submit response
```

### 2.2 Backend data (no changes needed)

The following `TeachingSession` columns already exist in `backend/src/db/models.py`:

| Column | Type | Used by exam |
|--------|------|-------------|
| `exam_phase` | `Text \| None` | `"exam"` while in exam, `None` after pass, `"retry_study"` during retry |
| `exam_attempt` | `Integer` | Incremented on each submit; returned in `ExamSubmitResponse.exam_attempt` |
| `exam_scores` | `JSONB` | Stores questions + answers + per-chunk scores |
| `failed_chunk_ids` | `ARRAY(Text)` | Set on fail; used by retry endpoint |
| `concept_mastered` | `Boolean` | Set `True` on pass; used to derive `exercise_gate.completed` |

### 2.3 Pydantic schemas (no changes needed)

All exam schemas are already in `backend/src/api/teaching_schemas.py`:

```
ExamStartRequest  { concept_id: str }
ExamQuestion      { question_index: int, chunk_id: str, chunk_heading: str, question_text: str }
ExamStartResponse { exam_id: str, questions: list[ExamQuestion], total_questions: int, pass_threshold: float }
ExamAnswer        { question_index: int, answer_text: str }
ExamSubmitRequest { answers: list[ExamAnswer] }
PerChunkScore     { chunk_id: str, heading: str, score: float }
ExamSubmitResponse{ score: float, passed: bool, total_correct: int, total_questions: int,
                    per_chunk_scores: dict, failed_chunks: list[PerChunkScore],
                    exam_attempt: int, retry_options: list[str] }
ExamRetryRequest  { retry_type: str, failed_chunk_ids: list[str] }
ExamRetryResponse { retry_chunks: list[ChunkSummary], exam_phase: str, exam_attempt: int }
```

---

## 3. API Design

No new endpoints. Three existing endpoints consumed by the frontend for the first time:

| Endpoint | Method | Request | Response | Rate limit |
|----------|--------|---------|----------|-----------|
| `/api/v2/sessions/{id}/exam/start` | POST | `ExamStartRequest` | `ExamStartResponse` | 10/minute |
| `/api/v2/sessions/{id}/exam/submit` | POST | `ExamSubmitRequest` | `ExamSubmitResponse` | 10/minute |
| `/api/v2/sessions/{id}/exam/retry` | POST | `ExamRetryRequest` | `ExamRetryResponse` | 10/minute |

Authentication: `X-API-Secret` header (existing API key middleware — same as all other endpoints).

---

## 4. Sequence Diagrams

### 4.1 Happy path — exam pass

```
Student                LearningPage          SessionContext          Backend
  │                        │                      │                    │
  │ Click "Section Exam"   │                      │                    │
  │──────────────────────► │                      │                    │
  │                        │ dispatch(START_EXAM) │                    │
  │                        │─────────────────────►│                    │
  │                        │                      │ POST /exam/start   │
  │                        │                      │───────────────────►│
  │                        │                      │   (LLM, ~12-18 s)  │
  │                        │                      │◄───────────────────│
  │                        │  EXAM_STARTED        │                    │
  │                        │◄─────────────────────│                    │
  │ ExamView renders ◄──── │                      │                    │
  │ (questions shown)      │                      │                    │
  │                        │                      │                    │
  │ Type answers           │                      │                    │
  │ Click Submit           │                      │                    │
  │──────────────────────► │                      │                    │
  │                        │ submitExam(answers)  │                    │
  │                        │─────────────────────►│                    │
  │                        │                      │ POST /exam/submit   │
  │                        │                      │───────────────────►│
  │                        │                      │   (LLM, ~12-18 s)  │
  │                        │                      │◄───────────────────│
  │                        │  EXAM_RESULT         │                    │
  │                        │◄─────────────────────│ passed=true        │
  │                        │                      │                    │
  │                        │ dispatch(EXAM_PASSED) │                   │
  │                        │─────────────────────►│                    │
  │                        │                      │ refreshMastery()   │
  │ CompletionView ◄─────  │                      │                    │
```

### 4.2 Fail path — targeted retry

```
Student submits → /exam/submit → passed=false
  │
  │ ExamView shows score + failed_chunks
  │ Student clicks "Study failed chunks"
  │──────────────────────────────────────► retryExam("targeted", failedIds)
  │                                              │
  │                                       POST /exam/retry
  │                                              │
  │                                       dispatch(EXAM_RETRY)
  │                                         payload: { retry_chunks, exam_attempt }
  │                                              │
  │ LearningPage re-renders SELECTING_CHUNK      │
  │ chunkList = retry_chunks (filtered subset)   │
  │ exercise_gate row visible again (unlocked)   │
  │ Student re-studies, clicks gate → START_EXAM │
```

### 4.3 Persistence fix — navigation without reset

```
Student is on SELECTING_CHUNK phase
  │
  │ Clicks browser back / navigates to /map
  │──────────────────────────────────────► useEffect unmount in LearningPage
  │                                              │
  │                                       dispatch({ type: "RESET" })
  │                                              │
  │                                       RESET reducer: returns initialState
  │                                       BUT does NOT remove localStorage key
  │                                              │
  │ Student navigates back to /learn/:conceptId  │
  │──────────────────────────────────────────────►
  │                                         START_LOADING → localStorage key
  │                                         still present → session resumed
```

---

## 5. Detailed Change Specifications

### 5.1 `backend/src/api/teaching_router.py` — line 1697

**Current code (line 1697):**
```python
                completed=False,
```

**Replacement:**
```python
                completed=bool(session.concept_mastered),
```

This requires `session` to be in scope. Confirm: `session` is retrieved via `db.get(TeachingSession, session_id)` at the top of the `get_chunk_list` handler and is therefore in scope at line 1697.

### 5.2 `backend/src/adaptive/prompt_builder.py` — line 485

**Current string (exact):**
```python
        "\"image_url\": string URL from RELEVANT IMAGES block if the card content directly references that image, otherwise null.\n"
```

**Replacement:**
```python
        "\"image_url\": string URL from RELEVANT IMAGES block — assign an image whose topic matches this card's subject matter; distribute all available images across the cards rather than leaving any unused, otherwise null.\n"
```

No other changes to `prompt_builder.py`.

### 5.3 `frontend/src/api/sessions.js` — add 3 exports

Append after the existing `evaluateChunkAnswers` export (line 155):

```js
export const startExam = (sessionId, conceptId) =>
  api.post(
    `/api/v2/sessions/${sessionId}/exam/start`,
    { concept_id: conceptId },
    { timeout: 120_000 }  // LLM generates one question per chunk; allow 2 minutes
  );

export const submitExam = (sessionId, answers) =>
  api.post(
    `/api/v2/sessions/${sessionId}/exam/submit`,
    { answers },
    { timeout: 120_000 }  // LLM evaluates one answer per chunk; allow 2 minutes
  );

export const retryExam = (sessionId, retryType, failedChunkIds = []) =>
  api.post(
    `/api/v2/sessions/${sessionId}/exam/retry`,
    { retry_type: retryType, failed_chunk_ids: failedChunkIds },
  );
```

`answers` is `Array<{ question_index: number, answer_text: string }>` — mirrors `ExamAnswer` Pydantic schema.

### 5.4 `frontend/src/context/SessionContext.jsx` — reducer + callbacks + context value

#### 5.4.1 Import additions (top of file, line 22 area)

```js
import {
  // ... existing imports ...
  startExam as startExamAPI,
  submitExam as submitExamAPI,
  retryExam as retryExamAPI,
} from "../api/sessions";
```

#### 5.4.2 `initialState` additions

```js
// After chunkEvalResult: null, add:
examQuestions: [],
examAnswers: {},
examResult: null,
examLoading: false,
examAttempt: 0,
```

#### 5.4.3 Five new reducer cases

Add the following cases to `sessionReducer`, placed after the `CHUNK_EVAL_RESULT` case (around line 351):

```js
case "EXAM_LOADING":
  return { ...state, examLoading: true, error: null };

case "EXAM_STARTED":
  // payload: ExamStartResponse { exam_id, questions, total_questions, pass_threshold }
  return {
    ...state,
    examLoading: false,
    examQuestions: action.payload.questions,
    examAnswers: {},
    examResult: null,
    phase: "EXAM",
  };

case "EXAM_RESULT":
  // payload: ExamSubmitResponse
  return {
    ...state,
    examLoading: false,
    examResult: action.payload,
    examAttempt: action.payload.exam_attempt,
  };

case "EXAM_PASSED":
  // Exam result already set by EXAM_RESULT; now advance to COMPLETED
  if (state.session?.concept_id) {
    localStorage.removeItem(`ada_session_${state.session.concept_id}`);
  }
  return {
    ...state,
    phase: "COMPLETED",
    mastered: true,
    score: Math.round((state.examResult?.score ?? 0) * 100),
  };

case "EXAM_RETRY":
  // payload: ExamRetryResponse { retry_chunks, exam_phase, exam_attempt }
  return {
    ...state,
    examLoading: false,
    examResult: null,
    examQuestions: [],
    examAnswers: {},
    examAttempt: action.payload.exam_attempt,
    chunkList: action.payload.retry_chunks,
    phase: "SELECTING_CHUNK",
  };
```

#### 5.4.4 Modify `RESET` case (line 521)

**Current:**
```js
case "RESET":
  if (state.session?.concept_id) {
    localStorage.removeItem(`ada_session_${state.session.concept_id}`);
  }
  return initialState;
```

**Replacement:**
```js
case "RESET":
  // Memory-only reset — does NOT clear localStorage.
  // Use SESSION_COMPLETED to clear localStorage on deliberate completion.
  return initialState;

case "SESSION_COMPLETED":
  if (state.session?.concept_id) {
    localStorage.removeItem(`ada_session_${state.session.concept_id}`);
  }
  return initialState;
```

#### 5.4.5 Three new callbacks

Add after `completeChunkItem` callback (around line 901):

```js
const startExam = useCallback(async () => {
  if (!state.session?.id || !state.session?.concept_id) return;
  dispatch({ type: "EXAM_LOADING" });
  try {
    const res = await startExamAPI(state.session.id, state.session.concept_id);
    dispatch({ type: "EXAM_STARTED", payload: res.data });
  } catch (err) {
    dispatch({ type: "ERROR", payload: friendlyError(err) });
  }
}, [state.session]);

const submitExam = useCallback(async (answers) => {
  if (!state.session?.id) return;
  dispatch({ type: "EXAM_LOADING" });
  try {
    const res = await submitExamAPI(state.session.id, answers);
    dispatch({ type: "EXAM_RESULT", payload: res.data });
    if (res.data.passed) {
      trackEvent("exam_passed", {
        score: res.data.score,
        attempt: res.data.exam_attempt,
        concept_id: state.session?.concept_id,
      });
      dispatch({ type: "EXAM_PASSED" });
      await refreshMastery();
    } else {
      trackEvent("exam_failed", {
        score: res.data.score,
        attempt: res.data.exam_attempt,
        failed_chunks: res.data.failed_chunks?.length,
        concept_id: state.session?.concept_id,
      });
    }
  } catch (err) {
    dispatch({ type: "ERROR", payload: friendlyError(err) });
  }
}, [state.session, refreshMastery]);

const retryExam = useCallback(async (retryType, failedChunkIds = []) => {
  if (!state.session?.id) return;
  dispatch({ type: "EXAM_LOADING" });
  try {
    const res = await retryExamAPI(state.session.id, retryType, failedChunkIds);
    dispatch({ type: "EXAM_RETRY", payload: res.data });
  } catch (err) {
    dispatch({ type: "ERROR", payload: friendlyError(err) });
  }
}, [state.session]);
```

#### 5.4.6 Context value additions

Add to the `SessionContext.Provider` value object:

```js
// Exam
startExam,
submitExam,
retryExam,
examQuestions: state.examQuestions,
examAnswers: state.examAnswers,
examResult: state.examResult,
examLoading: state.examLoading,
examAttempt: state.examAttempt,
```

### 5.5 `frontend/src/components/learning/CompletionView.jsx` — 3 call sites

Replace all three `reset()` calls at lines 149, 171, 193 with:

```js
dispatch({ type: "SESSION_COMPLETED" });
```

`dispatch` is already available because `useSession()` returns it. The existing destructure at line 42:

```js
const { score, mastered, conceptTitle, session, reset } = useSession();
```

Must be updated to:

```js
const { score, mastered, conceptTitle, session, dispatch } = useSession();
```

Remove `reset` from the destructure.

### 5.6 `frontend/src/components/learning/ExamView.jsx` — new component

**Full component specification:**

```
Props:
  (none — reads all state from useSession())

Internal state:
  localAnswers: { [question_index]: string }  — controlled textarea values
  submitted: boolean                           — true after submit fires; prevents double-submit display race

Derived values (computed in render, not state):
  allAnswered: boolean  — every question_index in examQuestions has localAnswers[idx].trim().length > 0
  passThreshold: number — not available in current ExamStartResponse; default 0.7 until backend adds it
                          NOTE: pass_threshold IS in ExamStartResponse. Store as examPassThreshold in
                          context initialState. Add to EXAM_STARTED reducer case.
  scorePercent: number  — Math.round(examResult.score * 100)
  passedColor: string   — "var(--color-success)" | "var(--color-danger)"
```

**Render tree (pseudo-JSX):**

```
<div maxWidth=700px margin=auto padding=2rem>

  [Phase: loading (examLoading === true)]
  ─────────────────────────────────────────
  <div style=centred spinner area>
    <LoadingSpinner />
    <p>{t("exam.generating", "Generating exam questions...")} (~{estimatedSeconds}s)</p>
  </div>

  [Phase: questions (examLoading === false AND examResult === null)]
  ─────────────────────────────────────────────────────────────────
  <h2>{t("exam.title", "Section Exam")}</h2>
  <p style=muted>
    {t("exam.instruction", "Answer each question in your own words. You need {{threshold}}% to pass.",
       { threshold: Math.round((examPassThreshold ?? 0.7) * 100) })}
  </p>
  {examAttempt > 0 && (
    <p style=warning-pill>
      {t("exam.attempt", "Attempt {{n}}", { n: examAttempt + 1 })}
    </p>
  )}
  {examQuestions.map((q) => (
    <div key={q.question_index} style=card-border>
      <p style=question-heading>
        <span style=chunk-label>{q.chunk_heading}</span>
        {q.question_text}
      </p>
      <textarea
        aria-label={t("exam.answerLabel", "Your answer for: {{q}}", { q: q.question_text })}
        value={localAnswers[q.question_index] ?? ""}
        onChange={(e) => setLocalAnswers(prev => ({ ...prev, [q.question_index]: e.target.value }))}
        rows={4}
        placeholder={t("exam.placeholder", "Write your answer here...")}
        disabled={examLoading}
        style=full-width-textarea
      />
    </div>
  ))}
  <button
    disabled={!allAnswered || examLoading}
    onClick={handleSubmit}
    style=primary-button-full-width
  >
    {examLoading ? t("common.loading") : t("exam.submit", "Submit Exam")}
  </button>

  [Phase: result — passed (examResult !== null AND examResult.passed === true)]
  ──────────────────────────────────────────────────────────────────────────────
  <div style=success-banner>
    <h2>{t("exam.passed", "Exam Passed!")} — {scorePercent}%</h2>
    <p>{t("exam.passedMsg", "Excellent work. This concept is now mastered.")}</p>
    [CompletionView renders automatically once phase === "COMPLETED"]
  </div>
  NOTE: This state is transient — EXAM_PASSED immediately sets phase to COMPLETED,
  so LearningPage will render CompletionView before the student sees this banner.
  A brief 500 ms delay before dispatching EXAM_PASSED allows the "passed" banner
  to flash. Implement as:
    setTimeout(() => dispatch({ type: "EXAM_PASSED" }), 500)
  inside the submitExam callback in SessionContext when passed === true.

  [Phase: result — failed (examResult !== null AND examResult.passed === false)]
  ──────────────────────────────────────────────────────────────────────────────
  <div style=fail-banner>
    <h2>{t("exam.failed", "Not quite")} — {scorePercent}%</h2>
    <p>
      {t("exam.failedMsg",
         "You need {{threshold}}% to pass. {{correct}} of {{total}} questions correct.",
         { threshold: Math.round(passThreshold * 100),
           correct: examResult.total_correct,
           total: examResult.total_questions })}
    </p>
  </div>

  {examResult.failed_chunks.length > 0 && (
    <div>
      <h3 style=section-heading>{t("exam.reviewNeeded", "Sections to review:")}</h3>
      <ul>
        {examResult.failed_chunks.map(fc => (
          <li key={fc.chunk_id}>{fc.heading}</li>
        ))}
      </ul>
    </div>
  )}

  <div style=button-row>
    {examResult.retry_options.includes("targeted") && (
      <button
        onClick={() => retryExam("targeted", examResult.failed_chunks.map(fc => fc.chunk_id))}
        disabled={examLoading}
        style=secondary-button
      >
        {t("exam.retryTargeted", "Study failed sections")}
      </button>
    )}
    <button
      onClick={() => retryExam("full_redo", [])}
      disabled={examLoading}
      style=primary-button
    >
      {t("exam.retryFull", "Redo all sections")}
    </button>
  </div>
</div>
```

**Event handler:**
```js
const handleSubmit = () => {
  if (!allAnswered || examLoading) return;
  const answers = examQuestions.map(q => ({
    question_index: q.question_index,
    answer_text: (localAnswers[q.question_index] ?? "").trim(),
  }));
  submitExam(answers);
};
```

**Hooks used:**
- `useSession()` — reads `examQuestions`, `examAnswers`, `examResult`, `examLoading`, `examAttempt`, `examPassThreshold`; calls `submitExam`, `retryExam`
- `useTranslation()` — all display strings
- `useState` — `localAnswers` object

### 5.7 `frontend/src/pages/LearningPage.jsx` — exam gate row + phase render

#### 5.7.1 Import additions

```js
import ExamView from "../components/learning/ExamView";
import {
  // existing imports from useSession...
  startExam,
  examLoading,
  examQuestions,
  examResult,
  examAttempt,
} from using useSession() destructure
```

Add to the `useSession()` destructure at the top of `LearningPage`:
```js
const {
  // ...existing...
  startExam,
  examLoading,
  examQuestions,
  examResult,
  examAttempt,
} = useSession();
```

#### 5.7.2 Phase render block — add before the closing `return null`

```js
// ── Exam phase ─────────────────────────────────────────────────────────────
if (phase === "EXAM") {
  return <ExamView />;
}
```

This block must be placed after the `CHUNK_QUESTIONS` render block and before the final fallback.

#### 5.7.3 Gate row locking logic (inside the `SELECTING_CHUNK` render, `visibleChunks.map`)

The existing `isLocked` derivation at line 397:

```js
const isLocked = !isInfoPanel
  && prevRequired.length > 0
  && !(prevRequired[prevRequired.length - 1]?.chunk_id in (chunkProgress || {}));
```

Must be extended for the `exercise_gate` type:

```js
const isGate = chunk.chunk_type === "exercise_gate";

// Gate is locked unless ALL non-gate, non-optional, non-info chunks are complete
const allStudyDone = isGate
  ? visibleChunks
      .filter(c =>
        c.chunk_type !== "exercise_gate" &&
        c.chunk_type !== "learning_objective" &&
        c.is_optional !== true
      )
      .every(c => c.chunk_id in (chunkProgress || {}))
  : false;

const isLocked = isGate
  ? !allStudyDone
  : (!isInfoPanel
      && prevRequired.length > 0
      && !(prevRequired[prevRequired.length - 1]?.chunk_id in (chunkProgress || {})));
```

#### 5.7.4 Gate row `statusIcon` and `statusColor`

After the `isLocked` derivation, add:

```js
const isDone = isGate
  ? chunk.completed === true          // set by backend when concept_mastered=True
  : chunk.chunk_id in (chunkProgress || {});

const statusIcon = isDone
  ? "✓"
  : isLocked
    ? "🔒"
    : isGate
      ? "★"                           // star glyph distinguishes the gate from numbered sections
      : `${idx + 1}`;
```

#### 5.7.5 Gate row `onClick` handler

The existing action button uses `handleStartClick` / `handleStartLearning`. For the gate, override:

```js
onClick={() =>
  isGate
    ? startExam()
    : isInfoPanel
      ? handleStartLearning(chunk.chunk_id)
      : handleStartClick(chunk.chunk_id)
}
```

#### 5.7.6 Gate row button label

```js
{isDone
  ? (isExpanded ? "▲" : t("map.reviewLesson", "Review"))
  : isLocked
    ? null                              // show lock icon only, no button
    : isGate
      ? t("exam.start", "Take Exam")
      : isExpanded
        ? "▲"
        : t("learning.startSubsection", "Start")
}
```

### 5.8 Context `initialState` — add `examPassThreshold`

```js
examPassThreshold: 0.7,   // overwritten by EXAM_STARTED payload
```

### 5.9 `EXAM_STARTED` reducer addition

The `EXAM_STARTED` case stores `pass_threshold` from the API response:

```js
case "EXAM_STARTED":
  return {
    ...state,
    examLoading: false,
    examQuestions: action.payload.questions,
    examPassThreshold: action.payload.pass_threshold,
    examAnswers: {},
    examResult: null,
    phase: "EXAM",
  };
```

Add `examPassThreshold` to `initialState` and to the context value object.

---

## 6. Security Design

| Concern | Approach |
|---------|----------|
| XSS via question text | Exam questions are rendered as plain JSX text nodes (`{q.question_text}`) — never via `dangerouslySetInnerHTML`. |
| XSS via answer textarea | Textarea `value` is a controlled React input; no HTML interpretation. |
| Input length | No explicit max length on frontend textarea; backend uses only first 500 chars of answer text for LLM evaluation (hardcoded in `submit_exam` handler). Optional: add `maxLength={1000}` to textarea. |
| Rate limiting | `/exam/start`, `/exam/submit`, `/exam/retry` all carry `@limiter.limit("10/minute")` in the backend — already in place. |
| Auth | `X-API-Secret` header injected by the Axios `api` client instance — same as all other endpoints. |

---

## 7. Observability Design

### Logging (backend — already implemented in endpoints)
```
[exam-start]  session_id=... total_questions=...
[exam-submit] PASSED: session_id=... score=... attempt=...
[exam-submit] FAILED: session_id=... score=... attempt=... failed_chunks=...
[exam-retry]  session_id=... retry_type=... retry_chunks=... attempt=...
```

### Analytics (frontend — add to SessionContext callbacks)

```js
trackEvent("exam_passed",  { score, attempt, concept_id })
trackEvent("exam_failed",  { score, attempt, failed_chunks: count, concept_id })
trackEvent("exam_started", { total_questions, concept_id })
trackEvent("exam_retry",   { retry_type, concept_id })
```

These use the existing PostHog `trackEvent` wrapper — no new infrastructure.

---

## 8. Error Handling and Resilience

| Error scenario | Frontend handling |
|---------------|------------------|
| `/exam/start` times out (LLM slow) | `friendlyError(err)` → `dispatch({ type: "ERROR" })` → error banner in LearningPage with "Try again" |
| `/exam/submit` times out | Same as above; student answers are held in `localAnswers` state in `ExamView` — they are not lost if the submit fails |
| `passed=false` + retry attempt 3 | `retry_options` from backend will only contain `["full_redo"]` after 3 attempts; frontend renders only the "Redo all sections" button |
| `concept_mastered` race condition on `/exam/submit` | Backend already has `SELECT ... scalar_one_or_none()` guard before `INSERT StudentMastery` — duplicate mastery insert is handled without error |
| Student navigates away during exam | `RESET` no longer clears localStorage. Exam state (`examQuestions`, `examResult`) is ephemeral in memory only; student returns to `SELECTING_CHUNK` on next visit. They can re-click the gate row to start a new exam (a new `/exam/start` call will overwrite the stored questions in `exam_scores` JSONB). |

---

## 9. Locale Keys — Full `exam.*` Namespace

Add the following JSON keys to all 13 locale files. `en.json` carries the canonical English strings; the other 12 files carry translations (or English fallbacks until translated):

```json
"exam.title": "Section Exam",
"exam.instruction": "Answer each question in your own words. You need {{threshold}}% to pass.",
"exam.attempt": "Attempt {{n}}",
"exam.answerLabel": "Your answer for: {{q}}",
"exam.placeholder": "Write your answer here...",
"exam.submit": "Submit Exam",
"exam.generating": "Generating exam questions...",
"exam.evaluating": "Evaluating your answers...",
"exam.passed": "Exam Passed!",
"exam.passedMsg": "Excellent work. This concept is now mastered.",
"exam.failed": "Not quite",
"exam.failedMsg": "You need {{threshold}}% to pass. {{correct}} of {{total}} questions correct.",
"exam.reviewNeeded": "Sections to review:",
"exam.retryTargeted": "Study failed sections",
"exam.retryFull": "Redo all sections",
"exam.start": "Take Exam",
"exam.locked": "Complete all sections first",
"exam.estimatedTime": "~{{seconds}}s"
```

The other 12 locale files (`ar`, `de`, `es`, `fr`, `hi`, `ja`, `ko`, `ml`, `pt`, `si`, `ta`, `zh`) each receive the identical key list. English values are acceptable as stubs; the platform's translation workflow can update them post-launch. The important rule is that the keys exist so `t("exam.foo")` never falls back to displaying the raw key string.

---

## 10. Testing Strategy

### Unit tests (backend — `backend/tests/test_exam_gate.py`)

| Test | Assertion |
|------|-----------|
| `test_exam_gate_completed_field_reflects_mastery` | Mock `session.concept_mastered=True`; call `get_chunk_list`; assert injected gate has `completed=True` |
| `test_exam_gate_completed_field_false_when_not_mastered` | Same with `concept_mastered=False`; assert `completed=False` |
| `test_image_instruction_topic_match` | Call `build_next_card_prompt()` with `content_piece_images=[{"url": "x"}]`; assert the string "directly references" is NOT in the returned system prompt; assert "topic matches" or "distribute" IS present |

### Integration tests (backend)

| Test | Assertion |
|------|-----------|
| `test_start_exam_generates_questions` | POST `/exam/start`; assert `total_questions` > 0; assert `session.exam_phase == "exam"` |
| `test_submit_exam_pass_creates_mastery` | POST `/exam/submit` with all correct answers; assert `passed=True`; assert `StudentMastery` row exists |
| `test_submit_exam_fail_sets_failed_chunks` | POST `/exam/submit` with wrong answers; assert `passed=False`; assert `failed_chunk_ids` set on session |
| `test_retry_targeted_returns_subset` | POST `/exam/retry` with `retry_type="targeted"`; assert returned chunk count < total |
| `test_retry_targeted_blocked_after_3_attempts` | Set `exam_attempt=3` on session; POST with `retry_type="targeted"`; assert 409 |

### Frontend tests (when test framework is added)

| Test | Assertion |
|------|-----------|
| `RESET reducer does not clear localStorage` | Dispatch `RESET` on state with `session.concept_id`; assert `localStorage.removeItem` not called |
| `SESSION_COMPLETED reducer clears localStorage` | Dispatch `SESSION_COMPLETED`; assert `localStorage.removeItem` called with correct key |
| `exam gate locked when not all chunks complete` | Render `LearningPage` with incomplete chunk list; assert gate row has `🔒` icon |
| `exam gate unlocked when all study chunks complete` | Render with all non-gate chunks in `chunkProgress`; assert gate row shows "Take Exam" button |

---

## Key Decisions Requiring Stakeholder Input

1. **`examPassThreshold` display format:** The `pass_threshold` value from `ExamStartResponse` is a float (e.g., `0.7`). The DLD renders it as `Math.round(pass_threshold * 100)` percent. Confirm this matches the intended UX — some platforms prefer fractions shown as "7 of 10 correct".

2. **Delay before `EXAM_PASSED` dispatch:** The DLD specifies a 500 ms `setTimeout` so the student sees a "passed" flash banner before `CompletionView` takes over. Confirm this is acceptable or adjust the delay value.

3. **Textarea `maxLength`:** The DLD recommends `maxLength={1000}`. Backend truncates to 500 chars on evaluation. If the student types more than 1000 chars, the excess is silently dropped. A frontend character counter would improve UX. Accept or specify a different limit.

4. **XP on exam pass:** As noted in HLD ADR-3 — if exam pass should award XP, backend must add `xp_awarded` to `ExamSubmitResponse` and the `EXAM_PASSED` dispatch must call `useAdaptiveStore.getState().awardXP(xp_awarded)`.
