"""业务 AW 生成器 — 从频繁模式自动生成业务 AW"""

import logging

logger = logging.getLogger(__name__)

from ..adapter.base import BAWDef, BAWOperationDef, CallDef, CodeGenerator, ActionRecognizer


class BusinessAWGenerator:
    """从频繁模式自动生成业务 AW"""

    def __init__(self, code_gen: CodeGenerator, action_recognizer: ActionRecognizer = None):
        self.code_gen = code_gen
        self.recognizer = action_recognizer

    def generate_from_pattern(self, pattern: dict, component_calls: list[dict]) -> str:
        """将频繁操作模式生成为业务 AW"""
        operation_name = pattern.get("name", "execute")
        calls = []
        for c in component_calls:
            calls.append(CallDef(
                component=c.get("component", ""),
                method=c.get("method", ""),
                args=c.get("args", []),
                data_binding=c.get("data_binding", ""),
            ))

        params = [{"name": "page", "type": "Page"}, {"name": "data", "type": "dict"}]
        op = BAWOperationDef(name=operation_name, params=params, calls=calls)
        baw_def = BAWDef(
            class_name=pattern.get("class_name", "GeneratedBAW"),
            module="baw.generated",
            operations=[op],
        )
        return self.code_gen.generate_business_aw(baw_def)

    def generate_all(self, patterns: list[dict]) -> list[dict]:
        """批量生成 BAW"""
        results = []
        for p in patterns:
            component_calls = []
            if "components" in p:
                for comp_name, methods in p["components"].items():
                    for m in methods:
                        component_calls.append({
                            "component": comp_name,
                            "method": m,
                            "args": [],
                        })
            if not component_calls:
                component_calls = [
                    {"component": "page", "method": "perform_action", "args": ["data"]}
                ]

            p["class_name"] = p.get("baw_name", p.get("class_name", "GeneratedBAW"))
            code = self.generate_from_pattern(p, component_calls)
            results.append({
                "baw_name": p["class_name"],
                "pattern": p.get("pattern", ""),
                "frequency": p.get("frequency", 0),
                "code": code,
            })
        return results

    def suggest_wrap(self, component_call_sequences: list[list[dict]],
                     min_frequency: int = 3) -> list[dict]:
        """建议封装 — 出现 min_frequency 次以上的组件调用序列"""
        from collections import Counter

        suggestions = []
        counter = Counter()
        for seq in component_call_sequences:
            key = " → ".join(
                f"{c.get('component', '?')}.{c.get('method', '?')}"
                for c in seq
            )
            if key:
                counter[key] += 1

        for key, count in counter.items():
            if count >= min_frequency:
                suggestions.append({
                    "pattern": key,
                    "frequency": count,
                    "suggestion": f"Appeared {count} times, suggest wrapping into BAW",
                    "baw_name": self._derive_name(key),
                })

        return sorted(suggestions, key=lambda s: s["frequency"], reverse=True)

    def _derive_name(self, pattern_key: str) -> str:
        parts = pattern_key.split(" → ")
        verbs = []
        for p in parts[:3]:
            if "." in p:
                verbs.append(p.split(".")[-1].capitalize())
        name = "".join(verbs) if verbs else "CompositeOperation"
        return name
