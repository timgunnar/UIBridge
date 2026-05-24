"""Document ingestion mixin — NL design document parsing and convention injection."""

import re
import logging

logger = logging.getLogger(__name__)

from ..item import KBItem, Confidence, KnowledgeSource
from ._base import _FRONTMATTER_RE


class _DocumentsMixin:
    """Document ingestion: design doc parsing and human convention injection."""

    # ── Document Ingestion (confidence 0.9-0.99) ──────

    def extract_from_design_doc(self, text: str, source_name: str = "design_doc") -> list[KBItem]:
        """Parse NL design document → KB items for conventions and patterns.

        Supports:
        - YAML frontmatter (--- ... ---) for structured extraction
        - Markdown-style key-value pairs
        - Arrow/mapping notation for component type mappings
        """
        items = []

        # Phase 1: YAML frontmatter
        items += self._extract_frontmatter(text, source_name)

        # Phase 2: regex-based extraction from markdown/plain text
        items += self._extract_naming_rules(text, source_name)
        items += self._extract_xpath_rules(text, source_name)
        items += self._extract_component_mappings(text, source_name)

        return items

    def _extract_frontmatter(self, text: str, source_name: str) -> list[KBItem]:
        """Extract KB items from YAML frontmatter (--- delimited block)."""
        fm_match = _FRONTMATTER_RE.match(text)
        if not fm_match:
            return []
        try:
            import yaml
            data = yaml.safe_load(fm_match.group(1))
        except Exception:
            logger.warning("Failed to parse YAML frontmatter from design doc", exc_info=True)
            return []
        if not isinstance(data, dict):
            return []

        items = []
        if "naming" in data and isinstance(data["naming"], dict):
            rules = [f"{k}: {v}" for k, v in data["naming"].items()]
            items.append(KBItem(
                id=f"doc_fm_naming_{source_name}",
                category="conventions",
                key="convention.naming",
                value={"naming_rules": rules},
                confidence=Confidence(score=0.95, source=KnowledgeSource.HUMAN_INJECTION),
                description=f"Naming conventions from {source_name} (frontmatter)",
                tags=["naming", "convention", "human"],
                source_file=source_name,
            ))

        if "xpath" in data and isinstance(data["xpath"], dict):
            rules = [f"{k}: {v}" for k, v in data["xpath"].items()]
            items.append(KBItem(
                id=f"doc_fm_xpath_{source_name}",
                category="conventions",
                key="convention.xpath",
                value={"xpath_conventions": rules},
                confidence=Confidence(score=0.95, source=KnowledgeSource.HUMAN_INJECTION),
                description=f"XPath conventions from {source_name} (frontmatter)",
                tags=["xpath", "convention", "human"],
                source_file=source_name,
            ))

        if "components" in data and isinstance(data["components"], dict):
            mappings = [{"role": k, "type": v} for k, v in data["components"].items()]
            items.append(KBItem(
                id=f"doc_fm_mappings_{source_name}",
                category="components",
                key="component.type_mappings",
                value={"mappings": mappings},
                confidence=Confidence(score=0.95, source=KnowledgeSource.HUMAN_INJECTION),
                description=f"Component type mappings from {source_name} (frontmatter)",
                tags=["mapping", "component", "human"],
                source_file=source_name,
            ))

        return items

    def _extract_naming_rules(self, text: str, source_name: str) -> list[KBItem]:
        """Extract naming conventions with word-boundary-anchored keywords."""
        naming_patterns = re.findall(
            r'\b(?:命名规则|命名规范|命名约定|命名|naming\s+(?:convention|rule|pattern|style)|'
            r'naming)'
            r'.*?[:：]\s*([^\n]+)',
            text, re.IGNORECASE
        )
        if not naming_patterns:
            return []
        return [KBItem(
            id=f"doc_naming_{source_name}",
            category="conventions",
            key="convention.naming",
            value={"naming_rules": naming_patterns},
            confidence=Confidence(score=0.9, source=KnowledgeSource.HUMAN_INJECTION),
            description=f"Naming conventions from {source_name}",
            tags=["naming", "convention", "human"],
            source_file=source_name,
        )]

    def _extract_xpath_rules(self, text: str, source_name: str) -> list[KBItem]:
        """Extract XPath conventions with context-anchored keywords."""
        xpath_patterns = re.findall(
            r'\b(?:XPath|xpath|定位(?:器|方式|策略|规则|优[先级]))'
            r'.*?[:：]\s*([^\n]+)',
            text, re.IGNORECASE
        )
        if not xpath_patterns:
            return []
        return [KBItem(
            id=f"doc_xpath_{source_name}",
            category="conventions",
            key="convention.xpath",
            value={"xpath_conventions": xpath_patterns},
            confidence=Confidence(score=0.9, source=KnowledgeSource.HUMAN_INJECTION),
            description=f"XPath conventions from {source_name}",
            tags=["xpath", "convention", "human"],
            source_file=source_name,
        )]

    def _extract_component_mappings(self, text: str, source_name: str) -> list[KBItem]:
        """Extract component type mappings with broader suffix support."""
        comp_mappings = re.findall(
            r'([\w\s-]+?)\s*(?:→|->|=>|映射到|映射为|maps?\s+to)\s*(\w+)',
            text, re.IGNORECASE
        )
        if not comp_mappings:
            return []
        return [KBItem(
            id=f"doc_mappings_{source_name}",
            category="components",
            key="component.type_mappings",
            value={"mappings": [{"role": m[0].strip(), "type": m[1]} for m in comp_mappings]},
            confidence=Confidence(score=0.85, source=KnowledgeSource.HUMAN_INJECTION),
            description=f"Component type mappings from {source_name}",
            tags=["mapping", "component", "human"],
            source_file=source_name,
        )]

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
