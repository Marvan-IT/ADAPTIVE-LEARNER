# Exercise Pattern Parsing — Detailed Low-Level Design

## 1. Component Breakdown

| Component | File | Responsibility |
|-----------|------|---------------|
| `ExerciseMarker` dataclass | `book_profiler.py` | Carries pattern + behavior + **group** for one exercise heading |
| `BookProfile` | `book_profiler.py` | Owns `exercise_markers: list[ExerciseMarker]`; serialized to `book_profile.json` |
| LLM profiler prompt | `book_profiler.py` | Instructs LLM to classify each marker into a vocabulary group |
| `_llm_dict_to_profile()` | `book_profiler.py` | Deserializes LLM JSON → `ExerciseMarker` objects with `group` |
| `legacy_profile_from_config()` | `book_profiler.py` | Hardcoded fallback — must also emit `group` field |
| `_NOISE_HEADING_PATTERNS` | `chunk_parser.py` | List of compiled patterns for headings that are body content, not subsection boundaries |
| `_build_section_chunks()` | `chunk_parser.py` | Main parse loop — exercise zone tagging, orphan content handling |
| `_classify_chunk()` | `chunk_parser.py` | Maps heading + zone state → `(chunk_type, is_optional)` |
| `_normalize_heading()` | `chunk_parser.py` | OCR cleanup — adds Stats Lab normalization, `©` prefix strip |
| `_postprocess_chunks()` | `chunk_parser.py` | Dedup, merge, split — **new step: back-matter re-assignment** |
| `_reassign_back_matter()` | `chunk_parser.py` | **New helper:** re-assigns `concept_id` of back-matter chunks to last section |
| Alembic migration | `alembic/versions/016_chunk_type_check_constraint.py` | Adds PostgreSQL CHECK constraint on `concept_chunks.chunk_type` |
| `config.py` | `config.py` | New vocabulary group string constants |

---

## 2. Data Design

### 2.1 ExerciseMarker — Extended Dataclass

```python
# book_profiler.py

class ExerciseMarker(BaseModel):
    """An auto-detected exercise heading pattern."""
    pattern: str    # heading text or regex
    behavior: str   # "zone_section_end" | "zone_chapter_end" | "inline_single"
    group: str = "zone_divider"  # NEW — vocabulary group (see 2.2)
```

**`group` valid values:**

| Value | Meaning |
|-------|---------|
| `"zone_divider"` | Organizational label — skip heading, buffer orphan content (default) |
| `"pmp_topic"` | PMP child topic — promote as exercise chunk |
| `"standalone_exercise"` | Named exercise type — promote as exercise chunk directly |
| `"chapter_pool"` | Stats-style chapter-level pool — exercise or chapter_review chunk |
| `"back_matter"` | Chapter back matter — chapter_review chunk, re-assigned to last section |
| `"lab"` | Stats Lab / experiment — lab chunk, re-assigned to last section |

### 2.2 Vocabulary Group Definitions

These are the canonical headings per book pattern. The LLM profiler is expected to emit these; they are also present in `legacy_profile_from_config()` as the hardcoded fallback.

**EX-A — Prealgebra, Elementary Algebra, Intermediate Algebra:**
```
zone_divider:       "SECTION N.M EXERCISES", "Practice Makes Perfect"
                    regex: r"^section\s+\d+\.\d+", r"^practice makes perfect"
standalone_exercise: "Writing Exercises", "Self Check", "Everyday Math", "Mixed Practice"
back_matter:        "Key Terms", "Key Concepts", "Key Equations",
                    "Review Exercises", "Practice Test", "Chapter Review"
```

**EX-A-alt — College Algebra:**
```
zone_divider:       "N.M SECTION EXERCISES" (note: reversed format)
                    regex: r"^\d+\.\d+\s+section\s+exercises"
standalone_exercise: "Verbal", "Numeric", "Algebraic", "Graphical",
                    "Real-World Applications", "Technology", "Extensions"
back_matter:        same as EX-A + "Key Equations"
```

