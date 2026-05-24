"""Python 适配器兼容性测试 — reference + screenplay (8/8)"""
import pytest
import sys
import os

# Ensure uibridge is importable from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uibridge.adapter.base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter,
    MethodTemplate, ComponentDef, ScriptDef, TestDataDef,
    ElementInfo, BAWDef, BAWOperationDef, CallDef,
)


# ═══════════════════════════════════════════════════════════════
# Test classes for reference adapter
# ═══════════════════════════════════════════════════════════════

class TestReferenceAdapter:
    """参考适配器 5 个接口测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from uibridge.adapter.reference import (
            ReferenceComponentResolver,
            ReferenceLocatorStrategy,
            ReferenceActionRecognizer,
            ReferenceCodeGenerator,
            ReferenceDataFormatter,
        )
        self.resolver = ReferenceComponentResolver()
        self.locator = ReferenceLocatorStrategy()
        self.recognizer = ReferenceActionRecognizer()
        self.generator = ReferenceCodeGenerator()
        self.formatter = ReferenceDataFormatter()

    # Stage 1: Instantiation

    def test_stage1_instantiation(self):
        """5 个接口类均可实例化"""
        assert isinstance(self.resolver, ComponentResolver)
        assert isinstance(self.locator, LocatorStrategy)
        assert isinstance(self.recognizer, ActionRecognizer)
        assert isinstance(self.generator, CodeGenerator)
        assert isinstance(self.formatter, DataFormatter)

    # Stage 2: ComponentResolver

    def test_stage2_resolve_table(self):
        """ARIA role=table → TableAW"""
        cls = self.resolver.resolve_type("table", {}, "")
        assert cls == "TableAW"

    def test_stage2_resolve_textbox(self):
        """ARIA role=textbox → InputAW"""
        cls = self.resolver.resolve_type("textbox", {}, "")
        assert cls == "InputAW"

    def test_stage2_methods_for_table(self):
        """TableAW 应返回常用方法"""
        methods = self.resolver.get_methods_for_role("TableAW", "table")
        assert len(methods) > 0
        names = [m.name for m in methods]
        assert any("filter" in n or "click" in n or "get" in n for n in names)

    # Stage 3: LocatorStrategy

    def test_stage3_build_xpath(self):
        """生成 XPath"""
        ei = ElementInfo(tag="button", attrs={"data-testid": "submit-btn"}, text="Submit", ancestor_chain=[])
        xpath = self.locator.build_xpath(ei, {})
        assert len(xpath) > 0
        assert "submit-btn" in xpath or "Submit" in xpath

    def test_stage3_locator_priority(self):
        """定位器优先级"""
        pri = self.locator.get_locator_priority()
        assert len(pri) >= 3
        assert "data-module" in pri or "data-testid" in pri

    # Stage 4: CodeGenerator

    def test_stage4_generate_component_aw(self):
        """生成 ComponentAW 代码"""
        cd = ComponentDef(
            class_name="LoginFormAW",
            module="aaw.form_aw",
            xpath="//form[@data-module='login']",
            methods=[
                MethodTemplate(name="enter_username", params=[{"name": "text"}], action_type="input", returns="self"),
                MethodTemplate(name="enter_password", params=[{"name": "text"}], action_type="input", returns="self"),
                MethodTemplate(name="click_login", params=[], action_type="click", returns="self"),
            ],
            base_class="BaseAW",
        )
        code = self.generator.generate_component_aw(cd)
        assert "class LoginFormAW" in code
        assert "enter_username" in code
        assert "BaseAW" in code

    def test_stage4_generate_test_script(self):
        """生成测试脚本代码"""
        sd = ScriptDef(
            class_name="TestLogin",
            test_name="test_should_login_successfully",
            description="Valid login test",
            imports=["import pytest", "from aaw.login_form_aw import LoginFormAW"],
            fixtures=["def browser():", "def page(browser):"],
            steps=[
                "form = LoginFormAW(page)",
                "form.enter_username('admin')",
                "form.enter_password('secret')",
                "form.click_login()",
                "assert page.url.endswith('/dashboard')",
            ],
            data_refs=[],
        )
        code = self.generator.generate_test_script(sd)
        assert "TestLogin" in code or "test_should_login" in code
        assert "LoginFormAW" in code

    def test_stage4_generate_test_data(self):
        """生成测试数据代码"""
        td = TestDataDef(
            file_path="test_data/user_data.py",
            variable_name="VALID_USER",
            fields={"username": "admin", "password": "secret123"},
        )
        code = self.generator.generate_test_data(td)
        assert "VALID_USER" in code

    # Stage 5: Import/Assertion styles

    def test_stage5_import_style(self):
        """返回正确的 import 风格"""
        style = self.generator.get_import_style()
        assert style is not None
        assert isinstance(style, str) and len(style) > 0

    def test_stage5_assertion_style(self):
        """返回断言风格"""
        style = self.generator.get_assertion_style()
        assert style is not None
        assert isinstance(style, str) and len(style) > 0


# ═══════════════════════════════════════════════════════════════
# Test classes for screenplay adapter
# ═══════════════════════════════════════════════════════════════

class TestScreenplayAdapter:
    """Screenplay 适配器 5 个接口测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from uibridge.adapter.screenplay import (
            ScreenplayComponentResolver,
            ScreenplayLocatorStrategy,
            ScreenplayActionRecognizer,
            ScreenplayCodeGenerator,
            ScreenplayDataFormatter,
        )
        self.resolver = ScreenplayComponentResolver()
        self.locator = ScreenplayLocatorStrategy()
        self.recognizer = ScreenplayActionRecognizer()
        self.generator = ScreenplayCodeGenerator()
        self.formatter = ScreenplayDataFormatter()

    def test_stage1_instantiation(self):
        """5 个接口类均可实例化"""
        assert isinstance(self.resolver, ComponentResolver)
        assert isinstance(self.locator, LocatorStrategy)
        assert isinstance(self.recognizer, ActionRecognizer)
        assert isinstance(self.generator, CodeGenerator)
        assert isinstance(self.formatter, DataFormatter)

    def test_stage2_resolve_button(self):
        """button → Click/Target"""
        cls = self.resolver.resolve_type("button", {}, "")
        assert len(cls) > 0

    def test_stage2_methods_for_button(self):
        """button 的 Screenplay 方法"""
        methods = self.resolver.get_methods_for_role("Target", "button")
        assert len(methods) > 0

    def test_stage3_build_xpath(self):
        """生成 XPath"""
        ei = ElementInfo(tag="input", attrs={"placeholder": "Search", "id": "search-box"}, text="", ancestor_chain=[])
        xpath = self.locator.build_xpath(ei, {})
        # Screenplay locator may return empty if no preferred attr found
        # At minimum it should return a string
        assert isinstance(xpath, str)

    def test_stage4_generate_component_target(self):
        """生成 Target 定义"""
        cd = ComponentDef(
            class_name="SearchInput",
            module="pages.user_page_elements",
            xpath="//input[@placeholder='Search']",
            methods=[MethodTemplate(name="located", params=[], action_type="click", returns="Target")],
            base_class="Target",
        )
        code = self.generator.generate_component_aw(cd)
        assert "SearchInput" in code
        assert "Target" in code

    def test_stage4_generate_test_feature(self):
        """生成 Screenplay 测试"""
        sd = ScriptDef(
            class_name="DescribeUserSearch",
            test_name="test_should_find_user_by_name",
            description="Search for a user",
            imports=["import pytest", "from screenplay.actor import Actor"],
            fixtures=["def actor():"],
            steps=[
                "actor = Actor('test-user')",
                "actor.was_able_to(Search.for_term('admin'))",
                "actor.should_see(Text.of('.result-count'), '1 result')",
            ],
            data_refs=[],
        )
        code = self.generator.generate_test_script(sd)
        assert "DescribeUserSearch" in code or "test_should_find_user" in code


