"""Unit tests for KnowledgeGraph and CrossValidator modules."""

import os
import tempfile
import time
from pathlib import Path

import pytest

from uibridge.kb.item import KBItem, Confidence, KnowledgeSource
from uibridge.kb.store import KBStore
from uibridge.kb.graph import KnowledgeGraph, GraphNode, GraphEdge, _infer_node_type
from uibridge.kb.cross_validate import CrossValidator


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _make_item(category, key, item_id, score=0.5,
               source=KnowledgeSource.STATIC_ANALYSIS,
               value=None, description="", tags=None, archived=False,
               source_files=None):
    """Create a KBItem for testing."""
    conf = Confidence(score=score, source=source,
                      last_validated_at=time.time())
    return KBItem(
        id=item_id, category=category, key=key,
        value=value or {}, confidence=conf,
        description=description, tags=tags or [],
        source_files=source_files or [],
        archived=archived,
    )


def _make_store(items: list[KBItem]) -> KBStore:
    """Create a temporary KBStore and populate it with items."""
    tmpdir = tempfile.mkdtemp()
    store = KBStore(tmpdir)
    for item in items:
        store.save(item)
    return store


# ══════════════════════════════════════════════════════════════
# TestKnowledgeGraphBuild
# ══════════════════════════════════════════════════════════════

