# Detailed Low-Level Design — Chunk Classification & Language Feature

**Feature slug:** `chunk-classification-language`
**Date:** 2026-04-01

---

## 1. Component Breakdown

| Component | File | Responsibility |
|-----------|------|----------------|
| Chunk classifier | `backend/src/api/teaching_router.py` | `_get_chunk_type()`, `_is_optional_chunk()` |
| Exam gate injector | `backend/src/api/teaching_router.py` | Deduplicated gate injection in `list_chunks()` |
| Language propagator | `backend/src/api/teaching_router.py` | `update_student_language()` handler extended |
| Heading translator | `backend/src/api/teaching_router.py` | `_translate_summaries_headings()` |
| Exercise prompt builder | `backend/src/api/prompts.py` | `build_exercise_card_system_prompt()`, `build_exercise_recovery_prompt()` |
| Exercise card prompt | `backend/src/adaptive/prompt_builder.py` | `build_exercise_card_prompt()` |
| Exercise recovery engine | `backend/src/adaptive/adaptive_engine.py` | `generate_exercise_recovery_card()` |
| Chunk complete endpoint | `backend/src/api/teaching_router.py` | `POST /sessions/{id}/chunks/{chunk_id}/complete` |
| Schema updates | `backend/src/api/teaching_schemas.py` | `ChunkSummary.is_optional`, `NextCardRequest` exercise fields, `CompleteChunkItemRequest` |
| Session state | `frontend/src/context/SessionContext.jsx` | `LANGUAGE_CHANGED` reducer, `CHUNK_COMPLETE` action |
| Language dispatch | `frontend/src/context/StudentContext.jsx` | calls `dispatch(LANGUAGE_CHANGED)` after language update |
| Complete button | `frontend/src/components/learning/CardLearningView.jsx` | renders Complete button on last card |
| API wrapper | `frontend/src/api/sessions.js` | `completeChunkItem()` function; remove `beginCheck`, `sendResponse` |
| Deleted component | `frontend/src/components/learning/SocraticChat.jsx` | DELETE this file |
| Chunk list rendering | `frontend/src/pages/LearningPage.jsx` | render `learning_objective` + `section_review` as non-interactive panels, `exercise` with badge |

---

## 2. Data Design

### 2.1 No new DB tables or columns required

All state lives in existing columns:
- `TeachingSession.presentation_text` (JSONB text column) — stores card cache; cleared on language change
- `TeachingSession.chunk_progress` (JSONB) — stores per-chunk completion; unaffected by language change
- `TeachingSession.preferred_language` is read at card generation time from the `Student` row (not cached in session)

### 2.2 Updated Pydantic schemas

#### `ChunkSummary` (teaching_schemas.py) — additive change

```python
class ChunkSummary(BaseModel):
    chunk_id:    str
    order_index: int
    heading:     str
    has_images:  bool
    has_mcq:     bool
    chunk_type:  str = "teaching"   # see taxonomy in HLD §6
    is_optional: bool = False        # NEW: True only for Writing Exercises
    completed:   bool = False
    score:       int | None = None
    mode_used:   str | None = None
```

#### `NextCardRequest` (teaching_schemas.py) — additive change

```python
class NextCardRequest(BaseModel):
    card_index:              int   = Field(default=0, ge=0)
    time_on_card_sec:        float = Field(default=0.0, ge=0.0)
    wrong_attempts:          int   = Field(default=0, ge=0)
    hints_used:              int   = Field(default=0, ge=0)
    idle_triggers:           int   = Field(default=0, ge=0)
    # NEW — exercise failure context
    failed_exercise_question: str | None = None   # MCQ question text student got wrong twice
    student_wrong_answer:     str | None = None   # exact text of the wrong option chosen
```

#### `CompleteChunkItemRequest` / `CompleteChunkItemResponse` (teaching_schemas.py) — new

```python
class CompleteChunkItemRequest(BaseModel):
    """Body for POST /sessions/{id}/chunks/{chunk_id}/complete.
    No score required — this is a pure bookmark call."""
    pass  # empty body; chunk_id comes from the URL path parameter

class CompleteChunkItemResponse(BaseModel):
    chunk_id:           str
    next_chunk_id:      str | None  # None if this was the last study chunk
    all_study_complete: bool        # True → unlock exam gate
```

