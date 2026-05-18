"""Java Fluent 适配器 — Java + TestNG + PageFactory + AssertJ 流式模式"""

import re
from typing import Optional

from .base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter,
    MethodTemplate, ComponentDef,
    BAWDef, CallDef,
    ImportStyle, AssertionStyle,
    ElementInfo, TestDataDef, ScriptDef,
    scan_java_source_for_package,
)


class FluentComponentResolver(ComponentResolver):
    """PageFactory: 所有组件用 @FindBy 定位，统一为 PageElement"""

    ARIA_MAP = {
        "table": "PageElement", "grid": "PageElement",
        "form": "PageElement", "dialog": "PageElement",
        "combobox": "PageElement", "listbox": "PageElement",
        "textbox": "PageElement", "searchbox": "PageElement",
        "button": "PageElement", "link": "PageElement",
    }

    METHOD_TEMPLATES = {
        "PageElement": [
            MethodTemplate("click", [], "click"),
            MethodTemplate("enter", [{"name": "text", "type": "String"}], "input"),
            MethodTemplate("getText", [], "read", "String"),
            MethodTemplate("shouldBeVisible", [], "assertion"),
            MethodTemplate("shouldContain", [{"name": "text", "type": "String"}], "assertion"),
        ],
    }

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def resolve_type(self, aria_role: str, dom_attrs: dict, snapshot_context: str) -> str:
        return "PageElement"

    def suggest_name(self, url: str, aria_role: str, dom_attrs: dict) -> str:
        data_module = dom_attrs.get("data-module", "")
        if data_module:
            return re.sub(r'[-_\s]', '', data_module).upper()
        domain = self._extract_domain(url)
        return f"{domain.upper()}_{aria_role.upper()}" if aria_role else "PAGE_ELEMENT"

    def get_methods_for_role(self, component_type: str, aria_role: str) -> list[MethodTemplate]:
        return self.METHOD_TEMPLATES.get("PageElement", [])

    def _extract_domain(self, url: str) -> str:
        match = re.search(r'/(\w+)/(manage|list|create)', url)
        return match.group(1) if match else "unknown"


class FluentLocatorStrategy(LocatorStrategy):
    """Fluent: @FindBy 注解，css 和 xpath 优先"""

    PRIORITY = ["css", "xpath", "id", "data-test"]

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def build_xpath(self, element_info: ElementInfo, dom_context: dict) -> str:
        attrs = element_info.attrs
        if "id" in attrs and attrs["id"]:
            return f"#{attrs['id']}"
        for attr in ["data-test", "data-testid"]:
            if attr in attrs and attrs[attr]:
                return f"[{attr}='{attrs[attr]}']"
        if "name" in attrs and attrs["name"]:
            return f"*[name='{attrs['name']}']"
        return ""

    def extract_feature_point(self, xpath: str) -> dict:
        for attr in ["id", "data-test", "data-testid", "name"]:
            match = re.search(rf"\[?{attr}='([^']+)'\]?", xpath)
            if match:
                return {"type": attr, "value": match.group(1)}
        return {"type": "css", "value": xpath}

    def get_locator_priority(self) -> list[str]:
        if self.kb:
            kb_conventions = self.kb.get_locator_conventions()
            if kb_conventions and "priority" in kb_conventions:
                return kb_conventions["priority"]
        return self.PRIORITY


