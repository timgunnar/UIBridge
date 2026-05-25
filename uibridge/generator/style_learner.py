"""风格学习器 — 分析项目中已有测试脚本，学习代码风格。支持 Python AST 和 Java javalang。"""

import ast
import re
from pathlib import Path
from dataclasses import dataclass, field
from glob import glob
import logging

logger = logging.getLogger(__name__)


@dataclass
class StyleProfile:
    """代码风格画像"""
    language: str = "python"  # python / java

    # Import
    import_grouping: str = "mixed"
    quote_style: str = "double"

    # Fixture / Setup
    fixture_name_convention: str = "snake_case"
    fixture_decorator: bool = True
    use_before_method: bool = False  # Java: @BeforeMethod

    # Organization
    use_test_class: bool = True
    class_prefix: str = "Test"

    # Assertion
    assert_style: str = "pytest_assert"  # pytest_assert / self_assert / assertj / testng_assert

    # Docstrings / JavaDoc
    use_docstrings: bool = True
    docstring_style: str = "triple_double"

    # Comments
    comment_density: float = 0.0
    inline_comment_style: str = "hash_space"

    # Naming
    test_method_prefix: str = "test_"
    variable_naming: str = "snake_case"
    test_annotation: str = ""  # Java: @Test

    # Java-specific
    package_name: str = ""
    extends_class: str = ""


def _safe_get_docstring(node: ast.AST) -> str | None:
    """ast.get_docstring 安全版 — 捕获对非函数/类/模块节点的 TypeError"""
    try:
        return ast.get_docstring(node)
    except TypeError:
        return None


def _is_fixture_decorator(d: ast.expr) -> bool:
    """检测装饰器是否为 fixture 变体（@fixture / @pytest.fixture / @pytest_fixture 等）"""
    if isinstance(d, ast.Name) and d.id == "fixture":
        return True
    if isinstance(d, ast.Attribute) and d.attr == "fixture":
        # e.g., @pytest.fixture
        return True
    return False


