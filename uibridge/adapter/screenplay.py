"""Screenplay 适配器 — B 公司风格的适配器实现"""

import re

from jinja2 import Environment, BaseLoader

from .base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter,
    MethodTemplate, ComponentDef, PageComponent, PageDef,
    BAWDef, BAWOperationDef, CallDef,
    ImportStyle, FixtureStyle, AssertionStyle,
    ElementInfo, TestDataDef, ScriptDef,
    sanitize_identifier,
)

_JINJA_ENV = Environment(loader=BaseLoader())
_DOMAIN_RE = re.compile(r'/(\w+)/(manage|list|create|edit|detail)')


class ScreenplayComponentResolver(ComponentResolver):
    """Screenplay 模式: 组件 → Target(页面元素定位)，优先从 KB 查询"""

    ARIA_MAP = {
        "table": "TableTarget", "grid": "TableTarget", "treegrid": "TableTarget",
        "form": "FormTarget",
        "textbox": "InputTarget", "searchbox": "InputTarget", "spinbutton": "SpinnerTarget",
        "checkbox": "CheckboxTarget", "radio": "RadioTarget", "switch": "ToggleTarget",
        "combobox": "DropdownTarget", "listbox": "DropdownTarget",
        "slider": "SliderTarget", "option": "OptionTarget",
        "menu": "MenuTarget", "menubar": "MenuTarget",
        "tablist": "TabTarget", "tab": "TabTarget",
        "tree": "TreeTarget", "treeitem": "TreeItemTarget",
        "navigation": "NavTarget", "link": "LinkTarget", "button": "ButtonTarget",
        "dialog": "DialogTarget", "alert": "AlertTarget", "alertdialog": "DialogTarget",
        "banner": "BannerTarget", "tooltip": "TooltipTarget",
        "progressbar": "ProgressTarget", "status": "StatusTarget",
        "log": "LogTarget", "timer": "TimerTarget",
        "region": "RegionTarget", "group": "GroupTarget",
        "list": "ListTarget", "listitem": "ListItemTarget",
        "separator": "SeparatorTarget",
        "img": "ImageTarget", "heading": "HeadingTarget",
        "main": "MainTarget", "contentinfo": "FooterTarget",
    }

    METHOD_TEMPLATES = {
        "TableTarget": [
            MethodTemplate("locate", [], "read", "TableTarget"),
            MethodTemplate("row_count", [], "read", "int"),
            MethodTemplate("cell_text", [{"name": "row", "type": "int"}, {"name": "col", "type": "int"}], "read", "str"),
            MethodTemplate("filter_by", [{"name": "column", "type": "str"}, {"name": "value", "type": "str"}], "input"),
        ],
        "FormTarget": [
            MethodTemplate("locate", [], "read", "FormTarget"),
            MethodTemplate("submit", [], "click"),
            MethodTemplate("reset", [], "click"),
        ],
        "InputTarget": [
            MethodTemplate("locate", [], "read", "InputTarget"),
            MethodTemplate("enter", [{"name": "text", "type": "str"}], "input"),
            MethodTemplate("clear", [], "input"),
            MethodTemplate("value", [], "read", "str"),
        ],
        "ButtonTarget": [
            MethodTemplate("locate", [], "read", "ButtonTarget"),
            MethodTemplate("click", [], "click"),
        ],
        "DropdownTarget": [
            MethodTemplate("locate", [], "read", "DropdownTarget"),
            MethodTemplate("select_by_value", [{"name": "value", "type": "str"}], "select"),
            MethodTemplate("select_by_index", [{"name": "index", "type": "int"}], "select"),
            MethodTemplate("selected_value", [], "read", "str"),
        ],
        "CheckboxTarget": [
            MethodTemplate("locate", [], "read", "CheckboxTarget"),
            MethodTemplate("check", [], "click"),
            MethodTemplate("uncheck", [], "click"),
            MethodTemplate("is_checked", [], "read", "bool"),
        ],
        "LinkTarget": [
            MethodTemplate("locate", [], "read", "LinkTarget"),
            MethodTemplate("click", [], "click"),
            MethodTemplate("href", [], "read", "str"),
        ],
        "DialogTarget": [
            MethodTemplate("locate", [], "read", "DialogTarget"),
            MethodTemplate("accept", [], "click"),
            MethodTemplate("dismiss", [], "click"),
        ],
    }

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def resolve_type(self, aria_role: str, dom_attrs: dict, snapshot_context: str) -> str:
        role_map = self._resolve_aria_map()
        return role_map.get(aria_role.lower(), "Target")

    def suggest_name(self, url: str, aria_role: str, dom_attrs: dict) -> str:
        domain = self._extract_domain(url)
        data_module = dom_attrs.get("data-module", "")
        if data_module:
            return data_module.replace("-", "_").upper()
        return f"{domain}_{aria_role}".upper() if aria_role else "PAGE_ELEMENT"

    def get_methods_for_role(self, component_type: str, aria_role: str) -> list[MethodTemplate]:
        return self.METHOD_TEMPLATES.get(component_type, [
            MethodTemplate("locate", [], "read", "Target"),
        ])

    def _extract_domain(self, url: str) -> str:
        match = _DOMAIN_RE.search(url)
        return match.group(1) if match else "unknown"


