"""Tests for RuntimeAnalyzer — runtime trace analysis, method trace processing."""

import sys
import os
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from playwright.sync_api import sync_playwright
from playwright._impl._errors import Error as PlaywrightError

from uibridge.engine.runtime_analyzer import (
    NetworkEntry,
    RuntimeReport,
    RuntimeAnalyzer,
)


def _require_browser():
    try:
        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
    except PlaywrightError as e:
        if "Executable doesn't exist" in str(e):
            pytest.skip("Playwright browser not installed — run: playwright install chromium")


# ══════════════════════════════════════════════════════════
# Test NetworkEntry dataclass
# ══════════════════════════════════════════════════════════

class TestNetworkEntry:
    """NetworkEntry dataclass construction and fields."""

    def test_defaults(self):
        entry = NetworkEntry(url="https://example.com/api")
        assert entry.url == "https://example.com/api"
        assert entry.method == "GET"
        assert entry.status == 0
        assert entry.duration_ms == 0
        assert entry.request_type == ""
        assert entry.ok is False

    def test_full_construction(self):
        entry = NetworkEntry(
            url="https://example.com/api/users",
            method="POST",
            status=201,
            duration_ms=45.2,
            request_type="fetch",
            ok=True,
        )
        assert entry.url == "https://example.com/api/users"
        assert entry.method == "POST"
        assert entry.status == 201
        assert entry.duration_ms == 45.2
        assert entry.request_type == "fetch"
        assert entry.ok is True

    def test_equality(self):
        a = NetworkEntry(url="/api", method="GET", status=200, ok=True, request_type="xhr")
        b = NetworkEntry(url="/api", method="GET", status=200, ok=True, request_type="xhr")
        assert a == b

    def test_inequality_different_url(self):
        a = NetworkEntry(url="/api/a")
        b = NetworkEntry(url="/api/b")
        assert a != b

    def test_xhr_request_type(self):
        entry = NetworkEntry(url="/api/data", request_type="xhr")
        assert entry.request_type == "xhr"

    def test_fetch_request_type(self):
        entry = NetworkEntry(url="/api/data", request_type="fetch")
        assert entry.request_type == "fetch"


# ══════════════════════════════════════════════════════════
# Test RuntimeReport dataclass
# ══════════════════════════════════════════════════════════

class TestRuntimeReport:
    """RuntimeReport dataclass, properties, and to_dict()."""

    def test_defaults(self):
        report = RuntimeReport()
        assert report.network_requests == []
        assert report.console_errors == []
        assert report.performance_metrics == {}
        assert report.start_time == 0
        assert report.end_time == 0

    def test_total_requests_empty(self):
        report = RuntimeReport()
        assert report.total_requests == 0

    def test_total_requests_with_entries(self):
        report = RuntimeReport(network_requests=[
            NetworkEntry(url="/api/a", request_type="xhr"),
            NetworkEntry(url="/api/b", request_type="xhr"),
            NetworkEntry(url="/page.html", request_type="document"),
        ])
        assert report.total_requests == 3

    def test_failed_requests_none(self):
        report = RuntimeReport(network_requests=[
            NetworkEntry(url="/api/a", ok=True),
            NetworkEntry(url="/api/b", ok=True),
        ])
        assert report.failed_requests == 0

    def test_failed_requests_some(self):
        report = RuntimeReport(network_requests=[
            NetworkEntry(url="/api/a", ok=True),
            NetworkEntry(url="/api/b", ok=False),
            NetworkEntry(url="/api/c", ok=False),
        ])
        assert report.failed_requests == 2

    def test_xhr_requests_count(self):
        report = RuntimeReport(network_requests=[
            NetworkEntry(url="/api/a", request_type="xhr"),
            NetworkEntry(url="/api/b", request_type="fetch"),
            NetworkEntry(url="/api/c", request_type="xhr"),
            NetworkEntry(url="/page.html", request_type="document"),
            NetworkEntry(url="/style.css", request_type="stylesheet"),
        ])
        assert report.xhr_requests == 3  # 2 xhr + 1 fetch

    def test_to_dict_structure(self):
        report = RuntimeReport(
            network_requests=[
                NetworkEntry(url="/api/users", request_type="xhr", ok=True),
                NetworkEntry(url="/api/items", request_type="fetch", ok=True),
                NetworkEntry(url="/page.html", request_type="document", ok=True),
            ],
            console_errors=["[error] Something went wrong"],
            performance_metrics={"first-paint": 42},
            start_time=100.0,
            end_time=105.0,
        )
        d = report.to_dict()

        assert isinstance(d, dict)
        assert d["total_requests"] == 3
        assert d["failed_requests"] == 0
        assert d["xhr_requests"] == 2
        assert "api_endpoints" in d
        assert len(d["api_endpoints"]) == 2  # unique API URLs
        assert "/api/users" in d["api_endpoints"]
        assert "/api/items" in d["api_endpoints"]
        assert d["console_errors"] == ["[error] Something went wrong"]
        assert d["performance_metrics"] == {"first-paint": 42}

    def test_to_dict_empty_report(self):
        report = RuntimeReport()
        d = report.to_dict()
        assert d["total_requests"] == 0
        assert d["failed_requests"] == 0
        assert d["xhr_requests"] == 0
        assert d["api_endpoints"] == []
        assert d["console_errors"] == []
        assert d["performance_metrics"] == {}

    def test_to_dict_api_endpoints_deduplicated(self):
        report = RuntimeReport(network_requests=[
            NetworkEntry(url="/api/users", request_type="xhr"),
            NetworkEntry(url="/api/users", request_type="fetch"),  # duplicate
            NetworkEntry(url="/api/users", request_type="xhr"),   # duplicate
        ])
        d = report.to_dict()
        assert len(d["api_endpoints"]) == 1

    def test_to_dict_no_api_requests(self):
        report = RuntimeReport(network_requests=[
            NetworkEntry(url="/page.html", request_type="document"),
            NetworkEntry(url="/style.css", request_type="stylesheet"),
            NetworkEntry(url="/app.js", request_type="script"),
        ])
        d = report.to_dict()
        assert d["xhr_requests"] == 0
        assert d["api_endpoints"] == []


