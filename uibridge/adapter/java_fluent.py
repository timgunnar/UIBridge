"""Java Fluent 适配器 — Java + TestNG + PageFactory + AssertJ 流式模式"""

import re
from typing import Optional
import logging

logger = logging.getLogger(__name__)

from .base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter,
    MethodTemplate, ComponentDef,
    BAWDef, CallDef,
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


class FluentComponentResolver(ComponentResolver):
    """PageFactory: 组件用 @FindBy 定位，按类型分化为不同 PageElement 子类"""

    ARIA_MAP = {
        "table": "TableElement", "grid": "TableElement", "treegrid": "TableElement",
        "form": "FormElement",
        "textbox": "InputElement", "searchbox": "InputElement", "spinbutton": "SpinnerElement",
        "checkbox": "CheckboxElement", "radio": "RadioElement", "switch": "ToggleElement",
        "combobox": "DropdownElement", "listbox": "DropdownElement",
        "slider": "SliderElement", "option": "OptionElement",
        "menu": "MenuElement", "menubar": "MenuElement",
        "tablist": "TabElement", "tab": "TabElement",
        "tree": "TreeElement", "treeitem": "TreeItemElement",
        "navigation": "NavElement", "link": "LinkElement", "button": "ButtonElement",
        "dialog": "DialogElement", "alert": "AlertElement", "alertdialog": "DialogElement",
        "banner": "BannerElement", "tooltip": "TooltipElement",
        "progressbar": "ProgressElement", "status": "StatusElement",
        "log": "LogElement", "timer": "TimerElement",
        "region": "RegionElement", "group": "GroupElement",
        "list": "ListElement", "listitem": "ListItemElement",
        "separator": "SeparatorElement",
        "img": "ImageElement", "heading": "HeadingElement",
        "main": "MainElement", "contentinfo": "FooterElement",
    }

    METHOD_TEMPLATES = {
        "TableElement": [
            MethodTemplate("click", [], "click"),
            MethodTemplate("getRowCount", [], "read", "int"),
            MethodTemplate("getCellText", [{"name": "row", "type": "int"}, {"name": "col", "type": "int"}], "read", "String"),
            MethodTemplate("shouldBeVisible", [], "assertion"),
            MethodTemplate("shouldContain", [{"name": "text", "type": "String"}], "assertion"),
        ],
        "FormElement": [
            MethodTemplate("submit", [], "click"),
            MethodTemplate("reset", [], "click"),
            MethodTemplate("shouldBeVisible", [], "assertion"),
        ],
        "InputElement": [
            MethodTemplate("enter", [{"name": "text", "type": "String"}], "input"),
            MethodTemplate("clear", [], "input"),
            MethodTemplate("getText", [], "read", "String"),
            MethodTemplate("shouldContain", [{"name": "text", "type": "String"}], "assertion"),
        ],
        "ButtonElement": [
            MethodTemplate("click", [], "click"),
            MethodTemplate("shouldBeVisible", [], "assertion"),
            MethodTemplate("shouldBeEnabled", [], "assertion"),
        ],
        "DropdownElement": [
            MethodTemplate("selectByValue", [{"name": "value", "type": "String"}], "select"),
            MethodTemplate("selectByIndex", [{"name": "index", "type": "int"}], "select"),
            MethodTemplate("getSelectedText", [], "read", "String"),
            MethodTemplate("shouldBeVisible", [], "assertion"),
        ],
        "CheckboxElement": [
            MethodTemplate("check", [], "click"),
            MethodTemplate("uncheck", [], "click"),
            MethodTemplate("isChecked", [], "read", "boolean"),
        ],
        "LinkElement": [
            MethodTemplate("click", [], "click"),
            MethodTemplate("getHref", [], "read", "String"),
            MethodTemplate("shouldBeVisible", [], "assertion"),
        ],
        "DialogElement": [
            MethodTemplate("accept", [], "click"),
            MethodTemplate("dismiss", [], "click"),
            MethodTemplate("shouldBeVisible", [], "assertion"),
        ],
        "PageElement": [
            MethodTemplate("click", [], "click"),
            MethodTemplate("getText", [], "read", "String"),
            MethodTemplate("shouldBeVisible", [], "assertion"),
            MethodTemplate("shouldContain", [{"name": "text", "type": "String"}], "assertion"),
        ],
    }

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def resolve_type(self, aria_role: str, dom_attrs: dict, snapshot_context: str) -> str:
        role_map = self._resolve_aria_map()
        return role_map.get(aria_role.lower(), "PageElement")

    def suggest_name(self, url: str, aria_role: str, dom_attrs: dict) -> str:
        data_module = dom_attrs.get("data-module", "")
        if data_module:
            return to_java_class_name(data_module)
        domain = extract_domain(url)
        role = aria_role or "Element"
        return f"{to_java_class_name(domain)}{to_java_class_name(role)}"

    def get_methods_for_role(self, component_type: str, aria_role: str) -> list[MethodTemplate]:
        return self.METHOD_TEMPLATES.get(component_type, self.METHOD_TEMPLATES.get("PageElement", []))