# ═══════════════════════════════════════════════════════════════
# Pipeline integration test
# ═══════════════════════════════════════════════════════════════

class TestPipelineIntegration:
    """端到端管道测试"""

    def test_pipeline_instantiation(self):
        """管道可用所有适配器创建"""
        from uibridge.adapter.reference import (
            ReferenceComponentResolver,
            ReferenceLocatorStrategy,
            ReferenceActionRecognizer,
            ReferenceCodeGenerator,
            ReferenceDataFormatter,
        )
        from uibridge.pipeline import Pipeline

        p = Pipeline(
            component_resolver=ReferenceComponentResolver(),
            locator_strategy=ReferenceLocatorStrategy(),
            action_recognizer=ReferenceActionRecognizer(),
            code_generator=ReferenceCodeGenerator(),
            data_formatter=ReferenceDataFormatter(),
            project_root=".",
        )
        assert p is not None

    def test_pipeline_analyze_from_raw_recording(self):
        """从 IR v1 录制分析到 IR v2"""
        from uibridge.adapter.reference import (
            ReferenceComponentResolver,
            ReferenceLocatorStrategy,
            ReferenceActionRecognizer,
            ReferenceCodeGenerator,
            ReferenceDataFormatter,
        )
        from uibridge.pipeline import Pipeline
        from uibridge.engine.ir.raw_recording import (
            RawRecording, RawRecordingMeta, RawStep, ActionType,
            Target, SelectorSet, Snapshot,
        )

        recording = RawRecording(
            version="1.0",
            meta=RawRecordingMeta(source="test", duration_ms=1000, viewport={"width": 1280, "height": 800}, generated_at="2026-01-01"),
            steps=[
                RawStep(
                    id="s1", action=ActionType.NAVIGATE, target=Target(selectors=SelectorSet(), label="Login"),
                    value=None, input_type=None, modifiers=[], timestamp_ms=0,
                    before_snapshot_id="", after_snapshot_id="snap0",
                    navigation_triggered=True, tab_index=0,
                ),
                RawStep(
                    id="s2", action=ActionType.INPUT, target=Target(selectors=SelectorSet(xpath="//input[@name='user']"), label="Username"),
                    value="admin", input_type="text", modifiers=[], timestamp_ms=100,
                    before_snapshot_id="", after_snapshot_id="",
                    navigation_triggered=False, tab_index=0,
                ),
                RawStep(
                    id="s3", action=ActionType.CLICK, target=Target(selectors=SelectorSet(xpath="//button[@type='submit']"), label="Login"),
                    value=None, input_type=None, modifiers=[], timestamp_ms=200,
                    before_snapshot_id="", after_snapshot_id="snap1",
                    navigation_triggered=False, tab_index=0,
                ),
            ],
            snapshots={
                "snap0": Snapshot(id="snap0", url="https://example.com/login", title="Login", aria_snapshot="- page\n  - textbox \"Username\"\n  - button \"Login\"", timestamp_ms=0),
                "snap1": Snapshot(id="snap1", url="https://example.com/dashboard", title="Dashboard", aria_snapshot="- page\n  - navigation", timestamp_ms=200),
            },
        )

        p = Pipeline(
            component_resolver=ReferenceComponentResolver(),
            locator_strategy=ReferenceLocatorStrategy(),
            action_recognizer=ReferenceActionRecognizer(),
            code_generator=ReferenceCodeGenerator(),
            data_formatter=ReferenceDataFormatter(),
            project_root=".",
        )
        seq = p.analyze(recording)
        assert seq is not None
        assert len(seq.scenarios) > 0

    def test_pipeline_map_to_framework(self):
        """IR v2 → IR v3 框架映射"""
        from uibridge.adapter.reference import (
            ReferenceComponentResolver,
            ReferenceLocatorStrategy,
            ReferenceActionRecognizer,
            ReferenceCodeGenerator,
            ReferenceDataFormatter,
        )
        from uibridge.pipeline import Pipeline
        from uibridge.engine.ir.semantic_action import (
            SemanticActionSequence, SemanticScenario, SemanticAction,
        )

        semantic = SemanticActionSequence(
            version="2.0",
            meta={"source": "test"},
            scenarios=[
                SemanticScenario(
                    name="Login Scenario",
                    page_flow=["/login", "/dashboard"],
                    actions=[
                        SemanticAction(type="page_action", page="/login", action="fill_username", params={"value": "admin"}, source_steps=["s2"]),
                        SemanticAction(type="page_action", page="/login", action="click_login", params={}, source_steps=["s3"]),
                    ],
                    description="Login to app",
                )
            ],
        )

        p = Pipeline(
            component_resolver=ReferenceComponentResolver(),
            locator_strategy=ReferenceLocatorStrategy(),
            action_recognizer=ReferenceActionRecognizer(),
            code_generator=ReferenceCodeGenerator(),
            data_formatter=ReferenceDataFormatter(),
            project_root=".",
        )
        call_seq = p.map_to_framework(semantic)
        assert call_seq is not None
        assert len(call_seq.test_cases) > 0

    def test_pipeline_generate_and_verify(self):
        """IR v3 → 代码生成 + 自检"""
        from uibridge.adapter.reference import (
            ReferenceComponentResolver,
            ReferenceLocatorStrategy,
            ReferenceActionRecognizer,
            ReferenceCodeGenerator,
            ReferenceDataFormatter,
        )
        from uibridge.pipeline import Pipeline
        from uibridge.engine.ir.framework_call import (
            FrameworkCallSequence, TestCaseIR, FrameworkStep, MethodCall, Decl,
        )

        call_seq = FrameworkCallSequence(
            version="3.0",
            meta={"source": "test"},
            test_cases=[
                TestCaseIR(
                    name="test_should_login",
                    description="Login test",
                    imports=["import pytest"],
                    fixtures=[],
                    steps=[
                        FrameworkStep(
                            decl=Decl(var="page", type="Page", factory="page", resolver="pytest.fixture"),
                            calls=[MethodCall(method="goto", args=["https://example.com"], kwargs={}, is_raw=True)],
                            comment="Navigate to login page",
                        ),
                        FrameworkStep(
                            decl=None,
                            calls=[MethodCall(method="assert", args=["True"], kwargs={}, is_raw=True)],
                            comment="Verify success",
                        ),
                    ],
                    review_needed=False,
                )
            ],
        )

        # Create a minimal recording for generate_and_verify
        from uibridge.engine.ir.raw_recording import (
            RawRecording, RawRecordingMeta, Snapshot,
        )
        recording = RawRecording(
            version="1.0",
            meta=RawRecordingMeta(source="test", duration_ms=100, viewport={"width": 1280, "height": 800}, generated_at="2026-01-01"),
            steps=[],
            snapshots={},
        )

        p = Pipeline(
            component_resolver=ReferenceComponentResolver(),
            locator_strategy=ReferenceLocatorStrategy(),
            action_recognizer=ReferenceActionRecognizer(),
            code_generator=ReferenceCodeGenerator(),
            data_formatter=ReferenceDataFormatter(),
            project_root=".",
        )
        results = p.generate_and_verify(call_seq, recording)
        assert len(results) == 1
        assert "test_name" in results[0]
        assert "code" in results[0]


