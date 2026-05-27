"""Convention miner — naming, operation, import, locator, and assertion conventions."""

import logging
import re
from pathlib import Path

from .extractor._base import safe_relative_to
from .item import KBItem, Confidence, KnowledgeSource

# Compiled regex for convention mining (hot path — called per source file)
_CONV_IMPORT_RE = re.compile(r'^import\s+([\w.]+(?:\.\*)?)\s*;', re.MULTILINE)
_CONV_METHOD_RE = re.compile(
    r'(?:public|private|protected|static)\s+\w+\s+(\w+)\s*\([^)]*\).*\{'
)
_CONV_LOCATOR_CALL_RE = re.compile(r'(\w+)\.(\w+)\s*\(')

logger = logging.getLogger(__name__)


class ConventionMiner:
    """Naming, operation, import, locator, and assertion convention mining."""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root)

    # ── Naming Convention Extraction (batch analysis) ──

    def _extract_naming_conventions(self, items: list[KBItem]) -> list[KBItem]:
        """Analyze class/method name patterns across all extracted items and
        produce a naming convention KB entry.

        Runs after all files are processed. Examines suffixes and prefixes
        across all components/pages to determine team conventions.
        """
        suffix_counts = {}
        prefix_counts = {}
        style_counts = {"camelCase": 0, "snake_case": 0}

        for item in items:
            if item.category not in ("components", "pages"):
                continue
            val = item.value

            # 收集类名后缀
            naming = val.get("naming", {})
            if "class_suffix" in naming:
                suffix_counts[naming["class_suffix"]] = suffix_counts.get(naming["class_suffix"], 0) + 1

            # 收集方法名前缀
            if "method_prefix" in naming:
                prefix_counts[naming["method_prefix"]] = prefix_counts.get(naming["method_prefix"], 0) + 1

            # 收集字段风格
            if "field_style" in naming:
                style_counts[naming["field_style"]] = style_counts.get(naming["field_style"], 0) + 1

        # 如果数据不足，不生成条目
        total_with_naming = len([i for i in items if i.category in ("components", "pages") and i.value.get("naming")])
        if total_with_naming < 1:
            return []

        convention = {}
        if suffix_counts:
            convention["class_suffix"] = max(suffix_counts, key=suffix_counts.get)
        if prefix_counts:
            convention["method_prefix"] = max(prefix_counts, key=prefix_counts.get)
        if style_counts:
            convention["field_style"] = max(style_counts, key=style_counts.get)

        # 附加分布信息
        if suffix_counts:
            convention["class_suffix_distribution"] = suffix_counts
        if prefix_counts:
            convention["method_prefix_distribution"] = prefix_counts

        naming_item = KBItem(
            id="naming_conventions_auto",
            category="conventions",
            key="convention.naming",
            value=convention,
            confidence=Confidence(score=0.65, source=KnowledgeSource.PATTERN_MINING),
            description=f"Auto-detected naming conventions: "
                        f"class suffix={convention.get('class_suffix', 'N/A')}, "
                        f"method prefix={convention.get('method_prefix', 'N/A')}, "
                        f"field style={convention.get('field_style', 'N/A')}",
            tags=["naming", "convention", "auto-detected"],
        )

        return [naming_item]

    # ── Convention helper extractors ──

    @staticmethod
    def _classify_method_prefix(name: str) -> str:
        """将方法名分类到操作类别，返回类别名。"""
        lower = name.lower()
        if any(lower.startswith(p) for p in ("get", "find", "fetch", "retrieve", "query")):
            return "retrieval"
        if any(lower.startswith(p) for p in ("set", "update", "modify", "put", "post")):
            return "mutation"
        if any(lower.startswith(p) for p in ("click", "tap", "press", "touch", "hit")):
            return "click"
        if any(lower.startswith(p) for p in ("select", "choose", "pick", "set_selected")):
            return "select"
        if any(lower.startswith(p) for p in ("type", "input", "fill", "enter", "write", "send")):
            return "input"
        if any(lower.startswith(p) for p in ("clear", "reset", "remove", "delete", "clean")):
            return "clear"
        if any(lower.startswith(p) for p in ("is", "has", "can", "should", "check", "verify", "validate",
                                                "assert", "expect", "exists", "contains")):
            return "verification"
        if any(lower.startswith(p) for p in ("wait", "until", "sleep", "pause", "delay")):
            return "wait"
        if any(lower.startswith(p) for p in ("sort", "filter", "order", "search", "sort_by", "filter_by")):
            return "data"
        if any(lower.startswith(p) for p in ("open", "close", "navigate", "goto", "go_to", "refresh",
                                                "back", "forward")):
            return "navigation"
        if any(lower.startswith(p) for p in ("export", "import", "save", "load", "download", "upload")):
            return "io"
        if any(lower.startswith(p) for p in ("scroll", "drag", "drop", "hover", "move", "swipe")):
            return "advanced_interaction"
        if any(lower.startswith(p) for p in ("init", "setup", "teardown", "before", "after", "cleanup")):
            return "lifecycle"
        return "other"

    def _extract_operation_conventions(self, source_files: set[Path]) -> "KBItem | None":
        """从组件文件中提取常见操作模式（方法名前缀分类）。"""
        category_counts: dict[str, int] = {}
        total_files = 0

        for f in source_files:
            if f.suffix not in (".java", ".py"):
                continue
            try:
                content = f.read_text("utf-8")
            except Exception:
                logger.warning("Failed to read file for method extraction: %s", f, exc_info=True)
                continue
            total_files += 1
            # Match method definitions: Java (public/private/protected void/Type name(...))
            # and Python (def name(...))
            methods = re.findall(
                r'(?:public|private|protected|static|\s)+\w+\s+(\w+)\s*\(|def\s+(\w+)\s*\(',
                content,
            )
            for java_name, py_name in methods:
                name = java_name or py_name
                cat = self._classify_method_prefix(name)
                category_counts[cat] = category_counts.get(cat, 0) + 1

        if not category_counts:
            return None

        # Sort by frequency
        sorted_cats = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
        dominant = sorted_cats[0]

        return KBItem(
            id="convention_operations",
            category="conventions",
            key="convention.operations",
            value={
                "operation_categories": [
                    {"category": cat, "count": cnt, "ratio": round(cnt / sum(category_counts.values()), 3)}
                    for cat, cnt in sorted_cats
                ],
                "dominant_operation": dominant[0],
                "total_methods_analyzed": sum(category_counts.values()),
                "files_analyzed": total_files,
            },
            confidence=Confidence(score=0.55, source=KnowledgeSource.PATTERN_MINING),
            description=f"Operation patterns: dominant={dominant[0]} "
                        f"({dominant[1]}/{sum(category_counts.values())} methods)",
            tags=["operation", "convention", "aggregated"],
            source_files=[safe_relative_to(f, self.project_root) for f in source_files
                          if f.suffix in (".java", ".py")][:30],
            aggregation="convention_batch",
        )

    def _extract_import_conventions(self, source_files: set[Path]) -> "KBItem | None":
        """从源码中提取常见导入模式。"""
        import_counts: dict[str, int] = {}
        total_files = 0

        for f in source_files:
            if f.suffix not in (".java", ".py"):
                continue
            try:
                content = f.read_text("utf-8")
            except Exception:
                logger.warning("Failed to read file for import extraction: %s", f, exc_info=True)
                continue
            total_files += 1
            if f.suffix == ".java":
                imports = re.findall(r'^import\s+([\w.]+(?:\.\*)?)\s*;', content, re.MULTILINE)
            else:
                imports = re.findall(r'^(?:from\s+(\S+)\s+import|import\s+(\S+))', content, re.MULTILINE)
                imports = [m[0] or m[1] for m in imports]
            for imp in imports:
                # Group by top-level or second-level package
                parts = imp.split(".")
                if len(parts) >= 2:
                    key = ".".join(parts[:2])
                else:
                    key = parts[0]
                import_counts[key] = import_counts.get(key, 0) + 1

        if not import_counts:
            return None

        # Top import groups
        top_imports = sorted(import_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        top_package = top_imports[0]

        return KBItem(
            id="convention_imports",
            category="conventions",
            key="convention.imports",
            value={
                "top_imports": [
                    {"package": pkg, "count": cnt} for pkg, cnt in top_imports
                ],
                "total_distinct_packages": len(import_counts),
                "files_analyzed": total_files,
            },
            confidence=Confidence(score=0.55, source=KnowledgeSource.PATTERN_MINING),
            description=f"Import patterns: top={top_package[0]} ({top_package[1]} usages, "
                        f"{len(import_counts)} distinct packages)",
            tags=["import", "convention", "aggregated"],
            source_files=[safe_relative_to(f, self.project_root) for f in source_files
                          if f.suffix in (".java", ".py")][:30],
            aggregation="convention_batch",
        )

    def _extract_locator_usage_conventions(self, source_files: set[Path],
                                           profile: "FrameworkProfile") -> "KBItem | None":
        """从源码中提取定位器的实际使用模式（与 profile 的优先级列表不同，
        此处统计各类定位器在源码中的实际出现次数）。"""
        locator_counts: dict[str, int] = {}
        total_files = 0

        # Patterns to detect locator usage
        locator_patterns = [
            (r'@FindBy\s*\(\s*(\w+)\s*=', "annotation"),
            (r'By\.(\w+)\s*\(', "selenium_api"),
            (r'(?:driver\.)?find[_Ee]lement\s*\(\s*By\.(\w+)', "find"),
            (r'(?:data-module|data-test(?:id)?)\s*=', "data_attribute"),
        ]

        for f in source_files:
            if f.suffix not in (".java", ".py"):
                continue
            try:
                content = f.read_text("utf-8")
            except Exception:
                logger.warning("Failed to read file for locator extraction: %s", f, exc_info=True)
                continue
            total_files += 1

            for pattern, group in locator_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for m in matches:
                    loc = m.strip().lower() if isinstance(m, str) else str(m).strip().lower()
                    if loc:
                        locator_counts[loc] = locator_counts.get(loc, 0) + 1

        if not locator_counts:
            return None

        sorted_locs = sorted(locator_counts.items(), key=lambda x: x[1], reverse=True)
        top_locator = sorted_locs[0]

        return KBItem(
            id="convention_locator_usage",
            category="conventions",
            key="convention.locator_usage",
            value={
                "locator_usage": [
                    {"type": loc, "count": cnt} for loc, cnt in sorted_locs[:15]
                ],
                "total_locator_sites": sum(locator_counts.values()),
                "files_analyzed": total_files,
            },
            confidence=Confidence(score=0.55, source=KnowledgeSource.PATTERN_MINING),
            description=f"Locator usage: top={top_locator[0]} ({top_locator[1]} sites, "
                        f"{len(locator_counts)} distinct types)",
            tags=["locator", "convention", "aggregated"],
            source_files=[safe_relative_to(f, self.project_root) for f in source_files
                          if f.suffix in (".java", ".py")][:30],
            aggregation="convention_batch",
        )

    def _extract_assertion_conventions(self, test_files: list[Path]) -> "KBItem | None":
        """从测试文件中提取断言风格模式。"""
        assertion_patterns = [
            (r'assert\s+(?!equals|That|NotNull|Null|True|False|Same|NotSame)', "assert_keyword"),
            (r'Assert\.assert\w+\(', "testng_assert"),
            (r'assertEquals\s*\(', "junit_assert"),
            (r'assertThat\s*\(', "hamcrest_assert"),
            (r'assert\s+\w+\s*==', "assert_equal"),
            (r'assert\s+\w+\s*!=\s*null', "assert_not_null"),
            (r'verify\s*\(', "mockito_verify"),
            (r'\.should\(', "should_style"),
            (r'expect\s*\(', "expect_style"),
            (r'assertEqual\s*\(', "unittest_assert"),
            (r'self\.assert\w+\(', "unittest_self_assert"),
            (r'assert\s+\w+\.', "pytest_assert"),
        ]

        style_counts: dict[str, int] = {}
        total_files = 0

        for f in test_files:
            try:
                content = f.read_text("utf-8")
            except Exception:
                logger.warning("Failed to read test file for assertion extraction: %s", f, exc_info=True)
                continue
            total_files += 1
            for pattern, style in assertion_patterns:
                count = len(re.findall(pattern, content))
                if count > 0:
                    style_counts[style] = style_counts.get(style, 0) + count

        if not style_counts:
            return None

        sorted_styles = sorted(style_counts.items(), key=lambda x: x[1], reverse=True)
        dominant = sorted_styles[0]

        return KBItem(
            id="convention_assertions",
            category="conventions",
            key="convention.assertions",
            value={
                "assertion_styles": [
                    {"style": s, "occurrences": c} for s, c in sorted_styles
                ],
                "dominant_style": dominant[0],
                "files_analyzed": total_files,
            },
            confidence=Confidence(score=0.55, source=KnowledgeSource.PATTERN_MINING),
            description=f"Assertion patterns: dominant={dominant[0]} "
                        f"({dominant[1]} occurrences, {len(sorted_styles)} styles detected)",
            tags=["assertion", "convention", "aggregated"],
            source_files=[safe_relative_to(f, self.project_root) for f in test_files][:30],
            aggregation="convention_batch",
        )

    def _extract_patterns(self, test_files: list[Path],
                          profile: "FrameworkProfile") -> list["KBItem"]:
        """从测试文件中挖掘 BAW 模式。"""
        patterns = {}
        for f in test_files[:30]:
            try:
                content = f.read_text("utf-8")
                # Find sequences of method calls (component.method())
                calls = re.findall(r'(\w+)\.(\w+)\s*\(', content)
                if len(calls) >= 3:
                    # Build n-gram patterns
                    for i in range(len(calls) - 2):
                        seq = tuple(c[1] for c in calls[i:i + 3])
                        key = " → ".join(seq)
                        patterns[key] = patterns.get(key, 0) + 1
            except Exception:
                logger.warning("Failed to extract patterns from test file: %s", f, exc_info=True)
                pass

        # Top patterns
        result = []
        for seq, count in sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:15]:
            if count >= 2:
                result.append(KBItem(
                    id=f"pattern_{hash(seq) % 10000}",
                    category="patterns",
                    key=f"pattern.baw_{hash(seq) % 10000}",
                    value={"sequence": seq, "frequency": count},
                    confidence=Confidence(
                        score=min(0.7, 0.4 + count * 0.05),
                        source=KnowledgeSource.PATTERN_MINING,
                    ),
                    description=f"Frequent operation pattern ({count}x): {seq}",
                    tags=["auto-mined", "pattern", "aggregated"],
                    aggregation="pattern_mined",
                ))

        return result
