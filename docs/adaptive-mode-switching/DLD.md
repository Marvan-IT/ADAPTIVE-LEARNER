# Detailed Low-Level Design: Adaptive Mode Switching

## Revision History
| Date | Author | Change |
|------|--------|--------|
| 2026-03-14 | solution-architect | Initial DLD |

---

## 1. Component Breakdown

| Component | File | Change |
|-----------|------|--------|
| AdaptivePromptBuilder | `adaptive/prompt_builder.py` | RC-1: replace triple-block with `_CARD_MODE_DELIVERY` dict |
| BatchPromptBuilder | `api/prompts.py` | RC-1b: `_MODE_DELIVERY` dict; RC-3: TRY_IT visual hints; RC-7: image rules |
| TeachingService | `api/teaching_service.py` | RC-2: `_batch_consecutive_try_its()`; RC-5: conservative cap; RC-7: image max-1; cache v9 |
| AdaptiveEngine | `adaptive/adaptive_engine.py` | RC-6: `generate_recovery_card()`; `_RECOVERY_STYLE_MODIFIERS`; `_RECOVERY_LANG_MAP` |
| AdaptiveRouter | `adaptive/adaptive_router.py` | RC-6: `asyncio.gather`; import `generate_recovery_card` |
| AdaptiveSchemas | `adaptive/schemas.py` | RC-6: `re_explain_card_title` on `NextCardRequest`; `recovery_card` on `NextCardResponse` |
| TeachingSchemas | `api/teaching_schemas.py` | RC-8: `UpdateSessionInterestsRequest` |
| TeachingRouter | `api/teaching_router.py` | RC-8: `PUT /sessions/{id}/interests` endpoint |
| SessionsAPI | `frontend/src/api/sessions.js` | RC-6: `re_explain_card_title`; RC-8: `updateSessionInterests()` |
| SessionContext | `frontend/src/context/SessionContext.jsx` | RC-6: `INSERT_RECOVERY_CARD` reducer + dispatch |
| CardLearningView | `frontend/src/components/learning/CardLearningView.jsx` | RC-4: pass signals on wrong×2 |
| LearningPage | `frontend/src/pages/LearningPage.jsx` | RC-8: per-section customize panel + import from sessions.js |
| StudentForm | `frontend/src/components/welcome/StudentForm.jsx` | RC-8: remove interests + style fields |

---

## 2. Schema Changes

### `adaptive/schemas.py`

```python
class NextCardRequest(CardBehaviorSignals):
    re_explain_card_title: str | None = None
    # When set with wrong_attempts >= 2: backend generates recovery re-explain card.
    # Must NOT start with "Let's Try Again" (prevents recovery-of-recovery loops).

class NextCardResponse(BaseModel):
    session_id: UUID
    card: dict
    card_index: int
    adaptation_applied: str
    learning_profile_summary: dict
    motivational_note: str | None = None
    performance_vs_baseline: str | None = None
    recovery_card: dict | None = None   # NEW: set when wrong×2 + re_explain_card_title provided
```

### `api/teaching_schemas.py`

```python
class UpdateSessionInterestsRequest(BaseModel):
    interests: list[str] = Field(
        default_factory=list,
        description="Per-session interest override (empty = use student profile interests)"
    )
```

---

## 3. New API Endpoint

**PUT /api/v2/sessions/{session_id}/interests**

```
Request body: UpdateSessionInterestsRequest
  { "interests": ["music", "sports"] }

Response 200:
  { "session_id": "<uuid>", "lesson_interests": [...] }

Response 404: Session not found
```

Auth: existing `verify_api_key` dependency (same as all other session endpoints).

---

## 4. Sequence: Wrong×2 Recovery Flow

