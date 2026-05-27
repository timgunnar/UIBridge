"""LocatorExtractor — extract XPath, CSS, @FindBy, and other locators from source.

Identifies all locator strategies used in a project, extracts actual
locator values, and builds a usage profile for each strategy type.
"""

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from ..parser import UnifiedAST, parse_file

# ── Locator extraction regexes ──

# Java: @FindBy(id = "foo"), @FindBy(xpath = "//div"), By.id("foo")
_JAVA_FINDBY_RE = re.compile(
    r'@FindBy\(\s*(?:how\s*=\s*How\.(\w+)\s*,\s*)?(\w+)\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_JAVA_BY_RE = re.compile(r'By\.(\w+)\s*\(\s*["\']([^"\']+)["\']')
_JAVA_DATA_ATTR_RE = re.compile(r'["\']data-(testid|test|module)["\']\s*,\s*["\']([^"\']+)["\']')

# Python: page.locator("css=..."), page.get_by_role("button"), find_element(By.ID, "foo")
_PY_LOCATOR_RE = re.compile(r'\.locator\(\s*["\']([^"\']+)["\']')
_PY_GET_BY_RE = re.compile(r'\.get_by_(\w+)\(\s*["\']([^"\']+)["\']')
_PY_FIND_ELEMENT_RE = re.compile(r'find_element(?:_by_\w+)?\(\s*["\']([^"\']+)["\']')
_PY_BY_RE = re.compile(r'By\.(\w+)\s*,\s*["\']([^"\']+)["\']')


class LocatorInfo:
    """A single locator occurrence with metadata."""

    __slots__ = ("strategy", "value", "target_element", "filepath", "class_name", "method_name")

    def __init__(self, strategy: str = "", value: str = "",
                 target_element: str = "", filepath: str = "",
                 class_name: str = "", method_name: str = ""):
        self.strategy = strategy         # e.g., "id", "xpath", "css", "data-testid"
        self.value = value               # the actual locator string
        self.target_element = target_element  # element being located
        self.filepath = filepath
        self.class_name = class_name
        self.method_name = method_name

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "value": self.value,
            "target_element": self.target_element,
            "filepath": self.filepath,
            "class_name": self.class_name,
            "method_name": self.method_name,
        }

    def __repr__(self):
        return f"LocatorInfo({self.strategy}={self.value!r})"


# ── Normalization ──

_STRATEGY_ALIASES = {
    "id": "id",
    "ID": "id",
    "name": "name",
    "NAME": "name",
    "xpath": "xpath",
    "XPATH": "xpath",
    "css": "cssSelector",
    "cssSelector": "cssSelector",
    "CSS": "cssSelector",
    "className": "className",
    "CLASS_NAME": "className",
    "tagName": "tagName",
    "TAG_NAME": "tagName",
    "linkText": "linkText",
    "LINK_TEXT": "linkText",
    "partialLinkText": "partialLinkText",
    "PARTIAL_LINK_TEXT": "partialLinkText",
    "testid": "data-testid",
    "test": "data-test",
    "module": "data-module",
    "role": "role",
    "text": "text",
    "label": "label",
    "placeholder": "placeholder",
    "alt": "alt",
    "title": "title",
    "test_id": "test_id",
}


class LocatorExtractor:
    """Extracts locators from source files and builds usage profiles."""

    def __init__(self):
        self._locators: list[LocatorInfo] = []

    def extract_from_file(self, filepath: str) -> list[LocatorInfo]:
        """Extract all locators from a single file.

        Results are also appended to self._locators for aggregate queries.
        """
        path = Path(filepath)
        if not path.exists():
            return []

        try:
            content = path.read_text("utf-8", errors="replace")
        except Exception:
            return []

        locators = []

        if path.suffix == ".java":
            locators = self._extract_java_locators(filepath, content)
        elif path.suffix == ".py":
            locators = self._extract_python_locators(filepath, content)

        self._locators.extend(locators)
        return locators

    def _extract_java_locators(self, filepath: str, content: str) -> list[LocatorInfo]:
        """Extract locators from Java source code."""
        locators = []

        # Get class name for context
        class_m = re.search(r'class\s+(\w+)', content)
        class_name = class_m.group(1) if class_m else Path(filepath).stem

        # Track current method
        current_method = "<unknown>"
        for line in content.split("\n"):
            method_m = re.search(
                r'(?:public|protected|private|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\(', line)
            if method_m:
                current_method = method_m.group(1)

            # @FindBy(how = How.ID, using = "foo") or @FindBy(id = "foo")
            for m in _JAVA_FINDBY_RE.finditer(line):
                how = m.group(1)  # How.ID, etc. (optional)
                attr = m.group(2)  # id, xpath, css, etc.
                value = m.group(3)
                strategy = _STRATEGY_ALIASES.get(how, _STRATEGY_ALIASES.get(attr, attr.lower()))
                locators.append(LocatorInfo(
                    strategy=strategy, value=value,
                    filepath=filepath, class_name=class_name,
                    method_name=current_method,
                ))

            # By.id("foo"), By.xpath("//div"), etc.
            for m in _JAVA_BY_RE.finditer(line):
                strategy = _STRATEGY_ALIASES.get(m.group(1), m.group(1).lower())
                value = m.group(2)
                locators.append(LocatorInfo(
                    strategy=strategy, value=value,
                    filepath=filepath, class_name=class_name,
                    method_name=current_method,
                ))

            # data-testid, data-test, data-module
            for m in _JAVA_DATA_ATTR_RE.finditer(line):
                strategy = f"data-{m.group(1)}"
                value = m.group(2)
                locators.append(LocatorInfo(
                    strategy=strategy, value=value,
                    filepath=filepath, class_name=class_name,
                    method_name=current_method,
                ))

        return locators

    def _extract_python_locators(self, filepath: str, content: str) -> list[LocatorInfo]:
        """Extract locators from Python source code."""
        locators = []

        class_m = re.search(r'class\s+(\w+)', content)
        class_name = class_m.group(1) if class_m else Path(filepath).stem

        current_method = "<module>"
        for line in content.split("\n"):
            method_m = re.search(r'^\s*def\s+(\w+)\s*\(', line)
            if method_m:
                current_method = method_m.group(1)

            # .locator("css=...") or .locator("xpath=...")
            for m in _PY_LOCATOR_RE.finditer(line):
                value = m.group(1)
                if "=" in value:
                    strategy, _, actual_value = value.partition("=")
                    strategy = _STRATEGY_ALIASES.get(strategy.strip(), strategy.strip())
                else:
                    strategy = "cssSelector"  # default
                    actual_value = value
                locators.append(LocatorInfo(
                    strategy=strategy, value=actual_value,
                    filepath=filepath, class_name=class_name,
                    method_name=current_method,
                ))

            # .get_by_role("button", ...), .get_by_text("Submit"), .get_by_test_id("...")
            for m in _PY_GET_BY_RE.finditer(line):
                strategy = _STRATEGY_ALIASES.get(m.group(1), m.group(1))
                value = m.group(2)
                locators.append(LocatorInfo(
                    strategy=strategy, value=value,
                    filepath=filepath, class_name=class_name,
                    method_name=current_method,
                ))

            # By.ID, "foo" (Selenium Python)
            for m in _PY_BY_RE.finditer(line):
                strategy = _STRATEGY_ALIASES.get(m.group(1), m.group(1).lower())
                value = m.group(2)
                locators.append(LocatorInfo(
                    strategy=strategy, value=value,
                    filepath=filepath, class_name=class_name,
                    method_name=current_method,
                ))

        return locators

    def extract_from_files(self, filepaths: list[str]) -> list[LocatorInfo]:
        """Extract locators from multiple files."""
        self._locators = []
        for fp in filepaths:
            self._locators.extend(self.extract_from_file(fp))
        return self._locators

    def get_strategy_usage(self) -> dict[str, int]:
        """Count locators per strategy type.

        Returns dict of {strategy_name: occurrence_count}.
        """
        counter = Counter(l.strategy for l in self._locators)
        return dict(counter.most_common())

    def get_strategy_priorities(self) -> list[str]:
        """Return strategy names in descending order of usage frequency."""
        usage = self.get_strategy_usage()
        return list(usage.keys())

    def get_primary_strategy(self) -> str:
        """Return the most-used locator strategy."""
        usage = self.get_strategy_usage()
        if not usage:
            return "unknown"
        return max(usage, key=usage.get)

    def get_locators_by_strategy(self, strategy: str) -> list[LocatorInfo]:
        """Filter locators by strategy type."""
        return [l for l in self._locators if l.strategy == strategy]

    def get_locators_by_file(self) -> dict[str, list[LocatorInfo]]:
        """Group locators by file path."""
        grouped = defaultdict(list)
        for loc in self._locators:
            grouped[loc.filepath].append(loc)
        return dict(grouped)

    def get_unique_values(self, strategy: str | None = None) -> set[str]:
        """Get unique locator values, optionally filtered by strategy."""
        if strategy:
            locs = self.get_locators_by_strategy(strategy)
        else:
            locs = self._locators
        return {l.value for l in locs}

    def get_complex_locators(self) -> list[LocatorInfo]:
        """Find locators that look complex (long XPath, CSS with combinators)."""
        complex_locs = []
        for loc in self._locators:
            if loc.strategy == "xpath" and len(loc.value) > 40:
                complex_locs.append(loc)
            elif loc.strategy == "cssSelector" and (" " in loc.value or ">" in loc.value):
                complex_locs.append(loc)
        return complex_locs
