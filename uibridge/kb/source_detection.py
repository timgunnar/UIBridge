"""SourceDetector — automatic project source directory detection.

Supports Maven (single + multi-module), Gradle (Groovy/Kotlin DSL), and Python projects.
"""

import re
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class SourceDetector:
    """Detects project source directory layout for Java and Python projects."""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)

    def detect(self) -> dict[str, str]:
        """自动检测项目源码目录结构，支持 Java 和 Python 项目。

        检测优先级：
        1. pom.xml / build.gradle → Java Maven/Gradle 布局
        2. pyproject.toml / setup.py → Python 项目布局
        3. 递归扫描 src/ 反推实际目录
        4. 兜底返回通用默认值

        Returns:
            {"component_aw": "path/to/aw/", "pages": "path/to/pages/", "tests": "path/to/tests/"}
        """
        root = self.project_root

        # ── Gradle 项目检测 (优先，因为可能有 build.gradle + pom.xml 共存) ──
        gradle_indicators = ["build.gradle", "build.gradle.kts"]
        has_gradle = any((root / f).exists() for f in gradle_indicators)
        if has_gradle:
            gradle_dirs = self._detect_gradle_dirs(root)
            if gradle_dirs:
                return gradle_dirs

        # ── Java/Maven 项目检测 ──
        if (root / "pom.xml").exists():
            return self._detect_java_dirs(root)

        # ── Python 项目检测 ──
        py_indicators = ["pyproject.toml", "setup.py", "setup.cfg"]
        is_python = any((root / f).exists() for f in py_indicators)

        if is_python:
            return self._detect_python_dirs(root)

        # ── 通用检测：递归扫描常见目录名 ──
        detected = self._scan_common_dirs(root)
        if detected:
            return detected

        # ── 兜底 ──
        return {"pages": "src/main/java", "tests": "src/test/java"}

    # ══════════════════════════════════════════════════════════
    # Java / Maven
    # ══════════════════════════════════════════════════════════

    def _detect_java_dirs(self, root: Path) -> dict[str, str]:
        """Java/Maven 项目的目录自动检测，支持多模块项目。"""
        pom = root / "pom.xml"
        if pom.exists():
            modules = self._read_maven_modules(root, pom)
            if modules:
                return self._merge_module_dirs(root, modules)

            try:
                custom_dirs = self._read_pom_source_dirs(pom)
                if custom_dirs:
                    result = self._build_java_result(root, custom_dirs)
                    if result:
                        return result
            except Exception:
                logger.warning("Failed to read custom POM source dirs, falling back to standard layout", exc_info=True)
                pass

        std_pages = root / "src" / "main" / "java"
        if std_pages.exists():
            result = {"pages": "src/main/java", "tests": "src/test/java"}
            aw_dir = self._infer_aw_dir(root, "src/main/java")
            if aw_dir:
                result["component_aw"] = aw_dir
            return result

        detected = self._scan_java_dirs(root)
        if detected:
            return detected

        return {"pages": "src/main/java", "tests": "src/test/java"}

    @staticmethod
    def _read_maven_modules(root: Path, pom: Path) -> list[str]:
        """读取 pom.xml 中的 <modules> 列表。"""
        try:
            content = pom.read_text("utf-8")
            module_matches = re.findall(r'<module>\s*([^<\s]+)\s*</module>', content)
            valid = []
            for m in module_matches:
                if (root / m).is_dir():
                    valid.append(m)
            return valid
        except Exception:
            logger.warning("Failed to read pom.xml for module detection", exc_info=True)
            return []

    @staticmethod
    def _read_pom_source_dirs(pom: Path) -> dict[str, str] | None:
        """读取单个 pom.xml 的 sourceDirectory 和 testSourceDirectory。"""
        try:
            content = pom.read_text("utf-8")
            src_match = re.search(r'<sourceDirectory>\s*([^<\s]+)\s*</sourceDirectory>', content)
            test_match = re.search(r'<testSourceDirectory>\s*([^<\s]+)\s*</testSourceDirectory>', content)
            result = {}
            if src_match:
                result["pages"] = src_match.group(1)
            if test_match:
                result["tests"] = test_match.group(1)
            return result if result else None
        except Exception:
            logger.warning("Failed to read pom.xml source directories", exc_info=True)
            return None

    def _merge_module_dirs(self, root: Path, modules: list[str]) -> dict[str, str]:
        """遍历多个 Maven 模块，合并源码目录。"""
        all_pages = []
        all_tests = []
        all_aw = []

        for module_name in modules:
            module_root = root / module_name
            module_pom = module_root / "pom.xml"

            custom_dirs = None
            if module_pom.exists():
                custom_dirs = self._read_pom_source_dirs(module_pom)

            if custom_dirs:
                if "pages" in custom_dirs:
                    p = str((module_root / custom_dirs["pages"]).relative_to(root))
                    all_pages.append(p)
                if "tests" in custom_dirs:
                    t = str((module_root / custom_dirs["tests"]).relative_to(root))
                    all_tests.append(t)
            else:
                std_main = module_root / "src" / "main" / "java"
                std_test = module_root / "src" / "test" / "java"
                if std_main.exists():
                    all_pages.append(str(std_main.relative_to(root)))
                if std_test.exists():
                    all_tests.append(str(std_test.relative_to(root)))

            aw = self._infer_aw_dir(module_root,
                                     custom_dirs.get("pages", "src/main/java") if custom_dirs else "src/main/java")
            if aw:
                all_aw.append(str((module_root / aw).relative_to(root)))

        result = {}
        if all_pages:
            result["pages"] = self._common_prefix(all_pages)
        if all_tests:
            result["tests"] = self._common_prefix(all_tests)
        if all_aw:
            result["component_aw"] = self._common_prefix(all_aw)

        if "tests" not in result and all_pages:
            result["tests"] = self._infer_test_dir(root, all_pages[0]) or "src/test/java"

        return result if result else {"pages": "src/main/java", "tests": "src/test/java"}

    def _build_java_result(self, root: Path, custom_dirs: dict[str, str]) -> dict[str, str] | None:
        """从 pom.xml 自定义目录构建结果字典。"""
        result = {}
        if "pages" in custom_dirs:
            result["pages"] = custom_dirs["pages"]
            aw_dir = self._infer_aw_dir(root, custom_dirs["pages"])
            if aw_dir:
                result["component_aw"] = aw_dir
        if "tests" in custom_dirs:
            result["tests"] = custom_dirs["tests"]
        else:
            pages = custom_dirs.get("pages", "src/main/java")
            result["tests"] = self._infer_test_dir(root, pages) or "src/test/java"
        if "component_aw" not in result and "pages" in custom_dirs:
            aw_dir = self._infer_aw_dir(root, custom_dirs["pages"])
            if aw_dir:
                result["component_aw"] = aw_dir
        return result if result else None

    # ══════════════════════════════════════════════════════════
    # Gradle
    # ══════════════════════════════════════════════════════════

    def _detect_gradle_dirs(self, root: Path) -> dict[str, str] | None:
        """检测 Gradle 项目（build.gradle / build.gradle.kts）的源码目录。"""
        result = {}

        for gradle_file in ["build.gradle", "build.gradle.kts"]:
            gf = root / gradle_file
            if not gf.exists():
                continue
            try:
                content = gf.read_text("utf-8")
                src_dirs = self._extract_gradle_source_sets(content, root)
                if "pages" in src_dirs:
                    result["pages"] = src_dirs["pages"]
                if "tests" in src_dirs:
                    result["tests"] = src_dirs["tests"]
                if "aw" in src_dirs:
                    result["component_aw"] = src_dirs["aw"]
            except Exception:
                logger.warning("Failed to extract Gradle source directories from build file", exc_info=True)
                pass

        if not result:
            result = self._scan_gradle_src_dirs(root)

        if not result:
            std_main = root / "src" / "main" / "java"
            std_test = root / "src" / "test" / "java"
            if std_main.exists():
                result["pages"] = "src/main/java"
            if std_test.exists():
                result["tests"] = "src/test/java"

        if "component_aw" not in result and "pages" in result:
            aw_dir = self._infer_aw_dir(root, result["pages"])
            if aw_dir:
                result["component_aw"] = aw_dir

        return result if result else None

    @staticmethod
    def _extract_gradle_source_sets(content: str, root: Path) -> dict[str, str]:
        """从 Gradle 构建文件中提取 sourceSets 定义的自定义源码目录。"""
        result = {}

        srcsets_block = re.search(
            r'sourceSets\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}',
            content, re.DOTALL
        )
        search_text = srcsets_block.group(1) if srcsets_block else content

        main_patterns = re.findall(
            r"(?:main\s*\{[^}]*java\s*\{[^}]*srcDirs?\s*[=:]\s*\[([^\]]+)\][^}]*\})"
            r"|(?:main\.java\.srcDirs?\s*[=:]\s*\[([^\]]+)\])",
            search_text, re.DOTALL
        )
        for match_group in main_patterns:
            dirs_str = match_group[0] or match_group[1]
            if dirs_str:
                dirs = re.findall(r"['\"]([^'\"]+)['\"]", dirs_str)
                if dirs:
                    result["pages"] = dirs[0]

        test_patterns = re.findall(
            r"(?:test\s*\{[^}]*java\s*\{[^}]*srcDirs?\s*[=:]\s*\[([^\]]+)\][^}]*\})"
            r"|(?:test\.java\.srcDirs?\s*[=:]\s*\[([^\]]+)\])",
            search_text, re.DOTALL
        )
        for match_group in test_patterns:
            dirs_str = match_group[0] or match_group[1]
            if dirs_str:
                dirs = re.findall(r"['\"]([^'\"]+)['\"]", dirs_str)
                if dirs:
                    result["tests"] = dirs[0]

        return result

    @staticmethod
    def _scan_gradle_src_dirs(root: Path) -> dict[str, str]:
        """扫描 Gradle 项目根目录下的 src/{name}/java 模式。"""
        result = {}
        src_root = root / "src"
        if not src_root.exists():
            return result

        for src_sub in src_root.iterdir():
            if not src_sub.is_dir():
                continue
            java_dir = src_sub / "java"
            if java_dir.exists() and any(java_dir.rglob("*.java")):
                src_name = src_sub.name
                rel = str(java_dir.relative_to(root))
                if src_name in ("main",):
                    result["pages"] = rel
                elif src_name in ("test",):
                    result["tests"] = rel
                elif src_name not in result:
                    if "test" in src_name.lower():
                        result["tests"] = rel
                    else:
                        result["pages"] = rel

        return result

    # ══════════════════════════════════════════════════════════
    # Python
    # ══════════════════════════════════════════════════════════

    def _detect_python_dirs(self, root: Path) -> dict[str, str]:
        """Python 项目的目录自动检测。"""
        result = {}

        for candidate in ["pages", "page_objects", "pageobjects"]:
            if (root / candidate).exists() and any((root / candidate).glob("*.py")):
                result["pages"] = candidate
                break
        if "pages" not in result:
            result["pages"] = "pages"

        for candidate in ["tests", "test_scripts", "testscripts"]:
            if (root / candidate).exists() and any((root / candidate).glob("*.py")):
                result["tests"] = candidate
                break
        if "tests" not in result:
            result["tests"] = "tests"

        for candidate in ["aw", "aaw", "components", "component_aw"]:
            if (root / candidate).exists() and any((root / candidate).glob("*.py")):
                result["component_aw"] = candidate
                break

        return result

    # ══════════════════════════════════════════════════════════
    # Shared Helpers
    # ══════════════════════════════════════════════════════════

    def _infer_aw_dir(self, root: Path, pages_dir: str) -> str | None:
        """从 pages 目录推断 AW/组件封装目录。"""
        pages_path = root / pages_dir
        if not pages_path.exists():
            return None
        parent = pages_path.parent
        for candidate in ["aw", "aaw", "components", "component_aw", "widgets"]:
            candidate_path = parent / candidate
            if candidate_path.exists() and any(candidate_path.rglob("*.java")) or \
               any(candidate_path.rglob("*.py")):
                return str(candidate_path.relative_to(root))
        for candidate in ["aw", "aaw", "components"]:
            candidate_path = pages_path / candidate
            if candidate_path.exists():
                return str(candidate_path.relative_to(root))
        return None

    def _infer_test_dir(self, root: Path, src_dir: str) -> str | None:
        """从源码目录推断测试目录。"""
        candidates = [
            src_dir.replace("main", "test"),
            "src/test/java",
            "test",
        ]
        for c in candidates:
            if (root / c).exists():
                return c
        return None

    def _scan_java_dirs(self, root: Path) -> dict[str, str] | None:
        """扫描项目中实际 .java 文件位置，反推源码目录结构。"""
        src_root = root / "src"
        if not src_root.exists():
            return None
        java_files = list(src_root.glob("**/*.java"))
        if not java_files:
            return None

        result = {}
        test_paths = set()
        main_paths = set()
        aw_paths = set()

        for f in java_files:
            rel = str(f.parent.relative_to(root))
            parts = f.parent.parts
            if "test" in parts or "tests" in parts:
                test_paths.add(rel)
            else:
                main_paths.add(rel)
                if any(p in ("aw", "aaw", "components", "widgets") for p in parts):
                    aw_paths.add(rel)

        if main_paths:
            result["pages"] = self._common_prefix(list(main_paths))
        if test_paths:
            result["tests"] = self._common_prefix(list(test_paths))
        if aw_paths:
            result["component_aw"] = self._common_prefix(list(aw_paths))

        return result if result else None

    def _scan_common_dirs(self, root: Path) -> dict[str, str] | None:
        """通用目录扫描：查找任何包含 .py / .java 文件的目录。"""
        result = {}
        for dir_name, key in [("pages", "pages"), ("tests", "tests"),
                              ("aw", "component_aw"), ("aaw", "component_aw"),
                              ("components", "component_aw")]:
            d = root / dir_name
            if d.exists() and (list(d.rglob("*.py")) or list(d.rglob("*.java"))):
                result[key] = dir_name

        src = root / "src"
        if src.exists():
            for sub in src.iterdir():
                if sub.is_dir():
                    for dir_name, key in [("pages", "pages"), ("tests", "tests"),
                                          ("aw", "component_aw"), ("aaw", "component_aw")]:
                        d = sub / dir_name
                        if d.exists() and key not in result:
                            result[key] = str(d.relative_to(root))

        return result if result else None

    @staticmethod
    def _common_prefix(paths: list[str]) -> str:
        """找多个路径的公共前缀目录。"""
        if not paths:
            return ""
        if len(paths) == 1:
            return paths[0]
        parts_list = [p.replace("\\", "/").split("/") for p in paths]
        common = []
        for i in range(min(len(p) for p in parts_list)):
            chunk = parts_list[0][i]
            if all(p[i] == chunk for p in parts_list):
                common.append(chunk)
            else:
                break
        return "/".join(common) if common else ""
