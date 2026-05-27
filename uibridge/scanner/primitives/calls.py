"""CallAnalyzer — extract method invocations from source files.

Tracks which methods are called within each method body, building
a call graph for understanding code flow and component interaction.
"""

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from ..parser import UnifiedAST, parse_file

# ── Regex for method call extraction ──

_JAVA_CALL_RE = re.compile(r'(\w+)\.(\w+)\s*\(')          # obj.method(
_JAVA_STATIC_CALL_RE = re.compile(r'(\w+)\.(\w+)\s*\(')   # Class.method(
_JAVA_SELF_CALL_RE = re.compile(r'(?:this\.)?(\w+)\s*\(') # method( or this.method(
_PY_CALL_RE = re.compile(r'(?:self\.)?(\w+)\s*\(', re.MULTILINE)
_PY_METHOD_CALL_RE = re.compile(r'(\w+)\.(\w+)\s*\(', re.MULTILINE)


class MethodCall:
    """A single method invocation."""

    __slots__ = ("caller_class", "caller_method", "target_object",
                 "target_method", "filepath", "line")

    def __init__(self, caller_class: str = "", caller_method: str = "",
                 target_object: str = "", target_method: str = "",
                 filepath: str = "", line: int = 0):
        self.caller_class = caller_class
        self.caller_method = caller_method
        self.target_object = target_object
        self.target_method = target_method
        self.filepath = filepath
        self.line = line

    def to_dict(self) -> dict:
        return {
            "caller_class": self.caller_class,
            "caller_method": self.caller_method,
            "target_object": self.target_object,
            "target_method": self.target_method,
            "filepath": self.filepath,
            "line": self.line,
        }

    def __repr__(self):
        return (f"{self.caller_class}.{self.caller_method}()"
                f" → {self.target_object}.{self.target_method}()")