class ScreenplayLocatorStrategy(LocatorStrategy):
    """Screenplay 定位策略: 使用 data-test 属性，优先从 KB 查询"""

    PRIORITY = ["data-module", "data-testid", "data-test", "id", "name", "aria-label", "css"]

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def get_locator_priority(self) -> list[str]:
        return self._resolve_locator_priority()

    def build_xpath(self, element_info: ElementInfo, dom_context: dict) -> str:
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
        # 2. 元素自身的稳定属性
        for attr in ["data-test", "data-module", "id", "name"]:
            if attr in attrs and attrs[attr]:
                return f"[{attr}='{attrs[attr]}']"
        if element_info.text:
            return f"text={element_info.text[:30]}"
        return ""

    def _best_attr(self, attrs: dict) -> str:
        for attr in ["data-test", "data-testid", "id", "name", "aria-label"]:
            if attr in attrs and attrs[attr]:
                return attr
        return ""

    def extract_feature_point(self, xpath: str) -> dict:
        match = re.search(r"\[(data-test|data-module)='([^']+)'\]", xpath)
        if match:
            return {"type": match.group(1), "value": match.group(2)}
        return {"type": "xpath", "value": xpath}


class ScreenplayActionRecognizer(ActionRecognizer):
    """Screenplay: DOM 操作 → Task / Interaction（含缓冲区聚合）"""

    def aggregate(self, raw_steps: list, page_context: dict) -> list:
        actions = []
        input_buffer = []
        last_component = None

        for step in raw_steps:
            action_type = step.action.value if hasattr(step.action, "value") else str(step.action)

            target_label = step.target.label if step.target and step.target.label else ""
            target_tag = step.target.tag if step.target and step.target.tag else ""
            value = getattr(step, 'value', '') or ''

            base = {
                "component": sanitize_identifier(target_label, fallback_tag=target_tag or "actor") if target_label else "actor",
                "value": value,
            }

            if action_type == "navigate":
                actions.append({**base, "raw_steps": [step], "type": "task", "action": "Navigate.to"})
                input_buffer.clear()
                continue

            if action_type in ("input", "fill"):
                input_buffer.append(step)
                last_component = base["component"]
                continue

            if action_type == "click":
                if input_buffer:
                    # 聚合：输入 + 点击 → 复合任务
                    combined_steps = input_buffer + [step]
                    inputs = [s.value for s in input_buffer if hasattr(s, 'value') and s.value]
                    actions.append({
                        "raw_steps": combined_steps,
                        "component": last_component,
                        "value": inputs,
                        "type": "composite_task",
                        "action": "FillAndSubmit",
                    })
                    input_buffer.clear()
                else:
                    actions.append({**base, "raw_steps": [step], "type": "interaction", "action": "Click.on"})
                continue

            if action_type == "select":
                actions.append({**base, "raw_steps": [step], "type": "interaction", "action": "SelectOption.by_value"})
                continue

            # 其他事件（dblclick, hover, rightclick, drop, scroll, mutation, keydown 等）
            actions.append({**base, "raw_steps": [step], "type": "interaction", "action": action_type})

        # 未处理的输入缓冲
        for s in input_buffer:
            actions.append({"raw_steps": [s], "component": last_component, "value": getattr(s, 'value', '') or '',
                           "type": "interaction", "action": "Enter.text"})

        return actions



