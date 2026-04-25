# DLD — Complete i18n Coverage + Admin Re-trigger Invalidation

**Feature slug:** `i18n-complete-coverage`
**Date:** 2026-04-24
**Status:** Phase 0 — Design

---

## 1. `invalidate_chunk_cache` Helper

### Signature

```python
# backend/src/api/teaching_service.py

async def invalidate_chunk_cache(
    db: AsyncSession,
    chunk_ids: list[str],
) -> int:
    """
    For every active TeachingSession whose concepts_queue references any of
    chunk_ids, clear those chunks' exam_questions_by_chunk entries across all
    language slices, and also remove any cached card entries for those chunks.

    Returns the count of sessions modified.
    """
```

### Algorithm

```
1. Query TeachingSession rows where:
   - completed_at IS NULL  (active sessions only)
   - presentation_text::jsonb contains any of chunk_ids in concepts_queue
     (JSONB containment check or LIKE fallback for non-JSONB setups)

2. For each matching session:
   a. ca = CacheAccessor(session.presentation_text, language="en")
   b. For each lang_code in ca._data["by_language"]:
       lang_slice = ca.get_slice(lang_code)
       # Clear exam questions for each affected chunk
       eq_map = lang_slice.get("exam_questions_by_chunk", {})
       for chunk_id in chunk_ids:
           eq_map.pop(str(chunk_id), None)
       lang_slice["exam_questions_by_chunk"] = eq_map
       # Clear cached cards that originated from the affected chunks.
       # Cards store chunk_id in the "chunk_id" field (added in card schema).
       lang_slice["cards"] = [
           c for c in lang_slice.get("cards", [])
           if str(c.get("chunk_id", "")) not in {str(cid) for cid in chunk_ids}
       ]
       ca.set_slice(lang_slice, lang=lang_code)
   c. session.presentation_text = ca.to_json()

3. await db.flush()  # caller commits after all admin handler logic completes

4. Log: "[invalidate] sessions_invalidated={count} chunk_ids={chunk_ids}"

5. Return count
```

**Notes:**
- The helper does **not** call `db.commit()` itself; the admin handler owns the transaction so invalidation is atomic with the content change.
- The JSONB query uses `CAST(presentation_text AS TEXT) LIKE '%<chunk_id>%'` as a conservative fallback when the column is not indexed as JSONB. This is acceptable because invalidation is a low-frequency admin operation.
- If `chunk_ids` is empty, the function returns 0 immediately.

---

## 2. CacheAccessor Schema Extension

### Before (current)

```json
{
  "cache_version": 3,
  "by_language": {
    "ml": {
      "presentation": "...",
      "cards": [...],
      "concepts_queue": ["chunk-uuid-1", "chunk-uuid-2"],
      "concepts_covered": ["chunk-uuid-1"]
    }
  }
}
```

### After (extended)

```json
{
  "cache_version": 3,
  "by_language": {
    "ml": {
      "presentation": "...",
      "cards": [...],
      "concepts_queue": ["chunk-uuid-1", "chunk-uuid-2"],
      "concepts_covered": ["chunk-uuid-1"],
      "exam_questions_by_chunk": {
        "chunk-uuid-1": [
          {"index": 0, "text": "..."},
          {"index": 1, "text": "..."}
        ]
      }
    }
  }
}
```

**New accessor methods on `CacheAccessor`:**

```python
def get_exam_questions(self, chunk_id: str, lang: str | None = None) -> list[dict] | None:
    """Return cached exam questions for chunk_id in lang, or None if not cached."""
    sl = self.get_slice(lang)
    return sl.get("exam_questions_by_chunk", {}).get(str(chunk_id))

def set_exam_questions(self, chunk_id: str, questions: list[dict], lang: str | None = None) -> None:
    """Store exam questions for chunk_id in lang slice."""
    sl = self.get_slice(lang)
    eq = sl.setdefault("exam_questions_by_chunk", {})
    eq[str(chunk_id)] = questions
    self.set_slice(sl, lang=lang)

def clear_exam_questions(self, chunk_id: str) -> None:
    """Remove exam questions for chunk_id from every language slice."""
    for lang_code, sl in self._data.get("by_language", {}).items():
        sl.get("exam_questions_by_chunk", {}).pop(str(chunk_id), None)
```

**Interaction with existing `mark_stale(lang)`:** Calling `mark_stale("ml")` deletes the entire `"ml"` key from `by_language`, which includes `exam_questions_by_chunk`. No additional clearing needed for language switches — the existing mechanism handles it correctly.