#### Updated `ChunkListResponse`

```python
class ChunkListResponse(BaseModel):
    concept_id:          str
    section_title:       str
    chunks:              list[ChunkSummary]  # now includes is_optional
    current_chunk_index: int
    translated:          bool = False       # NEW: True when headings were just translated
```

### 2.3 Data flow — language change

```
PATCH /students/{id}/language
  │
  ├─ DB: UPDATE students SET preferred_language = :lang WHERE id = :id
  │
  ├─ DB: SELECT teaching_sessions WHERE student_id = :id AND completed_at IS NULL
  │         ORDER BY started_at DESC LIMIT 1
  │
  ├─ DB: SELECT concept_chunks WHERE concept_id = session.concept_id (headings only)
  │
  ├─ LLM: _translate_summaries_headings(headings, lang, client)
  │         → returns list[str] in same order, or original list on error
  │
  ├─ In-memory: build translated ChunkSummary list
  │
  ├─ DB: UPDATE teaching_sessions SET presentation_text = :busted_json WHERE id = :session_id
  │         busted_json = { ...existing, "cache_version": -1, "cards": [] }
  │
  └─ DB: COMMIT
       │
       └─ Return: StudentResponse + { "translated_headings": list[str] }
```

### 2.4 Caching strategy

The `presentation_text` JSONB column acts as the card cache. Setting `cache_version: -1` is the bust signal. The card-generation service checks `cache["cache_version"]` against the current `CACHE_VERSION` constant; a mismatch forces regeneration. No separate cache store is needed.

---

## 3. API Design

### 3.1 New endpoint — Complete chunk item

```
POST /api/v2/sessions/{session_id}/chunks/{chunk_id}/complete
```

**Auth:** `X-API-Key` header (existing `APIKeyMiddleware`)
**Rate limit:** 60/minute (same as list_chunks)

**Path parameters:**
| Name | Type | Description |
|------|------|-------------|
| `session_id` | UUID | Teaching session |
| `chunk_id` | string | UUID of the chunk being completed |

**Request body:** empty (`{}`)

**Response 200:**
```json
{
  "chunk_id": "3fa85f64-...",
  "next_chunk_id": "4ab91c77-...",
  "all_study_complete": false
}
```

**Response 200 (last chunk):**
```json
{
  "chunk_id": "3fa85f64-...",
  "next_chunk_id": null,
  "all_study_complete": true
}
```

**Error responses:**
| Code | Condition |
|------|-----------|
| 404 | Session not found |
| 404 | Chunk not found in this session's concept |
| 409 | Chunk already completed (idempotent — still returns 200 with current state) |
| 500 | DB error |

**Implementation notes:**
- The handler reads `session.chunk_progress` JSONB, adds the `chunk_id` key with `{"completed_at": now().isoformat()}`, then recalculates `all_study_complete` using the same `teaching_ids.issubset(completed_ids)` logic as `complete_chunk`.
- `exercise` chunks with `is_optional=True` are **excluded** from `teaching_ids` in the `all_study_complete` check.
- The handler does **not** generate cards or call the LLM.

### 3.2 Modified endpoint — Language update

```
PATCH /api/v2/students/{student_id}/language
```

**Request body (unchanged):**
```json
{ "language": "es" }
```

**Response 200 (extended):**
```json
{
  "id": "...",
  "display_name": "Ana",
  "preferred_language": "es",
  "translated_headings": ["Usar la notación de suma", "Identificar múltiplos"],
  "session_cache_cleared": true
}
```

The `translated_headings` list is in the same order as the session's current chunk list. Frontend maps by index. If no active session exists, `translated_headings` is `[]` and `session_cache_cleared` is `false`.

### 3.3 Modified endpoint — Next card (exercise path)

```
POST /api/v2/sessions/{session_id}/next-card
```

**Request body (extended, all new fields optional):**
```json
{
  "card_index": 2,
  "time_on_card_sec": 45.0,
  "wrong_attempts": 2,
  "hints_used": 0,
  "idle_triggers": 0,
  "failed_exercise_question": "Which property does 3 + 5 = 5 + 3 demonstrate?",
  "student_wrong_answer": "Associative Property"
}
```

