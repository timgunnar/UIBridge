"""模板引擎 — Jinja2 驱动的代码生成器。

CodeGenerator 负责加载模板并渲染生成各类 AW 代码。
支持 Python 和 Java，通过 StyleProfile 控制代码风格。
"""

import logging
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, ChoiceLoader

from .style_learner import StyleProfile

logger = logging.getLogger(__name__)

# 包内置模板目录（fallback 路径）
# __file__ → uibridge/uibridge/generator/engine.py
# 模板在 uibridge/uibridge/templates/codegen/（generator 的父目录）
_PACKAGE_DIR = Path(__file__).parent
_BUNDLED_TEMPLATES = _PACKAGE_DIR.parent / "templates" / "codegen"

# 4-space indent
_INDENT = "    "
_INDENT2 = _INDENT * 2


class CodeGenerator:
    """Jinja2 模板驱动的代码生成器。

    模板搜索顺序：
    1. {project_root}/templates/codegen/{lang}/{type}.jinja2
    2. 包内置模板（fallback）
    """

    def __init__(self, project_root: str = ".", kb_manager=None):
        self.project_root = Path(project_root).resolve()
        self.kb_manager = kb_manager

        project_templates = self.project_root / "templates" / "codegen"
        search_paths = [str(project_templates), str(_BUNDLED_TEMPLATES)]

        existing = [p for p in search_paths if Path(p).is_dir()]
        if not existing:
            existing = [str(_BUNDLED_TEMPLATES)]

        loader = ChoiceLoader([FileSystemLoader(p) for p in existing])
        self.env = Environment(loader=loader, autoescape=False)

    # ── 公开 API ────────────────────────────────────────────────

    def generate_component_aw(self, comp_def, style_profile: Optional[StyleProfile] = None) -> str:
        """生成组件 AW 代码。"""
        style = style_profile or StyleProfile()
        lang = style.language or "python"
        template = self._load_template(lang, "component_aw")
        context = self._build_context(comp_def, style)
        kb = context.get("kb", {})
        context["methods_code"] = self._render_methods(comp_def, style, kb)
        return template.render(**context)

    def generate_business_aw(self, baw_def, style_profile: Optional[StyleProfile] = None) -> str:
        """生成业务 AW 代码。"""
        style = style_profile or StyleProfile()
        lang = style.language or "python"
        template = self._load_template(lang, "business_aw")
        context = self._build_context(baw_def, style)
        context["operations_code"] = self._render_operations(baw_def, style)
        return template.render(**context)

    def generate_test_script(self, script_def, style_profile: Optional[StyleProfile] = None) -> str:
        """生成测试脚本代码。"""
        style = style_profile or StyleProfile()
        lang = style.language or "python"
        template = self._load_template(lang, "test_script")
        context = self._build_context(script_def, style)
        kb = context.get("kb", {})
        context["imports_code"] = self._render_imports(script_def, style, kb)
        context["steps_code"] = self._render_steps(script_def, style)
        context["fixtures_code"] = self._render_fixtures(script_def, style, kb)
        return template.render(**context)

    def generate_test_data(self, data_def, style_profile: Optional[StyleProfile] = None) -> str:
        """生成测试数据文件内容。"""
        style = style_profile or StyleProfile()
        lang = style.language or "python"
        template = self._load_template(lang, "test_data")
        context = self._build_context(data_def, style)
        return template.render(**context)

    def generate_xpath_register(self, xpath_def, style_profile: Optional[StyleProfile] = None) -> str:
        """生成 XPath 注册文件。"""
        style = style_profile or StyleProfile()
        lang = style.language or "python"
        template = self._load_template(lang, "xpath_register")
        context = self._build_context(xpath_def, style)
        return template.render(**context)

    # ── 模板加载 ────────────────────────────────────────────────

    def _load_template(self, lang: str, name: str):
        template_path = f"{lang}/{name}.jinja2"
        return self.env.get_template(template_path)

    def _build_context(self, def_obj, style: StyleProfile) -> dict:
        """构建模板渲染上下文，含 KB 查询结果（如有 kb_manager）。"""
        ctx = {
            "def": def_obj,
            "style": style,
            "naming": self._naming_from_style(style),
        }
        if self.kb_manager:
            ctx["kb"] = self._query_kb()
        else:
            ctx["kb"] = {}
        return ctx

    def _query_kb(self) -> dict:
        """从 KB 查询生成所需的团队知识上下文。

        查询 4 类 convention：naming、imports、assertions、locators。
        全部 defensive — 任一查询失败不影响其他。
        """
        kb_ctx = {}
        try:
            naming = self.kb_manager.get_naming_rules()
            if naming:
                kb_ctx["naming"] = naming
        except Exception:
            logger.debug("KB naming query failed", exc_info=True)

        try:
            imports = self.kb_manager.store.get_by_key("conventions", "convention.imports")
            if imports:
                kb_ctx["imports"] = imports.value
        except Exception:
            logger.debug("KB imports query failed", exc_info=True)

        try:
            assertions = self.kb_manager.store.get_by_key("conventions", "convention.assertions")
            if assertions:
                kb_ctx["assertions"] = assertions.value
        except Exception:
            logger.debug("KB assertions query failed", exc_info=True)

        try:
            locators = self.kb_manager.get_locator_conventions()
            if locators:
                kb_ctx["locators"] = locators
            locator_usage = self.kb_manager.store.get_by_key("conventions", "convention.locator_usage")
            if locator_usage:
                kb_ctx["locator_usage"] = locator_usage.value
        except Exception:
            logger.debug("KB locators query failed", exc_info=True)

        return kb_ctx

    def _naming_from_style(self, style: StyleProfile) -> dict:
        """从 StyleProfile 提取命名相关约定的便捷字典。"""
        q = '"' if style.quote_style == "double" else "'"
        prefix = style.test_method_prefix or ("test_" if style.language == "python" else "test")
        return {
            "test_method_prefix": prefix,
            "class_prefix": style.class_prefix,
            "variable_naming": style.variable_naming,
            "fixture_name_convention": style.fixture_name_convention,
            "assert_style": style.assert_style,
            "quote_char": q,
        }

    # ── 代码片段渲染（Python 端预构建，模板只需简单输出） ──────

    def _resolve_param_str(self, params, style: StyleProfile) -> str:
        """将 params 列表转为参数字符串。"""
        parts = []
        for p in params:
            if isinstance(p, dict):
                name = p.get("name", p)
                ptype = p.get("type", "")
                if style.language == "java":
                    ptype = ptype or "String"
                    parts.append(f"{ptype} {name}")
                else:
                    parts.append(name)
            else:
                if style.language == "java":
                    parts.append(f"String {p}")
                else:
                    parts.append(str(p))
        return ", ".join(parts)

    def _render_methods(self, comp_def, style: StyleProfile, kb: dict | None = None) -> str:
        """生成组件方法代码，KB locator 数据决定默认定位器策略。"""
        if not comp_def.methods:
            return ""
        # 从 KB 取定位器策略偏好
        primary_locator = "css"
        if kb:
            loc_usage = kb.get("locator_usage", {}).get("locator_usage", [])
            if loc_usage:
                primary_locator = loc_usage[0].get("type", "css")
            elif kb.get("locators"):
                primary_locator = kb["locators"].get("priority", "css")
        lines = []
        for method in comp_def.methods:
            params_str = self._resolve_param_str(method.params, style)
            lines.append("")
            if style.language == "java":
                lines.append(f"{_INDENT}/**")
                lines.append(f"{_INDENT} * {method.action_type or method.name} 操作")
                lines.append(f"{_INDENT} */")
                lines.append(f"{_INDENT}public void {method.name}({params_str}) {{")
                lines.append(f"{_INDENT2}// TODO: 实现 {method.action_type or method.name} 操作")
                lines.append(f"{_INDENT}}}")
            else:
                lines.append(f"{_INDENT}def {method.name}(self{', ' + params_str if params_str else ''}):")
                lines.append(f'{_INDENT2}"""{method.name}{" [" + method.action_type + "]" if method.action_type else ""}"""')
                lines.append(f"{_INDENT2}# TODO: 实现 {method.action_type or method.name} 操作")
                lines.append(f"{_INDENT2}pass")
        return "\n".join(lines)

    def _render_operations(self, baw_def, style: StyleProfile) -> str:
        """生成业务操作代码。"""
        if not baw_def.operations:
            return ""
        lines = []
        for op in baw_def.operations:
            params_str = self._resolve_param_str(op.params, style)
            lines.append("")
            if style.language == "java":
                lines.append(f"{_INDENT}/**")
                lines.append(f"{_INDENT} * 执行业务操作: {op.name}")
                lines.append(f"{_INDENT} */")
                lines.append(f"{_INDENT}public void {op.name}({params_str}) {{")
                for call in op.calls:
                    args_str = ", ".join(str(a) for a in call.args)
                    lines.append(f"{_INDENT2}{call.component.lower()}.{call.method}({args_str});")
                lines.append(f"{_INDENT}}}")
            else:
                lines.append(f"{_INDENT}def {op.name}(self{', ' + params_str if params_str else ''}):")
                lines.append(f'{_INDENT2}"""执行业务操作: {op.name}"""')
                for call in op.calls:
                    args_str = ", ".join(str(a) for a in call.args)
                    if call.data_binding:
                        lines.append(f"{_INDENT2}# 数据绑定: {call.data_binding}")
                    lines.append(f"{_INDENT2}self.{call.component}.{call.method}({args_str})")
        return "\n".join(lines)

    def _render_imports(self, script_def, style: StyleProfile, kb: dict | None = None) -> str:
        """生成 import 代码，优先使用 script 指定的导入，其次 KB 的 convention.imports。"""
        lines = []
        if script_def.imports:
            for imp in script_def.imports:
                lines.append(imp)
        elif kb and kb.get("imports", {}).get("top_imports"):
            for entry in kb["imports"]["top_imports"][:5]:
                pkg = entry.get("package", entry) if isinstance(entry, dict) else entry
                if style.language == "java":
                    lines.append(f"import {pkg};")
                else:
                    lines.append(f"import {pkg}")
        elif style.language == "java":
            if style.assert_style == "assertj":
                lines.append("import static org.assertj.core.api.Assertions.assertThat;")
            if style.assert_style == "testng_assert":
                lines.append("import org.testng.Assert;")
            if style.test_annotation:
                lines.append("import org.testng.annotations.Test;")
            if style.use_before_method:
                lines.append("import org.testng.annotations.BeforeMethod;")
        return "\n".join(lines) if lines else ""

    def _render_steps(self, script_def, style: StyleProfile) -> str:
        """生成测试步骤代码。"""
        if not script_def.steps:
            return ""
        lines = []
        for step in script_def.steps:
            if isinstance(step, dict):
                desc = step.get("description", "") or str(step)
                code = step.get("code", "")
                lines.append(f"{_INDENT2}# {desc}")
                if code:
                    lines.append(f"{_INDENT2}{code}")
            else:
                lines.append(f"{_INDENT2}# {str(step)}")
        return "\n".join(lines)

    def _render_fixtures(self, script_def, style: StyleProfile, kb: dict | None = None) -> str:
        """生成 fixture 代码，用 KB assertion style 决定断言导入。"""
        if not script_def.fixtures:
            return ""
        lines = []
        # KB assertions 可覆盖 assert_style
        assert_style = style.assert_style
        if kb and kb.get("assertions", {}).get("dominant_style"):
            assert_style = kb["assertions"]["dominant_style"]
        if style.language == "python" and style.fixture_decorator:
            for fixture in script_def.fixtures:
                lines.append("")
                lines.append(f"{_INDENT}@pytest.fixture")
                lines.append(f"{_INDENT}def {fixture}(self):")
                lines.append(f"{_INDENT2}pass")
        elif style.language == "java" and style.use_before_method:
            lines.append("")
            lines.append(f"{_INDENT}@BeforeMethod")
            lines.append(f"{_INDENT}public void setUp() {{")
            for fixture in script_def.fixtures:
                lines.append(f"{_INDENT2}// 准备 fixture: {fixture}")
            lines.append(f"{_INDENT}}}")
        return "\n".join(lines) if lines else ""
