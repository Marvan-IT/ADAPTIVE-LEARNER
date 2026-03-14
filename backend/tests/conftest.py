import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Make backend/src importable from tests without requiring an editable install.
# Insert at index 0 so the project source takes precedence over any installed copy.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def pytest_configure(config):
    """Register custom markers so tests can be selectively run by category."""
    config.addinivalue_line("markers", "unit: fast, fully-isolated unit tests")
    config.addinivalue_line(
        "markers",
        "integration: tests that require a live database or external service",
    )
    config.addinivalue_line(
        "markers",
        "e2e: full end-to-end tests covering a complete user workflow",
    )


@pytest.fixture
def fake_concept_detail():
    return {
        "concept_id": "PREALG.C1.S1",
        "concept_title": "Introduction to Numbers",
        "summary": "Numbers are the basis of mathematics.",
        "sections": [{"title": "Counting", "text": "We count things using numbers."}],
        "prerequisites": [],
    }


@pytest.fixture
def mock_knowledge_svc(fake_concept_detail):
    svc = MagicMock()
    svc.get_concept_detail = AsyncMock(return_value=fake_concept_detail)
    svc.graph = MagicMock()
    svc.graph.predecessors.return_value = []
    return svc


@pytest.fixture
def mock_llm_client():
    card_json = json.dumps({
        "cards": [{
            "card_type": "TEACH",
            "title": "Let's Try Again — Test Topic",
            "content": "Test content with analogy.",
            "image_indices": [],
            "question": {
                "text": "What is 2+2?",
                "options": ["3", "4", "5", "6"],
                "correct_index": 1,
                "explanation": "2+2=4",
                "difficulty": "EASY"
            }
        }]
    })
    choice = MagicMock()
    choice.message.content = card_json
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client
