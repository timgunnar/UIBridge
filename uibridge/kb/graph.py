"""KnowledgeGraph — in-memory graph layer over YAML KBStore.

Supports relationship traversal without external graph databases.
Builds nodes and edges from existing KBItems on initialization.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

from .store import KBStore
from .item import KBItem


# ── Graph data types ────────────────────────────────────────────

class GraphNode:
    """A knowledge node in the graph."""

    def __init__(self, node_id: str, node_type: str, data: dict,
                 confidence: float = 0.5):
        self.id = node_id
        self.type = node_type           # ComponentType, Method, Locator, OperationSequence, FileFormat, NamingRule
        self.data = data                # payload from KBItem.value
        self.confidence = confidence

    def __repr__(self):
        return f"GraphNode(id={self.id!r}, type={self.type!r})"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "data": self.data,
            "confidence": self.confidence,
        }


class GraphEdge:
    """A directed edge between two knowledge nodes."""

    def __init__(self, from_id: str, relation: str, to_id: str):
        self.from_id = from_id
        self.relation = relation       # has_method, uses_locator, called_by, appears_in, references, inherits
        self.to_id = to_id

    def __repr__(self):
        return f"GraphEdge({self.from_id!r} -[{self.relation}]-> {self.to_id!r})"

    def to_dict(self) -> dict:
        return {
            "from": self.from_id,
            "relation": self.relation,
            "to": self.to_id,
        }


# Node type constants used during index building
_CONVENTION_NODE_TYPES = {"NamingRule", "Locator", "FileFormat", "AssertionStyle", "ImportRule"}
_COMPONENT_NODE_TYPES = {"ComponentType", "Method", "Locator"}
_PATTERN_NODE_TYPES = {"OperationSequence", "BusinessPattern", "PageStructure"}


def _infer_node_type(item: KBItem) -> str:
    """Infer a graph node type from a KBItem's category, key, and value."""
    cat = item.category

    if cat == "conventions":
        key = item.key.lower()
        if "naming" in key or "prefix" in key or "suffix" in key:
            return "NamingRule"
        if "locator" in key or "xpath" in key or "selector" in key:
            return "Locator"
        if "file" in key or "format" in key or "extension" in key:
            return "FileFormat"
        if "assert" in key or "verify" in key or "check" in key:
            return "AssertionStyle"
        if "import" in key or "package" in key:
            return "ImportRule"
        return "NamingRule"

    if cat == "components":
        key = item.key.lower()
        value = item.value or {}
        # If value has method-like entries, it's a ComponentType
        if "methods" in value or "class_name" in value or "base_class" in value:
            return "ComponentType"
        if "method" in key or "methods" in value or "signature" in value:
            return "Method"
        if "locator" in key or "xpath" in value or "selector" in value:
            return "Locator"
        return "ComponentType"

    if cat == "patterns":
        key = item.key.lower()
        if "operation" in key or "step" in key or "sequence" in key:
            return "OperationSequence"
        if "business" in key or "workflow" in key:
            return "BusinessPattern"
        return "OperationSequence"

    if cat == "pages":
        return "PageStructure"

    return "Unknown"


# ── KnowledgeGraph ─────────────────────────────────────────────