When `failed_exercise_question` is present and `wrong_attempts >= 2`, the handler branches to `generate_exercise_recovery_card()` instead of `generate_per_card()`.

### 3.4 Removed endpoints

| Endpoint | Reason |
|----------|--------|
| `POST /api/v2/sessions/{id}/check` | Socratic check removed |
| `POST /api/v2/sessions/{id}/respond` | Socratic response removed |

Both handlers and their Pydantic schemas (`StudentResponseRequest`, `SocraticResponse`) are deleted. The `beginCheck` and `sendResponse` exports are removed from `sessions.js`.

### 3.5 Versioning

All changes are on existing `/api/v2` paths. The new `/chunks/{chunk_id}/complete` sub-resource follows the existing `chunks` path convention. No version bump needed; all request/response changes are additive (new optional fields).

### 3.6 Error handling conventions

- All errors return `{"detail": "<message>"}` (FastAPI default)
- LLM failures in `_translate_summaries_headings` are caught, logged with `logger.warning`, and the function returns the original untranslated headings — never raises to caller
- Exercise recovery card LLM failure raises `HTTPException(500)` with a user-facing message

---

## 4. Function Signatures

### 4.1 Classifier functions (teaching_router.py)

```python
def _get_chunk_type(heading: str) -> str:
    """
    Classify a chunk heading into one of six types.
    Priority order (first match wins):
      1. section_review  — matches ^\d+\.\d+\s+
      2. learning_objective — contains 'learning objectives' or 'be prepared'
      3. exercise (optional) — contains 'writing exercises'
      4. exercise — contains 'practice makes perfect', 'everyday math', 'mixed practice'
      5. section_review (exam source) — matches ^section \d+ or contains '(exercises)'
      6. teaching — everything else
    Returns: 'learning_objective' | 'section_review' | 'teaching' |
             'exercise' | 'exercise_gate'
    Note: 'exercise_gate' is never returned here; it is only used for
          the synthetic row injected in list_chunks().
    """

def _is_optional_chunk(heading: str) -> bool:
    """
    Returns True only for 'Writing Exercises' headings.
    Used to set ChunkSummary.is_optional and to exclude from all_study_complete.
    """
    return "writing exercises" in heading.lower()
```

### 4.2 Heading translator (teaching_router.py)

```python
async def _translate_summaries_headings(
    headings: list[str],
    language: str,
    client: AsyncOpenAI,
) -> list[str]:
    """
    Translate a list of chunk headings to the target language.
    Uses a single gpt-4o-mini call with all headings in one JSON array.
    Returns translated headings in the same order.
    On any error (timeout, parse failure), returns the original list unchanged.

    Prompt strategy:
      System: "You are a math education translator. Translate each heading in
               the JSON array to {language_name}. Return a JSON array of the
               same length in the same order. Headings only — do not translate
               concept IDs or numbers."
      User:   JSON.dumps(headings)
    Expected response: JSON array of strings.
    Max tokens: 500 (headings are short).
    Timeout: 10 s.
    """
```

### 4.3 Exercise prompt builder (prompts.py)

```python
def build_exercise_card_system_prompt(language: str) -> str:
    """
    System prompt for generating 2–3 MCQ cards from a real textbook exercise chunk.

    Rules embedded in the prompt:
    - Source ONLY from the textbook problem text provided — do not invent problems
    - Each card has exactly one MCQ with 4 options and a correct_index
    - Wrong options must be plausible common mistakes (not obviously wrong)
    - Difficulty: MEDIUM (one question may be HARD if the chunk has advanced problems)
    - Each card includes a brief explanation of why the correct answer is right
    - Cards are numbered sequentially; return as JSON array matching LessonCard schema
    - Language: {language_name}

    Returns: system prompt string.
    """

def build_exercise_recovery_prompt(
    failed_question: str,
    wrong_answer: str,
    chunk_heading: str,
    chunk_text: str,
    language: str,
) -> tuple[str, str]:
    """
    Builds (system_prompt, user_prompt) for a step-by-step walkthrough recovery card.

    Recovery card structure:
    - title: "Let's work through this together"  (translated)
    - content: step-by-step numbered walkthrough of the correct solution
    - question: a simplified version of the original question (easier MCQ, EASY difficulty)
    - is_recovery: True
    - chunk_id: inherited from caller

    System prompt rules:
    - Acknowledge the wrong answer without shaming: "Many students choose X because..."
    - Show the correct approach in 3–5 numbered steps
    - End with a simplified MCQ on the same concept (easier variant)
    - Language: {language_name}

    Returns: (system_prompt, user_prompt) tuple.
    """
```

