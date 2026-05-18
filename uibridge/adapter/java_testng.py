"""Java TestNG 适配器 — Java + TestNG + Maven + Page Object 模式"""

import re
from pathlib import Path
from typing import Optional

from .base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter,
    MethodTemplate, ComponentDef, PageComponent, PageDef,
    BAWDef, BAWOperationDef, CallDef,
    ImportStyle, FixtureStyle, AssertionStyle,
    ElementInfo, TestDataDef, ScriptDef,
    scan_java_source_for_package,
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

    def _get_aria_map(self) -> dict:
        if self.kb:
            for item in self.kb.store.list_category("conventions"):
                if "component_types" in item.key:
                    return item.value.get("aria_role_map", self.ARIA_MAP)
        return self.ARIA_MAP

    def resolve_type(self, aria_role: str, dom_attrs: dict, snapshot_context: str) -> str:
        aria_map = self._get_aria_map()
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
        domain = self._extract_domain(url)
        data_module = dom_attrs.get("data-module", "")
        if data_module:
            return self._java_class_name(data_module)
        role = aria_role or "element"
        return f"{self._java_class_name(domain)}{self._java_class_name(role)}"

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

    def _extract_domain(self, url: str) -> str:
        match = re.search(r'/(\w+)/(manage|list|create|edit|detail)', url)
        if match:
            return match.group(1)
        parts = url.rstrip("/").split("/")
        return parts[-1] if parts else "unknown"

    def _java_class_name(self, name: str) -> str:
        """将 snake_case / kebab-case 转为 PascalCase"""
        parts = re.split(r'[-_\s]', name)
        return "".join(p.capitalize() for p in parts if p)


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
        for ancestor in element_info.ancestor_chain:
            anc_attrs = ancestor.get("attrs", {})
            if "data-module" in anc_attrs:
                module = anc_attrs["data-module"]
                return f"//*[@data-module='{module}']//{element_info.tag}[@{self._best_attr(attrs)}='{attrs.get(self._best_attr(attrs))}']"
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
        if self.kb:
            kb_conventions = self.kb.get_locator_conventions()
            if kb_conventions and "priority" in kb_conventions:
                return kb_conventions["priority"]
        return self.PRIORITY

    def _best_attr(self, attrs: dict) -> str:
        for attr in ["id", "name", "data-testid"]:
            if attr in attrs and attrs[attr]:
                return attr
        return "class"


# ═══════════════════════════════════════════════════════════════
# JavaActionRecognizer
# ═══════════════════════════════════════════════════════════════

class JavaActionRecognizer(ActionRecognizer):
    """将 DOM 操作序列聚合为 Java Page Object 方法调用"""

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
        value = ""
        if isinstance(first, dict):
            t = first.get("target", {})
            if isinstance(t, dict):
                target_label = t.get("label", "")
            value = first.get("value", "")
        elif hasattr(first, 'target') and first.target:
            target_label = first.target.label or ""
            value = getattr(first, 'value', '') or ''

        base = {
            "raw_steps": list(buffer),
            "component": target_label.replace(" ", "_").lower() if target_label else "page",
            "value": value,
        }
        if action_type == "input" and len(buffer) >= 2:
            return {**base, "type": "composite_action", "action": "enterAndSubmit", "steps": len(buffer)}
        return {**base, "type": "single_action", "action": action_type, "steps": len(buffer)}

    def recognize_pattern(self, sequences: list) -> list[dict]:
        """PrefixSpan 频繁子序列挖掘"""
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
            pattern_key = " → ".join(pattern)
            patterns.append({
                "pattern": pattern_key,
                "actions": list(pattern),
                "frequency": count,
                "suggestion": f"Suggest wrapping into BusinessAW (appeared {count} times)",
            })
        return patterns


# ═══════════════════════════════════════════════════════════════
# JavaCodeGenerator
# ═══════════════════════════════════════════════════════════════

