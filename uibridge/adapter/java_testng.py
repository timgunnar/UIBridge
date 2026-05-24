"""Java TestNG 适配器 — Java + TestNG + Maven + Page Object 模式"""

import re
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

from .base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter,
    MethodTemplate, ComponentDef, PageComponent, PageDef,
    BAWDef, BAWOperationDef, CallDef,
    ElementInfo, TestDataDef, ScriptDef,
    scan_java_source_for_package,
    sanitize_identifier,
    _to_java_type,
    to_java_class_name,
    post_process_java_code,
    format_action_params,
    extract_domain,
    JINJA_ENV,
    resolve_package,
)


# ═══════════════════════════════════════════════════════════════
# JavaComponentResolver
# ═══════════════════════════════════════════════════════════════

class JavaComponentResolver(ComponentResolver):
    """基于 ARIA role 映射为 Java Page Object 中的组件类型"""

    ARIA_MAP = {
        "table": "WebTable", "grid": "WebTable", "treegrid": "WebTable",
        "form": "WebForm", "dialog": "WebDialog",
        "combobox": "WebDropdown", "listbox": "WebDropdown",
        "menu": "WebMenu", "menubar": "WebMenu",
        "tablist": "WebTab", "tree": "WebTree",
        "navigation": "WebNav",
        "button": "WebButton", "link": "WebLink",
        "textbox": "WebInput", "searchbox": "WebInput",
        "checkbox": "WebCheckbox", "radio": "WebRadio",
        "alert": "WebAlert", "banner": "WebBanner",
    }

    METHOD_TEMPLATES = {
        "WebTable": [
            MethodTemplate("waitForLoad", [], "wait"),
            MethodTemplate("clickRow", [{"name": "index", "type": "int"}], "click"),
            MethodTemplate("getRowCount", [], "read", "int"),
            MethodTemplate("getCellText", [{"name": "row", "type": "int"}, {"name": "col", "type": "int"}], "read", "String"),
            MethodTemplate("assertRowContains", [{"name": "text", "type": "String"}], "assertion"),
            MethodTemplate("filterByColumn", [{"name": "col", "type": "int"}, {"name": "value", "type": "String"}], "input"),
        ],
        "WebForm": [
            MethodTemplate("waitForLoad", [], "wait"),
            MethodTemplate("submit", [], "click"),
            MethodTemplate("reset", [], "click"),
            MethodTemplate("assertFieldError", [{"name": "field", "type": "String"}], "assertion"),
        ],
        "WebInput": [
            MethodTemplate("enter", [{"name": "text", "type": "String"}], "input"),
            MethodTemplate("clear", [], "input"),
            MethodTemplate("getValue", [], "read", "String"),
            MethodTemplate("assertValue", [{"name": "expected", "type": "String"}], "assertion"),
        ],
        "WebButton": [
            MethodTemplate("click", [], "click"),
            MethodTemplate("assertEnabled", [], "assertion"),
            MethodTemplate("assertDisabled", [], "assertion"),
        ],
        "WebDropdown": [
            MethodTemplate("selectByValue", [{"name": "value", "type": "String"}], "select"),
            MethodTemplate("getSelected", [], "read", "String"),
            MethodTemplate("assertSelected", [{"name": "expected", "type": "String"}], "assertion"),
        ],
        "WebDialog": [
            MethodTemplate("waitForVisible", [], "wait"),
            MethodTemplate("confirm", [], "click"),
            MethodTemplate("cancel", [], "click"),
            MethodTemplate("getMessage", [], "read", "String"),
        ],
        "WebMenu": [
            MethodTemplate("clickItem", [{"name": "label", "type": "String"}], "click"),
            MethodTemplate("assertItemVisible", [{"name": "label", "type": "String"}], "assertion"),
        ],
        "WebTab": [
            MethodTemplate("select", [{"name": "tabName", "type": "String"}], "click"),
            MethodTemplate("assertSelected", [{"name": "tabName", "type": "String"}], "assertion"),
        ],
        "WebTree": [
            MethodTemplate("expand", [{"name": "node", "type": "String"}], "click"),
            MethodTemplate("clickNode", [{"name": "label", "type": "String"}], "click"),
            MethodTemplate("assertNodeVisible", [{"name": "label", "type": "String"}], "assertion"),
        ],
        "WebNav": [
            MethodTemplate("goTo", [{"name": "section", "type": "String"}], "click"),
            MethodTemplate("assertActive", [{"name": "section", "type": "String"}], "assertion"),
        ],
        "WebLink": [
            MethodTemplate("click", [], "click"),
            MethodTemplate("getUrl", [], "read", "String"),
            MethodTemplate("assertHrefContains", [{"name": "text", "type": "String"}], "assertion"),
        ],
        "WebCheckbox": [
            MethodTemplate("check", [], "click"),
            MethodTemplate("uncheck", [], "click"),
            MethodTemplate("isChecked", [], "read", "boolean"),
            MethodTemplate("assertChecked", [], "assertion"),
        ],
        "WebRadio": [
            MethodTemplate("select", [{"name": "value", "type": "String"}], "click"),
            MethodTemplate("getSelected", [], "read", "String"),
            MethodTemplate("assertSelected", [{"name": "expected", "type": "String"}], "assertion"),
        ],
        "WebAlert": [
            MethodTemplate("getText", [], "read", "String"),
            MethodTemplate("accept", [], "click"),
            MethodTemplate("dismiss", [], "click"),
        ],
        "WebBanner": [
            MethodTemplate("assertVisible", [], "assertion"),
            MethodTemplate("getText", [], "read", "String"),
        ],
    }

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def resolve_type(self, aria_role: str, dom_attrs: dict, snapshot_context: str) -> str:
        aria_map = self._resolve_aria_map()
        data_module = dom_attrs.get("data-module", "")
        if data_module:
            return self._guess_from_name(data_module, aria_role)
        role_lower = aria_role.lower()
        if role_lower in aria_map:
            return aria_map[role_lower]
        tag = dom_attrs.get("tag", "").lower()
        tag_map = {
            "input": "WebInput", "select": "WebDropdown",
            "button": "WebButton", "a": "WebLink",
            "textarea": "WebInput", "table": "WebTable",
        }
        return tag_map.get(tag, "WebElement")

    def suggest_name(self, url: str, aria_role: str, dom_attrs: dict) -> str:
        domain = extract_domain(url)
        data_module = dom_attrs.get("data-module", "")
        if data_module:
            return to_java_class_name(data_module)
        role = aria_role or "element"
        return f"{to_java_class_name(domain)}{to_java_class_name(role)}"

    def get_methods_for_role(self, component_type: str, aria_role: str) -> list[MethodTemplate]:
        return self.METHOD_TEMPLATES.get(component_type, [
            MethodTemplate("click", [], "click"),
            MethodTemplate("assertVisible", [], "assertion"),
        ])

    def _guess_from_name(self, attr_value: str, aria_role: str) -> str:
        lower = attr_value.lower()
        if any(k in lower for k in ("table", "grid", "list")):
            return "WebTable"
        if any(k in lower for k in ("form", "edit", "create")):
            return "WebForm"
        if any(k in lower for k in ("select", "dropdown", "combo", "picker")):
            return "WebDropdown"
        if any(k in lower for k in ("dialog", "modal", "popup")):
            return "WebDialog"
        return self.ARIA_MAP.get(aria_role, "WebElement")


