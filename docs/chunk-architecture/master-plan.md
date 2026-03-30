# Master Plan: ADA Full Architecture Redesign
## From Fragmented Extraction to Unified Chunk-Based Pipeline

---

## Context & Why This Change

The current ADA pipeline has three fundamental problems:

1. **Fragmented extraction** — Text and images are extracted separately by PyMuPDF. The spatial relationship between a diagram and its explanation is permanently lost at extraction time. Images are matched to cards by loose `concept_id` keyword lookup, causing wrong or missing images on cards.

2. **Wrong storage layer** — ChromaDB is single-node only, cannot scale horizontally, and requires a fragile `image_index.json` mapping file. Not suitable for production with real concurrent users.

3. **Weak card adaptation** — Cards are generated from multiple unrelated concept blocks retrieved by semantic search, not from coherent subsection-level passages. Adaptation changes card count and MCQ difficulty but does NOT adapt the presentation style (language, analogies, tone) per student interests and mode.

**Intended outcome:** Every student covers every concept in the textbook in order. No content is skipped. Adaptation changes only HOW the content is presented — not what is shown. Images on cards are always the correct diagram because they are stored with their text at extraction time.

---

## What Happens to Your Current Extracted Data

### Current state
```
backend/output/prealgebra/
├── chroma_db/          ← ChromaDB vector store (concept blocks)
├── images/             ← Extracted image files (keep these)
├── image_index.json    ← Image path mapping (will be replaced)
├── graph.json          ← NetworkX concept dependency graph (keep this)
└── concepts.json       ← Concept metadata (partially reused)

PostgreSQL:
├── students            ← KEEP — untouched
├── teaching_sessions   ← KEEP — untouched
├── conversation_messages ← KEEP — untouched
└── student_mastery     ← KEEP — untouched
```

### What happens to each component

| Component | Action | Reason |
|---|---|---|
| `chroma_db/` | ❌ Discarded | Replaced by pgvector. Concept blocks are different granularity from chunks — cannot migrate directly |
| `image_index.json` | ❌ Discarded | Replaced by `chunk_images` table with proper co-location |
| `images/` on disk | ✅ Kept | Re-used as-is during dev. Uploaded to R2 for production |
| `graph.json` | ✅ Kept | NetworkX dependency graph is unchanged — concept relationships still valid |
| `concepts.json` | ✅ Partially reused | `concept_id` values reused as foreign keys in `concept_chunks` table |
| PostgreSQL student/session tables | ✅ Fully kept | Zero changes — student progress, mastery, history all preserved |
| Old extraction code | ❌ Replaced | `pdf_reader.py`, `text_cleaner.py`, `section_detector.py`, `concept_builder.py` replaced by new Mathpix pipeline |
| Mathpix OCR (single image) | ✅ Kept but unused | Mathpix PDF API replaces per-image OCR calls — old code stays as fallback |

### Migration summary
- **Student data**: zero impact — all preserved
- **Images on disk**: zero impact — reused, optionally uploaded to R2 later
- **Extracted text**: re-extracted from scratch via Mathpix PDF API (one-time cost per book)
- **ChromaDB**: replaced — re-embedding happens automatically during new pipeline run

---

## Part 1 — Extraction Pipeline (Mathpix PDF API)

### Current pipeline (replaced)
```
PDF → pdf_reader → text_cleaner → section_detector → content_filter
    → concept_builder → llm_extractor → ChromaDB
    → image_extractor (separate pass) → Mathpix OCR → image_index.json
```

### New pipeline
```
PDF → Mathpix PDF API → .mmd text (unified: text + LaTeX + images together)
    → mmd_parser.py → structured blocks
    → chunk_builder.py → subsection chunks + download images
    → embed chunks → INSERT into PostgreSQL concept_chunks + chunk_images
```

### Why Mathpix PDF API
- Returns `.mmd` (Mathpix Markdown) — text, LaTeX, and image references co-located exactly as in the PDF
- LaTeX accuracy is Mathpix's core strength — no hallucination
- One API call per PDF page — replaces the entire multi-step extraction chain
- Significantly better than PyMuPDF for multi-column OpenStax layouts

### What `.mmd` looks like
```markdown
## Chapter 1: Whole Numbers

### 1.1 Introduction to Whole Numbers

#### Identify Whole Numbers
The whole numbers are the counting numbers and zero.
$$0, 1, 2, 3, 4, 5 \ldots$$

#### Model Whole Numbers
Each block represents a place value...
![fig_001](cdn.mathpix.com/fig_001.png)
*Figure 1.1 — Base-10 blocks representing 243*

#### Round Whole Numbers
To round a whole number to a specific place value, locate the
rounding digit, look at the digit immediately to the right.
$$1846 \rightarrow 1800 \quad \text{(tens digit 4 < 5)}$$
![fig_004](cdn.mathpix.com/fig_004.png)
*Figure 1.4 — Number line showing rounding*
```

### Heading hierarchy → storage mapping
```
#     Book title       (metadata only)
##    Chapter          (metadata only)
###   Section          → concept_chunks.section  e.g. "1.1 Introduction to Whole Numbers"
####  Subsection       → ONE chunk (one row in concept_chunks)
```

