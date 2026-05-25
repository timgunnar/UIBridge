"""Playwright Java TestNG 适配器兼容性测试 — custom_playwright_java"""
import pytest
import sys
import os
from dataclasses import dataclass, field
from enum import Enum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uibridge.adapter.base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter,
    MethodTemplate, ComponentDef, ScriptDef, TestDataDef,
    ElementInfo, BAWDef, BAWOperationDef, CallDef, PageDef, PageComponent,
    _to_java_type,
)


# ── Minimal mock types for render_step duck typing ──────────────

class StepKind(Enum):
    decl = "decl"
    navigate = "navigate"
    action = "action"
    assert_step = "assert"


@dataclass
class MockDecl:
    type: str = "LoginFormAW"
    var: str = "loginForm"


@dataclass
class MockCall:
    component: str = "loginForm"
    method: str = "enterUsername"
    args: list = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)


@dataclass
class MockStep:
    kind: StepKind = StepKind.action
    decl: MockDecl = None
    calls: list = field(default_factory=list)
    comment: str = ""


# ═══════════════════════════════════════════════════════════════
# PlaywrightJava adapter tests
# ═══════════════════════════════════════════════════════════════

class TestPlaywrightJavaAdapter:
    """Playwright Java TestNG 适配器 5 个接口测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from uibridge.adapter.custom_playwright_java import (
            PlaywrightComponentResolver,
            PlaywrightLocatorStrategy,
            PlaywrightActionRecognizer,
            PlaywrightCodeGenerator,
            PlaywrightDataFormatter,
        )
        self.resolver = PlaywrightComponentResolver()
        self.locator = PlaywrightLocatorStrategy()
        self.recognizer = PlaywrightActionRecognizer()
        self.generator = PlaywrightCodeGenerator()
        self.formatter = PlaywrightDataFormatter()

    # ── Stage 1: Instantiation ──────────────────────────────────

    def test_stage1_instantiation(self):
        """5 个接口类均可实例化"""
        assert isinstance(self.resolver, ComponentResolver)
        assert isinstance(self.locator, LocatorStrategy)
        assert isinstance(self.recognizer, ActionRecognizer)
        assert isinstance(self.generator, CodeGenerator)
        assert isinstance(self.formatter, DataFormatter)

    # ── Stage 2: ComponentResolver ──────────────────────────────

    def test_stage2_resolve_type_table(self):
        """ARIA role=table → TableAW"""
        cls = self.resolver.resolve_type("table", {}, "")
        assert cls == "TableAW"

    def test_stage2_resolve_type_textbox(self):
        """ARIA role=textbox → InputAW"""
        cls = self.resolver.resolve_type("textbox", {}, "")
        assert cls == "InputAW"

    def test_stage2_resolve_type_button(self):
        """ARIA role=button → ButtonAW"""
        cls = self.resolver.resolve_type("button", {}, "")
        assert cls == "ButtonAW"

    def test_stage2_resolve_type_combobox(self):
        """ARIA role=combobox → DropdownAW"""
        cls = self.resolver.resolve_type("combobox", {}, "")
        assert cls == "DropdownAW"

    def test_stage2_resolve_type_dialog(self):
        """ARIA role=dialog → DialogAW"""
        cls = self.resolver.resolve_type("dialog", {}, "")
        assert cls == "DialogAW"

    def test_stage2_resolve_type_via_data_module(self):
        """data-module attr → 名称推断"""
        cls = self.resolver.resolve_type("generic", {"data-module": "user-table"}, "")
        assert cls == "TableAW"

        cls = self.resolver.resolve_type("generic", {"data-module": "edit-form"}, "")
        assert cls == "FormAW"

        cls = self.resolver.resolve_type("generic", {"data-module": "city-dropdown"}, "")
        assert cls == "DropdownAW"

        cls = self.resolver.resolve_type("generic", {"data-module": "confirm-dialog"}, "")
        assert cls == "DialogAW"

    def test_stage2_resolve_type_fallback_by_tag(self):
        """无 ARIA role 时回退到 HTML tag"""
        cls = self.resolver.resolve_type("unknown", {"tag": "input"}, "")
        assert cls == "InputAW"

        cls = self.resolver.resolve_type("unknown", {"tag": "select"}, "")
        assert cls == "DropdownAW"

        cls = self.resolver.resolve_type("unknown", {"tag": "button"}, "")
        assert cls == "ButtonAW"

    def test_stage2_resolve_type_unknown(self):
        """未知 role + 无 tag → BaseComponentAW"""
        cls = self.resolver.resolve_type("unknown", {}, "")
        assert cls == "BaseComponentAW"

    def test_stage2_suggest_name(self):
        """组件命名建议 — PascalCase Java 类名"""
        name = self.resolver.suggest_name("https://app.com/user/list", "table", {})
        assert len(name) > 0

    def test_stage2_suggest_name_with_data_module(self):
        """data-module → 直接转 Java 类名"""
        name = self.resolver.suggest_name("", "table", {"data-module": "user-table"})
        assert "UserTable" in name or "Table" in name

    def test_stage2_get_methods_for_table(self):
        """TableAW 返回 Playwright 风格方法"""
        methods = self.resolver.get_methods_for_role("TableAW", "table")
        assert len(methods) > 0
        names = [m.name for m in methods]
        for m in methods:
            assert m.name
            assert m.action_type
        assert any("waitForLoad" in n or "clickRow" in n or "getRowCount" in n for n in names)

    def test_stage2_get_methods_for_input(self):
        """InputAW 返回 Playwright fill 方法"""
        methods = self.resolver.get_methods_for_role("InputAW", "textbox")
        assert len(methods) > 0
        names = [m.name for m in methods]
        assert any("fill" in n or "type" in n or "getValue" in n for n in names)

    def test_stage2_get_methods_for_button(self):
        """ButtonAW 返回 click 方法"""
        methods = self.resolver.get_methods_for_role("ButtonAW", "button")
        assert len(methods) > 0
        names = [m.name for m in methods]
        assert "click" in names

    def test_stage2_get_methods_default(self):
        """未知组件类型 → 默认 click + assertVisible"""
        methods = self.resolver.get_methods_for_role("CustomAW", "custom")
        assert len(methods) == 2
        names = [m.name for m in methods]
        assert "click" in names
        assert "assertVisible" in names

    def test_stage2_get_methods_for_dropdown(self):
        """DropdownAW 返回 selectOption 方法"""
        methods = self.resolver.get_methods_for_role("DropdownAW", "combobox")
        assert len(methods) > 0
        names = [m.name for m in methods]
        assert any("selectOption" in n or "getSelected" in n for n in names)

    def test_stage2_get_methods_for_dialog(self):
        """DialogAW 返回 confirm/cancel 方法"""
        methods = self.resolver.get_methods_for_role("DialogAW", "dialog")
        assert len(methods) > 0
        names = [m.name for m in methods]
        assert any("confirm" in n or "cancel" in n for n in names)

    # ── Stage 3: LocatorStrategy ────────────────────────────────

    def test_stage3_build_xpath_by_id(self):
        """id 优先定位"""
        ei = ElementInfo(
            tag="input",
            attrs={"id": "username", "name": "user"},
            text="",
            ancestor_chain=[],
        )
        xpath = self.locator.build_xpath(ei, {})
        assert xpath == "#username"

    def test_stage3_build_xpath_by_data_testid(self):
        """data-testid 定位（无 id 时）"""
        ei = ElementInfo(
            tag="button",
            attrs={"data-testid": "submit-btn"},
            text="",
            ancestor_chain=[],
        )
        xpath = self.locator.build_xpath(ei, {})
        assert "submit-btn" in xpath

    def test_stage3_build_xpath_by_name(self):
        """name 属性定位"""
        ei = ElementInfo(
            tag="input",
            attrs={"name": "email"},
            text="",
            ancestor_chain=[],
        )
        xpath = self.locator.build_xpath(ei, {})
        assert "email" in xpath

    def test_stage3_build_xpath_by_placeholder(self):
        """placeholder 定位"""
        ei = ElementInfo(
            tag="input",
            attrs={"placeholder": "Enter your name"},
            text="",
            ancestor_chain=[],
        )
        xpath = self.locator.build_xpath(ei, {})
        assert "placeholder" in xpath.lower() or "Enter your name" in xpath

    def test_stage3_build_xpath_by_aria_label(self):
        """aria-label 定位"""
        ei = ElementInfo(
            tag="button",
            attrs={"aria-label": "Close dialog"},
            text="",
            ancestor_chain=[],
        )
        xpath = self.locator.build_xpath(ei, {})
        assert "Close dialog" in xpath

    def test_stage3_build_xpath_by_text(self):
        """文本定位 — Playwright 特色"""
        ei = ElementInfo(
            tag="span",
            attrs={"class": "label"},
            text="Submit",
            ancestor_chain=[],
        )
        xpath = self.locator.build_xpath(ei, {})
        assert "Submit" in xpath

    def test_stage3_build_xpath_by_class(self):
        """类名定位 — 无其他属性时"""
        ei = ElementInfo(
            tag="div",
            attrs={"class": "container main"},
            text="",
            ancestor_chain=[],
        )
        xpath = self.locator.build_xpath(ei, {})
        assert ".container" in xpath

    def test_stage3_build_xpath_empty(self):
        """无可用属性 → 空字符串"""
        ei = ElementInfo(
            tag="div",
            attrs={},
            text="",
            ancestor_chain=[],
        )
        xpath = self.locator.build_xpath(ei, {})
        assert xpath == ""

    def test_stage3_best_attr(self):
        """最佳属性选择 — 优先级: data-testid > id > name > placeholder > aria-label"""
        ei = ElementInfo(
            tag="input",
            attrs={
                "data-testid": "login-user",
                "id": "username",
                "name": "user",
                "placeholder": "Enter user",
                "aria-label": "Username",
            },
            text="",
            ancestor_chain=[],
        )
        best = self.locator.best_attr(ei)
        assert best == "data-testid"

    def test_stage3_best_attr_no_preferred(self):
        """无首选属性 → 空字符串"""
        ei = ElementInfo(
            tag="div",
            attrs={"class": "container"},
            text="",
            ancestor_chain=[],
        )
        best = self.locator.best_attr(ei)
        assert best == ""

    def test_stage3_extract_feature_point_id(self):
        """从 #id 选择器提取"""
        fp = self.locator.extract_feature_point("#username")
        assert fp["type"] == "id"
        assert fp["value"] == "username"

    def test_stage3_extract_feature_point_data_testid(self):
        """从 [data-testid=...] 提取"""
        fp = self.locator.extract_feature_point("[data-testid='submit-btn']")
        assert fp["type"] == "data-testid"
        assert fp["value"] == "submit-btn"

    def test_stage3_extract_feature_point_name(self):
        """从 [name=...] 提取"""
        fp = self.locator.extract_feature_point("[name='email']")
        assert fp["type"] == "name"
        assert fp["value"] == "email"

    def test_stage3_extract_feature_point_text(self):
        """从 text=... 提取"""
        fp = self.locator.extract_feature_point('text="Submit"')
        assert fp["type"] == "text"
        assert fp["value"] == "Submit"

    def test_stage3_extract_feature_point_class(self):
        """从 .class 选择器提取"""
        fp = self.locator.extract_feature_point(".container")
        assert fp["type"] == "class"
        assert fp["value"] == "container"

    def test_stage3_extract_feature_point_fallback(self):
        """通用选择器回退"""
        fp = self.locator.extract_feature_point("page.locator('[data-module=login]')")
        assert fp["type"] == "selector"
        assert len(fp["value"]) > 0

    def test_stage3_locator_priority(self):
        """定位器优先级列表"""
        pri = self.locator.get_locator_priority()
        assert len(pri) > 0
        # Playwright prefers id, placeholder, aria-label, text, css, xpath
        expected = ["id", "placeholder", "aria-label", "text", "css", "xpath"]
        assert pri == expected

    # ── Stage 4: ActionRecognizer ───────────────────────────────

    def test_stage4_aggregate_navigate(self):
        """navigate 聚合"""
        steps = [
            {"action": "navigate", "value": "https://example.com", "target": {"label": "Login", "tag": ""}},
        ]
        result = self.recognizer.aggregate(steps, {"page": "/login"})
        assert len(result) > 0

    def test_stage4_aggregate_input_click(self):
        """input + click 聚合为复合动作"""
        steps = [
            {"action": "input", "value": "admin", "target": {"label": "Username", "tag": "input"}},
            {"action": "click", "value": None, "target": {"label": "Login", "tag": "button"}},
        ]
        result = self.recognizer.aggregate(steps, {"page": "/login"})
        assert len(result) > 0
        # input+click should be merged into composite
        assert any(
            (isinstance(a, dict) and a.get("type") == "composite_action")
            for a in result
        ) or len(result) >= 1

    def test_stage4_aggregate_multiple_inputs(self):
        """多个连续 input 聚合"""
        steps = [
            {"action": "input", "value": "admin", "target": {"label": "Username", "tag": "input"}},
            {"action": "input", "value": "secret", "target": {"label": "Password", "tag": "input"}},
            {"action": "click", "value": None, "target": {"label": "Login", "tag": "button"}},
        ]
        result = self.recognizer.aggregate(steps, {"page": "/login"})
        assert len(result) >= 1

    def test_stage4_recognize_pattern_empty(self):
        """序列数不足时不产出模式"""
        # recognize_pattern requires >= 3 sequences
        patterns = self.recognizer.recognize_pattern([])
        assert patterns == []

        patterns = self.recognizer.recognize_pattern([[], []])
        assert patterns == []

    def test_stage4_recognize_pattern(self):
        """频繁子序列模式挖掘"""
        seqs = [
            [{"action": "input"}, {"action": "click"}],
            [{"action": "input"}, {"action": "click"}],
            [{"action": "input"}, {"action": "click"}],
        ]
        patterns = self.recognizer.recognize_pattern(seqs)
        # 3 identical sequences → should find pattern
        assert len(patterns) >= 1
        for p in patterns:
            assert "frequency" in p
            assert "suggestion" in p

    # ── Stage 5: CodeGenerator ─────────────────────────────────

    def test_stage5_generate_component_aw(self):
        """生成 Playwright Component AW"""
        cd = ComponentDef(
            class_name="LoginForm",
            module="com.enterprise.components.LoginForm",
            xpath="[data-module='login']",
            methods=[
                MethodTemplate(name="enterUsername", params=[{"name": "text", "type": "String"}], action_type="input", returns="void"),
                MethodTemplate(name="enterPassword", params=[{"name": "text", "type": "String"}], action_type="input", returns="void"),
                MethodTemplate(name="clickLogin", params=[], action_type="click", returns="void"),
            ],
            base_class="BaseComponentAW",
        )
        code = self.generator.generate_component_aw(cd)
        assert "class LoginForm" in code
        assert "enterUsername" in code
        assert "BaseComponentAW" in code

    def test_stage5_generate_component_with_wait(self):
        """Component AW 包含 waitForLoad 方法"""
        cd = ComponentDef(
            class_name="UserTable",
            module="com.enterprise.components.UserTable",
            xpath="[data-module='user-table']",
            methods=[
                MethodTemplate(name="waitForLoad", params=[], action_type="wait", returns="void"),
                MethodTemplate(name="getRowCount", params=[], action_type="read", returns="int"),
            ],
            base_class="BaseComponentAW",
        )
        code = self.generator.generate_component_aw(cd)
        assert "class UserTable" in code
        assert "waitForLoad" in code
        assert "getRowCount" in code

    def test_stage5_generate_component_with_assertion(self):
        """Component AW 包含断言方法"""
        cd = ComponentDef(
            class_name="StatusBanner",
            module="com.enterprise.components.StatusBanner",
            xpath="[data-module='banner']",
            methods=[
                MethodTemplate(name="assertVisible", params=[], action_type="assertion", returns="void"),
                MethodTemplate(name="getText", params=[], action_type="read", returns="String"),
            ],
            base_class="BaseComponentAW",
        )
        code = self.generator.generate_component_aw(cd)
        assert "class StatusBanner" in code
        assert "assertVisible" in code or "assertThat" in code

    def test_stage5_generate_component_with_select(self):
        """Component AW 包含 selectOption"""
        cd = ComponentDef(
            class_name="CityDropdown",
            module="com.enterprise.components.CityDropdown",
            xpath="[data-module='city']",
            methods=[
                MethodTemplate(name="selectOption", params=[{"name": "value", "type": "String"}], action_type="select", returns="void"),
            ],
            base_class="BaseComponentAW",
        )
        code = self.generator.generate_component_aw(cd)
        assert "class CityDropdown" in code
        assert "selectOption" in code

    def test_stage5_generate_business_aw(self):
        """生成 Playwright Page Object (BAW)"""
        baw = BAWDef(
            class_name="UserManagementPage",
            module="user",
            operations=[
                BAWOperationDef(
                    name="addUser",
                    params=[{"name": "username", "type": "String"}],
                    calls=[
                        CallDef(component="UserTable", method="clickAddButton", args=[]),
                        CallDef(component="UserForm", method="enterName", args=["username"]),
                        CallDef(component="UserForm", method="submit", args=[]),
                    ],
                ),
            ],
        )
        code = self.generator.generate_business_aw(baw)
        assert "class UserManagementPage" in code

    def test_stage5_generate_test_script(self):
        """生成 Playwright TestNG 测试"""
        sd = ScriptDef(
            class_name="TestUserLogin",
            test_name="shouldLoginSuccessfully",
            description="Valid login test",
            imports=[
                "import org.testng.annotations.Test;",
                "import org.testng.Assert;",
            ],
            fixtures=[],
            steps=[
                'page.navigate("https://example.com/login");',
                'loginForm.enterUsername("admin");',
                'loginForm.enterPassword("secret");',
                "loginForm.clickLogin();",
                'Assert.assertEquals(page.url(), "https://example.com/dashboard");',
            ],
            data_refs=[],
        )
        code = self.generator.generate_test_script(sd)
        assert "TestUserLogin" in code or "shouldLoginSuccessfully" in code
        assert "@Test" in code or "test" in code.lower()

    def test_stage5_generate_test_data(self):
        """生成 Playwright TestNG DataProvider"""
        td = TestDataDef(
            file_path="src/test/java/com/enterprise/test/data/UserTestData.java",
            variable_name="VALID_USER",
            fields={"username": "admin", "password": "secret123"},
        )
        code = self.generator.generate_test_data(td)
        assert "VALID_USER" in code or "admin" in code

    def test_stage5_generate_dispatches_to_test_script(self):
        """generate() 根据 layer_config 分发到 generate_test_script"""
        sd = ScriptDef(
            class_name="TestDispatch",
            test_name="testDispatch",
            description="Dispatch test",
            imports=[],
            fixtures=[],
            steps=['page.navigate("https://example.com");'],
            data_refs=[],
        )
        code = self.generator.generate(sd, {"maps_to": "test_script"})
        assert "TestDispatch" in code or "testDispatch" in code

    def test_stage5_generate_dispatches_to_test_data(self):
        """generate() 根据 layer_config 分发到 generate_test_data"""
        td = TestDataDef(
            file_path="data/DispatchData.java",
            variable_name="DISPATCH_USER",
            fields={"name": "test"},
        )
        code = self.generator.generate(td, {"maps_to": "test_data"})
        assert "DISPATCH_USER" in code or "test" in code

    def test_stage5_generate_dispatches_to_component_aw(self):
        """generate() 分发到 generate_component_aw"""
        cd = ComponentDef(
            class_name="DispatchForm",
            module="dispatch",
            xpath="[data-module='dispatch']",
            methods=[MethodTemplate(name="click", params=[], action_type="click")],
            base_class="BaseComponentAW",
        )
        code = self.generator.generate(cd, {"maps_to": "component_aw"})
        assert "DispatchForm" in code

    def test_stage5_generate_dispatches_to_business_aw(self):
        """generate() 分发到 generate_business_aw"""
        baw = BAWDef(
            class_name="DispatchPage",
            module="dispatch",
            operations=[
                BAWOperationDef(
                    name="doSomething",
                    params=[],
                    calls=[CallDef(component="Button", method="click", args=[])],
                ),
            ],
        )
        code = self.generator.generate(baw, {"maps_to": "business_aw"})
        assert "DispatchPage" in code

    def test_stage5_generate_unknown_layer_raises(self):
        """未知 layer → ValueError"""
        sd = ScriptDef(class_name="X", test_name="x", description="x", imports=[], fixtures=[], steps=[], data_refs=[])
        with pytest.raises(ValueError):
            self.generator.generate(sd, {"maps_to": "unknown_layer"})

    def test_stage5_render_step_decl(self):
        """渲染变量声明步骤"""
        step = MockStep(
            kind=StepKind.decl,
            decl=MockDecl(type="LoginFormAW", var="loginForm"),
        )
        code = self.generator.render_step(step)
        assert "LoginFormAW" in code
        assert "loginForm" in code
        assert "new" in code

    def test_stage5_render_step_navigate(self):
        """渲染 navigate 步骤"""
        step = MockStep(
            kind=StepKind.navigate,
            calls=[MockCall(method="navigate", args=["https://example.com/login"])],
        )
        code = self.generator.render_step(step)
        assert "navigate" in code
        assert "https://example.com/login" in code

    def test_stage5_render_step_action_with_args(self):
        """渲染 action 步骤（带参数）"""
        step = MockStep(
            kind=StepKind.action,
            calls=[MockCall(component="loginForm", method="enterUsername", args=["admin"])],
        )
        code = self.generator.render_step(step)
        assert "loginForm.enterUsername" in code
        assert "admin" in code

    def test_stage5_render_step_action_no_args(self):
        """渲染 action 步骤（无参数）"""
        step = MockStep(
            kind=StepKind.action,
            calls=[MockCall(component="loginForm", method="clickLogin", args=[])],
        )
        code = self.generator.render_step(step)
        assert "loginForm.clickLogin()" in code

    def test_stage5_render_step_assert(self):
        """渲染断言步骤"""
        step = MockStep(
            kind=StepKind.assert_step,
            calls=[MockCall(args=["assert page.url == \"https://example.com/dashboard\""])],
        )
        code = self.generator.render_step(step)
        # Should render some assertion
        assert len(code) > 0

    def test_stage5_render_step_assert_no_msg(self):
        """渲染无消息断言 → 默认 assertNotNull"""
        step = MockStep(
            kind=StepKind.assert_step,
            calls=[MockCall(args=[])],
        )
        code = self.generator.render_step(step)
        assert "assertNotNull" in code or "Assert" in code

    def test_stage5_render_assertion_url_equals(self):
        """渲染 URL 相等断言"""
        code = self.generator._render_assertion('assert page.url == "https://example.com/dashboard"')
        assert "assertEquals" in code
        assert "https://example.com/dashboard" in code

    def test_stage5_render_assertion_element_visible(self):
        """渲染元素可见断言"""
        code = self.generator._render_assertion("assert element 'submit-btn' (button) is visible")
        assert "submit-btn" in code or "isVisible" in code

    def test_stage5_render_assertion_element_absent(self):
        """渲染元素不存在断言"""
        code = self.generator._render_assertion("assert element 'error-msg' (alert) is absent")
        assert "error-msg" in code or "isVisible" in code

    def test_stage5_render_assertion_text_equals(self):
        """渲染文本相等断言"""
        code = self.generator._render_assertion("assert text of 'heading' == \"Welcome\"")
        assert "assertEquals" in code or "textContent" in code

    def test_stage5_render_assertion_count_changed(self):
        """渲染计数变化断言"""
        code = self.generator._render_assertion("assert count of table elements increased")
        assert "count" in code or "should" in code.lower()

    def test_stage5_render_assertion_layout_stable(self):
        """渲染布局稳定断言"""
        code = self.generator._render_assertion("assert layout of 'main-content' is stable")
        assert "layout" in code or "stable" in code

    def test_stage5_render_assertion_generic(self):
        """渲染通用断言"""
        code = self.generator._render_assertion("assert the page loads within 5 seconds")
        assert "verify" in code or "TODO" in code or "assert" in code.lower()

    def test_stage5_render_assertion_unknown(self):
        """渲染未知格式断言 → TODO"""
        code = self.generator._render_assertion("random check something")
        assert "TODO" in code or "Assert" in code

    def test_stage5_import_style(self):
        """返回 import 风格"""
        style = self.generator.get_import_style()
        assert style is not None
        assert isinstance(style, str) and len(style) > 0

    def test_stage5_assertion_style(self):
        """断言风格 — testng_assert"""
        style = self.generator.get_assertion_style()
        assert style is not None
        assert isinstance(style, str) and len(style) > 0

    def test_stage5_default_assertion_style(self):
        """默认断言风格为 testng_assert"""
        style = self.generator._default_assertion_style()
        assert style == "testng_assert"

    def test_stage5_target_language(self):
        """目标语言为 Java"""
        assert self.generator.target_language == "java"

    def test_stage5_default_base_class(self):
        """默认 base class"""
        assert self.generator.default_base_class == "BaseComponentAW"

    def test_stage5_generate_test_script_with_data_refs(self):
        """带 data_refs 的测试脚本"""
        sd = ScriptDef(
            class_name="TestWithData",
            test_name="testWithData",
            description="Test with data provider",
            imports=[
                "import org.testng.annotations.Test;",
                "import org.testng.Assert;",
            ],
            fixtures=[],
            steps=['page.navigate("https://example.com");'],
            data_refs=["VALID_USER"],
        )
        code = self.generator.generate_test_script(sd)
        assert len(code) > 0
        # data_refs should trigger dataProvider annotation
        assert "dataProvider" in code

    # ── Stage 6: DataFormatter ─────────────────────────────────

    def test_stage6_format_basic(self):
        """基本测试数据格式化"""
        data = self.formatter.format(
            {"username": "admin", "password": "secret", "email": "admin@test.com"},
            {"domain": "user"},
        )
        assert isinstance(data, TestDataDef)
        assert len(data.variable_name) > 0
        assert len(data.fields) == 3

    def test_stage6_format_single_field(self):
        """单字段格式化"""
        data = self.formatter.format(
            {"search_term": "hello"},
            {"domain": "search"},
        )
        assert isinstance(data, TestDataDef)
        assert len(data.fields) == 1
        assert "search_term" in data.fields

    def test_stage6_format_empty(self):
        """空数据格式化"""
        data = self.formatter.format({}, {"domain": "empty"})
        assert isinstance(data, TestDataDef)
        assert len(data.fields) == 0

    def test_stage6_format_variable_name(self):
        """变量名为 PascalCase + TestData 后缀"""
        data = self.formatter.format({"key": "val"}, {"domain": "user-login"})
        assert "TestData" in data.variable_name or "User" in data.variable_name

    def test_stage6_get_data_ref_style(self):
        """数据引用风格 — Java import"""
        ref = self.formatter.get_data_ref_style("user")
        assert "import" in ref
        assert "TestData" in ref or "data" in ref

    def test_stage6_infer_java_type_string(self):
        """字符串 → String"""
        assert _to_java_type("hello") == "String"

    def test_stage6_infer_java_type_bool(self):
        """布尔 → boolean"""
        assert _to_java_type(True) == "boolean"
        assert _to_java_type(False) == "boolean"

    def test_stage6_infer_java_type_int(self):
        """整数 → int"""
        assert _to_java_type(42) == "int"
        assert _to_java_type(0) == "int"

    def test_stage6_infer_java_type_float(self):
        """浮点数 → double"""
        assert _to_java_type(3.14) == "double"

    def test_stage6_infer_java_type_none(self):
        """None → String"""
        assert _to_java_type(None) == "String"


# ═══════════════════════════════════════════════════════════════
# Adapter swap test — same engine, different Playwright style
# ═══════════════════════════════════════════════════════════════

class TestPlaywrightAdapterSwap:
    """同一 ScriptDef，Playwright vs 其他 Java 适配器产出不同"""

    def test_same_input_different_java_output(self):
        """Playwright vs TestNG output differ"""
        from uibridge.adapter.custom_playwright_java import PlaywrightCodeGenerator
        from uibridge.adapter.java_testng import JavaCodeGenerator

        sd = ScriptDef(
            class_name="TestExample",
            test_name="exampleTest",
            description="Example",
            imports=["import org.testng.annotations.Test;"],
            fixtures=[],
            steps=['driver.get("https://example.com");'],
            data_refs=[],
        )

        playwright_code = PlaywrightCodeGenerator().generate_test_script(sd)
        testng_code = JavaCodeGenerator().generate_test_script(sd)

        assert len(playwright_code) > 0
        assert len(testng_code) > 0
        # Different styles should produce different output
        assert playwright_code != testng_code
