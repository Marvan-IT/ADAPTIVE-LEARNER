# DLD — Card Blank Screen Fix

**Feature slug:** `card-blank-screen-fix`
**Date:** 2026-03-09
**Author:** Solution Architect

---

## 1. Component Breakdown

### 1.1 `SessionContext.jsx` — reducer and action handler

**Single responsibility:** Manages all session state transitions for the card learning flow.

Three surgical changes are required:

| Change ID | Location | What changes |
|-----------|----------|-------------|
| CHG-1 | `NEXT_CARD` reducer case (line 80–87) | Add upper-bound clamp to `currentCardIndex` |
| CHG-2 | `ADAPTIVE_CARD_ERROR` reducer case (line 140–151) | Fix underflow; do not advance index on error |
| CHG-3 | `goToNextCard()` callback (line 318–352) | Skip adaptive API call when next pre-gen card exists |

No new actions, no new state fields, no new selectors.

---

### 1.2 `CardLearningView.jsx` — null guard replacement

**Single responsibility:** Renders the active card UI for all card types.

One change:

| Change ID | Location | What changes |
|-----------|----------|-------------|
| CHG-4 | Line 517: `if (!card) return null` | Replace with visible error UI using `noCardsError` i18n key |

---

### 1.3 `frontend/src/locales/en.json` — i18n keys

Two keys added:

```json
"learning.generatingCards": "ADA is preparing your lesson cards...",
"learning.noCardsError": "No cards could be loaded for this lesson. Please go back and try again."
```

Note: `learning.generatingCard` (singular) already exists at line 113 of `en.json` and is used by the adaptive card skeleton. The new `learning.generatingCards` (plural) is used by the initial lesson loading state (CHG-4 loading branch, if needed in future).

For the immediate fix, only `learning.noCardsError` is strictly required by CHG-4. `learning.generatingCards` is added for completeness and future use.

---

## 2. Data Design

### State invariant (enforced post-fix)

After every reducer transition the following invariant must hold:

```
0 <= state.currentCardIndex <= Math.max(0, state.cards.length - 1)
```

This is guaranteed by:
- CHG-1: clamps `NEXT_CARD` upper bound.
- CHG-2: does not change `currentCardIndex` on `ADAPTIVE_CARD_ERROR`; clamp is a safety net only.
- `PREV_CARD` already clamps to `Math.max(currentCardIndex - 1, 0)` (unchanged, correct).
- `ADAPTIVE_CARD_LOADED` appends to `cards[]` BEFORE incrementing `currentCardIndex` (unchanged, correct).

### No new state fields

The fix adds no new fields to `initialState`. `adaptiveCardLoading` (already in state) is used as-is for the loading skeleton guard.

### Derived value used in CHG-4

```
isLastPreGenCard = currentCardIndex >= cards.length - 1
```

This is computed inline inside `goToNextCard()`. It is not stored in state.

---

## 3. API Design

No new API endpoints. No changes to existing endpoint contracts.

The only API behavioural change is a reduction in call frequency to:

```
POST /api/v2/sessions/{session_id}/complete-card
```

**Before fix:** Called on every "Next" click.
**After fix:** Called only when `currentCardIndex >= cards.length - 1` (student exhausts pre-generated cards).

This is a client-side behavioural change only. The endpoint contract is unchanged.

---

## 4. Sequence Diagrams

### 4.1 Happy path — navigating pre-generated cards (post-fix)

```
Student clicks "Next"
  → CardLearningView.jsx: handleNextCard()
  → goToNextCard(signals)
      currentCardIndex (e.g. 1) < cards.length - 1 (e.g. 3)
      → dispatch({ type: "NEXT_CARD" })
          reducer: currentCardIndex = Math.min(2, Math.max(0, 3 - 1)) = Math.min(2, 2) = 2
      → return (no API call)
  → CardLearningView renders card at index 2
```

### 4.2 Happy path — reaching last pre-generated card (adaptive extension)