**EX-B — Statistics, Business Statistics:**
```
chapter_pool:       "CHAPTER REVIEW", "FORMULA REVIEW", "PRACTICE", "HOMEWORK",
                    "BRINGING IT TOGETHER: PRACTICE", "BRINGING IT TOGETHER: HOMEWORK",
                    "SOLUTIONS", "REFERENCES"
                    regex: case-insensitive match on each
lab:                "Stats Lab", "Stats hab" (OCR variant → normalized to "Stats Lab")
                    regex: r"^stats\s+h?ab$" (normalized in _normalize_heading)
```

**EX-C — Algebra 1:**
```
zone_divider:       "N.M.K Practice" sub-part (detected by N.M.K title pattern)
                    regex: r"^\d+\.\d+\.\d+\s+practice" (post-normalization)
pmp_topic:          internal headings within the Practice sub-part body
                    (detected as all ## headings between zone_divider and
                     next N.M.K heading or next N.M section)
```

**EX-D — Clinical Nursing Skills:**
```
zone_divider:       "Assessments"
                    regex: r"^assessments?\b"
standalone_exercise: "Review Questions", "Check Your Understanding Questions",
                    "Reflection Questions", "Competency-Based Assessments"
```

### 2.3 Config Constants (config.py additions)

```python
# Vocabulary group name constants — used as ExerciseMarker.group values
EXERCISE_GROUP_ZONE_DIVIDER    = "zone_divider"
EXERCISE_GROUP_PMP_TOPIC       = "pmp_topic"
EXERCISE_GROUP_STANDALONE      = "standalone_exercise"
EXERCISE_GROUP_CHAPTER_POOL    = "chapter_pool"
EXERCISE_GROUP_BACK_MATTER     = "back_matter"
EXERCISE_GROUP_LAB             = "lab"

# Updated EXERCISE_SECTION_MARKERS — keep for legacy mmd_parser compatibility
EXERCISE_SECTION_MARKERS = [
    "Practice Makes Perfect",
    "Mixed Practice",
    "Everyday Math",
    "Writing Exercises",
    "Self Check",
    "Verbal",
    "Numeric",
    "Algebraic",
    "Graphical",
    "Real-World Applications",
    "Technology",
    "Extensions",
]

# New: back matter headings that get re-assigned to the last section
BACK_MATTER_CHUNK_HEADINGS = [
    "Key Terms",
    "Key Concepts",
    "Key Equations",
    "Review Exercises",
    "Practice Test",
    "Chapter Review",
    "CHAPTER REVIEW",
    "FORMULA REVIEW",
    "PRACTICE",
    "HOMEWORK",
    "SOLUTIONS",
    "REFERENCES",
    "BRINGING IT TOGETHER: PRACTICE",
    "BRINGING IT TOGETHER: HOMEWORK",
]
```

### 2.4 Database Schema Change

```sql
-- Migration: 016_chunk_type_check_constraint.py

ALTER TABLE concept_chunks
ADD CONSTRAINT ck_concept_chunks_chunk_type
CHECK (chunk_type IN ('teaching', 'exercise', 'lab', 'chapter_intro', 'chapter_review'));
```

Downgrade removes the constraint. Migration must verify no existing rows violate the constraint before adding it.

---

## 3. API Design

Not applicable — this feature modifies the offline extraction pipeline only. No HTTP endpoints are added, changed, or removed. The Admin Book Content UI reads `concept_chunks` by `concept_id` without any changes.

---

## 4. Sequence Diagrams

### 4.1 EX-A Section Parse (Happy Path — Prealgebra 1.1)

