"""AnnotationExtractor — extract @Test, @FindBy, @Override, decorators etc.

Identifies annotations/decorators used across a project and classifies
them into: test, locator, lifecycle, framework, custom.
"""

import re
from collections import Counter
from pathlib import Path
from typing import Optional

from ..parser import UnifiedAST, parse_file

# ── Annotation classification tables ──

_TEST_ANNOTATIONS = frozenset({
    "Test", "BeforeClass", "AfterClass", "BeforeMethod", "AfterMethod",
    "BeforeTest", "AfterTest", "BeforeSuite", "AfterSuite",
    "BeforeEach", "AfterEach", "BeforeAll", "AfterAll",
    "TestNG", "ParameterizedTest", "RepeatedTest", "TestFactory",
    "TestTemplate", "TestMethodOrder",
})

_LOCATOR_ANNOTATIONS = frozenset({
    "FindBy", "FindBys", "FindAll", "AndroidFindBy", "iOSFindBy",
    "CacheLookup",
})

_LIFECYCLE_ANNOTATIONS = frozenset({
    "Before", "After", "BeforeClass", "AfterClass",
    "Override", "Deprecated", "SuppressWarnings", "SafeVarargs",
    "FunctionalInterface",
})

_FRAMEWORK_ANNOTATIONS = frozenset({
    "SpringBootApplication", "Component", "Service", "Repository",
    "Controller", "RestController", "Autowired", "Value",
    "Configuration", "Bean", "Scope", "Qualifier",
})

_PY_TEST_DECORATORS = frozenset({
    "pytest.mark", "pytest.fixture", "pytest.mark.parametrize",
    "mock.patch", "unittest.mock.patch",
})


class AnnotationInfo:
    """Information about a single annotation occurrence."""

    __slots__ = ("name", "category", "args", "target", "filepath", "line")

    def __init__(self, name: str = "", category: str = "unknown",
                 args: dict | None = None, target: str = "",
                 filepath: str = "", line: int = 0):
        self.name = name
        self.category = category
        self.args = args or {}
        self.target = target  # class, method, field
        self.filepath = filepath
        self.line = line

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "args": self.args,
            "target": self.target,
            "filepath": self.filepath,
            "line": self.line,
        }


class AnnotationExtractor:
    """Extracts and classifies annotations/decorators from source files."""

    def __init__(self, use_ast: bool = True):
        self.use_ast = use_ast
        self._annotations: list[AnnotationInfo] = []

    def analyze_file(self, filepath: str) -> list[AnnotationInfo]:
        """Extract all annotations from a single file.

        Results are also appended to self._annotations for aggregate queries.
        """
        path = Path(filepath)
        if not path.exists():
            return []

        try:
            content = path.read_text("utf-8", errors="replace")
        except Exception:
            return []

        if self.use_ast:
            results = self._analyze_with_ast(filepath, content)
        else:
            results = self._analyze_with_regex(filepath, content, path.suffix)

        self._annotations.extend(results)
        return results

    def _analyze_with_ast(self, filepath: str, content: str) -> list[AnnotationInfo]:
        """Use UnifiedAST for structured annotation extraction."""
        ast = parse_file(filepath)
        results = []

        # File-level annotations
        for ann in ast.annotations:
            results.append(AnnotationInfo(
                name=ann.name,
                category=self._classify(ann.name),
                args=ann.attrs.get("args", {}),
                target="file",
                filepath=filepath,
            ))

        # Class-level + method-level + field-level
        for cls in ast.classes:
            for ann in cls.attrs.get("annotations", []):
                results.append(AnnotationInfo(
                    name=ann.name,
                    category=self._classify(ann.name),
                    args=ann.attrs.get("args", {}),
                    target="class",
                    filepath=filepath,
                ))
            for method in cls.attrs.get("methods", []):
                for ann in method.attrs.get("annotations", []):
                    results.append(AnnotationInfo(
                        name=ann.name,
                        category=self._classify(ann.name),
                        args=ann.attrs.get("args", {}),
                        target="method",
                        filepath=filepath,
                    ))
            for field in cls.attrs.get("fields", []):
                for ann in field.attrs.get("annotations", []):
                    results.append(AnnotationInfo(
                        name=ann.name,
                        category=self._classify(ann.name),
                        args=ann.attrs.get("args", {}),
                        target="field",
                        filepath=filepath,
                    ))

        return results

    def _analyze_with_regex(self, filepath: str, content: str,
                             suffix: str) -> list[AnnotationInfo]:
        """Regex-based annotation extraction."""
        results = []

        if suffix == ".java":
            for m in re.finditer(r'@(\w+)(?:\(([^)]*)\))?', content):
                name = m.group(1)
                args_raw = m.group(2) or ""
                args = {}
                for am in re.finditer(r'(\w+)\s*=\s*("[^"]*"|\'[^\']*\'|[^,]+)', args_raw):
                    args[am.group(1)] = am.group(2).strip('"\'')
                results.append(AnnotationInfo(
                    name=name,
                    category=self._classify(name),
                    args=args,
                    target="unknown",
                    filepath=filepath,
                ))
        elif suffix == ".py":
            for m in re.finditer(r'@(\w+(?:\.\w+)*(?:\([^)]*\))?)', content):
                raw = m.group(1)
                if "(" in raw:
                    name = raw[:raw.index("(")]
                else:
                    name = raw
                results.append(AnnotationInfo(
                    name=name,
                    category=self._classify(name),
                    target="unknown",
                    filepath=filepath,
                ))

        return results

    @staticmethod
    def _classify(name: str) -> str:
        """Classify an annotation name into a category."""
        # Strip package prefix for fully-qualified names
        short = name.split(".")[-1] if "." in name else name

        if short in _TEST_ANNOTATIONS:
            return "test"
        if short in _LOCATOR_ANNOTATIONS:
            return "locator"
        if short in _LIFECYCLE_ANNOTATIONS:
            return "lifecycle"
        if short in _FRAMEWORK_ANNOTATIONS:
            return "framework"
        if name in _PY_TEST_DECORATORS or short in _PY_TEST_DECORATORS:
            return "test"
        # Heuristic: if it starts with "Test" → test
        if short.startswith("Test") and short != "TestConfiguration":
            return "test"
        return "custom"

    def analyze_files(self, filepaths: list[str]) -> list[AnnotationInfo]:
        """Extract annotations from multiple files."""
        self._annotations = []
        for fp in filepaths:
            self._annotations.extend(self.analyze_file(fp))
        return self._annotations

    def get_frequencies(self) -> dict[str, int]:
        """Return annotation name → occurrence count."""
        counter = Counter(a.name for a in self._annotations)
        return dict(counter.most_common())

    def get_by_category(self, category: str) -> list[AnnotationInfo]:
        """Filter annotations by category."""
        return [a for a in self._annotations if a.category == category]

    def get_category_counts(self) -> dict[str, int]:
        """Count annotations per category."""
        counter = Counter(a.category for a in self._annotations)
        return dict(counter)

    def get_locator_annotations(self) -> list[AnnotationInfo]:
        """Get all locator-type annotations (e.g., @FindBy)."""
        return self.get_by_category("locator")

    def get_test_annotations(self) -> list[AnnotationInfo]:
        """Get all test-type annotations (e.g., @Test)."""
        return self.get_by_category("test")
