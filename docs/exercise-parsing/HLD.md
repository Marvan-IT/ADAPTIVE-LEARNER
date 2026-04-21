# Exercise Pattern Parsing — High-Level Design

## 1. Executive Summary

**Feature:** Exercise Pattern Parsing
**Problem:** The active chunk pipeline (`chunk_parser.py`) already preserves exercise content, but it mis-classifies or mis-labels it. Exercise headings that should become first-class chunks — PMP topics, Writing Exercises, Self Check, Stats Labs, chapter back matter — are either silently swallowed into `_NOISE_HEADING_PATTERNS` or tagged with unhelpful "(Exercises)" suffixes. Chapter back matter (Key Terms, Practice Test, etc.) is created under a standalone `concept_id` instead of being attached to the last section in the chapter.

**Solution:** Extend `ExerciseMarker` with a `group` field, remove conflicting noise patterns, fix orphan content handling, and add back-matter re-assignment — so all exercise and assessment content appears correctly in the Admin Book Content UI as properly typed subsections of the right section.

**Scope — In:**
- `book_profiler.py`: `ExerciseMarker` dataclass extension + profiler prompt update
- `chunk_parser.py`: noise pattern removal, orphan content handling, zone logic, back-matter re-assignment, OCR normalization
- `config.py`: new vocabulary group constants
- Alembic migration: CHECK constraint on `chunk_type`

**Scope — Out:**
- `mmd_parser.py` (legacy path — not modified)
- `pipeline.py` (no changes — clarifying comment only)
- Frontend (Admin UI already renders chunks by `concept_id` automatically)
- New DB tables (none required)

---

## 2. Functional Requirements

| # | Requirement | Priority |
|---|------------|---------|
| FR-1 | PMP topic headings are promoted to `chunk_type: exercise` subsections (not swallowed as noise) | P0 |
| FR-2 | Standalone exercise headings (Writing Exercises, Self Check, Everyday Math, Mixed Practice) become exercise chunks | P0 |
| FR-3 | Chapter back matter (Key Terms, Key Concepts, Review Exercises, Practice Test) is attached to the last section's `concept_id` with `chunk_type: chapter_review` | P0 |
| FR-4 | Statistics chapter pools (CHAPTER REVIEW, PRACTICE, HOMEWORK, BRINGING IT TOGETHER, SOLUTIONS, REFERENCES) attached to last section | P0 |
| FR-5 | Stats Labs (including OCR variant "Stats hab") become `chunk_type: lab` chunks | P0 |
| FR-6 | Algebra 1 Practice sub-parts (N.M.K Practice) are flattened into individual exercise chunks | P1 |
| FR-7 | Nursing assessment headings (Review Questions, Check Your Understanding, Reflection Questions, Competency-Based Assessments) become exercise chunks | P1 |
| FR-8 | College algebra standalone exercise types (Verbal, Numeric, Algebraic, Graphical, Real-World Applications, Technology, Extensions) become exercise chunks | P1 |
| FR-9 | Content between zone dividers and the next heading is preserved (no orphan text lost) | P0 |
| FR-10 | Best-effort fallback: unknown headings after the last teaching subsection default to `chunk_type: exercise` with a warning log | P1 |
| FR-11 | `chunk_type` DB column has a CHECK constraint enforcing valid values | P1 |

---

## 3. Non-Functional Requirements

| Concern | Target |
|---------|--------|
| Correctness | Zero content dropped — every `\section*{}` / `\subsection*{}` heading produces a chunk or has its content prepended to an adjacent chunk |
| Performance | Pipeline reprocess time per book unchanged (no additional LLM calls per chunk) |
| Backward compatibility | Teaching chunks for all 8 books unaffected — only exercise/review chunks change |
| Observability | `logger.warning()` for every unmatched heading in exercise zone; `logger.info()` for back-matter re-assignment counts |
| DB integrity | Alembic migration adds CHECK constraint; migration is reversible (downgrade removes constraint) |

---

## 4. System Context

```
PDF → pdf_reader → text_cleaner
    → ocr_validator (TOC, signal_stats, quality_report)
    → book_profiler  ← [CHANGE: ExerciseMarker.group added; profiler prompt updated]
         └─ BookProfile (exercise_markers with group field)
    → chunk_parser   ← [CHANGE: noise patterns, orphan handling, zone logic, back-matter re-assign]
         └─ ParsedChunk[]
    → chunk_builder  (no change)
    → concept_chunks table (PostgreSQL + pgvector)
    → Admin Book Content UI (reads by concept_id — no change needed)
```

Data flow within `chunk_parser._build_section_chunks()`:

```
MMD body text
  │
  ├─ heading scan → all_candidates[]
  │
  ├─ noise filter     ← [CHANGE: exercise headings removed from _NOISE_HEADING_PATTERNS]
  │    drops: EXAMPLE, TRY IT, Solution, HOW TO, ...
  │    keeps: Self Check, Writing Exercises, Everyday Math, etc. (NEW)
  │
  ├─ exercise zone tagging
  │    zone_divider  → skip heading, buffer orphan content (NEW)
  │    pmp_topic     → exercise chunk (promoted subsection) (NEW)
  │    standalone_exercise → exercise chunk (NEW)
  │    chapter_pool  → exercise/chapter_review chunk (NEW)
  │    lab           → lab chunk (NEW)
  │    back_matter   → chapter_review chunk (NEW)
  │
  ├─ orphan content handler (NEW)
  │    content between zone divider and first heading → prepended to first chunk
  │
  └─ ParsedChunk[] (per section)
       │
       └─ back-matter re-assignment (post-section-loop) (NEW)
            re-assign concept_id of chapter_review/lab chunks
            to last regular section in chapter
```