class StyleLearner:
    """学习项目中已有测试脚本的代码风格，支持 Python 和 Java"""

    def __init__(self):
        self.profile = StyleProfile()

    def learn(self, test_dir: str) -> StyleProfile:
        """从测试目录学习代码风格"""
        py_scripts = glob(f"{test_dir}/**/test_*.py", recursive=True)
        if not py_scripts:
            py_scripts = glob(f"{test_dir}/**/*test*.py", recursive=True)

        java_scripts = glob(f"{test_dir}/**/*Test*.java", recursive=True)

        if py_scripts:
            return self._learn_python(py_scripts)
        elif java_scripts:
            return self._learn_java(java_scripts)
        return self.profile

    def learn_from_files(self, file_paths: list[str]) -> StyleProfile:
        """从指定文件列表学习风格"""
        py_files = [f for f in file_paths if f.endswith('.py')]
        java_files = [f for f in file_paths if f.endswith('.java')]

        if py_files:
            return self._learn_python(py_files)
        elif java_files:
            return self._learn_java(java_files)
        return self.profile

    # ── Python 学习 ─────────────────────────────

    def _learn_python(self, scripts: list[str]) -> StyleProfile:
        profiles = [self._analyze_python(s) for s in scripts[:50]]
        profiles = [p for p in profiles if p is not None]
        if not profiles:
            return self.profile

        self.profile.language = "python"
        self.profile.quote_style = self._most_common(p.quote_style for p in profiles)
        self.profile.use_test_class = self._most_common(p.use_test_class for p in profiles)
        self.profile.assert_style = self._most_common(p.assert_style for p in profiles)
        self.profile.use_docstrings = self._most_common(p.use_docstrings for p in profiles)
        self.profile.comment_density = sum(p.comment_density for p in profiles) / max(len(profiles), 1)
        self.profile.fixture_decorator = self._most_common(p.fixture_decorator for p in profiles)
        self.profile.test_method_prefix = self._detect_prefix(profiles)
        self.profile.import_grouping = self._most_common(p.import_grouping for p in profiles)
        self.profile.class_prefix = self._most_common(p.class_prefix for p in profiles)
        self.profile.docstring_style = self._most_common(p.docstring_style for p in profiles)
        self.profile.inline_comment_style = self._most_common(p.inline_comment_style for p in profiles)
        self.profile.variable_naming = self._most_common(p.variable_naming for p in profiles)
        self.profile.fixture_name_convention = self._most_common(p.fixture_name_convention for p in profiles)
        return self.profile

    def _analyze_python(self, path_or_source: str) -> StyleProfile | None:
        p = StyleProfile()
        source = self._read_source(path_or_source)
        if source is None:
            return None

        p.quote_style = "double" if source.count('"') > source.count("'") * 0.5 else "single"

        try:
            tree = ast.parse(source)
            p.use_test_class = any(
                isinstance(node, ast.ClassDef) and node.name.startswith("Test")
                for node in ast.walk(tree)
            )
            p.use_docstrings = any(
                isinstance(node, ast.FunctionDef) and
                _safe_get_docstring(node) is not None
                for node in ast.walk(tree)
            )
            p.fixture_decorator = any(
                isinstance(node, ast.FunctionDef) and
                any(_is_fixture_decorator(d) for d in node.decorator_list)
                for node in ast.walk(tree)
            )
            # 检测测试类前缀
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                    p.class_prefix = "Test"
                    break
                elif isinstance(node, ast.ClassDef) and "Test" in node.name:
                    p.class_prefix = ""

            # 检测方法名前缀
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                    p.test_method_prefix = "test_"
                    break

            # 检测 import 分组风格
            from_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))
            direct_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Import) and not isinstance(n, ast.ImportFrom))
            if from_count > direct_count * 2:
                p.import_grouping = "from_heavy"
            elif direct_count > from_count * 2:
                p.import_grouping = "direct_heavy"
            else:
                p.import_grouping = "mixed"

            # 检测文档字符串风格
            for node in ast.walk(tree):
                try:
                    doc = ast.get_docstring(node)
                except TypeError:
                    # ast.get_docstring raises TypeError for nodes that can't have docstrings
                    continue
                if doc:
                    p.docstring_style = "triple_double" if '"""' in source else "triple_single"
                    break

            # 检测变量命名约定
            if re.search(r'\b[a-z]+_[a-z]+\s*=', source):
                p.variable_naming = "snake_case"

            # 检测 fixture 命名约定
            pattern = source
            if re.search(r'def\s+([a-z]+_[a-z_]+)\s*\(', pattern):
                p.fixture_name_convention = "snake_case"
        except SyntaxError:
            pass

        total_lines = source.count("\n") + 1
        comment_lines = sum(1 for line in source.split("\n") if line.strip().startswith("#"))
        p.comment_density = comment_lines / max(total_lines, 1)
        # 内联注释风格
        inline_comments = [l for l in source.split("\n") if "#" in l and not l.strip().startswith("#")]
        p.inline_comment_style = "hash_space" if any("  #" in l for l in inline_comments) else "hash"
        return p

    # ── Java 学习 ───────────────────────────────

    def _learn_java(self, scripts: list[str]) -> StyleProfile:
        profiles = [self._analyze_java(s) for s in scripts[:50]]
        profiles = [p for p in profiles if p is not None]
        if not profiles:
            return self.profile

        self.profile.language = "java"
        self.profile.use_test_class = True
        self.profile.assert_style = self._most_common(p.assert_style for p in profiles)
        self.profile.comment_density = sum(p.comment_density for p in profiles) / max(len(profiles), 1)
        self.profile.test_annotation = self._most_common(p.test_annotation for p in profiles)
        self.profile.package_name = self._most_common(p.package_name for p in profiles)
        self.profile.test_method_prefix = self._most_common(p.test_method_prefix for p in profiles)
        self.profile.extends_class = self._most_common(p.extends_class for p in profiles)
        self.profile.import_grouping = self._most_common(p.import_grouping for p in profiles)
        self.profile.class_prefix = self._most_common(p.class_prefix for p in profiles)
        self.profile.variable_naming = self._most_common(p.variable_naming for p in profiles)
        return self.profile

    def _analyze_java(self, path_or_source: str) -> StyleProfile | None:
        p = StyleProfile(language="java")
        source = self._read_source(path_or_source)
        if source is None:
            return None

        # 检测注解
        if "@Test" in source:
            p.test_annotation = "@Test"
        if re.search(r'@Test\s*\(\s*priority', source):
            p.test_annotation = "@Test(priority=...)"

        # 断言风格
        if "assertThat" in source or "Assertions.assertThat" in source:
            p.assert_style = "assertj"
        elif "assertEquals" in source or "assertTrue" in source:
            p.assert_style = "testng_assert"

        # Package
        pkg_match = re.search(r'package\s+([\w.]+)\s*;', source)
        if pkg_match:
            p.package_name = pkg_match.group(1)

        # 方法名前缀 — 检测 testXxx 或 shouldXxx 模式
        method_matches = re.findall(r'(?:void|boolean|String|int|long)\s+(test\w+)\s*\(', source)
        if not method_matches:
            method_matches = re.findall(r'(?:void|boolean|String|int|long)\s+(should\w+)\s*\(', source)
        if method_matches:
            first = method_matches[0]
            if first.startswith("test"):
                p.test_method_prefix = "test"
            elif first.startswith("should"):
                p.test_method_prefix = "should"

        # extends
        extends_match = re.search(r'extends\s+(\w+)', source)
        if extends_match:
            p.extends_class = extends_match.group(1)

        # 类名前缀检测
        class_match = re.search(r'class\s+(Test\w+)\s+', source)
        if class_match:
            p.class_prefix = "Test"
        class_match = re.search(r'class\s+(\w+Test)\s+', source)
        if class_match:
            p.class_prefix = ""

        # import 分组：检查是否有 static imports
        if "import static" in source:
            p.import_grouping = "static_present"
        else:
            p.import_grouping = "standard"

        # 变量命名约定
        if re.search(r'\b[A-Z][a-z]+Builder\b', source):
            p.variable_naming = "PascalCase"
        else:
            p.variable_naming = "camelCase"

        # 注释密度
        total_lines = source.count("\n") + 1
        comment_lines = sum(1 for line in source.split("\n")
                           if line.strip().startswith("//") or line.strip().startswith("*"))
        p.comment_density = comment_lines / max(total_lines, 1)
        return p

    # ── 辅助 ────────────────────────────────────

    def _read_source(self, path_or_source: str) -> str | None:
        """读取源码：先尝试作为文件路径，失败则视为源码字符串"""
        try:
            p = Path(path_or_source)
            if p.exists() and p.is_file():
                return p.read_text(encoding="utf-8")
        except (OSError, ValueError):
            pass
        if "\n" in path_or_source or "class " in path_or_source or "package " in path_or_source:
            return path_or_source
        return None

    def _most_common(self, values) -> str:
        from collections import Counter
        lst = [v for v in values if v]
        return Counter(lst).most_common(1)[0][0] if lst else ""

    def _detect_prefix(self, profiles: list[StyleProfile]) -> str:
        """从已分析的文件中检测测试方法前缀"""
        prefixes = [p.test_method_prefix for p in profiles if p.test_method_prefix]
        return self._most_common(prefixes) if prefixes else "test_"