```
Student clicks "Next" on last pre-gen card
  → goToNextCard(signals)
      currentCardIndex (3) >= cards.length - 1 (3)
      → dispatch({ type: "ADAPTIVE_CARD_LOADING" })
      → await completeCardAndGetNext(session.id, signals)
          [backend generates next adaptive card]
      → dispatch({ type: "ADAPTIVE_CARD_LOADED", payload: res.data })
          reducer: cards = [...cards, newCard], currentCardIndex = 4
      → CardLearningView renders new adaptive card at index 4
```

### 4.3 Error path — adaptive API fails (post-fix)

```
Student clicks "Next" on last pre-gen card
  → goToNextCard(signals)
      → dispatch({ type: "ADAPTIVE_CARD_LOADING" })
      → await completeCardAndGetNext(...)  [throws error]
      → catch: dispatch({ type: "ADAPTIVE_CARD_ERROR" })
          reducer (pre-fix): currentCardIndex = Math.min(idx+1, cards.length-1)
                             if cards=[1 item], idx=0: Math.min(1, 0) = 0  ✓
                             if cards=[], idx=0: Math.min(1, -1) = -1  ✗ BUG
          reducer (post-fix): currentCardIndex = cards.length > 0
                                ? Math.min(state.currentCardIndex, cards.length - 1)
                                : 0
                             if cards=[1 item], idx=0: Math.min(0, 0) = 0  ✓
                             if cards=[], idx=0: 0  ✓ (no underflow)
      → CardLearningView renders same card (student held in place)
      → [Optional: error toast shown by caller — out of scope for this fix]
```

### 4.4 Null card guard (Bug 1 — post-fix)

```
cards = [] (API returned empty or not yet loaded)
  → card = cards[currentCardIndex] = undefined
  → CardLearningView:
      adaptiveCardLoading = false → skip adaptive skeleton
      card = undefined → enter noCardsError branch (NEW)
      → render:
          <p>{t("learning.noCardsError")}</p>
          <button onClick={() => { reset(); navigate("/map") }}>
            {t("learning.backToMap")}
          </button>
      (blank screen eliminated)
```

### 4.5 Index out of bounds display (Bug 2 — post-fix)

```
cards = [c0, c1, c2, c3]  (length 4, indices 0–3)
NEXT_CARD dispatched when currentCardIndex = 3 (last card)
  reducer (pre-fix): 3 + 1 = 4  → card = cards[4] = undefined → blank screen
  reducer (post-fix): Math.min(4, Math.max(0, 4-1)) = Math.min(4, 3) = 3  → card = cards[3]
Progress display: "Card 4" (clamped 3+1 display), not "(5/1)"
```

---

## 5. Integration Design

No external integration changes. All changes are intra-component.

The only integration point affected is `goToNextCard()` → `completeCardAndGetNext()`. The change is a guard that reduces call frequency; the API contract itself is not modified.

---

## 6. Security Design

No security surface changes. All four bugs are client-side display/state bugs. No new network calls, no new data exposure, no auth changes.

---

## 7. Observability Design

### Logging
No new backend logging required.

Frontend: The `noCardsError` UI state is visible to the student. No `console.error` is needed beyond what is already in `startLesson()` error dispatch path.

### Analytics
No new `trackEvent()` calls are added by this fix. The existing `lesson_error` event fired from `startLesson()`'s catch block already captures the case where `getCards()` fails, which is the most common reason `cards` would be empty.

If the product team wants explicit tracking of the `noCardsError` render, a `trackEvent("cards_null_guard_hit", ...)` call can be added to the CHG-4 error branch. This is optional and left for the frontend developer to decide in consultation with analytics requirements.

---

## 8. Error Handling and Resilience

### CHG-1 — NEXT_CARD clamp
```
currentCardIndex = Math.min(state.currentCardIndex + 1, Math.max(0, state.cards.length - 1))
```
- If `cards` is empty: `Math.max(0, -1) = 0` → index stays 0. Safe.
- If at last card: index is clamped to last valid position. Safe.