# ═══════════════════════════════════════════════════════════════
# JavaLocatorStrategy
# ═══════════════════════════════════════════════════════════════

class JavaLocatorStrategy(LocatorStrategy):
    """Java Selenium 定位策略: @FindBy 注解风格"""

    PRIORITY = ["id", "name", "xpath", "cssSelector"]

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def build_xpath(self, element_info: ElementInfo, dom_context: dict) -> str:
        attrs = element_info.attrs
        for selector in self._build_ancestor_chain(element_info, max_depth=3):
            m = re.search(r"data-module='([^']+)'", selector)
            if m:
                module = m.group(1)
                best = self.best_attr(element_info)
                return f"//*[@data-module='{module}']//{element_info.tag}[@{best}='{attrs.get(best)}']"
        for attr in ["id", "name", "data-testid", "data-module"]:
            if attr in attrs and attrs[attr]:
                return f"//{element_info.tag}[@{attr}='{attrs[attr]}']"
        if element_info.text:
            return f"//{element_info.tag}[contains(text(), '{element_info.text[:30]}')]"
        return ""

    def extract_feature_point(self, xpath: str) -> dict:
        for attr in ["id", "name", "data-module", "data-testid"]:
            match = re.search(rf"@{attr}=['\"]([^'\"]+)['\"]", xpath)
            if match:
                return {"type": attr, "value": match.group(1)}
        match = re.search(r"contains\([., ]'([^']+)'\)", xpath)
        if match:
            return {"type": "text-contains", "value": match.group(1)}
        return {"type": "xpath", "value": xpath}

    def get_locator_priority(self) -> list[str]:
        return self._resolve_locator_priority()

    def best_attr(self, element) -> str:
        """Return best attribute name for XPath construction."""
        attrs = element.attributes if hasattr(element, 'attributes') else element.attrs
        for attr in ["id", "name", "data-testid"]:
            if attr in attrs and attrs[attr]:
                return attr
        return "class"