### 4.4 Exercise card prompt builder (prompt_builder.py)

```python
def build_exercise_card_prompt(
    chunk: dict,           # {"id": str, "heading": str, "text": str, "section": str}
    student_profile: dict, # {"style": str, "interests": list[str], "language": str}
    language: str,
) -> tuple[str, str]:
    """
    Pure function. Builds (system_prompt, user_prompt) for exercise chunk card generation.

    Delegates system prompt to build_exercise_card_system_prompt(language).
    User prompt includes:
      - CHUNK HEADING: {heading}
      - CHUNK TEXT (truncated to 2000 chars): {text}
      - STUDENT STYLE: {style}
      - STUDENT INTERESTS: {interests}
      - CARD COUNT: Generate 2 cards. If chunk text contains 3+ distinct problems, generate 3 cards.

    Returns: (system_prompt, user_prompt) tuple.
    """
```

### 4.5 Exercise recovery card engine (adaptive_engine.py)

```python
async def generate_exercise_recovery_card(
    failed_question: str,
    wrong_answer: str,
    chunk: dict,           # {"id": str, "heading": str, "text": str}
    language: str,
    client: AsyncOpenAI,
) -> LessonCard:
    """
    Generates a single recovery card after 2 wrong answers on an exercise MCQ.

    Flow:
      1. Build prompts via build_exercise_recovery_prompt()
      2. Call gpt-4o (OPENAI_MODEL) with max_tokens=1200, timeout=30
      3. 3-retry exponential back-off (matches existing LLM retry pattern)
      4. Parse JSON response into LessonCard with is_recovery=True
      5. On parse failure, attempt json_repair fallback
      6. On exhausted retries, raise ValueError

    The returned LessonCard has:
      - chunk_id = str(chunk["id"])
      - is_recovery = True
      - question.difficulty = "EASY"
    """
```

### 4.6 Exam gate deduplication (teaching_router.py — list_chunks handler)

**Current (buggy):**
```python
# Appended unconditionally even if a gate already exists
visible_for_exam = [s for s in summaries if s.chunk_type != "exam_question_source"]
if visible_for_exam:
    summaries.append(synthetic_gate)
```

**Fixed logic:**
```python
# Only inject if no existing exercise_gate chunk exists
already_has_gate = any(s.chunk_type == "exercise_gate" for s in summaries)
if not already_has_gate:
    # Compute synthetic id deterministically
    from uuid import uuid5, NAMESPACE_DNS
    synthetic_id = str(uuid5(NAMESPACE_DNS, f"exam_gate:{concept_id}"))
    max_order = max((s.order_index for s in summaries), default=0)
    summaries.append(ChunkSummary(
        chunk_id=synthetic_id,
        order_index=max_order + 1,
        heading="Section Exam",
        has_images=False,
        has_mcq=False,
        chunk_type="exercise_gate",
        is_optional=False,
        completed=False,
        score=None,
        mode_used=None,
    ))
```

### 4.7 `all_study_complete` update

The existing check at line ~1097 must exclude `exercise` chunks with `is_optional=True`:

```python
teaching_ids = {
    str(c["id"]) for c in all_sorted
    if _get_chunk_type(c.get("heading", "")) in ("teaching", "exercise")
    and not _is_optional_chunk(c.get("heading", ""))
}
```

The same logic applies in the new `complete_chunk_item` handler.

---

## 5. Sequence Diagrams

### 5.1 Exercise chunk — happy path (2 cards, both answered correctly)