### CHG-2 — ADAPTIVE_CARD_ERROR no-advance
```
currentCardIndex = state.cards.length > 0
  ? Math.min(state.currentCardIndex, state.cards.length - 1)
  : 0
```
- If `cards` is empty: returns 0. Safe (no card renders; CHG-4 null guard shows error UI).
- If `cards` is non-empty: clamp to last valid index. Index does NOT advance (intentional: student held in place on error).
- `adaptiveCardLoading` is set to `false` in this case (unchanged).

### CHG-3 — goToNextCard pre-gen boundary
```javascript
async (signals) => {
  if (!state.session || !signals) {
    dispatch({ type: "NEXT_CARD" });
    return;
  }
  // NEW: skip adaptive API if a pre-generated card exists at next index
  if (state.currentCardIndex < state.cards.length - 1) {
    dispatch({ type: "NEXT_CARD" });
    return;
  }
  // Ceiling reached
  if (state.cards.length >= MAX_ADAPTIVE_CARDS) {
    recordCardInteraction(...).catch(...);
    dispatch({ type: "NEXT_CARD" });
    return;
  }
  // Adaptive extension: only reached at last pre-gen card
  dispatch({ type: "ADAPTIVE_CARD_LOADING" });
  try {
    const res = await completeCardAndGetNext(state.session.id, signals);
    ...
    dispatch({ type: "ADAPTIVE_CARD_LOADED", payload: res.data });
  } catch (err) {
    dispatch({ type: "ADAPTIVE_CARD_ERROR" });
  }
}
```

The `MAX_ADAPTIVE_CARDS` ceiling check remains; it now fires only when the student has genuinely exhausted pre-generated cards and accumulated adaptive extensions.

### CHG-4 — null guard error UI

The null guard is placed after the existing `adaptiveCardLoading` early return (line 495–515). Execution flow:

```
if (adaptiveCardLoading) → return skeleton   [existing, line 495]
if (!card)               → return errorUI    [new, replaces line 517]
// card is defined and not loading
```

The error UI contains:
- The translated error message (`noCardsError`).
- A "Back to Map" button that calls `reset()` then `navigate("/map")`.
- The `AssistantPanel` is NOT rendered in the error state (no session to assist with).

---

## 9. Testing Strategy

### Unit tests — `SessionContext.jsx` reducer

All tests use pure function testing: call `sessionReducer(state, action)` directly.

| Test ID | Description | Assertion |
|---------|-------------|-----------|
| UT-1 | `NEXT_CARD` at last card (index = length - 1) | `currentCardIndex` unchanged (clamped) |
| UT-2 | `NEXT_CARD` from mid-deck | `currentCardIndex` increments by 1 |
| UT-3 | `NEXT_CARD` with empty `cards` array | `currentCardIndex` = 0 (no underflow) |
| UT-4 | `ADAPTIVE_CARD_ERROR` with non-empty cards | `currentCardIndex` unchanged; `adaptiveCardLoading` = false |
| UT-5 | `ADAPTIVE_CARD_ERROR` with empty `cards` array | `currentCardIndex` = 0; no negative value |
| UT-6 | `ADAPTIVE_CARD_ERROR` does not advance index | result.currentCardIndex === initial.currentCardIndex |

### Unit tests — `goToNextCard()` callback

These tests mock `completeCardAndGetNext` and assert dispatch call patterns.

| Test ID | Description | Assertion |
|---------|-------------|-----------|
| UT-7 | Mid-deck click (pre-gen card at next index exists) | `completeCardAndGetNext` NOT called; `NEXT_CARD` dispatched |
| UT-8 | Last pre-gen card click | `ADAPTIVE_CARD_LOADING` dispatched; `completeCardAndGetNext` called |
| UT-9 | Adaptive ceiling reached | `completeCardAndGetNext` NOT called; `recordCardInteraction` called; `NEXT_CARD` dispatched |