```
Student answers card N wrong for 2nd time (isSecondAttempt = true)
  ↓
CardLearningView.jsx:
  elapsedSec = (performance.now() - cardStartTimeRef.current) / 1000
  goToNextCard({
    cardIndex:           currentCardIndex,
    timeOnCardSec:       elapsedSec,
    wrongAttempts:       2,
    selectedWrongOption: selectedWrongOptionRef.current ?? null,
    hintsUsed:           hintsUsedRef.current,
    idleTriggers:        idleTriggerCount,
    difficultyBias:      null,
    reExplainCardTitle:  card?.is_recovery ? null : (card?.title ?? null),
  })
  ↓
SessionContext.goToNextCard:
  dispatch NEXT_CARD → currentCardIndex = N+1 (lag card shown, zero latency)
  background: await completeCardAndGetNext(session.id, signals)
  ↓
POST /api/v2/sessions/{id}/complete-card
  { wrong_attempts: 2, re_explain_card_title: "Example 1.47", ... }
  ↓
adaptive_router.complete_card():
  need_recovery = (wrong_attempts >= 2 AND re_explain_card_title set AND not "Let's Try Again")
  effective_interests = session.lesson_interests OR student.interests
  effective_style = session.style OR student.style

  asyncio.gather(
    generate_next_card(..., model=ADAPTIVE_CARD_MODEL),  → section_N+1 in STRUGGLING
    _maybe_recovery()  → generate_recovery_card(topic, concept_id, interests, style, language)
  )
  ↓
Returns: NextCardResponse {
  card: section_N+1_STRUGGLING,
  recovery_card: { title: "Let's Try Again — Example 1.47", is_recovery: true, ... }
}
  ↓
SessionContext:
  dispatch REPLACE_UPCOMING_CARD → slot section_N+1 at N+2
  if (res.data.recovery_card && cards.length < MAX_ADAPTIVE_CARDS):
    dispatch INSERT_RECOVERY_CARD → insert recovery at N+2, push adaptive to N+3

Final deck: [N:done] → [N+1:lag/FAST] → [N+2:recovery/STRUGGLING] → [N+3:adaptive/STRUGGLING]
```

---

## 5. Module-Level Dicts Added to `adaptive_engine.py`

```python
# Inline style modifiers — mirrors STYLE_MODIFIERS in api/prompts.py
# NOTE: kept decoupled intentionally (no api/ import in adaptive/).
_RECOVERY_STYLE_MODIFIERS: dict[str, str] = {
    "pirate":    "Use pirate language naturally: 'Ahoy!', 'matey', treasure=answer.",
    "astronaut": "Frame as space mission: 'Mission Control', 'zero gravity', 'launch sequence'.",
    "gamer":     "Use gaming language: 'level up', 'XP gained', 'boss battle', 'respawn'.",
    "default":   "",
}

_RECOVERY_LANG_MAP: dict[str, str] = {
    "ta": "Tamil", "ar": "Arabic", "hi": "Hindi", "fr": "French",
    "es": "Spanish", "zh": "Chinese", "ja": "Japanese", "de": "German",
    "ko": "Korean", "pt": "Portuguese", "ml": "Malayalam", "si": "Sinhala",
}
```

---

## 6. `INSERT_RECOVERY_CARD` Reducer

```javascript
case "INSERT_RECOVERY_CARD": {
  const insertAt = state.currentCardIndex + 1;
  const newCards = [
    ...state.cards.slice(0, insertAt),
    { ...action.payload, index: insertAt },              // recovery card
    ...state.cards.slice(insertAt).map((c, i) => ({      // all subsequent cards
      ...c, index: insertAt + 1 + i,                     // re-indexed to avoid drift
    })),
  ];
  return { ...state, cards: newCards };
}
```

Dispatched from `goToNextCard()` after `REPLACE_UPCOMING_CARD` when `res.data.recovery_card` is set:
```javascript
dispatch({ type: "REPLACE_UPCOMING_CARD", payload: res.data });
if (res.data?.recovery_card && state.cards.length < MAX_ADAPTIVE_CARDS) {
  dispatch({ type: "INSERT_RECOVERY_CARD", payload: res.data.recovery_card });
}
```

---

## 7. Anti-Loop Protection (3 Layers)