```
Student                 Frontend              Backend               OpenAI
  │                        │                     │                     │
  │  Click "Practice       │                     │                     │
  │  Makes Perfect"        │                     │                     │
  │ ─────────────────────► │                     │                     │
  │                        │ POST /chunk-cards   │                     │
  │                        │ {chunk_id: "abc"}   │                     │
  │                        │ ──────────────────► │                     │
  │                        │                     │ build_exercise_     │
  │                        │                     │ card_prompt()       │
  │                        │                     │ ──────────────────► │
  │                        │                     │ ◄────────────────── │
  │                        │                     │ [card1, card2]      │
  │                        │ ◄────────────────── │                     │
  │  Card 1 shown          │                     │                     │
  │ ◄───────────────────── │                     │                     │
  │  Answers correctly     │                     │                     │
  │ ─────────────────────► │                     │                     │
  │  Card 2 shown          │                     │                     │
  │ ◄───────────────────── │                     │                     │
  │  Answers correctly     │                     │                     │
  │ ─────────────────────► │                     │                     │
  │  "Complete" button     │                     │                     │
  │  appears (last card)   │                     │                     │
  │ ─────────────────────► │                     │                     │
  │  Clicks Complete       │ POST /chunks/abc    │                     │
  │                        │ /complete           │                     │
  │                        │ ──────────────────► │                     │
  │                        │ ◄────────────────── │                     │
  │                        │ {all_study_complete:│                     │
  │                        │  false,             │                     │
  │                        │  next_chunk_id: X}  │                     │
  │  Next chunk loads      │                     │                     │
  │ ◄───────────────────── │                     │                     │
```

### 5.2 Exercise chunk — 2-wrong-answer recovery path

```
Student                 Frontend              Backend               OpenAI
  │  Wrong answer ×2      │                     │                     │
  │ ─────────────────────► │                     │                     │
  │                        │ POST /next-card     │                     │
  │                        │ {wrong_attempts: 2, │                     │
  │                        │  failed_exercise_   │                     │
  │                        │  question: "...",   │                     │
  │                        │  student_wrong_     │                     │
  │                        │  answer: "..."}     │                     │
  │                        │ ──────────────────► │                     │
  │                        │                     │ wrong_attempts >= 2 │
  │                        │                     │ AND failed_exercise │
  │                        │                     │ _question set:      │
  │                        │                     │ generate_exercise_  │
  │                        │                     │ recovery_card()     │
  │                        │                     │ ──────────────────► │
  │                        │                     │ ◄────────────────── │
  │                        │                     │ recovery card       │
  │                        │ ◄────────────────── │                     │
  │  Recovery card shown   │                     │                     │
  │  (is_recovery=True,    │                     │                     │
  │   step-by-step)        │                     │                     │
  │ ◄───────────────────── │                     │                     │
```

### 5.3 Language change propagation

```
Student           StudentContext       Backend              OpenAI
  │  Changes         │                   │                    │
  │  language to     │                   │                    │
  │  Spanish         │                   │                    │
  │ ────────────────► │                   │                    │
  │                   │ PATCH /students/  │                    │
  │                   │ {id}/language     │                    │
  │                   │ {language: "es"}  │                    │
  │                   │ ────────────────► │                    │
  │                   │                   │ UPDATE students    │
  │                   │                   │ Find active session│
  │                   │                   │ Load headings      │
  │                   │                   │ ─────────────────► │
  │                   │                   │ ◄───────────────── │
  │                   │                   │ translated_headings│
  │                   │                   │ Bust card cache    │
  │                   │                   │ COMMIT             │
  │                   │ ◄──────────────── │                    │
  │                   │ {translated_      │                    │
  │                   │  headings: [...], │                    │
  │                   │  session_cache_   │                    │
  │                   │  cleared: true}   │                    │
  │                   │                   │                    │
  │                   │ i18n.change       │                    │
  │                   │ Language("es")    │                    │
  │                   │                   │                    │
  │                   │ dispatch(         │                    │
  │                   │  LANGUAGE_CHANGED,│                    │
  │                   │  {headings:[...]})│                    │
  │  UI re-renders    │                   │                    │
  │  with Spanish     │                   │                    │
  │  headings         │                   │                    │
  │ ◄──────────────── │                   │                    │
```

### 5.4 Error path — heading translation timeout

```
Backend
  │  _translate_summaries_headings() called
  │  OpenAI call times out after 10 s
  │  except Exception as e:
  │      logger.warning("[lang-translate] timeout for lang=%s: %s", language, e)
  │      return headings  # return original untranslated list
  │
  │  Cache bust still proceeds
  │  Response: translated_headings = original headings, session_cache_cleared = true
```

---

## 6. Two-Path Branch Logic — Teaching vs Exercise