# ═══════════════════════════════════════════════════════════════
# JavaActionRecognizer
# ═══════════════════════════════════════════════════════════════

class JavaActionRecognizer(ActionRecognizer):
    """将 DOM 操作序列聚合为 Java Page Object 方法调用"""

    def _composite_action_name(self) -> str:
        return "enterAndSubmit"



# ═══════════════════════════════════════════════════════════════
# JavaCodeGenerator
# ═══════════════════════════════════════════════════════════════

class JavaCodeGenerator(CodeGenerator):
    """生成 Java + TestNG/JUnit5 + Selenium 风格代码"""
    target_language = "java"
    default_base_class = "BaseComponent"
    DEFAULT_PACKAGE = "com.acme"
    DEFAULT_BASE_PAGE = "BasePage"

    def __init__(self, kb_manager=None, package_name: Optional[str] = None,
                 base_page_class: str = DEFAULT_BASE_PAGE, test_framework: str = "testng"):
        self.kb = kb_manager
        self.kb_manager = kb_manager
        self.project_root = str(kb_manager.project_root) if kb_manager and hasattr(kb_manager, 'project_root') else ""
        if package_name is not None:
            self.package = package_name
        else:
            pkg = resolve_package(self.project_root, self.kb_manager, self.DEFAULT_PACKAGE)
            if pkg is None:
                self.package = self.DEFAULT_PACKAGE
            else:
                self.package = pkg  # "" 表示默认包
        self.base_page = base_page_class
        self.test_framework = test_framework  # "testng" | "junit5" | "junit4"
        self._detect_framework()

    def _detect_framework(self):
        """从 KB 或项目源码自动检测测试框架"""
        if self.kb:
            for item in self.kb.store.list_category("conventions"):
                if "test_framework" in item.key:
                    self.test_framework = item.value.get("type", "testng")
                    return
        # 从项目源码检测
        if self.kb and hasattr(self.kb, 'project_root'):
            test_dir = self.kb.project_root / "src" / "test" / "java"
            if test_dir.exists():
                import glob
                for f in list(test_dir.glob("**/*.java"))[:20]:
                    try:
                        content = f.read_text(encoding="utf-8")
                        if "org.junit.jupiter" in content:
                            self.test_framework = "junit5"
                            return
                        if "org.junit.Test" in content:
                            self.test_framework = "junit4"
                            return
                    except Exception:
                        logger.warning("Failed to read Java file during framework detection", exc_info=True)
                        pass
    def generate_component_aw(self, comp_def: ComponentDef) -> str:
        JINJA_ENV.filters["repr"] = lambda v: repr(v)
        template = JINJA_ENV.from_string(JAVA_COMPONENT_TEMPLATE)
        return post_process_java_code(template.render(comp=comp_def, package=self.package), self.package)

    def generate_business_aw(self, baw_def: BAWDef) -> str:
        template = JINJA_ENV.from_string(JAVA_PAGE_OBJECT_TEMPLATE)
        return post_process_java_code(template.render(baw=baw_def, package=self.package), self.package)

    def generate_test_script(self, script_def: ScriptDef,
                             template_path: str = "") -> str:
        if self.test_framework == "junit5":
            template = JINJA_ENV.from_string(JAVA_JUNIT5_TEMPLATE)
        else:
            template = JINJA_ENV.from_string(JAVA_TESTNG_TEMPLATE)
        return post_process_java_code(template.render(s=script_def, package=self.package,
                               framework=self.test_framework), self.package)

    def generate_test_data(self, data_def: TestDataDef,
                           template_path: str = "") -> str:
        JINJA_ENV.filters["repr"] = lambda v: repr(v)
        template = JINJA_ENV.from_string(JAVA_TEST_DATA_TEMPLATE)
        return post_process_java_code(template.render(d=data_def, package=self.package), self.package)

    def _default_assertion_style(self) -> str:
        return "testng_assert"

    def render_step(self, step) -> str:
        """Java TestNG 风格步骤渲染"""
        kind = getattr(step, 'kind', None)
        decl = getattr(step, 'decl', None)

        if kind and kind.value == "decl" and decl:
            return f"{decl.type} {decl.var} = new {decl.type}(driver);"

        if kind and kind.value == "navigate" and step.calls:
            url = step.calls[0].args[0] if step.calls[0].args else ""
            return f'driver.get("{url}");'

        if kind and kind.value == "action" and step.calls:
            call = step.calls[0]
            component = call.component or "page"
            method = call.method
            args_str = format_action_params(call)
            if args_str:
                return f"{component}.{method}({args_str});"
            return f"{component}.{method}();"

        if kind and kind.value == "assert" and step.calls:
            msg = step.calls[0].args[0] if step.calls[0].args else step.comment
            if msg:
                return self._render_assertion(msg)
            return "Assert.assertNotNull(page);"

        comment = getattr(step, 'comment', '')
        if comment:
            return f"// {comment}"
        return ""

    def _render_assertion(self, candidate: str) -> str:
        from uibridge.adapter.base import parse_assertion_candidate
        p = parse_assertion_candidate(candidate)
        atype = p.get("type", "unknown")
        if atype == "url_equals":
            return f'Assert.assertEquals(page.getCurrentUrl(), "{p["url"]}");'
        elif atype == "element_visible":
            return f'Assert.assertTrue(page.isVisible("[data-module=\'{p["element"]}\']"), "{p["element"]} should be visible");'
        elif atype == "element_absent":
            return f'Assert.assertFalse(page.isVisible("[data-module=\'{p["element"]}\']"), "{p["element"]} should be absent");'
        elif atype == "text_equals":
            return f'Assert.assertEquals(page.getText("[data-module=\'{p["element"]}\']"), "{p["text"]}");'
        elif atype == "count_changed":
            return f'// {p["role"]} count should be {p["direction"]}'
        elif atype == "layout_stable":
            return f'// assert layout of \'{p["element"]}\' is stable'
        elif atype == "generic":
            msg = p.get("message", candidate)
            return f'// verify: {msg}'
        else:
            return f'Assert.assertNotNull(page); // TODO: assert {candidate}'


