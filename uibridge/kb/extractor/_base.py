"""KBExtractor base — shared utilities and constants."""

import re
from pathlib import Path

_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---', re.DOTALL)
_FEATURE_POINT_RE = re.compile(r"@(data-module|data-test(?:id)?)\s*=\s*['\"]([^'\"]+)['\"]")


def safe_relative_to(path: Path, base: Path) -> str:
    """Return path relative to base, or absolute path string if not under base."""
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)