The `POST /sessions/{id}/next-card` handler must branch on chunk type:

```python
# In next_card() handler (teaching_router.py)

chunk = await chunk_ksvc.get_chunk_by_id(db, req.chunk_id)
chunk_type = _get_chunk_type(chunk.get("heading", ""))

if chunk_type == "exercise":
    # Exercise path
    if req.failed_exercise_question and req.wrong_attempts >= 2:
        # Recovery card branch
        card = await generate_exercise_recovery_card(
            failed_question=req.failed_exercise_question,
            wrong_answer=req.student_wrong_answer or "",
            chunk=chunk,
            language=student.preferred_language,
            client=_get_openai_client(),
        )
    else:
        # Normal exercise card generation
        system_p, user_p = build_exercise_card_prompt(
            chunk=chunk,
            student_profile={"style": session.style,
                             "interests": student.interests,
                             "language": student.preferred_language},
            language=student.preferred_language,
        )
        card = await _call_llm_for_exercise_card(system_p, user_p, chunk_id=str(chunk["id"]))
else:
    # Teaching path (existing adaptive generation)
    card = await generate_per_card(
        session=session,
        student=student,
        chunk=chunk,
        signals=CardBehaviorSignals(...),
        client=_get_openai_client(),
    )
```

**Key invariant:** Exercise chunks never call `generate_per_card()`. Teaching chunks never call `generate_exercise_recovery_card()`. The branch is determined solely by `_get_chunk_type(chunk.heading)`.

---

## 7. Frontend State Changes

### 7.1 SessionContext reducer additions

```javascript
// New action type
case "LANGUAGE_CHANGED":
  return {
    ...state,
    // Replace headings in chunkList by index
    chunkList: state.chunkList.map((chunk, i) => ({
      ...chunk,
      heading: action.payload.headings[i] ?? chunk.heading,
    })),
    // Clear card cache so cards regenerate in new language
    cards: [],
    currentCardIndex: 0,
  };

// Modified CHUNK_COMPLETE — now also handles the new completeChunkItem API
case "CHUNK_ITEM_COMPLETE":
  return {
    ...state,
    chunkList: state.chunkList.map((c) =>
      c.chunk_id === action.payload.chunk_id
        ? { ...c, completed: true }
        : c
    ),
    allStudyComplete: action.payload.all_study_complete,
  };
```

### 7.2 StudentContext — language change dispatch

```javascript
// In updateLanguage() function (StudentContext.jsx)
const updateLanguage = useCallback(async (newLang) => {
  const res = await updateStudentLanguage(student.id, newLang);
  const { translated_headings, session_cache_cleared } = res.data;
  // Update i18n
  i18n.changeLanguage(newLang);
  // Update student state
  setStudentState((prev) => ({ ...prev, preferred_language: newLang }));
  // Propagate to session context if headings came back
  if (translated_headings?.length > 0) {
    sessionDispatch({ type: "LANGUAGE_CHANGED", payload: { headings: translated_headings } });
  }
}, [student, sessionDispatch]);
```

`sessionDispatch` must be wired from `SessionContext` into `StudentContext`. Options:
1. Pass `sessionDispatch` as a prop to `StudentProvider` (simplest)
2. Use a shared event bus (overkill for this use case)

**Decision:** Option 1 — pass `sessionDispatch` as optional prop; if not provided, language change skips the dispatch.

### 7.3 Complete button in CardLearningView

```jsx
// Shown only on the last card of the current chunk
const isLastCard = currentCardIndex === cards.length - 1;

{isLastCard && (
  <button
    onClick={handleChunkComplete}
    style={{ /* primary button styles */ }}
  >
    {t("learning.completeChunk")}  {/* i18n key, all 13 locales */}
  </button>
)}
```

`handleChunkComplete` calls `completeChunkItem(sessionId, currentChunkId)` from `sessions.js`, then dispatches `CHUNK_ITEM_COMPLETE`.

### 7.4 LearningPage — non-interactive panels