# ═══════════════════════════════════════════════════════════════
# JavaDataFormatter
# ═══════════════════════════════════════════════════════════════

class JavaDataFormatter(DataFormatter):
    """录制值 → Java 测试数据常量类"""
    DEFAULT_PACKAGE = "com.acme"

    def __init__(self, kb_manager=None, package_name: Optional[str] = None):
        self.kb = kb_manager
        self.kb_manager = kb_manager
        self.project_root = str(kb_manager.project_root) if kb_manager and hasattr(kb_manager, 'project_root') else ""
        if package_name is not None:
            self.package = package_name
        else:
            pkg = resolve_package(self.project_root, self.kb_manager, self.DEFAULT_PACKAGE)
            if pkg is None:
                self.package = self.DEFAULT_PACKAGE
            else:
                self.package = pkg

    def format(self, captured_values: dict, data_context: dict) -> TestDataDef:
        domain = data_context.get("domain", "unknown")
        class_name = f"{to_java_class_name(domain)}TestData"
        fields = {}
        for key, value in captured_values.items():
            java_type = _to_java_type(value)
            fields[key] = {"value": value, "type": java_type}
        if self.package:
            pkg_path = self.package.replace('.', '/') + '/'
        else:
            pkg_path = ''
        return TestDataDef(
            file_path=f"src/test/java/{pkg_path}data/{class_name}.java",
            variable_name=class_name,
            fields=fields,
        )

    def get_data_ref_style(self, domain: str) -> str:
        class_name = f"{to_java_class_name(domain)}TestData"
        if self.package:
            return f"import {self.package}.data.{class_name};"
        return f"import data.{class_name};"


# ═══════════════════════════════════════════════════════════════
# Jinja2 模板 — Java 代码输出
# ═══════════════════════════════════════════════════════════════