class CallAnalyzer:
    """Analyzes method calls within source files."""

    def __init__(self, use_ast: bool = True):
        self.use_ast = use_ast
        self._calls: list[MethodCall] = []

    def analyze_file(self, filepath: str) -> list[MethodCall]:
        """Extract all method calls from a single file.

        Results are also appended to self._calls for aggregate queries.
        """
        path = Path(filepath)
        if not path.exists():
            return []

        try:
            content = path.read_text("utf-8", errors="replace")
        except Exception:
            return []

        if self.use_ast:
            calls = self._analyze_with_ast(filepath, content)
        else:
            calls = self._analyze_with_regex(filepath, content, path.suffix)

        self._calls.extend(calls)
        return calls

    def _analyze_with_ast(self, filepath: str, content: str) -> list[MethodCall]:
        """Use UnifiedAST to get structured methods, then regex inside each body."""
        ast = parse_file(filepath)
        if not ast.classes:
            return self._analyze_with_regex(filepath, content, Path(filepath).suffix)

        calls = []
        for cls in ast.classes:
            for method in cls.attrs.get("methods", []):
                # For AST mode, we still need to find the method body to extract calls.
                # Fall back to regex for the call extraction within method bodies.
                pass

        # Since UnifiedAST doesn't store method bodies, fall back to regex
        return self._analyze_with_regex(filepath, content, Path(filepath).suffix)

    def _analyze_with_regex(self, filepath: str, content: str,
                             suffix: str) -> list[MethodCall]:
        """Regex-based call extraction from source text."""
        calls = []
        lines = content.split("\n")

        # Find class name
        if suffix == ".java":
            class_m = re.search(r'class\s+(\w+)', content)
        else:
            class_m = re.search(r'class\s+(\w+)', content)
        class_name = class_m.group(1) if class_m else Path(filepath).stem

        # Track current method
        current_method = "<module>"

        for line_num, line in enumerate(lines, 1):
            # Detect method declarations
            if suffix == ".java":
                method_m = re.search(
                    r'(?:public|protected|private|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\(', line)
            else:
                method_m = re.search(r'^\s*def\s+(\w+)\s*\(', line)
            if method_m:
                current_method = method_m.group(1)

            # Extract calls on the same line
            if suffix == ".java":
                for m in re.finditer(r'(\w+)\.(\w+)\s*\(', line):
                    obj, meth = m.group(1), m.group(2)
                    if obj not in ("System", "String", "Integer", "Boolean",
                                   "List", "Map", "Set", "Arrays", "Collections",
                                   "Objects", "Optional", "new", "return", "if",
                                   "for", "while", "switch", "throw", "assert"):
                        calls.append(MethodCall(
                            caller_class=class_name,
                            caller_method=current_method,
                            target_object=obj,
                            target_method=meth,
                            filepath=filepath,
                            line=line_num,
                        ))
                # Also self calls: this.method() or bare method()
                for m in re.finditer(r'(?:this\.)?(\w+)\s*\(', line):
                    meth = m.group(1)
                    if (re.match(r'^[a-z]', meth)  # starts lowercase = likely method
                            and meth not in ("if", "for", "while", "switch",
                                            "return", "new", "throw", "assert",
                                            "try", "catch", "finally",
                                            "synchronized")):
                        # Avoid duplicate from the obj.method pattern already matched
                        if not re.search(rf'\b\w+\.{meth}\s*\(', line):
                            calls.append(MethodCall(
                                caller_class=class_name,
                                caller_method=current_method,
                                target_object="this",
                                target_method=meth,
                                filepath=filepath,
                                line=line_num,
                            ))
            else:  # Python
                for m in re.finditer(r'(\w+)\.(\w+)\s*\(', line):
                    obj, meth = m.group(1), m.group(2)
                    calls.append(MethodCall(
                        caller_class=class_name,
                        caller_method=current_method,
                        target_object=obj,
                        target_method=meth,
                        filepath=filepath,
                        line=line_num,
                    ))
                for m in re.finditer(r'(?:self\.)?(\w+)\s*\(', line):
                    meth = m.group(1)
                    if (re.match(r'^[a-z_]', meth)
                            and meth not in ("print", "len", "range", "int", "str",
                                            "list", "dict", "set", "tuple", "bool",
                                            "float", "type", "isinstance", "hasattr",
                                            "getattr", "setattr", "super",
                                            "if", "for", "while", "with", "try",
                                            "except", "return", "yield", "raise",
                                            "assert", "import")):
                        if not re.search(rf'\b\w+\.{meth}\s*\(', line):
                            calls.append(MethodCall(
                                caller_class=class_name,
                                caller_method=current_method,
                                target_object="self",
                                target_method=meth,
                                filepath=filepath,
                                line=line_num,
                            ))

        return calls

    def analyze_files(self, filepaths: list[str]) -> list[MethodCall]:
        """Analyze calls across multiple files."""
        self._calls = []
        for fp in filepaths:
            self._calls.extend(self.analyze_file(fp))
        return self._calls

    def get_call_graph(self) -> dict[str, list[str]]:
        """Build a caller → callees map.

        Returns dict of {"ClassName.methodName": ["TargetClass.targetMethod", ...]}.
        """
        graph: dict[str, list[str]] = defaultdict(list)
        for call in self._calls:
            caller = f"{call.caller_class}.{call.caller_method}"
            target = f"{call.target_object}.{call.target_method}"
            graph[caller].append(target)
        return dict(graph)

    def get_most_called(self, top_n: int = 20) -> list[tuple[str, int]]:
        """Return the most frequently called (target_object, target_method) pairs."""
        counter = Counter()
        for call in self._calls:
            counter[(call.target_object, call.target_method)] += 1
        return counter.most_common(top_n)

    def get_call_frequency_by_object(self) -> dict[str, int]:
        """Count total calls per target object."""
        counter = Counter()
        for call in self._calls:
            counter[call.target_object] += 1
        return dict(counter.most_common())