class FluentActionRecognizer(ActionRecognizer):
    """Fluent: DOM 操作 → 返回 this 的链式方法"""

    def aggregate(self, raw_steps: list, page_context: dict) -> list:
        actions = []
        for step in raw_steps:
            if isinstance(step, dict):
                step_type = step.get("action", "")
            else:
                step_type = step.action.value if hasattr(step.action, "value") else str(step.action)

            target_label = ""
            value = ""
            if isinstance(step, dict):
                t = step.get("target", {})
                if isinstance(t, dict):
                    target_label = t.get("label", "")
                value = step.get("value", "")
            elif hasattr(step, 'target') and step.target:
                target_label = step.target.label or ""
                value = getattr(step, 'value', '') or ''

            base = {
                "raw_steps": [step],
                "component": target_label.replace(" ", "_").lower() if target_label else "page",
                "value": value,
            }
            if step_type == "input":
                actions.append({**base, "type": "fluent_action", "action": "enterAndContinue"})
            elif step_type == "click":
                actions.append({**base, "type": "fluent_action", "action": "clickAndContinue"})
            elif step_type == "navigate":
                actions.append({**base, "type": "fluent_action", "action": "navigateTo"})
            elif step_type:
                actions.append({**base, "type": "fluent_action", "action": step_type})
        return actions

    def recognize_pattern(self, sequences: list) -> list[dict]:
        if len(sequences) < 3:
            return []
        action_seqs = []
        for seq in sequences:
            actions = []
            if isinstance(seq, list):
                for item in seq:
                    if isinstance(item, dict):
                        actions.append(item.get("action", "?"))
                    else:
                        actions.append(str(item))
            action_seqs.append(actions)
        from ..adapter.base import _PrefixSpan
        miner = _PrefixSpan(min_support=3, max_length=8)
        frequent_patterns = miner.mine(action_seqs)
        patterns = []
        for pattern, count in frequent_patterns:
            patterns.append({
                "pattern": " → ".join(pattern),
                "actions": list(pattern),
                "frequency": count,
            })
        return patterns