class JavaCodeGenerator(CodeGenerator):
    """生成 Java + TestNG/JUnit5 + Selenium 风格代码"""

    def __init__(self, kb_manager=None, package_name: Optional[str] = None,
                 base_page_class: str = "BasePage", test_framework: str = "testng"):
        self.kb = kb_manager
        if package_name is not None:
            self.package = package_name
        else:
            pkg = self._resolve_package()
            if pkg is None:
                self.package = "com.acme"
            else:
                self.package = pkg  # "" 表示默认包
        self.base_page = base_page_class
        self.test_framework = test_framework  # "testng" | "junit5" | "junit4"
        self._detect_framework()

    def _resolve_package(self) -> Optional[str]:
        """从 KB 或源码扫描检测项目包名。

        返回值：
        - 包名字符串：检测到统一包名
        - ""（空字符串）：默认包（无 package 声明）
        - None：无法检测
        """
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

        # 源码扫描兜底
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
                        pass

    def generate_component_aw(self, comp_def: ComponentDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        env.filters["repr"] = lambda v: repr(v)
        template = env.from_string(JAVA_COMPONENT_TEMPLATE)
        return self._post_process(template.render(comp=comp_def, package=self.package))

    def generate_business_aw(self, baw_def: BAWDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        template = env.from_string(JAVA_PAGE_OBJECT_TEMPLATE)
        return self._post_process(template.render(baw=baw_def, package=self.package))

    def generate_test_script(self, script_def: ScriptDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        if self.test_framework == "junit5":
            template = env.from_string(JAVA_JUNIT5_TEMPLATE)
        else:
            template = env.from_string(JAVA_TESTNG_TEMPLATE)
        return self._post_process(template.render(s=script_def, package=self.package,
                               framework=self.test_framework))

    def generate_test_data(self, data_def: TestDataDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        env.filters["repr"] = lambda v: repr(v)
        template = env.from_string(JAVA_TEST_DATA_TEMPLATE)
        return self._post_process(template.render(d=data_def, package=self.package))

    def get_import_style(self) -> ImportStyle:
        is_junit5 = self.test_framework == "junit5"
        test_imports = [
            "import org.junit.jupiter.api.Test;",
            "import org.junit.jupiter.api.BeforeEach;",
            "import org.junit.jupiter.api.AfterEach;",
        ] if is_junit5 else [
            "import org.testng.annotations.Test;",
            "import org.testng.annotations.BeforeMethod;",
        ]
        assert_import = "import static org.junit.jupiter.api.Assertions.*;" if is_junit5 else "import org.testng.Assert;"

        if self.kb:
            for item in self.kb.store.list_category("conventions"):
                if "import_style" in item.key:
                    examples = item.value.get("examples", [])
                    return ImportStyle(
                        from_imports=examples + [
                            f"import {self.package}.pages.HomePage;",
                            f"import {self.package}.components.WebInput;",
                            f"import {self.package}.components.WebButton;",
                        ],
                        direct_imports=[
                            *test_imports,
                            "import org.openqa.selenium.WebDriver;",
                            "import org.openqa.selenium.chrome.ChromeDriver;",
                            assert_import,
                        ],
                    )
        return ImportStyle(
            from_imports=[
                f"import {self.package}.pages.HomePage;",
                f"import {self.package}.components.WebInput;",
                f"import {self.package}.components.WebButton;",
            ],
            direct_imports=[
                *test_imports,
                "import org.openqa.selenium.WebDriver;",
                "import org.openqa.selenium.chrome.ChromeDriver;",
                assert_import,
            ],
        )

    def get_assertion_style(self) -> AssertionStyle:
        if self.kb:
            for item in self.kb.store.list_category("conventions"):
                if "assertion_style" in item.key:
                    return AssertionStyle(type=item.value.get("type", "testng_assert"))
        return AssertionStyle(type="testng_assert")

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
            return "Assert.assertNotNull(page);"

        comment = getattr(step, 'comment', '')
        if comment:
            return f"// {comment}"
        return ""


# ═══════════════════════════════════════════════════════════════
# JavaDataFormatter
# ═══════════════════════════════════════════════════════════════

class JavaDataFormatter(DataFormatter):
    """录制值 → Java 测试数据常量类"""

    def __init__(self, kb_manager=None, package_name: Optional[str] = None):
        self.kb = kb_manager
        if package_name is not None:
            self.package = package_name
        else:
            pkg = self._resolve_package()
            if pkg is None:
                self.package = "com.acme"
            else:
                self.package = pkg

    def _resolve_package(self) -> Optional[str]:
        """从 KB 或源码扫描检测项目包名。"""
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

    def format(self, captured_values: dict, data_context: dict) -> TestDataDef:
        domain = data_context.get("domain", "unknown")
        class_name = f"{self._java_class_name(domain)}TestData"
        fields = {}
        for key, value in captured_values.items():
            java_type = self._infer_java_type(value)
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
        class_name = f"{self._java_class_name(domain)}TestData"
        if self.package:
            return f"import {self.package}.data.{class_name};"
        return f"import data.{class_name};"

    def _java_class_name(self, name: str) -> str:
        parts = re.split(r'[-_\s]', name)
        return "".join(p.capitalize() for p in parts if p)

    def _infer_java_type(self, value) -> str:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "double"
        return "String"


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
