"""Aggregated extraction mixin — Phase 2 aggregated KB extraction from profiled projects."""

import logging
import re
from pathlib import Path

from ._base import safe_relative_to
from ..item import KBItem, Confidence, KnowledgeSource
from ...profile import FrameworkProfile, ProfileField

logger = logging.getLogger(__name__)


class _AggregationMixin:
    """Phase 2 aggregated extraction that only scans UI-relevant files."""

    # ═══════════════════════════════════════════════════════════════
    # Phase 2: Aggregated Extraction
    # ═══════════════════════════════════════════════════════════════

    def extract_aggregated(self, profile: "FrameworkProfile") -> list[KBItem]:
        """Phase 2: 只扫描 UI 相关文件，按组件族聚合生成 KBItem。

        Args:
            profile: Phase 1 输出的项目画像

        Returns:
            聚合后的 KBItem 列表（~50-200 个）
        """
        items = []
        source_dirs = profile.source_dirs.value or {}

        # Collect all Java and Python files from source dirs
        all_java = []
        all_py = []
        for dir_path in source_dirs.values():
            target = self.project_root / dir_path
            if not target.exists():
                continue
            all_java.extend(target.glob("**/*.java"))
            all_py.extend(target.glob("**/*.py"))

        # Filter to only UI-relevant files
        ui_java = self._filter_ui_files(all_java, profile)
        ui_py = self._filter_ui_files(all_py, profile)

        # ── Component families (Java) ──
        families = self._group_by_component_family(ui_java, profile)
        for family_name, files in families.items():
            item = self._extract_component_family(family_name, files, profile)
            if item:
                items.append(item)

        # ── Component families (Python) ──
        py_pages = [f for f in ui_py if "page" in str(f).lower() or "screen" in str(f).lower()]
        py_components = [f for f in ui_py if f not in py_pages]

        if py_components:
            py_families = self._group_by_component_family(py_components, profile)
            for family_name, files in py_families.items():
                item = self._extract_component_family(family_name, files, profile)
                if item:
                    items.append(item)

        # ── Page index ──
        page_items = self._extract_page_index(ui_java + py_pages, profile)
        items.extend(page_items)

        # ── Individual UI files not in any family ──
        family_files = set()
        for files in families.values():
            family_files.update(str(f) for f in files)
        for f in ui_java:
            if str(f) not in family_files:
                item = self._extract_single_ui_file(f, profile)
                if item:
                    items.append(item)

        # ── Aggregated conventions ──
        convention_items = self._extract_aggregated_conventions(profile, items)
        items.extend(convention_items)

        # ── Pattern mining from test files ──
        test_files = []
        test_dir = source_dirs.get("tests", "")
        if test_dir:
            test_target = self.project_root / test_dir
            if test_target.exists():
                test_files.extend(test_target.glob("**/*.java"))
                test_files.extend(test_target.glob("**/*.py"))
        pattern_items = self._extract_patterns(test_files, profile)
        items.extend(pattern_items)

        return items

    def _filter_ui_files(self, files: list[Path],
                         profile: "FrameworkProfile") -> list[Path]:
        """只保留 UI 相关包路径中的文件。"""
        ui_packages = profile.ui_packages.value or []
        if not ui_packages:
            return list(files)

        result = []
        for f in files:
            path_str = str(f).replace("\\", "/")
            # Match against inferred UI packages
            for pkg in ui_packages:
                if pkg in path_str:
                    result.append(f)
                    break
            else:
                # Fallback: check individual file for UI relevance
                if f.suffix == ".java":
                    try:
                        content = f.read_text("utf-8")[:2000]  # Only read first 2KB
                        if self._quick_ui_check(content):
                            result.append(f)
                    except Exception:
                        logger.warning("Failed to read file for UI check: %s", f, exc_info=True)
                        pass
                else:
                    result.append(f)  # Python files — include by default
        return result

    def _quick_ui_check(self, content: str) -> bool:
        """Quick check if file content suggests UI relevance."""
        ui_indicators = [
            r'@FindBy', r'@Page', r'@Component', r'By\.\w+\(', r'WebElement',
            r'WebDriver', r'getPage\(\)', r'PageObject', r'extends\s+\w*(?:Page|Component|AW|Widget)',
            r'data-module', r'data-testid', r'data-test',
        ]
        for pattern in ui_indicators:
            if re.search(pattern, content):
                return True
        return False

    def _group_by_component_family(self, files: list[Path],
                                   profile: "FrameworkProfile") -> dict[str, list[Path]]:
        """按组件族分组：Table* → "table", Button* → "button" 等。

        优先级：基类映射 > 类名后缀 > 包路径关键词 > 文件内容特征
        """
        base_map = profile.base_classes.value or {}
        # Reverse: component_type → base class names
        type_to_bases = {}
        for base, ctype in base_map.items():
            type_to_bases.setdefault(ctype, set()).add(base.lower())

        # Known type keywords
        known_types = [
            "table", "form", "button", "input", "dialog", "dropdown",
            "menu", "tree", "tab", "link", "label", "checkbox", "search",
            "calendar", "panel", "sidebar", "header", "footer",
        ]

        families = {}
        ungrouped = []

        for f in files:
            assigned = False
            fname = f.stem.lower()

            # 1. Try known type keywords in filename
            for kw in known_types:
                if kw in fname:
                    families.setdefault(kw, []).append(f)
                    assigned = True
                    break

            if assigned:
                continue

            # 2. Try base class mapping from content
            try:
                content = f.read_text("utf-8")[:3000]
                m = re.search(r'extends\s+(\w+)', content)
                if m:
                    base_lower = m.group(1).lower()
                    for ctype, bases in type_to_bases.items():
                        if base_lower in bases:
                            families.setdefault(ctype, []).append(f)
                            assigned = True
                            break
            except Exception:
                logger.warning("Failed to read file for family grouping: %s", f, exc_info=True)
                pass

            if not assigned:
                ungrouped.append(f)

        # Ungrouped files get their own family based on filename
        for f in ungrouped:
            # Use the first word as family name
            stem = f.stem.lower()
            # Try to extract component type from name
            assigned = False
            for kw in known_types:
                if kw in stem:
                    families.setdefault(kw, []).append(f)
                    assigned = True
                    break
            if not assigned:
                # Use stem itself as family
                families.setdefault(stem, []).append(f)

        return families

    def _extract_component_family(self, family_name: str, files: list[Path],
                                  profile: "FrameworkProfile") -> "KBItem | None":
        """为一个组件族生成 1 个聚合 KBItem。"""
        if not files:
            return None

        classes = []
        common_methods = set()
        all_locators = []
        all_annotations = set()
        first_methods = None

        for f in files:
            class_info = {
                "name": f.stem,
                "source": safe_relative_to(f, self.project_root),
                "methods": [],
                "locators": [],
            }
            try:
                content = f.read_text("utf-8")
                # Extract methods
                methods = re.findall(r'(?:public|private|protected)\s+\w+\s+(\w+)\s*\(', content)
                class_info["methods"] = methods

                # Track common methods (intersection across all files)
                if first_methods is None:
                    first_methods = set(methods)
                else:
                    common_methods = set(methods) & first_methods
                    first_methods = common_methods or first_methods

                # Extract locators
                loc_matches = re.findall(r'(?:@FindBy|By\.\w+)\([^)]*["\']([^"\']+)["\']', content)
                class_info["locators"] = list(set(loc_matches))
                all_locators.extend(class_info["locators"])

                # Extract annotations
                annotations = re.findall(r'@(\w+)', content)
                all_annotations.update(annotations)
            except Exception:
                logger.warning("Failed to extract class info from file: %s", f, exc_info=True)
                pass

            classes.append(class_info)

        # Boost confidence: more files = higher confidence
        base_confidence = min(0.85, 0.55 + len(files) * 0.05)

        return KBItem(
            id=f"family_{family_name}",
            category="components",
            key=f"component_family.{family_name}",
            value={
                "family": family_name,
                "file_count": len(files),
                "classes": classes,
                "common_methods": list(common_methods) if common_methods else [],
                "locators": list(set(all_locators))[:20],
                "annotations": list(all_annotations),
            },
            confidence=Confidence(
                score=base_confidence,
                source=KnowledgeSource.STATIC_ANALYSIS,
            ),
            description=f"{family_name.capitalize()} component family ({len(files)} classes)"
                        + (f", {len(common_methods)} shared methods" if common_methods else ""),
            tags=[family_name, "component", "aggregated"]
                 + [c["name"] for c in classes[:5]],
            source_files=[safe_relative_to(f, self.project_root) for f in files],
            aggregation="component_family",
        )

    def _extract_single_ui_file(self, filepath: Path,
                                profile: "FrameworkProfile") -> "KBItem | None":
        """为单个未分组的 UI 文件生成 KBItem。"""
        return self._legacy_extract_from_java_file(str(filepath))

    def _extract_page_index(self, page_files: list[Path],
                            profile: "FrameworkProfile") -> list["KBItem"]:
        """生成页面索引 KBItem。"""
        if not page_files:
            return []

        pages = []
        for f in page_files:
            page_info = {"name": f.stem, "source": safe_relative_to(f, self.project_root)}
            try:
                content = f.read_text("utf-8")[:3000]
                # Count feature points (data-module, data-testid, etc.)
                fps = len(re.findall(r'@(?:data-module|data-test(?:id)?)\s*=\s*["\']([^"\']+)["\']', content))
                page_info["feature_points"] = fps
            except Exception:
                logger.warning("Failed to extract page info from file: %s", f, exc_info=True)
                page_info["feature_points"] = 0
            pages.append(page_info)

        items = []

        # Page index (aggregate)
        items.append(KBItem(
            id="page_index",
            category="pages",
            key="page.index",
            value={
                "page_count": len(pages),
                "pages": pages,
            },
            confidence=Confidence(score=0.7, source=KnowledgeSource.STATIC_ANALYSIS),
            description=f"Page index: {len(pages)} pages",
            tags=["page", "index", "aggregated"],
            source_files=[safe_relative_to(f, self.project_root) for f in page_files],
            aggregation="page_index",
        ))

        return items

    def _extract_aggregated_conventions(self, profile: "FrameworkProfile",
                                        items: list["KBItem"]) -> list["KBItem"]:
        """生成聚合约定条目。

        Profile 是结构性元数据（base_classes、locator_priorities 等）的权威来源。
        KB conventions 只存储从源码实际扫描到的运行时模式：
        - 操作模式（get/set、click/select 等方法名前缀分布）
        - 导入模式（常用库的导入频率）
        - 定位器使用模式（各类定位器在源码中的实际使用次数）
        - 断言模式（从测试文件中识别的断言风格）
        """
        convention_items = []

        # Collect unique source files referenced by existing items
        referenced_files = set()
        for item in items:
            for sf in item.source_files:
                file_path = self.project_root / sf
                if file_path.exists():
                    referenced_files.add(file_path)

        if not referenced_files:
            return []

        # 1. Operation patterns: method name prefixes found in component files
        op_item = self._extract_operation_conventions(referenced_files)
        if op_item:
            convention_items.append(op_item)

        # 2. Import patterns: commonly used import statements
        import_item = self._extract_import_conventions(referenced_files)
        if import_item:
            convention_items.append(import_item)

        # 3. Locator usage patterns: actual locator types used in source
        locator_item = self._extract_locator_usage_conventions(referenced_files, profile)
        if locator_item:
            convention_items.append(locator_item)

        # 4. Assertion patterns from test files
        source_dirs = profile.source_dirs.value or {}
        test_dir = source_dirs.get("tests", "")
        if test_dir:
            test_target = self.project_root / test_dir
            if test_target.exists():
                test_files = list(test_target.glob("**/*.java")) + list(test_target.glob("**/*.py"))
                assertion_item = self._extract_assertion_conventions(test_files)
                if assertion_item:
                    convention_items.append(assertion_item)

        return convention_items