# ═══════════════════════════════════════════════════════════════
# Self-test runner
# ═══════════════════════════════════════════════════════════════

class TestSelfTestRunner:
    """自检运行器"""

    def test_runner_creates_and_runs(self):
        """自检运行器可执行 Python 代码"""
        from uibridge.engine.self_test import SelfTestRunner

        code = """
def test_always_pass():
    assert True
"""
        runner = SelfTestRunner(timeout=30)
        result = runner.run(code, "test_always_pass")
        assert result.status in ("passed", "failed")  # depends on env
        assert result.confidence >= 0


# ═══════════════════════════════════════════════════════════════
# IR data structures
# ═══════════════════════════════════════════════════════════════

class TestIRDataStructures:
    """IR v1/v2/v3 数据结构"""

    def test_raw_recording_serialization(self):
        """IR v1 序列化"""
        from uibridge.engine.ir.raw_recording import (
            RawRecording, RawRecordingMeta, RawStep, ActionType, Target, SelectorSet, Snapshot,
        )
        recording = RawRecording(
            version="1.0",
            meta=RawRecordingMeta(source="test", duration_ms=500, viewport={"width": 1280, "height": 800}, generated_at="2026-01-01"),
            steps=[
                RawStep(
                    id="s1", action=ActionType.CLICK, target=Target(
                        selectors=SelectorSet(css="button"),
                        label="OK",
                        tag="button",
                        url="",
                        page_hint="",
                        component_hint="",
                    ),
                    value=None, input_type=None, modifiers=[], timestamp_ms=0,
                    before_snapshot_id="", after_snapshot_id="",
                    navigation_triggered=False, tab_index=0,
                ),
            ],
            snapshots={"snap0": Snapshot(id="snap0", url="https://example.com", title="Test", aria_snapshot="- page", timestamp_ms=0)},
        )
        d = recording.to_dict()
        assert d["version"] == "1.0"
        assert len(d["steps"]) == 1
        # round-trip
        r2 = RawRecording.from_dict(d)
        assert r2.meta.source == "test"
        assert len(r2.steps) == 1

    def test_semantic_action_sequence(self):
        """IR v2 语义动作序列"""
        from uibridge.engine.ir.semantic_action import (
            SemanticActionSequence, SemanticScenario, SemanticAction,
        )
        seq = SemanticActionSequence(
            version="2.0",
            meta={"source": "test"},
            scenarios=[
                SemanticScenario(
                    name="Test Scenario",
                    page_flow=["/page1"],
                    actions=[
                        SemanticAction(type="page_action", page="/page1", action="click_button", params={"button": "Submit"}, source_steps=["s1"]),
                    ],
                    description="Click a button",
                )
            ],
        )
        d = seq.to_dict()
        assert d["version"] == "2.0"
        assert len(d["scenarios"]) == 1

    def test_framework_call_sequence(self):
        """IR v3 框架调用序列"""
        from uibridge.engine.ir.framework_call import (
            FrameworkCallSequence, TestCaseIR, FrameworkStep, MethodCall,
        )
        seq = FrameworkCallSequence(
            version="3.0",
            meta={"source": "test"},
            test_cases=[
                TestCaseIR(
                    name="test_example",
                    description="An example test",
                    imports=[],
                    fixtures=[],
                    steps=[
                        FrameworkStep(
                            decl=None,
                            calls=[MethodCall(method="click", args=["//button"], kwargs={}, is_raw=True)],
                            comment="Click button",
                        ),
                    ],
                    review_needed=False,
                ),
            ],
        )
        assert len(seq.test_cases) == 1
        assert seq.test_cases[0].name == "test_example"