---

## 3. Exam Question Flow — Before vs After

### Before (current)

```
POST /chunk-cards/next
  └─ teaching_router.py:971–1045
       └─ Always calls LLM (gpt-4o-mini) per request
       └─ Questions returned in response, NOT stored
       └─ Client holds questions in React state
       └─ Language switch: cache bust removes cards, but client still
          holds previous language questions in state until re-enter chunk
```

### After (new)

```
POST /chunk-cards/next
  └─ teaching_router.py (refactored)
       ├─ ca = CacheAccessor(session.presentation_text, language=student_lang)
       ├─ cached_q = ca.get_exam_questions(req.chunk_id)
       ├─ if cached_q is not None:
       │    questions = [ChunkExamQuestion(**q, chunk_id=req.chunk_id) for q in cached_q]
       └─ else:
            ├─ Call LLM (existing logic, lines 995–1045)
            ├─ ca.set_exam_questions(req.chunk_id, [q.dict() for q in questions])
            └─ session.presentation_text = ca.to_json()

Language switch (PATCH /students/{id}/language):
  └─ mark_stale(new_lang) clears entire slice including exam questions
  └─ Returns session_cache_cleared: true
  └─ Frontend: reloadCurrentChunk() + RELOAD_EXAM_QUESTIONS dispatch

Admin edit (any mutation):
  └─ invalidate_chunk_cache(db, [chunk_id]) clears exam slice for that chunk
  └─ Student's next /chunk-cards call regenerates in their language
```

---

## 4. Admin Handler Hook List

Every handler below must call `invalidate_chunk_cache(db, chunk_id_list)` **after** the DB mutation and **before** `db.commit()`.

| File | Line (approx.) | Handler | Chunk IDs to pass | Notes |
|------|---------------|---------|-------------------|-------|
| `admin_router.py` | ~1789 | `update_chunk` | `[chunk_id]` | After `setattr()` mutations |
| `admin_router.py` | ~1858 | `toggle_chunk_visibility` | `[chunk_id]` | |
| `admin_router.py` | ~1905 | `toggle_chunk_exam_gate` | `[chunk_id]` | Clears exam question cache too |
| `admin_router.py` | ~1954 | `merge_chunks` | `[id1, id2]` | Merged result is a new chunk; clear both |
| `admin_router.py` | ~2108 | `split_chunk` | `[chunk_id]` | Original chunk replaced; clear original |
| `admin_router.py` | ~2441 | `rename_section` | `affected_chunk_ids` (already computed at line ~2459) | List of all chunk IDs in section |
| `admin_router.py` | ~2498 | `toggle_section_optional` | All chunk IDs in section | Query chunks where `concept_id = sec.concept_id` |
| `admin_router.py` | ~2554 | `toggle_section_exam_gate` | All chunk IDs in section | Clears exam question cache |
| `admin_router.py` | ~2610 | `toggle_section_visibility` | All chunk IDs in section | |
| `admin_router.py` | ~2671 | `promote_subsection_to_section` | `[chunk_id]` + all sibling chunks after it | Affects section membership |
| `admin_router.py` | ~2975 | `modify_graph_edge` (add/remove) | All chunks in both source and target concepts | Graph change affects card ordering |
| `audit_service.py` | each `_undo_*` and `_redo_*` helper | Every undo/redo helper | Same chunk IDs as original operation | Add one `await invalidate_chunk_cache(...)` call per helper |

**Import required in both files:**
```python
from api.teaching_service import invalidate_chunk_cache
```

---

## 5. Locale Key Catalogue

### 5a. Tutor Styles

| Key | English Value |
|-----|--------------|
| `tutorStyles.default` | `"Default"` |
| `tutorStyles.pirate` | `"Pirate"` |
| `tutorStyles.astronaut` | `"Space"` |
| `tutorStyles.gamer` | `"Gamer"` |

### 5b. Interests

| Key | English Value |
|-----|--------------|
| `interests.Sports` | `"Sports"` |
| `interests.Gaming` | `"Gaming"` |
| `interests.Music` | `"Music"` |
| `interests.Movies` | `"Movies"` |
| `interests.Food` | `"Food"` |
| `interests.Animals` | `"Animals"` |
| `interests.Space` | `"Space"` |
| `interests.Technology` | `"Technology"` |
| `interests.Art` | `"Art"` |
| `interests.Nature` | `"Nature"` |

### 5c. Admin Content Editor (`adminContent.*`)

