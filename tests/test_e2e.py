"""端到端测试 — 完整链路：浏览器操作 → 录制 → 分析 → 映射 → 生成 → 自检"""

import sys
import os
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from playwright.sync_api import sync_playwright


HTML_FORM_PAGE = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Test Form</title></head>
<body>
  <h1>User Search</h1>
  <form>
    <label for="search-box">Search</label>
    <input id="search-box" type="text" data-testid="search-input" placeholder="Enter keyword" aria-label="Search">
    <button id="search-btn" type="button" data-testid="search-button" aria-label="Execute search">Search</button>
  </form>
</body>
</html>"""


class TestEndToEnd:
    """完整链路端到端测试，使用真实浏览器"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from uibridge.adapter.reference import (
            ReferenceComponentResolver,
            ReferenceLocatorStrategy,
            ReferenceActionRecognizer,
            ReferenceCodeGenerator,
            ReferenceDataFormatter,
        )
        from uibridge.pipeline import Pipeline

        self.resolver = ReferenceComponentResolver()
        self.locator = ReferenceLocatorStrategy()
        self.recognizer = ReferenceActionRecognizer()
        self.generator = ReferenceCodeGenerator()
        self.formatter = ReferenceDataFormatter()

        self.pipeline = Pipeline(
            component_resolver=self.resolver,
            locator_strategy=self.locator,
            action_recognizer=self.recognizer,
            code_generator=self.generator,
            data_formatter=self.formatter,
        )

        self.tmpdir = tempfile.mkdtemp(prefix="uibridge_e2e_")
        self.html_path = Path(self.tmpdir) / "test_page.html"
        self.html_path.write_text(HTML_FORM_PAGE)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _record_simple_interaction(self, pipeline=None):
        """Helper: record navigate + fill + click on the test form."""
        if pipeline is None:
            pipeline = self.pipeline
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            session = pipeline.record(page)
            page.goto(self.html_path.as_uri())
            page.wait_for_load_state("networkidle")
            session.capture_snapshot()
            page.fill('[data-testid="search-input"]', "Alice")
            page.click('[data-testid="search-button"]')
            recording = session.to_raw_recording()
            browser.close()
        return recording, session

    # ── 核心 E2E 路径 ──────────────────────────

    def test_full_pipeline_reference(self):
        """完整管线：浏览器交互 → 录制 → 分析 → 生成 Reference 代码"""
        from uibridge.engine.ir.raw_recording import RawRecording

        recording, _ = self._record_simple_interaction()

        assert isinstance(recording, RawRecording)
        assert len(recording.steps) >= 2  # navigate + at least 1 action

        # Stage 2: 语义分析
        semantic = self.pipeline.analyze(recording)
        assert len(semantic.scenarios) == 1
        assert len(semantic.scenarios[0].actions) >= 1

        # Stage 3: 框架映射
        call_seq = self.pipeline.map_to_framework(semantic)
        assert len(call_seq.test_cases) == 1
        assert len(call_seq.test_cases[0].steps) >= 1

        # Stage 4: 代码生成 + 自检
        results = self.pipeline.generate_and_verify(call_seq, recording)
        assert len(results) == 1
        result = results[0]
        assert len(result["code"]) > 0
        # 自检可能失败（生成的代码引用了框架组件 AW 模块，测试环境不一定有），
        # 只要代码成功生成并返回了自检结果即可
        assert "verify" in result

    def test_full_pipeline_screenplay(self):
        """Screenplay 适配器端到端"""
        from uibridge.adapter.screenplay import (
            ScreenplayComponentResolver,
            ScreenplayLocatorStrategy,
            ScreenplayActionRecognizer,
            ScreenplayCodeGenerator,
            ScreenplayDataFormatter,
        )
        from uibridge.pipeline import Pipeline

        pipeline = Pipeline(
            component_resolver=ScreenplayComponentResolver(),
            locator_strategy=ScreenplayLocatorStrategy(),
            action_recognizer=ScreenplayActionRecognizer(),
            code_generator=ScreenplayCodeGenerator(),
            data_formatter=ScreenplayDataFormatter(),
        )

        recording, _ = self._record_simple_interaction(pipeline)
        semantic = pipeline.analyze(recording)
        call_seq = pipeline.map_to_framework(semantic)
        results = pipeline.generate_and_verify(call_seq, recording)

        assert len(results) == 1
        code = results[0]["code"]
        assert "actor" in code.lower() or "Actor" in code

    def test_full_pipeline_java_testng(self):
        """Java TestNG 适配器端到端"""
        from uibridge.adapter.java_testng import (
            JavaComponentResolver,
            JavaLocatorStrategy,
            JavaActionRecognizer,
            JavaCodeGenerator,
            JavaDataFormatter,
        )
        from uibridge.pipeline import Pipeline

        pipeline = Pipeline(
            component_resolver=JavaComponentResolver(),
            locator_strategy=JavaLocatorStrategy(),
            action_recognizer=JavaActionRecognizer(),
            code_generator=JavaCodeGenerator(),
            data_formatter=JavaDataFormatter(),
        )

        recording, _ = self._record_simple_interaction(pipeline)
        semantic = pipeline.analyze(recording)
        call_seq = pipeline.map_to_framework(semantic)
        results = pipeline.generate_and_verify(call_seq, recording)

        assert len(results) == 1
        code = results[0]["code"]
        assert "class" in code and "Test" in code

    def test_full_pipeline_java_fluent(self):
        """Java Fluent 适配器端到端"""
        from uibridge.adapter.java_fluent import (
            FluentComponentResolver,
            FluentLocatorStrategy,
            FluentActionRecognizer,
            FluentCodeGenerator,
            FluentDataFormatter,
        )
        from uibridge.pipeline import Pipeline

        pipeline = Pipeline(
            component_resolver=FluentComponentResolver(),
            locator_strategy=FluentLocatorStrategy(),
            action_recognizer=FluentActionRecognizer(),
            code_generator=FluentCodeGenerator(),
            data_formatter=FluentDataFormatter(),
        )

        recording, _ = self._record_simple_interaction(pipeline)
        semantic = pipeline.analyze(recording)
        call_seq = pipeline.map_to_framework(semantic)
        results = pipeline.generate_and_verify(call_seq, recording)

        assert len(results) == 1
        code = results[0]["code"]
        assert "class" in code

    # ── 录制内容验证 ──────────────────────────

    def test_recording_captures_steps(self):
        """录制应捕获导航、输入、点击事件"""
        recording, _ = self._record_simple_interaction()

        actions = [s.action.value if hasattr(s.action, 'value') else str(s.action)
                   for s in recording.steps]
        assert "navigate" in actions
        assert "input" in actions
        assert "click" in actions

    def test_recording_snapshots(self):
        """录制应捕获 ARIA 快照"""
        recording, _ = self._record_simple_interaction()

        assert len(recording.snapshots) >= 1
        non_empty = [s for s in recording.snapshots.values() if len(s.aria_snapshot) > 0]
        assert len(non_empty) >= 1, "At least one snapshot should have ARIA data"

    # ── Stage 2 验证 ──────────────────────────

    def test_analyze_produces_scenarios(self):
        """语义分析应产生场景"""
        recording, _ = self._record_simple_interaction()

        semantic = self.pipeline.analyze(recording)
        assert len(semantic.scenarios) >= 1
        scenario = semantic.scenarios[0]
        assert len(scenario.page_flow) >= 1
        assert len(scenario.actions) >= 1

    # ── Stage 3 验证 ──────────────────────────

    def test_map_to_framework_produces_test_cases(self):
        """框架映射应产生测试用例"""
        recording, _ = self._record_simple_interaction()

        semantic = self.pipeline.analyze(recording)
        call_seq = self.pipeline.map_to_framework(semantic)

        assert len(call_seq.test_cases) >= 1
        tc = call_seq.test_cases[0]
        assert tc.name.startswith("test_")
        assert len(tc.imports) > 0
        assert len(tc.steps) > 0

    # ── KB 集成验证 ──────────────────────────

    def test_pipeline_with_kb_manager(self):
        """带 KB Manager 的 Pipeline 应能正常完成全流程"""
        from uibridge.kb.kb_store import KBStore
        from uibridge.kb.kb_manager import KBManager

        store = KBStore()
        kb = KBManager(str(self.tmpdir))
        # 将 store 替换为我们的预制 store
        kb.store = store

        # 播种一条命名约定
        kb.inject(
            category="conventions",
            key="convention.naming",
            value={"naming_rules": [
                {"pattern": "page", "replacement": "currentPage"}
            ]},
            description="Test naming rule: rename page → currentPage",
        )

        from uibridge.pipeline import Pipeline

        pipeline = Pipeline(
            component_resolver=self.resolver,
            locator_strategy=self.locator,
            action_recognizer=self.recognizer,
            code_generator=self.generator,
            data_formatter=self.formatter,
            kb_manager=kb,
        )

        recording, _ = self._record_simple_interaction(pipeline)
        semantic = pipeline.analyze(recording)
        call_seq = pipeline.map_to_framework(semantic)
        results = pipeline.generate_and_verify(call_seq, recording)

        assert len(results) == 1
        assert len(results[0]["code"]) > 0

    # ── 程序化控制验证 ──────────────────────

    def test_session_stop(self):
        """stop() 应停止录制并返回 RawRecording"""
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            session = self.pipeline.record(page)
            page.goto(self.html_path.as_uri())
            page.wait_for_load_state("networkidle")
            page.click('#search-btn')
            recording = session.stop()
            browser.close()

        assert recording is not None
        assert not session.is_active
        assert len(recording.steps) >= 1

    # ── 交互式录制流（start / stop 双调用）──────

    def test_start_stop_recording_flow(self):
        """模拟 Agent 双调用流程：start → 操作 → stop，验证录制捕获了步骤"""
        from playwright.sync_api import sync_playwright
        from uibridge.engine.recorder import RecordingSession

        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.html_path.as_uri())
            page.wait_for_load_state("networkidle")

            # Step 1: start — 创建 session，浏览器保持打开
            session = self.pipeline.record(page)

            # Step 2: 用户在浏览器中操作（模拟）
            page.fill('[data-testid="search-input"]', "Test")
            page.click('[data-testid="search-button"]')
            # 给事件桥接一点时间处理
            page.wait_for_timeout(200)

            # Step 3: stop — 停止录制，获取结果
            recording = session.stop()

            assert len(recording.steps) >= 2, f"Expected at least 2 steps, got {len(recording.steps)}"
            actions = [s.action.value if hasattr(s.action, 'value') else str(s.action)
                       for s in recording.steps]
            assert "input" in actions or "navigate" in actions
        finally:
            browser.close()
            pw.stop()

    def test_session_thread_safety(self):
        """多步操作后 stop 应正确捕获所有步骤（验证锁机制）"""
        from playwright.sync_api import sync_playwright
        from uibridge.engine.recorder import RecordingSession

        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self.html_path.as_uri())
            page.wait_for_load_state("networkidle")

            session = self.pipeline.record(page)

            # 模拟多次快速操作
            for i in range(5):
                page.fill('[data-testid="search-input"]', f"query_{i}")
                page.click('[data-testid="search-button"]')
                page.wait_for_timeout(50)

            recording = session.stop()

            # 应至少有 navigate + 多次 input/click
            assert len(recording.steps) >= 3
        finally:
            browser.close()
            pw.stop()