JAVA_COMPONENT_TEMPLATE = """// [AUTO-GEN] Component: {{ comp.class_name }}
package {{ package }}.components;

import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.By;

/**
 * {{ comp.class_name }} — auto-generated component wrapper.
 */
public class {{ comp.class_name }} {
    private final WebDriver driver;
    private final String rootXpath;

    public {{ comp.class_name }}(WebDriver driver, String xpath) {
        this.driver = driver;
        this.rootXpath = xpath;
    }

{% for method in comp.methods %}
{% if method.action_type == 'wait' %}
    public void {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        driver.findElement(By.xpath(rootXpath)).isDisplayed();
    }
{% elif method.action_type == 'click' %}
    public void {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        driver.findElement(By.xpath(rootXpath)).click();
    }
{% elif method.action_type == 'input' %}
    public void {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        driver.findElement(By.xpath(rootXpath)).sendKeys({{ method.params[0].name }});
    }
{% elif method.action_type == 'read' %}
    public {{ method.returns }} {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        return driver.findElement(By.xpath(rootXpath)).getText();
    }
{% elif method.action_type == 'assertion' %}
    public void {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        String actual = driver.findElement(By.xpath(rootXpath)).getText();
        Assert.assertEquals(actual, {{ method.params[0].name }});
    }
{% endif %}
{% endfor %}

{% for method in comp.methods if method.action_type == 'select' %}
    public void {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        new org.openqa.selenium.support.ui.Select(driver.findElement(By.xpath(rootXpath)))
            .selectByVisibleText({{ method.params[0].name }});
    }
{% endfor %}
}
"""

JAVA_PAGE_OBJECT_TEMPLATE = """// [AUTO-GEN] Page: {{ baw.class_name }}
package {{ package }}.pages;

import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.By;
{% for op in baw.operations %}
{% for call in op.calls %}
import {{ package }}.components.{{ call.component }};
{% endfor %}
{% endfor %}

/**
 * {{ baw.class_name }} — auto-generated page object.
 */
public class {{ baw.class_name }} extends BasePage {
{% for op in baw.operations %}
{% for call in op.calls %}
    private {{ call.component }} {{ call.component[:1].lower() }}{{ call.component[1:] }};
{% endfor %}
{% endfor %}

    public {{ baw.class_name }}(WebDriver driver) {
        super(driver);
{% for op in baw.operations %}
{% for call in op.calls %}
        this.{{ call.component[:1].lower() }}{{ call.component[1:] }} = new {{ call.component }}(driver, "//*[@data-module='{{ call.component.lower()|replace("web", "") }}']");
{% endfor %}
{% endfor %}
    }

{% for op in baw.operations %}
    public void {{ op.name }}({% for p in op.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
{% for call in op.calls %}
        {{ call.component[:1].lower() }}{{ call.component[1:] }}.{{ call.method }}({{ call.args|join(', ') }});
{% endfor %}
    }
{% endfor %}
}
"""

JAVA_TESTNG_TEMPLATE = """// [AUTO-GEN] {{ s.description or s.test_name }}
package {{ package }}.tests;

{% for imp in s.imports %}
{{ imp }}
{% endfor %}

public class {{ s.class_name }} {
    private WebDriver driver;

    @BeforeMethod
    public void setUp() {
        driver = new ChromeDriver();
    }

    @Test
    public void {{ s.test_name }}() {
{% for step in s.steps %}
        {{ step }}
{% endfor %}
    }
}
"""

JAVA_JUNIT5_TEMPLATE = """// [AUTO-GEN] {{ s.description or s.test_name }} — JUnit 5
package {{ package }}.tests;

{% for imp in s.imports %}
{{ imp }}
{% endfor %}

class {{ s.class_name }} {
    private WebDriver driver;

    @BeforeEach
    void setUp() {
        driver = new ChromeDriver();
    }

    @Test
    void {{ s.test_name }}() {
{% for step in s.steps %}
        {{ step }}
{% endfor %}
    }

    @AfterEach
    void tearDown() {
        if (driver != null) {
            driver.quit();
        }
    }
}
"""

JAVA_TEST_DATA_TEMPLATE = """// [AUTO-GEN] Test Data: {{ d.variable_name }}
package {{ package }}.data;

public class {{ d.variable_name }} {
{% for field, info in d.fields.items() %}
    public static final {{ info.type }} {{ field.upper() }} = {{ info.value | repr }};
{% endfor %}
}
"""