### Component test — `CardLearningView.jsx` null guard

| Test ID | Description | Assertion |
|---------|-------------|-----------|
| CT-1 | Render with `cards = []`, `adaptiveCardLoading = false` | `noCardsError` i18n text is visible in the DOM |
| CT-2 | Render with `cards = [card]`, `currentCardIndex = 0` | Card content renders; error UI not present |
| CT-3 | Render with `adaptiveCardLoading = true` | Skeleton renders; error UI not present |

### i18n completeness test

| Test ID | Description | Assertion |
|---------|-------------|-----------|
| IT-1 | All 13 locale JSON files contain `learning.generatingCards` key | Key present |
| IT-2 | All 13 locale JSON files contain `learning.noCardsError` key | Key present |

### Integration test

| Test ID | Description | Assertion |
|---------|-------------|-----------|
| INT-1 | Full card navigation: 3 pre-gen cards, click Next 3 times | Adaptive API called exactly once (on 3rd click only) |
| INT-2 | Full card navigation: adaptive API errors on 3rd click | Student sees same card (index = 2); no blank screen |
| INT-3 | Remediation flow: cards reloaded after failed Socratic | `currentCardIndex` resets to 0; first remediation card rendered |

---

## Detailed Code Specifications

### CHG-1 — `NEXT_CARD` reducer (SessionContext.jsx lines 80–87)

Replace:
```javascript
case "NEXT_CARD":
  return {
    ...state,
    currentCardIndex: state.currentCardIndex + 1,
    idleTriggerCount: 0,
    motivationalNote: null,
    performanceVsBaseline: null,
  };
```

With:
```javascript
case "NEXT_CARD":
  return {
    ...state,
    currentCardIndex: Math.min(
      state.currentCardIndex + 1,
      Math.max(0, state.cards.length - 1)
    ),
    idleTriggerCount: 0,
    motivationalNote: null,
    performanceVsBaseline: null,
  };
```

---

### CHG-2 — `ADAPTIVE_CARD_ERROR` reducer (SessionContext.jsx lines 140–151)

Replace:
```javascript
case "ADAPTIVE_CARD_ERROR":
  return {
    ...state,
    adaptiveCardLoading: false,
    currentCardIndex: Math.min(
      state.currentCardIndex + 1,
      state.cards.length - 1
    ),
    idleTriggerCount: 0,
    motivationalNote: null,
    performanceVsBaseline: null,
  };
```

With:
```javascript
case "ADAPTIVE_CARD_ERROR":
  return {
    ...state,
    adaptiveCardLoading: false,
    currentCardIndex: state.cards.length > 0
      ? Math.min(state.currentCardIndex, state.cards.length - 1)
      : 0,
    idleTriggerCount: 0,
    motivationalNote: null,
    performanceVsBaseline: null,
  };
```

---

### CHG-3 — `goToNextCard()` (SessionContext.jsx lines 318–352)

Insert the pre-gen boundary guard immediately after the `MAX_ADAPTIVE_CARDS` ceiling check comment and before the `dispatch({ type: "ADAPTIVE_CARD_LOADING" })` line.

Full replacement of the function body:

