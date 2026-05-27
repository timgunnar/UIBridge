"""组件 AW 生成器"""

import logging

logger = logging.getLogger(__name__)

# ── Stub classes (adapter/ deleted in v0.4.0, moved to scanner+generator) ──
class ComponentDef:
    def __init__(self, class_name="", module="", xpath="", methods=None, base_class="BaseAW"):
        self.class_name = class_name; self.module = module; self.xpath = xpath
        self.methods = methods or []; self.base_class = base_class
class MethodTemplate:
    def __init__(self, name="", params=None, action_type=""):
        self.name = name; self.params = params or []; self.action_type = action_type
class CodeGenerator:
    def generate_component_aw(self, comp_def): raise NotImplementedError
class ComponentResolver:
    def get_methods_for_role(self, component_type, aria_role): return []
def sanitize_identifier(name: str) -> str:
    import re; return re.sub(r'[^a-zA-Z0-9_]', '_', name.lower()).strip('_') or 'field'


class ComponentAWGenerator:
    """基于运行时发现的组件，自动生成组件 AW 代码"""

    def __init__(self, code_gen: CodeGenerator, resolver: ComponentResolver = None):
        self.code_gen = code_gen
        self.resolver = resolver

    def generate(self, component_type: str, aria_role: str, xpath: str,
                 resolver=None, discovered_inputs: list[dict] = None,
                 discovered_buttons: list[dict] = None,
                 base_class: str = "BaseAW") -> str:
        r = resolver or self.resolver
        if r is None:
            raise ValueError("resolver is required")
        methods = r.get_methods_for_role(component_type, aria_role)

        if discovered_inputs:
            for inp in discovered_inputs:
                name = inp.get("name", "") or inp.get("placeholder", "") or "field"
                clean_name = sanitize_identifier(name)
                if not any(m.name == f"enter_{clean_name}" for m in methods):
                    methods.append(MethodTemplate(
                        name=f"enter_{clean_name}",
                        params=[{"name": "text", "type": "str"}],
                        action_type="input",
                    ))

        if discovered_buttons:
            for btn in discovered_buttons:
                text = btn.get("text", "") or btn.get("aria_label", "")
                clean_name = sanitize_identifier(text)[:30]
                if clean_name and not any(m.name == f"click_{clean_name}" for m in methods):
                    methods.append(MethodTemplate(
                        name=f"click_{clean_name}" if clean_name else "click",
                        params=[],
                        action_type="click",
                    ))

        comp_def = ComponentDef(
            class_name=component_type,
            module=f"aaw.{component_type.lower()}",
            xpath=xpath,
            methods=methods,
            base_class=base_class,
        )
        return self.code_gen.generate_component_aw(comp_def)

    def generate_all(self, components: list[dict], resolver=None,
                     base_class: str = "BaseAW") -> list[dict]:
        """批量生成组件 AW"""
        results = []
        for comp in components:
            code = self.generate(
                component_type=comp.get("type", "BaseAW"),
                aria_role=comp.get("aria_role", "generic"),
                xpath=comp.get("xpath", "//*"),
                resolver=resolver,
                discovered_inputs=comp.get("inputs", []),
                discovered_buttons=comp.get("interactables", []),
                base_class=base_class,
            )
            results.append({
                "type": comp.get("type", ""),
                "name": comp.get("name", ""),
                "code": code,
            })
        return results