class KnowledgeGraph:
    """In-memory graph layer over YAML KBStore. Supports relationship traversal.

    Builds a node/edge index from existing KBItems in the store, inferring
    node types and relationships from item structure and content.
    """

    def __init__(self, store: KBStore):
        self.store = store
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._build_index()

    # ── Build ──────────────────────────────────────────────────

    def _build_index(self):
        """Scan all KBItems and build node/edge index.

        Edges are inferred from:
          - Same-category grouping (related_to)
          - Shared tags (shares_tag)
          - Value references to other item keys (references)
          - Method → component containment (has_method)
          - Locator → component containment (uses_locator)
        """
        self._nodes.clear()
        self._edges.clear()

        items = self.store.list_all()
        if not items:
            return

        # Phase 1: create nodes
        for item in items:
            node_type = _infer_node_type(item)
            node = GraphNode(
                node_id=item.id,
                node_type=node_type,
                data=item.value or {},
                confidence=item.confidence.effective_score,
            )
            self._nodes[item.id] = node

        # Phase 2: build lookup by key for cross-reference edges
        key_to_ids: dict[str, list[str]] = {}
        for item in items:
            key_to_ids.setdefault(item.key, []).append(item.id)

        # Phase 3: infer edges
        component_ids = [i.id for i in items if i.category == "components"]
        convention_ids = [i.id for i in items if i.category == "conventions"]
        pattern_ids = [i.id for i in items if i.category == "patterns"]

        for item in items:
            # ── Tag-based edges ──
            for tag in item.tags:
                for other in items:
                    if other.id != item.id and tag in other.tags:
                        self._add_edge_if_new(item.id, "shares_tag", other.id)

            # ── Category-based related_to edges ──
            for other in items:
                if (other.id != item.id
                        and other.category == item.category
                        and other.id > item.id):  # avoid duplicates
                    self._add_edge_if_new(item.id, "related_to", other.id)

            # ── Cross-reference: component → convention ──
            if item.id in component_ids:
                for conv_id in convention_ids:
                    conv_item = next((i for i in items if i.id == conv_id), None)
                    if conv_item and self._value_references(item.value, conv_item):
                        self._add_edge_if_new(item.id, "uses_convention", conv_id)

            # ── Method containment in component value ──
            if "methods" in (item.value or {}):
                methods = item.value.get("methods", [])
                if isinstance(methods, list):
                    for m in methods:
                        if isinstance(m, dict):
                            m_id = m.get("id", f"{item.id}_method_{m.get('name', 'unknown')}")
                        else:
                            m_id = f"{item.id}_method_{m}"
                        # Create a synthetic Method node if not exists
                        if m_id not in self._nodes:
                            method_data = m if isinstance(m, dict) else {"name": str(m)}
                            method_node = GraphNode(
                                node_id=m_id,
                                node_type="Method",
                                data=method_data,
                                confidence=item.confidence.effective_score,
                            )
                            self._nodes[m_id] = method_node
                        self._add_edge_if_new(item.id, "has_method", m_id)

            # ── Locator containment ──
            for loc_field in ("xpath_patterns", "locators", "locator_priorities"):
                if loc_field in (item.value or {}):
                    loc_val = item.value[loc_field]
                    loc_list = loc_val if isinstance(loc_val, list) else [loc_val]
                    for i_l, lv in enumerate(loc_list):
                        loc_id = f"{item.id}_locator_{i_l}"
                        if loc_id not in self._nodes:
                            loc_data = lv if isinstance(lv, dict) else {"value": str(lv)}
                            loc_node = GraphNode(
                                node_id=loc_id,
                                node_type="Locator",
                                data=loc_data,
                                confidence=item.confidence.effective_score,
                            )
                            self._nodes[loc_id] = loc_node
                        self._add_edge_if_new(item.id, "uses_locator", loc_id)

            # ── Component hierarchy: base_class reference ──
            base = (item.value or {}).get("base_class", "")
            if base:
                base_id = f"base_class_{base}"
                if base_id not in self._nodes:
                    base_node = GraphNode(
                        node_id=base_id,
                        node_type="ComponentType",
                        data={"class_name": base},
                        confidence=item.confidence.effective_score * 0.7,
                    )
                    self._nodes[base_id] = base_node
                self._add_edge_if_new(item.id, "inherits", base_id)

            # ── Pattern → component references ──
            if item.id in pattern_ids:
                val = item.value or {}
                for field in ("uses_components", "target_components", "components"):
                    refs = val.get(field, [])
                    if isinstance(refs, list):
                        for ref in refs:
                            ref_str = str(ref) if not isinstance(ref, str) else ref
                            matched = False
                            for comp_id in component_ids:
                                comp_item = next((i for i in items if i.id == comp_id), None)
                                if comp_item and ref_str.lower() in comp_item.key.lower():
                                    self._add_edge_if_new(item.id, "references", comp_id)
                                    matched = True
                            if not matched:
                                # Create a synthetic target node
                                target_id = f"target_{ref_str}"
                                if target_id not in self._nodes:
                                    target_node = GraphNode(
                                        node_id=target_id,
                                        node_type="ComponentType",
                                        data={"name": ref_str},
                                        confidence=0.3,
                                    )
                                    self._nodes[target_id] = target_node
                                self._add_edge_if_new(item.id, "references", target_id)

            # ── Shared source files → related ──
            if item.source_files:
                for other in items:
                    if other.id != item.id and other.source_files:
                        common = set(item.source_files) & set(other.source_files)
                        if common:
                            self._add_edge_if_new(item.id, "shares_source", other.id)

    # ── Query ──────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a knowledge node by ID."""
        return self._nodes.get(node_id)

    def query_related(self, node_id: str, relation: str = None) -> list[GraphNode]:
        """Find nodes related to this one.

        Args:
            node_id: The source node ID.
            relation: Optional filter by edge relation type
                      (e.g. 'has_method', 'uses_locator', 'references', 'inherits').

        Returns:
            List of GraphNode instances connected to the source node.
            Returns empty list if node_id not found.
        """
        if node_id not in self._nodes:
            return []

        result_ids: set[str] = set()
        for edge in self._edges:
            if edge.from_id == node_id:
                if relation is None or edge.relation == relation:
                    result_ids.add(edge.to_id)
            elif edge.to_id == node_id:
                if relation is None or edge.relation == relation:
                    result_ids.add(edge.from_id)

        return [self._nodes[nid] for nid in result_ids if nid in self._nodes]

    def find_by_type(self, node_type: str) -> list[GraphNode]:
        """Find all nodes of a certain type (ComponentType, Method, Locator, etc.)."""
        return [n for n in self._nodes.values() if n.type == node_type]

    def add_relation(self, from_id: str, relation: str, to_id: str):
        """Add an edge between two nodes explicitly.

        Nodes must already exist in the graph (via _build_index).
        """
        if from_id not in self._nodes:
            raise KeyError(f"Source node not found: {from_id}")
        if to_id not in self._nodes:
            raise KeyError(f"Target node not found: {to_id}")
        self._add_edge_if_new(from_id, relation, to_id)

    # ── Stats ──────────────────────────────────────────────────

    def node_count(self) -> int:
        """Total number of graph nodes."""
        return len(self._nodes)

    def edge_count(self) -> int:
        """Total number of graph edges."""
        return len(self._edges)

    def type_counts(self) -> dict[str, int]:
        """Count of nodes by type."""
        counts: dict[str, int] = {}
        for node in self._nodes.values():
            counts[node.type] = counts.get(node.type, 0) + 1
        return counts

    # ── Internal ───────────────────────────────────────────────

    @staticmethod
    def _value_references(value: dict, other_item: KBItem) -> bool:
        """Check if a value dict references another KBItem's key or description."""
        if not value or not other_item:
            return False
        # Check common value field names for key references
        ref_hints = [
            value.get("base_class"),
            value.get("extends"),
            value.get("implements"),
            value.get("type"),
        ]
        other_key_parts = other_item.key.lower().split(".")
        other_desc_words = set(other_item.description.lower().split())
        for hint in ref_hints:
            if hint and isinstance(hint, str):
                hint_lower = hint.lower()
                if any(part in hint_lower for part in other_key_parts if part):
                    return True
                if any(word in hint_lower for word in other_desc_words if len(word) > 3):
                    return True
        return False

    def _add_edge_if_new(self, from_id: str, relation: str, to_id: str):
        """Add an edge, skipping duplicates."""
        for edge in self._edges:
            if (edge.from_id == from_id and edge.relation == relation
                    and edge.to_id == to_id):
                return  # already exists
        self._edges.append(GraphEdge(from_id, relation, to_id))
