"""UnifiedAST — lightweight regex-based parser for Java and Python.

Provides a minimal abstraction over source code structure without requiring
tree-sitter. For v0.4.0, uses regex fallback parsing. Designed so tree-sitter
can be dropped in later without changing the API.

UnifiedAST node types:
  - "class"    → name, bases, methods, fields, annotations
  - "method"   → name, return_type, params, annotations, body
  - "field"    → name, type, annotations
  - "import"   → module, names
  - "annotation" → name, args (key=value pairs)
"""

import re
from pathlib import Path
from typing import Any, Optional

# ── Compiled regex ─────────────────────────────────────────────

_JAVA_CLASS_RE = re.compile(
    r'(?:public\s+|protected\s+|private\s+)?(?:abstract\s+|static\s+)?'
    r'(?:class|interface|enum)\s+(\w+)'
    r'(?:\s+extends\s+([\w.<>]+))?'
    r'(?:\s+implements\s+([\w.<>,\s]+))?',
    re.MULTILINE,
)

_JAVA_METHOD_RE = re.compile(
    r'((?:@\w+(?:\([^)]*\))?\s*)+)?'           # annotations group 1
    r'(public\s+|protected\s+|private\s+)?'     # access modifier
    r'(static\s+)?'                              # static
    r'(?:abstract\s+)?'
    r'(?:<[^>]+>\s+)?'                           # generics
    r'([\w<>\[\],\s]+)\s+'                       # return type group 3 (real)
    r'(\w+)\s*'                                  # method name group 4 (real)
    r'\(([^)]*)\)',                              # params group 5 (real)
    re.MULTILINE,
)

_JAVA_FIELD_RE = re.compile(
    r'((?:@\w+(?:\([^)]*\))?\s*)+)?'            # annotations
    r'(public\s+|protected\s+|private\s+)?'     # access
    r'(static\s+|final\s+)*'                    # modifiers
    r'([\w<>\[\],\s]+)\s+'                       # type
    r'(\w+)\s*[;=]',                             # name
    re.MULTILINE,
)

_JAVA_IMPORT_RE = re.compile(
    r'import\s+(static\s+)?([\w.*]+)\s*;',
    re.MULTILINE,
)

_PY_CLASS_RE = re.compile(
    r'class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:',
    re.MULTILINE,
)

_PY_METHOD_RE = re.compile(
    r'^\s*def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^:]+))?\s*:',
    re.MULTILINE,
)

_PY_IMPORT_RE = re.compile(
    r'(?:from\s+([\w.]+)\s+import\s+([\w,\s*()]+)|import\s+([\w.]+(?:\s+as\s+\w+)?))',
    re.MULTILINE,
)

_PY_DECORATOR_RE = re.compile(r'@(\w+(?:\.\w+)*(?:\([^)]*\))?)')


# ═══════════════════════════════════════════════════════════════
# AST Node
# ═══════════════════════════════════════════════════════════════