Enumerated from `AdminBookContentPage.jsx` and `PrereqAccordion` component:

| Key | English String / Source Location |
|-----|----------------------------------|
| `adminContent.contentEditor` | `"Content Editor"` (header suffix, line ~535) |
| `adminContent.published` | `"Published"` (status badge, line ~555) |
| `adminContent.draftUnsaved` | `"Draft — unsaved"` (dirty badge, line ~558) |
| `adminContent.loading` | `"Loading..."` (loading state, line ~527) |
| `adminContent.noSectionsFound` | `"No sections found"` (empty left panel, line ~569) |
| `adminContent.chapter` | `"Chapter"` (chapter header prefix, line ~574) |
| `adminContent.hidden` | `"hidden"` (section hidden badge, line ~617) |
| `adminContent.selectSection` | `"Select a section from the left panel"` (center empty state, line ~725) |
| `adminContent.loadingChunks` | `"Loading chunks..."` (chunk loading, line ~728) |
| `adminContent.noChunksFound` | `"No chunks found for this section"` (chunk empty state, line ~730) |
| `adminContent.renameSectionTitle` | `"New section name:"` (window.prompt label, line ~395) |
| `adminContent.unsavedChangesTitle` | `"Unsaved Changes"` (dialog title, line ~411) |
| `adminContent.unsavedChangesMsg` | `"This section has unsaved chunk edits that will be discarded. Continue?"` (dialog, line ~411) |
| `adminContent.continueBtn` | `"Continue"` (dialog confirm, line ~411) |
| `adminContent.renameBook` | `"Rename book"` (button title, line ~549) |
| `adminContent.renameBookPrompt` | `"Rename book:"` (prompt label, line ~538) |
| `adminContent.failedRenameBook` | `"Failed to rename book:"` (alert prefix, line ~545) |
| `adminContent.toggleOptionalBtn` | `"Opt"` (section toggle button, line ~654) |
| `adminContent.toggleExamBtn` | `"E"` (exam gate toggle, line ~667) |
| `adminContent.showBtn` | `"Show"` (show section, line ~679) |
| `adminContent.hideBtn` | `"Hide"` (hide section, line ~679) |
| `adminContent.renameSectionTitle2` | `"Rename section"` (button title attribute, line ~639) |
| `adminContent.editBtn` | `"Edit"` (chunk inline edit, line ~753) |
| `adminContent.requiredBtn` | `"Required"` (toggle optional off, line ~754) |
| `adminContent.optionalBtn` | `"Optional"` (toggle optional on, line ~754) |
| `adminContent.enableExamBtn` | `"Enable Exam"` (toggle exam disabled, line ~755) |
| `adminContent.noExamBtn` | `"No Exam"` (exam disabled label, line ~755) |
| `adminContent.mergeDownBtn` | `"Merge ↓"` (merge with next chunk, line ~789) |
| `adminContent.splitBtn` | `"Split"` (split chunk, line ~798) |
| `adminContent.promoteBtn` | `"Promote"` (promote to section, line ~827) |
| `adminContent.promotedSuccess` | `"Promoted"` (toast title, line ~818) |
| `adminContent.promotedDesc` | `"Chunk promoted to new section"` (toast body, line ~818) |
| `adminContent.promoteSectionPrompt` | `"New section label (optional):"` (prompt, line ~803) |
| `adminContent.regenBtn` | `"Regen"` (regenerate embedding, line ~840) |
| `adminContent.toExerciseBtn` | `"→ Exercise"` (chunk type toggle, line ~782) |
| `adminContent.toTeachingBtn` | `"→ Teaching"` (chunk type toggle, line ~782) |
| `adminContent.mergeSaveNote` | `"Merge these two chunks? This will be applied when you save."` (dialog message, line ~368) |
| `adminContent.mergeChunksTitle` | `"Merge Chunks"` (dialog title, line ~368) |
| `adminContent.mergeBtn` | `"Merge"` (dialog confirm, line ~368) |
| `adminContent.discardChangesTitle` | `"Discard Changes"` (dialog title, line ~521) |
| `adminContent.discardChangesMsg` | `"Discard all unsaved changes? This cannot be undone."` (dialog, line ~521) |
| `adminContent.discardBtn` | `"Discard"` (dialog confirm + bottom bar, line ~521 + ~982) |
| `adminContent.saveChangesBtn` | `"Save Changes"` (bottom bar, line ~990) |
| `adminContent.savingBtn` | `"Saving..."` (saving in progress, line ~990) |
| `adminContent.savedTitle` | `"Saved"` (toast title, line ~514) |
| `adminContent.savedDesc` | `"All changes applied successfully"` (toast body, line ~514) |
| `adminContent.saveFailedTitle` | `"Save Failed"` (toast title, line ~516) |
| `adminContent.regenAllTitle` | `"Regenerate All Embeddings"` (dialog title, line ~491) |
| `adminContent.regenAllBtn` | `"Regenerate Embeddings"` (bottom bar, line ~1023) |
| `adminContent.regeneratingBtn` | `"Regenerating..."` (busy state, line ~1023) |
| `adminContent.allEmbeddingsOk` | `"All embeddings OK"` (status, line ~1004) |
| `adminContent.staleEmbeddingsMsg` | `"stale embedding(s)"` (status count, line ~1001) |
| `adminContent.splitHereBtn` | `"✂ Split here"` (split position marker, line ~914) |
| `adminContent.cancelBtn` | `"Cancel"` (inline edit cancel, line ~869) |
| `adminContent.saveBtn` | `"Save"` (inline edit save, line ~861) |
| `adminContent.newSplitBadge` | `"New (split)"` (temp chunk badge, line ~883) |
| `adminContent.modifiedBadge` | `"Modified"` (chunk modified indicator, line ~880) |
| `adminContent.staleBadge` | `"stale"` (left panel stale indicator, line ~705) |
| `adminContent.contentUpdatedTitle` | `"Content updated"` (undo/redo toast, line ~267) |
| `adminContent.contentUpdatedDesc` | `"Unsaved drafts cleared. Content re-fetched from server."` (toast body, line ~267) |
| `adminContent.prereqSectionTitle` | `"Prerequisites"` (right panel header, line ~123) |
| `adminContent.sections` | `"sections"` (graph info label, line ~126) |
| `adminContent.edges` | `"edges"` (graph info label, line ~127) |
| `adminContent.noPrereqs` | `"No prerequisites"` (prereq accordion, line ~149) |
| `adminContent.addPrereqBtn` | `"+ Add prerequisite"` (prereq button, line ~170) |
| `adminContent.selectOption` | `"Select..."` (prereq select placeholder, line ~163) |
| `adminContent.addBtn` | `"Add"` (prereq add confirm, line ~166) |
| `adminContent.removePrereqTitle` | `"Remove Prerequisite"` (dialog title, line ~111) |
| `adminContent.confirmBtn` | `"Confirm"` (dialog confirm, line ~111) |
| `adminContent.errorTitle` | `"Error"` (generic error toast title, line ~106) |
| `adminContent.failedAddPrereq` | `"Failed to add prerequisite"` (error fallback, line ~107) |
| `adminContent.optionalBadge` | `"Optional"` (chunk inline badge, line ~889) |
| `adminContent.hiddenBadge` | `"Hidden"` (chunk inline badge, line ~892) |
| `adminContent.noExamBadge` | `"No Exam"` (chunk inline badge, line ~895) |
| `adminContent.staleEmbeddingBadge` | `"Stale embedding"` (chunk inline badge, line ~898) |
| `adminContent.clickToDivider` | `"Click a divider to split at that point:"` (split mode helper, line ~907) |

