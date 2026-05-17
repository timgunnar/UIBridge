"""组件 AW 生成器"""

from ..adapter.base import ComponentDef, MethodTemplate, CodeGenerator, ComponentResolver


class ComponentAWGenerator:
    """基于运行时发现的组件，自动生成组件 AW 代码"""

    def __init__(self, code_gen: CodeGenerator, resolver: ComponentResolver = None):
        self.code_gen = code_gen
        self.resolver = resolver

    def generate(self, component_type: str, aria_role: str, xpath: str,
                 resolver=None, discovered_inputs: list[dict] = None,
                 discovered_buttons: list[dict] = None) -> str:
        r = resolver or self.resolver
        if r is None:
            raise ValueError("resolver is required")
        methods = r.get_methods_for_role(component_type, aria_role)

        if discovered_inputs:
            for inp in discovered_inputs:
                name = inp.get("name", "") or inp.get("placeholder", "") or "field"
                clean_name = name.replace(" ", "_").lower()
                if not any(m.name == f"enter_{clean_name}" for m in methods):
                    methods.append(MethodTemplate(
                        name=f"enter_{clean_name}",
                        params=[{"name": "text", "type": "str"}],
                        action_type="input",
                    ))

        if discovered_buttons:
            for btn in discovered_buttons:
                text = btn.get("text", "") or btn.get("aria_label", "")
                clean_name = text.replace(" ", "_").lower()[:30]
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
            base_class="BaseAW",
        )
        return self.code_gen.generate_component_aw(comp_def)

    def generate_all(self, components: list[dict], resolver=None) -> list[dict]:
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
            )
            results.append({
                "type": comp.get("type", ""),
                "name": comp.get("name", ""),
                "code": code,
            })
        return results
