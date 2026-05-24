"""Project profiling mixin — Phase 1 project profiling and extended inference."""

import logging
import re
from pathlib import Path

from ...profile import FrameworkProfile, ProfileField

logger = logging.getLogger(__name__)


class _ProfileMixin:
    """Phase 1 project profiling and extended profile inference."""

    # ═══════════════════════════════════════════════════════════════
    # Phase 1: Project Profiling
    # ═══════════════════════════════════════════════════════════════

    # UI-related class name suffixes (case-insensitive)
    _UI_CLASS_SUFFIXES = frozenset([
        "page", "component", "aw", "element", "widget", "view", "panel",
        "form", "table", "dialog", "modal", "tab", "menu", "header",
        "footer", "sidebar", "screen", "layout", "card", "drawer",
        "toast", "tooltip", "popover", "dropdown", "combobox",
    ])

    # Non-UI package path segments to exclude
    _NON_UI_PATH_SEGMENTS = frozenset([
        "model", "dto", "vo", "entity", "domain", "service", "repository",
        "dao", "controller", "rest", "api", "config", "util", "helper",
        "constant", "exception", "error", "enum", "interceptor", "filter",
        "listener", "aspect", "advice", "handler", "mapper", "converter",
        "validator", "job", "scheduler", "task", "response", "request",
    ])

    def profile_project(self, source_dirs: dict[str, str]) -> "FrameworkProfile":
        """Phase 1: 扫描项目结构，推断 UI 框架画像。不生成 KBItem。

        Args:
            source_dirs: auto_detect_source_dirs() 的输出，
                         e.g. {"component_aw": "path/", "pages": "path/", "tests": "path/"}

        Returns:
            FrameworkProfile with field-level confidence tracking.
        """
        profile = FrameworkProfile()

        # 1. Build file analysis
        build_info = self._profile_build_file()
        if build_info.get("project_type"):
            profile.project_type = build_info["project_type"]

        # 2. Collect all source file paths
        all_java = []
        all_py = []
        for dir_path in source_dirs.values():
            target = self.project_root / dir_path
            if not target.exists():
                continue
            all_java.extend(target.glob("**/*.java"))
            all_py.extend(target.glob("**/*.py"))

        profile.total_java_files = len(all_java)
        profile.total_py_files = len(all_py)

        # 3. Sample files for profiling
        sample_java = all_java[:50]
        sample_py = all_py[:30]
        sample_data = self._profile_sample_files(sample_java, sample_py)

        # 4. Infer UI packages
        ui_pkgs = self._infer_ui_packages(sample_data.get("java_files", []),
                                          sample_data.get("java_packages", []))
        profile.ui_packages = ProfileField(
            value=ui_pkgs,
            source="auto",
            confidence=0.65 if ui_pkgs else 0.3,
        )

        # 5. Infer base class → component type mapping
        base_map = self._infer_base_class_map(sample_data)
        profile.base_classes = ProfileField(
            value=base_map,
            source="auto",
            confidence=0.6 if base_map else 0.3,
        )

        # 6. Detect annotations
        annotations = sample_data.get("java_annotations", [])
        profile.annotations = ProfileField(
            value=list(set(annotations))[:20],
            source="auto",
            confidence=0.65 if annotations else 0.3,
        )

        # 7. Infer locator priorities
        priorities = self._infer_locator_priorities(sample_data)
        profile.locator_priorities = ProfileField(
            value=priorities,
            source="auto",
            confidence=0.6 if priorities else 0.3,
        )

        # 8. Naming conventions
        naming = self._infer_naming_from_sample(sample_data)
        profile.naming_conventions = ProfileField(
            value=naming,
            source="auto",
            confidence=0.55 if naming else 0.3,
        )

        # 9. Source dirs (from auto_detect, refined)
        profile.source_dirs = ProfileField(
            value=source_dirs,
            source="auto",
            confidence=0.6,
        )

        profile.ui_relevant_files = sum(
            1 for f in sample_data.get("java_files", [])
            if f.get("is_ui_relevant")
        )

        # 10. Layer structure
        self._infer_layer_structure(source_dirs, profile)

        # 11. Reference directories
        self._infer_reference_directories(source_dirs, profile)

        # 12. Output config
        self._infer_output_config(profile)

        # 13. Component monitoring
        self._infer_component_monitoring(profile)

        profile.profiling_confidence = self._compute_profiling_confidence(profile)
        profile.updated_by = "profile_project"

        return profile

    def _profile_build_file(self) -> dict:
        """Read pom.xml or build.gradle for project type and dependencies."""
        info = {}
        pom = self.project_root / "pom.xml"
        if pom.exists():
            info["project_type"] = "java_maven"
            # Quick scan for test framework
            try:
                content = pom.read_text("utf-8")
                if "testng" in content.lower():
                    info["test_framework"] = "testng"
                elif "junit" in content.lower():
                    info["test_framework"] = "junit"
            except Exception:
                logger.warning("Failed to read pom.xml for test framework detection", exc_info=True)
                pass
            return info

        for gradle_file in ["build.gradle", "build.gradle.kts"]:
            if (self.project_root / gradle_file).exists():
                info["project_type"] = "java_gradle"
                return info

        if (self.project_root / "pyproject.toml").exists():
            info["project_type"] = "python_pytest"
        elif (self.project_root / "setup.py").exists():
            info["project_type"] = "python_pytest"

        return info

    def _profile_sample_files(self, java_files: list[Path],
                              py_files: list[Path]) -> dict:
        """Sample source files to extract UI-relevant patterns.

        Returns dict with keys:
            java_files: list of per-file dicts {path, class_name, extends, annotations,
                         locator_attrs, package, is_ui_relevant}
            java_packages: list of package strings
            java_annotations: list of annotation names found
            py_imports: list of import patterns
        """
        result = {
            "java_files": [],
            "java_packages": [],
            "java_annotations": [],
            "py_imports": [],
        }

        for f in java_files:
            file_info = self._profile_single_java(f)
            if file_info:
                result["java_files"].append(file_info)
                if file_info.get("package"):
                    result["java_packages"].append(file_info["package"])
                result["java_annotations"].extend(file_info.get("annotations", []))

        for f in py_files:
            imports = self._profile_single_python(f)
            if imports:
                result["py_imports"].extend(imports)

        return result

    def _profile_single_java(self, filepath: Path) -> dict | None:
        """Quickly profile a single Java file for UI relevance. No AST parsing needed."""
        try:
            content = filepath.read_text("utf-8")
        except Exception:
            logger.warning("Failed to read Java file for profiling: %s", filepath, exc_info=True)
            return None

        info = {
            "path": str(filepath.relative_to(self.project_root)),
            "package": "",
            "class_name": "",
            "extends": "",
            "annotations": [],
            "locator_attrs": [],
            "is_ui_relevant": False,
        }

        # Extract package
        m = re.search(r'^\s*package\s+([\w.]+)\s*;', content, re.MULTILINE)
        if m:
            info["package"] = m.group(1)

        # Extract class name
        m = re.search(r'public\s+class\s+(\w+)', content)
        if m:
            info["class_name"] = m.group(1)

        # Extract extends
        m = re.search(r'extends\s+(\w+)', content)
        if m:
            info["extends"] = m.group(1)

        # Extract annotations
        annotations = re.findall(r'@(\w+)', content)
        info["annotations"] = list(set(annotations))

        # Extract locator attributes
        locator_attrs = set()
        for pattern in [r'@FindBy\(\w+\s*=\s*"([^"]+)"',
                        r'@(\w+)\s*\(\s*[\w."]+\s*\)',
                        r'By\.(\w+)\(["\']([^"\']+)']:
            for m in re.finditer(pattern, content):
                if m.lastindex and m.lastindex >= 1:
                    locator_attrs.add(m.group(1))
        info["locator_attrs"] = list(locator_attrs)

        # Determine UI relevance
        info["is_ui_relevant"] = self._is_ui_relevant_java(
            filepath, info["class_name"], info["extends"],
            info["annotations"], info["package"],
        )

        return info

    def _profile_single_python(self, filepath: Path) -> list[str]:
        """Extract import patterns from a Python file for profiling."""
        try:
            content = filepath.read_text("utf-8")
        except Exception:
            logger.warning("Failed to read Python file for profiling: %s", filepath, exc_info=True)
            return []
        imports = []
        for m in re.finditer(r'(?:from|import)\s+([\w.]+)', content):
            imports.append(m.group(1))
        return imports

    def _is_ui_relevant_java(self, filepath: Path, class_name: str,
                             extends: str, annotations: list[str],
                             package: str) -> bool:
        """Determine if a Java file is UI-relevant based on heuristics."""
        # Check: UI annotations
        ui_annotations = {"FindBy", "AndroidFindBy", "iOSFindBy", "DataModule",
                          "Page", "Component", "Element", "Widget"}
        if ui_annotations.intersection(annotations):
            return True

        # Check: extends a UI base class
        if extends:
            extends_lower = extends.lower()
            for suffix in self._UI_CLASS_SUFFIXES:
                if suffix in extends_lower or extends_lower.startswith("base"):
                    return True

        # Check: class name suffix
        class_lower = class_name.lower() if class_name else ""
        for suffix in self._UI_CLASS_SUFFIXES:
            if class_lower.endswith(suffix):
                return True

        # Check: file path contains UI directory
        path_str = str(filepath).lower().replace("\\", "/")
        ui_dirs = {"pages", "components", "elements", "widgets", "aw",
                   "aaw", "baw", "screens", "views", "uicomponents"}
        path_parts = set(path_str.split("/"))
        if ui_dirs.intersection(path_parts):
            return True

        # Check: package contains UI segments
        if package:
            pkg_parts = set(package.lower().split("."))
            if ui_dirs.intersection(pkg_parts):
                return True
            # Exclude explicitly non-UI packages
            if self._NON_UI_PATH_SEGMENTS.intersection(pkg_parts):
                return False

        # Has locator patterns
        try:
            content = filepath.read_text("utf-8")
            if re.search(r'By\.\w+|@FindBy|locator|Locator', content):
                return True
        except Exception:
            logger.warning("Failed to check UI relevance for file: %s", filepath, exc_info=True)
            pass

        return False

    def _infer_ui_packages(self, java_files: list[dict],
                           java_packages: list[str]) -> list[str]:
        """Infer which packages contain UI code.

        Returns list of package path substrings to include when scanning.
        Format: "com/acme/components", "com/acme/pages" (url-safe for path matching).
        """
        ui_packages = set()

        for f in java_files:
            if not f.get("is_ui_relevant"):
                continue
            pkg = f.get("package", "")
            if pkg:
                ui_packages.add(pkg.replace(".", "/"))

        # Also derive top-level UI package from package structure
        if java_packages:
            from collections import Counter
            pkg_counter = Counter(
                ".".join(p.split(".")[:3])  # top 3 segments
                for p in java_packages if p
            )
            # Add common package prefixes
            for pkg_prefix, count in pkg_counter.most_common(3):
                if count >= 2:
                    ui_packages.add(pkg_prefix.replace(".", "/"))

        return sorted(ui_packages)

    def _infer_base_class_map(self, sample_data: dict) -> dict[str, str]:
        """Infer base class → component type mappings from sampled files."""
        base_map = {}

        # Known mappings (from existing _BASE_CLASS_TYPE_MAP pattern)
        known = {
            "table": ["table", "grid", "datagrid"],
            "form": ["form"],
            "button": ["button", "btn"],
            "input": ["input", "textbox", "textfield"],
            "dialog": ["dialog", "modal", "popup"],
            "dropdown": ["dropdown", "select", "combo", "combobox"],
            "menu": ["menu"],
            "tree": ["tree"],
            "tab": ["tab"],
            "link": ["link"],
            "label": ["label"],
            "checkbox": ["checkbox"],
            "search": ["search"],
            "calendar": ["calendar", "datepicker", "date"],
        }

        for f in sample_data.get("java_files", []):
            extends = f.get("extends", "").lower()
            if not extends:
                continue
            for comp_type, keywords in known.items():
                for kw in keywords:
                    if kw in extends:
                        base_map[f["extends"]] = comp_type
                        break

        return base_map

    def _infer_locator_priorities(self, sample_data: dict) -> list[str]:
        """Infer locator attribute priority order from sampled files."""
        attr_counts = {}
        priority_order = ["id", "name", "css", "xpath", "data-testid",
                         "data-test", "data-module", "className", "tagName",
                         "linkText", "partialLinkText"]

        for f in sample_data.get("java_files", []):
            for attr in f.get("locator_attrs", []):
                attr_lower = attr.lower().replace("_", "")
                attr_counts[attr_lower] = attr_counts.get(attr_lower, 0) + 1

        # Sort existing priorities by frequency
        detected = sorted(attr_counts, key=attr_counts.get, reverse=True)
        # Add remaining standard priorities
        for attr in priority_order:
            if attr not in detected:
                detected.append(attr)

        return detected[:8]  # Top 8

    def _infer_naming_from_sample(self, sample_data: dict) -> dict:
        """Infer naming conventions from sampled files."""
        suffixes = {}
        prefixes = {}
        styles = {"camelCase": 0}

        for f in sample_data.get("java_files", []):
            class_name = f.get("class_name", "")
            if class_name:
                # Detect class suffix
                for suffix in self._UI_CLASS_SUFFIXES:
                    if class_name.lower().endswith(suffix) and len(class_name) > len(suffix):
                        full_suffix = class_name[-len(suffix):]
                        suffixes[full_suffix] = suffixes.get(full_suffix, 0) + 1
                        break

            # Detect method naming from file content
            annotations = f.get("annotations", [])
            if "Test" in annotations:
                styles["camelCase"] = styles.get("camelCase", 0) + 1
                # Check for snake_case in test names
                if "_" in class_name:
                    styles["snake_case"] = styles.get("snake_case", 0) + 1

        result = {}
        if suffixes:
            result["class_suffix"] = max(suffixes, key=suffixes.get)
            result["class_suffix_distribution"] = suffixes
        if prefixes:
            result["method_prefix"] = max(prefixes, key=prefixes.get)
            result["method_prefix_distribution"] = prefixes
        if len(styles) > 1:  # More than just camelCase count
            result["field_style"] = max(styles, key=styles.get)

        return result

    def _compute_profiling_confidence(self, profile: "FrameworkProfile") -> float:
        """Compute overall profiling confidence from field-level scores."""
        fields = [
            profile.ui_packages,
            profile.base_classes,
            profile.annotations,
            profile.locator_priorities,
            profile.naming_conventions,
            profile.layer_structure,
            profile.reference_directories,
            profile.output_config,
        ]
        scores = [f.confidence for f in fields if f.value]
        if not scores:
            return 0.3
        return sum(scores) / len(scores)

    # ── Phase 1.5: Extended Profile Inference ───────────────────

    def _infer_layer_structure(self, source_dirs: dict[str, str],
                                profile: "FrameworkProfile"):
        """Infer project code layers from source directory structure.

        Defaults to 4 layers based on project_type, adjusts dir names
        from actual directories found under source_dirs.
        """
        java = profile.project_type in ("java_maven", "java_gradle")
        root = self.project_root

        # Determine actual directory names from project
        pages_dir = source_dirs.get("pages", "")
        tests_dir = source_dirs.get("tests", "")
        aw_dir = source_dirs.get("component_aw", "")

        # Extract last directory component as the layer dir name
        def last_dir(path: str) -> str:
            return path.replace("\\", "/").rstrip("/").split("/")[-1] if path else ""

        # Build layer list: detect actual dir names from project
        layers = []
        layer_dirs = {
            "component_aw": last_dir(aw_dir) if aw_dir else ("components" if java else "aaw"),
            "page": last_dir(pages_dir) if pages_dir else ("pages" if java else "pages"),
            "test": last_dir(tests_dir) if tests_dir else ("tests" if java else "tests"),
            "test_data": "data" if java else "test_data",
        }

        # Check if expected directories exist under source root
        component_dir_exists = aw_dir and (root / aw_dir).exists()
        page_dir_exists = pages_dir and (root / pages_dir).exists()
        test_dir_exists = tests_dir and (root / tests_dir).exists()

        confidence = 0.6 if (component_dir_exists or page_dir_exists or test_dir_exists) else 0.45

        layers = [
            {
                "name": "component_aw",
                "dir": layer_dirs["component_aw"],
                "role": "UI 组件封装",
                "enabled": False,  # 组件 AW 由用户维护，不自动生成
            },
            {
                "name": "page",
                "dir": layer_dirs["page"],
                "role": "页面对象",
                "enabled": page_dir_exists,
            },
            {
                "name": "test",
                "dir": layer_dirs["test"],
                "role": "测试脚本",
                "enabled": True,
            },
            {
                "name": "test_data",
                "dir": layer_dirs["test_data"],
                "role": "测试数据",
                "enabled": True,
            },
        ]

        profile.layer_structure = ProfileField(
            value=layers,
            source="auto",
            confidence=confidence,
            description="项目代码分层结构。enabled=true 的层表示录制后会生成对应文件。"
                        "通过 NL 对话修改层名和目录名以匹配项目实际命名",
        )

    def _infer_reference_directories(self, source_dirs: dict[str, str],
                                      profile: "FrameworkProfile"):
        """Classify source directories by maturity based on file count and naming.

        mature: 文件 >= 3 且类名模式一致的目录
        developing: 文件 < 3 或命名混合的目录
        deprecated: 明确过时的目录标记（暂不自动检测）
        """
        root = self.project_root
        mature = []
        developing = []
        deprecated = []

        for label, dir_path in source_dirs.items():
            target = root / dir_path
            if not target.exists():
                continue
            files = list(target.glob("**/*.java")) + list(target.glob("**/*.py"))
            if not files:
                continue

            rel_path = str(target.relative_to(root)).replace("\\", "/")

            # Mature: 3+ files with consistent naming
            if len(files) >= 3:
                # Check naming consistency: most classes share a common suffix
                suffixes = {}
                for f in files:
                    stem = f.stem
                    for sfx in ["Page", "Test", "AW", "Component", "Widget", "Element",
                               "Builder", "Factory", "Data", "Helper", "Util"]:
                        if stem.endswith(sfx):
                            suffixes[sfx] = suffixes.get(sfx, 0) + 1
                            break
                dominant = max(suffixes.values()) if suffixes else 0
                if dominant >= len(files) * 0.6:
                    mature.append(rel_path)
                else:
                    developing.append(rel_path)
            else:
                developing.append(rel_path)

        confidence = 0.5 if mature else 0.4

        profile.reference_directories = ProfileField(
            value={
                "mature": mature,
                "developing": developing,
                "deprecated": deprecated,
            },
            source="auto",
            confidence=confidence,
            description="成熟目录代码作为框架权威参考，开发中目录仅作辅助，过时目录忽略。"
                        "通过 NL 对话添加或移除目录以调整参考范围",
        )

    def _infer_output_config(self, profile: "FrameworkProfile"):
        """Set default output config based on project type.

        Java projects: test_script + test_data (default templates)
        Python projects: test_script + test_data (default templates)
        """
        java = profile.project_type in ("java_maven", "java_gradle")

        generate = [
            {
                "type": "test_script",
                "dir": "tests" if java else "tests",
                "template": "testng_page_object" if java else "pytest_page_object",
            },
            {
                "type": "test_data",
                "dir": "data" if java else "test_data",
                "template": "builder" if java else "dataclass",
            },
        ]

        profile.output_config = ProfileField(
            value={"generate": generate},
            source="auto",
            confidence=0.65,
            description="录制完成后自动生成的文件类型及输出位置。"
                        "通过 NL 对话增删生成目标或调整模板",
        )

    def _infer_component_monitoring(self, profile: "FrameworkProfile"):
        """Initialize component monitoring config (disabled by default).

        Lists up to 10 candidate components from base_classes for user selection.
        """
        base_classes = profile.base_classes.value or {}
        candidate_components = [cls for cls in base_classes.keys() if cls][:10]

        profile.component_monitoring = ProfileField(
            value={
                "enabled": False,
                "components": candidate_components,
                "check_interval_days": 7,
            },
            source="auto",
            confidence=0.50,
            description="组件过时检测。开启后定期对比 KB 中组件快照与源码，发现方法增删或定位器变更时告警。"
                        "通过 NL 对话开关或调整监控组件列表",
        )
