"""Stage 3: Framework Mapping — SemanticActionSequence → FrameworkCallSequence"""
import logging

logger = logging.getLogger(__name__)

from ..engine.ir.raw_recording import RawRecording, ActionType
from ..engine.ir.semantic_action import SemanticActionSequence, SemanticScenario
from ..engine.ir.framework_call import (
    FrameworkCallSequence, TestCaseIR, FrameworkStep, Decl, MethodCall, StepKind,
)
from ..adapter.base import sanitize_identifier, extract_domain


class StageMapping:
    DEFAULT_HOME_PAGE = "HomePage"

    def __init__(self, component_resolver, locator_strategy, action_recognizer,
                 code_generator, data_formatter, kb_manager=None):
        self.component_resolver = component_resolver
        self.locator_strategy = locator_strategy
        self.action_recognizer = action_recognizer
        self.code_generator = code_generator
        self.data_formatter = data_formatter
        self.kb_manager = kb_manager
        from ..engine.dom_diff import DOMDiffer
        self.dom_differ = DOMDiffer()
        self._resolved_package = ""

    def map_to_framework(self, semantic: SemanticActionSequence) -> FrameworkCallSequence:
        test_cases = []
        for scenario in semantic.scenarios:
            tc = self._map_scenario(scenario)
            test_cases.append(tc)
        return FrameworkCallSequence(test_cases=test_cases)

    def _map_scenario(self, scenario: SemanticScenario) -> TestCaseIR:
        """将语义场景映射为框架级测试用例，使用 CodeGenerator 进行框架特定的渲染"""
        steps: list[FrameworkStep] = []
        page_class = scenario.page_flow[-1] if scenario.page_flow else self.DEFAULT_HOME_PAGE
        page_var = "page"

        # 页面声明步骤
        steps.append(FrameworkStep(
            kind=StepKind.DECL,
            decl=Decl(var=page_var, type=page_class, factory="resolve"),
        ))

        for action in scenario.actions:
            action_type = action.type
            action_name = action.action
            params = action.params or {}

            if action_type in ("single_action", "composite_action", "page_action"):
                component = params.get("component", page_var)
                value = params.get("value", "")
                raw_steps = params.get("raw_steps", [])

                # 从 raw_steps 提取真实的目标信息
                target_label = ""
                for rs in raw_steps:
                    if isinstance(rs, dict):
                        t = rs.get("target", {})
                        if isinstance(t, dict):
                            target_label = t.get("label", "")
                        if t and hasattr(t, 'label'):
                            target_label = t.label
                    elif hasattr(rs, 'target') and rs.target:
                        target_label = rs.target.label or ""

                if action_name in ("input", "fill", "input_then_click"):
                    steps.append(FrameworkStep(
                        kind=StepKind.ACTION,
                        calls=[MethodCall(
                            method="enter" if value else "click",
                            component=component,
                            args=[value] if value else [],
                            kwargs={"label": target_label} if target_label else {},
                        )],
                    ))
                elif action_name in ("click",):
                    steps.append(FrameworkStep(
                        kind=StepKind.ACTION,
                        calls=[MethodCall(
                            method="click",
                            component=component,
                            kwargs={"label": target_label} if target_label else {},
                        )],
                    ))
                elif action_name == "navigate":
                    steps.append(FrameworkStep(
                        kind=StepKind.NAVIGATE,
                        calls=[MethodCall(method="goto", args=[params.get("url", "")])],
                    ))
                else:
                    steps.append(FrameworkStep(
                        kind=StepKind.ACTION,
                        calls=[MethodCall(method=action_name, component=component)],
                    ))

            elif action_type == "assertion":
                steps.append(FrameworkStep(
                    kind=StepKind.ASSERT,
                    calls=[MethodCall(
                        method=action_name,
                        component=params.get("component", page_var),
                        kwargs=params.get("kwargs", {}),
                    )],
                    comment=params.get("description", ""),
                ))

        # 收集 imports
        import_style = self.code_generator.get_import_style()
        imports = set()
        if isinstance(import_style, str):
            # New API: style identifier string
            lang = getattr(self.code_generator, 'target_language', 'python')
            if lang == 'java':
                imports.update([
                    "import org.testng.annotations.Test;",
                    "import org.testng.annotations.BeforeMethod;",
                ])
            else:
                imports.add("import pytest")
        else:
            # Legacy API: ImportStyle object
            for imp in import_style.direct_imports:
                imports.add(f"import {imp}" if not imp.startswith("import ") else imp)
            for imp in import_style.from_imports:
                imports.add(imp)

        # KB 集成：用高置信度 KB 知识替换硬编码的默认包名
        if self.kb_manager:
            imports = self._apply_kb_imports(imports)

        safe_name = self._sanitize_test_name(scenario.name)
        return TestCaseIR(
            name=f"test_{safe_name}",
            description=f"场景: {' -> '.join(scenario.page_flow)}",
            imports=sorted(imports),
            fixtures=[],
            steps=steps,
        )

    def _build_assertion_map(self, recording: RawRecording) -> dict[int, list[str]]:
        """遍历所有连续快照对，为每个场景索引构建断言候选映射。

        场景 N 的快照对：snapshot[N] (进入页面的快照) vs snapshot[N+1] (离开/操作后)。
        无下一快照时，使用最后一个快照作为 after。
        """
        snapshots = list(recording.snapshots.values())
        if len(snapshots) < 2:
            return {}

        # 提取 NAVIGATE 步骤的快照 ID（按录制顺序）
        nav_snapshot_ids = []
        for step in recording.steps:
            if step.action == ActionType.NAVIGATE and step.after_snapshot_id:
                nav_snapshot_ids.append(step.after_snapshot_id)

        if not nav_snapshot_ids:
            # 无显式导航步骤：使用全部快照，每个场景对应一对
            nav_snapshot_ids = [s.id for s in snapshots]

        # 建立场景索引 → 断言候选列表
        assertion_map = {}
        for i in range(len(nav_snapshot_ids)):
            before_id = nav_snapshot_ids[i]
            after_id = (nav_snapshot_ids[i + 1] if i + 1 < len(nav_snapshot_ids)
                        else snapshots[-1].id)

            before_snap = recording.snapshots.get(before_id)
            after_snap = recording.snapshots.get(after_id)
            if before_snap and after_snap and before_id != after_id:
                result = self.dom_differ.diff(
                    before_snap.aria_snapshot, after_snap.aria_snapshot,
                    before_snap.url, after_snap.url,
                    before_snap.layout_info, after_snap.layout_info,
                )
                assertion_map[i] = result.assertion_candidates

        return assertion_map

    def _extract_captured_values(self, recording: RawRecording) -> dict:
        values = {}
        for step in recording.steps:
            action = step.action
            if action == ActionType.INPUT and step.value:
                label = step.target.label if step.target else "unknown"
                tag = step.target.tag if step.target else ""
                key = sanitize_identifier(label, fallback_tag=tag or "field") if label else "field"
                values[key] = step.value
        return values

    @staticmethod
    def _sanitize_test_name(name: str) -> str:
        """清除测试名中的非法字符（中文、标点、CSS 选择器等）"""
        from ..adapter.base import sanitize_identifier
        return sanitize_identifier(name, fallback_tag="test")

    def _apply_kb_imports(self, imports: set[str]) -> set[str]:
        """用 KB 中的实际包名替换 import 中的硬编码默认值。

        硬编码默认如 com.acme.* → KB 推导的 com.enterprise.*。
        """
        pkg = self._resolved_package
        default_pkg = getattr(self.code_generator, 'DEFAULT_PACKAGE', 'com.acme')
        if not pkg or pkg == default_pkg:
            return imports

        replacements = {default_pkg: pkg}
        fixed = set()
        for imp in imports:
            for old, new in replacements.items():
                if old in imp:
                    imp = imp.replace(old, new)
            fixed.add(imp)
        return fixed

    def _render_framework_step(self, step: FrameworkStep) -> str:
        """将 FrameworkStep 渲染为框架风格的代码字符串。

        委托给适配器的 CodeGenerator.render_step()，确保按目标语言/框架语法生成。
        """
        return self.code_generator.render_step(step)
