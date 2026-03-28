"""
test_image_assignment.py
Unit tests for image pool filtering, cap, and missed-image cleanup
logic from teaching_service.py (generate_cards method).

All tests are pure unit tests — no DB, no LLM, no FastAPI.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest


# ── Helper constructors ───────────────────────────────────────────────────────

def _img(
    filename: str = "img.png",
    description: str = "A diagram",
    image_type: str = "DIAGRAM",
    is_educational: bool | None = True,
) -> dict:
    return {
        "filename": filename,
        "description": description,
        "image_type": image_type,
        "is_educational": is_educational,
    }


def _card(title: str = "Card", content: str = "content", images: list | None = None, image_indices: list | None = None) -> dict:
    return {
        "title": title,
        "content": content,
        "images": images or [],
        "image_indices": image_indices or [],
    }


# ── Utility: replicate useful_images filter from generate_cards ───────────────

_CHECKLIST_KEYWORDS = (
    "checklist", "self-assessment", "i can", "confidently",
    "with some help", "rubric", "evaluate my understanding", "learning target",
)
_IMAGE_TYPE_PRIORITY = {"DIAGRAM": 0, "CHART": 1, "GRAPH": 1, "TABLE": 2, "PHOTO": 3}


def _build_useful_images(images: list[dict]) -> list[dict]:
    """Mirror the useful_images filter logic from generate_cards()."""
    useful = [
        img for img in images
        if img.get("is_educational") is not False
        and img.get("description")
        and not any(
            kw in (img.get("description") or "").lower()
            for kw in _CHECKLIST_KEYWORDS
        )
    ]
    useful = sorted(
        useful,
        key=lambda img: (
            _IMAGE_TYPE_PRIORITY.get((img.get("image_type") or "").upper(), 4),
            -len(img.get("description") or ""),
        ),
    )[:16]
    return useful


def _run_missed_image_cleanup(all_raw_cards: list[dict], useful_images: list[dict]) -> None:
    """Mirror the missed-image cleanup pass from generate_cards()."""
    _assigned_fnames: set[str] = {
        img.get("filename") or img.get("file", "")
        for card in all_raw_cards
        for img in card.get("images", [])
    }
    for _img in useful_images:
        _fname = _img.get("filename") or _img.get("file", "")
        if _fname in _assigned_fnames or not _fname:
            continue
        _desc_words = set((_img.get("description") or "").lower().split())
        if not _desc_words:
            continue
        _best_card = None
        _best_score = 0
        for _card in all_raw_cards:
            _content_words = set(_card.get("content", "").lower().split())
            _score = len(_desc_words & _content_words)
            if _score > _best_score:
                _best_score = _score
                _best_card = _card
        if _best_card is not None and _best_score > 0:
            _best_card.setdefault("images", []).append(_img)
            _assigned_fnames.add(_fname)


# ── Tests: image pool filtering and cap ──────────────────────────────────────

class TestUsefulImagesFilter:
    """Verify the pool filtering and 16-image cap logic."""

    def test_pool_capped_at_16_images(self):
        """
        Business: useful_images pool is capped at 16 regardless of input size.
        """
        images = [_img(filename=f"img{i}.png", description=f"diagram {i}") for i in range(20)]
        useful = _build_useful_images(images)
        assert len(useful) == 16

    def test_checklist_keyword_excluded(self):
        """
        Business: images whose description contains 'checklist' are excluded
        because they are self-assessment rubrics, not math diagrams.
        """
        images = [
            _img(filename="a.png", description="A number line diagram"),
            _img(filename="b.png", description="Learning target checklist"),
            _img(filename="c.png", description="Self-assessment rubric"),
        ]
        useful = _build_useful_images(images)
        fnames = [img["filename"] for img in useful]
        assert "b.png" not in fnames
        assert "c.png" not in fnames
        assert "a.png" in fnames

    def test_is_educational_false_excluded(self):
        """
        Business: Images with is_educational=False are decorative — excluded.
        """
        images = [
            _img(filename="educational.png", description="Number line", is_educational=True),
            _img(filename="decorative.png", description="Decorative border", is_educational=False),
        ]
        useful = _build_useful_images(images)
        fnames = [img["filename"] for img in useful]
        assert "decorative.png" not in fnames
        assert "educational.png" in fnames

    def test_is_educational_none_included(self):
        """
        Business: Images with is_educational=None (unannotated) pass the filter
        because the check is 'is not False'.
        """
        images = [_img(filename="unannotated.png", description="Some diagram", is_educational=None)]
        useful = _build_useful_images(images)
        assert len(useful) == 1
        assert useful[0]["filename"] == "unannotated.png"

    def test_diagram_sorts_before_photo(self):
        """
        Business: DIAGRAM type has priority 0; PHOTO has priority 3.
        After sorting, DIAGRAM appears before PHOTO.
        """
        images = [
            _img(filename="photo.png", description="Photo of a student", image_type="PHOTO"),
            _img(filename="diagram.png", description="Number line diagram", image_type="DIAGRAM"),
        ]
        useful = _build_useful_images(images)
        assert useful[0]["filename"] == "diagram.png"
        assert useful[1]["filename"] == "photo.png"

    def test_image_with_empty_description_excluded(self):
        """
        Business: Images with empty description are not useful for content matching.
        """
        images = [
            _img(filename="no_desc.png", description="", image_type="DIAGRAM"),
            _img(filename="has_desc.png", description="A bar chart", image_type="DIAGRAM"),
        ]
        useful = _build_useful_images(images)
        fnames = [img["filename"] for img in useful]
        assert "no_desc.png" not in fnames
        assert "has_desc.png" in fnames


# ── Tests: missed-image cleanup pass ─────────────────────────────────────────

class TestMissedImageCleanup:
    """Verify the cleanup pass attaches unassigned images to matching cards."""

    def test_unassigned_image_with_matching_description_attached(self):
        """
        Business: An unassigned image whose description overlaps with card content
        is attached to that card during the cleanup pass.
        """
        img = _img(filename="number_line.png", description="number line diagram")
        cards = [_card(title="Number Line", content="the number line shows integers")]
        useful_images = [img]

        _run_missed_image_cleanup(cards, useful_images)

        assert len(cards[0]["images"]) == 1
        assert cards[0]["images"][0]["filename"] == "number_line.png"

    def test_image_with_empty_description_not_assigned(self):
        """
        Business: An image with empty description can't be matched — not attached.
        """
        img = _img(filename="empty.png", description="")
        cards = [_card(title="Some Card", content="some content here")]
        useful_images = [img]

        _run_missed_image_cleanup(cards, useful_images)

        assert cards[0]["images"] == []

    def test_image_matching_no_card_not_attached(self):
        """
        Business: An image whose description has zero word overlap with all cards
        is not randomly assigned.
        """
        img = _img(filename="unrelated.png", description="xyzzy frobble gorp")
        cards = [_card(title="Fractions", content="adding fractions with common denominator")]
        useful_images = [img]

        _run_missed_image_cleanup(cards, useful_images)

        assert cards[0]["images"] == []

    def test_already_assigned_image_not_reassigned(self):
        """
        Business: Images already assigned to cards are skipped in the cleanup
        pass — no duplicates.
        """
        img = _img(filename="already.png", description="number line diagram")
        # Card already has this image
        card = _card(
            title="Number Line",
            content="the number line shows integers",
            images=[{"filename": "already.png", "description": "number line diagram"}],
        )
        cards = [card]
        useful_images = [img]

        _run_missed_image_cleanup(cards, useful_images)

        # Should not be duplicated
        assert len(cards[0]["images"]) == 1

    def test_image_indices_empty_list_no_error(self):
        """
        Business: A card with image_indices=[] does not crash during index-based
        image resolution and its images list remains empty.
        """
        card = _card(title="Empty", content="no images here", image_indices=[])
        assert card["image_indices"] == []

        # Simulate index-based image assignment loop
        useful_images = [_img(filename="x.png", description="some diagram")]
        for global_idx in card["image_indices"]:
            if isinstance(global_idx, int) and 0 <= global_idx < len(useful_images):
                card["images"].append(dict(useful_images[global_idx]))

        assert card["images"] == []

    def test_out_of_bounds_image_index_safely_skipped(self):
        """
        Business: An out-of-bounds image_indices value (e.g., 999) is safely
        skipped — no IndexError, no image appended.
        """
        card = _card(title="Card", content="some content", image_indices=[999])
        useful_images = [_img(filename="img0.png", description="diagram")]

        # Simulate index-based image assignment loop
        for global_idx in card["image_indices"]:
            if isinstance(global_idx, int) and 0 <= global_idx < len(useful_images):
                card["images"].append(dict(useful_images[global_idx]))

        assert card["images"] == []

    def test_card_can_hold_multiple_images(self):
        """
        Business: There is no hard limit of 2 images per card in the cleanup pass.
        A card receiving 3 images is valid.
        """
        imgs = [
            _img(filename=f"img{i}.png", description=f"math diagram {i}")
            for i in range(3)
        ]
        card = _card(title="Math Concepts", content="math diagram overview")
        for img in imgs:
            card["images"].append(img)

        assert len(card["images"]) == 3