```jsx
// In the chunk list renderer
{chunk.chunk_type === "learning_objective" || chunk.chunk_type === "section_review" ? (
  <div className="chunk-panel non-interactive">
    <span>{chunk.heading}</span>
    <span className="badge">{t(`chunkType.${chunk.chunk_type}`)}</span>
  </div>
) : chunk.chunk_type === "exercise" ? (
  <div className={`chunk-panel study-item ${chunk.is_optional ? "optional" : ""}`}>
    <span>{chunk.heading}</span>
    <span className="badge">{chunk.is_optional ? t("chunkType.optional") : t("chunkType.practice")}</span>
  </div>
) : (
  // existing teaching / exercise_gate rendering
  ...
)}
```

---

## 8. Prompt Structures

### 8.1 Exercise card system prompt

```
You are an interactive math practice generator for the ADA learning platform.

## YOUR TASK
Given a textbook exercise chunk, generate 2–3 multiple-choice question (MCQ) cards.
Each card tests one problem from the chunk.

## RULES
- Source problems ONLY from the chunk text provided — do not invent new problems
- Each card has exactly one MCQ with 4 answer options (A, B, C, D)
- One option must be correct; all others must be plausible common mistakes
- Difficulty: MEDIUM. If the chunk contains 3+ problems, one card may be HARD.
- Include a brief explanation (2–3 sentences) of why the correct answer is right
- Card count: 2 unless chunk text contains 3+ clearly distinct problems, then 3

## OUTPUT FORMAT (JSON)
[
  {
    "index": 0,
    "title": "<short title from problem>",
    "content": "<problem statement in Markdown>",
    "question": {
      "text": "<question>",
      "options": ["<A>", "<B>", "<C>", "<D>"],
      "correct_index": <0-3>,
      "explanation": "<why correct>",
      "difficulty": "MEDIUM"
    },
    "chunk_id": "<chunk_id>",
    "is_recovery": false
  }
]

## LANGUAGE
Respond entirely in {language_name}.
```

### 8.2 Exercise recovery card prompt

**System:**
```
You are a supportive math tutor helping a student who answered incorrectly twice.

## YOUR TASK
Generate one recovery card that walks through the correct solution step by step,
then ends with a simpler version of the same question to rebuild confidence.

## RULES
- Acknowledge the wrong answer without blame: start with
  "Many students choose '{wrong_answer}' because..."
- Show the correct approach in 3–5 numbered steps
- Each step must be complete — no abbreviations or "as before"
- End with a SIMPLIFIED MCQ (EASY difficulty) testing the same core concept

## OUTPUT FORMAT (JSON — single card object)
{
  "index": 0,
  "title": "Let's work through this together",
  "content": "<full step-by-step walkthrough in Markdown>",
  "question": {
    "text": "<simplified question>",
    "options": ["<A>", "<B>", "<C>", "<D>"],
    "correct_index": <0-3>,
    "explanation": "<why correct>",
    "difficulty": "EASY"
  },
  "chunk_id": "<chunk_id>",
  "is_recovery": true
}

## LANGUAGE
Respond entirely in {language_name}.
```

**User:**
```
CHUNK HEADING: {chunk_heading}

ORIGINAL QUESTION: {failed_question}

STUDENT'S WRONG ANSWER: {wrong_answer}

CHUNK TEXT (source material):
{chunk_text truncated to 1500 chars}
```

---

## 9. Security Design

No new attack surface introduced:
- `chunk_id` path parameter: validated as UUID string; used in `WHERE chunk_id = :id` parameterised query
- Heading translation input: `headings` list is sourced from DB (not user input) before being sent to OpenAI — no prompt injection risk from user-controlled text
- `failed_exercise_question` / `student_wrong_answer` in `NextCardRequest`: these are user-supplied strings injected into an LLM prompt. Mitigations:
  - Hard-truncated to 500 chars each before insertion into prompt
  - Inserted as quoted values in a structured prompt block, not as instruction text
  - Existing `max_length=2000` Pydantic validator applies to all string fields in request schemas — add `max_length=500` to these two specific fields

---

## 10. Observability Design

All new code paths use the existing `logger = logging.getLogger(__name__)` pattern.