class ASTNode:
    """A lightweight AST node with named attributes (behaves like a dict)."""

    __slots__ = ("type", "name", "attrs")

    def __init__(self, node_type: str, name: str = "", **attrs):
        self.type = node_type
        self.name = name
        self.attrs = attrs

    def __getattr__(self, key: str) -> Any:
        if key in ("type", "name", "attrs"):
            return object.__getattribute__(self, key)
        try:
            return self.attrs[key]
        except KeyError:
            raise AttributeError(f"No attribute '{key}' on ASTNode") from None

    def __getitem__(self, key: str) -> Any:
        if key == "type":
            return self.type
        if key == "name":
            return self.name
        return self.attrs[key]

    def get(self, key: str, default=None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def to_dict(self) -> dict:
        return {"type": self.type, "name": self.name, **self.attrs}

    def __repr__(self):
        return f"ASTNode({self.type}, {self.name!r}, {self.attrs!r})"


# ═══════════════════════════════════════════════════════════════
# UnifiedAST
# ═══════════════════════════════════════════════════════════════


class UnifiedAST:
    """Minimal AST wrapper: provides class/method/field/annotation node access.

    Usage:
        ast = parse_file("MyPage.java")
        for cls in ast.classes:
            print(cls.name, cls.bases)
            for method in cls.methods:
                print("  ", method.name, method.params)
    """

    def __init__(self, filepath: str = "", language: str = "unknown"):
        self.filepath = filepath
        self.language = language
        self.classes: list[ASTNode] = []
        self.imports: list[ASTNode] = []
        self.annotations: list[ASTNode] = []  # file-level annotations

    def to_dict(self) -> dict:
        return {
            "filepath": self.filepath,
            "language": self.language,
            "classes": [c.to_dict() for c in self.classes],
            "imports": [i.to_dict() for i in self.imports],
            "annotations": [a.to_dict() for a in self.annotations],
        }

    def find_class(self, name: str) -> Optional[ASTNode]:
        """Find a class by name (exact match)."""
        for cls in self.classes:
            if cls.name == name:
                return cls
        return None

    def get_class_names(self) -> list[str]:
        """Return all class names in this file."""
        return [c.name for c in self.classes]

    def get_all_methods(self) -> list[ASTNode]:
        """Flatten all methods from all classes."""
        methods = []
        for cls in self.classes:
            for m in cls.attrs.get("methods", []):
                methods.append(m)
        return methods

    def get_all_annotations(self) -> list[ASTNode]:
        """Return all annotations (class-level + method-level + field-level)."""
        result = list(self.annotations)
        for cls in self.classes:
            for ann in cls.attrs.get("annotations", []):
                result.append(ann)
            for m in cls.attrs.get("methods", []):
                for ann in m.attrs.get("annotations", []):
                    result.append(ann)
            for f in cls.attrs.get("fields", []):
                for ann in f.attrs.get("annotations", []):
                    result.append(ann)
        return result

    def __repr__(self):
        return (f"UnifiedAST({self.filepath!r}, {self.language}, "
                f"{len(self.classes)} classes, {len(self.imports)} imports)")


# ═══════════════════════════════════════════════════════════════
# Parser entry point
# ═══════════════════════════════════════════════════════════════


def parse_file(filepath: str) -> UnifiedAST:
    """Parse a source file into a UnifiedAST.

    Auto-detects language from file extension. Returns an empty AST on failure.
    """
    path = Path(filepath)
    if not path.exists():
        return UnifiedAST(filepath, "unknown")

    try:
        content = path.read_text("utf-8", errors="replace")
    except Exception:
        return UnifiedAST(filepath, "unknown")

    if path.suffix == ".java":
        return _parse_java(filepath, content)
    elif path.suffix == ".py":
        return _parse_python(filepath, content)
    else:
        return UnifiedAST(filepath, "unknown")


# ═══════════════════════════════════════════════════════════════
# Java parser (regex fallback)
# ═══════════════════════════════════════════════════════════════


def _parse_java(filepath: str, content: str) -> UnifiedAST:
    ast = UnifiedAST(filepath, "java")

    # ── Imports ──
    for m in _JAVA_IMPORT_RE.finditer(content):
        is_static = bool(m.group(1))
        module = m.group(2)
        ast.imports.append(ASTNode(
            "import", module,
            static=is_static,
        ))

    # ── Classes ──
    for m in _JAVA_CLASS_RE.finditer(content):
        class_name = m.group(1)
        extends = m.group(2) or ""
        implements_raw = m.group(3) or ""

        # Find the class body (naive brace matching — good enough for profiling)
        start = m.end()
        body = _extract_brace_block(content, start)

        # Parse annotations on the class (lines before the class declaration)
        class_annotations = _extract_java_annotations_before(content, m.start())

        # Parse methods
        methods = _parse_java_methods(body)
        # Parse fields
        fields = _parse_java_fields(body)

        ast.classes.append(ASTNode(
            "class", class_name,
            extends=extends,
            implements=[i.strip() for i in implements_raw.split(",") if i.strip()],
            annotations=class_annotations,
            methods=methods,
            fields=fields,
        ))

    return ast


def _extract_java_annotations_before(content: str, class_start: int) -> list[ASTNode]:
    """Extract @Annotation lines before a given position in source."""
    # Look at the ~500 chars before class_start for annotations
    region_start = max(0, class_start - 500)
    region = content[region_start:class_start]
    annotations = []
    for m in re.finditer(r'@(\w+)(?:\(([^)]*)\))?', region):
        name = m.group(1)
        args_raw = m.group(2) or ""
        args = _parse_annotation_args(args_raw)
        annotations.append(ASTNode("annotation", name, args=args))
    return annotations


def _parse_annotation_args(raw: str) -> dict[str, str]:
    """Parse key=value pairs from annotation arguments."""
    if not raw.strip():
        return {}
    args = {}
    for m in re.finditer(r'(\w+)\s*=\s*("[^"]*"|\'[^\']*\'|[^,]+)', raw):
        args[m.group(1)] = m.group(2).strip('"\'')
    return args


def _parse_java_methods(body: str) -> list[ASTNode]:
    """Extract method declarations from a Java class body."""
    methods = []
    for m in _JAVA_METHOD_RE.finditer(body):
        # Groups: 1=annotations, 2=access, 3=static, 4=return_type, 5=name, 6=params
        annotations_raw = m.group(1) or ""
        return_type = m.group(4) if m.lastindex and m.lastindex >= 4 else "void"
        method_name = m.group(5) if m.lastindex and m.lastindex >= 5 else m.group(4)
        params_raw = m.group(6) if m.lastindex and m.lastindex >= 6 else ""

        _ = m.group(2)  # access modifier — unused for now
        _ = m.group(3)  # static — unused for now

        if not method_name or method_name in ("if", "for", "while", "switch", "return", "new"):
            continue

        # Parse annotations
        method_annotations = []
        for am in re.finditer(r'@(\w+)(?:\(([^)]*)\))?', annotations_raw):
            ann_args = _parse_annotation_args(am.group(2) or "")
            method_annotations.append(ASTNode("annotation", am.group(1), args=ann_args))

        # Parse params into a list of (type, name) tuples
        params = []
        for param in params_raw.split(","):
            param = param.strip()
            if not param:
                continue
            parts = param.rsplit(None, 1)
            if len(parts) == 2:
                params.append({"type": parts[0].strip(), "name": parts[1].strip()})
            else:
                params.append({"type": "", "name": parts[0].strip()})

        methods.append(ASTNode(
            "method", method_name,
            return_type=return_type.strip(),
            params=params,
            annotations=method_annotations,
        ))

    return methods


def _parse_java_fields(body: str) -> list[ASTNode]:
    """Extract field declarations from a Java class body."""
    fields = []
    for m in _JAVA_FIELD_RE.finditer(body):
        annotations_raw = m.group(1) or ""
        field_type = m.group(4)
        field_name = m.group(5)

        field_annotations = []
        for am in re.finditer(r'@(\w+)(?:\(([^)]*)\))?', annotations_raw):
            ann_args = _parse_annotation_args(am.group(2) or "")
            field_annotations.append(ASTNode("annotation", am.group(1), args=ann_args))

        fields.append(ASTNode(
            "field", field_name,
            field_type=field_type.strip(),
            annotations=field_annotations,
        ))

    return fields


def _extract_brace_block(content: str, start: int) -> str:
    """Naively extract the text between matching braces starting from start.

    Falls back to returning the rest of the content if brace matching is ambiguous.
    """
    if start >= len(content):
        return ""
    # Find the opening brace
    brace_pos = content.find("{", start)
    if brace_pos == -1:
        return ""
    depth = 0
    i = brace_pos
    while i < len(content):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return content[brace_pos + 1:i]
        i += 1
    # Fallback: unclosed brace
    return content[brace_pos + 1:]


# ═══════════════════════════════════════════════════════════════
# Python parser (regex fallback)
# ═══════════════════════════════════════════════════════════════


def _parse_python(filepath: str, content: str) -> UnifiedAST:
    ast = UnifiedAST(filepath, "python")

    # ── Imports ──
    for m in _PY_IMPORT_RE.finditer(content):
        if m.group(1):  # from X import Y
            module = m.group(1)
            names = [n.strip() for n in m.group(2).split(",")]
        else:  # import X
            module = m.group(3).split(" as ")[0].strip()
            names = [module]
        ast.imports.append(ASTNode("import", module, names=names))

    # ── Classes ──
    for m in _PY_CLASS_RE.finditer(content):
        class_name = m.group(1)
        bases_raw = m.group(2) or ""
        bases = [b.strip() for b in bases_raw.split(",") if b.strip()]

        # Find class body (indentation-based)
        class_start = m.end()
        body = _extract_python_block(content, class_start)

        # Extract decorators before class
        class_annotations = _extract_python_decorators(content, m.start())

        # Parse methods
        methods = _parse_python_methods(body)

        ast.classes.append(ASTNode(
            "class", class_name,
            bases=bases,
            annotations=class_annotations,
            methods=methods,
        ))

    return ast


def _extract_python_decorators(content: str, def_pos: int) -> list[ASTNode]:
    """Extract decorator lines before a class/function definition."""
    region_start = max(0, def_pos - 500)
    region = content[region_start:def_pos]
    annotations = []
    for m in _PY_DECORATOR_RE.finditer(region):
        annotations.append(ASTNode("annotation", m.group(1)))
    return annotations


def _extract_python_block(content: str, start: int) -> str:
    """Extract an indented block starting from start position."""
    lines = content[start:].split("\n")
    if not lines:
        return ""
    # Find the first non-empty line to determine base indent
    first_line = ""
    first_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            first_line = line
            first_idx = i
            break
    if not first_line:
        return ""

    # Get the indentation of the first meaningful line
    indent = len(first_line) - len(first_line.lstrip())
    block_lines = []
    for i in range(first_idx, len(lines)):
        line = lines[i]
        if line.strip() == "":
            block_lines.append(line)
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent < indent:
            break
        block_lines.append(line)
    return "\n".join(block_lines)


def _parse_python_methods(body: str) -> list[ASTNode]:
    """Extract method definitions from a Python class body."""
    methods = []
    for m in _PY_METHOD_RE.finditer(body):
        method_name = m.group(1)
        params_raw = m.group(2)
        return_type = m.group(3) or ""

        # Skip dunder methods unless they're test-relevant
        if method_name.startswith("__") and method_name.endswith("__"):
            if method_name not in ("__init__", "__call__", "__enter__", "__exit__"):
                continue

        # Find decorators before this method
        method_start_in_body = m.start()
        decorators = _extract_python_decorators(body, method_start_in_body)

        # Parse params
        params = []
        for param in params_raw.split(","):
            param = param.strip()
            if not param or param == "self" or param == "cls":
                continue
            if ":" in param:
                pname, _, ptype = param.partition(":")
                params.append({"name": pname.strip(), "type": ptype.strip()})
            elif "=" in param:
                pname, _, _ = param.partition("=")
                params.append({"name": pname.strip(), "type": ""})
            else:
                params.append({"name": param.strip(), "type": ""})

        methods.append(ASTNode(
            "method", method_name,
            return_type=return_type.strip(),
            params=params,
            annotations=decorators,
        ))

    return methods
