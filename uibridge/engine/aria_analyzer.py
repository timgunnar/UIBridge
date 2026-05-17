"""ARIA 分析器 — 从页面 ARIA 快照中自动发现组件"""

import json
import re
from dataclasses import dataclass, field
from playwright.sync_api import Page


@dataclass
class DiscoveredComponent:
    """发现的组件"""
    type: str  # TableAW / FormAW / DropdownAW / ButtonAW / Unknown
    aria_role: str
    xpath: str
    children: list[dict] = field(default_factory=list)
    inputs: list[dict] = field(default_factory=list)
    interactables: list[dict] = field(default_factory=list)


@dataclass
class ElementInfo:
    """元素信息"""
    tag: str
    attrs: dict = field(default_factory=dict)
    text: str = ""
    ancestor_chain: list[str] = field(default_factory=list)


class AriaAnalyzer:
    """用 Playwright ARIA 快照分析页面结构，自动发现组件边界。"""

    ARIA_TO_COMPONENT = {
        "table": "TableAW",
        "grid": "TableAW",
        "treegrid": "TableAW",
        "form": "FormAW",
        "combobox": "DropdownAW",
        "listbox": "DropdownAW",
        "menu": "MenuAW",
        "menubar": "MenuAW",
        "dialog": "DialogAW",
        "alertdialog": "DialogAW",
        "tablist": "TabAW",
        "tabpanel": "TabPanelAW",
        "tree": "TreeAW",
        "navigation": "NavAW",
    }

    # CSS class 启发式：div+css 组件检测
    CSS_CLASS_PATTERNS = [
        (r"(?:^|\s)(?:btn|button)(?:[-\s]|$)", "button"),
        (r"(?:^|\s)(?:table|datatable|grid)(?:[-\s]|$)", "table"),
        (r"(?:^|\s)(?:form|form-group)(?:[-\s]|$)", "form"),
        (r"(?:^|\s)(?:dropdown|select|picker|combo)(?:[-\s]|$)", "combobox"),
        (r"(?:^|\s)(?:modal|dialog|popup|overlay)(?:[-\s]|$)", "dialog"),
        (r"(?:^|\s)(?:menu|nav|sidebar)(?:[-\s]|$)", "menu"),
        (r"(?:^|\s)(?:tab|tab-bar)(?:[-\s]|$)", "tablist"),
        (r"(?:^|\s)(?:tree|treeview)(?:[-\s]|$)", "tree"),
        (r"(?:^|\s)(?:input|text-field|textfield)(?:[-\s]|$)", "textbox"),
        (r"(?:^|\s)(?:checkbox|check-box)(?:[-\s]|$)", "checkbox"),
        (r"(?:^|\s)(?:card|panel|section|widget)(?:[-\s]|$)", "region"),
    ]

    def __init__(self, page: Page):
        self.page = page

    def analyze(self) -> list[DiscoveredComponent]:
        """打开页面，分析 ARIA 树，自动识别所有组件。"""
        components = []

        discovered = self._discover_standard_components()
        components.extend(discovered)

        custom = self._discover_custom_components()
        components.extend(custom)

        div_components = self._discover_div_components()
        components.extend(div_components)

        return components

    def _discover_div_components(self) -> list[DiscoveredComponent]:
        """通过 CSS class 模式发现 div+css 组件（非语义化 HTML）"""
        js_code = """
        () => {
            const patterns = """ + json.dumps([[p[0], p[1]] for p in self.CSS_CLASS_PATTERNS]) + """;
            const results = [];
            const seen = new Set();

            for (const [regexStr, ariaRole] of patterns) {
                const regex = new RegExp(regexStr, 'i');
                const els = document.querySelectorAll('[class]');
                for (const el of els) {
                    const cls = el.className || '';
                    if (!regex.test(cls)) continue;
                    const tag = el.tagName.toLowerCase();
                    // 跳过已经有 ARIA role 的元素（标准组件已覆盖）
                    if (el.hasAttribute('role')) continue;
                    // 跳过已被 data-module/data-testid 覆盖的
                    if (el.hasAttribute('data-module') || el.hasAttribute('data-testid')) continue;

                    let xpath = '';
                    if (el.id) xpath = `//${tag}[@id='${el.id}']`;
                    else {
                        // 使用 class 中最有辨识度的部分
                        const classes = cls.split(/\\s+/).filter(c => c.length > 2 && c.length < 30);
                        const bestClass = classes.find(c => regex.test(c)) || classes[0] || '';
                        if (bestClass) xpath = `//${tag}[contains(@class,'${bestClass}')]`;
                    }
                    if (!xpath || seen.has(xpath)) continue;
                    seen.add(xpath);

                    // 收集子元素
                    const children = Array.from(el.querySelectorAll('input,select,textarea,button,a'))
                        .slice(0, 20).map(c => ({
                            tag: c.tagName.toLowerCase(),
                            type: c.getAttribute('type') || '',
                            name: c.getAttribute('name') || '',
                            placeholder: c.getAttribute('placeholder') || '',
                            text: (c.textContent || '').trim().substring(0, 50),
                        }));
                    const interactables = Array.from(el.querySelectorAll('button,a,[onclick],.btn,.button'))
                        .slice(0, 20).map(c => ({
                            tag: c.tagName.toLowerCase(),
                            text: (c.textContent || '').trim().substring(0, 50),
                            role: c.getAttribute('role') || '',
                            aria_label: c.getAttribute('aria-label') || '',
                        }));

                    // 推测组件类型
                    let compType = 'UnknownAW';
                    if (ariaRole === 'button') compType = 'ButtonAW';
                    else if (ariaRole === 'table') compType = 'TableAW';
                    else if (ariaRole === 'form') compType = 'FormAW';
                    else if (ariaRole === 'combobox') compType = 'DropdownAW';
                    else if (ariaRole === 'dialog') compType = 'DialogAW';
                    else if (ariaRole === 'menu') compType = 'MenuAW';
                    else if (ariaRole === 'tablist') compType = 'TabAW';
                    else if (ariaRole === 'textbox') compType = 'InputAW';
                    else if (ariaRole === 'checkbox') compType = 'CheckboxAW';
                    else if (ariaRole === 'region') compType = 'PanelAW';

                    results.push({
                        type: compType,
                        aria_role: 'div+' + ariaRole,
                        xpath: xpath,
                        children: children,
                        interactables: interactables,
                    });
                }
            }
            return results;
        }
        """
        try:
            raw = self.page.evaluate(js_code)
            return [DiscoveredComponent(
                type=r["type"],
                aria_role=r["aria_role"],
                xpath=r["xpath"],
                children=r.get("children", []),
                interactables=r.get("interactables", []),
            ) for r in (raw or [])]
        except Exception:
            return []

    def _discover_standard_components(self) -> list[DiscoveredComponent]:
        """通过标准 ARIA role 发现组件"""
        components = []
        for role, component_type in self.ARIA_TO_COMPONENT.items():
            try:
                elements = self.page.locator(f'[role="{role}"]').all()
                for el in elements:
                    xpath = self._build_stable_xpath(el)
                    children_els = self._extract_children(el)
                    inputs = []
                    if role in ("form", "dialog"):
                        inputs = self._find_inputs_within(el)
                    if xpath:
                        components.append(DiscoveredComponent(
                            type=component_type,
                            aria_role=role,
                            xpath=xpath,
                            children=children_els,
                            inputs=inputs,
                            interactables=self._find_interactables(el),
                        ))
            except Exception:
                continue
        return components

    def _discover_custom_components(self) -> list[DiscoveredComponent]:
        """通过 data-module / data-testid 等自定义属性发现组件"""
        components = []
        for attr in ["data-module", "data-testid", "data-component"]:
            try:
                elements = self.page.locator(f"[{attr}]").all()
                seen_values = set()
                for el in elements:
                    value = el.get_attribute(attr) or ""
                    if value in seen_values:
                        continue
                    seen_values.add(value)
                    xpath = f"//*[@{attr}='{value}']"
                    components.append(DiscoveredComponent(
                        type=self._guess_component_type(value),
                        aria_role="custom",
                        xpath=xpath,
                        interactables=self._find_interactables(el),
                    ))
            except Exception:
                continue
        return components

    def _build_stable_xpath(self, element) -> str:
        """构建稳定 XPath，优先使用稳定属性"""
        for strategy in [
            lambda: element.get_attribute("data-module"),
            lambda: element.get_attribute("data-testid"),
            lambda: element.get_attribute("id"),
        ]:
            try:
                val = strategy()
                if val:
                    tag = element.evaluate("el => el.tagName.toLowerCase()")
                    attr_name = "data-module" if element.get_attribute("data-module") else (
                        "data-testid" if element.get_attribute("data-testid") else "id"
                    )
                    return f"//{tag}[@{attr_name}='{val}']"
            except Exception:
                continue
        try:
            return element.evaluate("""
                el => {
                    function buildPath(node) {
                        if (!node || node === document.body) return '';
                        const parent = node.parentElement;
                        const path = buildPath(parent);
                        const tag = node.tagName.toLowerCase();
                        if (node.id) return `//${tag}[@id='${node.id}']`;
                        const idx = Array.from(parent?.children || []).filter(
                            c => c.tagName === node.tagName
                        ).indexOf(node) + 1;
                        return `${path}/${tag}[${idx}]`;
                    }
                    return buildPath(el);
                }
            """)
        except Exception:
            return ""

    def _extract_children(self, element) -> list[dict]:
        """提取组件的子元素列表"""
        children = []
        try:
            child_elements = element.evaluate("""
                el => Array.from(el.querySelectorAll('input, select, textarea, button, a[role]'))
                    .map(c => ({
                        tag: c.tagName.toLowerCase(),
                        type: c.getAttribute('type') || '',
                        name: c.getAttribute('name') || '',
                        placeholder: c.getAttribute('placeholder') || '',
                        role: c.getAttribute('role') || '',
                        text: (c.textContent || '').trim().substring(0, 50),
                    }))
            """)
            children = child_elements or []
        except Exception:
            pass
        return children

    def _find_inputs_within(self, element) -> list[dict]:
        """在组件范围内找到所有输入元素"""
        try:
            return element.evaluate("""
                el => Array.from(el.querySelectorAll('input, select, textarea'))
                    .map(c => ({
                        tag: c.tagName.toLowerCase(),
                        type: c.getAttribute('type') || 'text',
                        name: c.getAttribute('name') || '',
                        placeholder: c.getAttribute('placeholder') || '',
                        required: !!c.required,
                    }))
            """) or []
        except Exception:
            return []

    def _find_interactables(self, element) -> list[dict]:
        """找到可交互元素（按钮、链接等）"""
        try:
            return element.evaluate("""
                el => Array.from(el.querySelectorAll('button, a, [role="button"], [onclick]'))
                    .map(c => ({
                        tag: c.tagName.toLowerCase(),
                        text: (c.textContent || '').trim().substring(0, 50),
                        role: c.getAttribute('role') || '',
                        aria_label: c.getAttribute('aria-label') || '',
                    }))
            """) or []
        except Exception:
            return []

    def _guess_component_type(self, attr_value: str) -> str:
        """根据属性值推测组件类型"""
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
        if any(k in lower for k in ("tree", "treeview")):
            return "TreeAW"
        return "UnknownAW"