### Chunking rule
**One subsection (####) = one chunk. Never split mid-subsection.**
OpenStax subsections fit within the 8,191 token embedding limit — no size-based splitting needed.

### Complete coverage — no content ever dropped

Previously "Be Careful", "Try It", "Exercises", "Learning Objectives", "Media" blocks were skipped due to ChromaDB storage limits. With PostgreSQL + pgvector ALL blocks are stored. The heading text carries the semantic meaning — no type column needed. The LLM reads "Be Careful" in the heading and generates a warning-style card naturally.

The parser handles three content cases to guarantee 100% PDF coverage:

**Case 1 — Normal subsection (#### heading)**
Each `####` heading starts a new chunk. Most content falls here.

**Case 2 — Orphan text (text between ### and first ####)**
OpenStax sections often have introductory paragraphs before the first subsection:
```markdown
### 1.1 Introduction to Whole Numbers
"In this section we will explore..."   ← NO #### heading — would be lost
                                        → saved as chunk: heading = section title
#### Identify Whole Numbers            ← normal chunk starts here
```

**Case 3 — Chapter-level summaries (### with no #### children)**
"Key Terms", "Key Concepts", "Review Exercises", "Practice Test" appear as `###` with content directly inside. If a `###` has no `####` children, its full content becomes one chunk.

**Parser logic (mmd_parser.py):**
```python
def parse_mmd(mmd_text):
    for line in mmd_text:
        if line.startswith("### "):        # Section boundary
            save_orphan_chunk_if_any()     # save text before first ####
            current_section = line
            current_orphan_text = ""

        elif line.startswith("#### "):    # Subsection → new chunk
            save_current_chunk_if_any()
            start_new_chunk(heading=line)

        elif current_chunk:
            current_chunk.text += line    # normal content accumulation

        else:
            current_orphan_text += line   # capture before first ####
```

**Result:** Every line in the .mmd belongs to exactly one chunk. Nothing dropped. `order_index` increments for every chunk including orphan text and chapter summaries.

### Fidelity vs current pipeline
| Content | Current (PyMuPDF) | Mathpix PDF API |
|---|---|---|
| Plain text | ⚠️ Scrambled in 2-column layouts | ✅ Layout-aware |
| Section headings | ⚠️ Heuristic, can miss | ✅ Preserved from PDF |
| LaTeX formulas | ❌ Image → separate OCR pass | ✅ Extracted as LaTeX directly |
| Images | ❌ No context, loose match | ✅ Co-located with text |
| Figure captions | ❌ Often lost | ✅ Linked to image |
| Tables | ⚠️ Often garbled | ⚠️ Better, not perfect |
| Multi-column order | ❌ Frequently wrong | ✅ Usually correct |

### New files
```
backend/src/extraction/mathpix_pdf_extractor.py  — calls Mathpix PDF API, returns .mmd
backend/src/extraction/mmd_parser.py             — parses .mmd into structured blocks
backend/src/extraction/chunk_builder.py          — builds chunks, downloads images, embeds, saves to DB
backend/src/pipeline.py                          — modify: new orchestration entry point
```

---

## Part 2 — Storage Layer

### Current (replaced)
- ChromaDB → concept block embeddings (single-node, no scale)
- `image_index.json` → fragile image path mapping
- Local filesystem → image binary files

### New: Three tiers

#### Tier 1: PostgreSQL + pgvector — text, LaTeX, embeddings

**Table: `concept_chunks`** (one row per subsection)
```sql
CREATE TABLE concept_chunks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_slug     TEXT NOT NULL,                    -- "prealgebra"
    concept_id    TEXT NOT NULL,                    -- reused from existing concepts.json
    section       TEXT NOT NULL,                    -- "1.1 Introduction to Whole Numbers"
    order_index   INTEGER NOT NULL,                 -- absolute textbook order, never changes
    heading       TEXT NOT NULL,                    -- "Round Whole Numbers" or "Be Careful: ..." or "Try It"
    text          TEXT NOT NULL,                    -- full subsection prose
    latex         TEXT[] DEFAULT '{}',              -- ["1846 \rightarrow 1800", ...]
    embedding     vector(1536),                     -- embed(heading + text)
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON concept_chunks USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX ON concept_chunks (book_slug, concept_id, order_index);
```

**Table: `chunk_images`** (0–N rows per chunk)
```sql
CREATE TABLE chunk_images (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id      UUID NOT NULL REFERENCES concept_chunks(id) ON DELETE CASCADE,
    image_url     TEXT NOT NULL,        -- R2 URL (prod) or local path (dev)
    caption       TEXT,                 -- "Figure 1.4 — Number line showing rounding"
    order_index   INTEGER DEFAULT 0     -- for subsections with multiple images
);
CREATE INDEX ON chunk_images (chunk_id);
```

#### Tier 2: Cloudflare R2 — image binary files (production)
- Free tier: 10GB storage + 1M requests/month — covers ADA's full image volume
- Zero egress fees (unlike S3) — critical when many students load diagrams
- S3-compatible API — `boto3` works unchanged with endpoint swap

#### Tier 3: Local filesystem — development only
```
backend/output/{book_slug}/images/fig_001.png  (existing images reused)
```

#### Image URL resolution (config-driven, zero schema changes to switch)
```python
# backend/src/config.py
IMAGE_STORAGE = os.getenv("IMAGE_STORAGE", "local")   # "local" | "r2"
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL", "http://localhost:8889/images")
```

### How extraction saves everything (chunk_builder.py)
```
For each parsed chunk:

  STEP 1 — Image files
    Download image binary from Mathpix CDN (expires ~1hr, do immediately)
    Dev:  save to backend/output/{book_slug}/images/{filename}
    Prod: upload to R2 bucket → get permanent URL

  STEP 2 — Embedding
    Call text-embedding-3-small on (heading + text)
    Returns vector(1536)

  STEP 3 — Save chunk to PostgreSQL
    INSERT INTO concept_chunks (book_slug, concept_id, section,
      order_index, heading, text, latex, embedding)

  STEP 4 — Save images to PostgreSQL
    For each image in chunk:
      INSERT INTO chunk_images (chunk_id, image_url, caption, order_index)
```

### Final state after pipeline run (prealgebra example)
```
PostgreSQL:
  concept_chunks:  ~400 rows (one per subsection)
  chunk_images:    ~200 rows (subsections that have diagrams)

Disk / R2:
  ~200 image files
  (same files as before if images/ folder already exists — just re-registered in DB)
```

### What gets removed
| Old component | Replaced by |
|---|---|
| ChromaDB | PostgreSQL + pgvector |
| `image_index.json` | `chunk_images` table |
| `get_concept_images()` | `SELECT * FROM chunk_images WHERE chunk_id = $1` |
| Keyword image matching | Not needed — image is a column at extraction time |
| `[CARD:N]` marker system | Not needed |

---

## Part 3 — Card Generation (Chunk-Based + Style Adaptation)

### Core invariants
1. Cards always generated in `order_index` order — exact PDF sequence, never shuffled, never reordered by type
2. Every student covers every chunk — ALL blocks included (Be Careful, Try It, Exercises, Learning Objectives, Media — everything)
3. `chunk.images` sent to LLM via GPT-4o vision when chunk has image — LLM sees actual diagram
4. Image attached to correct card after generation — no keyword guessing
5. MCQ must be passed before `chunk_index` advances in session
6. `order_index` is the single source of truth for card sequence — no other field overrides it

### Exercise chunk rule (universal — applies to all sections across all 16 books)

The last chunk of every section is the exercise chunk (heading contains "Exercises" or "Practice").

**Rule: 2 MCQ cards per teaching subsection that preceded it in the section.**

```
Section: "1.2 Add Whole Numbers"
  Subsection 1: "Use Addition Notation"       ← teaching chunk
  Subsection 2: "Model Addition"              ← teaching chunk
  Subsection 3: "Add Whole Numbers"           ← teaching chunk
  Subsection 4: "Add Multiple Digit Numbers"  ← teaching chunk
  Last:         "Section 1.2 Exercises"       ← exercise chunk

Exercise chunk generates:
  2 MCQ cards from problems testing subsection 1
  2 MCQ cards from problems testing subsection 2
  2 MCQ cards from problems testing subsection 3
  2 MCQ cards from problems testing subsection 4
  ─────────────────────────────────
  8 MCQ cards total (2 × 4 subsections)
```

**Question difficulty: same for all modes — real textbook level.**
The teaching cards adapted to the student so they can answer real questions.
Making easier questions for STRUGGLING students would hide whether they actually learned.

**Wrong-answer explanation adapts to mode:**
```
STRUGGLING: full step-by-step explanation after wrong answer
NORMAL:     brief explanation after wrong answer
FAST:       one-line correction after wrong answer
```

**No pass/fail gate on exercise cards** — student sees correct explanation if wrong and advances.
Exercise chunk completion = section mastered.

**LLM prompt for exercise chunk:**
```
"Here are the section exercises: [full exercise text]

 The teaching subsections in this section were:
 1. [subsection 1 heading]
 2. [subsection 2 heading]
 3. [subsection 3 heading]
 4. [subsection 4 heading]

 Generate exactly 2 MCQ questions per subsection (N×2 cards total).
 Questions must be at real textbook difficulty — same for all students.
 Cover each subsection in order."
```

### Special content chunks — card generation rules by heading type

Not all chunks are teaching subsections. The parser stores every block, but the LLM prompt instructs different card behaviour based on what the heading signals.

| Chunk heading pattern | Cards generated | MCQ | Counted in Socratic exam |
|---|---|---|---|
| Normal `####` (concept teaching) | Natural paragraph split | ✅ 1 MCQ at end | ✅ 2 questions |
| `"Be Careful: ..."` | 1 warning-style card | ✅ 1 MCQ | ✅ 2 questions |
| `"Try It"` / `"Practice"` | 1 worked-example card | ✅ 1 MCQ | ✅ 2 questions |
| `"Learning Objectives"` | 1 overview card (roadmap of what's coming) | ❌ No MCQ | ❌ Not counted |
| Section intro (orphan text — heading == parent `###` title) | 1 context card | ❌ No MCQ | ❌ Not counted |
| `"Section X.Y Exercises"` | 2 MCQ per teaching subsection in section | All MCQ only | ❌ Not counted |
| `"Key Terms"` / `"Key Concepts"` | 1 reference card | ❌ No MCQ | ❌ Not counted |
| `"Chapter Summary"` / `"Chapter Review"` | 1–2 recap content cards | ❌ No MCQ | ❌ Not counted |
| `"Review Exercises"` / `"Practice Test"` (chapter-level) | 2 MCQ per **section** in chapter | All MCQ only | ❌ Not counted |

**How the LLM knows which rule applies:**
The system prompt instructs the LLM to read the heading and apply the matching rule:
```
heading contains "Learning Objectives"          → overview card, NO MCQ
heading == parent section title (orphan intro)  → 1 context card, NO MCQ
heading contains "Key Terms" / "Key Concepts"
                / "Summary" / "Chapter Review"  → reference card, NO MCQ
heading contains "Exercises" / "Practice Test"  → MCQ-only exercise cards (2 per subsection)
all other headings                              → natural paragraph split + 1 MCQ
```

**Socratic exam question count:**
The "2 questions per subsection" rule counts only chunks that had an MCQ — teaching `####`, Be Careful, and Try It chunks. Learning Objectives, intro context, and summary/reference chunks are excluded from the Socratic question total.

**Chapter-level Review Exercises:**
`"Review Exercises"` and `"Practice Test"` at end of chapter (a `###` with no `####` children) follow the same 2-MCQ-per-section rule as section exercises, but scope spans ALL sections in the chapter. Student works through these after completing all chapter sections — no pass/fail gate, same as section exercises.

**Concrete example — Section 1.1 full chunk list with card rules:**
```
Chunk 1: heading = "1.1 Introduction to Whole Numbers" (orphan intro)
  → 1 context card, NO MCQ, NOT in Socratic exam

Chunk 2: heading = "Learning Objectives"
  → 1 overview card, NO MCQ, NOT in Socratic exam

Chunk 3: heading = "Identify Whole Numbers"
  → natural split + MCQ, counted in Socratic exam (2 questions)

Chunk 4: heading = "Be Careful: Zero is a whole number"
  → 1 warning card + MCQ, counted (2 questions)

Chunk 5: heading = "Model Whole Numbers"
  → natural split + MCQ, counted (2 questions)

Chunk 6: heading = "Try It: Model 243"
  → 1 worked-example card + MCQ, counted (2 questions)

Chunk 7: heading = "Section 1.1 Exercises"
  → 2 MCQ × 4 teaching chunks above = 8 MCQ cards, NOT in Socratic exam

Socratic exam for section 1.1: 4 teaching chunks × 2 questions = 8 questions
```

---

### Adaptation rule
**Same content. Same chunk. Same MCQ concept. Different presentation.**
The adaptive engine changes HOW the content is explained — never WHETHER it is covered.

### What adapts per student
| Student signal | Adaptation |
|---|---|
| STRUGGLING (low XP, high error rate) | Step-by-step numbered, KID_SIMPLE vocab, 80% analogies from interests, easy MCQ difficulty 1–2 |
| NORMAL (average XP, average error rate) | High-school level, 50% analogies, real-world hook, medium MCQ difficulty 3 |
| FAST (high XP, low error rate) | Technical terminology, 20% analogies, edge case MCQ difficulty 4–5 |
| `interests = ["football"]` | Football analogies, scores/yards/stats examples |
| `interests = ["technology"]` | Coding/server/data analogies |
| `style = "gamer"` | Gaming language (XP/HP/level up), quests |
| `style = "pirate"` | Pirate language (doubloons/treasure) |
| `language = "ar"` | Entire card generated in Arabic |

### How a chunk is divided into cards

**Natural split approach — PDF order drives the cards.**

The LLM reads the full chunk once and splits it by natural paragraph breaks — exactly as the textbook author organized the content. No predetermined card type template. No invented content. Everything on a card came directly from the PDF.

**One fixed rule:** every content card is immediately followed by its own MCQ testing that specific paragraph/group.

```
Chunk: "Round Whole Numbers" (3 paragraphs)

  paragraph 1: definition of rounding        → Card 1 (content)
                                             → Card 2 (MCQ testing para 1) → PASS → Next
  paragraph 2: the rule (look at next digit) → Card 3 (content)
                                             → Card 4 (MCQ testing para 2) → PASS → Next
  paragraph 3: worked example 1,846 → 1,800 → Card 5 (content) + image
                                             → Card 6 (MCQ testing para 3) → PASS → chunk complete
```

**Card count by mode (interleaved content + MCQ pairs):**
```
STRUGGLING (each paragraph = its own card):
  6 paragraphs → 6 content + 6 MCQ = 12 cards

NORMAL (LLM merges simple paragraphs into groups):
  4 groups → 4 content + 4 MCQ = 8 cards

FAST (LLM merges into 1–2 cards):
  2 groups → 2 content + 2 MCQ = 4 cards
```

**MCQ fail / recovery per content card:**
```
Student fails MCQ for card N:
  FAIL once  → recovery card (same paragraph, different example) → new MCQ
  FAIL twice → RECAP card (key rule summarised) → advance to card N+2 (next content)
               student never stuck on one card forever
```

Chunk is complete when the last MCQ in the chunk is passed (or cleared via RECAP).

**LLM prompt structure:**
```
SYSTEM:
  Read the chunk content below.
  Split it into cards following the natural paragraph order from the PDF.
  Do NOT reorder content. Do NOT invent content not in the chunk.
  Write each card in the student's style (see profile below).
  After EVERY content card, add one MCQ testing that specific paragraph/group.
  Return as JSON array of alternating [content, MCQ, content, MCQ, ...] pairs.

  Student mode: STRUGGLING / NORMAL / FAST
  Style: [gamer / pirate / astronaut / default]
  Interests: [football / technology / mathematics / ...]
  Language: [en / ar / fr / ...]

USER:
  Heading: "Round Whole Numbers"
  Content: "To round a whole number..."
  LaTeX: ["1846 → 1800"]
  Image: "Number line showing rounding to nearest hundred"
```

**Adaptation per mode — same natural split, different writing style:**

| | STRUGGLING | NORMAL | FAST |
|---|---|---|---|
| Each card | Step-by-step, numbered, KID_SIMPLE vocab | Standard explanation | Concise, technical |
| Analogies | 80% — from student interests | 50% | 20% |
| MCQ after each card | ✅ — tests that paragraph | ✅ — tests that group | ✅ — tests merged content |
| MCQ difficulty | 1–2 (direct recall) | 3 (application) | 4–5 (edge case + WHY) |
| Total cards per chunk | 2× paragraphs (content + MCQ each) | 2× groups | 2× merged groups |

**Special chunk headings — LLM handles naturally:**
The LLM reads "Be Careful" in the heading and writes a warning-style card.
Reads "Try It" and writes an exercise card. Reads "Learning Objectives" and writes an overview card.
No extra type mapping needed — the heading text is self-describing.

---

### Concrete example: "Round Whole Numbers" chunk → same chunk, 4 different cards

**Chunk content (same for all students):**
```
paragraph 1: "To round a whole number, find the rounding place value..."
paragraph 2: "Look at the digit immediately to the right. If less than 5, keep unchanged. If 5 or more, add 1."
paragraph 3: worked example — 1,846 → 1,800
latex:  ["1846 \rightarrow 1800", "2567 \rightarrow 2600"]
image:  fig_004.png — number line diagram
```

**Student A — STRUGGLING | interests: football | style: default**
```
Card 1 (content) — paragraph 1, written simply with analogy
  "In a football game the announcer says '1,846 yards — about 1,800!'
   That 'about' is rounding! Rounding means finding the nearest
   value at a given place. It makes big numbers easier to work with."

Card 2 (MCQ, difficulty 1) — tests paragraph 1
  Q: "What does rounding a number mean?"
  A) Making it bigger  B) Finding the nearest value at a place ✓
  C) Removing zeros   D) Adding digits

Card 3 (content) — paragraph 2 (the rule), step-by-step numbered
  "Here is the rounding rule — always follow these steps:
   Step 1: Find the place you are rounding to (hundreds = 8)
   Step 2: Look at the digit to its RIGHT (tens = 4)
   Step 3: Is it 5 or more? NO (4 < 5) → keep the digit, zeros after"
  [image: fig_004.png]

Card 4 (MCQ, difficulty 1) — tests paragraph 2
  Q: "To round 1,846 to hundreds, which digit do you look at?"
  A) The 1  B) The 8  C) The 4 ✓  D) The 6

Card 5 (content) — paragraph 3 (worked example), fully walked through
  "Let us round 1,846 to the nearest hundred together:
   Step 1: hundreds digit = 8
   Step 2: tens digit = 4
   Step 3: 4 < 5 → keep 8, replace rest with zeros
   $$1846 \rightarrow 1800$$ ✓"

Card 6 (MCQ, difficulty 1) — tests paragraph 3
  Q: "Round 3,742 to the nearest hundred."
  A) 3,700 ✓  B) 3,800  C) 3,740  D) 4,000
```

**Student B — NORMAL | interests: technology | style: default**
```
Card 1 (content) — paragraphs 1+2 merged
  "Rounding is like data compression — keep important digits, drop the rest.
   Rule: look one digit RIGHT of your target place.
   0–4 → round down. 5–9 → round up.
   $$1846 \rightarrow 1800 \quad \text{(tens=4, round down)}$$"
  [image: fig_004.png]

Card 2 (MCQ, difficulty 3) — tests paragraphs 1+2
  Q: "What rule determines whether you round up or keep the digit?"
  A) Look at the digit itself  B) Look one place to the RIGHT ✓
  C) Always round up          D) Look one place to the LEFT

Card 3 (content) — paragraph 3 (worked example)
  "Try 2,567 rounded to hundreds:
   Tens digit = 6 ≥ 5 → round up hundreds digit
   $$2567 \rightarrow 2600$$"

Card 4 (MCQ, difficulty 3) — tests paragraph 3
  Q: "Round 7,851 to the nearest thousand."
  A) 7,000  B) 8,000 ✓  C) 7,900  D) 7,800
```

**Student C — FAST | interests: mathematics | style: default**
```
Card 1 (content) — all paragraphs merged into one concise technical card
  "Round N to place p: check digit at p-1.
   <5 → truncate. ≥5 → increment (carry propagates if digit=9).
   $$1846 \rightarrow 1800 \quad (r=4<5)$$
   $$1950 \rightarrow 2000 \quad \text{(carry: }9+1=10\text{)}$$"
  [image: fig_004.png]

Card 2 (MCQ, difficulty 5) — edge case
  Q: "Round 9,961 to nearest hundred. Why does carry occur?"
  A) 9,900  B) 10,000 ✓  C) 9,960  D) 10,100
```

**Student D — NORMAL | interests: gaming | style: gamer**
```
Card 1 (content) — paragraphs 1+2, gamer language
  "Your character scored 1,846 XP. The leaderboard shows 1,800.
   ROUNDING ALGORITHM (unlock this skill):
   → Target the hundreds digit (your save point)
   → Scout the digit to its right
   → 0–4? STAY. 5–9? LEVEL UP.
   $$1846 \xrightarrow{\text{tens=4, stay}} 1800$$"
  [image: fig_004.png]

Card 2 (MCQ, difficulty 3) — gamer language
  Q: "You're at 1,846 XP. Rounded to hundreds on the leaderboard?"
  A) 1,900  B) 1,800 ✓  C) 2,000  D) 1,840

Card 3 (content) — paragraph 3 (worked example, gamer language)
  "Boss fight: 2,567 damage rounded to hundreds?
   Tens digit = 6 ≥ 5 → LEVEL UP the hundreds digit
   $$2567 \rightarrow 2600$$"

Card 4 (MCQ, difficulty 3) — gamer language
  Q: "Your character has 4,350 HP. Rounded to nearest thousand?"
  A) 4,000  B) 5,000 ✓  C) 4,300  D) 4,400
```

### Per-chunk session flow

**Example: Section "1.1 Introduction to Whole Numbers" — 4 subsections with 3, 2, 5, 6 paragraphs**

```
Section starts → load all 4 chunks from DB ordered by order_index
              → calculate initial mode from student history
              → chunk_index = 0

━━━━ CHUNK 1 — "Identify Whole Numbers" (3 paragraphs) ━━━━
  → recalculate mode from student history
  → send chunk text + image (if any) to LLM via GPT-4o vision
  → LLM reads 3 paragraphs → interleaved content+MCQ pairs
    STRUGGLING: 3 content + 3 MCQ = 6 cards
    NORMAL:     2 groups + 2 MCQ = 4 cards
    FAST:       1 merged + 1 MCQ = 2 cards
  → student works through card-by-card:
      content → MCQ (PASS → next content, FAIL once → recovery, FAIL twice → RECAP → next)
  → last MCQ passed → chunk_index = 1 → recalculate mode

━━━━ CHUNK 2 — "Model Whole Numbers" (2 paragraphs) ━━━━
  → recalculate blended mode using chunk 1 performance + history
  → ONE LLM call → all chunk 2 cards generated
    STRUGGLING: 2 content + 2 MCQ = 4 cards
    NORMAL:     1 group   + 1 MCQ = 2 cards
    FAST:       1 merged  + 1 MCQ = 2 cards
  → student works through → last MCQ passed → chunk_index = 2

━━━━ CHUNK 3 — "Identify Place Value" (5 paragraphs) ━━━━
  → recalculate blended mode
  → ONE LLM call → all chunk 3 cards generated
    STRUGGLING: 5 content + 5 MCQ = 10 cards
    NORMAL:     3 groups  + 3 MCQ =  6 cards
    FAST:       2 merged  + 2 MCQ =  4 cards
  → student works through → last MCQ passed → chunk_index = 3

━━━━ CHUNK 4 — "Round Whole Numbers" (6 paragraphs) ━━━━
  → recalculate blended mode
  → ONE LLM call → all chunk 4 cards generated
    STRUGGLING: 6 content + 6 MCQ = 12 cards
    NORMAL:     4 groups  + 4 MCQ =  8 cards
    FAST:       2 merged  + 2 MCQ =  4 cards
  → student works through → last MCQ passed → chunk_index = 4

━━━━ All 4 chunks complete ━━━━
  → all teaching chunks done + exercise chunk done → trigger Final Socratic Exam
  → exam pass (≥65%) → INSERT student_mastery (concept 1.1 mastered) → 1.2 unlocks
```

---

### Complete end-to-end section example — Section 1.2 "Add Whole Numbers"

**Chunks for this section (in order_index order from concept_chunks):**
```
Chunk 1: "Learning Objectives"              ← no MCQ (intro)
Chunk 2: "Use Addition Notation"            ← 3 paragraphs
Chunk 3: "Model Addition"                   ← 2 paragraphs + image
Chunk 4: "Add Whole Numbers"                ← 4 paragraphs
Chunk 5: "Add Multiple Digit Numbers"       ← 5 paragraphs
Chunk 6: "Section 1.2 Exercises"            ← exercise chunk
```

**Student: NORMAL mode | interests: technology | language: English**

━━━━ SESSION START ━━━━
```
Load 6 chunks from DB ordered by order_index
Initial mode = build_blended_analytics(history) → NORMAL
chunk_index = 0
```

━━━━ CHUNK 1 — "Learning Objectives" ━━━━
```
heading rule: "Learning Objectives" → 1 overview card, NO MCQ
Card 1 (content): "By end of section you will: use + symbol, model with blocks, add numbers"
Student reads → Next → chunk_index = 1 (no MCQ to pass)
```

━━━━ CHUNK 2 — "Use Addition Notation" (3 paragraphs, no image) ━━━━
```
Mode = NORMAL → ONE LLM call → 2 groups + 2 MCQ = 4 cards

Card 1 (content, paras 1+2 merged):
  "Addition uses the + symbol. In 3 + 5 = 8, the 3 and 5 are addends, 8 is the sum."
Card 2 (MCQ, difficulty 3):
  Q: "In 4 + 7 = 11, what are the addends?"
  C) 4 and 7 ✓ → PASS → Next (instant)
Card 3 (content, para 3):
  "Adding 0 to any number gives the same number: n + 0 = n (data: null record stays null)"
Card 4 (MCQ, difficulty 3):
  Q: "What is 15 + 0?"  C) 15 ✓ → PASS → last MCQ → chunk boundary

Chunk 2 signals: first_try_pass_rate = 1.0, recap = 0, recovery = 0
→ mode stays NORMAL → API call for chunk 3 → chunk_index = 2
```

━━━━ CHUNK 3 — "Model Addition" (2 paragraphs + image) ━━━━
```
Mode = NORMAL, HAS image → GPT-4o vision → ONE LLM call → 1 merged + 1 MCQ = 2 cards

Card 1 (content, with image):
  "Base-10 blocks show addition. 43 + 25: place 4 tens+3 ones, add 2 tens+5 ones → 68"
  [image: base-10 blocks diagram]
Card 2 (MCQ, difficulty 3):
  Q: "3 tens + 4 tens = ?"
  → Student ✗ FAIL (1st) → recovery card → new MCQ → Student ✓ PASS → chunk boundary

Chunk 3 signals: first_try_pass_rate = 0.0, recovery = 1
→ 0% first-try rate → SHIFT TOWARD STRUGGLING
→ mode becomes STRUGGLING → API call for chunk 4 → chunk_index = 3
```

━━━━ CHUNK 4 — "Add Whole Numbers" (4 paragraphs) ━━━━
```
Mode = STRUGGLING → ONE LLM call → 4 content + 4 MCQ = 8 cards
(step-by-step, numbered, coding analogies for "technology" interest)

Cards 1–8: content, MCQ, content, MCQ, content, MCQ, content, MCQ
→ Card 6 MCQ: Student ✗ FAIL → FAIL again → RECAP card → advance
→ All 8 cards done → chunk boundary

Chunk 4 signals: first_try_pass_rate = 2/4 = 0.50, recap_count = 1
→ recap_count ≥ 1 → STAY STRUGGLING → chunk_index = 4
```

━━━━ CHUNK 5 — "Add Multiple Digit Numbers" (5 paragraphs) ━━━━
```
Mode = STRUGGLING → 5 content + 5 MCQ = 10 cards
Student passes all 10 MCQs on first try
Chunk 5 signals: first_try_pass_rate = 1.0, recap = 0
→ perfect run → SHIFT TOWARD NORMAL → mode = NORMAL → chunk_index = 5
```

━━━━ CHUNK 6 — "Section 1.2 Exercises" (exercise chunk) ━━━━
```
heading rule: contains "Exercises" → 2 MCQ per teaching chunk
Teaching chunks: 2, 3, 4, 5 = 4 chunks → 8 MCQ cards, SAME difficulty all modes

8 MCQ cards covering all 4 subsections in order
No pass/fail gate — student answers and advances regardless
Wrong-answer explanation adapts to mode (STRUGGLING = step-by-step)
All 8 done → chunk_index = 6 → all chunks complete
```

━━━━ FINAL SOCRATIC EXAM ━━━━
```
Teaching chunks with MCQ: chunks 2, 3, 4, 5 = 4 chunks
Questions: 4 × 2 = 8 typed-answer questions, same difficulty all modes

Q1/Q2: "Use Addition Notation"
Q3/Q4: "Model Addition"
Q5/Q6: "Add Whole Numbers"
Q7/Q8: "Add Multiple Digit Numbers"

Student answers → ADA evaluates each
Result: 5/8 = 62.5% → FAIL (need ≥65%)
Failed: Chunk 3 (0/2), Chunk 5 (1/2)

Student shown choice:
  A) Review only failed chunks (3 and 5), then retry 4 questions
  B) Redo entire section from beginning

Student picks A → chunks 3 and 5 regenerated at STRUGGLING mode
→ 4 new questions for those chunks → 3/4 = 75% → PASS ✓

→ INSERT student_mastery (concept_id: prealgebra_1.2)
→ Section 1.3 unlocks on concept graph
```

### Image sent to LLM — always when chunk has one

```python
if chunk.images:
    # GPT-4o vision — LLM sees actual diagram
    messages = [{"role": "user", "content": [
        {"type": "text",      "text": prompt},
        {"type": "image_url", "image_url": {"url": chunk.images[0].image_url}}
    ]}]
else:
    # text only — no vision tokens, faster + cheaper
    messages = [{"role": "user", "content": prompt}]
```

LLM sees the actual image → generates card content that accurately references the diagram → returns which card index the image belongs to → system attaches `chunk_images.image_url` to that card. No keyword guessing. No mismatches.

### Within-chunk navigation vs chunk boundary API call

**Cards within a chunk are all generated in ONE LLM call** when the chunk starts. Navigation between those cards is instant — no API call, all cards already in memory.

```
Chunk 1 loaded → ONE LLM call → returns [card1, card2, MCQ card]

  Student clicks Next (card1 → card2)      — instant, no API
  Student clicks Next (card2 → MCQ)        — instant, no API
  Student answers MCQ

    PASS:
      → chunk boundary reached
      → mode recalculated (current signals + history blend)
      → ONE API call → backend generates all chunk 2 cards
      → brief "Loading..." indicator
      → chunk 2 card 1 displayed

    FAIL (1st):
      → recovery card: ONE API call using same chunk content, different example
      → student answers new MCQ
      → PASS → chunk boundary → chunk 2 loads as above

    FAIL (2nd):
      → RECAP card shown (content only — student reads, clicks Next)
      → mode locked to STRUGGLING
      → chunk boundary → chunk 2 loads at STRUGGLING mode
```

**API call count per section (e.g., 4 chunks):**
- Optimal path (all pass 1st try): 4 LLM calls (one per chunk)
- With 1 recovery per chunk: up to 8 LLM calls
- Much cheaper than per-card generation — chunk = 2–6 paragraphs per LLM call

---

### Mode recalculation — blended per chunk boundary

After each chunk completes, mode is recalculated before the next chunk is sent to the LLM. The mode is always a **blend of per-chunk performance signals AND historical data**.

**Mode never changes mid-chunk.** One LLM call generates all cards for a chunk. The LLM uses a fixed mode for that entire chunk. Mode only updates at the boundary between chunks.

```
After chunk N completes, collect chunk-level signals:

  first_try_pass_rate = (MCQs passed on first attempt) / (total MCQs in chunk)
    e.g. chunk with 4 MCQs: passed 3 on first try → rate = 0.75
  recap_count       = number of content cards that needed a RECAP (2-fail advance)
  recovery_count    = number of content cards that needed a recovery card
  hints_used        = total hints requested in chunk
  idle_triggers     = idle pauses during chunk

  SHIFT TOWARD STRUGGLING:
    first_try_pass_rate < 0.50   (failed more than half the MCQs)
    OR recap_count ≥ 1           (hit 2-fail at least once — strongest signal)
    OR hints_used > 2

  SHIFT TOWARD FAST:
    first_try_pass_rate = 1.00   (perfect run — every MCQ right first try)
    AND hints_used = 0
    AND recovery_count = 0

  STAY SAME:
    all other cases

  blended_mode = build_blended_analytics(chunk_signals, student_history)

  Blending weights (existing logic in adaptive_engine.py):
    cold-start student (few sessions):  80% current / 20% history
    returning student (many sessions):  20% current / 80% history
```

**Outcome — same chunk content, different card style for next chunk:**
```
Mode shifted NORMAL → STRUGGLING:
  more content cards (each paragraph treated separately)
  simpler vocabulary, 80% analogies from student interests
  MCQ difficulty 1–2 (direct recall)

Mode shifted NORMAL → FAST:
  fewer content cards (LLM merges paragraphs aggressively)
  technical terminology, 20% analogies
  MCQ difficulty 4–5 (edge case + WHY)

Mode unchanged:
  same style as before
```

`build_blended_analytics()` in existing `adaptive_engine.py` — called once per chunk boundary. Per-chunk signals replace the old per-card signals from the previous architecture.

### Simplified LessonCard schema

`card_type` removed entirely. Two card behaviours only — identified by presence of `question` field.
`question2` removed — recovery handled by new LLM call, not pre-packed second question.
`title` kept — displayed in card UI. `image_url` added as primary image field.

```python
class LessonCard:
    index:     int
    title:     str            # short heading (e.g. "The Rounding Rule")
    content:   str            # markdown text from paragraph(s)
    image_url: str | None     # direct URL from chunk_images (chunk-based sessions)
    caption:   str | None     # figure caption
    question:  CardMCQ | None # null = content card,  set = MCQ card
    chunk_id:  str            # which chunk generated this card

    # Legacy fields — only populated for ChromaDB-path sessions, empty for chunk sessions:
    image_indices: list[int] = []
    images:        list[dict] = []
```

```
content card → question is null → frontend renders title + text + image (if image_url set)
MCQ card     → question is set  → frontend renders title + text + answer options
RECAP card   → question is null → content card (student reads, clicks Next — no MCQ)
```

**Frontend rendering rule (zero breakage):**
```javascript
// CardLearningView.jsx
const imageToShow = card.image_url  // new chunk path
    || (card.image_indices?.[0] != null ? session.images[card.image_indices[0]] : null);  // old path
```

Old card types removed: TEACH, EXAMPLE, VISUAL, QUESTION, APPLICATION, EXERCISE, RECAP, FUN, CHECKIN.
All replaced by the two behaviours above.

### Files to modify
```
backend/src/api/teaching_service.py      — replace concept block retrieval with chunk queries
backend/src/adaptive/prompt_builder.py  — build_next_card_prompt accepts chunk + images
backend/src/adaptive/adaptive_engine.py — chunk_index replaces section progress tracking
backend/src/api/prompts.py              — card generation prompt updated for chunk context
backend/src/api/teaching_schemas.py     — LessonCard simplified (remove card_type, add chunk_id)
backend/src/api/knowledge_service.py   — replace ChromaDB queries with pgvector SQL
```

---

## Part 4 — Final Socratic Chat Exam (Section Mastery Gate)

### When it triggers
After all teaching chunks + exercise chunk are completed for a section.

### Structure
```
2 questions per subsection — all modes, same difficulty, real textbook level
Student types answers (Socratic style — not multiple choice)
ADA evaluates each answer and marks correct/incorrect
Pass mark: 65%
```

### Question language rule (all modes)
```
Written in student's chosen language (ar/fr/en/...)
Plain words — no academic jargon, concrete examples not abstract definitions

WRONG: "Define the commutative property of addition."
RIGHT: "If 3 + 5 = 8, what is 5 + 3? Why?"

WRONG: "Explain the associative property."
RIGHT: "Does (2 + 3) + 4 give the same answer as 2 + (3 + 4)? Show your work."
```

### Scoring
```
Section "1.2 Add Whole Numbers" — 4 subsections = 8 questions total

Subsection 1: Q1 ✓  Q2 ✗  → 1/2
Subsection 2: Q3 ✓  Q4 ✓  → 2/2
Subsection 3: Q5 ✗  Q6 ✗  → 0/2
Subsection 4: Q7 ✓  Q8 ✓  → 2/2
Total: 5/8 = 62.5% → FAIL (need ≥65%)
Failed subsections: Subsection 1 (1/2), Subsection 3 (0/2)
```

### Exam fails → student chooses retry path

After any failed attempt the student is shown their score and given a choice:

```
┌─────────────────────────────────────────────────────┐
│  You scored 5/8 (62%). You need 65% to pass.        │
│                                                     │
│  Failed subsections:                                │
│    • Use Addition Notation  (1/2)                   │
│    • Add Whole Numbers      (0/2)                   │
│                                                     │
│  What would you like to do?                         │
│                                                     │
│  A) Review only the sections I got wrong            │
│     (faster — re-study 2 subsections then retry)   │
│                                                     │
│  B) Start the full section again                    │
│     (thorough — go through everything from start)  │
└─────────────────────────────────────────────────────┘
```

**Option A — Targeted retry:**
- Cards regenerated for failed subsections only (mode shifted toward STRUGGLING)
- Student works through those subsection cards
- Retakes 2 NEW questions for each failed subsection only
- Total score recalculated — if ≥65% → MASTERED

**Option B — Full redo:**
- ALL chunks of section regenerated from scratch at STRUGGLING mode
- Student works through entire section (all teaching chunks + exercises)
- Full Socratic exam resets (8 questions again)
- Attempt counter resets to 1

**This choice appears after every failed attempt — no automatic decision.**
Student always controls which path they take.

### Attempt counter — tracks targeted retries only

```
attempt=1: full exam
attempt=2: after student chose A (targeted retry)
attempt=3: after student chose A again (second targeted retry)

After attempt 3 fails:
  → only Option B shown (full redo) — targeted retry exhausted
  → student must redo full section before exam resets
```

### Session persistence — student exits and returns

State saved to `teaching_sessions` after every action:

```sql
exam_attempt     INTEGER DEFAULT 0   -- attempt number (1, 2, 3)
exam_scores      JSONB               -- per-subsection scores {"chunk_id": score}
failed_chunk_ids TEXT[]              -- subsection chunk_ids that failed
exam_phase       TEXT                -- "studying"|"exam"|"retry_study"|"retry_exam"
```

```
Exits mid-exam (answered 3/8)     → returns: resumes from question 4
Fails, exits before choosing A/B  → returns: choice screen shown again
Chose A, exits mid re-study       → returns: resumes re-study from that chunk
Fails attempt 3, exits            → returns: only Option B shown (full redo)
```

Student never loses passed subsection scores. Only failed subsections are retried on Option A.

### Pass → section mastered
```
Score ≥ 65% on any attempt:
  → INSERT into student_mastery (concept_id, student_id)
  → next section unlocks on concept graph
  → student_mode recalculated fresh for next section
```

---

## Part 6 — Concept Graph (Prerequisites, Locked/Unlocked)

### Two-level structure

```
GRAPH LEVEL (concept = ### section)  — prerequisites, locked/unlocked, mastery
    ↓
CHUNK LEVEL (subsection = #### )     — sequential content within a concept
```

Each `###` section in the `.mmd` = one graph node = one concept.
Each `####` subsection = one chunk belonging to that concept.

```
concept_chunks table:
  chunk 1 → concept_id: "prealgebra_1.1"  order_index: 1
  chunk 2 → concept_id: "prealgebra_1.1"  order_index: 2
  chunk 3 → concept_id: "prealgebra_1.1"  order_index: 3
  chunk 4 → concept_id: "prealgebra_1.2"  order_index: 4
  chunk 5 → concept_id: "prealgebra_1.2"  order_index: 5
```

### Graph building (graph_builder.py — new file)

**Step 1 — Nodes: one per `###` section (automatic)**
```
prealgebra_1.1  "Introduction to Whole Numbers"
prealgebra_1.2  "Add Whole Numbers"
prealgebra_1.3  "Subtract Whole Numbers"
prealgebra_1.4  "Multiply Whole Numbers"
prealgebra_1.5  "Divide Whole Numbers"
prealgebra_2.1  "Use the Language of Algebra"
prealgebra_2.2  "Evaluate, Simplify Expressions"
prealgebra_2.3  "Solving Equations"
prealgebra_2.4  "Find Multiples and Factors"
prealgebra_3.1  "Introduction to Integers"
prealgebra_3.2  "Add Integers"
prealgebra_3.3  "Subtract Integers"
prealgebra_3.4  "Multiply and Divide Integers"
prealgebra_3.5  "Solve Equations with Integers"
prealgebra_4.1  "Visualize Fractions"
prealgebra_4.2  "Multiply and Divide Fractions"
prealgebra_4.3  "Multiply and Divide Mixed Numbers"
prealgebra_4.4  "Add and Subtract Fractions"
... (continues through all chapters)
```

**Step 2 — Sequential edges within chapter (automatic, no LLM)**
```
1.1 → 1.2 → 1.3 → 1.4 → 1.5
2.1 → 2.2 → 2.3 → 2.4
3.1 → 3.2 → 3.3 → 3.4 → 3.5
4.1 → 4.2 → 4.3 → 4.4
```
Built from `###` heading order in `.mmd` — no LLM needed.

**Step 3 — Cross-chapter prerequisite edges (LLM extracted)**
LLM reads each section heading + first paragraph → identifies **direct** prerequisites only.
Transitive dependencies propagate automatically through sequential edges — LLM does not need to list them.

```
LLM extracts DIRECT prerequisites only:
  prealgebra_2.1  requires → 1.1, 1.2, 1.3, 1.4, 1.5
  prealgebra_3.1  requires → 1.1
  prealgebra_3.5  requires → 2.3
  prealgebra_4.1  requires → 1.4, 1.5
  prealgebra_4.4  requires → 2.4

LLM does NOT list: 4.2, 4.3, 4.4 also need 1.4, 1.5
  → those inherit the dependency through 4.1 → 4.2 → 4.3 → 4.4 sequential chain automatically
```

**Sequential edges always enforced within a chapter — student cannot skip any section:**
```
To unlock 4.4:  must satisfy 4.3 (sequential) AND any direct cross-chapter edges on 4.4
To unlock 4.3:  must satisfy 4.2 (sequential) AND any direct cross-chapter edges on 4.3
To unlock 4.1:  must satisfy 1.4 + 1.5 (cross-chapter) — first section of chapter 4

Example — if 1.1 + 1.2 are direct prerequisites of 4.1 only:
  1.1 + 1.2 → 4.1 → 4.2 → 4.3 → 4.4
  Student path: master 1.1, master 1.2 → unlocks 4.1
                master 4.1 → unlocks 4.2
                master 4.2 → unlocks 4.3
                master 4.3 → unlocks 4.4
  4.4 inherits the 1.1+1.2 requirement transitively — no direct edge needed
```

**Step 4 — Save to `graph.json` (same format as current)**
```json
{
  "nodes": [
    {"id": "prealgebra_1.1", "title": "Introduction to Whole Numbers"},
    {"id": "prealgebra_1.2", "title": "Add Whole Numbers"}
  ],
  "edges": [
    {"source": "prealgebra_1.1", "target": "prealgebra_1.2"},
    {"source": "prealgebra_1.5", "target": "prealgebra_4.1"}
  ]
}
```

### Lock/unlock logic (unchanged)

A concept is **unlocked** when all prerequisite concepts are in `student_mastery` table.
A concept is **mastered** when student completes all its chunks AND passes every MCQ.

```
Student masters concept 1.1:
  → all chunks of 1.1 completed, all MCQs passed
  → INSERT into student_mastery (student_id, concept_id="prealgebra_1.1")
  → graph traversal: 1.2 prerequisites met? → YES → 1.2 UNLOCKED
  → ConceptMapPage updates automatically
```

### Progress tracking change

```sql
-- teaching_sessions: add chunk_index column
chunk_index INTEGER DEFAULT 0   ← exact position within concept's chunks
```

Concept mastered when `chunk_index = COUNT(*) FROM concept_chunks WHERE concept_id = X`.

### What stays exactly the same

| Component | Status |
|---|---|
| `graph.json` format | ✅ Unchanged |
| `student_mastery` table | ✅ Unchanged |
| Prerequisite traversal in `knowledge_service.py` | ✅ Unchanged |
| ConceptMapPage locked/unlocked visual | ✅ Unchanged |
| Mastery threshold logic | ✅ Unchanged |

### New file
```
backend/src/extraction/graph_builder.py  — reads mmd_parser output →
                                           builds nodes + sequential edges +
                                           LLM cross-chapter edges →
                                           saves graph.json
```

---

## Part 6 — Image Delivery

### Dev (now, zero change needed)
FastAPI already serves `backend/output/` as static files.
Existing image files reused — just registered in `chunk_images` table with local paths.

### Production (when deploying)
Run one-time upload script: all images in `backend/output/` → R2 bucket.
Update `IMAGE_STORAGE=r2` and `IMAGE_BASE_URL` in `backend/.env`.
Zero schema changes — only env vars change.

```python
# backend/src/storage/r2_client.py (new)
def upload_image(local_path: str, key: str) -> str:
    s3.upload_file(local_path, R2_BUCKET, key, ExtraArgs={"ACL": "public-read"})
    return f"{IMAGE_BASE_URL}/{key}"

def resolve_image_url(stored_url: str) -> str:
    if IMAGE_STORAGE == "local":
        return stored_url   # already a local http URL
    return stored_url       # already a full R2 URL set at extraction time
```

---

---

## Conflict & Breaking Change Analysis

This section documents every conflict between the new plan and the existing codebase, with the resolution for each. **Prealgebra first** — other books continue using ChromaDB until explicitly migrated.

### 1. Hybrid Book Routing (Critical)
**Issue**: `main.py` discovers books by scanning for `chroma_db/` subdirectory. After migration, prealgebra uses pgvector but other books still need ChromaDB.
**Resolution**: Book detection logic changes to: check `concept_chunks` table for `book_slug`. If rows exist → use pgvector path. If not → fall back to ChromaDB. `KnowledgeService` gains a `has_chunks(book_slug)` method. `main.py` lifespan scans both sources. Both paths live in parallel during migration period.

### 2. `LessonCard.question2` Removed
**Issue**: Current `LessonCard` has `question2: CardMCQ | None` — a second pre-packed MCQ shown when the first is answered wrong. New plan replaces this with a new LLM call for a recovery card.
**Resolution**: `question2` field **removed**. Recovery = `POST /sessions/{id}/recovery-card` endpoint generates new content+MCQ pair from same chunk. The session cache tracks which MCQ card triggered recovery (`recovery_card_for_index`). Old sessions from ChromaDB path can still serve `question2` — only new chunk-based sessions drop it.

### 3. `image_indices: list[int]` → `image_url: str | None`
**Issue**: Current `LessonCard.image_indices` is a list of integers that the frontend resolves against the session's images array. New plan: single `image_url: str | None` direct URL.
**Resolution**: `LessonCard` keeps both fields during migration period:
```python
image_url: str | None = None      # new: direct URL (chunk-based sessions)
image_indices: list[int] = []     # old: kept for ChromaDB-path sessions, empty for chunk sessions
images: list[dict] = []           # old: kept for ChromaDB-path sessions
```
Frontend checks `image_url` first; falls back to `image_indices` resolution if `image_url` is null. This gives zero breakage on ChromaDB sessions.

### 4. `LessonCard.title` Kept
**Issue**: Current `LessonCard` has `title: str` for display. New plan schema omitted `title`.
**Resolution**: Keep `title` — it is low-cost and displayed in the UI. LLM generates a short heading (the chunk heading or a paragraph-level label). New schema:
```python
class LessonCard:
    index:     int
    title:     str            # short heading (kept — displayed in card UI)
    content:   str            # markdown text from paragraph(s)
    image_url: str | None     # direct URL from chunk_images (new path)
    caption:   str | None     # figure caption (new path)
    question:  CardMCQ | None # null = content card, set = MCQ card
    chunk_id:  str            # which chunk generated this (new path)
    # Legacy fields (ChromaDB path only — empty on chunk sessions):
    image_indices: list[int] = []
    images:        list[dict] = []
```

### 5. Session Cache Format Conflict
**Issue**: Current code stores session state in `session.presentation_text` as JSON with `concepts_queue`, `cards`, `concepts_covered`, `cache_version`. New plan stores position in `chunk_index` DB column.
**Resolution**: New chunk-based sessions use `chunk_index` column (always current). `presentation_text` is repurposed as `session_cache` JSONB for exam state only (`exam_scores`, `failed_chunk_ids`). Old ChromaDB-based sessions still use `presentation_text` queue format. `teaching_service` detects which path to use by checking if `concept_chunks` exist for that `book_slug`.

### 6. `TeachingSession.phase` Mapping
**Issue**: Current phase states: `PRESENTING, CARDS, CARDS_DONE, CHECKING, REMEDIATING, RECHECKING, REMEDIATING_2, RECHECKING_2, COMPLETED`. New plan introduces `studying, exam, retry_study, retry_exam`. Adding `exam_phase` column separately avoids breaking old sessions.
**Resolution**: Reuse existing phase values where possible — the new `exam_phase` column (TEXT, nullable) lives alongside existing `phase`:

| New state | `phase` value | `exam_phase` value |
|---|---|---|
| Chunk studying | `CARDS` | `studying` |
| Exercise chunk | `CARDS` | `studying` |
| Socratic exam active | `CHECKING` | `exam` |
| Targeted retry (re-study) | `REMEDIATING` | `retry_study` |
| Targeted retry (re-exam) | `RECHECKING` | `retry_exam` |
| Section mastered | `COMPLETED` | `null` |

Old ChromaDB sessions: `exam_phase = null` always (no migration needed for existing data).

### 7. `STARTER_PACK_INITIAL_SECTIONS` Obsolete
**Issue**: Current config generates first N=2 sections upfront. New architecture: one chunk at a time — no upfront batching.
**Resolution**: `STARTER_PACK_INITIAL_SECTIONS` used only in ChromaDB path. Chunk path: first chunk generated immediately when session starts. Add new config constant: `CHUNK_CARDS_MAX_TOKENS = 2500` (per-chunk, replaces per-section budgets for chunk path).

### 8. Token Budget — Per-Section → Per-Chunk
**Issue**: Current token budgets: STRUGGLING 40K, NORMAL 32K, FAST 24K for entire section batch. New architecture: one chunk = 2–6 paragraphs → much smaller per-call.
**Resolution**: Add chunk-specific token budgets to `config.py`:
```python
CHUNK_MAX_TOKENS_STRUGGLING = 3000   # ~6 content+MCQ pairs
CHUNK_MAX_TOKENS_NORMAL     = 2000   # ~4 content+MCQ pairs
CHUNK_MAX_TOKENS_FAST       = 1200   # ~2 content+MCQ pairs
CHUNK_MAX_TOKENS_RECOVERY   = 800    # single recovery card+MCQ
```
Old section budgets kept unchanged for ChromaDB path.

### 9. Mastery Threshold Change
**Issue**: Current `MASTERY_THRESHOLD = 70` (Socratic check, score 0-100). New plan: 65% pass rate on typed exam (N questions). Two different thresholds for two different exam types.
**Resolution**: Keep `MASTERY_THRESHOLD = 70` for ChromaDB path. Add new constant: `CHUNK_EXAM_PASS_RATE = 0.65` for chunk-based Socratic exam. Both constants in `config.py`. No existing logic touched.

### 10. `sub_sections` Parameter Format Change
**Issue**: `build_cards_user_prompt()`, `build_presentation_user_prompt()` expect `sub_sections: list[dict]` with `{title, type, text, section_index}`. New chunks have `{id, heading, text, latex, images}` — different shape.
**Resolution**: `prompt_builder.py` gets a new function `build_chunk_card_prompt(chunk: dict, ...)` alongside the existing `build_next_card_prompt()`. Old prompts untouched. Chunk prompt generates interleaved content+MCQ pairs from a single chunk's text.

### 11. Book Discovery Logic Change
**Issue**: `main.py` lifespan: `if (OUTPUT_DIR / book_slug / "chroma_db").exists()` → load book. Post-migration, prealgebra has no `chroma_db/` anymore but has `concept_chunks` rows.
**Resolution**: Detection priority:
```python
# main.py lifespan — hybrid detection
for book_slug in BOOK_CODE_MAP:
    has_chunks = await db.scalar(
        select(func.count()).where(ConceptChunk.book_slug == book_slug)
    ) > 0
    has_chroma = (OUTPUT_DIR / book_slug / "chroma_db").exists()

    if has_chunks:
        knowledge_services[book_slug] = ChunkKnowledgeService(book_slug)
    elif has_chroma:
        knowledge_services[book_slug] = ChromaKnowledgeService(book_slug)
    # else: not loaded
```

### 12. `is_educational` Image Filter Removed for Chunk Path
**Issue**: `teaching_service.py` filters images: `img.get("is_educational") is not False`. `chunk_images` table has no `is_educational` column.
**Resolution**: `chunk_images` images are co-located with their text at extraction time — they are all relevant by definition (Mathpix returns only content images, no decorative ones). No filter needed for chunk path. Filter kept only for ChromaDB path.

### 13. `concept_blocks.json` LaTeX Fallback Obsolete
**Issue**: `knowledge_service.py` loads `concept_blocks.json` at init as LaTeX fallback. New plan: LaTeX stored in `concept_chunks.latex` (TEXT[]) column.
**Resolution**: LaTeX fallback only runs in ChromaDB `KnowledgeService`. New `ChunkKnowledgeService` reads LaTeX directly from DB column. `concept_blocks.json` not deleted yet — kept as backup during migration period.

### 14. `CardInteraction` Table Stays — Now Tracks Per-MCQ-Card
**Issue**: `CardInteraction` records `card_index`, `wrong_attempts`, `hints_used`, `idle_triggers` per card. In new architecture, every MCQ card generates a `CardInteraction` row.
**Resolution**: No change to `CardInteraction` table or `complete-card` endpoint. The `first_try_pass_rate` signal is derived from `CardInteraction` rows for the current session: `wrong_attempts == 0` → passed first try.

### 15. `spaced_reviews` Table — Unchanged
New architecture doesn't change spaced review scheduling. The `SpacedReview` table, `review-due` endpoint, and review completion remain exactly as-is.

### 16. XP Award Trigger
**Issue**: Current XP awarded on `phase == "COMPLETED"` (Socratic check passed). New plan: section mastered via Socratic exam.
**Resolution**: XP awarded when `exam_phase` transitions to `null` (section mastered) AND score ≥ threshold. Same `XP_MASTERY = 50` + `XP_MASTERY_BONUS = 25` if exam score ≥ 90%. Logic lives in the same `_award_xp()` helper.

---

---

## Pre-Execution Checklist (Complete Before Phase 0 Starts)

Everything below must be confirmed BEFORE any agent starts implementing.

### ✅ Must verify before Phase 0 (infrastructure)

| Item | Check | How |
|---|---|---|
| pgvector ≥ 0.5.0 installed on PostgreSQL | HNSW index requires 0.5.0+ | `SELECT extversion FROM pg_extension WHERE extname = 'vector'` |
| prealgebra PDF present | `backend/data/prealgebra.pdf` must exist | `ls backend/data/prealgebra.pdf` |
| Database backup taken | Safety net before any schema change | `pg_dump -U postgres AdaptiveLearner > ada_backup.sql` |
| pgvector extension created in DB | Migration requires `vector` type | `CREATE EXTENSION IF NOT EXISTS vector;` |
| `alembic` in requirements.txt | Phase 0 devops work | `grep alembic backend/requirements.txt` |

### ✅ Must verify before Phase 2 (extraction)

| Item | Check | How |
|---|---|---|
| Mathpix PDF API access enabled | Different from single-image API — may need separate plan | Check `console.mathpix.com` for PDF API quota |
| Test `.mmd` output manually first | Run Mathpix PDF API on Chapter 1 ONLY — inspect `###`/`####` heading structure before full run | Manual API call |
| `pgvector` Python package added to requirements.txt | SQLAlchemy needs it for `vector(1536)` type | `pip install pgvector` + add to requirements.txt |

### ✅ Must verify before Phase 3 (backend services)

| Item | Check | How |
|---|---|---|
| GPT-4o vision API access | Card generation sends images to LLM | Test with `gpt-4o` + `image_url` content block via OpenAI playground |
| New `.env` variables added | `IMAGE_STORAGE`, `IMAGE_BASE_URL` | Add to `backend/.env` and `backend/.env.example` |
| `boto3` added to requirements.txt | R2/S3 client (needed for upload script, can be deferred) | `pip install boto3` |

### ⚠️ Important notes

- **Mathpix PDF API** is not the same as the single-image OCR you currently use. Test it on Chapter 1 before committing to full extraction — you mentioned having issues with `.mmd` before.
- **IVFFlat NOT used** — plan uses HNSW index instead (works on any number of rows). IVFFlat is deferred to production tuning.
- **`create_all()` removed in Phase 0** — Alembic becomes the only way to run migrations. After this change, never run `Base.metadata.create_all()` again.

---

## Phased Execution (Prealgebra First)

**Scope lock**: Every phase below applies to `book_slug = "prealgebra"` only. Other 15 books continue on ChromaDB unchanged until you give the go-ahead.

| Phase | Agent | Work | Prealgebra-specific |
|---|---|---|---|
| **0** | devops-engineer | **Pre-checks**: (a) install `pgvector` on PostgreSQL server via `CREATE EXTENSION IF NOT EXISTS vector` — must run BEFORE any migration; (b) remove `Base.metadata.create_all()` from `db/connection.py` and replace with Alembic as sole migration path. **Migrations**: `concept_chunks` (use `HNSW` index, not IVFFlat), `chunk_images`, + new nullable/defaulted columns on `teaching_sessions` (`chunk_index INTEGER DEFAULT 0`, `exam_phase TEXT`, `exam_attempt INTEGER DEFAULT 0`, `exam_scores JSONB`, `failed_chunk_ids TEXT[]`). **Config**: add `CHUNK_MAX_TOKENS_STRUGGLING/NORMAL/FAST/RECOVERY` and `CHUNK_EXAM_PASS_RATE = 0.65` to `config.py`. **NULL safety**: all code reading `failed_chunk_ids` must use `session.failed_chunk_ids or []`. `.env.example` updates. | All existing session/student rows safe — new columns get DEFAULT values; rollback via `alembic downgrade -1` |
| **1** | solution-architect | HLD + DLD + execution-plan docs in `docs/chunk-architecture/` | n/a |
| **2** | backend-developer | `mathpix_pdf_extractor.py`, `mmd_parser.py`, `chunk_builder.py`, `graph_builder.py`; run extraction for prealgebra → populate `concept_chunks` + `chunk_images` | run pipeline for prealgebra only |
| **3** | backend-developer | `ChunkKnowledgeService` (pgvector queries); update `teaching_service.py` with hybrid routing (chunk vs ChromaDB); `build_chunk_card_prompt()` in `prompt_builder.py`; recovery-card endpoint; Socratic exam endpoint; new session phase transitions; `r2_client.py` scaffold | prealgebra uses new path; other books unchanged |
| **4** | comprehensive-tester | Tests: mmd parsing, chunk building, image co-location, card generation per mode, MCQ pass/fail/recovery/RECAP flow, mode recalculation signals, Socratic exam pass/fail/retry logic, session persistence (exit+resume), hybrid book routing | prealgebra test fixtures only |
| **5** | frontend-developer | Dual `image_url` / `image_indices` rendering; chunk progress indicator; Socratic exam UI (typed answers, score display, A/B retry choice) | update card renderer to check `image_url` first |

---

## Future Optimizations (deferred — implement after testing)

| Optimization | Description |
|---|---|
| Card caching | Cache generated cards per `chunk_id + student_mode + style + language` as JSONB in PostgreSQL. Eliminates repeated LLM+vision calls for same chunk+mode combination across students. |
| R2 image upload | One-time script to upload existing `backend/output/` images to Cloudflare R2. Switch `IMAGE_STORAGE=r2` env var — zero schema changes. |
| pgvector IVFFlat tuning | Tune `lists` parameter on ivfflat index based on actual row count after full extraction. |

---

## What Gets Removed After Migration

| File / Component | Status |
|---|---|
| `backend/src/extraction/pdf_reader.py` | Deleted |
| `backend/src/extraction/text_cleaner.py` | Deleted |
| `backend/src/extraction/section_detector.py` | Deleted |
| `backend/src/extraction/concept_builder.py` | Deleted |
| `backend/src/storage/` (ChromaDB wrapper) | Deleted |
| `backend/output/*/chroma_db/` | Deleted after migration |
| `backend/output/*/image_index.json` | Deleted after migration |
| `requirements.txt` chromadb entry | Removed |

---

## Verification Checklist

### Extraction
1. Run Mathpix PDF API on Chapter 1 of prealgebra → inspect `.mmd` for correct `###`/`####` heading hierarchy
2. Run `mmd_parser.py` → verify ALL blocks stored including Try It, Exercises, Be Careful, Learning Objectives (no content dropped)
3. Run `chunk_builder.py` → verify each chunk row has correct `order_index`, `latex[]`, and `chunk_images` linked where image appears in `.mmd`

### Card Generation — Prealgebra
4. Generate cards for chunk "Round Whole Numbers" with STRUGGLING / NORMAL / FAST → verify:
   - Interleaved content+MCQ pairs (not single MCQ at end)
   - Same `image_url` attached to the content card that references the diagram
   - STRUGGLING: more cards; FAST: fewer merged cards
   - MCQ difficulty scales with mode; content stays the same

5. Generate cards for chunk "Learning Objectives" → verify: 1 overview card, `question = null`, no MCQ

6. Generate cards for exercise chunk "Section 1.1 Exercises" → verify:
   - Only MCQ cards (no content cards)
   - 2 MCQ per teaching subsection that preceded it in the section

### Session Flow
7. Start a session for prealgebra section 1.2, exit after chunk 2 → return → verify `chunk_index = 2` (resumes from chunk 3, not from beginning)
8. Fail MCQ on a content card → verify recovery card generated (new LLM call), `chunk_index` does NOT advance
9. Fail MCQ twice on same card → verify RECAP card shown → `chunk_index` advances on RECAP click (no infinite loop)
10. Complete all chunks including exercise chunk → verify Socratic exam triggered automatically

### Socratic Exam
11. Answer 5/8 questions correctly (62.5%) → verify: FAIL shown, correct subsections identified, A/B choice displayed
12. Choose A (targeted retry) → verify: only failed subsections regenerated at STRUGGLING mode
13. Pass retry exam (≥65%) → verify: `student_mastery` row inserted, next section unlocked in graph

### Hybrid Routing
14. Start session for a non-prealgebra book (e.g. elementary-algebra) → verify: ChromaDB path used, old behaviour unchanged
15. Start session for prealgebra → verify: chunk path used (`concept_chunks` queried, not ChromaDB)
16. Frontend: card from ChromaDB session has `image_indices` populated, `image_url = null` → image resolves via old path
17. Frontend: card from chunk session has `image_url` set, `image_indices = []` → image renders via direct URL

### Data Integrity
18. Confirm all existing `students`, `teaching_sessions`, `student_mastery`, `card_interactions` rows intact after Alembic migration
19. Swap `IMAGE_STORAGE=r2` env var → verify prealgebra images load from R2 URLs
20. Confirm blending weights in `build_blended_analytics()` produce correct STRUGGLING/NORMAL/FAST output for edge-case signal inputs
