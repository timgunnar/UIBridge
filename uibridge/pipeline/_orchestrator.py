"""核心管道 — 串联录制 → 分析 → 匹配 → 生成 全流程"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

from ..engine.ir.raw_recording import RawRecording, RawStep, ActionType, Target, SelectorSet
from ..engine.ir.semantic_action import SemanticActionSequence, SemanticScenario, SemanticAction
from ..engine.ir.framework_call import (
    FrameworkCallSequence, TestCaseIR, FrameworkStep, Decl, MethodCall, StepKind,
)
from ..engine.recorder import RecordingSession
from ..engine.aria_analyzer import AriaAnalyzer
from ..engine.dom_diff import DOMDiffer
from ..engine.self_test import SelfTestRunner, SelfTestResult
from ..adapter.base import (
    ComponentResolver, LocatorStrategy, ActionRecognizer,
    CodeGenerator, DataFormatter, ElementInfo, ScriptDef,
    sanitize_identifier,
    resolve_package, common_package_prefix,
    extract_domain,
)
from ..generator.style_learner import StyleLearner, StyleProfile
from ..generator.component_aw_gen import ComponentAWGenerator
from ..generator.business_aw_gen import BusinessAWGenerator
from ..generator.test_script_gen import TestScriptGenerator
from ..discovery import DiscoveryService
from .stage_analysis import StageAnalysis
from .stage_mapping import StageMapping
from .stage_generation import StageGeneration
from .stage_recording import StageRecording


class Pipeline:
    """端到端管道: 录制 → IR v1 → IR v2 → IR v3 → 代码"""

    MAX_FIX_RETRIES = 3

    DEFAULT_HOME_PAGE = "HomePage"
    DEFAULT_BASE_PAGE = "BasePage"

    def __init__(
        self,
        component_resolver: ComponentResolver,
        locator_strategy: LocatorStrategy,
        action_recognizer: ActionRecognizer,
        code_generator: CodeGenerator,
        data_formatter: DataFormatter,
        project_root: str = ".",
        kb_manager=None,
        profile_manager=None,
    ):
        self.component_resolver = component_resolver
        self.locator_strategy = locator_strategy
        self.action_recognizer = action_recognizer
        self.code_generator = code_generator
        self.data_formatter = data_formatter
        self.project_root = Path(project_root)
        self.kb_manager = kb_manager
        self.profile_manager = profile_manager
        # 自动播种 KB（如果为空）
        if self.kb_manager:
            self.kb_manager.auto_seed()

        self.aria_analyzer_cls = AriaAnalyzer
        self.dom_differ = DOMDiffer()
        self.self_test = SelfTestRunner()
        self.style_learner = StyleLearner()
        self.caw_gen = ComponentAWGenerator(code_generator, component_resolver)
        self.baw_gen = BusinessAWGenerator(code_generator, action_recognizer)
        self.script_gen = TestScriptGenerator(code_generator, data_formatter)

        self.discovery = DiscoveryService(
            code_generator=code_generator,
            component_resolver=component_resolver,
            action_recognizer=action_recognizer,
            aria_analyzer_cls=self.aria_analyzer_cls,
            kb_manager=kb_manager,
            style_learner=self.style_learner,
            project_root=str(project_root),
        )

        self._components: dict[str, dict] = {}
        self._pages: dict[str, dict] = {}
        self._baw_patterns: dict[str, dict] = {}
        self._style_profile: StyleProfile | None = None
        self._resolved_package: str = ""

        self._recording = StageRecording()

        self._analysis = StageAnalysis(component_resolver=component_resolver,
                                       action_recognizer=action_recognizer,
                                       kb_manager=kb_manager)

        self._mapping = StageMapping(component_resolver=component_resolver,
                                     locator_strategy=locator_strategy,
                                     action_recognizer=action_recognizer,
                                     code_generator=code_generator,
                                     data_formatter=data_formatter,
                                     kb_manager=kb_manager)

        self._generation = StageGeneration(code_generator=code_generator,
                                           data_formatter=data_formatter,
                                           action_recognizer=action_recognizer,
                                           component_resolver=component_resolver,
                                           script_gen=self.script_gen,
                                           self_test=self.self_test,
                                           stage_mapping=self._mapping,
                                           kb_manager=kb_manager,
                                           profile_manager=profile_manager,
                                           project_root=project_root)

    # ── Stage 1: 录制 → IR v1 ─────────────────

    def record(self, page, locator_attrs=None) -> RecordingSession:
        return self._recording.record(page, locator_attrs=locator_attrs)

    # ── Stage 2: IR v1 → IR v2 (语义理解) ─────

    def analyze(self, recording: RawRecording) -> SemanticActionSequence:
        return self._analysis.analyze(recording)

    # ── Stage 3: IR v2 → IR v3 (框架映射) ─────

    def map_to_framework(self, semantic: SemanticActionSequence) -> FrameworkCallSequence:
        return self._mapping.map_to_framework(semantic)

    # ── Stage 4: IR v3 → 代码 + 自检 ──────────

    def generate_and_verify(self, call_seq: FrameworkCallSequence,
                            recording: RawRecording) -> list[dict]:
        self._generation._style_profile = self._style_profile
        return self._generation.generate_and_verify(call_seq, recording)

    def _load_output_config(self) -> tuple[set[str], dict]:
        """Delegate to StageGeneration for backward compatibility."""
        return self._generation._load_output_config()

    def _detect_language(self) -> str:
        """Delegate to StageGeneration for backward compatibility."""
        self._generation._style_profile = self._style_profile
        return self._generation._detect_language()

    # ── 风格学习 ──────────────────────────────

    def learn_style(self, test_dir: str) -> StyleProfile:
        self._style_profile = self.style_learner.learn(test_dir)
        if self._generation:
            self._generation._style_profile = self._style_profile
        return self._style_profile

    def set_style(self, profile: StyleProfile):
        self._style_profile = profile
        if self._generation:
            self._generation._style_profile = profile

    # ── BAW 模式挖掘与生成 ────────────────────

    def mine_baw_patterns(self, semantic_sequences) -> list[dict]:
        return self.discovery.mine_baw_patterns(semantic_sequences)

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

    # ── 组件发现 ──────────────────────────────

    def discover_components(self, page) -> list[dict]:
        results = self.discovery.discover_components(page)
        for r in results:
            self._components[r["name"]] = r
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