```
parse_book_mmd()
  │
  ├─ _normalize_mmd_format(mmd_text)      → \section*{} → ## headings
  ├─ _build_parse_config(profile)
  │    loads ExerciseMarker list with group fields
  │
  ├─ _find_sections()                     → [section 1.1, 1.2, ...]
  │
  └─ _build_section_chunks(section 1.1)
       │
       ├─ body = mmd_text[1.1_start : 1.2_start]
       │
       ├─ heading scan → ["Identify Counting Numbers", "Model Whole Numbers", ...,
       │                   "SECTION 1.1 EXERCISES", "Practice Makes Perfect",
       │                   "Identify Counting Numbers and Whole Numbers",  ← PMP topic
       │                   "Model Whole Numbers",                           ← PMP topic
       │                   "Everyday Math", "Writing Exercises", "Self Check"]
       │
       ├─ noise filter
       │    KEEPS: "Identify Counting Numbers", "Model Whole Numbers" (teaching)
       │    KEEPS: "SECTION 1.1 EXERCISES" (was noise, now handled by zone logic)
       │    KEEPS: "Practice Makes Perfect"  (was noise, now handled by zone logic)
       │    KEEPS: "Everyday Math", "Writing Exercises", "Self Check" ← CHANGED
       │    drops: any EXAMPLE/TRY IT/Solution/HOW TO headings
       │
       ├─ exercise zone tagging
       │    "SECTION 1.1 EXERCISES" → group=zone_divider → in_exercises_zone=True
       │                               skip heading, buffer orphan_after_divider
       │    "Practice Makes Perfect" → group=zone_divider → skip heading (inner divider)
       │    "Identify Counting Numbers and Whole Numbers" → in_exercises_zone + not a divider
       │                               → emit exercise chunk
       │    "Model Whole Numbers" (second occurrence) → emit exercise chunk
       │    "Everyday Math"       → group=standalone_exercise → emit exercise chunk
       │    "Writing Exercises"   → group=standalone_exercise → emit exercise chunk
       │    "Self Check"          → group=standalone_exercise → emit exercise chunk
       │
       └─ result: teaching chunks [0..N-1] + exercise chunks [N..N+8]
```

### 4.2 EX-B Chapter Back Matter Re-Assignment

```
After _build_section_chunks() completes for all sections in chapter 1:

raw_chunks = [
  prealgebra_1.4 | "Experimental Design" [teaching]
  ...
  prealgebra_1.4 | "Data Collection Experiment (Lab)" [lab]   ← concept_id is "stats_1.4"
  prealgebra_1.4 | "Sampling Experiment (Lab)"        [lab]
  # Chapter-level pools were created under their own fake concept_id:
  stats_chapter_review | "CHAPTER REVIEW"   [chapter_review]  ← wrong concept_id
  stats_chapter_review | "PRACTICE"         [exercise]        ← wrong concept_id
  stats_chapter_review | "HOMEWORK"         [exercise]        ← wrong concept_id
]

_reassign_back_matter(raw_chunks, chapter_num=1, last_section_id="stats_1.4")

result:
  stats_1.4 | "CHAPTER REVIEW"  [chapter_review]  ← re-assigned
  stats_1.4 | "PRACTICE"        [exercise]        ← re-assigned
  stats_1.4 | "HOMEWORK"        [exercise]        ← re-assigned
```

### 4.3 Error Path — Unknown Exercise Heading

```
in_exercises_zone = True
heading = "Novel Exercise Type"

_match_exercise_group() → None (no vocabulary match)

fallback: emit chunk with chunk_type="exercise"
logger.warning("Exercise zone: unmatched heading '%s' for book '%s' — defaulting to exercise",
               heading, book_slug)
```

---

## 5. Integration Design

No external integrations. The extraction pipeline is offline. The only integration point is:

- **PostgreSQL `concept_chunks` table**: chunks are bulk-upserted by `chunk_builder.py` after `chunk_parser.py` returns. The new `chunk_type` values (`exercise`, `lab`, `chapter_review`) are already valid columns — no schema change other than the CHECK constraint.

---

## 6. Security Design

Not applicable to the extraction pipeline — it runs as a one-time offline batch job with no external network calls beyond the single LLM profiler call (already present, unchanged).

---

## 7. Observability Design

### Logging additions (chunk_parser.py)

```python
# When a zone divider is encountered:
logger.info("[exercise] zone_divider '%s' → in_exercises_zone=True (section %s)", heading, concept_id)

# When orphan content is buffered after a zone divider:
logger.info("[exercise] buffered %d chars of orphan content after divider '%s'", len(orphan), heading)

# When orphan content is prepended to the first exercise chunk:
logger.info("[exercise] prepended %d chars of orphan content to first exercise chunk '%s'", len(orphan), next_heading)

# When a heading in exercise zone has no vocabulary match (fallback):
logger.warning("[exercise] unmatched heading '%s' in exercise zone for %s — defaulting to 'exercise'", heading, concept_id)

# When back matter is re-assigned:
logger.info("[back_matter] re-assigned %d chunks from standalone concept_id to %s", count, last_section_id)

# After each book reprocess, log exercise chunk summary:
logger.info("[summary] %s: %d teaching, %d exercise, %d lab, %d chapter_review chunks",
            book_slug, n_teaching, n_exercise, n_lab, n_review)
```

