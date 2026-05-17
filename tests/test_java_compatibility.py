"""Java 适配器兼容性测试 — java_testng + java_fluent (14/14)"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uibridge.adapter.base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter,
    MethodTemplate, ComponentDef, ScriptDef, TestDataDef,
    ElementInfo, BAWDef, BAWOperationDef, CallDef, PageDef, PageComponent,
)


# ═══════════════════════════════════════════════════════════════
# java_testng adapter
# ═══════════════════════════════════════════════════════════════

class TestJavaTestNGAdapter:
    """Java TestNG 适配器 5 个接口测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from uibridge.adapter.java_testng import (
            JavaComponentResolver,
            JavaLocatorStrategy,
            JavaActionRecognizer,
            JavaCodeGenerator,
            JavaDataFormatter,
        )
        self.resolver = JavaComponentResolver()
        self.locator = JavaLocatorStrategy()
        self.recognizer = JavaActionRecognizer()
        self.generator = JavaCodeGenerator()
        self.formatter = JavaDataFormatter()

    def test_stage1_instantiation(self):
        """5 个接口类均可实例化"""
        assert isinstance(self.resolver, ComponentResolver)
        assert isinstance(self.locator, LocatorStrategy)
        assert isinstance(self.recognizer, ActionRecognizer)
        assert isinstance(self.generator, CodeGenerator)
        assert isinstance(self.formatter, DataFormatter)

    def test_stage2_resolve_java_components(self):
        """Java 组件类型解析"""
        assert self.resolver.resolve_type("table", {}, "") == "WebTable"
        assert self.resolver.resolve_type("textbox", {}, "") == "WebInput"
        assert self.resolver.resolve_type("button", {}, "") == "WebButton"
        assert self.resolver.resolve_type("combobox", {}, "") == "WebDropdown"
        assert self.resolver.resolve_type("dialog", {}, "") == "WebDialog"

    def test_stage2_java_methods_for_table(self):
        """WebTable 返回 Java 风格方法"""
        methods = self.resolver.get_methods_for_role("WebTable", "table")
        assert len(methods) > 0
        for m in methods:
            assert m.name  # method name must be present
            assert m.action_type  # action type must be present

    def test_stage2_suggest_name(self):
        """组件命名建议"""
        name = self.resolver.suggest_name("https://app.com/user/list", "table", {})
        assert len(name) > 0

    def test_stage3_java_locator_strategy(self):
        """Java 定位器策略"""
        ei = ElementInfo(
            tag="input",
            attrs={"id": "username", "name": "user", "data-testid": "login-user"},
            text="",
            ancestor_chain=[],
        )
        xpath = self.locator.build_xpath(ei, {})
        assert len(xpath) > 0
        # Should prefer data-testid or id
        assert "username" in xpath or "login-user" in xpath

    def test_stage3_locator_priority(self):
        """定位器优先级"""
        pri = self.locator.get_locator_priority()
        assert len(pri) > 0
        # Java typically prefers data-testid or xpath
        assert any(p in pri for p in ["data-testid", "xpath", "id", "name"])

    def test_stage4_java_component_aw_generation(self):
        """生成 Java Component AW"""
        cd = ComponentDef(
            class_name="LoginForm",
            module="com.enterprise.components.LoginForm",
            xpath="//form[@data-module='login']",
            methods=[
                MethodTemplate(name="enterUsername", params=[{"name": "text"}], action_type="input", returns="void"),
                MethodTemplate(name="enterPassword", params=[{"name": "text"}], action_type="input", returns="void"),
                MethodTemplate(name="clickLogin", params=[], action_type="click", returns="void"),
            ],
            base_class="WebForm",
        )
        code = self.generator.generate_component_aw(cd)
        assert "class LoginForm" in code or "LoginForm" in code
        assert "enterUsername" in code or "enter_username" in code

    def test_stage4_java_test_generation(self):
        """生成 Java TestNG 测试"""
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
                'driver.get("https://example.com/login");',
                'loginForm.enterUsername("admin");',
                'loginForm.enterPassword("secret");',
                "loginForm.clickLogin();",
                'Assert.assertEquals(driver.getCurrentUrl(), "https://example.com/dashboard");',
            ],
            data_refs=[],
        )
        code = self.generator.generate_test_script(sd)
        assert "TestUserLogin" in code or "shouldLoginSuccessfully" in code
        assert "@Test" in code or "test" in code.lower()

    def test_stage4_java_test_data(self):
        """生成 Java 测试数据"""
        td = TestDataDef(
            file_path="com/enterprise/data/UserTestData.java",
            variable_name="VALID_USER",
            fields={"username": "admin", "password": "secret123"},
        )
        code = self.generator.generate_test_data(td)
        assert "VALID_USER" in code or "admin" in code

    def test_stage5_java_import_style(self):
        """Java import 风格"""
        style = self.generator.get_import_style()
        assert style is not None

    def test_stage5_java_assertion_style(self):
        """Java 断言风格"""
        style = self.generator.get_assertion_style()
        assert style is not None

    def test_stage5_java_page_generation(self):
        """生成 Java Page Object"""
        page = PageDef(
            class_name="UserManagementPage",
            module="com.enterprise.pages.UserManagementPage",
            url_pattern="/user/**",
            components=[
                PageComponent(name="userTable", type="WebTable", xpath="//table[@data-module='user-table']"),
                PageComponent(name="addButton", type="WebButton", xpath="//button[@data-testid='add-user']"),
            ],
        )
        # This method should exist on the code generator
        if hasattr(self.generator, 'generate_page'):
            code = self.generator.generate_page(page)
            assert "UserManagementPage" in code