**Note on `window.prompt()` calls:** `handleRenameSection()` (line ~395) and the promote-to-section handler (line ~803) currently call `window.prompt()`. Per the plan, these must be replaced with `dialog.prompt()` from `DialogProvider` so the label string becomes translatable. This is a frontend developer task in Phase 3.

---

## 6. Tutor Style / Interest Constants File Change

### Current (`frontend/src/constants/tutorPreferences.js`)

```js
export const TUTOR_STYLES = [
  { id: "default", label: "Default", emoji: "📖" },
  { id: "pirate",  label: "Pirate",  emoji: "🏴‍☠️" },
  { id: "astronaut", label: "Space", emoji: "🚀" },
  { id: "gamer",   label: "Gamer",   emoji: "🎮" },
];

export const INTEREST_OPTIONS = [
  { id: "Sports", emoji: "⚽" },
  ...
];
```

### After (Phase 3 change)

```js
// label field REMOVED — consumers call t(`tutorStyles.${id}`)
export const TUTOR_STYLES = [
  { id: "default", emoji: "📖" },
  { id: "pirate",  emoji: "🏴‍☠️" },
  { id: "astronaut", emoji: "🚀" },
  { id: "gamer",   emoji: "🎮" },
];

// No change to INTEREST_OPTIONS structure — id IS the t() lookup key
export const INTEREST_OPTIONS = [
  { id: "Sports", emoji: "⚽" },
  ...
];
```

