"""InheritanceAnalyzer — extract extends/implements from source files.

Analyzes class inheritance hierarchies across a project to identify
base classes, interface implementations, and inheritance depth.
"""

import re
from collections import Counter
from pathlib import Path
from typing import Optional

from ..parser import UnifiedAST, parse_file

# ── Regex for quick extends extraction (no full parse needed) ──

_JAVA_EXTENDS_RE = re.compile(r'class\s+(\w+)(?:\s+extends\s+([\w.<>]+))?', re.MULTILINE)
_JAVA_IMPLEMENTS_RE = re.compile(r'class\s+\w+(?:\s+extends\s+[\w.<>]+)?\s+implements\s+([\w.<>,\s]+)', re.MULTILINE)
_PY_BASES_RE = re.compile(r'class\s+(\w+)\s*\(([^)]*)\)\s*:', re.MULTILINE)


class InheritanceNode:
    """Represents one class and its inheritance relationship."""

    __slots__ = ("class_name", "extends_list", "implements_list", "filepath", "depth_guess")

    def __init__(self, class_name: str, extends: list[str] | None = None,
                 implements: list[str] | None = None, filepath: str = "",
                 depth_guess: int = 0):
        self.class_name = class_name
        self.extends_list = extends or []
        self.implements_list = implements or []
        self.filepath = filepath
        self.depth_guess = depth_guess  # inferred depth in hierarchy

    def to_dict(self) -> dict:
        return {
            "class_name": self.class_name,
            "extends": self.extends_list,
            "implements": self.implements_list,
            "filepath": self.filepath,
            "depth_guess": self.depth_guess,
        }


class InheritanceAnalyzer:
    """Analyzes class inheritance across a set of source files."""

    def __init__(self, use_ast: bool = True):
        self.use_ast = use_ast
        self._nodes: list[InheritanceNode] = []

    def analyze_file(self, filepath: str) -> Optional[InheritanceNode]:
        """Extract inheritance info from a single file."""
        path = Path(filepath)
        if not path.exists():
            return None

        try:
            content = path.read_text("utf-8", errors="replace")
        except Exception:
            return None

        if self.use_ast:
            return self._analyze_with_ast(filepath, content)

        return self._analyze_with_regex(filepath, content, path.suffix)

    def _analyze_with_ast(self, filepath: str, content: str) -> Optional[InheritanceNode]:
        """Use UnifiedAST parser for extraction."""
        ast = parse_file(filepath)
        if not ast.classes:
            # Try regex fallback for the main class
            return self._analyze_with_regex(filepath, content, Path(filepath).suffix)

        cls = ast.classes[0]
        node = InheritanceNode(
            class_name=cls.name,
            extends=cls.attrs.get("bases", []) or [cls.attrs.get("extends", "")] if cls.attrs.get("extends") else [],
            implements=cls.attrs.get("implements", []),
            filepath=filepath,
            depth_guess=0,
        )
        return node

    def _analyze_with_regex(self, filepath: str, content: str,
                             suffix: str) -> Optional[InheritanceNode]:
        """Fast regex-based extraction without full parse."""
        if suffix == ".java":
            extends_m = _JAVA_EXTENDS_RE.search(content)
            implements_m = _JAVA_IMPLEMENTS_RE.search(content)
            class_name = extends_m.group(1) if extends_m else ""
            extends = [extends_m.group(2)] if extends_m and extends_m.group(2) else []
            implements_raw = implements_m.group(1) if implements_m else ""
            implements = [i.strip() for i in implements_raw.split(",") if i.strip()]
        elif suffix == ".py":
            m = _PY_BASES_RE.search(content)
            if m:
                class_name = m.group(1)
                extends = [b.strip() for b in m.group(2).split(",") if b.strip()]
                implements = []
            else:
                return None
        else:
            return None

        if not class_name:
            return None

        return InheritanceNode(
            class_name=class_name,
            extends=extends,
            implements=implements,
            filepath=filepath,
            depth_guess=1 if extends else 0,
        )

    def analyze_files(self, filepaths: list[str]) -> list[InheritanceNode]:
        """Analyze inheritance for a list of files."""
        self._nodes = []
        for fp in filepaths:
            node = self.analyze_file(fp)
            if node:
                self._nodes.append(node)
        return self._nodes

    def get_base_class_frequencies(self) -> dict[str, int]:
        """Return how many times each base class is extended.

        Returns dict of {base_class_name: extension_count}.
        """
        counts = Counter()
        for node in self._nodes:
            for ext in node.extends_list:
                if ext:
                    counts[ext] += 1
        return dict(counts.most_common())

    def get_inheritance_tree(self) -> dict[str, list[str]]:
        """Build parent → children map.

        Returns dict of {base_class: [child_class, ...]}.
        """
        tree: dict[str, list[str]] = {}
        for node in self._nodes:
            for ext in node.extends_list:
                if ext:
                    tree.setdefault(ext, []).append(node.class_name)
        return tree

    def get_interface_implementations(self) -> dict[str, list[str]]:
        """Build interface → implementing_classes map.

        Returns dict of {interface_name: [class_name, ...]}.
        """
        impl_map: dict[str, list[str]] = {}
        for node in self._nodes:
            for impl in node.implements_list:
                if impl:
                    impl_map.setdefault(impl, []).append(node.class_name)
        return impl_map

    def compute_depths(self) -> None:
        """Compute approximate inheritance depth for each node.

        Depth 0 = no extends, depth N = extends a class of depth N-1.
        This is a heuristic — accurate only within the analyzed set.
        """
        # Build name → node map
        name_map = {n.class_name: n for n in self._nodes}
        # Build extends → children map
        parent_map: dict[str, str] = {}  # child → parent (first extends)
        for node in self._nodes:
            if node.extends_list:
                parent_map[node.class_name] = node.extends_list[0]

        def get_depth(name: str, visited: set | None = None) -> int:
            if visited is None:
                visited = set()
            if name in visited:
                return 0  # circular
            visited.add(name)
            parent = parent_map.get(name)
            if parent and parent in name_map:
                return 1 + get_depth(parent, visited.copy())
            return 0 if not parent else 1  # parent exists but not in our set

        for node in self._nodes:
            node.depth_guess = get_depth(node.class_name)
