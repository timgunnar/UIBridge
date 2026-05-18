"""KBExtractor — extract knowledge from static analysis, runtime analysis, and documents"""

import ast
import logging
import re
from pathlib import Path
from typing import Optional

from .kb_item import KBItem, Confidence, KnowledgeSource

logger = logging.getLogger(__name__)


class KBExtractor:
    """Extracts framework knowledge from source code, runtime traces, and NL documents."""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self._java_available = None  # 延迟检测

    def _check_javalang(self) -> bool:
        """检测 javalang 是否可用，缓存结果。"""
        if self._java_available is None:
            try:
                import javalang  # noqa: F401
                self._java_available = True
            except ImportError:
                self._java_available = False
        return self._java_available

    # ── Static Analysis (confidence 0.6-0.8) ──────────

    def extract_from_component_aw(self, filepath: str) -> list[KBItem]:
        """Parse a component AW .py file → KB items for component type, XPath, methods."""
        path = Path(filepath)
        if not path.exists():
            return []

        tree = self._parse(path)
        if not tree:
            return []

        items = []
        class_name = self._find_class_name(tree)
        xpath_patterns = self._extract_xpath_patterns(tree)
        methods = self._extract_methods(tree)

        if class_name:
            items.append(KBItem(
                id=f"comp_{class_name.lower()}",
                category="components",
                key=f"component.{class_name}",
                value={
                    "class_name": class_name,
                    "xpath_patterns": xpath_patterns,
                    "methods": methods,
                    "source_file": str(path.relative_to(self.project_root)),
                },
                confidence=Confidence(score=0.7, source=KnowledgeSource.STATIC_ANALYSIS),
                description=f"Component AW: {class_name} with {len(methods)} methods",
                tags=[class_name, "component"],
                source_file=str(path.relative_to(self.project_root)),
            ))

        return items

    def extract_from_page_file(self, filepath: str) -> list[KBItem]:
        """Parse a page definition file → KB items for page structure."""
        path = Path(filepath)
        if not path.exists():
            return []

        tree = self._parse(path)
        if not tree:
            return []

        items = []
        class_name = self._find_class_name(tree)
        feature_points = self._extract_feature_points(tree)

        if class_name:
            items.append(KBItem(
                id=f"page_{class_name.lower()}",
                category="pages",
                key=f"page.{class_name}",
                value={
                    "class_name": class_name,
                    "feature_points": feature_points,
                    "source_file": str(path.relative_to(self.project_root)),
                },
                confidence=Confidence(score=0.7, source=KnowledgeSource.STATIC_ANALYSIS),
                description=f"Page: {class_name} with {len(feature_points)} feature points",
                tags=[class_name, "page"],
                source_file=str(path.relative_to(self.project_root)),
            ))

        return items

    def extract_from_test_script(self, filepath: str) -> list[KBItem]:
        """Parse a test script → KB items for import style, fixture, assertion patterns."""
        path = Path(filepath)
        if not path.exists():
            return []

        tree = self._parse(path)
        if not tree:
            return []

        items = []
        imports = self._extract_imports(tree)
        fixtures = self._extract_fixture_names(tree)
        assertion_style = self._detect_assertion_style(tree)
        class_name = self._find_class_name(tree)

        if class_name:
            items.append(KBItem(
                id=f"style_{class_name.lower()}",
                category="conventions",
                key=f"style.{class_name}",
                value={
                    "imports": imports,
                    "fixtures": fixtures,
                    "assertion_style": assertion_style,
                    "source_file": str(path.relative_to(self.project_root)),
                },
                confidence=Confidence(score=0.6, source=KnowledgeSource.STATIC_ANALYSIS),
                description=f"Style conventions from {class_name}: {len(imports)} imports, "
                            f"{assertion_style} assertions",
                tags=[class_name, "style", "convention"],
                source_file=str(path.relative_to(self.project_root)),
            ))

        return items

    # ── Runtime Analysis (confidence 0.8-0.95) ────────

    def extract_from_runtime_trace(self, component_type: str,
                                   method_traces: list[dict],
                                   page_url: str) -> list[KBItem]:
        """From runtime execution traces → validated XPath, locator strategies."""
        items = []

        for trace in method_traces:
            method_name = trace.get("method", "unknown")
            executed_ops = trace.get("executed_ops", [])
            xpaths = [op.get("locator", "") for op in executed_ops
                      if op.get("locator", "").startswith("xpath=")]

            items.append(KBItem(
                id=f"rt_{component_type}_{method_name}",
                category="components",
                key=f"runtime.{component_type}.{method_name}",
                value={
                    "component_type": component_type,
                    "method": method_name,
                    "validated_xpaths": xpaths,
                    "page_url": page_url,
                    "executed_ops": executed_ops,
                },
                confidence=Confidence(score=0.85, source=KnowledgeSource.RUNTIME_ANALYSIS),
                description=f"Runtime trace: {component_type}.{method_name}() → "
                            f"{len(xpaths)} XPath(s) validated",
                tags=[component_type, method_name, "runtime"],
            ))

        return items

    # ── Java Static Analysis (confidence 0.6-0.8) ──────

    def extract_from_java_file(self, filepath: str) -> list[KBItem]:
        """Parse a .java file → KB items for class, methods, annotations."""
        path = Path(filepath)
        if not path.exists():
            return []

        tree = self._parse_java(path)
        if not tree:
            return []

        items = []
        class_name = self._find_java_class_name(tree)
        methods = self._extract_java_methods(tree)
        annotations = self._extract_java_annotations(tree)
        package = self._extract_java_package(tree)

        if class_name:
            item_type = "components" if "component" in str(path).lower() or "element" in str(path).lower() else "pages"
            full_class = f"{package}.{class_name}" if package else class_name
            items.append(KBItem(
                id=f"java_{class_name.lower()}",
                category=item_type,
                key=f"java.{full_class}",
                value={
                    "class_name": class_name,
                    "package": package,
                    "methods": methods,
                    "annotations": annotations,
                    "source_file": str(path.relative_to(self.project_root)),
                },
                confidence=Confidence(score=0.7, source=KnowledgeSource.STATIC_ANALYSIS),
                description=f"Java class: {full_class} with {len(methods)} methods",
                tags=[class_name, "java", item_type.rstrip('s')],
                source_file=str(path.relative_to(self.project_root)),
            ))

        return items

    def extract_from_java_test(self, filepath: str) -> list[KBItem]:
        """Parse a Java test file → KB items for style conventions."""
        path = Path(filepath)
        if not path.exists():
            return []

        tree = self._parse_java(path)
        if not tree:
            return []

        items = []
        class_name = self._find_java_class_name(tree)
        package = self._extract_java_package(tree)
        imports = self._extract_java_imports(tree)
        annotations = self._extract_java_annotations(tree)

        if class_name:
            items.append(KBItem(
                id=f"java_style_{class_name.lower()}",
                category="conventions",
                key=f"java.style.{class_name}",
                value={
                    "class_name": class_name,
                    "package": package,
                    "imports": imports,
                    "annotations": annotations,
                    "source_file": str(path.relative_to(self.project_root)),
                },
                confidence=Confidence(score=0.6, source=KnowledgeSource.STATIC_ANALYSIS),
                description=f"Java test style from {class_name}",
                tags=[class_name, "java", "test", "style"],
                source_file=str(path.relative_to(self.project_root)),
            ))

        return items

    # ── Java AST Helpers ──────────────────────────────

    def _parse_java(self, path: Path):
        """Parse Java file using javalang. Returns None if javalang unavailable or parse fails."""
        if not self._check_javalang():
            return None
        try:
            import javalang
            return javalang.parse.parse(path.read_text(encoding="utf-8"))
        except ImportError:
            self._java_available = False
            return None
        except Exception:
            return None

    def _find_java_class_name(self, tree) -> Optional[str]:
        if tree is None:
            return None
        try:
            for path_node, node in tree:
                if hasattr(node, 'name') and type(node).__name__ == 'ClassDeclaration':
                    return node.name
        except Exception as e:
            logger.debug("Error finding Java class name: %s", e)
        return None

    def _extract_java_package(self, tree) -> str:
        if tree is None:
            return ""
        try:
            if hasattr(tree, 'package') and tree.package:
                return tree.package.name
        except Exception as e:
            logger.debug("Error extracting Java package: %s", e)
        return ""

    def _extract_java_methods(self, tree) -> list[dict]:
        methods = []
        try:
            for path_node, node in tree:
                if type(node).__name__ == 'MethodDeclaration':
                    params = []
                    for p in node.parameters:
                        params.append({"name": p.name, "type": p.type.name if hasattr(p.type, 'name') else str(p.type)})
                    returns = node.return_type.name if node.return_type and hasattr(node.return_type, 'name') else "void"
                    methods.append({
                        "name": node.name,
                        "params": params,
                        "returns": returns,
                        "modifiers": list(node.modifiers) if node.modifiers else [],
                    })
        except Exception as e:
            logger.debug("Error extracting Java methods: %s", e)
        return methods

    def _extract_java_annotations(self, tree) -> list[str]:
        annotations = []
        try:
            for path_node, node in tree:
                if type(node).__name__ == 'Annotation':
                    annotations.append(node.name)
        except Exception as e:
            logger.debug("Error extracting Java annotations: %s", e)
        return list(set(annotations))

    def _extract_java_imports(self, tree) -> list[str]:
        imports = []
        try:
            if hasattr(tree, 'imports') and tree.imports:
                for imp in tree.imports:
                    imports.append(imp.path)
        except Exception as e:
            logger.debug("Error extracting Java imports: %s", e)
        return imports

    # ── Document Ingestion (confidence 0.9-0.99) ──────

    def extract_from_design_doc(self, text: str, source_name: str = "design_doc") -> list[KBItem]:
        """Parse NL design document → KB items for conventions and patterns."""
        items = []

        # Extract naming conventions
        naming_patterns = re.findall(
            r'(?:命名|naming).*?[:：]\s*([^\n]+)',
            text, re.IGNORECASE
        )
        if naming_patterns:
            items.append(KBItem(
                id=f"doc_naming_{source_name}",
                category="conventions",
                key="convention.naming",
                value={"naming_rules": naming_patterns},
                confidence=Confidence(score=0.9, source=KnowledgeSource.HUMAN_INJECTION),
                description=f"Naming conventions from {source_name}",
                tags=["naming", "convention", "human"],
                source_file=source_name,
            ))

        # Extract XPath conventions
        xpath_patterns = re.findall(
            r'(?:XPath|xpath|定位).*?[:：]\s*([^\n]+)',
            text, re.IGNORECASE
        )
        if xpath_patterns:
            items.append(KBItem(
                id=f"doc_xpath_{source_name}",
                category="conventions",
                key="convention.xpath",
                value={"xpath_conventions": xpath_patterns},
                confidence=Confidence(score=0.9, source=KnowledgeSource.HUMAN_INJECTION),
                description=f"XPath conventions from {source_name}",
                tags=["xpath", "convention", "human"],
                source_file=source_name,
            ))

        # Extract component type mappings
        comp_mappings = re.findall(
            r'(\w+)\s*(?:→|->|→|映射到|映射为)\s*(\w+AW|Target|\w+Helper)',
            text
        )
        if comp_mappings:
            items.append(KBItem(
                id=f"doc_mappings_{source_name}",
                category="components",
                key="component.type_mappings",
                value={"mappings": [{"role": m[0], "type": m[1]} for m in comp_mappings]},
                confidence=Confidence(score=0.85, source=KnowledgeSource.HUMAN_INJECTION),
                description=f"Component type mappings from {source_name}",
                tags=["mapping", "component", "human"],
                source_file=source_name,
            ))

        return items

    def inject_convention(self, key: str, value: dict, description: str,
                          source: str = "human") -> KBItem:
        """Direct human injection of a convention."""
        return KBItem(
            id=f"human_{key.replace('.', '_')}",
            category="conventions",
            key=key,
            value=value,
            confidence=Confidence(score=0.95, source=KnowledgeSource.HUMAN_INJECTION),
            description=description,
            tags=["human", "convention"],
            source_file=source,
        )

    # ── AST Helpers ───────────────────────────────────

    def _parse(self, path: Path):
        try:
            return ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            return None

    def _find_class_name(self, tree: ast.Module) -> Optional[str]:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                return node.name
        return None

    def _extract_xpath_patterns(self, tree: ast.Module) -> list[str]:
        patterns = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets if isinstance(node.targets, list) else [node.targets]:
                    if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                        val = str(node.value.value)
                        if any(k in val for k in ("xpath", "//", "@", "data-", "locator")):
                            patterns.append(f"{target.id} = {val}")
        return patterns

    def _extract_methods(self, tree: ast.Module) -> list[dict]:
        methods = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args]
                returns = None
                if node.returns and isinstance(node.returns, ast.Name):
                    returns = node.returns.id
                methods.append({
                    "name": node.name,
                    "params": args[1:],  # skip self
                    "returns": returns,
                })
        return methods

    def _extract_feature_points(self, tree: ast.Module) -> list[dict]:
        """Extract XPath feature points from page classes (e.g., data-module values)."""
        points = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets if isinstance(node.targets, list) else [node.targets]:
                    if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                        val = str(node.value.value)
                        match = re.search(r"@(data-module|data-test(?:id)?)\s*=\s*['\"]([^'\"]+)['\"]", val)
                        if match:
                            points.append({
                                "variable": target.id,
                                "attr_type": match.group(1),
                                "value": match.group(2),
                            })
        return points

    def _extract_imports(self, tree: ast.Module) -> list[str]:
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                names = ", ".join(a.name for a in node.names)
                imports.append(f"from {node.module or ''} import {names}")
        return imports

    def _extract_fixture_names(self, tree: ast.Module) -> list[str]:
        fixtures = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and hasattr(dec.func, "attr"):
                        if dec.func.attr == "fixture":
                            fixtures.append(node.name)
                    elif isinstance(dec, ast.Attribute) and dec.attr == "fixture":
                        fixtures.append(node.name)
        return fixtures

    def _detect_assertion_style(self, tree: ast.Module) -> str:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                return "pytest_assert"
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr.startswith("assert"):
                        return "self.assertXxx"
        return "unknown"