### Verification log checklist (post-reprocess)

After each book reprocess, the pipeline should log (or the developer should query):

```sql
SELECT chunk_type, COUNT(*) FROM concept_chunks
WHERE book_slug = 'prealgebra2e'
GROUP BY chunk_type ORDER BY chunk_type;
```

Expected non-zero counts for: `teaching`, `exercise`, `chapter_review`.

---

## 8. Error Handling and Resilience

### 8.1 LLM profiler does not emit `group` field

`ExerciseMarker.group` defaults to `"zone_divider"`. Old cached `book_profile.json` files (without the `group` field) will deserialize safely via Pydantic's default. Behavior: the marker will act as a zone_divider (existing behavior). The book must be re-profiled with `--force` to get correct group classifications.

**Developer action required:** Delete `backend/output/{book_slug}/book_profile.json` before running the updated pipeline on all 8 books. Document this in the execution plan.

### 8.2 Orphan content after zone divider with no following exercise heading

```python
# In _build_section_chunks(), after iterating all meaningful_subs with in_exercises_zone=True:
if orphan_after_divider and not any_exercise_chunk_emitted:
    # Create a single exercise chunk with the orphan content
    raw_chunks.append(ParsedChunk(
        concept_id=sec["concept_id"],
        heading=sec["section_label"] + " (Exercises)",
        text=orphan_after_divider,
        chunk_type="exercise",
        ...
    ))
    logger.info("[exercise] created fallback exercise chunk from orphan content (%d chars)", ...)
```

### 8.3 Alembic migration check for invalid existing rows

```python
# In upgrade():
from alembic import op
import sqlalchemy as sa

conn = op.get_bind()
invalid = conn.execute(sa.text(
    "SELECT COUNT(*) FROM concept_chunks "
    "WHERE chunk_type NOT IN ('teaching','exercise','lab','chapter_intro','chapter_review')"
)).scalar()
if invalid:
    raise RuntimeError(
        f"Migration aborted: {invalid} rows have unknown chunk_type values. "
        "Fix them before adding the CHECK constraint."
    )
op.execute(
    "ALTER TABLE concept_chunks ADD CONSTRAINT ck_concept_chunks_chunk_type "
    "CHECK (chunk_type IN ('teaching','exercise','lab','chapter_intro','chapter_review'))"
)
```

---

## 9. Detailed Implementation Specifications

### 9.1 `_NOISE_HEADING_PATTERNS` — Entries to Remove

Remove these patterns from `chunk_parser.py` lines 74-130 (they must survive to exercise zone tagging):

```python
# REMOVE:
re.compile(r"^Self Check\b", re.IGNORECASE),
re.compile(r"^Writing Exercises\b", re.IGNORECASE),
re.compile(r"^Everyday Math\b", re.IGNORECASE),
re.compile(r"^Mixed Practice\b", re.IGNORECASE),
re.compile(r"^Review Exercises\b", re.IGNORECASE),
re.compile(r"^Practice Test\b", re.IGNORECASE),
re.compile(r"^Key Terms\b", re.IGNORECASE),
re.compile(r"^Key Concepts\b", re.IGNORECASE),
re.compile(r"^Formula Review\b", re.IGNORECASE),
re.compile(r"^Homework\b", re.IGNORECASE),
re.compile(r"^Solutions\b", re.IGNORECASE),
re.compile(r"^Bringing It Together\b", re.IGNORECASE),
re.compile(r"^Chapter Review\b", re.IGNORECASE),
re.compile(r"^Practice\b", re.IGNORECASE),
re.compile(r"^References\b", re.IGNORECASE),
re.compile(r"^Check Your Understanding\b", re.IGNORECASE),
re.compile(r"^Lesson Summary\b", re.IGNORECASE),
re.compile(r"^Lesson Overview\b", re.IGNORECASE),
re.compile(r"^Additional Resources\b", re.IGNORECASE),
re.compile(r"^Cool Down\b", re.IGNORECASE),
re.compile(r"^Warm Up\b", re.IGNORECASE),
re.compile(r"^Verbal\b", re.IGNORECASE),
re.compile(r"^Algebraic\b", re.IGNORECASE),
```