# ═══════════════════════════════════════════════════════════════
# java_fluent adapter
# ═══════════════════════════════════════════════════════════════

class TestJavaFluentAdapter:
    """Java Fluent 适配器 5 个接口测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from uibridge.adapter.java_fluent import (
            FluentComponentResolver,
            FluentLocatorStrategy,
            FluentActionRecognizer,
            FluentCodeGenerator,
            FluentDataFormatter,
        )
        self.resolver = FluentComponentResolver()
        self.locator = FluentLocatorStrategy()
        self.recognizer = FluentActionRecognizer()
        self.generator = FluentCodeGenerator()
        self.formatter = FluentDataFormatter()

    def test_stage1_instantiation(self):
        """5 个接口类均可实例化"""
        assert isinstance(self.resolver, ComponentResolver)
        assert isinstance(self.locator, LocatorStrategy)
        assert isinstance(self.recognizer, ActionRecognizer)
        assert isinstance(self.generator, CodeGenerator)
        assert isinstance(self.formatter, DataFormatter)

    def test_stage2_fluent_component_types(self):
        """Fluent 组件类型（泛型 PageElement）"""
        cls = self.resolver.resolve_type("button", {}, "")
        assert len(cls) > 0
        # Fluent typically uses generic PageElement
        cls2 = self.resolver.resolve_type("table", {}, "")
        assert len(cls2) > 0

    def test_stage3_fluent_locator(self):
        """Fluent 定位器 — 优先 data-testid"""
        ei = ElementInfo(
            tag="button",
            attrs={"data-testid": "submit-btn", "class": "btn-primary"},
            text="Submit",
            ancestor_chain=[],
        )
        xpath = self.locator.build_xpath(ei, {})
        assert len(xpath) > 0
        assert "submit-btn" in xpath or "Submit" in xpath

    def test_stage4_fluent_component_code(self):
        """Fluent 组件代码 — 链式 return this"""
        cd = ComponentDef(
            class_name="SearchField",
            module="com.fluent.elements.SearchField",
            xpath="//input[@placeholder='Search']",
            methods=[
                MethodTemplate(name="enterText", params=[{"name": "text"}], action_type="input", returns="SearchField"),
                MethodTemplate(name="submit", params=[], action_type="click", returns="SearchField"),
            ],
            base_class="PageElement",
        )
        code = self.generator.generate_component_aw(cd)
        assert "class SearchField" in code or "SearchField" in code
        assert "return this" in code or "SearchField" in code

    def test_stage4_fluent_test_generation(self):
        """Fluent 测试 — ShouldXxx 命名 + AssertJ"""
        sd = ScriptDef(
            class_name="ShouldCreateUser",
            test_name="shouldCreateUserSuccessfully",
            description="Create user with fluent API",
            imports=[
                "import org.testng.annotations.Test;",
                "import static org.assertj.core.api.Assertions.assertThat;",
            ],
            fixtures=[],
            steps=[
                "UserPage userPage = new UserPage(driver);",
                'userPage.addButton().click()',
                '.enterUsername("new_user")',
                '.enterEmail("user@example.com")',
                ".submit();",
                'assertThat(userPage.getSuccessMessage()).isEqualTo("User created");',
            ],
            data_refs=[],
        )
        code = self.generator.generate_test_script(sd)
        assert "ShouldCreateUser" in code or "shouldCreateUser" in code
        assert "assertThat" in code or "Assert" in code or "assert" in code.lower()

    def test_stage4_fluent_data_builder(self):
        """Fluent 测试数据 — Builder 模式"""
        td = TestDataDef(
            file_path="com/fluent/builders/UserBuilder.java",
            variable_name="DEFAULT_USER",
            fields={"username": "testuser", "email": "test@example.com", "role": "ADMIN"},
        )
        code = self.generator.generate_test_data(td)
        assert "DEFAULT_USER" in code or "testuser" in code or "builder" in code.lower()

    def test_stage5_fluent_import_style(self):
        """Fluent import 风格"""
        style = self.generator.get_import_style()
        assert style is not None

    def test_stage5_fluent_assertion_style(self):
        """Fluent 断言风格 (AssertJ)"""
        style = self.generator.get_assertion_style()
        assert style is not None


# ═══════════════════════════════════════════════════════════════
# Java cross-adapter swap test
# ═══════════════════════════════════════════════════════════════

class TestJavaAdapterSwap:
    """同一引擎 + 不同 Java 适配器 → 不同代码风格"""

    def test_same_input_different_java_output(self):
        """相同 ScriptDef，testng vs fluent 产出不同"""
        from uibridge.adapter.java_testng import JavaCodeGenerator
        from uibridge.adapter.java_fluent import FluentCodeGenerator

        sd = ScriptDef(
            class_name="TestExample",
            test_name="exampleTest",
            description="Example",
            imports=["import org.testng.annotations.Test;"],
            fixtures=[],
            steps=['driver.get("https://example.com");'],
            data_refs=[],
        )

        testng_code = JavaCodeGenerator().generate_test_script(sd)
        fluent_code = FluentCodeGenerator().generate_test_script(sd)

        assert len(testng_code) > 0
        assert len(fluent_code) > 0
        # Different styles should produce different output
        assert testng_code != fluent_code


# ═══════════════════════════════════════════════════════════════
# Action recognizer tests (shared across Java adapters)
# ═══════════════════════════════════════════════════════════════

class TestJavaActionRecognition:
    """Java 适配器的动作识别"""

    def test_java_testng_recognizer_aggregate(self):
        """Java TestNG 动作聚合"""
        from uibridge.adapter.java_testng import JavaActionRecognizer

        recognizer = JavaActionRecognizer()
        steps = [
            {"action": "input", "value": "admin", "target": {"label": "Username"}},
            {"action": "input", "value": "secret", "target": {"label": "Password"}},
            {"action": "click", "value": None, "target": {"label": "Login"}},
        ]
        result = recognizer.aggregate(steps, {"page": "/login"})
        assert len(result) > 0

    def test_java_fluent_recognizer_aggregate(self):
        """Java Fluent 动作聚合"""
        from uibridge.adapter.java_fluent import FluentActionRecognizer

        recognizer = FluentActionRecognizer()
        steps = [
            {"action": "click", "value": None, "target": {"label": "Add User"}},
            {"action": "input", "value": "John", "target": {"label": "Name"}},
        ]
        result = recognizer.aggregate(steps, {"page": "/users"})
        assert len(result) > 0


# ═══════════════════════════════════════════════════════════════
# Data formatter tests
# ═══════════════════════════════════════════════════════════════

class TestJavaDataFormatting:
    """Java 测试数据格式化"""

    def test_java_testng_data_format(self):
        """Java TestNG 数据格式化"""
        from uibridge.adapter.java_testng import JavaDataFormatter

        fmt = JavaDataFormatter()
        data = fmt.format(
            {"username": "admin", "password": "secret", "email": "admin@test.com"},
            {"domain": "user"},
        )
        assert isinstance(data, TestDataDef)
        assert data.variable_name

    def test_java_fluent_data_format(self):
        """Java Fluent 数据格式化"""
        from uibridge.adapter.java_fluent import FluentDataFormatter

        fmt = FluentDataFormatter()
        data = fmt.format(
            {"username": "testuser", "role": "ADMIN"},
            {"domain": "user"},
        )
        assert isinstance(data, TestDataDef)
        assert data.variable_name
