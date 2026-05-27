"""FileScanner — glob scan and classify source files by type.

Classifies files into: AW, Page, Test, Util, Config, Unknown.
Classification is based on file naming, directory placement, and content heuristics.
"""

import os
from pathlib import Path
from typing import Optional


class FileClass:
    """Constants for file classification."""
    AW = "aw"           # Component / Action Word
    PAGE = "page"       # Page Object
    TEST = "test"       # Test script
    UTIL = "util"       # Utility / helper
    CONFIG = "config"   # Configuration
    UNKNOWN = "unknown"


# ── Classification patterns ──

_AW_SUFFIXES = frozenset({
    "aw", "component", "element", "widget", "table", "form",
    "button", "input", "dialog", "modal", "dropdown", "menu",
    "tab", "panel", "card", "header", "footer", "sidebar",
    "toast", "tooltip", "combobox", "checkbox", "radio",
})

_PAGE_SUFFIXES = frozenset({"page", "screen", "view"})

_CONFIG_DIRS = frozenset({"config", "conf", "resources", "properties"})
_UTIL_DIRS = frozenset({"util", "utils", "helper", "helpers", "common"})


class FileScanner:
    """Scans and classifies source files in a project directory."""

    def __init__(self, root: str):
        self.root = Path(root)

    def scan(self, pattern: str = "**/*.java") -> list[Path]:
        """Glob-scan for files matching a pattern.

        Excludes common non-code directories (__pycache__, node_modules, etc.).
        """
        excluded = {"__pycache__", ".git", ".svn", ".hg", "node_modules",
                     "target", "build", "dist", ".idea", ".vscode", ".mvn",
                     "venv", ".venv", ".tox", ".eggs"}
        results = []
        for f in self.root.glob(pattern):
            path_str = str(f).replace("\\", "/")
            if any(f"/{excl}/" in path_str for excl in excluded):
                continue
            results.append(f)
        return sorted(results)

    def classify(self, filepath: str | Path) -> str:
        """Classify a single file into AW/Page/Test/Util/Config/Unknown.

        Heuristics (in priority order):
          1. Directory name signals (config/ → CONFIG, utils/ → UTIL)
          2. File name suffix (Page.java → PAGE, AW.java → AW)
          3. Parent directory suffix (pages/ → PAGE, tests/ → TEST)
          4. Content-based (def test_ → TEST, extends BasePage → PAGE)
        """
        path = Path(filepath) if isinstance(filepath, str) else filepath
        stem = path.stem.lower()
        parent = path.parent.name.lower()
        full_path = str(path).lower().replace("\\", "/")

        # 1. Directory signals
        if any(f"/{d}/" in full_path for d in _CONFIG_DIRS):
            return FileClass.CONFIG
        if any(f"/{d}/" in full_path for d in _UTIL_DIRS):
            return FileClass.UTIL

        # 2. Parent directory name
        if parent in ("tests", "test"):
            return FileClass.TEST
        if parent in ("pages", "screens", "views"):
            return FileClass.PAGE
        if parent in _AW_SUFFIXES:
            return FileClass.AW
        if parent in _CONFIG_DIRS:
            return FileClass.CONFIG
        if parent in _UTIL_DIRS:
            return FileClass.UTIL

        # 3. File name suffix
        for suffix in _AW_SUFFIXES:
            if stem.endswith(suffix) and len(stem) > len(suffix):
                return FileClass.AW
        for suffix in _PAGE_SUFFIXES:
            if stem.endswith(suffix) and len(stem) > len(suffix):
                return FileClass.PAGE

        # 4. "test" in filename
        if "test" in stem:
            # Distinguish test files from test utilities
            if stem.startswith("test") or stem.endswith("test"):
                return FileClass.TEST

        return FileClass.UNKNOWN

    def classify_all(self, pattern: str = "**/*.java") -> dict[str, list[Path]]:
        """Scan and classify all matching files.

        Returns dict with keys: aw, page, test, util, config, unknown
        Each value is a list of Path objects.
        """
        classified = {
            FileClass.AW: [],
            FileClass.PAGE: [],
            FileClass.TEST: [],
            FileClass.UTIL: [],
            FileClass.CONFIG: [],
            FileClass.UNKNOWN: [],
        }
        for f in self.scan(pattern):
            c = self.classify(f)
            classified[c].append(f)
        return classified

    def count_by_class(self, pattern: str = "**/*.java") -> dict[str, int]:
        """Return file counts per classification."""
        classified = self.classify_all(pattern)
        return {k: len(v) for k, v in classified.items()}