**After removal:** these headings reach the zone tagging step. Inside an exercise zone they are classified by vocabulary group; outside an exercise zone they become teaching chunks (the correct behavior for Lesson Overview, Lesson Summary, Cool Down, Warm Up, Additional Resources in the Algebra 1 EX-C pattern).

### 9.2 `_normalize_heading()` — OCR Cleanup Additions

```python
def _normalize_heading(heading: str) -> str:
    h = heading
    # [existing code...]

    # NEW: Strip © prefix (intermediate_algebra exercise anchors)
    h = re.sub(r"^©\s*", "", h)

    # NEW: Normalize "Stats hab" OCR variant → "Stats Lab"
    h = re.sub(r"^[Ss]tats\s+hab\b", "Stats Lab", h)

    return h
```

### 9.3 Exercise Zone Logic — Updated `_build_section_chunks()` Loop

The core zone-tagging loop becomes a dispatch on `ExerciseMarker.group`:

```python
# Pseudo-code for the updated zone classification block inside _build_section_chunks()

orphan_after_divider: str = ""

for (sh_start, sh_end, heading_text) in meaningful_subs:
    _norm = _normalize_heading(heading_text)

    # Match against exercise markers (now group-aware)
    ex_group, ex_behavior = _match_exercise_marker_group(_norm, compiled_exercise_markers)

    if ex_group == "zone_divider" or (ex_behavior in ("zone_section_end", "zone_chapter_end") and ex_group is None):
        # Organizational divider — set zone, buffer content below this heading
        in_exercises_zone = True
        # Content BETWEEN this heading and the next is "orphan_after_divider"
        # Compute orphan_after_divider here (content from sh_end to next heading start)
        orphan_after_divider = _extract_orphan_content(body, sh_end, next_heading_start)
        continue  # skip heading itself

    chunk_type_override = None

    if ex_group == "back_matter":
        chunk_type_override = "chapter_review"
    elif ex_group == "lab":
        chunk_type_override = "lab"
    elif ex_group in ("standalone_exercise", "pmp_topic", "chapter_pool") or in_exercises_zone:
        chunk_type_override = "exercise"

    # Build chunk text — prepend orphan if this is the first exercise chunk
    chunk_text = body[sh_start:content_end].strip()
    if orphan_after_divider:
        chunk_text = orphan_after_divider + "\n\n" + chunk_text
        orphan_after_divider = ""

    _ctype = chunk_type_override or _classify_chunk(heading_text, in_exercises_zone, sec["section_label"])[0]

    # Emit ParsedChunk with _ctype
    ...
```

### 9.4 Helper: `_match_exercise_marker_group()`

```python
def _match_exercise_marker_group(
    normalized_heading: str,
    compiled_markers: list[tuple[re.Pattern, str, str]],  # (pattern, behavior, group)
) -> tuple[str | None, str | None]:
    """Return (group, behavior) of the first matching exercise marker, or (None, None)."""
    for pat, behavior, group in compiled_markers:
        if pat.search(normalized_heading):
            return group, behavior
    return None, None
```

The `_build_parse_config()` function must be updated to compile `(pattern, behavior, group)` triples:

```python
compiled_exercise_markers: list[tuple[re.Pattern, str, str]] = []
for marker in profile.exercise_markers:
    compiled_exercise_markers.append(
        (re.compile(marker.pattern, re.IGNORECASE), marker.behavior, marker.group)
    )
```

### 9.5 Helper: `_reassign_back_matter()`

