"""DiscoveryService — 组件发现 + BAW 模式挖掘

从 Pipeline 分离出的独立服务：分析 DOM 和语义序列，发现可复用组件和业务模式。
"""

from collections import Counter
import logging

logger = logging.getLogger(__name__)


def _mine_ngram_patterns(action_sequences: list[list[str]],
                         n: int = 3, min_count: int = 2) -> list[dict]:
    """模块级工具：从动作类型序列中挖掘 N-gram 频繁子序列。

    不依赖 ActionRecognizer，可独立用于模式分析。
    """
    subsequence_counter = Counter()
    for actions in action_sequences:
        for i in range(len(actions) - (n - 1)):
            subseq = tuple(actions[i:i + n])
            subsequence_counter[subseq] += 1

    patterns = []
    for subseq, count in subsequence_counter.items():
        if count >= min_count:
            patterns.append({
                "pattern": "→".join(subseq),
                "actions": list(subseq),
                "frequency": count,
                "source": "auto_mined",
            })
    return patterns


class DiscoveryService:
    """负责发现项目中的 UI 组件和业务操作模式。

    与 Pipeline 解耦，可在录制前后独立调用。
    """

    def __init__(self, code_generator=None, component_resolver=None, action_recognizer=None,
                 aria_analyzer_cls=None, kb_manager=None, style_learner=None, project_root="."):
        self.code_generator = code_generator
        self.component_resolver = component_resolver
        self.action_recognizer = action_recognizer
        self.aria_analyzer_cls = aria_analyzer_cls
        self.kb_manager = kb_manager
        self.style_learner = style_learner
        self.project_root = project_root

    # ── 组件发现 ──────────────────────────────

    def discover_components(self, page) -> list[dict]:
        """从页面中发现可复用 UI 组件。

        使用 AriaAnalyzer 分析页面 DOM，再通过 ComponentResolver
        为每个组件生成规范名称和类型。
        """
        if not self.aria_analyzer_cls or not self.component_resolver:
            return []

        analyzer = self.aria_analyzer_cls(page)
        components = analyzer.analyze()
        results = []
        for comp in components:
            name = self.component_resolver.suggest_name(
                page.url, comp.aria_role,
                {"data-module": comp.xpath} if comp.aria_role == "custom" else {}
            )
            comp_type = self.component_resolver.resolve_type(
                comp.aria_role,
                {"data-module": comp.xpath} if comp.aria_role == "custom" else {},
                "",
            )
            results.append({
                "type": comp_type,
                "name": name,
                "xpath": comp.xpath,
                "aria_role": comp.aria_role,
                "inputs": comp.inputs,
                "interactables": comp.interactables,
            })
        return results

    # ── BAW 模式挖掘 ──────────────────────────

    def mine_baw_patterns(self, semantic_sequences: list) -> list[dict]:
        """从语义序列中挖掘频繁的 BAW 模式。

        委托给 ActionRecognizer 进行模式识别，为每个模式派生业务名称。
        """
        if not self.action_recognizer:
            return []

        all_action_sequences = []
        for seq in semantic_sequences:
            for scenario in seq.scenarios:
                all_action_sequences.append(scenario.actions)

        patterns = self.action_recognizer.recognize_pattern(all_action_sequences)
        for p in patterns:
            p["baw_name"] = self._derive_baw_name(p)
        return patterns

    @staticmethod
    def _derive_baw_name(pattern: dict) -> str:
        """从模式字符串派生业务操作名称。"""
        pattern_str = pattern.get("pattern", "")
        if "input" in pattern_str.lower():
            return "SearchAndFilter"
        if "click" in pattern_str.lower():
            return "NavigateAndClick"
        return "CompositeOperation"
