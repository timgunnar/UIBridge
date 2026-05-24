"""Stage 2: Semantic Analysis — RawRecording → SemanticActionSequence"""
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

from ..engine.ir.raw_recording import RawRecording, ActionType
from ..engine.ir.semantic_action import SemanticActionSequence, SemanticScenario, SemanticAction
from ..adapter.base import sanitize_identifier


class StageAnalysis:
    MAX_STEPS_PER_SCENE = 50
    IDLE_SPLIT_SECONDS = 5

    DEFAULT_PAGE_NAME = "UnknownPage"
    DEFAULT_HOME_PAGE = "HomePage"

    def __init__(self, component_resolver, action_recognizer, kb_manager=None):
        self.component_resolver = component_resolver
        self.action_recognizer = action_recognizer
        self.kb_manager = kb_manager
        from ..engine.aria_analyzer import AriaAnalyzer
        from ..engine.dom_diff import DOMDiffer
        self.aria_analyzer_cls = AriaAnalyzer
        self.dom_differ = DOMDiffer()

    def analyze(self, recording: RawRecording) -> SemanticActionSequence:
        scenarios = []
        current_scenario_steps = []
        current_page = ""
        page_flow = []
        # 空闲间隔阈值（毫秒）：超过此间隔视为新场景
        IDLE_GAP_MS = self.IDLE_SPLIT_SECONDS * 1000
        # 强制切分前容忍的额外步数（用于寻找语义边界）
        FORCE_SPLIT_GRACE = 10
        last_ts = 0

        # 跟踪当前场景的主要组件类型，用于语义边界检测
        current_dominant_component = ""

        # KB-driven noise filtering: track confidence per step
        low_confidence_count = 0
        total_processed = 0
        step_kb_confidence = {}  # step_id -> "high" | "medium" | "low"

        for step in recording.steps:
            action = step.action
            ts = step.timestamp_ms or 0

            # 过滤纯噪声步骤
            if action in (ActionType.MUTATION,):
                last_ts = ts
                continue

            # KB 组件类型校验（Stage 2 噪声过滤）
            confidence = self._validate_component_with_kb(step, self.kb_manager)
            step_kb_confidence[step.id] = confidence
            total_processed += 1
            if confidence == "low" and action not in (ActionType.NAVIGATE, ActionType.SCROLL):
                low_confidence_count += 1

            # NAVIGATE / TAB_SWITCH 总是场景边界
            is_boundary = action in (ActionType.NAVIGATE, ActionType.TAB_SWITCH)
            # 空闲间隔超过阈值也视为边界（纯点击 SPA 场景）
            if not is_boundary and last_ts > 0 and ts > last_ts and (ts - last_ts) > IDLE_GAP_MS:
                is_boundary = True

            # 步数超限强制切分：在大规模录制中保证生成可用性
            if not is_boundary and len(current_scenario_steps) >= self.MAX_STEPS_PER_SCENE:
                boundary_idx = self._find_semantic_split_point(
                    current_scenario_steps, self.MAX_STEPS_PER_SCENE - FORCE_SPLIT_GRACE
                )
                if boundary_idx > 0:
                    # 将 boundary_idx 之前的步骤保存为当前场景
                    overflow = current_scenario_steps[boundary_idx:]
                    current_scenario_steps = current_scenario_steps[:boundary_idx]
                    is_boundary = True

            if is_boundary:
                if current_scenario_steps:
                    scenarios.append(self._build_scenario(
                        current_scenario_steps, current_page, page_flow
                    ))
                    # 处理溢出步骤
                    if 'overflow' in dir():
                        current_scenario_steps = overflow
                        del overflow
                    else:
                        current_scenario_steps = []

            if action == ActionType.NAVIGATE:
                url = step.target.url if step.target else ""
                current_page = self._infer_page_name(url)
                page_flow = [current_page]
                current_scenario_steps.append(step)
                current_dominant_component = ""
            elif action == ActionType.TAB_SWITCH:
                current_dominant_component = ""
            else:
                current_scenario_steps.append(step)

            last_ts = ts

        if current_scenario_steps:
            scenarios.append(self._build_scenario(
                current_scenario_steps, current_page, page_flow
            ))

        # KB 噪声过滤摘要日志
        if self.kb_manager and low_confidence_count > 0:
            logger.info("%d/%d steps are low-confidence (unrecognized component types)", low_confidence_count, total_processed)

        return SemanticActionSequence(
            meta={
                "source": "pipeline_analysis",
                "kb_confidence_stats": {
                    "total": total_processed,
                    "low_confidence": low_confidence_count,
                    "step_confidence": step_kb_confidence,
                },
            },
            scenarios=scenarios,
        )

    def _find_semantic_split_point(self, steps: list, search_from: int) -> int:
        """在步数超限时寻找最佳语义切分点。

        优先选择：
        1. 组件类型变化点（如从 table 操作切换到 form 操作）
        2. 步骤间时间间隔 >= 2 秒的点
        3. 无更好选择时在 search_from 位置强制切分
        """
        MIN_GAP_MS = 2000

        for i in range(search_from, len(steps) - 1):
            # 检查组件类型变化
            comp_cur = self._step_component(steps[i])
            comp_next = self._step_component(steps[i + 1])
            if comp_cur and comp_next and comp_cur != comp_next:
                return i + 1

        for i in range(search_from, len(steps) - 1):
            ts_cur = steps[i].timestamp_ms or 0
            ts_next = steps[i + 1].timestamp_ms or 0
            if ts_next - ts_cur >= MIN_GAP_MS:
                return i + 1

        # 无语义边界，在搜索起点强制切分
        return search_from

    @staticmethod
    def _step_component(step) -> str:
        """从步骤中提取组件标识（用于组件类型变化检测）。"""
        if step.target:
            selector = step.target.selector_set
            if selector:
                return selector.data_module or selector.data_testid or selector.aria_role or ""
        return ""

    def _validate_component_with_kb(self, step, kb_manager) -> str:
        """Validate step component against KB, return confidence level.

        Returns:
            "high"   — KB recognizes this component type
            "medium" — KB has components but none match exactly
            "low"    — KB has no components at all or no match
        """
        if not kb_manager:
            return "medium"

        # Extract component hints from step
        tag = step.target.tag if step.target else ""
        role = ""
        data_module = ""
        if step.target and step.target.selectors:
            role = step.target.selectors.role or ""
            data_module = step.target.selectors.data_module or ""

        # Prepare DOM attrs for KB query
        dom_attrs = {}
        if role:
            dom_attrs["role"] = role
        if data_module:
            dom_attrs["data-module"] = data_module

        # Query KB for exact component type match
        result = kb_manager.get_component_type(role, dom_attrs)
        if result:
            return "high"

        # Check if any component category exists in KB at all
        all_components = kb_manager.store.list_category("components")
        if all_components and (tag or role):
            return "medium"
        return "low"

    def _build_scenario(self, steps: list, page: str, page_flow: list) -> SemanticScenario:
        actions = self.action_recognizer.aggregate(steps, {"page": page})
        # Stage 3: KB-driven noise filtering — merge subsequences into BAW operations
        if self.kb_manager:
            actions = self.action_recognizer._match_kb_patterns(actions, self.kb_manager)
        semantic_actions = []
        for i, act in enumerate(actions):
            if isinstance(act, dict):
                semantic_actions.append(SemanticAction(
                    type=act.get("type", "page_action"),
                    page=page,
                    action=act.get("action", "unknown"),
                    params={
                        "steps": act.get("steps", 1),
                        "raw_steps": act.get("raw_steps", []),
                        "component": act.get("component", ""),
                        "value": act.get("value", ""),
                    },
                ))

        actionable_steps = [
            s for s in steps
            if s.action not in (ActionType.NAVIGATE, ActionType.TAB_SWITCH)
        ]
        name = self._derive_scenario_name(actionable_steps, page)

        return SemanticScenario(
            name=name,
            page_flow=page_flow,
            actions=semantic_actions,
        )

    def _derive_scenario_name(self, steps: list, page: str) -> str:
        if not steps:
            return f"navigate_{page}"
        first = steps[0]
        action = first.action
        val = (first.value or "")[:20]
        if action == ActionType.INPUT:
            return f"input_{val}" if val else f"input_on_{page}"
        if action == ActionType.CLICK:
            label = first.target.label if first.target else ""
            tag = first.target.tag if first.target else ""
            safe_label = sanitize_identifier(label, fallback_tag=tag or "elem") if label else ""
            return f"click_{safe_label}" if safe_label else f"click_on_{page}"
        return f"action_on_{page}"

    def _infer_page_name(self, url: str) -> str:
        if not url or url == "about:blank":
            return self.DEFAULT_HOME_PAGE
        path = urlparse(url).path.strip("/")
        if not path:
            return self.DEFAULT_HOME_PAGE
        parts = path.split("/")
        meaningful = [p for p in parts if p and not p[0].isdigit()]
        return "".join(w.capitalize() for w in meaningful[-2:]) if meaningful else self.DEFAULT_PAGE_NAME