```python
def _reassign_back_matter(
    raw_chunks: list[ParsedChunk],
    book_slug: str,
) -> list[ParsedChunk]:
    """
    After all sections are parsed, re-assign chapter_review and lab chunks
    to the last regular (teaching) section in their chapter.

    Back matter chunks are identified by:
      - chunk_type in ("chapter_review", "lab")
      - AND their concept_id does not correspond to any real teaching section
        (i.e., they were emitted under a "Chapter Review" fake concept_id)

    The last real section in a chapter is the last concept_id of form
    "{book_slug}_{chapter_num}.{section_num}" where section_num > 0.
    """
    # Build map: chapter_num → last real section concept_id
    last_section_per_chapter: dict[int, str] = {}
    for chunk in raw_chunks:
        if chunk.chunk_type in ("teaching", "exercise"):
            m = re.match(rf"^{re.escape(book_slug)}_(\d+)\.(\d+)$", chunk.concept_id)
            if m:
                ch = int(m.group(1))
                last_section_per_chapter[ch] = chunk.concept_id

    reassigned = 0
    for chunk in raw_chunks:
        if chunk.chunk_type not in ("chapter_review", "lab"):
            continue
        m = re.match(rf"^{re.escape(book_slug)}_(\d+)\.(\d+)$", chunk.concept_id)
        if not m:
            continue  # already has a valid concept_id from the parse
        ch = int(m.group(1))
        target = last_section_per_chapter.get(ch)
        if target and target != chunk.concept_id:
            chunk.concept_id = target
            reassigned += 1

    logger.info("[back_matter] re-assigned %d back-matter chunks to their chapter's last section", reassigned)
    return raw_chunks
```

This helper is called at the start of `_postprocess_chunks()`, before deduplication.

### 9.6 Profiler Prompt Update

The JSON schema in `_PROFILER_JSON_SCHEMA` (`book_profiler.py` line 199) is updated to include `group`:

```json
"exercise_markers": [
  {
    "pattern": "<heading text or regex>",
    "behavior": "<zone_section_end | zone_chapter_end | inline_single>",
    "group": "<zone_divider | pmp_topic | standalone_exercise | chapter_pool | back_matter | lab>"
  }
]
```