class FluentCodeGenerator(CodeGenerator):
    """生成 Fluent API + PageFactory + AssertJ 风格"""

    def __init__(self, kb_manager=None, package_name: Optional[str] = None):
        self.kb = kb_manager
        if package_name is not None:
            self.package = package_name
        else:
            pkg = self._resolve_package()
            if pkg is None:
                self.package = "com.fluent"
            else:
                self.package = pkg

    def _resolve_package(self) -> Optional[str]:
        packages: set[str] = set()
        if self.kb:
            for item in self.kb.store.list_category("conventions"):
                if "package" in item.key:
                    pkg = item.value.get("package", "") if isinstance(item.value, dict) else ""
                    if pkg:
                        packages.add(pkg)
            if not packages:
                for item in self.kb.store.list_category("components"):
                    key = item.key
                    if key.startswith("java.") and "." in key[key.index("java.") + 5:]:
                        pkg_parts = key.replace("java.", "").rsplit(".", 1)
                        if len(pkg_parts) > 1:
                            packages.add(pkg_parts[0])
            if packages:
                parts_list = [p.split(".") for p in packages]
                common = parts_list[0]
                for p in parts_list[1:]:
                    i = 0
                    while i < min(len(common), len(p)) and common[i] == p[i]:
                        i += 1
                    common = common[:i]
                if common:
                    return ".".join(common)

        if self.kb and hasattr(self.kb, 'project_root'):
            result = scan_java_source_for_package(str(self.kb.project_root))
            if result is not None:
                return result

        return None

    def _post_process(self, code: str) -> str:
        """后处理：默认包时移除 package 行和项目内 import。"""
        if self.package:
            return code
        code = re.sub(r'^\s*package\s+\.[^;]+;\s*\n?', '', code, flags=re.MULTILINE)
        code = re.sub(r'^\s*import\s+\.[^;]+;\s*\n?', '', code, flags=re.MULTILINE)
        code = re.sub(r'\n{3,}', '\n\n', code)
        return code.strip() + '\n'

    def generate_component_aw(self, comp_def: ComponentDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        template = env.from_string(FLUENT_ELEMENT_TEMPLATE)
        return self._post_process(template.render(comp=comp_def, package=self.package))

    def generate_business_aw(self, baw_def: BAWDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        template = env.from_string(FLUENT_PAGE_TEMPLATE)
        return self._post_process(template.render(baw=baw_def, package=self.package))

    def generate_test_script(self, script_def: ScriptDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        template = env.from_string(FLUENT_TEST_TEMPLATE)
        return self._post_process(template.render(s=script_def, package=self.package))

    def generate_test_data(self, data_def: TestDataDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        env.filters["repr"] = lambda v: repr(v)
        template = env.from_string(FLUENT_DATA_BUILDER_TEMPLATE)
        return self._post_process(template.render(d=data_def, package=self.package))

    def get_import_style(self) -> ImportStyle:
        if self.kb:
            for item in self.kb.store.list_category("conventions"):
                if "import_style" in item.key:
                    examples = item.value.get("examples", [])
                    return ImportStyle(
                        from_imports=examples + [
                            f"import {self.package}.pages.HomePage;",
                        ],
                        direct_imports=[
                            "import org.testng.annotations.Test;",
                            "import org.testng.annotations.BeforeMethod;",
                            "import org.openqa.selenium.WebDriver;",
                            "import static org.assertj.core.api.Assertions.assertThat;",
                        ],
                    )
        return ImportStyle(
            from_imports=[f"import {self.package}.pages.HomePage;"],
            direct_imports=[
                "import org.testng.annotations.Test;",
                "import org.testng.annotations.BeforeMethod;",
                "import org.openqa.selenium.WebDriver;",
                "import static org.assertj.core.api.Assertions.assertThat;",
            ],
        )

    def get_assertion_style(self) -> AssertionStyle:
        return AssertionStyle(type="assertj")

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
            parts = []
            for a in call.args:
                parts.append(f'"{a}"' if isinstance(a, str) else str(a))
            for k, v in call.kwargs.items():
                parts.append(f'"{v}"' if isinstance(v, str) else str(v))
            args_str = ", ".join(parts)
            if args_str:
                return f"{component}.{method}({args_str});"
            return f"{component}.{method}();"

        if kind and kind.value == "assert" and step.calls:
            msg = step.calls[0].args[0] if step.calls[0].args else step.comment
            if msg:
                return f"// assert: {msg}";
            return "assertThat(page).isNotNull();"

        comment = getattr(step, 'comment', '')
        if comment:
            return f"// {comment}"
        return ""


class FluentDataFormatter(DataFormatter):
    """Fluent: Builder 模式而不是常量类"""

    def __init__(self, kb_manager=None, package_name: Optional[str] = None):
        self.kb = kb_manager
        if package_name is not None:
            self.package = package_name
        else:
            pkg = self._resolve_package()
            if pkg is None:
                self.package = "com.fluent"
            else:
                self.package = pkg

    def _resolve_package(self) -> Optional[str]:
        packages: set[str] = set()
        if self.kb:
            for item in self.kb.store.list_category("conventions"):
                if "package" in item.key:
                    pkg = item.value.get("package", "") if isinstance(item.value, dict) else ""
                    if pkg:
                        packages.add(pkg)
            if packages:
                parts_list = [p.split(".") for p in packages]
                common = parts_list[0]
                for p in parts_list[1:]:
                    i = 0
                    while i < min(len(common), len(p)) and common[i] == p[i]:
                        i += 1
                    common = common[:i]
                if common:
                    return ".".join(common)

        if self.kb and hasattr(self.kb, 'project_root'):
            result = scan_java_source_for_package(str(self.kb.project_root))
            if result is not None:
                return result

        return None

    def format(self, captured_values: dict, data_context: dict) -> TestDataDef:
        domain = data_context.get("domain", "unknown")
        class_name = f"{self._java_class_name(domain)}Builder"
        fields = {}
        for key, value in captured_values.items():
            java_type = "String" if isinstance(value, str) else type(value).__name__
            fields[key] = {"value": value, "type": java_type}
        return TestDataDef(
            file_path=f"src/test/java/builders/{class_name}.java",
            variable_name=class_name,
            fields=fields,
        )

    def get_data_ref_style(self, domain: str) -> str:
        class_name = f"{self._java_class_name(domain)}Builder"
        if self.package:
            return f"import {self.package}.builders.{class_name};"
        return f"import builders.{class_name};"

    def _java_class_name(self, name: str) -> str:
        parts = re.split(r'[-_\s]', name)
        return "".join(p.capitalize() for p in parts if p)


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
