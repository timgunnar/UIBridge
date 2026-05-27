"""Phase 1: Auto-discovery scanner — read-only, deterministic, zero-config.

Scans project root to infer build system, source dirs, AW components,
base classes, locator strategies, test dirs, and naming conventions.
Outputs a ProjectProfile with confidence scores on every field.
"""

import os
import re
from pathlib import Path
from typing import Optional

# ── Compiled regexes (compiled once, reused across files) ──

_JAVA_PACKAGE_RE = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)
_JAVA_CLASS_RE = re.compile(r'public\s+(?:abstract\s+)?class\s+(\w+)')
_JAVA_EXTENDS_RE = re.compile(r'extends\s+(\w+)')
_JAVA_IMPLEMENTS_RE = re.compile(r'implements\s+([\w,\s]+)')
_JAVA_ANNOTATION_RE = re.compile(r'@(\w+)')
_JAVA_LOCATOR_RE = re.compile(r'(?:@FindBy|By\.\w+|data-testid|data-test|data-module)')
_JAVA_TEST_ANNOTATION = "@Test"

_PY_IMPORT_RE = re.compile(r'(?:from|import)\s+([\w.]+)')
_PY_CLASS_RE = re.compile(r'class\s+(\w+)\s*(?:\(([^)]*)\))?:')
_PY_TEST_FUNC_RE = re.compile(r'^\s*def\s+(test_\w+)\s*\(', re.MULTILINE)
_PY_FIXTURE_RE = re.compile(r'@pytest\.fixture')

# ── Constants ──

_BUILD_FILE_DETECTORS = [
    ("pom.xml", "maven", "java"),
    ("build.gradle", "gradle", "java"),
    ("build.gradle.kts", "gradle", "java"),
    ("pyproject.toml", "poetry", "python"),
    ("setup.py", "setuptools", "python"),
    ("setup.cfg", "setuptools", "python"),
]

_JAVA_SOURCE_ROOTS = [
    "src/main/java",
    "src/test/java",
    "src",
]

_PYTHON_SOURCE_ROOTS = [
    "src",
    "tests",
    "test",
]

_AW_NAME_SUFFIXES = frozenset([
    "aw", "page", "component", "element", "widget", "view", "panel",
    "form", "table", "dialog", "modal", "tab", "menu", "header",
    "footer", "sidebar", "screen", "layout", "card", "drawer",
    "toast", "tooltip", "popover", "dropdown", "combobox", "button",
    "input", "checkbox", "radio", "select",
])

_TEST_DIR_NAMES = frozenset({"tests", "test", "src/test", "src/test/java",
                              "src/test/kotlin", "integrationTest"})

_NON_CODE_DIR_NAMES = frozenset({
    "__pycache__", ".git", ".svn", ".hg", "node_modules",
    "target", "build", "dist", ".idea", ".vscode", ".mvn",
    "venv", ".venv", ".tox", ".eggs", "egg-info",
})


class ProfileField:
    """A single inferred field with value, confidence, and provenance."""

    __slots__ = ("value", "confidence", "source")

    def __init__(self, value=None, confidence=0.5, source="auto"):
        self.value = value
        self.confidence = confidence
        self.source = source

    def to_dict(self):
        return {
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            value=d.get("value"),
            confidence=d.get("confidence", 0.5),
            source=d.get("source", "auto"),
        )

    def __repr__(self):
        return f"ProfileField(value={self.value!r}, confidence={self.confidence:.2f}, source={self.source!r})"

    def __eq__(self, other):
        if not isinstance(other, ProfileField):
            return NotImplemented
        return (self.value == other.value
                and self.confidence == other.confidence
                and self.source == other.source)