class FluentLocatorStrategy(LocatorStrategy):
    """Fluent: @FindBy 注解，css 和 xpath 优先"""

    PRIORITY = ["css", "xpath", "id", "data-test"]

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def build_xpath(self, element_info: ElementInfo, dom_context: dict) -> str:
        attrs = element_info.attrs
        # 1. 向上查找最近的 data-module 祖先
        for selector in self._build_ancestor_chain(element_info, max_depth=3):
            m = re.search(r"data-module='([^']+)'", selector)
            if m:
                module = m.group(1)
                best = self.best_attr(element_info)
                if best and attrs.get(best):
                    return f"[data-module='{module}'] [{best}='{attrs[best]}']"
                return f"[data-module='{module}']"
        # 2. 元素自身的稳定属性
        if "id" in attrs and attrs["id"]:
            return f"#{attrs['id']}"
        for attr in ["data-test", "data-testid"]:
            if attr in attrs and attrs[attr]:
                return f"[{attr}='{attrs[attr]}']"
        if "name" in attrs and attrs["name"]:
            return f"*[name='{attrs['name']}']"
        return ""

    def best_attr(self, element) -> str:
        """Return best attribute name for Fluent locator construction."""
        attrs = element.attributes if hasattr(element, 'attributes') else element.attrs
        for attr in ["id", "data-test", "data-testid", "name"]:
            if attr in attrs and attrs[attr]:
                return attr
        return ""

    def extract_feature_point(self, xpath: str) -> dict:
        for attr in ["id", "data-test", "data-testid", "name"]:
            match = re.search(rf"\[?{attr}='([^']+)'\]?", xpath)
            if match:
                return {"type": attr, "value": match.group(1)}
        return {"type": "css", "value": xpath}

    def get_locator_priority(self) -> list[str]:
        return self._resolve_locator_priority()


class FluentActionRecognizer(ActionRecognizer):
    """Fluent: DOM 操作 → 返回 this 的链式方法，含 buffer 聚合"""

    def _composite_action_type(self) -> str:
        return "fluent_action"

    def _single_action_type(self) -> str:
        return "fluent_action"



class FluentCodeGenerator(CodeGenerator):
    """生成 Fluent API + PageFactory + AssertJ 风格"""
    target_language = "java"
    default_base_class = "PageElement"
    DEFAULT_PACKAGE = "com.fluent"

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

    def generate_component_aw(self, comp_def: ComponentDef) -> str:
        template = JINJA_ENV.from_string(FLUENT_ELEMENT_TEMPLATE)
        return post_process_java_code(template.render(comp=comp_def, package=self.package), self.package)

    def generate_business_aw(self, baw_def: BAWDef) -> str:
        template = JINJA_ENV.from_string(FLUENT_PAGE_TEMPLATE)
        return post_process_java_code(template.render(baw=baw_def, package=self.package), self.package)

    def generate_test_script(self, script_def: ScriptDef,
                             template_path: str = "") -> str:
        template = JINJA_ENV.from_string(FLUENT_TEST_TEMPLATE)
        return post_process_java_code(template.render(s=script_def, package=self.package), self.package)

    def generate_test_data(self, data_def: TestDataDef,
                           template_path: str = "") -> str:
        JINJA_ENV.filters["repr"] = lambda v: repr(v)
        template = JINJA_ENV.from_string(FLUENT_DATA_BUILDER_TEMPLATE)
        return post_process_java_code(template.render(d=data_def, package=self.package), self.package)

    def _default_assertion_style(self) -> str:
        return "assertj"

    def render_step(self, step) -> str:
        """Java Fluent 风格步骤渲染"""
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
            return "assertThat(page).isNotNull();"

        comment = getattr(step, 'comment', '')
        if comment:
            return f"// {comment}"
        return ""

    def _render_assertion(self, candidate: str) -> str:
        from uibridge.adapter.base import parse_assertion_candidate
        p = parse_assertion_candidate(candidate)
        atype = p.get("type", "unknown")
        if atype == "url_equals":
            return f'assertThat(page.getCurrentUrl()).isEqualTo("{p["url"]}");'
        elif atype == "element_visible":
            return f'assertThat(page.find("[data-module=\'{p["element"]}\']")).isVisible();'
        elif atype == "element_absent":
            return f'assertThat(page.find("[data-module=\'{p["element"]}\']")).isHidden();'
        elif atype == "text_equals":
            return f'assertThat(page.find("[data-module=\'{p["element"]}\']")).hasText("{p["text"]}");'
        elif atype == "count_changed":
            direction = "greaterThan" if p["direction"] == "increased" else "lessThan"
            return f'// {p["role"]} count should be {p["direction"]}'
        elif atype == "layout_stable":
            return f'// assert layout of \'{p["element"]}\' is stable'
        elif atype == "generic":
            msg = p.get("message", candidate)
            return f'// verify: {msg}'
        else:
            return f'assertThat(page).isNotNull(); // TODO: assert {candidate}'


