"""Playwright Java TestNG 适配器 — Playwright + Java + TestNG + Maven + 四层分层架构

Component AW → Business AW → Test Data → Test Scripts
每一层都使用 Playwright 语义，而非 Selenium。
"""

import re
from pathlib import Path
from typing import Optional

from jinja2 import Environment, BaseLoader

from .base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter,
    MethodTemplate, ComponentDef, PageComponent, PageDef,
    BAWDef, BAWOperationDef, CallDef,
    ImportStyle, FixtureStyle, AssertionStyle,
    ElementInfo, TestDataDef, ScriptDef,
    scan_java_source_for_package,
    sanitize_identifier,
    _to_java_type,
    to_java_class_name,
    post_process_java_code,
    format_action_params,
)

_JINJA_ENV = Environment(loader=BaseLoader())
_DOMAIN_RE = re.compile(r'/(\w+)/(manage|list|create|edit|detail)')


# ═══════════════════════════════════════════════════════════════
# PlaywrightComponentResolver
# ═══════════════════════════════════════════════════════════════

class PlaywrightComponentResolver(ComponentResolver):
    """ARIA role → Playwright 风格的 ComponentAW 类型"""

    ARIA_MAP = {
        "table": "TableAW", "grid": "TableAW", "treegrid": "TableAW",
        "form": "FormAW", "dialog": "DialogAW",
        "combobox": "DropdownAW", "listbox": "DropdownAW",
        "menu": "MenuAW", "menubar": "MenuAW",
        "tablist": "TabAW", "tree": "TreeAW",
        "navigation": "NavAW",
        "button": "ButtonAW", "link": "LinkAW",
        "textbox": "InputAW", "searchbox": "SearchBoxAW",
        "checkbox": "CheckboxAW", "radio": "RadioAW",
        "alert": "AlertAW", "banner": "BannerAW",
    }

    METHOD_TEMPLATES = {
        "TableAW": [
            MethodTemplate("waitForLoad", [], "wait"),
            MethodTemplate("clickRow", [{"name": "index", "type": "int"}], "click"),
            MethodTemplate("getRowCount", [], "read", "int"),
            MethodTemplate("getCellText", [{"name": "row", "type": "int"}, {"name": "col", "type": "int"}], "read", "String"),
            MethodTemplate("assertRowContains", [{"name": "text", "type": "String"}], "assertion"),
        ],
        "FormAW": [
            MethodTemplate("waitForLoad", [], "wait"),
            MethodTemplate("submit", [], "click"),
            MethodTemplate("reset", [], "click"),
        ],
        "InputAW": [
            MethodTemplate("fill", [{"name": "text", "type": "String"}], "input"),
            MethodTemplate("type", [{"name": "text", "type": "String"}], "input"),
            MethodTemplate("clear", [], "input"),
            MethodTemplate("getValue", [], "read", "String"),
            MethodTemplate("assertHasValue", [{"name": "expected", "type": "String"}], "assertion"),
        ],
        "SearchBoxAW": [
            MethodTemplate("search", [{"name": "keyword", "type": "String"}], "input"),
            MethodTemplate("typeKeyword", [{"name": "keyword", "type": "String"}], "input"),
            MethodTemplate("clickSearch", [], "click"),
        ],
        "ButtonAW": [
            MethodTemplate("click", [], "click"),
            MethodTemplate("dblClick", [], "click"),
            MethodTemplate("assertEnabled", [], "assertion"),
            MethodTemplate("assertDisabled", [], "assertion"),
        ],
        "DropdownAW": [
            MethodTemplate("selectOption", [{"name": "value", "type": "String"}], "select"),
            MethodTemplate("getSelected", [], "read", "String"),
            MethodTemplate("assertSelected", [{"name": "expected", "type": "String"}], "assertion"),
        ],
        "DialogAW": [
            MethodTemplate("waitForVisible", [], "wait"),
            MethodTemplate("confirm", [], "click"),
            MethodTemplate("cancel", [], "click"),
            MethodTemplate("getMessage", [], "read", "String"),
        ],
        "MenuAW": [
            MethodTemplate("clickItem", [{"name": "label", "type": "String"}], "click"),
        ],
        "TabAW": [
            MethodTemplate("select", [{"name": "tabName", "type": "String"}], "click"),
            MethodTemplate("assertSelected", [{"name": "tabName", "type": "String"}], "assertion"),
        ],
        "LinkAW": [
            MethodTemplate("click", [], "click"),
            MethodTemplate("getUrl", [], "read", "String"),
        ],
        "CheckboxAW": [
            MethodTemplate("check", [], "click"),
            MethodTemplate("uncheck", [], "click"),
            MethodTemplate("isChecked", [], "read", "boolean"),
            MethodTemplate("assertChecked", [], "assertion"),
        ],
        "RadioAW": [
            MethodTemplate("select", [{"name": "value", "type": "String"}], "click"),
            MethodTemplate("assertSelected", [{"name": "expected", "type": "String"}], "assertion"),
        ],
        "AlertAW": [
            MethodTemplate("getText", [], "read", "String"),
            MethodTemplate("accept", [], "click"),
            MethodTemplate("dismiss", [], "click"),
        ],
        "NavAW": [
            MethodTemplate("goTo", [{"name": "section", "type": "String"}], "click"),
        ],
        "TreeAW": [
            MethodTemplate("expand", [{"name": "node", "type": "String"}], "click"),
            MethodTemplate("clickNode", [{"name": "label", "type": "String"}], "click"),
        ],
        "BannerAW": [
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
            "input": "InputAW", "select": "DropdownAW",
            "button": "ButtonAW", "a": "LinkAW",
            "textarea": "InputAW", "table": "TableAW",
        }
        return tag_map.get(tag, "BaseComponentAW")

    def suggest_name(self, url: str, aria_role: str, dom_attrs: dict) -> str:
        domain = self._extract_domain(url)
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
            return "TableAW"
        if any(k in lower for k in ("form", "edit", "create")):
            return "FormAW"
        if any(k in lower for k in ("select", "dropdown", "combo", "picker")):
            return "DropdownAW"
        if any(k in lower for k in ("dialog", "modal", "popup")):
            return "DialogAW"
        return self.ARIA_MAP.get(aria_role, "BaseComponentAW")

    def _extract_domain(self, url: str) -> str:
        match = _DOMAIN_RE.search(url)
        if match:
            return match.group(1)
        parts = url.rstrip("/").split("/")
        return parts[-1] if parts else "unknown"


# ═══════════════════════════════════════════════════════════════
# PlaywrightLocatorStrategy
# ═══════════════════════════════════════════════════════════════

class PlaywrightLocatorStrategy(LocatorStrategy):
    """Playwright 定位策略: page.locator() + CSS/text/role 选择器"""

    PRIORITY = ["id", "placeholder", "aria-label", "text", "css", "xpath"]

    def build_xpath(self, element_info: ElementInfo, dom_context: dict) -> str:
        """生成 Playwright 定位字符串（优先 CSS/text，其次 xpath）"""
        attrs = element_info.attrs

        # 1. 向上查找最近的 data-module 祖先
        for ancestor in element_info.ancestor_chain:
            anc_attrs = ancestor.get("attrs", {})
            if "data-module" in anc_attrs:
                module = anc_attrs["data-module"]
                best = self._best_attr(attrs)
                if best and attrs.get(best):
                    return f"[data-module='{module}'] [{best}='{attrs[best]}']"
                return f"[data-module='{module}']"

        # id 优先
        if "id" in attrs and attrs["id"]:
            return f"#{attrs['id']}"

        # data-testid
        if "data-testid" in attrs and attrs["data-testid"]:
            return f"[data-testid='{attrs['data-testid']}']"

        # name
        if "name" in attrs and attrs["name"]:
            return f"[name='{attrs['name']}']"

        # placeholder
        if "placeholder" in attrs and attrs["placeholder"]:
            return f"[placeholder='{attrs['placeholder']}']"

        # aria-label
        if "aria-label" in attrs and attrs["aria-label"]:
            return f"[aria-label='{attrs['aria-label']}']"

        # 文本定位 — Playwright 特色
        if element_info.text and len(element_info.text) < 50:
            return f'text="{element_info.text}"'

        # 类名
        if "class" in attrs and attrs["class"]:
            classes = attrs["class"].split()
            if classes:
                return f".{classes[0]}"

        return ""

    def _best_attr(self, attrs: dict) -> str:
        for attr in ["data-testid", "id", "name", "placeholder", "aria-label"]:
            if attr in attrs and attrs[attr]:
                return attr
        return ""

    def extract_feature_point(self, selector: str) -> dict:
        if selector.startswith("#"):
            return {"type": "id", "value": selector[1:]}
        if selector.startswith("[data-testid="):
            return {"type": "data-testid", "value": selector.split("=")[1].strip("[]'\"")}
        if selector.startswith("[name="):
            return {"type": "name", "value": selector.split("=")[1].strip("[]'\"")}
        if selector.startswith("text="):
            return {"type": "text", "value": selector[5:].strip('"')}
        if selector.startswith("."):
            return {"type": "class", "value": selector[1:]}
        return {"type": "selector", "value": selector}

    def get_locator_priority(self) -> list[str]:
        return self._resolve_locator_priority()


# ═══════════════════════════════════════════════════════════════
# PlaywrightActionRecognizer
# ═══════════════════════════════════════════════════════════════

class PlaywrightActionRecognizer(ActionRecognizer):
    """DOM 操作序列 → Playwright 方法调用聚合"""

    def aggregate(self, raw_steps: list, page_context: dict) -> list:
        actions = []
        buffer = []
        current_type = None

        for step in raw_steps:
            if isinstance(step, dict):
                step_type = step.get("action", "")
            else:
                step_type = step.action.value if hasattr(step.action, "value") else str(step.action)

            if step_type == "navigate":
                if buffer:
                    actions.append(self._aggregate_buffer(buffer, current_type))
                    buffer = []
                current_type = "navigation"
                buffer.append(step)
            elif step_type in ("input", "fill"):
                if current_type == "click":
                    actions.append(self._aggregate_buffer(buffer, current_type))
                    buffer = []
                buffer.append(step)
                current_type = "input"
            elif step_type == "click":
                if current_type == "input":
                    buffer.append(step)
                else:
                    if buffer:
                        actions.append(self._aggregate_buffer(buffer, current_type))
                        buffer = []
                    buffer.append(step)
                current_type = "click"
            else:
                if buffer:
                    actions.append(self._aggregate_buffer(buffer, current_type))
                    buffer = []
                buffer.append(step)
                current_type = step_type

        if buffer:
            actions.append(self._aggregate_buffer(buffer, current_type))
        return actions

    def _aggregate_buffer(self, buffer: list, action_type: str) -> dict:
        if not buffer:
            return {}
        first = buffer[0]
        target_label = ""
        target_tag = ""
        value = ""
        if isinstance(first, dict):
            t = first.get("target", {})
            if isinstance(t, dict):
                target_label = t.get("label", "")
                target_tag = t.get("tag", "")
            value = first.get("value", "")
        elif hasattr(first, 'target') and first.target:
            target_label = first.target.label or ""
            target_tag = first.target.tag or ""
            value = getattr(first, 'value', '') or ''

        base = {
            "raw_steps": list(buffer),
            "component": sanitize_identifier(target_label, fallback_tag=target_tag or "page") if target_label else "page",
            "value": value,
        }
        if action_type == "input" and len(buffer) >= 2:
            return {**base, "type": "composite_action", "action": "fillAndSubmit", "steps": len(buffer)}
        return {**base, "type": "single_action", "action": action_type, "steps": len(buffer)}

    def recognize_pattern(self, sequences: list) -> list[dict]:
        patterns = super().recognize_pattern(sequences)
        for p in patterns:
            p["suggestion"] = f"建议包装为 BusinessAW（出现 {p['frequency']} 次）"
        return patterns


# ═══════════════════════════════════════════════════════════════
# PlaywrightCodeGenerator
# ═══════════════════════════════════════════════════════════════

class PlaywrightCodeGenerator(CodeGenerator):
    """生成 Playwright + Java + TestNG 风格代码，融入四层分层架构"""
    target_language = "java"
    default_base_class = "BaseComponentAW"

    def __init__(self, kb_manager=None, package_name: Optional[str] = None,
                 base_page_class: str = "BasePage", test_framework: str = "testng"):
        self.kb = kb_manager
        if package_name is not None:
            self.package = package_name
        else:
            pkg = self._resolve_package()
            self.package = pkg if pkg is not None else "com.enterprise.test"
        self.base_page = base_page_class
        self.test_framework = test_framework

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

    # ── 四个生成方法 ──────────────────────────

    def generate_component_aw(self, comp_def: ComponentDef) -> str:
        _JINJA_ENV.filters["repr"] = lambda v: repr(v)
        template = _JINJA_ENV.from_string(PLAYWRIGHT_COMPONENT_TEMPLATE)
        return post_process_java_code(template.render(comp=comp_def, package=self.package), self.package)

    def generate_business_aw(self, baw_def: BAWDef) -> str:
        template = _JINJA_ENV.from_string(PLAYWRIGHT_PAGE_TEMPLATE)
        return post_process_java_code(template.render(baw=baw_def, package=self.package), self.package)

    def generate_test_script(self, script_def: ScriptDef) -> str:
        template = _JINJA_ENV.from_string(PLAYWRIGHT_TESTNG_TEMPLATE)
        return post_process_java_code(template.render(s=script_def, package=self.package,
                                                  framework=self.test_framework), self.package)

    def generate_test_data(self, data_def: TestDataDef) -> str:
        _JINJA_ENV.filters["repr"] = lambda v: repr(v)
        template = _JINJA_ENV.from_string(PLAYWRIGHT_TEST_DATA_TEMPLATE)
        return post_process_java_code(template.render(d=data_def, package=self.package), self.package)

    def get_import_style(self) -> ImportStyle:
        test_imports = [
            "import org.testng.annotations.Test;",
            "import org.testng.annotations.BeforeMethod;",
        ]
        assert_import = "import org.testng.Assert;"

        return ImportStyle(
            from_imports=[
                f"import {self.package}.pages.*;",
                f"import {self.package}.components.*;",
                f"import {self.package}.business.*;",
            ],
            direct_imports=[
                f"import {self.package}.tests.BaseTest;",
                "import com.microsoft.playwright.Page;",
                "import com.microsoft.playwright.Locator;",
                *test_imports,
                assert_import,
            ],
        )

    def get_assertion_style(self) -> AssertionStyle:
        return AssertionStyle(type="testng_assert")

    def render_step(self, step) -> str:
        """Playwright Java 风格步骤渲染"""
        kind = getattr(step, 'kind', None)
        decl = getattr(step, 'decl', None)

        if kind and kind.value == "decl" and decl:
            return f"{decl.type} {decl.var} = new {decl.type}(page);"

        if kind and kind.value == "navigate" and step.calls:
            url = step.calls[0].args[0] if step.calls[0].args else ""
            return f'page.navigate("{url}");'

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

    def _render_assertion(self, candidate: str) -> str:
        from uibridge.adapter.base import parse_assertion_candidate
        p = parse_assertion_candidate(candidate)
        atype = p.get("type", "unknown")
        if atype == "url_equals":
            return f'Assert.assertEquals(page.url(), "{p["url"]}");'
        elif atype == "element_visible":
            return f'Assert.assertTrue(page.isVisible("[data-module=\'{p["element"]}\']"), "{p["element"]} should be visible");'
        elif atype == "element_absent":
            return f'Assert.assertFalse(page.isVisible("[data-module=\'{p["element"]}\']"), "{p["element"]} should be absent");'
        elif atype == "text_equals":
            return f'Assert.assertEquals(page.locator("[data-module=\'{p["element"]}\']").textContent(), "{p["text"]}");'
        elif atype == "count_changed":
            return f'// {p["role"]} count should be {p["direction"]}'
        elif atype == "layout_stable":
            return f'// assert layout of \'{p["element"]}\' is stable'
        elif atype == "generic":
            msg = p.get("message", candidate)
            return f'// verify: {msg}'
        else:
            return f'Assert.assertNotNull(page); // TODO: assert {candidate}'

        comment = getattr(step, 'comment', '')
        if comment:
            return f"// {comment}"
        return ""


# ═══════════════════════════════════════════════════════════════
# PlaywrightDataFormatter
# ═══════════════════════════════════════════════════════════════

class PlaywrightDataFormatter(DataFormatter):
    """录制值 → Java TestNG DataProvider 测试数据类"""

    def __init__(self, kb_manager=None, package_name: Optional[str] = None):
        self.kb = kb_manager
        if package_name is not None:
            self.package = package_name
        else:
            pkg = self._resolve_package()
            self.package = pkg if pkg is not None else "com.enterprise.test"

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
# Jinja2 模板 — Playwright Java 代码输出
# ═══════════════════════════════════════════════════════════════

PLAYWRIGHT_COMPONENT_TEMPLATE = """// [AUTO-GEN] Component: {{ comp.class_name }}
package {{ package }}.components;

import com.microsoft.playwright.Locator;
import com.microsoft.playwright.Page;

import static com.microsoft.playwright.assertions.PlaywrightAssertions.assertThat;

/**
 * {{ comp.class_name }} — auto-generated Playwright component wrapper.
 */
public class {{ comp.class_name }} extends {{ comp.base_class }} {

    public {{ comp.class_name }}(Page page, String description) {
        super(page.locator("{{ comp.xpath }}"), description);
    }

{% for method in comp.methods %}
{% if method.action_type == 'wait' %}
    public {{ comp.class_name }} {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        locator.waitFor();
        return this;
    }
{% elif method.action_type == 'click' %}
    public {{ comp.class_name }} {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        locator.click();
        return this;
    }
{% elif method.action_type == 'input' %}
    public {{ comp.class_name }} {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        locator.fill({{ method.params[0].name }});
        return this;
    }
{% elif method.action_type == 'select' %}
    public {{ comp.class_name }} {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        locator.selectOption({{ method.params[0].name }});
        return this;
    }
{% elif method.action_type == 'read' %}
    public {{ method.returns }} {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        return locator.textContent();
    }
{% elif method.action_type == 'assertion' %}
    public {{ comp.class_name }} {{ method.name }}({% for p in method.params %}{{ p.type }} {{ p.name }}{% if not loop.last %}, {% endif %}{% endfor %}) {
        assertThat(locator).isVisible();
        return this;
    }
{% endif %}
{% endfor %}
}
"""

PLAYWRIGHT_PAGE_TEMPLATE = """// [AUTO-GEN] Page: {{ baw.class_name }}
package {{ package }}.pages;

import com.microsoft.playwright.Page;
{% for op in baw.operations %}
{% for call in op.calls %}
import {{ package }}.components.{{ call.component }};
{% endfor %}
{% endfor %}

/**
 * {{ baw.class_name }} — auto-generated page object.
 */
public class {{ baw.class_name }} extends BasePage<{{ baw.class_name }}> {

{% for op in baw.operations %}
{% for call in op.calls %}
    public final {{ call.component }} {{ call.component[:1].lower() }}{{ call.component[1:] }};
{% endfor %}
{% endfor %}

    public {{ baw.class_name }}(Page page) {
        super(page, "{{ baw.module }}");
{% for op in baw.operations %}
{% for call in op.calls %}
        this.{{ call.component[:1].lower() }}{{ call.component[1:] }} = new {{ call.component }}(page, "{{ call.component }}");
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

    @Override
    public {{ baw.class_name }} assertPageLoaded() {
{% for op in baw.operations %}
{% for call in op.calls %}
        {{ call.component[:1].lower() }}{{ call.component[1:] }}.assertVisible();
{% endfor %}
{% endfor %}
        return this;
    }
}
"""

PLAYWRIGHT_TESTNG_TEMPLATE = """// [AUTO-GEN] {{ s.description or s.test_name }}
package {{ package }}.tests;

{% for imp in s.imports %}
{{ imp }}
{% endfor %}
import {{ package }}.pages.*;
import {{ package }}.data.*;

public class {{ s.class_name }} extends BaseTest {

    @Test{% if s.data_refs %}(dataProvider = "{{ s.test_name }}Data", dataProviderClass = {{ s.class_name }}Data.class){% endif %}
    public void {{ s.test_name }}() {
{% for step in s.steps %}
        {{ step }}
{% endfor %}
    }
}
"""

PLAYWRIGHT_TEST_DATA_TEMPLATE = """// [AUTO-GEN] Test Data: {{ d.variable_name }}
package {{ package }}.data;

import org.testng.annotations.DataProvider;

public class {{ d.variable_name }} {
{% for field, info in d.fields.items() %}
    public static final {{ info.type }} {{ field.upper() }} = {{ info.value | repr }};
{% endfor %}

    @DataProvider(name = "{{ d.variable_name[:1].lower() }}{{ d.variable_name[1:] }}")
    public static Object[][] {{ d.variable_name[:1].lower() }}{{ d.variable_name[1:] }}() {
        return new Object[][]{
{% for field, info in d.fields.items() %}
                { {{ info.value | repr }} },
{% endfor %}
        };
    }
}
"""
