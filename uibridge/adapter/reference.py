"""参考适配器实现 — ComponentAW + BusinessAW + TestData 模式"""

import re

from .base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter,
    MethodTemplate, ComponentDef, PageComponent, PageDef,
    BAWDef, BAWOperationDef, CallDef,
    ImportStyle, FixtureStyle, AssertionStyle,
    ElementInfo, TestDataDef, ScriptDef,
)


# ═══════════════════════════════════════════════════════════════
# ComponentResolver 参考实现
# ═══════════════════════════════════════════════════════════════

class ReferenceComponentResolver(ComponentResolver):
    """基于 ARIA role + data-module 的组件类型解析，优先从 KB 查询"""

    # Hardcoded defaults — used when KB is not available
    ARIA_MAP = {
        "table": "TableAW", "grid": "TableAW", "treegrid": "TableAW",
        "form": "FormAW", "dialog": "DialogAW",
        "combobox": "DropdownAW", "listbox": "DropdownAW",
        "menu": "MenuAW", "menubar": "MenuAW",
        "tablist": "TabAW", "tree": "TreeAW",
        "navigation": "NavAW",
        "button": "ButtonAW", "link": "LinkAW",
        "textbox": "InputAW", "searchbox": "InputAW",
        "checkbox": "CheckboxAW", "radio": "RadioAW",
    }

    METHOD_TEMPLATES = {
        "TableAW": [
            MethodTemplate("wait_loaded", [], "wait"),
            MethodTemplate("click_row", [{"name": "index", "type": "int"}], "click"),
            MethodTemplate("get_row_count", [], "read", "int"),
            MethodTemplate("get_cell_text", [{"name": "row", "type": "int"}, {"name": "col", "type": "int"}], "read", "str"),
            MethodTemplate("assert_row_contains", [{"name": "text", "type": "str"}], "assertion"),
            MethodTemplate("filter_by_column", [{"name": "col", "type": "int"}, {"name": "value", "type": "str"}], "input"),
            MethodTemplate("select_all", [], "click"),
        ],
        "FormAW": [
            MethodTemplate("wait_loaded", [], "wait"),
            MethodTemplate("submit", [], "click"),
            MethodTemplate("reset", [], "click"),
            MethodTemplate("assert_field_error", [{"name": "field", "type": "str"}], "assertion"),
        ],
        "InputAW": [
            MethodTemplate("enter", [{"name": "text", "type": "str"}], "input"),
            MethodTemplate("clear", [], "input"),
            MethodTemplate("get_value", [], "read", "str"),
            MethodTemplate("assert_value", [{"name": "expected", "type": "str"}], "assertion"),
        ],
        "ButtonAW": [
            MethodTemplate("click", [], "click"),
            MethodTemplate("assert_enabled", [], "assertion"),
            MethodTemplate("assert_disabled", [], "assertion"),
        ],
        "DropdownAW": [
            MethodTemplate("select_by_value", [{"name": "value", "type": "str"}], "select"),
            MethodTemplate("select_by_index", [{"name": "index", "type": "int"}], "select"),
            MethodTemplate("get_selected", [], "read", "str"),
            MethodTemplate("assert_selected", [{"name": "expected", "type": "str"}], "assertion"),
        ],
        "CheckboxAW": [
            MethodTemplate("check", [], "click"),
            MethodTemplate("uncheck", [], "click"),
            MethodTemplate("is_checked", [], "read", "bool"),
        ],
        "DialogAW": [
            MethodTemplate("wait_visible", [], "wait"),
            MethodTemplate("confirm", [], "click"),
            MethodTemplate("cancel", [], "click"),
            MethodTemplate("get_message", [], "read", "str"),
        ],
        "MenuAW": [
            MethodTemplate("click_item", [{"name": "label", "type": "str"}], "click"),
            MethodTemplate("assert_item_visible", [{"name": "label", "type": "str"}], "assertion"),
        ],
        "TabAW": [
            MethodTemplate("select", [{"name": "tab_name", "type": "str"}], "click"),
            MethodTemplate("assert_selected", [{"name": "tab_name", "type": "str"}], "assertion"),
        ],
        "TreeAW": [
            MethodTemplate("expand", [{"name": "node", "type": "str"}], "click"),
            MethodTemplate("click_node", [{"name": "label", "type": "str"}], "click"),
        ],
        "NavAW": [
            MethodTemplate("go_to", [{"name": "section", "type": "str"}], "click"),
            MethodTemplate("assert_active", [{"name": "section", "type": "str"}], "assertion"),
        ],
        "LinkAW": [
            MethodTemplate("click", [], "click"),
            MethodTemplate("get_url", [], "read", "str"),
        ],
        "RadioAW": [
            MethodTemplate("select", [{"name": "value", "type": "str"}], "click"),
            MethodTemplate("get_selected", [], "read", "str"),
        ],
    }

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def _get_aria_map(self) -> dict:
        """Query KB for ARIA role map, fall back to hardcoded defaults."""
        if self.kb:
            kb_result = self.kb.get_component_type("table", {})
            if kb_result:
                # Extract full ARIA role map from KB conventions
                for item in self.kb.store.list_category("conventions"):
                    if "component_types" in item.key:
                        return item.value.get("aria_role_map", self.ARIA_MAP)
        return self.ARIA_MAP

    def resolve_type(self, aria_role: str, dom_attrs: dict, snapshot_context: str) -> str:
        aria_map = self._get_aria_map()
        # 1. 从属性推断
        data_module = dom_attrs.get("data-module", "")
        if data_module:
            return self._guess_from_name(data_module, aria_role)
        # 2. 从 ARIA role 映射 (KB or hardcoded)
        role_lower = aria_role.lower()
        if role_lower in aria_map:
            return aria_map[role_lower]
        # 3. 从 tag 推断
        tag = dom_attrs.get("tag", "").lower()
        tag_map = {
            "input": "InputAW", "select": "DropdownAW",
            "button": "ButtonAW", "a": "LinkAW",
            "textarea": "InputAW", "table": "TableAW",
        }
        if tag in tag_map:
            return tag_map[tag]
        return "UnknownAW"

    def suggest_name(self, url: str, aria_role: str, dom_attrs: dict) -> str:
        """自动命名：URL 提取 domain + role 组合"""
        domain = self._extract_domain(url)
        role = aria_role or "element"
        data_module = dom_attrs.get("data-module", "")
        if data_module:
            return data_module.replace("-", "_").replace(" ", "_")
        name = f"{domain}_{role}".replace(" ", "_").lower()
        # 去重：如果名字太通用，加数字后缀
        return name if len(name) > 3 else f"{role}_{domain}"

    def get_methods_for_role(self, component_type: str, aria_role: str) -> list[MethodTemplate]:
        return self.METHOD_TEMPLATES.get(component_type, [
            MethodTemplate("click", [], "click"),
            MethodTemplate("assert_visible", [], "assertion"),
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
        if any(k in lower for k in ("menu", "nav", "sidebar")):
            return "MenuAW"
        if any(k in lower for k in ("tab", "tabpanel")):
            return "TabAW"
        return self.ARIA_MAP.get(aria_role, "UnknownAW")

    def _extract_domain(self, url: str) -> str:
        match = re.search(r'/(\w+)/(manage|list|create|edit|detail)', url)
        if match:
            return match.group(1)
        parts = url.rstrip("/").split("/")
        return parts[-1] if parts else "unknown"


# ═══════════════════════════════════════════════════════════════
# LocatorStrategy 参考实现
# ═══════════════════════════════════════════════════════════════

class ReferenceLocatorStrategy(LocatorStrategy):
    """基于 data-module 优先的 XPath 约定，优先从 KB 查询"""

    PRIORITY = ["data-module", "data-testid", "id", "name", "aria-label", "css", "xpath"]

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def get_locator_priority(self) -> list[str]:
        if self.kb:
            kb_conventions = self.kb.get_locator_conventions()
            if kb_conventions and "priority" in kb_conventions:
                return kb_conventions["priority"]
        return self.PRIORITY

    def build_xpath(self, element_info: ElementInfo, dom_context: dict) -> str:
        attrs = element_info.attrs
        # 1. 向上查找最近的 data-module 祖先
        for ancestor in element_info.ancestor_chain:
            anc_attrs = ancestor.get("attrs", {})
            if "data-module" in anc_attrs:
                module = anc_attrs["data-module"]
                return f"//*[@data-module='{module}']//{element_info.tag}[@{self._best_attr(attrs)}='{attrs.get(self._best_attr(attrs))}']"
        # 2. 元素自身的稳定属性
        for attr in ["data-module", "data-testid", "id", "name"]:
            if attr in attrs and attrs[attr]:
                return f"//{element_info.tag}[@{attr}='{attrs[attr]}']"
        # 3. 文本匹配
        if element_info.text:
            return f"//{element_info.tag}[contains(text(), '{element_info.text[:30]}')]"
        return ""

    def extract_feature_point(self, xpath: str) -> dict:
        for attr in ["data-module", "data-testid", "id", "name"]:
            match = re.search(rf"@{attr}=['\"]([^'\"]+)['\"]", xpath)
            if match:
                return {"type": attr, "value": match.group(1)}
        match = re.search(r"contains\([., ]'([^']+)'\)", xpath)
        if match:
            return {"type": "text-contains", "value": match.group(1)}
        return {"type": "xpath", "value": xpath}

    def _best_attr(self, attrs: dict) -> str:
        for attr in ["data-testid", "id", "name", "aria-label"]:
            if attr in attrs and attrs[attr]:
                return attr
        return "class"


# ═══════════════════════════════════════════════════════════════
# ActionRecognizer 参考实现
# ═══════════════════════════════════════════════════════════════

class ReferenceActionRecognizer(ActionRecognizer):
    """将 DOM 操作序列聚合为 BAW 语义"""

    def aggregate(self, raw_steps: list, page_context: dict) -> list:
        from ..engine.ir.raw_recording import RawStep, ActionType
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

        # 提取目标标签
        target_label = ""
        if isinstance(first, dict):
            t = first.get("target", {})
            if isinstance(t, dict):
                target_label = t.get("label", "")
        elif hasattr(first, 'target') and first.target:
            target_label = first.target.label or ""

        # 提取值
        value = ""
        if isinstance(first, dict):
            value = first.get("value", "")
        else:
            value = getattr(first, 'value', '') or ''

        base = {
            "raw_steps": list(buffer),
            "component": target_label.replace(" ", "_").lower() if target_label else "page",
            "value": value,
        }

        if action_type == "input" and len(buffer) >= 2:
            return {**base, "type": "composite_action", "action": "input_then_click", "steps": len(buffer)}
        return {**base, "type": "single_action", "action": action_type, "steps": len(buffer)}

    def recognize_pattern(self, sequences: list) -> list[dict]:
        """PrefixSpan 频繁子序列挖掘 — 发现可封装的 BAW 模式"""
        if len(sequences) < 3:
            return []

        # 将序列转为 action 名称列表
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

        miner = _PrefixSpan(min_support=3, max_length=8)
        frequent_patterns = miner.mine(action_seqs)

        patterns = []
        for pattern, count in frequent_patterns:
            pattern_key = " → ".join(pattern)
            patterns.append({
                "pattern": pattern_key,
                "actions": list(pattern),
                "frequency": count,
                "suggestion": f"建议封装为 BusinessAW (出现 {count} 次)",
            })

        return patterns


from ..adapter.base import _PrefixSpan  # noqa: F401 — re-export for backward compatibility


# ═══════════════════════════════════════════════════════════════
# CodeGenerator 参考实现
# ═══════════════════════════════════════════════════════════════

class ReferenceCodeGenerator(CodeGenerator):
    """生成 ComponentAW + BusinessAW + TestScript 代码，优先从 KB 查询风格"""

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def generate_component_aw(self, comp_def: ComponentDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        template = env.from_string(COMPONENT_AW_TEMPLATE)
        return template.render(comp=comp_def)

    def generate_business_aw(self, baw_def: BAWDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        template = env.from_string(BUSINESS_AW_TEMPLATE)
        return template.render(baw=baw_def)

    def generate_test_script(self, script_def: ScriptDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        template = env.from_string(TEST_SCRIPT_TEMPLATE)
        return template.render(s=script_def)

    def generate_test_data(self, data_def: TestDataDef) -> str:
        from jinja2 import Environment, BaseLoader
        env = Environment(loader=BaseLoader())
        env.filters["repr"] = lambda v: repr(v)
        template = env.from_string(TEST_DATA_TEMPLATE)
        return template.render(d=data_def)

    def get_import_style(self) -> ImportStyle:
        if self.kb:
            for item in self.kb.store.list_category("conventions"):
                if "import_style" in item.key:
                    examples = item.value.get("examples", [])
                    return ImportStyle(
                        from_imports=examples or [
                            "from pages.homepage import HomePage",
                            "from aaw.input_aw import InputAW",
                        ],
                        direct_imports=["pytest"],
                    )
        return ImportStyle(
            from_imports=[
                "from pages.homepage import HomePage",
                "from aaw.input_aw import InputAW",
                "from aaw.button_aw import ButtonAW",
                "from baw.user_crud import UserCrud",
            ],
            direct_imports=["pytest"],
        )

    def get_assertion_style(self) -> AssertionStyle:
        if self.kb:
            for item in self.kb.store.list_category("conventions"):
                if "assertion_style" in item.key:
                    return AssertionStyle(type=item.value.get("type", "pytest_assert"))
        return AssertionStyle(type="pytest_assert")

    def render_step(self, step) -> str:
        """Python ComponentAW 风格步骤渲染"""
        kind = getattr(step, 'kind', None)
        decl = getattr(step, 'decl', None)

        if kind and kind.value == "decl" and decl:
            return f"{decl.var} = {decl.factory}({decl.type})"

        if kind and kind.value == "navigate" and step.calls:
            url = step.calls[0].args[0] if step.calls[0].args else ""
            return f'page.goto("{url}")'

        if kind and kind.value == "action" and step.calls:
            call = step.calls[0]
            component = call.component or "page"
            method = call.method
            parts = []
            for a in call.args:
                parts.append(f'"{a}"' if isinstance(a, str) else str(a))
            for k, v in call.kwargs.items():
                parts.append(f'{k}="{v}"' if isinstance(v, str) else f'{k}={v}')
            args_str = ", ".join(parts)
            if args_str:
                return f"{component}.{method}({args_str})"
            return f"{component}.{method}()"

        if kind and kind.value == "assert" and step.calls:
            call = step.calls[0]
            msg = call.args[0] if call.args else step.comment
            if msg:
                return f"# assert: {msg}"
            return "# assert: page state changed as expected"

        comment = getattr(step, 'comment', '')
        if comment:
            return f"# {comment}"
        return ""


# ═══════════════════════════════════════════════════════════════
# DataFormatter 参考实现
# ═══════════════════════════════════════════════════════════════

class ReferenceDataFormatter(DataFormatter):
    """录制值 → Python dict 常量"""

    def format(self, captured_values: dict, data_context: dict) -> TestDataDef:
        domain = data_context.get("domain", "unknown")
        module = f"{domain}_data"
        fields = {}
        for key, value in captured_values.items():
            fields[key] = {
                "value": value,
                "type": type(value).__name__,
            }
        var_name = f"VALID_{domain.upper()}" if domain else "TEST_DATA"
        return TestDataDef(
            file_path=f"test_data/{module}.py",
            variable_name=var_name,
            fields=fields,
        )

    def get_data_ref_style(self, domain: str) -> str:
        return f"from test_data.{domain}_data import VALID_{domain.upper()}"


# ═══════════════════════════════════════════════════════════════
# Jinja2 模板
# ═══════════════════════════════════════════════════════════════

COMPONENT_AW_TEMPLATE = '''# [AUTO-GEN] 组件: {{ comp.class_name }}
# 基于运行时分析和 ARIA 组件发现自动生成
from aaw.base_aw import BaseAW


class {{ comp.class_name }}(BaseAW):
    """{{ comp.class_name }} — 自动生成的组件 AW"""

    def __init__(self, page, xpath: str):
        super().__init__(page)
        self.root = xpath
{% for method in comp.methods if method.action_type in ('click', 'input', 'select') %}
        self.{{ method.name }}_locator = f"{xpath}//*[@data-action='{{ method.name }}']"
{% endfor %}

{% for method in comp.methods %}
{% if method.action_type == 'wait' %}
    def {{ method.name }}(self{% for p in method.params %}, {{ p.name }}: {{ p.type }}{% endfor %}):
        self.page.wait_for_selector(self.root, state="visible")

{% elif method.action_type == 'click' %}
    def {{ method.name }}(self{% for p in method.params %}, {{ p.name }}: {{ p.type }}{% endfor %}):
        self.page.locator(self.root).click()

{% elif method.action_type == 'input' %}
    def {{ method.name }}(self{% for p in method.params %}, {{ p.name }}: {{ p.type }}{% endfor %}):
        self.page.locator(self.root).fill(str({{ method.params[0].name }}))

{% elif method.action_type == 'assertion' %}
    def {{ method.name }}(self{% for p in method.params %}, {{ p.name }}: {{ p.type }}{% endfor %}):
        self.page.locator(self.root).wait_for(state="visible")

{% elif method.action_type == 'read' %}
    def {{ method.name }}(self{% for p in method.params %}, {{ p.name }}: {{ p.type }}{% endfor %}) -> {{ method.returns }}:
        return self.page.locator(self.root).inner_text()

{% endif %}
{% endfor %}
'''

BUSINESS_AW_TEMPLATE = '''# [AUTO-GEN] 业务: {{ baw.class_name }}
# 从录制中自动识别和封装的业务 AW
{% for op in baw.operations %}

class {{ baw.class_name }}:
    """{{ baw.class_name }} — 自动生成的业务 AW"""

    @staticmethod
    def {{ op.name }}(page{% for p in op.params %}, {{ p.name }}: {{ p.type }}{% endfor %}):
        """
{% for call in op.calls %}
        {{ call.component }}.{{ call.method }}({{ call.args|join(', ') }})
{% endfor %}
        """
{% for call in op.calls %}
        page.{{ call.component }}.{{ call.method }}({{ call.args|join(', ') }})
{% endfor %}
{% endfor %}
'''

TEST_SCRIPT_TEMPLATE = '''"""
[AUTO-GEN] {{ s.description or s.test_name }}
"""
{% for imp in s.imports %}
{{ imp }}
{% endfor %}


class Test{{ s.class_name }}:
{% for fixture in s.fixtures %}
    {{ fixture }}
{% endfor %}

    def {{ s.test_name }}(self, page):
        """
{% for step in s.steps %}
        {{ step }}
{% endfor %}
        """
{% for step in s.steps %}
        {{ step }}
{% endfor %}
'''

TEST_DATA_TEMPLATE = '''# [AUTO-GEN] 测试数据: {{ d.variable_name }}
# 字段从录制值自动提取

{{ d.variable_name }} = {
{% for field, info in d.fields.items() %}
    "{{ field }}": {{ info.value | repr }},  # {{ info.type }}
{% endfor %}
}
'''
