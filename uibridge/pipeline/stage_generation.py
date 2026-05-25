"""Stage 4: Code Generation — FrameworkCallSequence → Test Code + Self-Test"""
import logging
import re

logger = logging.getLogger(__name__)

from ..engine.ir.raw_recording import RawRecording, ActionType
from ..engine.ir.framework_call import (
    FrameworkCallSequence, FrameworkStep, MethodCall, StepKind,
)
from ..engine.self_test import SelfTestResult
from ..adapter.base import resolve_package, extract_domain
from ..generator.style_learner import StyleProfile


class StageGeneration:
    MAX_FIX_RETRIES = 3

    def __init__(self, code_generator, data_formatter, action_recognizer,
                 component_resolver, script_gen, self_test, stage_mapping=None,
                 kb_manager=None, profile_manager=None, project_root="."):
        self.code_generator = code_generator
        self.data_formatter = data_formatter
        self.action_recognizer = action_recognizer
        self.component_resolver = component_resolver
        self.script_gen = script_gen
        self.self_test = self_test
        self._stage_mapping = stage_mapping
        self.kb_manager = kb_manager
        self.profile_manager = profile_manager
        self.project_root = project_root
        self._style_profile = None
        self._resolved_package = ""
        self._kb_items_used: set[tuple[str, str]] = set()  # (category, item_id)

    def generate_and_verify(self, call_seq: FrameworkCallSequence,
                            recording: RawRecording) -> list[dict]:
        results = []
        assertion_map = self._stage_mapping._build_assertion_map(recording)

        # 从画像读取输出配置（要生成的文件类型 + 输出路径提示）
        output_types, output_hints = self._load_output_config()

        # 预先解析 KB 中的包名，供整个生成周期使用
        if self.kb_manager:
            self._resolved_package = resolve_package(
                str(self.kb_manager.project_root) if hasattr(self.kb_manager, 'project_root') else "",
                self.kb_manager, "")

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
            steps_code = [self._stage_mapping._render_framework_step(s) for s in tc.steps]

            # 应用 StyleLearner + KB 调整代码结构
            if self._style_profile:
                steps_code = self._apply_style(steps_code, self._style_profile)

            if self.kb_manager:
                steps_code = self._apply_kb_conventions(steps_code)

            # 由 layer_structure 驱动，遍历所有 managed_by_user=False 的层
            code = ""
            data_code = ""
            data_def = None

            layers = self._get_generatable_layers()

            # 无画像时回退：从 output_config 驱动，保持向后兼容
            if not layers:
                for ot in output_types:
                    layers.append({"maps_to": ot,
                                   "dir": output_hints.get(ot, {}).get("dir", "")})
            for layer in layers:
                maps_to = layer.get("maps_to", "")
                if not maps_to or maps_to not in output_types:
                    continue

                template_path = output_hints.get(maps_to, {}).get("template", "")

                if maps_to == "test_script":
                    code = self.script_gen.generate(
                        test_name=tc.name,
                        imports=list(tc.imports),
                        fixtures=tc.fixtures,
                        steps=steps_code,
                        description=tc.description,
                        style_profile=self._style_profile,
                        template_path=template_path,
                    )

                    # KB 集成: 用实际包名替换模板中的硬编码 package 声明
                    if self.kb_manager and self._resolved_package:
                        code = self._apply_kb_package_to_code(code)

                elif maps_to == "test_data":
                    captured_values = self._stage_mapping._extract_captured_values(recording)
                    domain = "unknown"
                    for step_ in recording.steps:
                        if step_.action == ActionType.NAVIGATE and step_.target and step_.target.url:
                            domain = extract_domain(step_.target.url)
                            if not domain:
                                from urllib.parse import urlparse
                                path = urlparse(step_.target.url).path.strip("/")
                                parts = [p for p in path.split("/") if p]
                                domain = parts[0] if parts else "unknown"
                            break
                    data_def = self.script_gen.generate_data(captured_values, domain)
                    data_code = self.code_generator.generate(data_def, layer_config={
                        "maps_to": maps_to, "template": template_path,
                        "dir": layer.get("dir", ""), "name": layer.get("name", ""),
                    })

                else:
                    # 自定义层暂不自动生成，记录日志后跳过
                    logger.warning("Skipping custom layer '%s' (maps_to=%s): not yet supported",
                                   layer.get("name"), maps_to)

            # 自检（仅当生成了测试脚本时）
            language = self._detect_language()
            verify = SelfTestResult(status="skipped", confidence=0.0)
            fix_info = None

            if code:
                verify = self.self_test.run(code, tc.name, language=language,
                                            project_dir=str(self.project_root))

                # P1: 自检失败 → 自动修复重试
                if verify.status != "passed":
                    error_text = verify.stderr + "\n" + verify.stdout
                    fix_info = self.self_test.fix_and_retry(
                        code, tc.name, error_text, language=language,
                        project_dir=str(self.project_root),
                        max_retries=self.MAX_FIX_RETRIES,
                    )
                    if fix_info["passed"]:
                        code = fix_info["fixed_code"]
                        verify = SelfTestResult(status="passed", confidence=0.85)

            # Channel 1: Feedback self-test results to KB
            if self.kb_manager and self._kb_items_used:
                passed = verify.status == "passed"
                for category, item_id in self._kb_items_used:
                    try:
                        self.kb_manager.record_self_test_result(item_id, category, passed)
                    except Exception:
                        logger.warning("Failed to record self-test result for %s/%s",
                                       category, item_id, exc_info=True)

            results.append({
                "test_name": tc.name,
                "code": code,
                "data_code": data_code,
                "data_def": data_def,
                "verify": verify,
                "fix_info": fix_info,
                "review_needed": tc.review_needed or verify.status != "passed",
                "kb_items_updated": len(self._kb_items_used),
                "output_hints": output_hints,
            })
            self._kb_items_used.clear()

        return results

    def _load_output_config(self) -> tuple[set[str], dict]:
        """从画像读取输出配置。

        Returns:
            (output_types, output_hints)
            - output_types: {"test_script", "test_data"} 等要生成的类型集合
            - output_hints: {"test_script": {"dir": "tests", "template": "..."}, ...}

        无画像时回退为默认行为（生成 test_script + test_data）。
        """
        default_types = {"test_script", "test_data"}
        default_hints = {"test_script": {"dir": "tests"}, "test_data": {"dir": "data"}}

        if not self.kb_manager:
            return default_types, default_hints

        profile = self.profile_manager.get_profile() if self.profile_manager else None
        if profile is None:
            return default_types, default_hints

        from ..profile import ProfileField
        output_config = profile.output_config
        if not isinstance(output_config, ProfileField):
            return default_types, default_hints

        config_value = output_config.value
        if not isinstance(config_value, dict):
            return default_types, default_hints

        generate_list = config_value.get("generate", [])
        if not generate_list:
            return default_types, default_hints

        types = set()
        hints = {}
        for entry in generate_list:
            if not isinstance(entry, dict):
                continue
            t = entry.get("type", "")
            if t:
                types.add(t)
                hints[t] = {"dir": entry.get("dir", ""), "template": entry.get("template", "")}

        # layer_structure 的 dir 仅在 output_config 未指定 dir 时补充
        layer_structure = profile.layer_structure
        if isinstance(layer_structure, ProfileField) and isinstance(layer_structure.value, list):
            for layer in layer_structure.value:
                if not isinstance(layer, dict):
                    continue
                dir_val = layer.get("dir", "")
                if not dir_val:
                    continue
                maps_to = layer.get("maps_to", "")
                if maps_to and maps_to in hints and not hints[maps_to]["dir"]:
                    hints[maps_to]["dir"] = dir_val

        return types if types else default_types, hints if hints else default_hints

    def _get_generatable_layers(self) -> list[dict]:
        """Return layers where uibridge should generate code (managed_by_user=False)."""
        if not self.profile_manager:
            return []
        profile = self.profile_manager.get_profile()
        if profile is None:
            return []
        from ..profile import ProfileField
        ls = profile.layer_structure
        if not isinstance(ls, ProfileField) or not isinstance(ls.value, list):
            return []
        return [
            layer for layer in ls.value
            if isinstance(layer, dict) and not layer.get("managed_by_user", True)
        ]

    def _apply_style(self, steps: list[str], profile: StyleProfile) -> list[str]:
        """将 StyleLearner 学到的风格应用到步骤代码中。

        注：引号风格、注释语法、断言风格等语言/框架特定特征，
        由适配器的 render_step() 在代码构造时直接生成正确语法。
        此处仅处理跨语言的代码行级别操作。
        """
        # 注释密度控制：低密度项目中去掉多余注释
        if profile.comment_density < 0.05:
            steps = [s for s in steps if not s.strip().startswith("#") and not s.strip().startswith("//")]

        return steps

    def _apply_kb_package_to_code(self, code: str) -> str:
        """用 KB 解析的包名替换生成代码中的硬编码 package/import 声明。"""
        pkg = self._resolved_package
        default_pkg = getattr(self.code_generator, 'DEFAULT_PACKAGE', 'com.acme')
        if not pkg or pkg == default_pkg:
            return code
        # Track the KB item providing this package convention
        item = self.kb_manager.store.get_by_key("conventions", "convention.package")
        if item:
            self._kb_items_used.add((item.category, item.id))
        # 替换: package com.acme.tests; → package com.enterprise.tests;
        code = re.sub(r'\b' + re.escape(default_pkg) + r'\b', pkg, code)
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
        if naming_rules:
            item = self.kb_manager.store.get_by_key("conventions", "convention.naming")
            if item:
                self._kb_items_used.add((item.category, item.id))

        # 定位器约定：KB 指定的自定义定位器格式 → 调整硬编码的定位器字符串
        locator_conventions = self.kb_manager.get_locator_conventions()
        if locator_conventions:
            preferred = locator_conventions.get("preferred_attribute", "")
            if preferred and preferred not in ("data-test", "id"):
                for attr in ("data-test", "data-testid"):
                    steps = [s.replace(f"[{attr}=", f"[{preferred}=") for s in steps]
            item = self.kb_manager.store.get_by_key("conventions", "convention.locator_priority")
            if item:
                self._kb_items_used.add((item.category, item.id))

        # 组件类型映射：KB 注册的自定义组件名 → 替换默认 Target/PageElement
        component_items = self.kb_manager.get_high_confidence_knowledge()
        for category, entries in component_items.items():
            if category != "components":
                continue
            for comp_key, comp_data in entries.items():
                if not isinstance(comp_data, dict):
                    continue
                default_name = comp_data.get("aria_role", "")
                custom_name = comp_data.get("class_name", "")
                if default_name and custom_name and default_name != custom_name:
                    steps = [s.replace(default_name, custom_name) for s in steps]
                entry = self.kb_manager.store.get_by_key("components", comp_key)
                if entry:
                    self._kb_items_used.add((entry.category, entry.id))

        return steps

    def _detect_language(self) -> str:
        """检测目标语言。优先从 StyleProfile，其次从适配器 target_language 属性。"""
        if self._style_profile:
            return self._style_profile.language
        return getattr(self.code_generator, "target_language", "python")