class ProjectProfile:
    """Auto-discovered project profile with per-field confidence scores.

    Fields (all ProfileField unless noted):
        project_type  – e.g. "java_maven", "python_pytest", "unknown"
        build_system  – e.g. "maven", "gradle", "poetry", "setuptools"
        language      – "java", "python", or "unknown"
        aw_dirs       – list of dir paths containing AW/Page components
        base_classes  – list of frequently-inherited class names
        locator_strategy – primary locator strategy name
        locator_priorities – ordered list of strategy names
        test_dirs     – list of directories containing test files
        naming_style  – "camelCase", "snake_case", or "mixed"
        source_dirs   – dict of {category: dir_path} for source directories
        profile_confidence – float 0.0-1.0 (computed, not a ProfileField)
    """

    def __init__(self):
        self.project_type = ProfileField("unknown", 0.1, "auto")
        self.build_system = ProfileField("unknown", 0.1, "auto")
        self.language = ProfileField("unknown", 0.1, "auto")
        self.aw_dirs = ProfileField([], 0.1, "auto")
        self.base_classes = ProfileField([], 0.1, "auto")
        self.locator_strategy = ProfileField("unknown", 0.1, "auto")
        self.locator_priorities = ProfileField([], 0.1, "auto")
        self.test_dirs = ProfileField([], 0.1, "auto")
        self.naming_style = ProfileField("unknown", 0.1, "auto")
        self.source_dirs = ProfileField({}, 0.1, "auto")
        self.profile_confidence = 0.1

    def to_dict(self) -> dict:
        return {
            "project_type": self.project_type.to_dict(),
            "build_system": self.build_system.to_dict(),
            "language": self.language.to_dict(),
            "aw_dirs": self.aw_dirs.to_dict(),
            "base_classes": self.base_classes.to_dict(),
            "locator_strategy": self.locator_strategy.to_dict(),
            "locator_priorities": self.locator_priorities.to_dict(),
            "test_dirs": self.test_dirs.to_dict(),
            "naming_style": self.naming_style.to_dict(),
            "source_dirs": self.source_dirs.to_dict(),
            "profile_confidence": self.profile_confidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectProfile":
        p = cls()
        p.project_type = ProfileField.from_dict(d.get("project_type", {}))
        p.build_system = ProfileField.from_dict(d.get("build_system", {}))
        p.language = ProfileField.from_dict(d.get("language", {}))
        p.aw_dirs = ProfileField.from_dict(d.get("aw_dirs", {}))
        p.base_classes = ProfileField.from_dict(d.get("base_classes", {}))
        p.locator_strategy = ProfileField.from_dict(d.get("locator_strategy", {}))
        p.locator_priorities = ProfileField.from_dict(d.get("locator_priorities", {}))
        p.test_dirs = ProfileField.from_dict(d.get("test_dirs", {}))
        p.naming_style = ProfileField.from_dict(d.get("naming_style", {}))
        p.source_dirs = ProfileField.from_dict(d.get("source_dirs", {}))
        p.profile_confidence = d.get("profile_confidence", 0.1)
        return p

    def __repr__(self):
        return (f"ProjectProfile(type={self.project_type.value}, lang={self.language.value}, "
                f"confidence={self.profile_confidence:.2f})")


# ═══════════════════════════════════════════════════════════════════
# Scanner
# ═══════════════════════════════════════════════════════════════════


class Scanner:
    """Auto-discovers project structure with zero configuration.

    Usage:
        scanner = Scanner()
        profile = scanner.discover("/path/to/project")
        print(profile.project_type.value)  # "java_maven"
    """

    def __init__(self):
        self._root: Optional[Path] = None

    def discover(self, project_root: str) -> ProjectProfile:
        """Run full auto-discovery on a project root directory.

        Steps:
          1. Detect build system + language from build files
          2. Find source directories (Java: src/main/java, etc.)
          3. Sample key files
          4. Infer AW dirs, base classes, test dirs, locators, naming
          5. Compute overall confidence

        Returns a ProjectProfile with all fields populated.
        """
        self._root = Path(project_root).resolve()
        profile = ProjectProfile()

        if not self._root.exists() or not self._root.is_dir():
            # Empty or nonexistent → lowest confidence
            return profile

        # Step 1: Detect build system + language
        self._detect_build_system(profile)

        # Step 2: Find source directories
        source_dirs = self._find_source_dirs(profile.language.value)
        profile.source_dirs = ProfileField(source_dirs, 0.6, "auto")

        # Step 3: Collect and sample source files
        samples = self._collect_samples(profile.language.value, source_dirs)

        if not samples:
            profile.profile_confidence = max(profile.build_system.confidence, 0.15)
            return profile

        # Step 4a: Infer AW/component directories
        aw_dirs = self._infer_aw_dirs(samples, profile.language.value)
        profile.aw_dirs = ProfileField(aw_dirs, 0.55 if aw_dirs else 0.2, "auto")

        # Step 4b: Infer base classes
        base_classes = self._infer_base_classes(samples, profile.language.value)
        profile.base_classes = ProfileField(base_classes, 0.5 if base_classes else 0.2, "auto")

        # Step 4c: Infer locator strategy
        locator_info = self._infer_locator_strategy(samples, profile.language.value)
        profile.locator_strategy = ProfileField(
            locator_info[0], 0.6 if locator_info[0] != "unknown" else 0.15, "auto"
        )
        profile.locator_priorities = ProfileField(
            locator_info[1], 0.55 if locator_info[1] else 0.15, "auto"
        )

        # Step 4d: Detect test directories
        test_dirs = self._infer_test_dirs(samples, profile.language.value, source_dirs)
        profile.test_dirs = ProfileField(test_dirs, 0.7 if test_dirs else 0.2, "auto")

        # Step 4e: Infer naming style
        naming = self._infer_naming_style(samples, profile.language.value)
        profile.naming_style = ProfileField(naming, 0.65 if naming != "unknown" else 0.15, "auto")

        # Step 5: Compute overall confidence
        profile.profile_confidence = self._compute_confidence(profile)

        return profile

    # ── Build system detection ──────────────────────────────────

    def _detect_build_system(self, profile: ProjectProfile) -> None:
        """Detect build system by scanning root for known build files."""
        found_files = []
        for filename, build_sys, lang in _BUILD_FILE_DETECTORS:
            if (self._root / filename).exists():
                found_files.append((filename, build_sys, lang))

        if not found_files:
            return  # stays "unknown" / 0.1

        # Pick first match (priority order in _BUILD_FILE_DETECTORS)
        filename, build_sys, lang = found_files[0]
        profile.build_system = ProfileField(build_sys, 0.9, filename)
        profile.language = ProfileField(lang, 0.95, filename)

        # Derive project_type
        if build_sys == "maven" and lang == "java":
            profile.project_type = ProfileField("java_maven", 0.85, filename)
        elif build_sys == "gradle" and lang == "java":
            profile.project_type = ProfileField("java_gradle", 0.85, filename)
        elif lang == "python":
            profile.project_type = ProfileField("python_pytest", 0.75, filename)

    # ── Source directory detection ──────────────────────────────

    def _find_source_dirs(self, language: str) -> dict[str, str]:
        """Find relevant source directories in the project tree.

        Returns dict like {"component_aw": "aaw/", "pages": "pages/", "tests": "tests/"}
        """
        result = {}

        if language == "java":
            # Java project: look under src/main/java, src/test/java
            main_java = self._root / "src" / "main" / "java"
            test_java = self._root / "src" / "test" / "java"

            if main_java.exists():
                result["component_aw"] = self._shortest_rel(main_java)
            if test_java.exists():
                result["tests"] = self._shortest_rel(test_java)

            # Fallback: scan for java dirs
            if not result:
                result = self._scan_for_lang_dirs(".java")

        elif language == "python":
            # Python project: look for src/, tests/, or project-root packages
            for candidate in ["src", "tests", "test"]:
                cand_path = self._root / candidate
                if cand_path.exists() and cand_path.is_dir():
                    if candidate in ("tests", "test"):
                        result["tests"] = self._shortest_rel(cand_path)
                    else:
                        result["component_aw"] = self._shortest_rel(cand_path)

            if not result:
                result = self._scan_for_lang_dirs(".py")

        else:
            # Unknown language — scan for both
            result = self._scan_for_lang_dirs(".py")
            if not result:
                result = self._scan_for_lang_dirs(".java")

        # Ensure we have at least a source root
        if not result:
            result["source"] = "."

        return result

    def _scan_for_lang_dirs(self, ext: str) -> dict[str, str]:
        """Find directories containing *ext files, up to depth 3."""
        result = {}
        try:
            for entry in os.scandir(self._root):
                if entry.is_dir() and entry.name not in _NON_CODE_DIR_NAMES:
                    sub = Path(entry.path)
                    files = list(sub.glob(f"**/*{ext}"))
                    if files:
                        rel = self._shortest_rel(sub)
                        if entry.name in _TEST_DIR_NAMES:
                            result["tests"] = rel
                        elif not result.get("component_aw"):
                            result["component_aw"] = rel
        except OSError:
            pass
        return result

    def _shortest_rel(self, path: Path) -> str:
        """Return relative path, using forward slashes."""
        try:
            return str(path.relative_to(self._root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    # ── Sampling ────────────────────────────────────────────────

    def _collect_samples(self, language: str,
                         source_dirs: dict[str, str]) -> list[dict]:
        """Collect and sample source files for analysis.

        Returns list of per-file dicts with keys:
          path, class_name, extends, annotations, locators,
          is_test, file_language
        """
        samples = []

        if language == "java":
            ext = ".java"
            max_files = 60
        elif language == "python":
            ext = ".py"
            max_files = 40
        else:
            # Unknown — try both
            for lang, e, mf in [("java", ".java", 60), ("python", ".py", 40)]:
                s = self._collect_samples(lang, source_dirs)
                samples.extend(s)
                if len(samples) >= 60:
                    samples = samples[:60]
                    break
            return samples

        file_paths = []
        for cat, dir_path in source_dirs.items():
            target = self._root / dir_path
            if target.exists():
                gathered = list(target.glob(f"**/*{ext}"))
                # Prioritize UI-relevant files: those with AW/Page suffixes
                ui_first = sorted(gathered, key=lambda p: (
                    0 if _is_ui_filename(p.stem) else 1, str(p)
                ))
                file_paths.extend(ui_first)

        # Sample up to max_files
        for fp in file_paths[:max_files]:
            info = self._profile_file(fp, language)
            if info:
                samples.append(info)

        return samples

    def _profile_file(self, filepath: Path, language: str) -> dict | None:
        """Extract key features from a single source file."""
        try:
            content = filepath.read_text("utf-8", errors="replace")
        except Exception:
            return None

        info = {
            "path": self._shortest_rel(filepath),
            "class_name": "",
            "extends": "",
            "annotations": [],
            "locators": [],
            "is_test": False,
            "file_language": language,
            "methods": [],
        }

        if language == "java":
            self._profile_java_content(content, filepath, info)
        else:
            self._profile_python_content(content, filepath, info)

        return info

    def _profile_java_content(self, content: str, filepath: Path,
                               info: dict) -> None:
        """Parse Java content for profiling features."""
        # Package — not needed for discovery but useful for debugging
        m = _JAVA_PACKAGE_RE.search(content)
        info["package"] = m.group(1) if m else ""

        # Class name
        m = _JAVA_CLASS_RE.search(content)
        if m:
            info["class_name"] = m.group(1)

        # Extends
        m = _JAVA_EXTENDS_RE.search(content)
        if m:
            info["extends"] = m.group(1)

        # Annotations
        info["annotations"] = _JAVA_ANNOTATION_RE.findall(content)

        # Is this a test file?
        if _JAVA_TEST_ANNOTATION in info["annotations"]:
            info["is_test"] = True
        if "test" in filepath.stem.lower() or "test" in filepath.parent.name.lower():
            info["is_test"] = True

        # Locators
        info["locators"] = self._extract_java_locators(content)

        # Method names (for naming style)
        for mm in re.finditer(r'(?:public|protected|private|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\(', content):
            info["methods"].append(mm.group(1))

    def _profile_python_content(self, content: str, filepath: Path,
                                 info: dict) -> None:
        """Parse Python content for profiling features."""
        # Class name
        m = _PY_CLASS_RE.search(content)
        if m:
            info["class_name"] = m.group(1)
            bases = m.group(2)
            if bases:
                info["extends"] = bases.split(",")[0].strip()

        # Test detection
        if _PY_TEST_FUNC_RE.search(content):
            info["is_test"] = True
        if "test" in filepath.stem.lower() or filepath.parent.name in _TEST_DIR_NAMES:
            info["is_test"] = True

        # Imports (as pseudo-annotations for pattern matching)
        imports = _PY_IMPORT_RE.findall(content)
        info["annotations"] = imports
        if "pytest" in str(imports):
            info["is_test"] = True

        # Method names
        for mm in re.finditer(r'^\s*def\s+(\w+)\s*\(', content, re.MULTILINE):
            info["methods"].append(mm.group(1))

        # Locators (page.locator, query_selector, find_element)
        locators = set()
        for pattern in [r'\.locator\(["\']([^"\']+)["\']',
                        r'\.get_by_role\(["\']([^"\']+)["\']',
                        r'\.get_by_test_id\(["\']([^"\']+)["\']',
                        r'find_element_by_\w+\(["\']([^"\']+)["\']',
                        r'By\.(\w+)\(["\']([^"\']+)["\']',
                        r"@pytest\.mark\.\w+"]:
            for mm in re.finditer(pattern, content):
                if mm.lastindex and mm.lastindex >= 1:
                    locators.add(mm.group(1))
        info["locators"] = list(locators)

    @staticmethod
    def _extract_java_locators(content: str) -> list[str]:
        """Extract locator strategy names from Java source."""
        strategies = set()
        # @FindBy annotations
        for m in re.finditer(r'@FindBy\(\s*(\w+)\s*=', content):
            strategies.add(m.group(1))
        # By.* calls
        for m in re.finditer(r'By\.(\w+)\(', content):
            strategies.add(m.group(1))
        # data-testid / data-test / data-module attributes
        for m in re.finditer(r'["\']data-(testid|test|module)["\']', content):
            strategies.add(f"data-{m.group(1)}")
        return sorted(strategies)

    # ── Inference helpers ───────────────────────────────────────

    def _infer_aw_dirs(self, samples: list[dict], language: str) -> list[str]:
        """Infer directories containing AW/Page components.

        Heuristic: directories where >=30% of files have UI-relevant names
        (suffixes like Page, AW, Component, etc.) or extend known base classes.
        """
        from collections import Counter
        dir_scores = Counter()  # dir → (ui_count, total_count) stored as dict separately

        dir_stats: dict[str, list] = {}  # dir → [ui_count, total_count]

        for s in samples:
            d = str(Path(s["path"]).parent).replace("\\", "/")
            if d == ".":
                continue
            if d not in dir_stats:
                dir_stats[d] = [0, 0]
            dir_stats[d][1] += 1

            class_name = s.get("class_name", "")
            extends = s.get("extends", "")
            if (_is_ui_filename(class_name)
                    or (extends and extends[0].isupper())
                    or _is_ui_filename(extends)):
                dir_stats[d][0] += 1

        aw_dirs = []
        for d, (ui_count, total) in dir_stats.items():
            if total >= 2 and ui_count / total >= 0.3:
                aw_dirs.append(d)

        return sorted(aw_dirs)

    def _infer_base_classes(self, samples: list[dict], language: str) -> list[str]:
        """Infer frequently-extended base classes from samples."""
        from collections import Counter
        extends_counts = Counter()

        for s in samples:
            ext = s.get("extends", "")
            if ext and ext[0].isupper():
                # Count meaningful base class names (exclude java.lang, builtins)
                if not ext.startswith(("Object", "object", "Exception", "Base")):
                    extends_counts[ext] += 1
                else:
                    extends_counts[ext] += 1

        # Return classes extended by 2+ files, sorted by frequency
        base_classes = [cls for cls, count in extends_counts.most_common(10)
                        if count >= 2]

        # If no multi-inherited base class found, return top ones anyway (lower confidence)
        if not base_classes:
            base_classes = [cls for cls, _ in extends_counts.most_common(5)]

        return base_classes

    def _infer_locator_strategy(self, samples: list[dict],
                                 language: str) -> tuple[str, list[str]]:
        """Infer primary locator strategy and priority order.

        Returns (primary_strategy, [ordered_priorities]).
        """
        from collections import Counter
        strategy_counts = Counter()

        # Known strategy names and their canonical order
        canonical_order = [
            "id", "name", "cssSelector", "xpath",
            "data-testid", "data-test", "data-module",
            "className", "tagName", "linkText", "partialLinkText",
            "role", "text", "label", "placeholder",
            "alt", "title", "test_id",
        ]

        for s in samples:
            for loc in s.get("locators", []):
                strategy_counts[loc] += 1

        # Sort detected strategies by frequency
        detected = [name for name, _ in strategy_counts.most_common()]
        # Append canonical-order strategies not yet seen
        for name in canonical_order:
            if name not in detected:
                detected.append(name)

        primary = detected[0] if detected else "unknown"
        return primary, detected[:8]

    def _infer_test_dirs(self, samples: list[dict], language: str,
                          source_dirs: dict[str, str]) -> list[str]:
        """Infer directories containing test code."""
        test_dirs = set()

        # Check source_dirs for test-labelled entries
        if "tests" in source_dirs:
            test_dirs.add(source_dirs["tests"])

        # Check individual samples
        for s in samples:
            if s.get("is_test"):
                d = str(Path(s["path"]).parent).replace("\\", "/")
                if d != ".":
                    # Walk up to find the test root
                    while d and d != ".":
                        leaf = d.rsplit("/", 1)[-1] if "/" in d else d
                        if leaf.lower() in _TEST_DIR_NAMES or "test" in leaf.lower():
                            test_dirs.add(d)
                            break
                        d = str(Path(d).parent).replace("\\", "/")

        # If samples showed tests in a parent dir of an already-known dir, generalize
        generalized = set()
        for d in test_dirs:
            # Keep the most specific test directory
            generalized.add(d)

        return sorted(generalized)

    def _infer_naming_style(self, samples: list[dict], language: str) -> str:
        """Infer naming convention: camelCase, snake_case, or mixed."""
        camel_count = 0
        snake_count = 0

        for s in samples:
            for name in s.get("methods", []):
                if "_" in name:
                    snake_count += 1
                elif any(c.isupper() for c in name):
                    # has uppercase but no underscores → camelCase
                    camel_count += 1
                elif name.islower():
                    snake_count += 1  # single lowercase word → either style

            # Also check class names
            cn = s.get("class_name", "")
            if cn:
                if "_" in cn and cn[0].isupper():
                    # PascalCase with underscores → hybrid, count as snake
                    snake_count += 1
                elif "_" not in cn:
                    camel_count += 1

        total = camel_count + snake_count
        if total == 0:
            return "unknown"

        camel_ratio = camel_count / total
        if camel_ratio >= 0.7:
            return "camelCase"
        elif camel_ratio <= 0.3:
            return "snake_case"
        else:
            return "mixed"

    def _compute_confidence(self, profile: ProjectProfile) -> float:
        """Compute overall profile confidence from field scores."""
        fields = [
            profile.project_type,
            profile.build_system,
            profile.language,
            profile.aw_dirs,
            profile.base_classes,
            profile.locator_strategy,
            profile.locator_priorities,
            profile.test_dirs,
            profile.naming_style,
            profile.source_dirs,
        ]
        scores = [f.confidence for f in fields if f.confidence > 0.1]
        if not scores:
            return 0.1
        return sum(scores) / len(scores)


# ── Utility ────────────────────────────────────────────────────


def _is_ui_filename(name: str) -> bool:
    """Check if a class/file name looks UI-relevant."""
    name_lower = name.lower()
    for suffix in _AW_NAME_SUFFIXES:
        if name_lower.endswith(suffix) and len(name_lower) > len(suffix):
            return True
    return False