**Call site changes:**

| File | Current | After |
|------|---------|-------|
| `RegisterPage.jsx:~532` | `style.label` | `t(\`tutorStyles.${style.id}\`)` |
| `SettingsPage.jsx:~318` | `style.label` | `t(\`tutorStyles.${style.id}\`)` |
| Any other render of `TUTOR_STYLES` | same | same pattern |
| Any render of `INTEREST_OPTIONS` | `opt.id` (was already id) | `t(\`interests.${opt.id}\`)` |

No change to `student.preferred_style` or `student.interests` stored values — they already store the English ID.

---

## 7. LanguageSelector Re-fetch Flow

### Current flow (LanguageSelector.jsx:49–58)

```
PATCH /students/{id}/language
  ├─ i18n.changeLanguage(lang.code)
  ├─ dispatch LANGUAGE_CHANGED (translates chunk headings in SessionContext)
  └─ if session_cache_cleared: reloadCurrentChunk()
```

`reloadCurrentChunk()` re-fetches `/chunk-cards/next` which returns new cards. But exam questions are returned separately and the client still holds the previous language questions in state.

### After (Phase 3 change)

```
PATCH /students/{id}/language
  ├─ i18n.changeLanguage(lang.code)
  ├─ dispatch LANGUAGE_CHANGED (translates chunk headings)
  └─ if session_cache_cleared:
       ├─ await reloadCurrentChunk()       // existing call — reloads cards
       └─ dispatch RELOAD_EXAM_QUESTIONS   // NEW — triggers /chunk-cards re-fetch
                                           // which now returns cached questions in new lang
```

**Implementation:** Add `RELOAD_EXAM_QUESTIONS` action to `SessionContext.jsx`. The reducer clears `examQuestions` from state, which triggers the existing `useEffect` that fetches exam questions when they are null.

Alternatively (simpler): `reloadCurrentChunk()` already calls `POST /chunk-cards/next` which now returns questions from the new-language cache slice. If `SessionContext` always overwrites `examQuestions` from this response, no new action is needed — only confirming that the response consumer updates the state field.

**Recommendation:** Confirm that the `chunk-cards` response handler in `SessionContext.jsx` always replaces `examQuestions` (not appends). If so, no new action needed; `reloadCurrentChunk()` is sufficient.

---

## 8. Sequence Diagrams

### 8a. Admin Edit → Student Sees Updated Card

```
Admin            admin_router.py          teaching_service.py      DB (TeachingSession)
  |                     |                         |                        |
  |-- PATCH /chunks/X --|                         |                        |
  |                     |-- update chunk fields --|                        |
  |                     |-- invalidate_chunk_cache([X]) -->               |
  |                     |                         |-- SELECT sessions WHERE|
  |                     |                         |   presentation_text LIKE %X% --
  |                     |                         |<-- matching sessions --|
  |                     |                         |-- for each session:   |
  |                     |                         |   clear exam_questions_by_chunk[X]
  |                     |                         |   clear cards where chunk_id=X
  |                     |                         |-- UPDATE session rows -|
  |                     |-- db.commit() ----------|                        |
  |<-- 200 OK ----------|                         |                        |
  |
Student          teaching_router.py        LLM (gpt-4o-mini)
  |                     |                         |
  |-- POST /chunk-cards/next (chunk_id=X) --------|
  |                     |-- get_exam_questions(X) -> None (cache miss)
  |                     |-- call LLM for cards (already existing) ------->|
  |                     |                                                  |
  |                     |-- call LLM for exam questions ----------------->|
  |                     |<-- questions in student's language --------------|
  |                     |-- set_exam_questions(X, questions)
  |                     |-- session.presentation_text = ca.to_json()
  |                     |-- db.commit()
  |<-- 200 with new cards + new questions in student's language
```

### 8b. Language Switch → Exam Questions Reload

```
Student          LanguageSelector.jsx     teaching_router.py (PATCH)   SessionContext
  |                     |                         |                        |
  |-- select Tamil ---  |                         |                        |
  |                     |-- PATCH /language/ta ---|                        |
  |                     |                         |-- mark_stale("ta")     |
  |                     |                         |   (clears "ta" slice)  |
  |                     |                         |-- db.commit()          |
  |                     |<-- {session_cache_cleared: true, translated_headings: [...]}
  |                     |-- i18n.changeLanguage("ta")                      |
  |                     |-- dispatch LANGUAGE_CHANGED ------------------>  |
  |                     |-- await reloadCurrentChunk() ----POST /chunk-cards/next
  |                     |                         |-- cache miss for "ta" slice
  |                     |                         |-- LLM generates cards in Tamil
  |                     |                         |-- LLM generates exam questions in Tamil
  |                     |                         |-- stores both in "ta" slice
  |                     |<-- cards + questions in Tamil -----------------  |
  |                     |                                   dispatch overwrites examQuestions
  |<-- UI shows Tamil cards + Tamil exam questions
```

