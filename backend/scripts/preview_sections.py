"""
preview_sections.py
-------------------
Generates a Markdown preview of the first 3 sub-sections of a concept,
with all associated images embedded inline.

Usage:
    cd backend
    python scripts/preview_sections.py [CONCEPT_ID] [N_SECTIONS]

Defaults to PREALG.C1.S4.MULTIPLY_WHOLE_NUMBERS, first 3 sections.
Output: ../docs/section-preview/{concept_slug}.md
"""

import json
import re
import sys
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).parent.parent
OUTPUT_DIR  = BACKEND_DIR / "output" / "prealgebra"
CHROMA_DIR  = OUTPUT_DIR / "chroma_db"
IMAGE_INDEX = OUTPUT_DIR / "image_index.json"
IMAGES_DIR  = OUTPUT_DIR / "images"
DOCS_OUT    = BACKEND_DIR.parent / "docs" / "section-preview"
DOCS_OUT.mkdir(parents=True, exist_ok=True)

CONCEPT_ID  = sys.argv[1] if len(sys.argv) > 1 else "PREALG.C1.S4.MULTIPLY_WHOLE_NUMBERS"
N_SECTIONS  = int(sys.argv[2]) if len(sys.argv) > 2 else 3


# ── 1. Load concept text from ChromaDB ──────────────────────────────────────
def load_concept_text(concept_id: str) -> str:
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # Try both known collection names
    for coll_name in ("concepts_prealgebra", "openstax_concepts"):
        try:
            col = client.get_collection(coll_name)
            result = col.get(ids=[concept_id], include=["documents"])
            if result["documents"]:
                return result["documents"][0]
        except Exception:
            continue
    raise RuntimeError(f"Concept '{concept_id}' not found in ChromaDB at {CHROMA_DIR}")


# ── 2. Parse sub-sections (mirrors teaching_service._parse_sub_sections) ────
def parse_sub_sections(text: str) -> list[dict]:
    sections = []
    current_title = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        if line.startswith("## "):
            if current_title or current_lines:
                sections.append({
                    "title": current_title or "Introduction",
                    "text":  "\n".join(current_lines).strip(),
                })
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_title or current_lines:
        sections.append({
            "title": current_title or "Introduction",
            "text":  "\n".join(current_lines).strip(),
        })

    return [s for s in sections if s["text"]]


# ── 3. Load images from image_index.json ────────────────────────────────────
def load_images(concept_id: str) -> list[dict]:
    with open(IMAGE_INDEX, encoding="utf-8") as f:
        index = json.load(f)
    images = index.get(concept_id, [])

    concept_img_dir = IMAGES_DIR / concept_id
    for i, img in enumerate(images):
        # Try logical filename first, fall back to zero-padded index
        candidates = [
            concept_img_dir / img.get("filename", ""),
            concept_img_dir / f"{concept_id}_{i:03d}.jpeg",
            concept_img_dir / f"{img.get('page', '')}.jpeg",
        ]
        img["_path"] = next((str(p) for p in candidates if p.exists()), None)
        # Relative path from docs/section-preview/ for markdown embedding
        if img["_path"]:
            try:
                img["_rel"] = Path(img["_path"]).relative_to(BACKEND_DIR.parent).as_posix()
                img["_rel"] = "../../" + img["_rel"]
            except ValueError:
                img["_rel"] = img["_path"]

    return images


# ── 4. Distribute images across sections by document order ──────────────────
def assign_images_to_sections(images: list[dict], n: int) -> list[list[dict]]:
    """Split images into n roughly equal buckets (in document order)."""
    buckets: list[list[dict]] = [[] for _ in range(n)]
    if not images:
        return buckets
    chunk = max(1, len(images) // n)
    for i, img in enumerate(images):
        bucket_idx = min(i // chunk, n - 1)
        buckets[bucket_idx].append(img)
    return buckets


# ── 5. Render markdown ───────────────────────────────────────────────────────
def render_md(concept_id: str, sections: list[dict], image_buckets: list[list[dict]]) -> str:
    title = concept_id.split(".")[-1].replace("_", " ").title()
    lines = [
        f"# {title} — Section Preview",
        f"",
        f"> **Concept:** `{concept_id}`  ",
        f"> **Sections shown:** {len(sections)}  ",
        f"> **Total images:** {sum(len(b) for b in image_buckets)}",
        f"",
        "---",
        "",
    ]

    total = len(sections)
    for idx, sec in enumerate(sections):
        bucket = image_buckets[idx] if idx < len(image_buckets) else []

        lines.append(f"## Section {idx + 1} of {total}: {sec['title']}")
        lines.append("")
        lines.append(sec["text"])
        lines.append("")

        if bucket:
            lines.append("### Images for this section")
            lines.append("")
            lines.append("| # | File | Page | Type | Description |")
            lines.append("|---|------|------|------|-------------|")
            for j, img in enumerate(bucket):
                fname = img.get("filename", "?")
                page  = img.get("page", "?")
                itype = img.get("image_type", "?")
                desc  = (img.get("description") or "").replace("\n", " ")[:120]
                lines.append(f"| {j} | `{fname}` | {page} | {itype} | {desc} |")
            lines.append("")

            for img in bucket:
                desc = (img.get("description") or img.get("filename", "image")).split(".")[0][:60]
                if img.get("_rel"):
                    lines.append(f"![{desc}]({img['_rel']})")
                else:
                    lines.append(f"> ⚠️ Image file not found: `{img.get('filename')}`")
                lines.append("")
        else:
            lines.append("*No images assigned to this section.*")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print(f"Loading concept text for {CONCEPT_ID}...")
    text = load_concept_text(CONCEPT_ID)
    print(f"  Text length: {len(text):,} chars")

    all_sections = parse_sub_sections(text)
    print(f"  Total sections parsed: {len(all_sections)}")
    for i, s in enumerate(all_sections):
        print(f"    [{i+1}] {s['title']!r}  ({len(s['text'])} chars)")

    sections = all_sections[:N_SECTIONS]
    print(f"\nUsing first {len(sections)} sections.")

    images = load_images(CONCEPT_ID)
    print(f"  Images in index: {len(images)}")
    found = sum(1 for img in images if img.get("_path"))
    print(f"  Images found on disk: {found}")

    buckets = assign_images_to_sections(images, len(sections))
    for i, b in enumerate(buckets):
        print(f"  Section {i+1} gets {len(b)} image(s)")

    md = render_md(CONCEPT_ID, sections, buckets)

    slug = CONCEPT_ID.lower().replace(".", "-")
    out_path = DOCS_OUT / f"{slug}.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"\nOutput written to: {out_path}")
    print("Open in VSCode with Ctrl+Shift+V to preview.")


if __name__ == "__main__":
    main()