| Log event | Level | Fields |
|-----------|-------|--------|
| Heading translation completed | INFO | `lang`, `heading_count`, `duration_ms` |
| Heading translation failed | WARNING | `lang`, `error` |
| Exercise card generated | INFO | `session_id`, `chunk_id`, `card_count` |
| Exercise recovery card generated | INFO | `session_id`, `chunk_id`, `failed_question_len` |
| Chunk item completed | INFO | `session_id`, `chunk_id`, `all_study_complete` |
| Cache busted on language change | INFO | `session_id`, `student_id`, `new_lang` |
| Exam gate injected (synthetic) | INFO | `session_id`, `concept_id` |
| Exam gate already exists (skip inject) | DEBUG | `session_id`, `concept_id` |

No new metrics or dashboards required at this time.

---

## 11. Error Handling & Resilience

| Scenario | Handling |
|----------|----------|
| `_translate_summaries_headings` LLM timeout | Catch exception, log warning, return original headings; cache bust still proceeds |
| Exercise card LLM returns < 2 cards | Pad with a single generic recall question using chunk heading as question text |
| Exercise recovery LLM exhausts 3 retries | Raise `ValueError`; handler returns HTTP 500 with `{"detail": "Recovery card generation failed"}` |
| `POST /chunks/{id}/complete` called twice | Idempotent: check `if chunk_id in session.chunk_progress` before writing; return 200 with current state |
| Language changed while exam in progress | Exam state cleared server-side; frontend shows the exam gate as "not started"; student must restart exam |
| `LANGUAGE_CHANGED` reducer fires with fewer headings than chunk list | Map by index with `?? chunk.heading` fallback — extra chunks retain original heading |

---

## 12. Testing Strategy

### Unit tests

| Test | File | Assertion |
|------|------|-----------|
| `_get_chunk_type` — all six types | `test_chunk_classification.py` | Each example heading maps to correct type |
| `_get_chunk_type` — priority order (section number beats exercise keyword) | same | `"1.1 Practice Makes Perfect"` → `section_review` |
| `_is_optional_chunk` — true/false cases | same | "Writing Exercises" → True; "Practice Makes Perfect" → False |
| Exam gate deduplication — no existing gate | `test_exam_gate.py` | One gate appended |
| Exam gate deduplication — existing gate in DB | same | No second gate appended |
| `_translate_summaries_headings` — success | `test_language_propagation.py` | Returns list of same length |
| `_translate_summaries_headings` — LLM timeout | same | Returns original list unchanged |
| `build_exercise_card_system_prompt` — language injection | `test_exercise_prompts.py` | Language name appears in prompt |
| `build_exercise_recovery_prompt` — wrong answer in prompt | same | `wrong_answer` string present in user prompt |
| `all_study_complete` excludes optional chunks | `test_chunk_completion.py` | Writing Exercises chunk not in teaching_ids |

### Integration tests

| Test | Scenario |
|------|----------|
| Exercise chunk happy path | POST /chunk-cards for exercise chunk returns 2 cards with MCQ fields set |
| Exercise recovery path | POST /next-card with wrong_attempts=2 + failed_exercise_question returns is_recovery=True card |
| Language change propagation | PATCH /language returns translated_headings; subsequent GET /chunks returns translated headings |
| Complete chunk item | POST /chunks/{id}/complete updates chunk_progress; second call is idempotent |
| Socratic endpoints removed | POST /check returns 404; POST /respond returns 404 |

### Contract tests

The `ChunkSummary.is_optional` field defaults to `False` — all existing integration tests continue to pass without modification.

---

## Key Decisions Requiring Stakeholder Input

1. **`sessionDispatch` wiring:** Should `StudentContext` receive `sessionDispatch` as a prop (simple but creates coupling), or should a shared context event bus be introduced? The prop approach is simpler but requires `LearningPage.jsx` to pass the ref down.

2. **Exercise chunk card generation endpoint:** Should exercise cards be generated via the existing `POST /chunk-cards` endpoint (with internal branch on chunk type) or a new `POST /chunk-exercise-cards` endpoint? Current design: branch internally in `/chunk-cards` to avoid API surface proliferation.

3. **Socratic schemas cleanup:** `SocraticResponse`, `StudentResponseRequest`, `RecheckResponse` are no longer needed if Socratic is fully removed. Should they be deleted from `teaching_schemas.py` (clean) or kept as dead code for a release cycle (safe)? Current design: delete immediately.

4. **Max length for `failed_exercise_question`:** Currently proposed at 500 chars. Is this sufficient for long multi-part exercise problems? Some textbook problems exceed this length.
