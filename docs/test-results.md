# Student Simulation Test Results

File: `backend/tests/test_student_simulations.py`
Generated: 2026-03-15
Framework: pytest + requests (synchronous, live backend)
Backend: http://localhost:8889
Marker: `@pytest.mark.e2e`

## Test Inventory

| # | Test ID | Class / Function | Business Criterion | Expected Status |
|---|---------|------------------|--------------------|-----------------|
| 1a | `TestAllSectionsCardStructure::test_card_structure_concept_1` | `TestAllSectionsCardStructure` | All cards for INTRODUCTION_TO_WHOLE_NUMBERS have `title`, `content`, `card_type`; non-CHECKIN cards have `question` and `question2` each with 4 options | PENDING — requires live backend |
| 1b | `TestAllSectionsCardStructure::test_card_structure_concept_2` | `TestAllSectionsCardStructure` | Same structure validation for ADD_WHOLE_NUMBERS | PENDING — requires live backend |
| 1c | `TestAllSectionsCardStructure::test_card_structure_concept_3` | `TestAllSectionsCardStructure` | Same structure validation for SUBTRACT_WHOLE_NUMBERS | PENDING — requires live backend |
| 2 | `test_fast_student` | standalone | Student answering all MCQs correct in 12 s each receives `learning_profile_summary.speed == "FAST"` | PENDING — requires live backend |
| 3 | `test_struggling_student` | standalone | Student with `wrong_attempts=2` and `re_explain_card_title` set on 3+ cards receives at least one non-null `recovery_card` | PENDING — requires live backend |
| 4 | `test_normal_student` | standalone | Student alternating correct and 1-wrong cards over 4 cards is not classified as `FAST` or `STRUGGLING` | PENDING — requires live backend |
| 5 | `test_mode_transition` | standalone | Mode after 3 fast-correct cards differs from mode after 3 slow-wrong cards (adaptive engine responds to signal changes) | PENDING — requires live backend |
| 6 | `test_recovery_card_not_nested` | standalone | Calling `complete-card` with a title starting "Let's Try Again" returns `recovery_card=None` (anti-loop guard active); no crash | PENDING — requires live backend |
| 7 | `test_consecutive_recoveries` | standalone | 3 consecutive cards with `wrong_attempts=2` and distinct titles each produce a recovery card with a non-null, non-empty title | PENDING — requires live backend |
| 8 | `test_last_card_completion` | standalone | After recording interactions for all cards, `POST /complete-cards` returns HTTP 200 and session advances to `CARDS_DONE` | PENDING — requires live backend |
| 9 | `test_last_card_both_wrong` | standalone | `complete-card` with `wrong_attempts=2` on the last card returns HTTP 200; subsequent `POST /complete-cards` also returns HTTP 200 | PENDING — requires live backend |
| 10 | `test_cross_section_profile_persistence` | standalone | After a struggling section 1 (section-complete with `state_score=1.0`), section 2 `next-section-cards` returns `current_mode` of `SLOW` or `NORMAL` (not `FAST`); `state_distribution.struggling >= 1` | PENDING — requires live backend |

## How to Run

```bash
# Run all 10 simulation tests (requires live backend on port 8889)
cd backend
pytest tests/test_student_simulations.py -v -m e2e

# Run a single test
pytest tests/test_student_simulations.py::test_fast_student -v

# Run with extended timeout output (tests can take 2–5 min total due to LLM calls)
pytest tests/test_student_simulations.py -v -m e2e --timeout=300
```

## Prerequisites

- Backend running: `python -m uvicorn src.api.main:app --reload --port 8889`
- `API_SECRET_KEY` set in `backend/.env`
- Prealgebra ChromaDB data loaded in `backend/output/prealgebra/chroma_db/`
- PostgreSQL running with ADA schema applied

## Notes

- Tests 2–7 use `POST /api/v2/sessions/{id}/complete-card` (from `adaptive_router.cards_router`)
  rather than `POST /record-interaction` because only `complete-card` returns
  `learning_profile_summary` and `recovery_card` in its response body.
- Test 10 falls back to `GET /students/{id}/analytics` if `next-section-cards`
  returns 400 (no more queued sections), still asserting cross-section data persistence.
- Tests involving LLM generation use a 120 s timeout per request.