class FluentDataFormatter(DataFormatter):
    """Fluent: Builder 模式而不是常量类"""
    DEFAULT_PACKAGE = "com.fluent"

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
        class_name = f"{to_java_class_name(domain)}Builder"
        fields = {}
        for key, value in captured_values.items():
            java_type = _to_java_type(value)
            fields[key] = {"value": value, "type": java_type}
        return TestDataDef(
            file_path=f"src/test/java/builders/{class_name}.java",
            variable_name=class_name,
            fields=fields,
        )

    def get_data_ref_style(self, domain: str) -> str:
        class_name = f"{to_java_class_name(domain)}Builder"
        if self.package:
            return f"import {self.package}.builders.{class_name};"
        return f"import builders.{class_name}";


# ═══════════════════════════════════════════════════════════════
# Fluent 模板
# ═══════════════════════════════════════════════════════════════

FLUENT_ELEMENT_TEMPLATE = """// [AUTO-GEN] Page Element: {{ comp.class_name }}
package {{ package }}.elements;

import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.support.FindBy;
import org.openqa.selenium.support.PageFactory;

public class {{ comp.class_name }} {
    private final WebDriver driver;

    @FindBy(xpath = "{{ comp.xpath }}")
    private WebElement element;

    public {{ comp.class_name }}(WebDriver driver) {
        this.driver = driver;
        PageFactory.initElements(driver, this);
    }
{% for method in comp.methods %}
{% if method.action_type == 'click' %}
    public {{ comp.class_name }} click() {
        element.click();
        return this;
    }
{% elif method.action_type == 'input' %}
    public {{ comp.class_name }} enter({{ method.params[0].type }} text) {
        element.sendKeys(text);
        return this;
    }
{% elif method.action_type == 'read' %}
    public {{ method.returns }} getText() {
        return element.getText();
    }
{% elif method.action_type == 'assertion' %}
    public {{ comp.class_name }} shouldBeVisible() {
        assert element.isDisplayed();
        return this;
    }
{% endif %}
{% endfor %}
}
"""

FLUENT_PAGE_TEMPLATE = """// [AUTO-GEN] Fluent Page: {{ baw.class_name }}
package {{ package }}.pages;

import org.openqa.selenium.WebDriver;
{% for op in baw.operations %}
{% for call in op.calls %}
import {{ package }}.elements.{{ call.component }};
{% endfor %}
{% endfor %}

public class {{ baw.class_name }} {
    private final WebDriver driver;
{% for op in baw.operations %}
{% for call in op.calls %}
    private final {{ call.component }} {{ call.component[:1].lower() }}{{ call.component[1:] }};
{% endfor %}
{% endfor %}

    public {{ baw.class_name }}(WebDriver driver) {
        this.driver = driver;
{% for op in baw.operations %}
{% for call in op.calls %}
        this.{{ call.component[:1].lower() }}{{ call.component[1:] }} = new {{ call.component }}(driver);
{% endfor %}
{% endfor %}
    }
{% for op in baw.operations %}
    public {{ baw.class_name }} {{ op.name }}({% for p in op.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
{% for call in op.calls %}
        {{ call.component[:1].lower() }}{{ call.component[1:] }}.{{ call.method }}({{ call.args|join(', ') }});
{% endfor %}
        return this;
    }
{% endfor %}
}
"""

FLUENT_TEST_TEMPLATE = """// [AUTO-GEN] {{ s.description or s.test_name }} — Fluent style
package {{ package }}.features;

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
    public void should{{ s.test_name|replace('test_', '') }}() {
{% for step in s.steps %}
        {{ step }}
{% endfor %}
    }
}
"""

FLUENT_DATA_BUILDER_TEMPLATE = """// [AUTO-GEN] Builder: {{ d.variable_name }}
package {{ package }}.builders;

public class {{ d.variable_name }} {
{% for field, info in d.fields.items() %}
    private {{ info.type }} {{ field }} = {{ info.value | repr }};
{% endfor %}

{% for field, info in d.fields.items() %}
    public {{ d.variable_name }} with{{ field[:1].upper() }}{{ field[1:] }}({{ info.type }} value) {
        this.{{ field }} = value;
        return this;
    }
{% endfor %}

    public {{ d.variable_name }} build() {
        return this;
    }
}
"""