```javascript
const goToNextCard = useCallback(
  async (signals) => {
    // If no session or no signals, just advance index
    if (!state.session || !signals) {
      dispatch({ type: "NEXT_CARD" });
      return;
    }
    // Pre-generated card is available at the next index — skip adaptive API
    if (state.currentCardIndex < state.cards.length - 1) {
      dispatch({ type: "NEXT_CARD" });
      return;
    }
    // Ceiling reached: record interaction but skip LLM generation
    if (state.cards.length >= MAX_ADAPTIVE_CARDS) {
      recordCardInteraction(state.session.id, signals).catch((err) =>
        console.error("[SessionContext] card interaction failed:", err)
      );
      dispatch({ type: "NEXT_CARD" });
      return;
    }
    dispatch({ type: "ADAPTIVE_CARD_LOADING" });
    try {
      const res = await completeCardAndGetNext(state.session.id, signals);
      trackEvent("adaptive_card_loaded", {
        card_index:              res.data.card_index,
        adaptation:              res.data.adaptation_applied,
        speed:                   res.data.learning_profile_summary?.speed,
        comprehension:           res.data.learning_profile_summary?.comprehension,
        engagement:              res.data.learning_profile_summary?.engagement,
        confidence:              res.data.learning_profile_summary?.confidence_score,
        performance_vs_baseline: res.data.performance_vs_baseline,
      });
      dispatch({ type: "ADAPTIVE_CARD_LOADED", payload: res.data });
      useAdaptiveStore.getState().updateMode(res.data.learning_profile_summary);
      useAdaptiveStore.getState().awardXP(5);
    } catch (err) {
      dispatch({ type: "ADAPTIVE_CARD_ERROR" });
    }
  },
  [state.session, state.cards.length, state.currentCardIndex]
);
```

Note: `state.currentCardIndex` is added to the `useCallback` dependency array (it was absent before).

---

### CHG-4 — null guard in `CardLearningView.jsx` (line 517)

Replace:
```javascript
if (!card) return null;
```

With:
```javascript
if (!card) {
  return (
    <div className="flex gap-4 items-start">
      <div className="flex-1 min-w-0" style={{ textAlign: "center", paddingTop: "4rem" }}>
        <p style={{
          color: "var(--color-text-muted)",
          fontSize: "1rem",
          marginBottom: "1.5rem",
        }}>
          {t("learning.noCardsError")}
        </p>
        <button
          onClick={() => { reset(); navigate("/map"); }}
          style={{
            padding: "0.6rem 1.4rem",
            borderRadius: "8px",
            background: "var(--color-primary)",
            color: "#fff",
            fontWeight: 600,
            border: "none",
            cursor: "pointer",
          }}
        >
          {t("learning.backToMap")}
        </button>
      </div>
      <div style={{ width: "320px", flexShrink: 0 }}>
        <AssistantPanel />
      </div>
    </div>
  );
}
```

`reset` must be destructured from `useSession()` and `navigate` from `useNavigate()` (both already imported or trivially added). Confirm `reset` is already available in the component's destructured context.

---

### i18n keys — `en.json`

Add after `"learning.generatingCard"` (line 113):

```json
"learning.generatingCards": "ADA is preparing your lesson cards...",
"learning.noCardsError": "No cards could be loaded for this lesson. Please go back and try again."
```

The same two keys must be added to all 12 other locale files (`ar.json`, `de.json`, `es.json`, `fr.json`, `hi.json`, `ja.json`, `ko.json`, `ml.json`, `pt.json`, `si.json`, `ta.json`, `zh.json`). Use the English values as temporary placeholders until translation is complete. i18next `fallbackLng: "en"` is already configured and will serve as a safety net.

---

## Key Decisions Requiring Stakeholder Input

1. **`NEXT_CARD` clamp behaviour at ceiling:** After the clamp, dispatching `NEXT_CARD` at the last pre-gen card is now a no-op (index stays the same). The `handleNextCard` caller in `CardLearningView.jsx` only invokes this path when `currentCardIndex < cards.length - 1`, so in normal flow the clamp never fires. However, confirm that no other caller depends on the unclamped over-increment behaviour.

2. **`reset()` call in error UI:** CHG-4 calls `reset()` before navigating back to the map. This clears the session state entirely. If students should be able to re-enter the lesson rather than starting fresh, the product team must decide whether `reset()` is the right call or whether partial state should be preserved.

3. **`useCallback` dependency addition:** `state.currentCardIndex` is added to `goToNextCard`'s dependency array. This is the correct fix but means the callback reference changes on every card navigation. Downstream consumers that hold a stale reference to `goToNextCard` via their own `useCallback` or `useMemo` will need to include `goToNextCard` in their deps. Audit `handleNextCard` in `CardLearningView.jsx` for this dependency.