class TestKnowledgeGraphBuild:
    """Tests for graph index construction."""

    def test_build_empty_store(self):
        """Empty store produces empty graph."""
        tmpdir = tempfile.mkdtemp()
        store = KBStore(tmpdir)
        graph = KnowledgeGraph(store)
        assert graph.node_count() == 0
        assert graph.edge_count() == 0

    def test_build_with_items(self):
        """Store with items → nodes created for each item."""
        items = [
            _make_item("components", "component_type.table", "c1",
                       value={"class_name": "WebTable", "methods": []},
                       score=0.8),
            _make_item("conventions", "convention.naming", "c2",
                       value={"naming_rules": ["prefix: set"]},
                       score=0.7),
            _make_item("patterns", "pattern.login", "c3",
                       value={"steps": ["open", "input", "click"]},
                       score=0.6),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        # Each item creates at least its own node
        assert graph.node_count() >= 3
        assert graph.edge_count() >= 0

    def test_node_types_inferred(self):
        """Node types are inferred from category and key."""
        items = [
            _make_item("components", "component_type.table", "c1",
                       value={"class_name": "WebTable"}),
            _make_item("conventions", "convention.naming", "c2",
                       value={"naming_rules": ["camelCase"]}),
            _make_item("conventions", "convention.locator_priority", "c3",
                       value={"priorities": ["id", "xpath"]}),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        assert graph.get_node("c1").type == "ComponentType"
        assert graph.get_node("c2").type == "NamingRule"
        assert graph.get_node("c3").type == "Locator"

    def test_method_nodes_synthetic(self):
        """Component with methods creates synthetic Method nodes."""
        items = [
            _make_item("components", "component_type.table", "c1",
                       value={
                           "class_name": "WebTable",
                           "methods": [
                               {"name": "sortColumn", "params": ["String", "int"]},
                               {"name": "getRowCount", "params": []},
                           ],
                       },
                       score=0.8),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        # 1 component + 2 synthetic method nodes
        assert graph.node_count() >= 3
        methods = graph.find_by_type("Method")
        assert len(methods) >= 2

    def test_locator_nodes_synthetic(self):
        """Component with xpath_patterns creates synthetic Locator nodes."""
        items = [
            _make_item("components", "component_type.table", "c1",
                       value={
                           "class_name": "WebTable",
                           "xpath_patterns": [
                               "//table[@data-module='search']",
                               "//div[@class='pagination']",
                           ],
                       },
                       score=0.8),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        locators = graph.find_by_type("Locator")
        assert len(locators) >= 2


# ══════════════════════════════════════════════════════════════
# TestKnowledgeGraphQuery
# ══════════════════════════════════════════════════════════════

class TestKnowledgeGraphQuery:
    """Tests for graph query operations."""

    def test_get_node_exists(self):
        """get_node returns node for existing ID."""
        items = [_make_item("components", "comp.table", "c1", score=0.9)]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        node = graph.get_node("c1")
        assert node is not None
        assert node.id == "c1"
        assert node.confidence == pytest.approx(0.9, abs=0.01)

    def test_get_node_not_found(self):
        """get_node returns None for non-existent ID."""
        tmpdir = tempfile.mkdtemp()
        store = KBStore(tmpdir)
        graph = KnowledgeGraph(store)
        assert graph.get_node("nonexistent") is None

    def test_query_related_by_tag(self):
        """Items sharing tags have related edges."""
        items = [
            _make_item("components", "comp.table", "c1",
                       tags=["table", "data"], score=0.8),
            _make_item("components", "comp.form", "c2",
                       tags=["form", "data"], score=0.7),
            _make_item("components", "comp.menu", "c3",
                       tags=["menu", "nav"], score=0.6),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        related = graph.query_related("c1")
        # c1 shares "data" with c2, so c2 should be related
        related_ids = {n.id for n in related}
        assert "c2" in related_ids

    def test_query_related_with_filter(self):
        """query_related with relation filter returns only matching edges."""
        items = [
            _make_item("components", "comp.table", "c1",
                       value={
                           "class_name": "WebTable",
                           "methods": [{"name": "sortColumn"}],
                       },
                       score=0.8),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        # Query by has_method relation
        related = graph.query_related("c1", relation="has_method")
        assert len(related) >= 1
        assert all(isinstance(n, GraphNode) for n in related)

    def test_query_related_unknown_node(self):
        """query_related on unknown node returns empty list."""
        tmpdir = tempfile.mkdtemp()
        store = KBStore(tmpdir)
        graph = KnowledgeGraph(store)
        assert graph.query_related("nonexistent") == []

    def test_find_by_type(self):
        """find_by_type returns all nodes of given type."""
        items = [
            _make_item("components", "comp.a", "c1"),
            _make_item("components", "comp.b", "c2"),
            _make_item("conventions", "conv.naming", "conv1",
                       value={"naming_rules": ["camelCase"]}),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        component_nodes = graph.find_by_type("ComponentType")
        assert len(component_nodes) >= 2
        naming_nodes = graph.find_by_type("NamingRule")
        assert len(naming_nodes) >= 1

    def test_add_relation(self):
        """add_relation adds an explicit edge."""
        items = [
            _make_item("components", "comp.a", "c1"),
            _make_item("components", "comp.b", "c2"),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        edge_count_before = graph.edge_count()
        graph.add_relation("c1", "test_relation", "c2")
        assert graph.edge_count() == edge_count_before + 1
        related = graph.query_related("c1", relation="test_relation")
        assert any(n.id == "c2" for n in related)

    def test_add_relation_missing_node(self):
        """add_relation raises KeyError for unknown node IDs."""
        items = [_make_item("components", "comp.a", "c1")]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        with pytest.raises(KeyError):
            graph.add_relation("c1", "test", "nonexistent")
        with pytest.raises(KeyError):
            graph.add_relation("nonexistent", "test", "c1")

    def test_inherits_edge(self):
        """Component with base_class creates inherits edge."""
        items = [
            _make_item("components", "comp.child", "c1",
                       value={"class_name": "ChildTable",
                              "base_class": "BaseTable"},
                       score=0.8),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        related = graph.query_related("c1", relation="inherits")
        assert len(related) >= 1

    def test_node_count_and_edge_count(self):
        """node_count and edge_count return correct values."""
        items = [
            _make_item("components", "comp.table", "c1",
                       value={"class_name": "WebTable", "methods": [
                           {"name": "sort"}, {"name": "filter"}]}),
            _make_item("components", "comp.form", "c2",
                       tags=["data"]),
            _make_item("conventions", "conv.locator", "conv1",
                       tags=["locator"]),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        assert graph.node_count() > 3  # includes synthetic method/locator nodes
        assert graph.edge_count() > 0  # tag-based and method edges
        type_counts = graph.type_counts()
        assert "ComponentType" in type_counts
        assert "Method" in type_counts

    def test_shared_source_files_edge(self):
        """Items with overlapping source_files get shares_source edges."""
        items = [
            _make_item("components", "comp.a", "c1",
                       source_files=["src/TableAW.java"]),
            _make_item("components", "comp.b", "c2",
                       source_files=["src/TableAW.java"]),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        related = graph.query_related("c1", relation="shares_source")
        assert any(n.id == "c2" for n in related)


# ══════════════════════════════════════════════════════════════
# TestCrossValidateMerge
# ══════════════════════════════════════════════════════════════

class TestCrossValidateMerge:
    """Tests for CrossValidator evidence merging."""

    def test_merge_evidence_updates_confidence(self):
        """Adding evidence from multiple sources adjusts confidence."""
        items = [
            _make_item("components", "comp.table", "c1",
                       score=0.5, source=KnowledgeSource.LLM_INFERENCE,
                       value={"class_name": "WebTable"}),
        ]
        store = _make_store(items)
        validator = CrossValidator(store)

        initial = validator.validate("c1")
        assert initial == pytest.approx(0.5, abs=0.01)

        validator.merge_evidence("c1", KnowledgeSource.STATIC_ANALYSIS,
                                 0.8, "Found in source code")
        updated = validator.validate("c1")
        # STATIC_ANALYSIS weight 0.65 with score 0.8 should pull confidence above 0.5
        assert updated > 0.5

    def test_merge_evidence_human_injection_boosts(self):
        """Human injection evidence should significantly boost confidence."""
        items = [
            _make_item("components", "comp.table", "c1",
                       score=0.4, source=KnowledgeSource.PATTERN_MINING,
                       value={"class_name": "WebTable"}),
        ]
        store = _make_store(items)
        validator = CrossValidator(store)

        validator.merge_evidence("c1", KnowledgeSource.HUMAN_INJECTION,
                                 0.95, "Manual verification by QA lead")
        updated = validator.validate("c1")
        assert updated > 0.7

    def test_merge_evidence_multiple_sources(self):
        """All three source types contribute to confidence."""
        items = [
            _make_item("components", "comp.menu", "c1",
                       score=0.3, source=KnowledgeSource.LLM_INFERENCE,
                       value={"class_name": "DropdownMenu"}),
        ]
        store = _make_store(items)
        validator = CrossValidator(store)

        # Code inference
        validator.merge_evidence("c1", KnowledgeSource.STATIC_ANALYSIS,
                                 0.75, "Parsed from MenuAW.java")
        # Browser observation
        validator.merge_evidence("c1", KnowledgeSource.RUNTIME_ANALYSIS,
                                 0.85, "Dropdown verified at runtime")
        # User input
        validator.merge_evidence("c1", KnowledgeSource.HUMAN_INJECTION,
                                 0.90, "Correct, we use this class for all menus")

        final = validator.validate("c1")
        assert final > 0.6  # combined evidence should raise confidence

    def test_evidence_detail_is_stored(self):
        """Evidence detail string is preserved."""
        items = [
            _make_item("components", "comp.btn", "c1",
                       score=0.5, value={"class_name": "ButtonAW"}),
        ]
        store = _make_store(items)
        validator = CrossValidator(store)
        from uibridge.kb.cross_validate import _EVIDENCE_STORE

        validator.merge_evidence("c1", KnowledgeSource.STATIC_ANALYSIS,
                                 0.7, "Found ButtonAW.java in src/aaw/")
        ev_list = _EVIDENCE_STORE.get("c1", [])
        assert len(ev_list) == 1
        assert ev_list[0]["detail"] == "Found ButtonAW.java in src/aaw/"


# ══════════════════════════════════════════════════════════════
# TestCrossValidateEmptyStore
# ══════════════════════════════════════════════════════════════

class TestCrossValidateEmptyStore:
    """Tests for CrossValidator with empty/missing items."""

    def test_validate_empty_store(self):
        """Empty store → validate returns 0.0."""
        tmpdir = tempfile.mkdtemp()
        store = KBStore(tmpdir)
        validator = CrossValidator(store)
        assert validator.validate("any_id") == 0.0

    def test_validate_nonexistent_item(self):
        """validate on non-existent item returns 0.0."""
        items = [_make_item("components", "comp.a", "c1")]
        store = _make_store(items)
        validator = CrossValidator(store)
        assert validator.validate("nonexistent") == 0.0

    def test_validate_all_empty(self):
        """validate_all on empty store returns empty dict."""
        tmpdir = tempfile.mkdtemp()
        store = KBStore(tmpdir)
        validator = CrossValidator(store)
        assert validator.validate_all() == {}

    def test_validate_all_with_items(self):
        """validate_all processes all stored items."""
        items = [
            _make_item("components", "comp.a", "c1", score=0.6),
            _make_item("conventions", "conv.b", "c2", score=0.7),
        ]
        store = _make_store(items)
        validator = CrossValidator(store)
        results = validator.validate_all()
        assert len(results) == 2
        assert "c1" in results
        assert "c2" in results
        assert 0.0 <= results["c1"] <= 1.0


# ══════════════════════════════════════════════════════════════
# TestCrossValidateResolveConflict
# ══════════════════════════════════════════════════════════════

class TestCrossValidateResolveConflict:
    """Tests for conflict resolution between items."""

    def test_resolve_winner_by_human_evidence(self):
        """Item with human injection evidence wins."""
        items = [
            _make_item("components", "comp.table_a", "c1",
                       score=0.6, source=KnowledgeSource.STATIC_ANALYSIS,
                       value={"class_name": "TableAW"}),
            _make_item("components", "comp.table_b", "c2",
                       score=0.6, source=KnowledgeSource.STATIC_ANALYSIS,
                       value={"class_name": "WebTableAW"}),
        ]
        store = _make_store(items)
        validator = CrossValidator(store)

        validator.merge_evidence("c2", KnowledgeSource.HUMAN_INJECTION,
                                 0.95, "QA confirmed: WebTableAW is correct")
        winner = validator.resolve_conflict("c1", "c2")
        assert winner == "c2"

    def test_resolve_winner_by_more_sources(self):
        """Item with more distinct evidence sources wins."""
        items = [
            _make_item("components", "comp.a", "c1",
                       score=0.5, source=KnowledgeSource.PATTERN_MINING),
            _make_item("components", "comp.b", "c2",
                       score=0.5, source=KnowledgeSource.PATTERN_MINING),
        ]
        store = _make_store(items)
        validator = CrossValidator(store)

        # c1 gets 2 distinct sources
        validator.merge_evidence("c1", KnowledgeSource.STATIC_ANALYSIS, 0.7)
        validator.merge_evidence("c1", KnowledgeSource.RUNTIME_ANALYSIS, 0.8)

        # c2 gets 1 source
        validator.merge_evidence("c2", KnowledgeSource.STATIC_ANALYSIS, 0.7)

        winner = validator.resolve_conflict("c1", "c2")
        assert winner == "c1"

    def test_resolve_winner_by_confidence(self):
        """When same source count, higher confidence wins."""
        items = [
            _make_item("components", "comp.x", "c1",
                       score=0.8, source=KnowledgeSource.STATIC_ANALYSIS),
            _make_item("components", "comp.y", "c2",
                       score=0.3, source=KnowledgeSource.STATIC_ANALYSIS),
        ]
        store = _make_store(items)
        validator = CrossValidator(store)
        # Equal sources, c1 has higher confidence
        winner = validator.resolve_conflict("c1", "c2")
        assert winner == "c1"

    def test_resolve_defaults_to_first(self):
        """When no differentiator, defaults to first item."""
        items = [
            _make_item("components", "comp.x", "c1", score=0.5),
            _make_item("components", "comp.y", "c2", score=0.5),
        ]
        store = _make_store(items)
        validator = CrossValidator(store)
        winner = validator.resolve_conflict("c1", "c2")
        assert winner == "c1"  # default


# ══════════════════════════════════════════════════════════════
# TestInferNodeType
# ══════════════════════════════════════════════════════════════

class TestInferNodeType:
    """Tests for _infer_node_type helper."""

    def test_convention_naming(self):
        item = _make_item("conventions", "convention.naming", "test")
        assert _infer_node_type(item) == "NamingRule"

    def test_convention_locator(self):
        item = _make_item("conventions", "convention.locator_priority", "test")
        assert _infer_node_type(item) == "Locator"

    def test_convention_file_format(self):
        item = _make_item("conventions", "convention.file_format", "test")
        assert _infer_node_type(item) == "FileFormat"

    def test_convention_assertion(self):
        item = _make_item("conventions", "convention.assert_style", "test")
        assert _infer_node_type(item) == "AssertionStyle"

    def test_convention_import(self):
        item = _make_item("conventions", "convention.import", "test")
        assert _infer_node_type(item) == "ImportRule"

    def test_component_with_class(self):
        item = _make_item("components", "comp.table", "t1",
                          value={"class_name": "WebTable"})
        assert _infer_node_type(item) == "ComponentType"

    def test_component_with_methods(self):
        item = _make_item("components", "comp.table", "t2",
                          value={"methods": ["sort"]})
        assert _infer_node_type(item) == "ComponentType"

    def test_pattern_operation(self):
        item = _make_item("patterns", "pattern.operation.login", "t3",
                          value={"steps": ["open", "input"]})
        assert _infer_node_type(item) == "OperationSequence"

    def test_page_structure(self):
        item = _make_item("pages", "page.dashboard", "t4", value={})
        assert _infer_node_type(item) == "PageStructure"

    def test_unknown_category(self):
        item = _make_item("unknown_cat", "some.key", "t5", value={})
        # Category gets normalized but _infer_node_type returns Unknown
        assert _infer_node_type(item) == "Unknown"


# ══════════════════════════════════════════════════════════════
# TestKnowledgeGraphFindByType (explicit)
# ══════════════════════════════════════════════════════════════

class TestKnowledgeGraphFindByType:
    """Dedicated tests for find_by_type."""

    def test_empty_result_for_unknown_type(self):
        items = [_make_item("components", "comp.a", "c1")]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        result = graph.find_by_type("NonExistentType")
        assert result == []

    def test_find_naming_rules(self):
        items = [
            _make_item("conventions", "conv.naming", "c1",
                       value={"naming_rules": ["camelCase"]}),
            _make_item("conventions", "conv.file_naming", "c2",
                       value={"file_naming": "snake_case"}),
            _make_item("components", "comp.table", "c3"),
        ]
        store = _make_store(items)
        graph = KnowledgeGraph(store)
        naming = graph.find_by_type("NamingRule")
        assert len(naming) >= 2


# ══════════════════════════════════════════════════════════════
# TestStoreSearchMethods
# ══════════════════════════════════════════════════════════════

class TestStoreSearchMethods:
    """Tests for search_by_tag and search_by_category."""

    def test_search_by_tag_exact(self):
        items = [
            _make_item("components", "comp.table", "c1",
                       tags=["table", "data"]),
            _make_item("components", "comp.form", "c2",
                       tags=["form", "input"]),
            _make_item("conventions", "conv.locator", "c3",
                       tags=["locator"]),
        ]
        store = _make_store(items)
        results = store.search_by_tag("table")
        assert len(results) == 1
        assert results[0].id == "c1"

    def test_search_by_tag_case_insensitive(self):
        items = [_make_item("components", "comp.a", "c1", tags=["Table"])]
        store = _make_store(items)
        results = store.search_by_tag("table")
        assert len(results) == 1

    def test_search_by_tag_archived_excluded(self):
        items = [
            _make_item("components", "comp.a", "c1",
                       tags=["data"], archived=True),
        ]
        store = _make_store(items)
        results = store.search_by_tag("data")
        assert len(results) == 0

    def test_search_by_tag_no_match(self):
        items = [_make_item("components", "comp.a", "c1", tags=["table"])]
        store = _make_store(items)
        results = store.search_by_tag("nonexistent")
        assert results == []

    def test_search_by_category_valid(self):
        items = [
            _make_item("components", "comp.a", "c1"),
            _make_item("components", "comp.b", "c2"),
            _make_item("conventions", "conv.c", "c3"),
        ]
        store = _make_store(items)
        results = store.search_by_category("components")
        assert len(results) == 2

    def test_search_by_category_invalid(self):
        items = [_make_item("components", "comp.a", "c1")]
        store = _make_store(items)
        results = store.search_by_category("nonexistent_cat")
        assert results == []

    def test_search_by_category_excludes_archived(self):
        items = [
            _make_item("components", "comp.a", "c1", archived=True),
            _make_item("components", "comp.b", "c2"),
        ]
        store = _make_store(items)
        results = store.search_by_category("components")
        assert len(results) == 1
        assert results[0].id == "c2"

    def test_search_by_tag_multiple_matches(self):
        items = [
            _make_item("components", "comp.a", "c1", tags=["data"], score=0.9),
            _make_item("components", "comp.b", "c2", tags=["data"], score=0.5),
        ]
        store = _make_store(items)
        results = store.search_by_tag("data")
        assert len(results) == 2
        # Sorted by confidence descending
        assert results[0].id == "c1"


# ══════════════════════════════════════════════════════════════
# TestGraphBackwardCompatibility
# ══════════════════════════════════════════════════════════════

class TestGraphBackwardCompatibility:
    """Ensure KBManager still works with new graph modules."""

    def test_kb_init_imports_graph(self):
        """__init__.py exports KnowledgeGraph and CrossValidator."""
        from uibridge.kb import KnowledgeGraph, GraphNode, GraphEdge, CrossValidator
        assert KnowledgeGraph is not None
        assert GraphNode is not None
        assert GraphEdge is not None
        assert CrossValidator is not None
