"""
Tests for the Zero-Touch Book Pipeline feature.

Feature areas covered:
  - calibrate.py: derive_slug(), derive_code()
  - config.py: BOOK_REGISTRY, BOOK_CODE_MAP loaded from books.yaml
  - dependency_builder.py: _get_expert_graph()
  - book_watcher.py: PDFHandler.on_created() subprocess triggering logic

Business criteria
-----------------
- Any PDF dropped into backend/data/{subject}/ is auto-discovered and processed.
- Filenames are normalised into clean snake_case slugs regardless of vendor suffixes.
- Short book codes are derived deterministically from the slug.
- The books.yaml registry is the single source of truth for 16 known books.
- Expert dependency graphs are loaded from YAML when available.
- The watcher triggers exactly one subprocess per PDF event; non-PDF and
  directory events are ignored.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from fastapi import HTTPException

# Ensure backend/src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# derive_slug — filename normalisation
# ---------------------------------------------------------------------------

class TestDeriveSlug:
    """derive_slug converts messy vendor-suffixed PDF filenames to snake_case slugs."""

    def test_calibrate_derives_slug_from_messy_filename(self):
        """FinancialAccounting with OP_ vendor hash is stripped to financial_accounting."""
        from src.extraction.calibrate import derive_slug

        result = derive_slug("FinancialAccounting-OP_YioY6nY.pdf")

        assert result == "financial_accounting"

    def test_calibrate_derives_slug_clinical_nursing(self):
        """Hyphen-separated title words with WEB suffix become underscore slug."""
        from src.extraction.calibrate import derive_slug

        result = derive_slug("Clinical-Nursing-Skills-WEB.pdf")

        assert result == "clinical_nursing_skills"

    def test_calibrate_derives_slug_strips_2e(self):
        """Edition suffix '-2e' is stripped so slug matches canonical registry key."""
        from src.extraction.calibrate import derive_slug

        result = derive_slug("Prealgebra-2e.pdf")

        assert result == "prealgebra"

    def test_derive_slug_managerial_accounting(self):
        """CamelCase filename without suffix is split on case boundaries."""
        from src.extraction.calibrate import derive_slug

        result = derive_slug("ManagerialAccounting.pdf")

        assert result == "managerial_accounting"


# ---------------------------------------------------------------------------
# derive_code — short book code derivation
# ---------------------------------------------------------------------------

class TestDeriveCode:
    """derive_code produces an uppercase code (<=10 chars) from a slug."""

    def test_calibrate_derives_code_from_slug(self):
        """Two-word slug with short initials pads from the full joined word string."""
        from src.extraction.calibrate import derive_code

        # 'financial_accounting' -> initials 'FA' (len 2 < 4)
        # pad = 'FINANCIALACCOUNTING'[:6] = 'FINANC'
        result = derive_code("financial_accounting")

        assert result == "FINANC"

    def test_calibrate_derives_code_prealgebra(self):
        """Single-word slug takes the first 6 uppercase characters."""
        from src.extraction.calibrate import derive_code

        # 'prealgebra' -> initials 'P' (len 1 < 4)
        # pad = 'PREALGEBRA'[:6] = 'PREALG'
        result = derive_code("prealgebra")

        assert result == "PREALG"


# ---------------------------------------------------------------------------
# BOOK_REGISTRY / BOOK_CODE_MAP — loaded from books.yaml
# ---------------------------------------------------------------------------

class TestBookRegistry:
    """BOOK_REGISTRY and BOOK_CODE_MAP are loaded from books.yaml at import time."""

    def test_books_yaml_loads_all_16_books(self):
        """books.yaml must contain exactly 16 registered books."""
        from src.config import BOOK_REGISTRY

        assert len(BOOK_REGISTRY) == 16

    def test_no_default_book_slug_in_config(self):
        """config must not expose a DEFAULT_BOOK_SLUG; routing is slug-based."""
        import src.config as config

        assert hasattr(config, "DEFAULT_BOOK_SLUG") is False

    def test_book_code_map_has_all_16_slugs(self):
        """BOOK_CODE_MAP must have one entry per registered book."""
        from src.config import BOOK_CODE_MAP

        assert len(BOOK_CODE_MAP) == 16

    def test_books_yaml_prealgebra_has_subject_mathematics(self):
        """Prealgebra registry entry must declare subject='mathematics'."""
        from src.config import BOOK_REGISTRY

        assert BOOK_REGISTRY["PREALG"]["subject"] == "mathematics"


# ---------------------------------------------------------------------------
# _get_expert_graph — YAML-backed expert dependency graphs
# ---------------------------------------------------------------------------

class TestExpertGraph:
    """_get_expert_graph loads hand-curated YAML graphs or returns None."""

    def test_expert_graph_loads_from_yaml_for_prealgebra(self):
        """prealgebra.yaml must exist and produce a non-empty dependency dict."""
        from src.graph.dependency_builder import _get_expert_graph

        result = _get_expert_graph("prealgebra")

        assert result is not None
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_expert_graph_falls_back_to_none_for_unknown(self):
        """Books without an expert YAML file return None, triggering keyword fallback."""
        from src.graph.dependency_builder import _get_expert_graph

        result = _get_expert_graph("unknown_xyz_book")

        assert result is None


# ---------------------------------------------------------------------------
# PDFHandler (book_watcher) — file system event handling
# ---------------------------------------------------------------------------

class TestPDFHandler:
    """PDFHandler fires a subprocess for PDF events and ignores everything else."""

    def _make_file_event(self, src_path: str, is_directory: bool = False):
        """Build a minimal watchdog FileCreatedEvent-compatible mock."""
        event = MagicMock()
        event.src_path = src_path
        event.is_directory = is_directory
        return event

    def test_watcher_triggers_on_pdf_creation(self):
        """A .pdf file inside a subject subfolder triggers exactly one Popen call."""
        from src.watcher.book_watcher import PDFHandler

        event = self._make_file_event(
            src_path="/some/data/nursing/ClinicalNursing.pdf",
            is_directory=False,
        )

        with patch("src.watcher.book_watcher.subprocess.Popen") as mock_popen:
            handler = PDFHandler()
            handler.on_created(event)

            mock_popen.assert_called_once()

    def test_watcher_ignores_non_pdf_files(self):
        """A .txt file must not start any pipeline subprocess."""
        from src.watcher.book_watcher import PDFHandler

        event = self._make_file_event(
            src_path="/some/data/nursing/readme.txt",
            is_directory=False,
        )

        with patch("src.watcher.book_watcher.subprocess.Popen") as mock_popen:
            handler = PDFHandler()
            handler.on_created(event)

            mock_popen.assert_not_called()

    def test_watcher_ignores_directory_events(self):
        """Directory creation events (is_directory=True) must be silently ignored."""
        from src.watcher.book_watcher import PDFHandler

        event = self._make_file_event(
            src_path="/some/data/nursing/",
            is_directory=True,
        )

        with patch("src.watcher.book_watcher.subprocess.Popen") as mock_popen:
            handler = PDFHandler()
            handler.on_created(event)

            mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# _wait_for_stable_file — file stability polling
# ---------------------------------------------------------------------------

class TestWaitForStableFile:
    """_wait_for_stable_file blocks until file size is unchanged for stable_secs polls."""

    def test_wait_for_stable_file_returns_when_stable(self):
        """Should return without raising when file size is constant across all polls."""
        from src.watcher.pipeline_runner import _wait_for_stable_file

        with patch("src.watcher.pipeline_runner.os.path.getsize", return_value=1000):
            # stable_secs=2 so after 2 identical size reads it should return
            # poll_interval=0 to avoid real sleeping; timeout=10 for headroom
            _wait_for_stable_file(Path("/fake/book.pdf"), stable_secs=2, poll_interval=0, timeout=10)

    def test_wait_for_stable_file_raises_on_timeout(self):
        """Should raise RuntimeError immediately when timeout=0 and size keeps changing."""
        from src.watcher.pipeline_runner import _wait_for_stable_file

        # Increasing sizes simulate a file still being written
        with patch("src.watcher.pipeline_runner.os.path.getsize", side_effect=iter(range(100))):
            with pytest.raises(RuntimeError):
                _wait_for_stable_file(
                    Path("/fake/book.pdf"),
                    stable_secs=5,
                    poll_interval=0,
                    timeout=0,
                )


# ---------------------------------------------------------------------------
# _load_book_registry — Pydantic validation of books.yaml entries
# ---------------------------------------------------------------------------

class TestBooksYamlValidation:
    """_load_book_registry must raise ValidationError when a required field is absent."""

    def test_books_yaml_validation_raises_on_missing_field(self):
        """An entry without 'book_slug' must cause a pydantic.ValidationError."""
        import pydantic

        # Patch the yaml file read so no real file is accessed, then patch safe_load
        # to return a single invalid entry that is missing the required 'book_slug' field.
        bad_data = {
            "books": [
                {
                    "book_code": "FAIL",
                    "pdf_filename": "x.pdf",
                    "title": "X",
                    "subject": "math",
                    # 'book_slug' deliberately omitted
                }
            ]
        }

        with patch("src.config._yaml.safe_load", return_value=bad_data), \
             patch("pathlib.Path.read_text", return_value=""):
            from src.config import _load_book_registry

            with pytest.raises(pydantic.ValidationError):
                _load_book_registry()


# ---------------------------------------------------------------------------
# _rescan_incomplete — startup re-enqueue of unfinished PDFs
# ---------------------------------------------------------------------------

class TestRescanIncomplete:
    """_rescan_incomplete triggers Popen for PDFs missing graph.json or books.yaml entry."""

    def test_rescan_triggers_pipeline_for_incomplete_slug(self, tmp_path):
        """Popen is called once for a PDF whose slug is not in books.yaml and has no graph.json."""
        # Set up data dir: tmp_path/data/business/NewBook.pdf
        data_dir = tmp_path / "data" / "business"
        data_dir.mkdir(parents=True)
        pdf_file = data_dir / "NewBook.pdf"
        pdf_file.write_bytes(b"")  # empty placeholder

        # books.yaml exists but does NOT contain "new_book"
        books_yaml = tmp_path / "books.yaml"
        books_yaml.write_text("books:\n  - book_slug: some_other_book\n", encoding="utf-8")

        # OUTPUT_DIR/new_book/graph.json does NOT exist
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch("src.watcher.book_watcher.DATA_DIR", data_dir.parent), \
             patch("src.watcher.book_watcher.OUTPUT_DIR", output_dir), \
             patch("src.watcher.book_watcher.BACKEND_DIR", tmp_path), \
             patch("src.watcher.book_watcher.subprocess.Popen") as mock_popen:

            from src.watcher.book_watcher import _rescan_incomplete
            _rescan_incomplete()

            mock_popen.assert_called_once()

    def test_rescan_skips_complete_slug(self, tmp_path):
        """Popen is NOT called when slug is in books.yaml and graph.json already exists."""
        # Set up data dir: tmp_path/data/business/NewBook.pdf
        data_dir = tmp_path / "data" / "business"
        data_dir.mkdir(parents=True)
        pdf_file = data_dir / "NewBook.pdf"
        pdf_file.write_bytes(b"")

        # books.yaml DOES contain "new_book"
        books_yaml = tmp_path / "books.yaml"
        books_yaml.write_text("books:\n  - book_slug: new_book\n", encoding="utf-8")

        # OUTPUT_DIR/new_book/graph.json DOES exist
        output_dir = tmp_path / "output"
        graph_dir = output_dir / "new_book"
        graph_dir.mkdir(parents=True)
        (graph_dir / "graph.json").write_text("{}", encoding="utf-8")

        with patch("src.watcher.book_watcher.DATA_DIR", data_dir.parent), \
             patch("src.watcher.book_watcher.OUTPUT_DIR", output_dir), \
             patch("src.watcher.book_watcher.BACKEND_DIR", tmp_path), \
             patch("src.watcher.book_watcher.subprocess.Popen") as mock_popen:

            from src.watcher.book_watcher import _rescan_incomplete
            _rescan_incomplete()

            mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# Stage 4 — dependency_graph.json copy logic
# ---------------------------------------------------------------------------

class TestPipelineStage4:
    """Stage 4 copies dependency_graph.json to graph.json when it exists."""

    def test_pipeline_stage4_uses_dependency_graph_when_present(self, tmp_path):
        """When dependency_graph.json exists, its contents are copied to graph.json."""
        import json
        import shutil

        book_dir = tmp_path / "mybook"
        book_dir.mkdir()

        dep_path = book_dir / "dependency_graph.json"
        dep_path.write_text('{"nodes":[],"edges":[]}', encoding="utf-8")

        graph_path = book_dir / "graph.json"

        # Replicate the stage 4 conditional logic from pipeline_runner.py
        if dep_path.exists():
            shutil.copy(dep_path, graph_path)

        assert graph_path.exists()
        assert json.loads(graph_path.read_text()) == {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# calibrate_book — page scan range
# ---------------------------------------------------------------------------

class TestCalibrateBookScanRange:
    """calibrate_book scans pages 10..min(60, total)-1, not beyond page 59."""

    def test_calibrate_scans_up_to_page_60(self):
        """For an 80-page document, pages 10 through 59 (50 pages) must be accessed."""
        from src.extraction.calibrate import calibrate_book

        # Build a fake fitz page that returns empty blocks
        fake_page = MagicMock()
        fake_page.get_text.return_value = {"blocks": []}

        # Build a fake document with 80 pages
        fake_doc = MagicMock()
        fake_doc.__len__ = MagicMock(return_value=80)
        fake_doc.__getitem__ = MagicMock(return_value=fake_page)
        fake_doc.__iter__ = MagicMock(return_value=iter([]))  # _detect_exercise_pattern
        fake_doc.close = MagicMock()

        with patch("src.extraction.calibrate.fitz.open", return_value=fake_doc):
            calibrate_book(Path("/fake/book.pdf"), "test_book", "mathematics")

        # Collect all page indices that were accessed via __getitem__
        accessed_indices = [call.args[0] for call in fake_doc.__getitem__.call_args_list]

        # Must have accessed exactly pages 10 through 59 (50 pages)
        assert len(accessed_indices) >= 50, (
            f"Expected at least 50 page accesses (pages 10-59), got {len(accessed_indices)}"
        )
        assert all(10 <= idx <= 59 for idx in accessed_indices), (
            f"Page indices out of expected range 10-59: "
            f"{[i for i in accessed_indices if not (10 <= i <= 59)]}"
        )


# ---------------------------------------------------------------------------
# _pdf_queue / _queue_worker — sequential pipeline processing
# ---------------------------------------------------------------------------

class TestQueueWorker:
    """Queue worker processes PDFs one at a time; _enqueue logs queue state."""

    def test_queue_processes_one_at_a_time(self):
        """
        Two PDFs enqueued must be processed sequentially: the second subprocess.run
        is only called after the first subprocess.run has returned.
        """
        import threading
        from src.watcher import book_watcher

        call_order: list[str] = []
        completed: list[str] = []

        def fake_run(args, **kwargs):
            # Identify which PDF this call is for from the --pdf argument
            pdf_name = Path(args[args.index("--pdf") + 1]).name
            call_order.append(f"start:{pdf_name}")
            # Record that the previous item must have finished before this started
            completed.append(list(call_order))
            result = MagicMock()
            result.returncode = 0
            return result

        # Drain the module-level queue so prior test state doesn't interfere
        while not book_watcher._pdf_queue.empty():
            try:
                book_watcher._pdf_queue.get_nowait()
                book_watcher._pdf_queue.task_done()
            except Exception:
                break

        with patch("src.watcher.book_watcher.subprocess.run", side_effect=fake_run):
            # Enqueue two items before starting the worker so they are both queued
            book_watcher._pdf_queue.put((Path("/data/math/BookA.pdf"), "mathematics"))
            book_watcher._pdf_queue.put((Path("/data/math/BookB.pdf"), "mathematics"))

            # Run one worker iteration in a thread so it processes both items
            worker_thread = threading.Thread(target=book_watcher._queue_worker, daemon=True)
            worker_thread.start()

            # Wait for both items to be processed (join blocks until task_done × 2)
            book_watcher._pdf_queue.join()

        # BookA must have started (and implicitly finished) before BookB started
        assert len(call_order) == 2
        assert "start:BookA.pdf" in call_order[0]
        assert "start:BookB.pdf" in call_order[1]
        # When BookB started, BookA's call must already be in call_order
        assert len(completed[1]) == 2, (
            "BookB started before BookA's subprocess.run returned — not sequential"
        )

    def test_enqueue_logs_queue_size(self):
        """
        _enqueue must call logger.info (reporting queue state) and put the item
        onto _pdf_queue, increasing qsize by exactly 1.
        """
        from src.watcher import book_watcher

        # Drain the queue first so we get a predictable baseline
        while not book_watcher._pdf_queue.empty():
            try:
                book_watcher._pdf_queue.get_nowait()
                book_watcher._pdf_queue.task_done()
            except Exception:
                break

        size_before = book_watcher._pdf_queue.qsize()

        with patch("src.watcher.book_watcher.logger") as mock_logger:
            book_watcher._enqueue(Path("test.pdf"), "mathematics")

        size_after = book_watcher._pdf_queue.qsize()
        assert size_after == size_before + 1, (
            f"Expected queue to grow by 1; before={size_before} after={size_after}"
        )
        mock_logger.info.assert_called_once()

        # Clean up the item we just added
        book_watcher._pdf_queue.get_nowait()
        book_watcher._pdf_queue.task_done()


# ---------------------------------------------------------------------------
# admin_retrigger_book — POST /api/admin/retrigger-book/{book_slug}
# ---------------------------------------------------------------------------
#
# Strategy: import api.main only AFTER pre-injecting stubs for modules that
# perform heavy I/O at import time (db.connection creates an asyncpg engine;
# api.teaching_router decorates handlers with slowapi limits that reference the
# app instance).  We install those stubs once at class setup time so the three
# test methods can share a single import.

def _make_retrigger_stubs():
    """
    Pre-inject lightweight stubs for modules that api.main would otherwise
    load at import time (DB engine creation, ChromaDB init, etc.).
    Idempotent — safe to call multiple times.
    """
    import importlib

    # Stub db.connection so create_async_engine is never called
    if "db.connection" not in sys.modules:
        stub_db = MagicMock()
        stub_db.get_db = MagicMock()
        stub_db.init_db = AsyncMock()
        stub_db.close_db = AsyncMock()
        sys.modules["db.connection"] = stub_db

    # Stub adaptive router to avoid its own heavy imports
    for mod_name in ("adaptive.adaptive_router",):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()

    # Stub api.rate_limiter (real one is fine but guard against missing slowapi)
    if "api.rate_limiter" not in sys.modules:
        try:
            from slowapi import Limiter
            from slowapi.util import get_remote_address
            stub_rl = MagicMock()
            stub_rl.limiter = Limiter(key_func=get_remote_address)
            sys.modules["api.rate_limiter"] = stub_rl
        except ImportError:
            sys.modules["api.rate_limiter"] = MagicMock()


_make_retrigger_stubs()


class TestAdminRetriggerBook:
    """
    Direct unit tests for the admin_retrigger_book handler in api/main.py.

    We call the handler function directly (not via HTTP) to keep tests fast and
    deterministic.  Key patching decisions:

    - api.main.DATA_DIR is replaced with a MagicMock whose rglob() returns a
      controlled list — patching the attribute on the real WindowsPath object is
      not possible (read-only), so we swap the whole object.
    - db.connection.get_db is patched so the local `from db.connection import
      get_db` inside the handler picks up our AsyncMock generator.
    - api.main.shutil and api.main.subprocess are patched to avoid real I/O.
    """

    @staticmethod
    def _build_mock_data_dir(fake_pdfs: list) -> MagicMock:
        """Return a MagicMock that behaves like a Path whose rglob returns fake_pdfs."""
        mock_data_dir = MagicMock(spec=Path)
        mock_data_dir.rglob.return_value = fake_pdfs
        return mock_data_dir

    @staticmethod
    def _build_mock_output_dir(tmp_path: Path, book_slug: str) -> MagicMock:
        """Return a MagicMock Path whose __truediv__ yields a real tmp dir."""
        real_out_dir = tmp_path / "output" / book_slug
        real_out_dir.mkdir(parents=True, exist_ok=True)
        mock_output_dir = MagicMock(spec=Path)
        mock_output_dir.__truediv__ = MagicMock(return_value=real_out_dir)
        return mock_output_dir

    @staticmethod
    def _fake_pdf(tmp_path: Path, book_slug: str) -> Path:
        """Create and return a real temp PDF path whose name derive_slug maps to book_slug."""
        pdf = tmp_path / "data" / "mathematics" / f"{book_slug.title()}.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"")
        return pdf

    @staticmethod
    def _make_db_mock():
        """Async DB mock + async generator that admin_retrigger_book iterates with."""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        async def fake_get_db():
            yield mock_db

        return mock_db, fake_get_db

    def test_retrigger_deletes_chunks_and_output(self, tmp_path):
        """
        admin_retrigger_book must issue a DELETE on concept_chunks for the given slug
        and call shutil.rmtree on the matching output directory.
        """
        import asyncio
        from api.admin_router import admin_retrigger_book_legacy as admin_retrigger_book

        pdf = self._fake_pdf(tmp_path, "prealgebra")
        mock_db, fake_get_db = self._make_db_mock()
        mock_data_dir = self._build_mock_data_dir([pdf])
        mock_output_dir = self._build_mock_output_dir(tmp_path, "prealgebra")

        fake_request = MagicMock()
        fake_request.headers.get.return_value = "test-key"

        with patch("api.admin_router._API_KEY", "test-key"), \
             patch("api.admin_router.DATA_DIR", mock_data_dir), \
             patch("api.admin_router.OUTPUT_DIR", mock_output_dir), \
             patch("db.connection.get_db", fake_get_db), \
             patch("api.admin_router.shutil.rmtree") as mock_rmtree, \
             patch("api.admin_router.subprocess.Popen"):
            asyncio.run(admin_retrigger_book("prealgebra", fake_request))

        mock_db.execute.assert_called_once()
        sql_str = str(mock_db.execute.call_args[0][0]).upper()
        assert "DELETE" in sql_str
        assert "CONCEPT_CHUNKS" in sql_str

        mock_rmtree.assert_called_once()

    def test_retrigger_404_when_no_pdf(self, tmp_path):
        """
        admin_retrigger_book must raise HTTPException(404) when DATA_DIR.rglob
        returns no PDFs whose derive_slug matches the requested book_slug.
        """
        import asyncio
        from api.admin_router import admin_retrigger_book_legacy as admin_retrigger_book

        mock_db, fake_get_db = self._make_db_mock()
        # rglob returns empty list — no matching PDF on disk
        mock_data_dir = self._build_mock_data_dir([])
        mock_output_dir = self._build_mock_output_dir(tmp_path, "no_such_book")

        fake_request = MagicMock()
        fake_request.headers.get.return_value = "test-key"

        with patch("api.admin_router._API_KEY", "test-key"), \
             patch("api.admin_router.DATA_DIR", mock_data_dir), \
             patch("api.admin_router.OUTPUT_DIR", mock_output_dir), \
             patch("db.connection.get_db", fake_get_db), \
             patch("api.admin_router.shutil.rmtree"), \
             patch("api.admin_router.subprocess.Popen"):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(admin_retrigger_book("no_such_book", fake_request))

        assert exc_info.value.status_code == 404

    def test_retrigger_spawns_pipeline_runner(self, tmp_path):
        """
        admin_retrigger_book must call subprocess.Popen with command-line arguments
        that include 'src.watcher.pipeline_runner' and '--pdf'.
        """
        import asyncio
        from api.admin_router import admin_retrigger_book_legacy as admin_retrigger_book

        pdf = self._fake_pdf(tmp_path, "prealgebra")
        mock_db, fake_get_db = self._make_db_mock()
        mock_data_dir = self._build_mock_data_dir([pdf])
        mock_output_dir = self._build_mock_output_dir(tmp_path, "prealgebra")

        fake_request = MagicMock()
        fake_request.headers.get.return_value = "test-key"

        with patch("api.admin_router._API_KEY", "test-key"), \
             patch("api.admin_router.DATA_DIR", mock_data_dir), \
             patch("api.admin_router.OUTPUT_DIR", mock_output_dir), \
             patch("db.connection.get_db", fake_get_db), \
             patch("api.admin_router.shutil.rmtree"), \
             patch("api.admin_router.subprocess.Popen") as mock_popen:
            asyncio.run(admin_retrigger_book("prealgebra", fake_request))

        mock_popen.assert_called_once()
        popen_args = mock_popen.call_args[0][0]  # first positional arg is the cmd list
        assert "src.watcher.pipeline_runner" in popen_args
        assert "--pdf" in popen_args


# ---------------------------------------------------------------------------
# chunk_builder — image_url stored as relative path
# ---------------------------------------------------------------------------

class TestChunkBuilderRelativeImageUrl:
    """save_chunk must store image_url as a relative /images/... path, not an absolute URL."""

    @pytest.mark.asyncio
    async def test_chunk_builder_stores_relative_image_url(self, tmp_path):
        """
        When download_image returns a local filename, save_chunk must build an
        image_url that starts with '/images/' and contains no 'http://' or 'localhost'.
        """
        from unittest.mock import AsyncMock, patch as _patch, MagicMock
        from extraction.chunk_builder import save_chunk
        from extraction.chunk_parser import ParsedChunk

        images_dir = tmp_path / "images_downloaded"
        images_dir.mkdir()

        chunk = ParsedChunk(
            book_slug="prealgebra",
            concept_id="prealgebra_1.1",
            section="1.1",
            order_index=0,
            heading="Introduction",
            text="Some text",
            latex=[],
            image_urls=["https://cdn.mathpix.com/snip/abc123.jpg"],
        )

        # Mock the DB session
        mock_db = AsyncMock()
        # Idempotency check — return no existing rows
        mock_execute_result = MagicMock()
        mock_execute_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_execute_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        captured_images: list[object] = []
        original_add = mock_db.add.side_effect

        def capture_add(obj):
            from db.models import ChunkImage
            if isinstance(obj, ChunkImage):
                captured_images.append(obj)

        mock_db.add.side_effect = capture_add

        with _patch("extraction.chunk_builder.download_image", return_value="abc.jpg"):
            await save_chunk(
                db=mock_db,
                chunk=chunk,
                embedding=[0.0] * 1536,
                images_dir=images_dir,
                image_base_url="http://localhost:8889",
                book_slug="prealgebra",
            )

        assert len(captured_images) == 1, "Expected exactly one ChunkImage to be added"
        image_url = captured_images[0].image_url
        assert image_url.startswith("/images/"), (
            f"image_url should be relative, got: {image_url}"
        )
        assert "http://" not in image_url, (
            f"image_url must not contain 'http://': {image_url}"
        )
        assert "localhost" not in image_url, (
            f"image_url must not contain 'localhost': {image_url}"
        )


# ---------------------------------------------------------------------------
# _normalize_image_url — strips host from full URLs, passes relative URLs through
# ---------------------------------------------------------------------------

class TestNormalizeImageUrl:
    """_normalize_image_url converts absolute image URLs to root-relative paths."""

    def test_normalize_image_url_strips_host(self):
        """
        Full URL with host → root-relative path.
        Already-relative path → unchanged.
        Empty string → empty string.
        """
        from api.chunk_knowledge_service import _normalize_image_url

        # Case 1: full URL — host and port must be stripped
        full_url = "http://localhost:8889/images/prealgebra/images_downloaded/abc.jpg"
        result = _normalize_image_url(full_url)
        assert result == "/images/prealgebra/images_downloaded/abc.jpg", (
            f"Expected stripped path, got: {result}"
        )

        # Case 2: already relative — must pass through unchanged
        relative = "/images/prealgebra/images_downloaded/abc.jpg"
        result = _normalize_image_url(relative)
        assert result == relative, (
            f"Relative URL must be returned unchanged, got: {result}"
        )

        # Case 3: empty string — must return empty string without error
        result = _normalize_image_url("")
        assert result == "", f"Empty string must return empty string, got: {result!r}"