---

## 9. Security Design

- No new authenticated surfaces; all admin handlers already gated by `require_admin` dependency.
- `invalidate_chunk_cache` does not accept `chunk_ids` from user input — the IDs come from the DB (pre-validated by the chunk lookup). No injection risk.
- Locale files are static JSON shipped with the frontend build; no runtime user influence.

---

## 10. Observability Design

| Signal | What | Where |
|--------|------|-------|
| Log INFO | `[invalidate] sessions_invalidated={n} chunk_ids={ids}` | `teaching_service.invalidate_chunk_cache` |
| Log INFO | `[exam-cache] hit chunk_id={id} lang={lang}` | `teaching_router.py` exam path |
| Log INFO | `[exam-cache] miss chunk_id={id} lang={lang} — generating` | `teaching_router.py` exam path |
| Log WARNING | `[invalidate] large_scope chunk_count={n} — consider batching` | When n > 50 chunks |
| Metric (existing) | `i18n_session_cache_eviction_total` | `CacheAccessor.set_slice()` already emits |

---

## 11. Error Handling & Resilience

| Scenario | Handling |
|---------|---------|
| `invalidate_chunk_cache` fails mid-loop | Log warning and continue; do not fail the admin request. Stale cache is a degraded UX, not a data-corruption risk. |
| Exam question LLM call fails | Existing retry + fallback to empty list (lines 1026–1045). Cache nothing if generation fails. |
| `presentation_text` exceeds 512 KB after exam question addition | `CacheAccessor.set_slice()` eviction logic handles this automatically. |
| Language PATCH times out (existing 3s timeout) | HTTP 503 already returned; exam question state not corrupted. |
| `window.prompt()` replacement with `dialog.prompt()` — user cancels | Return `null` from dialog; handler returns early without mutation (same behaviour as current). |

---

## 12. Testing Strategy

### Backend Unit Tests

| Test File | Coverage |
|-----------|---------|
| `test_cache_accessor_exam_questions.py` | `get_exam_questions`, `set_exam_questions`, `clear_exam_questions`; interaction with `mark_stale()`; size cap |
| `test_invalidate_chunk_cache.py` | Helper with 0/1/N sessions; sessions not touching affected chunk unchanged; all language slices cleared |
| `test_language_switch_regenerates_exam_questions.py` | PATCH → cache miss → LLM called → Tamil questions returned |
| `test_admin_edit_invalidates_student_cache.py` | Parametrised over all 11 admin handlers + undo + redo |
| `test_mcq_options_respect_language.py` | `_language_instruction` present in every student-facing LLM call path |

### Frontend E2E (Playwright)

| Spec | Coverage |
|------|---------|
| `non-english-student.spec.js` | Full Malayalam student journey; switch to Tamil mid-session; no English strings visible |
| `admin-content-crud.spec.js` | All admin mutations; concurrent student session reflects change within next card fetch |
| `admin-i18n.spec.js` | Admin UI in Tamil; every visible string non-English |

### Contract Testing

- `PATCH /students/{id}/language` response schema unchanged (only `session_cache_cleared` field already present is used).
- `POST /chunk-cards/next` response schema unchanged (questions field already present; now populated from cache on hits).

---

## Key Decisions Requiring Stakeholder Input

1. **`window.prompt()` replacement scope:** Should both `handleRenameSection` and the promote-to-section label prompt be replaced with `dialog.prompt()` in Phase 3, or only the rename (the promote label is optional and defaults to empty)? Replacing both is cleaner but increases Phase 3 scope.

2. **Exam question cache TTL:** Currently cached forever (until admin edit or language switch). Should there be a time-based expiry (e.g. 24 hours) to prevent very long-lived sessions from serving outdated questions? Current design has no TTL.

3. **`invalidate_chunk_cache` failure policy:** Current design logs a warning and continues rather than failing the admin request. Stakeholders should confirm that a degraded-UX-but-not-blocking approach is acceptable, or whether admin edit should be transactional (fail if invalidation fails).
