"""KBManager — lifecycle management: seed → query → feedback → evolve"""

import re
import time
from pathlib import Path
from typing import Optional

from .kb_item import KBItem, Confidence, KnowledgeSource
from .kb_store import KBStore
from .kb_extractor import KBExtractor


class KBManager:
    """Manages the full KB lifecycle with confidence scoring and NL interaction."""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.store = KBStore(project_root)
        self.extractor = KBExtractor(project_root)

    # ══════════════════════════════════════════════════════════
    # Seed Phase
    # ══════════════════════════════════════════════════════════

    def seed_from_static_analysis(self, source_dirs: dict[str, str]) -> list[KBItem]:
        """Bulk seed KB from static analysis of source directories.

        source_dirs: {"component_aw": "aaw/", "pages": "pages/", "tests": "tests/"}

        自动检测 Python (.py) 和 Java (.java) 文件并使用对应的提取器。
        """
        seeded = []

        for category, dir_path in source_dirs.items():
            target_dir = self.project_root / dir_path
            if not target_dir.exists():
                continue

            # 优先 Python，其次 Java
            py_files = list(target_dir.glob("**/*.py"))
            java_files = list(target_dir.glob("**/*.java"))

            if py_files:
                for path in py_files:
                    if category == "component_aw":
                        items = self.extractor.extract_from_component_aw(str(path))
                    elif category == "pages":
                        items = self.extractor.extract_from_page_file(str(path))
                    elif category == "tests":
                        items = self.extractor.extract_from_test_script(str(path))
                    else:
                        continue
                    for item in items:
                        self.store.save(item)
                        seeded.append(item)

            if java_files:
                for path in java_files:
                    if category == "tests":
                        items = self.extractor.extract_from_java_test(str(path))
                    else:
                        items = self.extractor.extract_from_java_file(str(path))
                    for item in items:
                        self.store.save(item)
                        seeded.append(item)

        # 批量分析：命名约定提取（在所有文件处理完毕后）
        if seeded:
            naming_items = self.extractor._extract_naming_conventions(seeded)
            for item in naming_items:
                self.store.save(item)

        return seeded

    def auto_detect_source_dirs(self) -> dict[str, str]:
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

    def _detect_java_dirs(self, root: Path) -> dict[str, str]:
        """Java/Maven 项目的目录自动检测，支持多模块项目。"""
        pom = root / "pom.xml"
        if pom.exists():
            # 检查是否为多模块项目
            modules = self._read_maven_modules(root, pom)
            if modules:
                return self._merge_module_dirs(root, modules)

            # 单模块：尝试 pom.xml 自定义目录
            try:
                custom_dirs = self._read_pom_source_dirs(pom)
                if custom_dirs:
                    result = self._build_java_result(root, custom_dirs)
                    if result:
                        return result
            except Exception:
                pass

        # 标准 Maven 布局
        std_pages = root / "src" / "main" / "java"
        std_tests = root / "src" / "test" / "java"
        if std_pages.exists():
            result = {"pages": "src/main/java", "tests": "src/test/java"}
            aw_dir = self._infer_aw_dir(root, "src/main/java")
            if aw_dir:
                result["component_aw"] = aw_dir
            return result

        # 递归扫描反推
        detected = self._scan_java_dirs(root)
        if detected:
            return detected

        return {"pages": "src/main/java", "tests": "src/test/java"}

    # ── Maven 多模块辅助方法 ──

    @staticmethod
    def _read_maven_modules(root: Path, pom: Path) -> list[str]:
        """读取 pom.xml 中的 <modules> 列表。"""
        try:
            content = pom.read_text("utf-8")
            # regex 方式提取，兼容无 xml 库的环境
            module_matches = re.findall(r'<module>\s*([^<\s]+)\s*</module>', content)
            # 过滤掉不存在的模块目录
            valid = []
            for m in module_matches:
                if (root / m).is_dir():
                    valid.append(m)
            return valid
        except Exception:
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
            return None

    def _merge_module_dirs(self, root: Path, modules: list[str]) -> dict[str, str]:
        """遍历多个 Maven 模块，合并源码目录。"""
        all_pages = []
        all_tests = []
        all_aw = []

        for module_name in modules:
            module_root = root / module_name
            module_pom = module_root / "pom.xml"

            # 尝试模块的 pom.xml 自定义目录
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
                # 标准布局
                std_main = module_root / "src" / "main" / "java"
                std_test = module_root / "src" / "test" / "java"
                if std_main.exists():
                    all_pages.append(str(std_main.relative_to(root)))
                if std_test.exists():
                    all_tests.append(str(std_test.relative_to(root)))

            # 推断 AW 目录
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

        # 兜底：如果模块没有发现测试目录，用标准路径推断
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

    # ── Gradle 检测 ──

    def _detect_gradle_dirs(self, root: Path) -> dict[str, str] | None:
        """检测 Gradle 项目（build.gradle / build.gradle.kts）的源码目录。

        支持自定义 sourceSets 配置，也检测 src/{name}/java 模式。
        """
        result = {}

        # 读取 build.gradle 或 build.gradle.kts
        for gradle_file in ["build.gradle", "build.gradle.kts"]:
            gf = root / gradle_file
            if not gf.exists():
                continue
            try:
                content = gf.read_text("utf-8")

                # 提取 sourceSets 块中自定义的 src 目录
                src_dirs = self._extract_gradle_source_sets(content, root)
                if "pages" in src_dirs:
                    result["pages"] = src_dirs["pages"]
                if "tests" in src_dirs:
                    result["tests"] = src_dirs["tests"]
                if "aw" in src_dirs:
                    result["component_aw"] = src_dirs["aw"]
            except Exception:
                pass

        # 如果 sourceSets 没找到，扫描实际的 src 目录
        if not result:
            result = self._scan_gradle_src_dirs(root)

        # 标准 Gradle 布局兜底
        if not result:
            std_main = root / "src" / "main" / "java"
            std_test = root / "src" / "test" / "java"
            if std_main.exists():
                result["pages"] = "src/main/java"
            if std_test.exists():
                result["tests"] = "src/test/java"

        # 推断 AW 目录
        if "component_aw" not in result and "pages" in result:
            aw_dir = self._infer_aw_dir(root, result["pages"])
            if aw_dir:
                result["component_aw"] = aw_dir

        return result if result else None

    @staticmethod
    def _extract_gradle_source_sets(content: str, root: Path) -> dict[str, str]:
        """从 Gradle 构建文件中提取 sourceSets 定义的自定义源码目录。

        支持 Groovy DSL 和 Kotlin DSL 两种语法。
        模式示例：
          sourceSets { main { java { srcDirs = ['src/custom/java'] } } }
          sourceSets.main.java.srcDirs = ['src/custom/java']
        """
        result = {}

        # 模式 1: sourceSets { main { java { srcDirs ... } } }  (Groovy DSL 块)
        # 在 sourceSets 块内查找 main/java 的 srcDirs
        srcsets_block = re.search(
            r'sourceSets\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}',
            content, re.DOTALL
        )
        search_text = srcsets_block.group(1) if srcsets_block else content

        # 提取 main source dirs
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
                    result["pages"] = dirs[0]  # 取第一个主源码目录

        # 提取 test source dirs
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
                    # 自定义 sourceSet 名称 → 可能包含页面和测试代码
                    # 根据命名推断
                    if "test" in src_name.lower():
                        result["tests"] = rel
                    else:
                        result["pages"] = rel

        return result

    def _detect_python_dirs(self, root: Path) -> dict[str, str]:
        """Python 项目的目录自动检测。"""
        result = {}

        # 扫描常见目录名
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

    def _infer_aw_dir(self, root: Path, pages_dir: str) -> str | None:
        """从 pages 目录推断 AW/组件封装目录。"""
        pages_path = root / pages_dir
        if not pages_path.exists():
            return None
        # 在 pages 父目录下查找 aw/components 目录
        parent = pages_path.parent
        for candidate in ["aw", "aaw", "components", "component_aw", "widgets"]:
            candidate_path = parent / candidate
            if candidate_path.exists() and any(candidate_path.rglob("*.java")) or \
               any(candidate_path.rglob("*.py")):
                return str(candidate_path.relative_to(root))
        # 在 pages 内部查找 aw 子目录
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
                # 检测 AW/组件目录
                if any(p in ("aw", "aaw", "components", "widgets") for p in parts):
                    aw_paths.add(rel)

        # 找主源码的公共根目录
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

        # 检查 src/ 下
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

    def auto_seed(self) -> list[KBItem]:
        """自动播种 KB：检测目录 → 扫描文件 → 提取知识。

        阈值按项目文件数动态计算：max(5, java_file_count // 10)，
        小项目最少 5 条，大项目按比例增加。
        返回新播种的条目列表。
        """
        existing = self.store.list_all()
        threshold = self._compute_auto_seed_threshold()
        if len(existing) >= threshold:
            return []

        source_dirs = self.auto_detect_source_dirs()
        return self.seed_from_static_analysis(source_dirs)

    def _compute_auto_seed_threshold(self) -> int:
        """按项目源文件数量动态计算播种阈值。"""
        java_count = 0
        py_count = 0
        try:
            java_count = len(list(self.project_root.glob("**/*.java")))
        except Exception:
            pass
        try:
            py_count = len(list(self.project_root.glob("**/*.py")))
        except Exception:
            pass
        total = java_count + py_count
        return max(5, total // 10)

    def seed_from_runtime(self, component_type: str, method_traces: list[dict],
                          page_url: str) -> list[KBItem]:
        """Seed from runtime execution traces."""
        items = self.extractor.extract_from_runtime_trace(component_type, method_traces, page_url)
        for item in items:
            existing = self.store.get_by_key(item.category, item.key)
            if existing:
                # Merge: update confidence and add new xpaths
                existing.value.update(item.value)
                existing.confidence.score = max(existing.confidence.score, item.confidence.score)
                existing.confidence.source = item.confidence.source
                existing.version += 1
                self.store.save(existing)
            else:
                self.store.save(item)
        return items

    def seed_from_document(self, text: str, source_name: str = "design_doc") -> list[KBItem]:
        """Seed from NL design document."""
        items = self.extractor.extract_from_design_doc(text, source_name)
        for item in items:
            self.store.save(item)
        return items

    def inject(self, category: str, key: str, value: dict, description: str) -> KBItem:
        """Direct human injection of a KB entry."""
        item = self.extractor.inject_convention(key, value, description)
        item.category = category
        item.id = f"human_{category}_{key.replace('.', '_')}"
        self.store.save(item)
        return item

    # ══════════════════════════════════════════════════════════
    # Query Phase
    # ══════════════════════════════════════════════════════════

    def query(self, query_text: str, min_confidence: float = 0.4) -> list[KBItem]:
        """Search KB with NL text query."""
        results = self.store.search(query_text)
        return [r for r in results if r.confidence.effective_score >= min_confidence]

    def get_component_type(self, aria_role: str, dom_attrs: dict) -> Optional[dict]:
        """Query KB: what component type maps to this ARIA role?"""
        # First try exact match on data-module
        data_module = dom_attrs.get("data-module", "")
        if data_module:
            for item in self.store.list_category("components"):
                patterns = item.value.get("xpath_patterns", [])
                for p in patterns:
                    if data_module in p:
                        return {"type": item.value.get("class_name", "UnknownAW"), "kb_item": item}

        # Then try ARIA role mapping from conventions
        for item in self.store.list_category("conventions"):
            mappings = item.value.get("component_type_mappings", [])
            if isinstance(mappings, list):
                pass  # need structured mapping
            if item.key == "convention.component_types":
                role_map = item.value.get("aria_role_map", {})
                if aria_role in role_map:
                    return {"type": role_map[aria_role], "kb_item": item}

        return None

    def get_locator_conventions(self) -> dict:
        """Query KB: what locator strategies are configured?"""
        for item in self.store.list_category("conventions"):
            if item.key == "convention.locator_priority":
                return item.value
        return {}

    def get_naming_rules(self) -> list[str]:
        """Query KB: what naming conventions exist?"""
        for item in self.store.list_category("conventions"):
            if item.key == "convention.naming":
                return item.value.get("naming_rules", [])
        return []

    def get_pattern(self, pattern_key: str) -> Optional[dict]:
        """Query KB: get a specific pattern."""
        for item in self.store.list_category("patterns"):
            if item.key == pattern_key:
                return item.value
        return None

    # ══════════════════════════════════════════════════════════
    # Feedback Phase
    # ══════════════════════════════════════════════════════════

    def record_self_test_result(self, item_id: str, category: str, passed: bool):
        """Update confidence based on self-test result."""
        item = self.store.get(category, item_id)
        if item:
            if passed:
                item.confidence.record_pass()
            else:
                item.confidence.record_failure()
            self.store.save(item)

    def correct(self, category: str, item_id: str, corrections: dict,
                nl_note: str = "") -> KBItem:
        """Apply human correction to a KB item via NL feedback."""
        item = self.store.get(category, item_id)
        if not item:
            raise KeyError(f"KB item not found: {category}/{item_id}")

        item.value.update(corrections)
        item.confidence.manual_override = corrections.get("confidence_override",
                                                          item.confidence.effective_score)
        item.description = nl_note or item.description
        item.version += 1
        item.tags.append("corrected")
        self.store.save(item)
        return item

    def apply_nl_feedback(self, natural_language_feedback: str) -> list[KBItem]:
        """Apply NL feedback: parse intent and update relevant KB items.

        Examples:
          "TableAW's XPath should use data-module, not class" → update component convention
          "搜索框 should use data-test='search-box'" → update locator priority
        """
        affected = []
        feedback_lower = natural_language_feedback.lower()

        # Match against existing KB items by keyword
        for item in self.store.list_all():
            if any(tag.lower() in feedback_lower for tag in item.tags):
                if "should" in feedback_lower or "must" in feedback_lower:
                    item.confidence.score = max(0.8, item.confidence.score + 0.1)
                    item.confidence.source = KnowledgeSource.HUMAN_INJECTION
                    item.tags.append("nl-corrected")
                    item.version += 1
                    self.store.save(item)
                    affected.append(item)

        return affected

    # ══════════════════════════════════════════════════════════
    # Evolve Phase
    # ══════════════════════════════════════════════════════════

    def evolve(self):
        """Run KB evolution cycle: decay, generalize, archive."""
        self._apply_decay()
        self._generalize_patterns()
        self._archive_low_confidence()

    def _apply_decay(self):
        """Apply confidence decay to items not recently validated.

        Persists the decayed effective score as the new baseline and
        updates last_validated_at to prevent compounding decay.
        """
        now = time.time()
        for item in self.store.list_all():
            if item.confidence.decay_rate > 0 and not item.archived:
                score_after = item.confidence.effective_score
                if score_after < item.confidence.score:
                    item.confidence.score = score_after
                    item.confidence.last_validated_at = now
                    self.store.save(item)

    def _generalize_patterns(self):
        """Generalize: if 3+ items share the same value pattern, create a convention."""
        categories = [("components", "component_type"),
                       ("pages", "page_structure"),
                       ("patterns", "business_pattern")]

        for category, key_prefix in categories:
            items = self.store.list_category(category)
            value_signatures = {}
            for item in items:
                sig = self._value_signature(item.value)
                value_signatures.setdefault(sig, []).append(item)

            for sig, group in value_signatures.items():
                if len(group) >= 3:
                    # Pattern confirmed by 3+ items — boost confidence
                    for item in group:
                        item.confidence.score = min(1.0, item.confidence.score + 0.05)
                        item.tags.append("generalized")
                        self.store.save(item)

    def _archive_low_confidence(self, threshold: float = 0.2):
        """Archive items with sustained low confidence."""
        for item in self.store.list_all():
            if (item.confidence.effective_score < threshold
                    and not item.archived
                    and item.confidence.self_test_failures >= 3):
                self.store.archive(item)

    def _value_signature(self, value: dict) -> str:
        """Create a structural signature of a value dict for pattern detection."""
        return "|".join(sorted(f"{k}:{type(v).__name__}" for k, v in value.items()))

    # ══════════════════════════════════════════════════════════
    # NL Interaction
    # ══════════════════════════════════════════════════════════

    def query_nl(self, question: str) -> str:
        """Answer a NL question about the KB. Returns a text summary."""
        results = self.query(question, min_confidence=0.3)
        if not results:
            return f"No KB entries found matching: '{question}'"

        lines = [f"Found {len(results)} relevant KB entries for: '{question}'\n"]
        for item in results[:5]:
            conf = item.confidence.effective_score
            lines.append(
                f"- [{item.category}] {item.key}: {item.description} "
                f"(confidence: {conf:.2f})"
            )
        return "\n".join(lines)

    # ── NL Intent Patterns ──────────────────────────

    _INTENT_PATTERNS = [
        (re.compile(r'(?:删[除掉]|移除|去掉|清理)\s*(?:那个|这个|所有|掉)?\s*(.+)'), "DELETE"),
        (re.compile(r'(.+?)\s*(?:改为|改成)\s*(.+)'), "MODIFY"),
        (re.compile(r'(.+?)(?:应该|必须|需要|可以)\s*(?:用|使用)\s*(.+)'), "MODIFY"),
        (re.compile(r'(?:修改|更改?|调整|更新|设置)\s*(?:那个|这个)?\s*(.+)'), "MODIFY"),
        (re.compile(r'(?:新增|添加|加一[条个]|增加|创建)\s*(?:规则[:：]?\s*|一[条个]新(?:的)?\s*)?(.+)'), "ADD"),
    ]

    _CATEGORY_KEYWORDS = {
        "conventions": ["约定", "规范", "惯例", "定位", "优先级", "命名", "包名", "导入",
                       "断言", "convention", "priority", "locator", "naming"],
        "components": ["组件", "component", "aw", "target", "element", "元素",
                       "表格", "输入框", "按钮", "下拉", "弹窗", "菜单", "树",
                       "table", "input", "button", "dropdown", "dialog", "menu"],
        "patterns": ["模式", "pattern", "流程", "序列", "模板", "pattern", "template"],
        "pages": ["页面", "page", "url", "路由", "导航"],
    }

    def _parse_intent(self, instruction: str) -> dict:
        """Parse NL instruction into intent + parameters."""
        text = instruction.strip()

        for pattern, intent in self._INTENT_PATTERNS:
            m = pattern.match(text)
            if m:
                if intent == "DELETE":
                    return {"intent": "DELETE", "target": m.group(1).strip()}
                elif intent == "ADD":
                    return {"intent": "ADD", "content": m.group(1).strip()}
                elif intent == "MODIFY":
                    groups = m.groups()
                    if len(groups) == 2:
                        return {"intent": "MODIFY", "target": groups[0].strip(),
                                "new_value": groups[1].strip()}
                    else:
                        return {"intent": "MODIFY", "target": groups[0].strip()}

        # Check for question patterns → QUERY
        if re.search(r'[?？]|什么|哪些|怎么|如何|有没有|是什么|查', text):
            return {"intent": "QUERY", "question": text}

        # Fallback: treat as QUERY
        return {"intent": "QUERY", "question": text}

    def _infer_category(self, text: str) -> str:
        """Infer KB category from NL content keywords."""
        text_lower = text.lower()
        best_category = "conventions"
        best_score = 0
        for cat, keywords in self._CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > best_score:
                best_score = score
                best_category = cat
        return best_category

    def operate_nl(self, instruction: str) -> dict:
        """Execute KB CRUD via NL instruction. Returns structured result.

        Intents:
          QUERY: "表格组件的定位方式是什么？"
          ADD:   "新增规则：弹窗用 role='dialog' 识别"
          MODIFY:"表格组件的定位方式改为 data-testid"
          DELETE:"删掉表格排序的规则"
        """
        parsed = self._parse_intent(instruction)
        intent = parsed["intent"]

        if intent == "QUERY":
            answer = self.query_nl(parsed.get("question", instruction))
            return {"status": "ok", "intent": "QUERY", "result": answer}

        elif intent == "DELETE":
            target = parsed["target"]
            candidates = self.store.search(target)
            if not candidates:
                return {"status": "not_found", "intent": "DELETE",
                        "message": f"未找到与'{target}'匹配的 KB 条目",
                        "query": target}
            # Delete the best match
            best = candidates[0]
            self.store.archive(best)
            return {"status": "ok", "intent": "DELETE",
                    "message": f"已删除: [{best.category}] {best.key} — {best.description}",
                    "deleted": {"category": best.category, "key": best.key,
                               "description": best.description}}

        elif intent == "ADD":
            content = parsed["content"]
            category = self._infer_category(content)
            key = re.sub(r'[^\w]+', '_', content[:40]).strip('_').lower()
            if not key:
                key = f"nl_add_{int(time.time())}"
            item = self.inject(
                category=category,
                key=key,
                value={"description": content, "source": "nl_dialogue"},
                description=content,
            )
            return {"status": "ok", "intent": "ADD",
                    "message": f"已新增: [{category}] {key} — {content}",
                    "added": {"category": category, "key": key, "description": content}}

        elif intent == "MODIFY":
            target = parsed["target"]
            new_value = parsed.get("new_value", "")
            candidates = self.store.search(target)
            if not candidates:
                return {"status": "not_found", "intent": "MODIFY",
                        "message": f"未找到与'{target}'匹配的 KB 条目。要新增吗？",
                        "query": target, "suggest_add": True}
            best = candidates[0]
            old_desc = best.description
            best.description = f"{old_desc} (modified via NL: {new_value or target})"
            if new_value:
                best.value["nl_modification"] = new_value
            best.value["nl_instruction"] = instruction
            best.confidence.source = KnowledgeSource.HUMAN_INJECTION
            best.confidence.score = max(0.9, best.confidence.score)
            best.version += 1
            self.store.save(best)
            return {"status": "ok", "intent": "MODIFY",
                    "message": f"已更新: [{best.category}] {best.key} — {best.description}",
                    "modified": {"category": best.category, "key": best.key,
                                "old_description": old_desc,
                                "new_description": best.description}}

        return {"status": "error", "message": f"无法解析指令: '{instruction}'"}

    def summarize_kb(self) -> str:
        """Generate a full NL summary of the KB."""
        return self.store.summarize()

    def get_high_confidence_knowledge(self) -> dict[str, dict]:
        """Return all high-confidence knowledge as a structured dict, keyed by category."""
        result = {}
        for item in self.store.get_high_confidence(0.7):
            result.setdefault(item.category, {})[item.key] = item.value
        return result
