# Execution Plan — Chunk Card Quality Fix

## 1. Work Breakdown Structure (WBS)

| ID | Title | Description | Effort | Dependencies | Component |
|----|-------|-------------|--------|-------------|-----------|
| P1-1 | Fix user prompt instruction | Change lines 140–141 in `build_chunk_card_prompt()` from "interleaved" to "COMBINED" wording | 0.25 d | — | `prompt_builder.py` |
| P1-2 | Raise CHUNK_MAX_TOKENS_NORMAL | Update constant from 2000 → 5000 in `config.py` | 0.25 d | — | `config.py` |
| P1-3 | Switch model to gpt-4o (primary call) | Change `model="mini"` → `model="main"` on line 1535 of `generate_per_chunk` | 0.25 d | — | `teaching_service.py` |
| P1-4 | Switch model to gpt-4o (retry call) | Same change on line 1559 (retry `_chat` call) | 0.1 d | P1-3 | `teaching_service.py` |
| P1-5 | Add backend image fallback | Insert image injection loop after normalisation, before synthetic fallback | 0.5 d | — | `teaching_service.py` |
| P2-1 | Unit tests | Write `test_chunk_card_quality.py` covering 6 test cases as specified in DLD §9 | 0.75 d | P1-1, P1-2, P1-5 | `backend/tests/` |
| P2-2 | Manual smoke test | Load a chunk with images, verify combined card format + image display | 0.25 d | P1-1 – P1-5 | — |

**Total estimated effort: 2.35 developer-days**

---

## 2. Phased Delivery Plan

### Phase 1 — Code Fixes (Day 1)
All four code changes are independent and can be implemented in any order within the same working session.

- P1-1: Fix prompt instruction
- P1-2: Raise token budget constant
- P1-3 + P1-4: Switch model calls
- P1-5: Add image fallback

### Phase 2 — Testing and Validation (Day 2)
- P2-1: Write and run unit tests
- P2-2: Manual smoke test against live backend

---

## 3. Dependencies and Critical Path

```
P1-1 ──┐
P1-2 ──┤
P1-3 ──┤──→ P1-4 ──┐
P1-5 ──┘            ├──→ P2-1 ──→ P2-2
```

Critical path: P1-3 → P1-4 → P2-1 → P2-2 (1.35 d)

No external team dependencies. No Alembic migration required. No frontend changes required.

---

## 4. Definition of Done

### Phase 1 DoD
- [ ] `build_chunk_card_prompt()` no longer contains the word "interleaved"
- [ ] `build_chunk_card_prompt()` contains "COMBINED" in the closing generation instruction
- [ ] `config.py` `CHUNK_MAX_TOKENS_NORMAL == 5000`
- [ ] Both `_chat(model="mini")` calls in `generate_per_chunk` changed to `model="main"`
- [ ] Image fallback loop present and guarded by `if images:`
- [ ] Backend starts cleanly with `python -m uvicorn src.api.main:app --reload --port 8889`

### Phase 2 DoD
- [ ] All 6 unit tests in `test_chunk_card_quality.py` pass
- [ ] Manual smoke test: at least one card in a chunk session shows an image
- [ ] Manual smoke test: no card is content-only or MCQ-only (every card has both fields)
- [ ] No regressions in existing test suite (`test_per_card_adaptive.py`, `test_universal_cards.py`)

---

## 5. Rollout Strategy

**Deployment approach:** Direct merge to main. No feature flag needed — all changes are either constant updates or prompt text changes with no schema impact.

**Rollback plan:**
- Issue 3 (token): revert `CHUNK_MAX_TOKENS_NORMAL` to 2000 in `config.py`
- Issue 4 (model): revert `model="main"` to `model="mini"` in both `_chat` calls
- Issues 1 and 2 (prompt + fallback): revert `prompt_builder.py` and `teaching_service.py` to previous commit

All rollbacks are single-file changes achievable with `git revert` or manual edit.

**Post-launch validation:**
1. Trigger a fresh chunk card generation for a concept with known images.
2. Confirm response JSON has `image_url` populated on at least one card.
3. Confirm every card in the response has both `content` and `question` fields non-null.
4. Check backend logs for absence of `[per-chunk] first attempt empty` warnings (indicates model is following instructions).

---

## 6. Effort Summary Table

| Phase | Key Tasks | Estimated Effort | Team Members Needed |
|-------|-----------|-----------------|---------------------|
| Phase 1 — Code Fixes | P1-1 through P1-5 | 1.35 d | 1 backend developer |
| Phase 2 — Testing | P2-1, P2-2 | 1.0 d | 1 backend developer |
| **Total** | | **2.35 d** | **1 backend developer** |

---

## Key Decisions Requiring Stakeholder Input

1. **Cost sign-off:** gpt-4o costs approximately 3–4× more per token than gpt-4o-mini. The chunk generation path is called once per chunk per student session. Confirm the cost increase is acceptable before deploying.
2. **`CHUNK_MAX_TOKENS_STRUGGLING` anomaly:** After this fix, NORMAL (5000) > STRUGGLING (3000). This is semantically backwards. A follow-up task should raise STRUGGLING to at least 6000 and FAST to at least 2500. Out of scope for this fix but should be tracked.
3. **Image fallback strategy:** Current design assigns `images[0]` to all image-null cards in the chunk. If the preferred behaviour is to only assign the image to the first card in the chunk (not all), the fallback loop needs an early-break condition. Confirm before implementation.
