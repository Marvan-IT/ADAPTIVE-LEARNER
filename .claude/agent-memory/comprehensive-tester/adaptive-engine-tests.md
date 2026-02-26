# Adaptive Engine Test Suite Notes

## File
`backend/tests/test_adaptive_engine.py`

## Test Count by Group
- Group 1 (profile_builder): 29 tests across 6 classes
  - TestClassifySpeed: 7
  - TestClassifyComprehension: 8
  - TestClassifyEngagement: 8
  - TestComputeConfidenceScore: 5 (+ 1 edge)
  - TestClassifyNextStep: 7
  - TestBuildLearningProfile: 3
- Group 2 (generation_profile): 22 tests across 2 classes
  - TestBuildGenerationProfileBaseLookup: 9 (one per cell)
  - TestBuildGenerationProfileEngagementModifiers: 13
- Group 3 (remediation): 17 tests across 3 classes
  - TestFindRemediationPrereq: 6
  - TestHasUnmetPrereq: 3
  - TestBuildRemediationCards: 8
- Group 4 (prompt_builder): 22 tests across 2 classes
  - TestBuildAdaptivePromptSystemPrompt: 14
  - TestBuildAdaptivePromptUserPrompt: 8
- Group 5 (engine integration, async): 12 tests in TestGenerateAdaptiveLesson

Total: ~102 tests

## Critical Implementation Details Verified Against Source
1. `classify_next_step(comprehension, speed, has_unmet_prereq)` — comprehension is arg 0
2. `build_remediation_cards()` returns list[dict] (not validated Pydantic objects)
3. The engine calls `graph.predecessors()` inside `find_remediation_prereq()`, not directly
4. `prereq_detail` is fetched via a second `knowledge_svc.get_concept_detail()` call in engine
5. Remediation cards are PREPENDED (index 0) to the all_cards list
6. `asyncio.sleep(2 * attempt)` — sleep is called between attempts 1→2 and 2→3 only
7. After all 3 retries exhausted, raises `ValueError` (not a specific exception subclass)
8. Empty string content triggers retry (same as exception), checked via `.strip()`