---

## 5. Architectural Style and Patterns

**Style:** Single-pipeline transformation — the existing chunk_parser parse path is extended, not replaced. No new modules required.

**Key pattern — Vocabulary groups in ExerciseMarker:** Rather than creating a separate `exercise_vocabularies.py` (which would conflict with the profiler's auto-detection system), the `group` field is added directly to the `ExerciseMarker` dataclass. The LLM profiler prompt is updated to emit this field. The chunk_parser dispatches on `group` value during zone classification.

**Rationale:** Extending the existing dataclass keeps all exercise metadata in one place (the `BookProfile`) and avoids a second lookup table that would need to stay in sync with profiler output. The profiler is the authoritative source for per-book structure.

---

## 6. Technology Stack

No new dependencies. All changes are within the existing extraction pipeline:

| Component | Technology | Change |
|-----------|-----------|--------|
| `book_profiler.py` | Python, Pydantic 2, OpenAI API | `ExerciseMarker` dataclass + prompt text |
| `chunk_parser.py` | Python, regex | `_NOISE_HEADING_PATTERNS`, zone logic, post-processing |
| `config.py` | Python | New group-name string constants |
| Alembic migration | Alembic 1.13, PostgreSQL 15 | `chunk_type` CHECK constraint |

---

## 7. Key Architectural Decisions

### ADR-1: Extend ExerciseMarker rather than create a new vocabulary file
**Options considered:**
- A: New `exercise_vocabularies.py` with per-book dicts (proposed in early plan)
- B: Add `group` field to existing `ExerciseMarker` (chosen)

**Decision:** B — extending `ExerciseMarker`.
**Rationale:** The profiler already auto-detects markers and caches the result in `book_profile.json`. A separate vocabulary file would require both the profiler and a new lookup to stay synchronized. Adding `group` to `ExerciseMarker` gives the LLM a single structured output that drives all downstream behavior. Backward compatibility is maintained because `group` has a default value of `"zone_divider"` (matching existing behavior).

### ADR-2: Remove exercise headings from `_NOISE_HEADING_PATTERNS` rather than reorder checks
**Options considered:**
- A: Keep noise patterns, add an "exercise zone check first" gate
- B: Remove conflicting entries from `_NOISE_HEADING_PATTERNS` (chosen)

**Decision:** B.
**Rationale:** The noise filter runs before zone tagging. A "check exercise zone first" gate would require every heading to be evaluated twice, complicating the linear scan. Removing entries from `_NOISE_HEADING_PATTERNS` is simpler and correct — these headings are not noise outside of exercise zones, but they are correctly handled by the zone logic inside exercise zones.

### ADR-3: Attach back matter to last section via post-processing, not during parse
**Options considered:**
- A: Detect last section during the body parse loop and directly emit chunks with its `concept_id`
- B: Post-process after all sections complete, re-assigning `concept_id` of back-matter chunks (chosen)

**Decision:** B.
**Rationale:** During `_build_section_chunks()`, the "last section" of a chapter is not known until all sections have been iterated. Post-processing the `concept_id` of `chapter_review` chunks after the loop is clean and does not require forward-lookahead in the main body parse.

### ADR-4: Add Alembic CHECK constraint for chunk_type
**Chosen values:** `('teaching', 'exercise', 'lab', 'chapter_intro', 'chapter_review')`
**Rationale:** Prevents silent mis-classification at the DB level. Any new type added in the future requires a deliberate migration, which is the correct gate.

---

## 8. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|---------|-----------|
| Noise pattern removal causes previously-noise headings to become spurious teaching chunks | Medium | Comprehensive regression tests per book; spot-check Admin UI after each reprocess |
| "Self Check" dedup collision: teaching + exercise versions of same heading in one section overwrite each other | Medium | Dedup key is `(concept_id, heading)` — exercise version has "(Exercises)" suffix in current code (line 904). Verify this works; if not, make dedup key `(concept_id, heading, chunk_type)` |
| LLM profiler does not emit `group` field for existing cached profiles | Low | `group` defaults to `"zone_divider"` via Pydantic default. Old cached `book_profile.json` files need to be deleted and regenerated after Phase 2C. Add `--force` flag to pipeline CLI docs |
| Back-matter re-assignment moves chunks to wrong section (e.g., floating section numbering) | Medium | Unit test verifies `concept_id` of Key Terms chunk equals last real section's `concept_id` per chapter |
| Stats Lab OCR variant "Stats hab" not normalized, appears as separate chunk type | Low | Phase 2F adds explicit normalization in `_normalize_heading()` before classification |
| Alembic CHECK constraint migration fails on existing rows with invalid `chunk_type` values | Low | Migration should audit existing values before adding constraint; warn and abort if unknown values found |

---

## Key Decisions Requiring Stakeholder Input

1. **"Practice Makes Perfect" label handling:** The plan drops "Practice Makes Perfect" as a heading and promotes its child topics as direct exercise subsections. Confirm this is the desired admin UI experience — alternatively, PMP could be kept as a grouping label chunk.
2. **is_optional for exercise chunks:** Currently `_classify_chunk()` marks Writing Exercises as `is_optional=True`. Should all exercise chunks default to `is_optional=True`? This affects whether they are included in the exam gate.
3. **Dedup behavior for "Self Check":** Confirm whether a section should be allowed to have both a teaching "Self Check" chunk and an exercise "Self Check" chunk simultaneously. Current dedup key only allows one per `(concept_id, heading)` pair.
4. **Reprocessing schedule:** All 8 books need reprocessing after the implementation. Confirm whether this can run in parallel with other pipeline work, and who triggers it.
