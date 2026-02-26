import sys
from pathlib import Path

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