# ══════════════════════════════════════════════════════════
# Test RuntimeAnalyzer — lifecycle (requires browser)
# ══════════════════════════════════════════════════════════

class TestRuntimeAnalyzerLifecycle:
    """RuntimeAnalyzer start/stop lifecycle and basic capture."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _require_browser()

    def test_start_creates_fresh_report(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()
            report = analyzer.stop()
            browser.close()

        assert isinstance(report, RuntimeReport)
        assert report.start_time > 0
        assert report.end_time > 0
        assert report.end_time >= report.start_time

    def test_double_start_is_idempotent(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()
            analyzer.start()  # second start should be harmless
            assert analyzer._active is True
            report = analyzer.stop()
            browser.close()

        assert isinstance(report, RuntimeReport)

    def test_stop_returns_report(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()
            report = analyzer.stop()
            browser.close()

        assert isinstance(report, RuntimeReport)

    def test_stop_collects_performance_metrics(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content("<html><body><h1>Perf Test</h1></body></html>")
            page.wait_for_load_state("networkidle")

            analyzer = RuntimeAnalyzer(page)
            analyzer.start()
            report = analyzer.stop()
            browser.close()

        # Performance metrics may be empty if paint didn't happen yet,
        # but the call should not raise
        assert isinstance(report.performance_metrics, dict)

    def test_not_active_before_start(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            assert analyzer._active is False
            browser.close()

    def test_active_after_start(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()
            assert analyzer._active is True
            analyzer.stop()
            browser.close()

    def test_not_active_after_stop(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()
            analyzer.stop()
            assert analyzer._active is False
            browser.close()


# ══════════════════════════════════════════════════════════
# Test RuntimeAnalyzer — network request capture
# ══════════════════════════════════════════════════════════

class TestNetworkCapture:
    """RuntimeAnalyzer captures network requests via page.goto()."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _require_browser()
        import shutil as _shutil
        self._tmpdir = tempfile.mkdtemp(prefix="uibridge_net_")
        self._html = Path(self._tmpdir) / "test.html"
        self._html.write_text(
            "<html><body><h1>Network Test</h1><p>Hello</p></body></html>"
        )
        yield
        _shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_captures_document_request(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            page.goto(self._html.as_uri())
            page.wait_for_load_state("networkidle")

            report = analyzer.stop()
            browser.close()

        assert report.total_requests > 0
        doc_requests = [r for r in report.network_requests if r.request_type == "document"]
        assert len(doc_requests) > 0, f"Expected at least one document request, got types: {[r.request_type for r in report.network_requests]}"

    def test_network_entry_has_method_and_url(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            page.goto(self._html.as_uri())
            page.wait_for_load_state("networkidle")

            report = analyzer.stop()
            browser.close()

        assert report.total_requests > 0, "Should have captured requests"
        for entry in report.network_requests:
            assert entry.url, "URL should not be empty"
            assert entry.method in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "")

    def test_response_updates_status(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            page.goto(self._html.as_uri())
            page.wait_for_load_state("networkidle")

            report = analyzer.stop()
            browser.close()

        doc_requests = [r for r in report.network_requests if r.request_type == "document"]
        assert len(doc_requests) > 0, "Should have document request"
        for r in doc_requests:
            assert r.status != 0, f"Document request should have status set: {r}"

    def test_successful_requests_marked_ok(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            page.goto(self._html.as_uri())
            page.wait_for_load_state("networkidle")

            report = analyzer.stop()
            browser.close()

        doc_requests = [r for r in report.network_requests if r.request_type == "document"]
        assert len(doc_requests) > 0, "Should have document request"
        for r in doc_requests:
            assert r.ok, f"Document request should be ok, got status={r.status}"

    def test_non_active_does_not_capture(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            # Do NOT call start() -- should not capture
            page.goto(self._html.as_uri())
            page.wait_for_load_state("networkidle")

            report = analyzer.stop()
            browser.close()

        assert report.total_requests == 0, "Should not capture when not active"


# ══════════════════════════════════════════════════════════
# Test RuntimeAnalyzer — console error capture
# ══════════════════════════════════════════════════════════

class TestConsoleCapture:
    """RuntimeAnalyzer captures console errors."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _require_browser()

    def test_captures_console_error(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            page.set_content("<html><body><h1>Error Test</h1></body></html>")
            page.evaluate("() => console.error('Test error message')")
            page.wait_for_timeout(100)

            report = analyzer.stop()
            browser.close()

        assert len(report.console_errors) > 0, "Expected at least one console error"
        error_texts = " ".join(report.console_errors)
        assert "Test error message" in error_texts, f"Console errors: {report.console_errors}"

    def test_captures_console_warning(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            page.set_content("<html><body><h1>Warning Test</h1></body></html>")
            page.evaluate("() => console.warn('Test warning message')")
            page.wait_for_timeout(100)

            report = analyzer.stop()
            browser.close()

        warning_msgs = [e for e in report.console_errors if e.startswith("[warning]")]
        assert len(warning_msgs) > 0, f"Expected warning, got: {report.console_errors}"

    def test_does_not_capture_console_log(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            page.set_content("<html><body><h1>Log Test</h1></body></html>")
            page.evaluate("() => console.log('This is a normal log')")
            page.wait_for_timeout(100)

            report = analyzer.stop()
            browser.close()

        log_msgs = [e for e in report.console_errors if "normal log" in e]
        assert len(log_msgs) == 0, f"Should not capture console.log, got: {log_msgs}"

    def test_filters_uibridge_internal_messages(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            page.set_content("<html><body><h1>Internal Test</h1></body></html>")
            page.evaluate("() => console.error('__uibridge_internal_debug_message')")
            page.wait_for_timeout(100)

            report = analyzer.stop()
            browser.close()

        internal_msgs = [e for e in report.console_errors if "__uibridge_" in e]
        assert len(internal_msgs) == 0, f"Should filter internal messages, got: {internal_msgs}"

    def test_console_error_truncated_to_200_chars(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            long_msg = "X" * 300
            page.set_content("<html><body><h1>Trunc Test</h1></body></html>")
            page.evaluate(f"() => console.error('{long_msg}')")
            page.wait_for_timeout(100)

            report = analyzer.stop()
            browser.close()

        for error in report.console_errors:
            # 200 chars + "[error] " prefix (8 chars) or "[warning] " (10 chars)
            assert len(error) <= 210, f"Message too long: {len(error)} chars"

    def test_non_active_does_not_capture_errors(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            # NOT starting

            page.set_content("<html><body><h1>Inactive Test</h1></body></html>")
            page.evaluate("() => console.error('Should not be captured')")
            page.wait_for_timeout(100)

            report = analyzer.stop()
            browser.close()

        assert report.console_errors == [], "Should not capture errors when not active"


# ══════════════════════════════════════════════════════════
# Test RuntimeAnalyzer — edge cases
# ══════════════════════════════════════════════════════════

class TestRuntimeAnalyzerEdgeCases:
    """Edge cases for RuntimeAnalyzer."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _require_browser()

    def test_stop_without_start_returns_empty_report(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            report = analyzer.stop()  # stop without start
            browser.close()

        assert isinstance(report, RuntimeReport)
        assert report.total_requests == 0
        assert report.console_errors == []

    def test_start_stop_start_stop_multiple_cycles(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)

            # Cycle 1
            analyzer.start()
            page.set_content("<html><body><h1>Cycle 1</h1></body></html>")
            report1 = analyzer.stop()

            # Cycle 2
            analyzer.start()
            page.set_content("<html><body><h1>Cycle 2</h1><p>More content</p></body></html>")
            page.evaluate("() => console.error('Cycle 2 error')")
            page.wait_for_timeout(100)
            report2 = analyzer.stop()

            browser.close()

        assert isinstance(report1, RuntimeReport)
        assert isinstance(report2, RuntimeReport)
        assert report1 is not report2  # different report objects

    def test_report_duration_positive(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            page.set_content("<html><body><h1>Duration</h1></body></html>")
            page.wait_for_load_state("networkidle")
            time.sleep(0.05)

            report = analyzer.stop()
            browser.close()

        duration = report.end_time - report.start_time
        assert duration > 0, f"Expected positive duration, got {duration}"

    def test_network_entry_ok_is_boolean(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            page.set_content("<html><body><h1>Bool Test</h1></body></html>")
            page.wait_for_load_state("networkidle")

            report = analyzer.stop()
            browser.close()

        for entry in report.network_requests:
            assert isinstance(entry.ok, bool)

    def test_network_entry_duration_is_float(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = RuntimeAnalyzer(page)
            analyzer.start()

            page.set_content("<html><body><h1>Duration Float</h1></body></html>")
            page.wait_for_load_state("networkidle")

            report = analyzer.stop()
            browser.close()

        for entry in report.network_requests:
            if entry.status != 0:  # might be 0 if response not yet received
                assert isinstance(entry.duration_ms, (int, float))