System prompt addition (add to rule #4):

```
4. exercise_markers behavior and group values:
   - behavior 'zone_section_end': heading starts an exercise zone that runs to section end
   - behavior 'zone_chapter_end': heading starts a chapter-level pool
   - behavior 'inline_single': heading is a named exercise type within a zone
   - group 'zone_divider': pure organizational label — skip heading, keep content
   - group 'pmp_topic': child topic under "Practice Makes Perfect" — promote as exercise chunk
   - group 'standalone_exercise': named exercise category (Writing Exercises, Verbal, etc.)
   - group 'chapter_pool': chapter-level pool (Stats PRACTICE, HOMEWORK, SOLUTIONS, etc.)
   - group 'back_matter': chapter back matter (Key Terms, Key Concepts, Practice Test, etc.)
   - group 'lab': Stats Lab or hands-on experiment section
```

### 9.7 `legacy_profile_from_config()` — Group Field Additions

The inline_exercise_patterns in `legacy_profile_from_config()` must be updated to emit group:

```python
exercise_markers: list[ExerciseMarker] = [
    ExerciseMarker(pattern=p, behavior="zone_section_end", group="zone_divider")
    for p in exercise_zone_patterns
]

exercise_markers += [
    ExerciseMarker(pattern=r"^practice makes perfect?", behavior="inline_single", group="zone_divider"),
    ExerciseMarker(pattern=r"^mixed practice",          behavior="inline_single", group="standalone_exercise"),
    ExerciseMarker(pattern=r"^everyday math",           behavior="inline_single", group="standalone_exercise"),
    ExerciseMarker(pattern=r"^writing exercises?",      behavior="inline_single", group="standalone_exercise"),
    ExerciseMarker(pattern=r"^self check",              behavior="inline_single", group="standalone_exercise"),
    ExerciseMarker(pattern=r"^key terms",               behavior="inline_single", group="back_matter"),
    ExerciseMarker(pattern=r"^key concepts",            behavior="inline_single", group="back_matter"),
    ExerciseMarker(pattern=r"^review exercises",        behavior="inline_single", group="back_matter"),
    ExerciseMarker(pattern=r"^practice test",           behavior="inline_single", group="back_matter"),
]
```

---

## 10. Testing Strategy

### Unit Tests (per pattern) — `backend/tests/test_exercise_parsing.py`

| Test Class | Fixture | Assertions |
|-----------|---------|-----------|
| `TestExAPrealgebra` | `fixtures/prealgebra_section_1_1.mmd` | 6 PMP topic chunks promoted, Writing Exercises chunk, Self Check chunk, Everyday Math chunk — all `chunk_type=exercise` |
| `TestExACollegeAlgebra` | `fixtures/college_algebra_section_1_1.mmd` | Verbal, Numeric, Algebraic, Graphical, Real-World Applications as exercise chunks |
| `TestExBStatistics` | `fixtures/statistics_chapter_1.mmd` | CHAPTER REVIEW, PRACTICE, HOMEWORK chunks have `concept_id=statistics_1.4`; Stats Lab chunk has `chunk_type=lab` |
| `TestExCAlgebra1` | `fixtures/algebra_1_lesson_1_1.mmd` | Practice topics flattened; Lesson Summary is `teaching`; Cool Down is `teaching` |
| `TestExDNursing` | `fixtures/nursing_chapter_1.mmd` | Review Questions, Check Your Understanding, Reflection Questions, Competency-Based Assessments as `exercise` chunks |

### Regression Tests

| Test | Assertion |
|------|-----------|
| `test_teaching_chunks_unaffected` | Prealgebra 1.1 teaching chunk count is unchanged after noise pattern removal |
| `test_orphan_content_preserved` | Content between "SECTION 1.1 EXERCISES" and first PMP topic is prepended to first exercise chunk |
| `test_self_check_dedup` | Prealgebra 1.1 has both a teaching Self Check chunk AND an exercise Self Check chunk (different `chunk_type`) |
| `test_back_matter_reassignment` | Key Terms and Practice Test chunks for chapter 1 have `concept_id` equal to the last section in chapter 1 |
| `test_stats_lab_normalization` | "Stats hab" heading is normalized to "Stats Lab" before chunk creation |
| `test_ocr_copyright_strip` | Heading "© Practice Makes Perfect" is normalized to "Practice Makes Perfect" |
| `test_unknown_exercise_heading_fallback` | Unknown heading in exercise zone defaults to `chunk_type=exercise` with a warning log |

### Integration Test

- Full pipeline run on `prealgebra2e`: verify total `exercise` chunk count >= 400 (matches recon data: 258 PMP + 60 Writing + 60 Self Check + 63 Everyday Math + 15 Mixed Practice)
- Full pipeline run on `statistics`: verify `lab` chunk count = 17 (recon data)
- Alembic migration test: verify `chunk_type` values before and after migration, CHECK constraint rejects invalid value

### Fixtures

Each fixture is a 50–150 line MMD excerpt extracted from the real book files. Stored at:

```
backend/tests/fixtures/
├── prealgebra_section_1_1.mmd
├── college_algebra_section_1_1.mmd
├── statistics_chapter_1.mmd
├── algebra_1_lesson_1_1.mmd
└── nursing_chapter_1.mmd
```

---

## Key Decisions Requiring Stakeholder Input

1. **Self Check dedup key:** Should the dedup key be `(concept_id, heading, chunk_type)` to allow both a teaching and exercise "Self Check" to coexist? The current key `(concept_id, heading)` would keep only the larger of the two.
2. **`is_optional` for exercise chunks:** Should all exercise and chapter_review chunks default to `is_optional=True`? This controls whether the exam gate includes them.
3. **Cached profile invalidation procedure:** After Phase 2C ships, all 8 cached `book_profile.json` files must be deleted and regenerated. Confirm who is responsible for this step and whether it can be automated in the pipeline CLI.
4. **EX-C pmp_topic detection within Practice sub-parts:** The plan requires detecting "all ## headings within the N.M.K Practice body" as pmp_topic. Confirm whether this needs a dedicated regex (to avoid promoting non-practice internal headings) or whether `in_exercises_zone=True` is sufficient.
