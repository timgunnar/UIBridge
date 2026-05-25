"""KBExtractor base — core initialization, public wrappers, and runtime extraction."""

import ast
import logging
import re
import warnings
from pathlib import Path
from typing import Optional

from ..item import KBItem, Confidence, KnowledgeSource

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---', re.DOTALL)
_FEATURE_POINT_RE = re.compile(r"@(data-module|data-test(?:id)?)\s*=\s*['\"]([^'\"]+)['\"]")


def safe_relative_to(path: Path, base: Path) -> str:
    """Return path relative to base, or absolute path string if not under base."""
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


class _ExtractorBase:
    """Core initialization, public wrappers, and runtime extraction for KBExtractor."""

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

    # ── Public wrappers (delegate to legacy for backward compat) ──

    def extract_from_component_aw(self, filepath: str) -> list[KBItem]:
        return self._legacy_extract_from_component_aw(filepath)

    def extract_from_page_file(self, filepath: str) -> list[KBItem]:
        return self._legacy_extract_from_page_file(filepath)

    def extract_from_test_script(self, filepath: str) -> list[KBItem]:
        return self._legacy_extract_from_test_script(filepath)

    def extract_from_java_file(self, filepath: str) -> list[KBItem]:
        return self._legacy_extract_from_java_file(filepath)

    def extract_from_java_test(self, filepath: str) -> list[KBItem]:
        return self._legacy_extract_from_java_test(filepath)

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
