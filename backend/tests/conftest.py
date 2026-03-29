import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

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
async def db_session():
    """
    Async SQLAlchemy session for integration tests that require a live PostgreSQL DB.

    Reads DATABASE_URL from the environment (or falls back to the dev default).
    Tests that use this fixture will be skipped automatically if the connection
    cannot be established (via pytest.skip inside the fixture).
    """
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker

        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postre2002@localhost:5432/AdaptiveLearner",
        )
        engine = create_async_engine(db_url, echo=False, future=True)
        async_session_factory = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with async_session_factory() as session:
            yield session
        await engine.dispose()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB not available: {exc}")


@pytest_asyncio.fixture
async def test_chunk(db_session):
    """
    Creates a single ConceptChunk row in the live test DB.

    Depends on the db_session fixture (requires a running PostgreSQL with
    migration 006 applied). Tests that use this fixture are automatically
    skipped if the DB is unavailable (because db_session skips first).

    Column names mirror ConceptChunk in backend/src/db/models.py exactly:
    id, book_slug, concept_id, section, order_index, heading, text, latex, embedding
    """
    from db.models import ConceptChunk  # noqa: PLC0415 — lazy import keeps unit tests fast

    chunk = ConceptChunk(
        id=uuid.uuid4(),
        book_slug="prealgebra",
        concept_id="prealgebra_1.1",
        section="1.1 Introduction to Whole Numbers",
        order_index=0,
        heading="Learning Objectives",
        text="By the end of this section you will be able to: use place value with whole numbers.",
        latex=[],
        embedding=None,
    )
    db_session.add(chunk)
    await db_session.commit()
    await db_session.refresh(chunk)
    return chunk


@pytest_asyncio.fixture
async def test_chunk_image(db_session, test_chunk):
    """
    Creates a single ChunkImage row linked to test_chunk.

    Column names mirror ChunkImage in backend/src/db/models.py exactly:
    id, chunk_id, image_url, caption, order_index
    """
    from db.models import ChunkImage  # noqa: PLC0415 — lazy import keeps unit tests fast

    image = ChunkImage(
        id=uuid.uuid4(),
        chunk_id=test_chunk.id,
        image_url="http://localhost:8889/images/prealgebra/1.1/fig_01.png",
        caption="Figure 1.1 — place value chart",
        order_index=0,
    )
    db_session.add(image)
    await db_session.commit()
    await db_session.refresh(image)
    return image


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