class ScreenplayCodeGenerator(CodeGenerator):
    """Screenplay 风格代码生成，优先从 KB 查询风格"""

    default_base_class = "Target"

    def __init__(self, kb_manager=None):
        self.kb = kb_manager

    def generate_component_aw(self, comp_def: ComponentDef) -> str:
        return self._render_target_class(comp_def)

    def generate_business_aw(self, baw_def: BAWDef) -> str:
        return self._render_task_class(baw_def)

    def generate_test_script(self, script_def: ScriptDef) -> str:
        template = _JINJA_ENV.from_string(SCREENPLAY_TEST_TEMPLATE)
        return template.render(s=script_def)

    def generate_test_data(self, data_def: TestDataDef) -> str:
        template = _JINJA_ENV.from_string(SCREENPLAY_FACTORY_TEMPLATE)
        return template.render(d=data_def)

    def get_import_style(self) -> ImportStyle:
        if self.kb:
            for item in self.kb.store.list_category("conventions"):
                if "import_style" in item.key:
                    examples = item.value.get("examples", [])
                    return ImportStyle(from_imports=examples or [
                        "from screenplay.actor import Actor",
                        "from screenplay.abilities import BrowseTheWeb",
                    ])
        return ImportStyle(from_imports=[
            "from screenplay.actor import Actor",
            "from screenplay.abilities import BrowseTheWeb",
        ])

    def get_assertion_style(self) -> AssertionStyle:
        if self.kb:
            for item in self.kb.store.list_category("conventions"):
                if "assertion_style" in item.key:
                    return AssertionStyle(type=item.value.get("type", "pytest_assert"))
        return AssertionStyle(type="pytest_assert")

    def render_step(self, step) -> str:
        """Screenplay 风格步骤渲染"""
        kind = getattr(step, 'kind', None)
        decl = getattr(step, 'decl', None)

        if kind and kind.value == "decl" and decl:
            return "actor = Actor.named(\"tester\").who_can(BrowseTheWeb.using(driver))"

        if kind and kind.value == "navigate" and step.calls:
            url = step.calls[0].args[0] if step.calls[0].args else ""
            return f'actor.attempts_to(Navigate.to("{url}"))'

        if kind and kind.value == "action" and step.calls:
            call = step.calls[0]
            component = call.component or "TARGET"
            method = call.method
            if method == "click":
                return f"actor.attempts_to(Click.on({component}))"
            elif method == "enter" and call.args:
                return f"actor.attempts_to(Enter.text(\"{call.args[0]}\").into({component}))"
            elif method == "select" and call.args:
                return f"actor.attempts_to(SelectOption.by_value(\"{call.args[0]}\").from_dropdown({component}))"
            return f"actor.attempts_to({method}({component}))"

        if kind and kind.value == "assert" and step.calls:
            msg = step.calls[0].args[0] if step.calls[0].args else step.comment
            if msg:
                return f"# assert: {msg}"
            return "actor.should(See.that(PAGE, Is.visible()))"

        comment = getattr(step, 'comment', '')
        if comment:
            return f"# {comment}"
        return ""

    def _render_target_class(self, comp_def: ComponentDef) -> str:
        template = _JINJA_ENV.from_string(SCREENPLAY_TARGET_TEMPLATE)
        return template.render(comp=comp_def)

    def _render_task_class(self, baw_def: BAWDef) -> str:
        steps_code = ""
        for op in baw_def.operations:
            for call in op.calls:
                component = call.component or "PAGE_ELEMENT"
                method = call.method
                args = call.args or []
                if method == "click":
                    steps_code += f"        actor.attempts_to(Click.on({component}))\n"
                elif method in ("enter", "input"):
                    val = args[0] if args else '""'
                    steps_code += f'        actor.attempts_to(Enter.text("{val}").into({component}))\n'
                elif method == "select":
                    val = args[0] if args else '""'
                    steps_code += f'        actor.attempts_to(SelectOption.by_value("{val}").from_dropdown({component}))\n'
                else:
                    steps_code += f"        actor.attempts_to({method}({component}))\n"

        template = _JINJA_ENV.from_string(SCREENPLAY_TASK_TEMPLATE)
        return template.render(class_name=baw_def.class_name, steps=steps_code.strip())


class ScreenplayDataFormatter(DataFormatter):
    """Screenplay 模式: Factory 而非 dict 常量"""

    def format(self, captured_values: dict, data_context: dict) -> TestDataDef:
        domain = data_context.get("domain", "unknown")
        var_name = f"valid_{domain}"
        return TestDataDef(
            file_path=f"factories/{domain}_factory.py",
            variable_name=var_name,
            fields=captured_values,
        )

    def get_data_ref_style(self, domain: str) -> str:
        return f"from factories.{domain}_factory import {domain.title()}Factory"


# ═══════════════════════════════════════════════════════════════
# Screenplay 模板
# ═══════════════════════════════════════════════════════════════

SCREENPLAY_TARGET_TEMPLATE = '''# [AUTO-GEN] Target: {{ comp.class_name }}
from pages.base import Target


class {{ comp.class_name }}({{ comp.base_class or "Target" }}):
    def __init__(self):
        super().__init__("{{ comp.xpath }}")
'''


SCREENPLAY_TASK_TEMPLATE = '''# [AUTO-GEN] Task: {{ class_name }}
from screenplay.actor import Task, Actor
{% if steps %}
from screenplay.interactions import Click, Enter, SelectOption
{% endif %}

class {{ class_name }}(Task):
    def perform_as(self, actor: Actor):
{% if steps %}
{{ steps }}
{% else %}
        pass
{% endif %}
'''


SCREENPLAY_TEST_TEMPLATE = '''"""
[AUTO-GEN] {{ s.description or s.test_name }} — Screenplay style
"""
import pytest
{% for imp in s.imports %}
{{ imp }}
{% endfor %}


class Describe{{ s.class_name }}:
{% for fixture in s.fixtures %}
    {{ fixture }}
{% endfor %}

    def {{ s.test_name }}(self, actor: Actor):
{% for step in s.steps %}
        {{ step }}
{% endfor %}
'''


SCREENPLAY_FACTORY_TEMPLATE = '''# [AUTO-GEN] Factory: {{ d.variable_name }}


class {{ d.variable_name.title() }}Factory:
    @staticmethod
    def {{ d.variable_name }}() -> dict:
        return {
{% for field, value in d.fields.items() %}
            "{{ field }}": "{{ value }}",
{% endfor %}
        }
'''
