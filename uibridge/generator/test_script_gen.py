"""测试脚本生成器"""

import logging

logger = logging.getLogger(__name__)

# ── Stub classes (adapter/ deleted in v0.4.0, moved to scanner+generator) ──
class ScriptDef:
    def __init__(self, class_name="", test_name="", description="", imports=None, fixtures=None, steps=None):
        self.class_name = class_name; self.test_name = test_name; self.description = description
        self.imports = imports or []; self.fixtures = fixtures or []; self.steps = steps or []
class TestDataDef:
    def __init__(self, file_path="", content=""):
        self.file_path = file_path; self.content = content
class CodeGenerator:
    def generate_test_script(self, script_def, template_path=""): raise NotImplementedError
class DataFormatter:
    def format(self, values, context): return TestDataDef()


class TestScriptGenerator:
    """生成测试脚本和测试数据"""

    def __init__(self, code_gen: CodeGenerator, data_fmt: DataFormatter):
        self.code_gen = code_gen
        self.data_fmt = data_fmt

    def generate(self, test_name: str, imports: list[str],
                 fixtures: list[str], steps: list[str],
                 description: str = "",
                 style_profile=None,
                 template_path: str = "") -> str:
        script_def = ScriptDef(
            class_name=self._to_class_name(test_name),
            test_name=test_name,
            description=description,
            imports=list(imports),
            fixtures=list(fixtures),
            steps=list(steps),
        )
        return self.code_gen.generate_test_script(
            script_def, template_path=template_path)

    def generate_data(self, captured_values: dict, domain: str) -> TestDataDef:
        return self.data_fmt.format(captured_values, {"domain": domain})

    def _to_class_name(self, test_name: str) -> str:
        import re
        name = test_name.replace("test_", "", 1) if test_name.startswith("test_") else test_name
        # 安全化：只保留字母数字和下划线
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        return "".join(
            word.capitalize()
            for word in name.split("_")
            if word
        )