| Layer | Where | Guard |
|-------|-------|-------|
| Backend function | `generate_recovery_card()` in `adaptive_engine.py` | `if topic_title.startswith("Let's Try Again"): return None` |
| Backend endpoint | `complete_card()` in `adaptive_router.py` | `need_recovery = ... and not title.startswith("Let's Try Again")` |
| Frontend | `CardLearningView.jsx` wrong×2 handler | `reExplainCardTitle: card?.is_recovery ? null : card?.title` |

---

## 8. Image Distribution Changes

### System prompt (`api/prompts.py`)
Replace IMAGE ASSIGNMENT RULES with stricter rules:
- Max 1 image per card (`image_indices` must have 0 or 1 entry)
- Topic-match guidance (number line → counting/addition, array → multiplication)
- All available images must appear on exactly one card

### Post-processing (`api/teaching_service.py`)
1. **Assignment loop**: add `break` after first valid image per card (max-1 enforcement)
2. **Fallback section**: extend from VISUAL-only to ALL card types (remove `card_type != "VISUAL"` guard)

---

## 9. Conservative Mode Cap

In `teaching_service.generate_cards()`, immediately after `build_blended_analytics()`:

```python
total_interactions = history.get("total_interactions", 0) if history else 0
if total_interactions < 5 and _generate_as == "FAST":
    _generate_as = "NORMAL"
    _blended_score = min(_blended_score, 2.4)
    logger.info("[mode-cap] concept=%s FAST→NORMAL interactions=%d", session.concept_id, total_interactions)
```

---

## 10. `_batch_consecutive_try_its()` Algorithm

```python
@staticmethod
def _batch_consecutive_try_its(sections: list[dict], max_batch: int = 4) -> list[dict]:
    result: list[dict] = []
    i = 0
    while i < len(sections):
        if sections[i].get("section_type") != "TRY_IT":
            result.append(sections[i]); i += 1; continue
        # Collect consecutive TRY_IT run
        batch = [sections[i]]
        while (i + len(batch) < len(sections)
               and sections[i + len(batch)].get("section_type") == "TRY_IT"
               and len(batch) < max_batch):
            batch.append(sections[i + len(batch)])
        if len(batch) == 1:
            result.append(batch[0])
        else:
            # Merge into TRY_IT_BATCH
            result.append({
                "title": f"{batch[0]['title']} – {batch[-1]['title']}",
                "text": "\n\n".join(
                    f"({chr(97+j)}) {s['title']}\n{s['text']}" for j, s in enumerate(batch)
                ),
                "section_type": "TRY_IT_BATCH",
            })
        i += len(batch)
    return result
```

Solo TRY_IT (run length = 1) passes through unchanged. Only consecutive runs are merged.

---

## 11. Cache Version

`_CARDS_CACHE_VERSION` is a **local variable inside `generate_cards()`** (not module-level). Change `= 7` → `= 9` to invalidate stale cached decks.

---

## 12. Key Variable Names (confirmed via code inspection)

| Variable | File | Line | Note |
|----------|------|------|------|
| `cardStartTimeRef.current` | CardLearningView.jsx | 200 | Reset to `performance.now()` on each card |
| `wrongAttemptsRef.current` | CardLearningView.jsx | 201 | Incremented on each wrong answer |
| `selectedWrongOptionRef.current` | CardLearningView.jsx | 202 | Index of selected wrong option |
| `hintsUsedRef.current` | CardLearningView.jsx | 203 | Hint count |
| `idleTriggerCount` | CardLearningView.jsx | 161 | From `useSession()` context |
| `isSecondAttempt` | CardLearningView.jsx | ~374 | `!!cs.replacementMcq` |
| `blended, _blended_score, _generate_as` | teaching_service.py | ~848 | Return from `build_blended_analytics()` |
| `switchStyle` | sessions.js | 34 | Already exists — use this name |
| `_CARDS_CACHE_VERSION` | teaching_service.py | inside `generate_cards()` | Local variable, value = 7 |
