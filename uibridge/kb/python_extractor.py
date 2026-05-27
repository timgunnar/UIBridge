"""Python extractor — legacy Python extractors and AST helpers."""

import ast
import warnings
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

from .extractor._base import safe_relative_to, _FEATURE_POINT_RE
from .item import KBItem, Confidence, KnowledgeSource


class PythonExtractor:
    """Legacy Python extractors and Python AST helpers."""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root)

    # ── Legacy Static Analysis (confidence 0.6-0.8) ──

    def _legacy_extract_from_component_aw(self, filepath: str) -> list[KBItem]:
        """Parse a component AW .py file → KB items for component type, XPath, methods."""
        warnings.warn(
            "_legacy_extract_from_component_aw is deprecated, use extract_aggregated() instead",
            DeprecationWarning, stacklevel=2)
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
                    "source_file": safe_relative_to(path, self.project_root),
                },
                confidence=Confidence(score=0.7, source=KnowledgeSource.STATIC_ANALYSIS),
                description=f"Component AW: {class_name} with {len(methods)} methods",
                tags=[class_name, "component"],
                source_file=safe_relative_to(path, self.project_root),
            ))

        return items

    def _legacy_extract_from_page_file(self, filepath: str) -> list[KBItem]:
        """Parse a page definition file → KB items for page structure."""
        warnings.warn(
            "_legacy_extract_from_page_file is deprecated, use extract_aggregated() instead",
            DeprecationWarning, stacklevel=2)
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
                    "source_file": safe_relative_to(path, self.project_root),
                },
                confidence=Confidence(score=0.7, source=KnowledgeSource.STATIC_ANALYSIS),
                description=f"Page: {class_name} with {len(feature_points)} feature points",
                tags=[class_name, "page"],
                source_file=safe_relative_to(path, self.project_root),
            ))

        return items

    def _legacy_extract_from_test_script(self, filepath: str) -> list[KBItem]:
        """Parse a test script → KB items for import style, fixture, assertion patterns."""
        warnings.warn(
            "_legacy_extract_from_test_script is deprecated, use extract_aggregated() instead",
            DeprecationWarning, stacklevel=2)
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
                    "source_file": safe_relative_to(path, self.project_root),
                },
                confidence=Confidence(score=0.6, source=KnowledgeSource.STATIC_ANALYSIS),
                description=f"Style conventions from {class_name}: {len(imports)} imports, "
                            f"{assertion_style} assertions",
                tags=[class_name, "style", "convention"],
                source_file=safe_relative_to(path, self.project_root),
            ))

        return items

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
                        match = _FEATURE_POINT_RE.search(val)
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