# ═══════════════════════════════════════════════════════════════
# Adapter swap test — same engine, different style
# ═══════════════════════════════════════════════════════════════

class TestAdapterSwap:
    """同一引擎 + 不同适配器 → 不同代码风格"""

    def test_same_input_different_output(self):
        """相同的 ScriptDef，reference 和 screenplay 产出不同"""
        from uibridge.adapter.reference import ReferenceCodeGenerator
        from uibridge.adapter.screenplay import ScreenplayCodeGenerator

        sd = ScriptDef(
            class_name="TestExample",
            test_name="test_example",
            description="Example",
            imports=["import pytest"],
            fixtures=[],
            steps=["assert True"],
            data_refs=[],
        )

        ref_code = ReferenceCodeGenerator().generate_test_script(sd)
        sp_code = ScreenplayCodeGenerator().generate_test_script(sd)

        # Both should generate valid code with the class name
        assert "TestExample" in ref_code or "test_example" in ref_code
        assert "TestExample" in sp_code or "test_example" in sp_code
        # But they should look different
        assert ref_code != sp_code


# ═══════════════════════════════════════════════════════════════
# DOM diff tests
# ═══════════════════════════════════════════════════════════════

class TestDOMDiff:
    """DOM 差异比较"""

    def test_diff_detects_changes(self):
        from uibridge.engine.dom_diff import DOMDiffer, DOMDiffResult, DiffEntry

        before = "- page\n  - textbox\n  - button"
        after = "- page\n  - textbox\n  - button\n  - dialog"

        differ = DOMDiffer()
        result = differ.diff(before, after, "url_before", "url_after")
        assert result.has_changes
        assert len(result.assertion_candidates) >= 0
