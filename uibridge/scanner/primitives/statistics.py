"""StatisticsCollector — naming distributions, import frequency, file metrics.

Collects project-wide statistics: naming styles, import popularity,
file size distributions, comment ratios, etc.
"""

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..parser import UnifiedAST, parse_file


class StatisticsCollector:
    """Collects aggregate statistics across source files."""

    def __init__(self):
        self._file_count = 0
        self._total_lines = 0
        self._comment_lines = 0
        self._naming_counter = Counter()      # naming_style → count
        self._import_counter = Counter()       # module → count
        self._suffix_counter = Counter()       # class suffix → count
        self._prefix_counter = Counter()       # method prefix → count
        self._file_sizes: list[int] = []       # line counts per file
        self._class_counts: list[int] = []     # classes per file
        self._method_counts: list[int] = []    # methods per class

    def analyze_file(self, filepath: str) -> dict[str, Any]:
        """Collect statistics from a single file.

        Returns a dict with per-file stats.
        """
        path = Path(filepath)
        if not path.exists():
            return {}

        try:
            content = path.read_text("utf-8", errors="replace")
        except Exception:
            return {}

        lines = content.split("\n")
        total_lines = len(lines)
        comment_lines = sum(1 for l in lines
                           if l.strip().startswith("//") or l.strip().startswith("#")
                           or l.strip().startswith("/*") or l.strip().startswith("*")
                           or l.strip().startswith("*/"))

        self._file_count += 1
        self._total_lines += total_lines
        self._comment_lines += comment_lines
        self._file_sizes.append(total_lines)

        # Parse with UnifiedAST for structured info
        ast = parse_file(filepath)
        class_count = len(ast.classes)
        self._class_counts.append(class_count)

        # Analyze naming from class/method names
        for cls in ast.classes:
            self._analyze_class_naming(cls.name)
            for method in cls.attrs.get("methods", []):
                self._analyze_method_naming(method.name)
            self._method_counts.append(len(cls.attrs.get("methods", [])))

        # Import frequency
        for imp in ast.imports:
            module = imp.attrs.get("names", [imp.name])[0] if imp.attrs.get("names") else imp.name
            self._import_counter[module] += 1

        return {
            "filepath": filepath,
            "total_lines": total_lines,
            "comment_lines": comment_lines,
            "class_count": class_count,
            "comment_ratio": comment_lines / max(total_lines, 1),
        }

    def _analyze_class_naming(self, name: str) -> None:
        """Extract naming style and suffix from a class name."""
        if not name:
            return
        # Suffix detection
        for suffix in ["Page", "Test", "AW", "Component", "Widget", "Element",
                       "Factory", "Builder", "Data", "Helper", "Util", "Manager",
                       "Service", "Repository", "Controller", "Handler",
                       "Listener", "Filter", "Mapper", "Converter", "Validator"]:
            if name.endswith(suffix) and len(name) > len(suffix):
                self._suffix_counter[suffix] += 1
                break

        # Naming style
        if "_" in name:
            self._naming_counter["snake_case"] += 1
        elif any(c.isupper() for c in name[1:]):
            self._naming_counter["camelCase"] += 1
        elif name.islower():
            self._naming_counter["lowercase"] += 1
        else:
            self._naming_counter["camelCase"] += 1

    def _analyze_method_naming(self, name: str) -> None:
        """Extract naming style and prefix from a method name."""
        if not name:
            return

        # Prefix detection
        for prefix in ["get", "set", "is", "has", "should", "can", "will",
                       "click", "type", "select", "check", "verify", "wait",
                       "find", "create", "update", "delete", "test"]:
            if name.lower().startswith(prefix.lower()) and len(name) > len(prefix):
                # Only count if the prefix is followed by uppercase (camelCase)
                if len(name) > len(prefix) and name[len(prefix)].isupper():
                    self._prefix_counter[prefix] += 1
                    break

        # Naming style
        if "_" in name:
            self._naming_counter["snake_case"] += 1
        elif any(c.isupper() for c in name):
            self._naming_counter["camelCase"] += 1
        else:
            self._naming_counter["lowercase"] += 1

    def analyze_files(self, filepaths: list[str]) -> dict[str, Any]:
        """Collect aggregate statistics from multiple files.

        Returns a comprehensive stats dict.
        """
        for fp in filepaths:
            self.analyze_file(fp)
        return self.get_summary()

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of all collected statistics."""
        return {
            "file_count": self._file_count,
            "total_lines": self._total_lines,
            "comment_lines": self._comment_lines,
            "comment_ratio": (self._comment_lines / max(self._total_lines, 1)),
            "avg_file_size": (self._total_lines / max(self._file_count, 1)),
            "median_file_size": self._median(self._file_sizes),
            "avg_classes_per_file": (sum(self._class_counts) / max(len(self._class_counts), 1)),
            "avg_methods_per_class": (sum(self._method_counts) / max(len(self._method_counts), 1)),
            "dominant_naming_style": self._naming_counter.most_common(1)[0][0] if self._naming_counter else "unknown",
            "naming_distribution": dict(self._naming_counter.most_common()),
            "top_suffixes": dict(self._suffix_counter.most_common(10)),
            "top_prefixes": dict(self._prefix_counter.most_common(10)),
            "top_imports": dict(self._import_counter.most_common(20)),
        }

    @staticmethod
    def _median(values: list[int]) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        if n % 2 == 0:
            return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
        return float(sorted_vals[n // 2])
