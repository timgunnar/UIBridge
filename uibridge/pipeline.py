"""核心管道 — 串联录制 → 分析 → 匹配 → 生成 全流程"""

from pathlib import Path

from .engine.ir.raw_recording import RawRecording, RawStep, ActionType, Target, SelectorSet
from .engine.ir.semantic_action import SemanticActionSequence, SemanticScenario, SemanticAction
from .engine.ir.framework_call import (
    FrameworkCallSequence, TestCaseIR, FrameworkStep, Decl, MethodCall, StepKind,
)
from .engine.recorder import RecordingSession
from .engine.aria_analyzer import AriaAnalyzer
from .engine.dom_diff import DOMDiffer
from .engine.self_test import SelfTestRunner, SelfTestResult
from .adapter.base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter, ElementInfo, ScriptDef,
)
from .generator.style_learner import StyleLearner, StyleProfile
from .generator.component_aw_gen import ComponentAWGenerator
from .generator.business_aw_gen import BusinessAWGenerator
from .generator.test_script_gen import TestScriptGenerator


class Pipeline:
    """端到端管道: 录制 → IR v1 → IR v2 → IR v3 → 代码"""

    def __init__(
        self,
        component_resolver: ComponentResolver,
        locator_strategy: LocatorStrategy,
        action_recognizer: ActionRecognizer,
        code_generator: CodeGenerator,
        data_formatter: DataFormatter,
        project_root: str = ".",
        kb_manager=None,
    ):
        self.component_resolver = component_resolver
        self.locator_strategy = locator_strategy
        self.action_recognizer = action_recognizer
        self.code_generator = code_generator
        self.data_formatter = data_formatter
        self.project_root = Path(project_root)
        self.kb_manager = kb_manager

        self.aria_analyzer_cls = AriaAnalyzer
        self.dom_differ = DOMDiffer()
        self.self_test = SelfTestRunner()
        self.style_learner = StyleLearner()
        self.caw_gen = ComponentAWGenerator(code_generator, component_resolver)
        self.baw_gen = BusinessAWGenerator(code_generator, action_recognizer)
        self.script_gen = TestScriptGenerator(code_generator, data_formatter)

        self._components: dict[str, dict] = {}
        self._pages: dict[str, dict] = {}
        self._baw_patterns: dict[str, dict] = {}
        self._style_profile: StyleProfile | None = None
        self._resolved_package: str = ""

    # ── Stage 1: 录制 → IR v1 ─────────────────

    def record(self, page) -> RecordingSession:
        return RecordingSession(page)

    # ── Stage 2: IR v1 → IR v2 (语义理解) ─────

    def analyze(self, recording: RawRecording) -> SemanticActionSequence:
        scenarios = []
        current_scenario_steps = []
        current_page = ""
        page_flow = []
        # 空闲间隔阈值（毫秒）：超过此间隔视为新场景
        IDLE_GAP_MS = 5000
        last_ts = 0

        for step in recording.steps:
            action = step.action if isinstance(step.action, ActionType) else ActionType(step.action)
            ts = step.timestamp_ms or 0

            # NAVIGATE / TAB_SWITCH 总是场景边界
            is_boundary = action in (ActionType.NAVIGATE, ActionType.TAB_SWITCH)
            # 空闲间隔超过阈值也视为边界（纯点击 SPA 场景）
            if not is_boundary and last_ts > 0 and ts > last_ts and (ts - last_ts) > IDLE_GAP_MS:
                is_boundary = True

            if is_boundary:
                if current_scenario_steps:
                    scenarios.append(self._build_scenario(
                        current_scenario_steps, current_page, page_flow
                    ))
                    current_scenario_steps = []

            if action == ActionType.NAVIGATE:
                url = step.target.url if step.target else ""
                current_page = self._infer_page_name(url)
                page_flow = [current_page]
                current_scenario_steps.append(step)
            elif action == ActionType.TAB_SWITCH:
                pass  # TAB_SWITCH 只做边界，不加入步骤
            else:
                current_scenario_steps.append(step)

            last_ts = ts

        if current_scenario_steps:
            scenarios.append(self._build_scenario(
                current_scenario_steps, current_page, page_flow
            ))

        return SemanticActionSequence(
            meta={"source": "pipeline_analysis"},
            scenarios=scenarios,
        )

    def _build_scenario(self, steps: list, page: str, page_flow: list) -> SemanticScenario:
        actions = self.action_recognizer.aggregate(steps, {"page": page})
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
            if (s.action if isinstance(s.action, ActionType) else ActionType(s.action))
            not in (ActionType.NAVIGATE, ActionType.TAB_SWITCH)
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
        action = first.action if isinstance(first.action, ActionType) else ActionType(first.action)
        val = (first.value or "")[:20]
        if action == ActionType.INPUT:
            return f"input_{val}" if val else f"input_on_{page}"
        if action == ActionType.CLICK:
            label = first.target.label if first.target else ""
            return f"click_{label}" if label else f"click_on_{page}"
        return f"action_on_{page}"

    def _infer_page_name(self, url: str) -> str:
        if not url or url == "about:blank":
            return "HomePage"
        from urllib.parse import urlparse
        path = urlparse(url).path.strip("/")
        if not path:
            return "HomePage"
        parts = path.split("/")
        meaningful = [p for p in parts if p and not p[0].isdigit()]
        return "".join(w.capitalize() for w in meaningful[-2:]) if meaningful else "UnknownPage"

    # ── Stage 3: IR v2 → IR v3 (框架映射) ─────

    def map_to_framework(self, semantic: SemanticActionSequence) -> FrameworkCallSequence:
        test_cases = []
        for scenario in semantic.scenarios:
            tc = self._map_scenario(scenario)
            test_cases.append(tc)
        return FrameworkCallSequence(test_cases=test_cases)

    def _map_scenario(self, scenario: SemanticScenario) -> TestCaseIR:
        """将语义场景映射为框架级测试用例，使用 CodeGenerator 进行框架特定的渲染"""
        steps: list[FrameworkStep] = []
        page_class = scenario.page_flow[-1] if scenario.page_flow else "HomePage"
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
        imports = set(import_style.direct_imports)
        for imp in import_style.from_imports:
            imports.add(imp)

        # KB 集成：用高置信度 KB 知识替换硬编码的默认包名
        if self.kb_manager:
            imports = self._apply_kb_imports(imports)

        safe_name = self._sanitize_test_name(scenario.name)
        return TestCaseIR(
            name=f"test_{safe_name}",
            description=f"场景: {' → '.join(scenario.page_flow)}",
            imports=sorted(imports),
            fixtures=["page"],
            steps=steps,
        )

    # ── Stage 4: IR v3 → 代码 + 自检 ──────────

    def generate_and_verify(self, call_seq: FrameworkCallSequence,
                            recording: RawRecording) -> list[dict]:
        results = []
        assertion_map = self._build_assertion_map(recording)

        # 预先解析 KB 中的包名，供整个生成周期使用
        if self.kb_manager:
            self._resolved_package = self._resolve_package_from_kb()

        for i, tc in enumerate(call_seq.test_cases):
            # 注入 DOM diff 断言
            candidates = assertion_map.get(i, [])
            for c in candidates:
                tc.steps.append(FrameworkStep(
                    kind=StepKind.ASSERT,
                    calls=[MethodCall(method="assert_diff", component="page",
                                      args=[c])],
                    comment=c,
                ))

            # 将 FrameworkStep 列表渲染为代码字符串
            steps_code = [self._render_framework_step(s) for s in tc.steps]

            # 应用 StyleLearner + KB 调整代码结构
            if self._style_profile:
                steps_code = self._apply_style(steps_code, self._style_profile)

            if self.kb_manager:
                steps_code = self._apply_kb_conventions(steps_code)

            code = self.script_gen.generate(
                test_name=tc.name,
                imports=list(tc.imports),
                fixtures=tc.fixtures,
                steps=steps_code,
                description=tc.description,
                style_profile=self._style_profile,
            )

            # KB 集成: 用实际包名替换模板中的硬编码 package 声明
            if self.kb_manager and self._resolved_package:
                code = self._apply_kb_package_to_code(code)

            # 提取测试数据
            captured_values = self._extract_captured_values(recording)
            domain = self._extract_domain(recording)
            data_def = self.script_gen.generate_data(captured_values, domain)
            data_code = self.code_generator.generate_test_data(data_def)

            # 自检
            language = self._detect_language()
            verify = self.self_test.run(code, tc.name, language=language,
                                        project_dir=str(self.project_root))

            # P1: 自检失败 → 自动修复重试
            fix_info = None
            if verify.status != "passed":
                error_text = verify.stderr + "\n" + verify.stdout
                fix_info = self.self_test.fix_and_retry(
                    code, tc.name, error_text, language=language,
                    project_dir=str(self.project_root),
                )
                if fix_info["passed"]:
                    code = fix_info["fixed_code"]
                    verify = SelfTestResult(status="passed", confidence=0.85)

            results.append({
                "test_name": tc.name,
                "code": code,
                "data_code": data_code,
                "data_def": data_def,
                "verify": verify,
                "fix_info": fix_info,
                "review_needed": tc.review_needed or verify.status != "passed",
            })

        return results

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

    def _render_framework_step(self, step: FrameworkStep) -> str:
        """将 FrameworkStep 渲染为框架风格的代码字符串。

        委托给适配器的 CodeGenerator.render_step()，确保按目标语言/框架语法生成。
        """
        return self.code_generator.render_step(step)

    def _apply_style(self, steps: list[str], profile: StyleProfile) -> list[str]:
        """将 StyleLearner 学到的风格应用到步骤代码中。

        覆盖：引号风格、注释风格、断言风格、命名惯例。
        """
        # 引号风格
        if profile.quote_style == "single":
            steps = [s.replace('"', "'") for s in steps]

        # 注释风格：Java 用 //，Python 用 #
        if profile.language == "java":
            steps = [s.replace("# ", "// ") for s in steps]

        # 断言风格
        if profile.assert_style in ("testng_assert", "assertj"):
            assertion_style = self.code_generator.get_assertion_style()
            if assertion_style.type == "testng_assert":
                steps = [s.replace("assert ", "Assert.") for s in steps]
            elif assertion_style.type == "assertj":
                steps = [s.replace("assert ", "assertThat(") for s in steps]

        # 注释密度控制：低密度项目中去掉多余注释
        if profile.comment_density < 0.05:
            steps = [s for s in steps if not s.strip().startswith("#") and not s.strip().startswith("//")]

        return steps

    @staticmethod
    def _sanitize_test_name(name: str) -> str:
        """清除测试名中的非法字符（@, ., 空格等）"""
        import re
        # 保留字母、数字、下划线、连字符、汉字
        safe = re.sub(r'[^a-zA-Z0-9_\-一-鿿]', '_', name)
        # 合并且修剪首尾下划线
        safe = re.sub(r'_+', '_', safe).strip('_')
        return safe or "unnamed"

    def _resolve_package_from_kb(self) -> str:
        """从 KB 或源码扫描提取基础包名（所有包的公共前缀）。

        返回 "" 表示无法检测（将使用适配器默认值），
        返回非空字符串为检测到的包名。
        """
        if not self.kb_manager:
            return ""
        packages: list[str] = []
        # get_high_confidence_knowledge 返回 {category: {item_key: item_value}}
        for category_items in self.kb_manager.get_high_confidence_knowledge().values():
            for item_key, item_value in category_items.items():
                if item_key.startswith("java.") or "." in item_key:
                    pkg = item_value.get("package", "")
                    if not pkg:
                        parts = item_key.split(".", 1)
                        if len(parts) == 2:
                            class_parts = parts[1].rsplit(".", 1)
                            if len(class_parts) == 2:
                                pkg = class_parts[0]
                    if pkg:
                        packages.append(pkg)
        if packages:
            if len(packages) == 1:
                return packages[0]
            common = packages[0].split(".")
            for pkg in packages[1:]:
                parts = pkg.split(".")
                i = 0
                while i < len(common) and i < len(parts) and common[i] == parts[i]:
                    i += 1
                common = common[:i]
                if not common:
                    return max(set(packages), key=packages.count)
            return ".".join(common)

        # KB 无结果时，扫描源码兜底
        from .adapter.base import scan_java_source_for_package
        result = scan_java_source_for_package(str(self.kb_manager.project_root))
        if result is not None:
            return result
        return ""

    def _apply_kb_imports(self, imports: set[str]) -> set[str]:
        """用 KB 中的实际包名替换 import 中的硬编码默认值。

        硬编码默认如 com.acme.* → KB 推导的 com.enterprise.*。
        """
        pkg = self._resolved_package
        if not pkg or pkg == "com.acme":
            return imports

        replacements = {"com.acme": pkg}
        fixed = set()
        for imp in imports:
            for old, new in replacements.items():
                if old in imp:
                    imp = imp.replace(old, new)
            fixed.add(imp)
        return fixed

    def _apply_kb_package_to_code(self, code: str) -> str:
        """用 KB 解析的包名替换生成代码中的硬编码 package/import 声明。"""
        import re
        pkg = self._resolved_package
        if not pkg or pkg == "com.acme":
            return code
        # 替换: package com.acme.tests; → package com.enterprise.tests;
        code = re.sub(r'\bcom\.acme\b', pkg, code)
        return code

    def _apply_kb_conventions(self, steps: list[str]) -> list[str]:
        """将 KB 中的命名/定位器/导入约定应用到已生成的步骤代码中。

        KB 约定在适配器层面已被使用（Resolver、LocatorStrategy 等），此方法
        处理跨适配器的后置调整：命名规则替换、import 别名、自定义注释格式等。
        """
        if not self.kb_manager:
            return steps

        # 命名约定：KB 中注册的命名模式 → 代码中替换
        naming_rules = self.kb_manager.get_naming_rules()
        for rule in naming_rules:
            if isinstance(rule, dict):
                pattern = rule.get("pattern", "")
                replacement = rule.get("replacement", "")
                if pattern and replacement:
                    steps = [s.replace(pattern, replacement) for s in steps]

        # 定位器约定：KB 指定的自定义定位器格式 → 调整硬编码的定位器字符串
        locator_conventions = self.kb_manager.get_locator_conventions()
        if locator_conventions:
            preferred = locator_conventions.get("preferred_attribute", "")
            if preferred and preferred not in ("data-test", "id"):
                for attr in ("data-test", "data-testid"):
                    steps = [s.replace(f"[{attr}=", f"[{preferred}=") for s in steps]

        # 组件类型映射：KB 注册的自定义组件名 → 替换默认 Target/PageElement
        high_conf = self.kb_manager.get_high_confidence_knowledge()
        for key, item in high_conf.items():
            if key.startswith("component."):
                default_name = item.get("aria_role", "")
                custom_name = item.get("class_name", "")
                if default_name and custom_name and default_name != custom_name:
                    steps = [s.replace(default_name, custom_name) for s in steps]

        return steps

    def _detect_language(self) -> str:
        """检测目标语言。优先从 StyleProfile，其次从适配器类名推断。"""
        if self._style_profile:
            return self._style_profile.language
        adapter_name = type(self.code_generator).__name__
        if "Java" in adapter_name or "Fluent" in adapter_name:
            return "java"
        return "python"

    # ── 风格学习 ──────────────────────────────

    def learn_style(self, test_dir: str) -> StyleProfile:
        self._style_profile = self.style_learner.learn(test_dir)
        return self._style_profile

    def set_style(self, profile: StyleProfile):
        self._style_profile = profile

    # ── BAW 模式挖掘与生成 ────────────────────

    def mine_baw_patterns(self, semantic_sequences: list[SemanticActionSequence]) -> list[dict]:
        all_action_sequences = []
        for seq in semantic_sequences:
            for scenario in seq.scenarios:
                all_action_sequences.append(scenario.actions)
        patterns = self.action_recognizer.recognize_pattern(all_action_sequences)
        for p in patterns:
            p["baw_name"] = self._derive_baw_name(p)
        return patterns

    def generate_baw_from_patterns(self, patterns: list[dict]) -> list[dict]:
        results = []
        for p in patterns:
            component_calls = p.get("component_calls", [])
            if not component_calls:
                component_calls = [{"component": "page", "method": p.get("pattern", "").split(" → ")[0]}]
            p["class_name"] = p.get("baw_name", "GeneratedBAW")
            code = self.baw_gen.generate_from_pattern(p, component_calls)
            results.append({"pattern": p, "code": code})
        return results

    def _derive_baw_name(self, pattern: dict) -> str:
        pattern_str = pattern.get("pattern", "")
        if "input" in pattern_str.lower():
            return "SearchAndFilter"
        if "click" in pattern_str.lower():
            return "NavigateAndClick"
        return "CompositeOperation"

    # ── 辅助方法 ──────────────────────────────

    def _extract_captured_values(self, recording: RawRecording) -> dict:
        values = {}
        for step in recording.steps:
            action = step.action if isinstance(step.action, ActionType) else ActionType(step.action)
            if action == ActionType.INPUT and step.value:
                label = step.target.label if step.target else "unknown"
                key = label.replace(" ", "_").lower() if label else "field"
                values[key] = step.value
        return values

    def _extract_domain(self, recording: RawRecording) -> str:
        for step in recording.steps:
            action = step.action if isinstance(step.action, ActionType) else ActionType(step.action)
            if action == ActionType.NAVIGATE and step.target and step.target.url:
                from urllib.parse import urlparse
                path = urlparse(step.target.url).path.strip("/")
                parts = [p for p in path.split("/") if p]
                return parts[0] if parts else "unknown"
        return "unknown"

    # ── 组件发现 ──────────────────────────────

    def discover_components(self, page) -> list[dict]:
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
            self._components[name] = results[-1]
        return results

    # ── 差异分析 ──────────────────────────────

    def diff_snapshots(self, recording: RawRecording) -> list[str]:
        """对比录制中所有连续快照对，收集全部断言候选。

        不再仅对比最后两张快照 — 遍历所有相邻对 (0-1, 1-2, ... N-1-N)，
        汇总所有差异产生的断言候选。
        """
        snapshots = list(recording.snapshots.values())
        if len(snapshots) < 2:
            return []

        all_candidates = []
        for i in range(len(snapshots) - 1):
            before = snapshots[i]
            after = snapshots[i + 1]
            result = self.dom_differ.diff(
                before.aria_snapshot, after.aria_snapshot,
                before.url, after.url,
                before.layout_info, after.layout_info,
            )
            all_candidates.extend(result.assertion_candidates)

        return all_candidates
