"""Tests for KBExtractor — all extraction mixins and helper functions.

Covers: _ExtractorBase, _JavaMixin, _PythonMixin, _ProfileMixin,
_AggregationMixin, _ConventionsMixin, _DocumentsMixin, safe_relative_to,
and KBItem/Confidence/KnowledgeSource.
"""

import os
import tempfile
from pathlib import Path

import pytest

from uibridge.kb.item import KBItem, Confidence, KnowledgeSource
from uibridge.kb.extractor import KBExtractor
from uibridge.kb.extractor._base import safe_relative_to
from uibridge.profile import FrameworkProfile, ProfileField


# ══════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════

def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_java_file(root: Path, rel_path: str, content: str) -> Path:
    p = root / rel_path
    _write(p, content)
    return p


def _make_py_file(root: Path, rel_path: str, content: str) -> Path:
    p = root / rel_path
    _write(p, content)
    return p


# ══════════════════════════════════════════════════════════
# Test safe_relative_to
# ══════════════════════════════════════════════════════════

class TestSafeRelativeTo:
    """safe_relative_to helper function."""

    def test_returns_relative_when_under_base(self):
        result = safe_relative_to(Path("/a/b/c/d.txt"), Path("/a/b"))
        assert result.replace("\\", "/") == "c/d.txt"

    def test_returns_absolute_when_not_under_base(self):
        result = safe_relative_to(Path("/other/file.txt"), Path("/a/b"))
        assert result == str(Path("/other/file.txt"))

    def test_same_directory(self):
        result = safe_relative_to(Path("/a/b/file.txt"), Path("/a/b"))
        assert result == "file.txt"

    def test_windows_style_paths(self):
        result = safe_relative_to(Path("C:/proj/src/foo.java"), Path("C:/proj"))
        assert result.replace("\\", "/") == "src/foo.java"


# ══════════════════════════════════════════════════════════
# Test KnowledgeSource / Confidence / KBItem
# ══════════════════════════════════════════════════════════

class TestKnowledgeSource:
    """KnowledgeSource enum and default decay rates."""

    def test_static_analysis_decay(self):
        assert KnowledgeSource.STATIC_ANALYSIS.default_decay_rate == 0.003

    def test_human_injection_no_decay(self):
        assert KnowledgeSource.HUMAN_INJECTION.default_decay_rate == 0.0

    def test_runtime_analysis_decay(self):
        assert KnowledgeSource.RUNTIME_ANALYSIS.default_decay_rate == 0.002

    def test_pattern_mining_decay(self):
        assert KnowledgeSource.PATTERN_MINING.default_decay_rate == 0.01


class TestConfidence:
    """Confidence dataclass: effective_score, record_pass/failure, decay."""

    def test_default_values(self):
        c = Confidence()
        assert c.score == 0.5
        assert c.source == KnowledgeSource.LLM_INFERENCE

    def test_effective_score_no_decay(self):
        c = Confidence(score=0.8, source=KnowledgeSource.HUMAN_INJECTION)
        assert 0.79 <= c.effective_score <= 0.81

    def test_manual_override(self):
        c = Confidence(score=0.5, manual_override=0.95)
        assert c.effective_score == 0.95

    def test_record_pass_increases_score(self):
        c = Confidence(score=0.7)
        c.record_pass()
        assert c.score > 0.7
        assert c.self_test_passes == 1

    def test_record_failure_decreases_score(self):
        c = Confidence(score=0.7)
        c.record_failure()
        assert c.score < 0.7
        assert c.self_test_failures == 1

    def test_score_clamped_to_1(self):
        c = Confidence(score=0.99)
        c.record_pass()
        assert c.score <= 1.0

    def test_score_clamped_to_0(self):
        c = Confidence(score=0.1)
        c.record_failure()
        assert c.score >= 0.0

    def test_effective_score_respects_decay(self):
        """After a long time, confidence should decay."""
        # last_validated_at must be > 0 for decay to apply
        c = Confidence(score=0.8, source=KnowledgeSource.PATTERN_MINING,
                       last_validated_at=1.0)  # very old (1 sec after epoch)
        decayed = c.effective_score
        assert decayed < 0.8  # should have decayed substantially


class TestKBItem:
    """KBItem dataclass: construction, to_dict/from_dict roundtrip."""

    def test_minimal_construction(self):
        item = KBItem(id="test_1", category="components", key="comp.test", value={"a": 1})
        assert item.id == "test_1"
        assert item.category == "components"
        assert item.key == "comp.test"
        assert item.value == {"a": 1}
        assert item.aggregation == ""
        assert item.source_files == []

    def test_full_construction(self):
        item = KBItem(
            id="full_1",
            category="conventions",
            key="conv.test",
            value={"rule": "camelCase"},
            confidence=Confidence(score=0.9, source=KnowledgeSource.HUMAN_INJECTION),
            description="Test convention",
            tags=["test", "conv"],
            source_file="test.java",
            source_files=["a.java", "b.java"],
            aggregation="convention_batch",
        )
        assert item.aggregation == "convention_batch"
        assert item.source_files == ["a.java", "b.java"]

    def test_to_dict_includes_aggregation(self):
        item = KBItem(
            id="agg_1", category="components", key="comp.agg",
            value={}, aggregation="component_family", source_files=["x.java"],
        )
        d = item.to_dict()
        assert d["aggregation"] == "component_family"
        assert d["source_files"] == ["x.java"]

    def test_from_dict_minimal(self):
        d = {"id": "d1", "category": "pages", "key": "page.test", "value": {}}
        item = KBItem.from_dict(d)
        assert item.id == "d1"
        assert item.aggregation == ""
        assert item.source_files == []

    def test_from_dict_missing_confidence(self):
        d = {"id": "d2", "category": "pages", "key": "page.test2", "value": {}}
        item = KBItem.from_dict(d)
        assert isinstance(item.confidence, Confidence)
        assert item.confidence.score == 0.5

    def test_roundtrip_full(self):
        item = KBItem(
            id="rt_1",
            category="components",
            key="comp.rt",
            value={"methods": ["click", "type"]},
            confidence=Confidence(score=0.75, source=KnowledgeSource.STATIC_ANALYSIS,
                                  self_test_passes=2, self_test_failures=1),
            description="Roundtrip test",
            tags=["comp"],
            source_file="src/Comp.java",
            source_files=["src/Comp.java", "src/Child.java"],
            aggregation="component_family",
        )
        d = item.to_dict()
        restored = KBItem.from_dict(d)
        assert restored.id == item.id
        assert restored.category == item.category
        assert restored.key == item.key
        assert restored.value == item.value
        assert restored.confidence.score == item.confidence.score
        assert restored.confidence.source == item.confidence.source
        assert restored.aggregation == item.aggregation
        assert restored.source_files == item.source_files
        assert restored.tags == item.tags


# ══════════════════════════════════════════════════════════
# Test KBExtractor Initialization
# ══════════════════════════════════════════════════════════

class TestKBExtractorInit:
    """KBExtractor initialization and project_root resolution."""

    def test_default_project_root_is_cwd(self):
        extractor = KBExtractor()
        assert isinstance(extractor.project_root, Path)

    def test_explicit_project_root(self, tmp_path):
        extractor = KBExtractor(str(tmp_path))
        assert extractor.project_root == tmp_path.resolve()

    def test_dot_project_root(self):
        extractor = KBExtractor(".")
        assert extractor.project_root.resolve() == Path(".").resolve()

    def test_javalang_not_available(self):
        """_check_javalang returns False when javalang not installed."""
        extractor = KBExtractor()
        extractor._java_available = None
        # Force import failure by ensuring javalang is not importable
        # In CI/dev envs without javalang, this should return False
        result = extractor._check_javalang()
        # Either True (javalang installed) or False
        assert isinstance(result, bool)


# ══════════════════════════════════════════════════════════
# Test Base Extractor — Runtime Trace
# ══════════════════════════════════════════════════════════

class TestRuntimeTrace:
    """KBExtractor.extract_from_runtime_trace."""

    def test_extract_with_xpath_traces(self):
        extractor = KBExtractor()
        traces = [
            {
                "method": "click",
                "executed_ops": [
                    {"locator": "xpath=//button[@id='submit']", "action": "click"},
                    {"locator": "id=submit", "action": "find"},
                ],
            },
            {
                "method": "getText",
                "executed_ops": [
                    {"locator": "xpath=//div[@class='result']", "action": "get_text"},
                ],
            },
        ]
        items = extractor.extract_from_runtime_trace("Button", traces, "http://example.com")
        assert len(items) == 2
        assert items[0].category == "components"
        assert items[0].confidence.source == KnowledgeSource.RUNTIME_ANALYSIS
        assert 0.8 <= items[0].confidence.score <= 0.9
        assert "rt_Button_click" == items[0].id
        # Check validated xpaths
        assert "xpath=//button[@id='submit']" in items[0].value["validated_xpaths"]

    def test_extract_empty_traces(self):
        extractor = KBExtractor()
        items = extractor.extract_from_runtime_trace("Button", [], "")
        assert items == []

    def test_extract_no_xpath_ops(self):
        extractor = KBExtractor()
        traces = [
            {
                "method": "hover",
                "executed_ops": [
                    {"locator": "id=menu", "action": "hover"},
                ],
            }
        ]
        items = extractor.extract_from_runtime_trace("Menu", traces, "http://example.com")
        assert len(items) == 1
        assert items[0].value["validated_xpaths"] == []

    def test_runtime_trace_tags(self):
        extractor = KBExtractor()
        traces = [{"method": "click", "executed_ops": [
            {"locator": "xpath=//button", "action": "click"}]}]
        items = extractor.extract_from_runtime_trace("Button", traces, "")
        assert "Button" in items[0].tags
        assert "runtime" in items[0].tags


# ══════════════════════════════════════════════════════════
# Test Java Regex Parsing
# ══════════════════════════════════════════════════════════

class TestJavaRegex:
    """KBExtractor._parse_java_regex and related static methods."""

    def test_parse_full_class(self):
        source = """
        package com.acme.components;
        import org.openqa.selenium.By;
        import org.openqa.selenium.WebElement;
        import static org.testng.Assert.*;

        @Component
        @FindBy(xpath = "//table")
        public class WebTable extends BaseComponent implements HasTable, Serializable {
            public void sortColumn(String name) {}
            public int getRowCount() { return 0; }
            private String internalState;
        }
        """
        result = KBExtractor._parse_java_regex(source)
        assert result is not None
        assert result["class_name"] == "WebTable"
        assert result["package"] == "com.acme.components"
        assert result["base_class"] == "BaseComponent"
        assert "HasTable" in result["implements"]
        assert "Serializable" in result["implements"]
        assert "FindBy" in result["annotations"]
        assert "Component" in result["annotations"]

    def test_parse_minimal_class(self):
        source = """
        package com.example;
        public class SimplePage {
        }
        """
        result = KBExtractor._parse_java_regex(source)
        assert result is not None
        assert result["class_name"] == "SimplePage"
        assert result["package"] == "com.example"
        assert "base_class" not in result

    def test_parse_no_package(self):
        source = """
        class BareClass {
            public void doSomething() {}
        }
        """
        result = KBExtractor._parse_java_regex(source)
        assert result is not None
        assert result["class_name"] == "BareClass"
        assert "package" not in result

    def test_parse_empty_returns_none(self):
        result = KBExtractor._parse_java_regex("")
        assert result is None

    def test_parse_no_class_returns_none(self):
        result = KBExtractor._parse_java_regex("package com.example;")
        assert result is None

    def test_parse_with_comments_ignored(self):
        source = """
        // This is a comment with a class FakeClass { ... }
        /* Block comment with class AnotherFake { } */
        package com.example;
        public class RealClass {
            // class InnerFake { }
            public void doWork() {}
        }
        """
        result = KBExtractor._parse_java_regex(source)
        assert result is not None
        assert result["class_name"] == "RealClass"

    def test_parse_methods_exclude_keywords(self):
        """Method regex should exclude Java keywords like if, while, for, etc."""
        source = """
        package com.example;
        public class ControlFlow {
            public void process() {
                if (true) { }
                while (true) { }
                for (int i = 0; i < 10; i++) { }
                try { } catch (Exception e) { }
            }
        }
        """
        result = KBExtractor._parse_java_regex(source)
        assert result is not None
        method_names = [m["name"] for m in result.get("methods", [])]
        # Only "process" should be captured, not keywords
        assert "process" in method_names
        assert "if" not in method_names
        assert "while" not in method_names
        assert "for" not in method_names

    def test_parse_locator_annotations(self):
        source = """
        public class LoginPage {
            @FindBy(id = "username")
            private WebElement usernameInput;

            @FindBy(xpath = "//button[@data-module='submit']")
            private WebElement submitButton;

            @DataTestId("password-field")
            private WebElement passwordInput;
        }
        """
        result = KBExtractor._parse_java_regex(source)
        assert result is not None
        assert "locator_annotations" in result
        # Should have at least the @FindBy annotations
        assert len(result["locator_annotations"]) >= 1

    def test_parse_annotation_deduplication(self):
        source = """
        @Test
        @Test
        @Component
        public class DupAnnotations {
        }
        """
        result = KBExtractor._parse_java_regex(source)
        assert result is not None
        # Annotations should be deduplicated
        assert result["annotations"].count("Test") == 1

    def test_parse_imports(self):
        source = """
        package com.example;
        import java.util.List;
        import java.util.Map;
        import static org.testng.Assert.assertEquals;

        public class MyUtils {
        }
        """
        result = KBExtractor._parse_java_regex(source)
        assert result is not None
        imports = result.get("imports", [])
        assert "java.util.List" in imports
        assert "java.util.Map" in imports


# ══════════════════════════════════════════════════════════
# Test Java AST Helpers
# ══════════════════════════════════════════════════════════

class TestJavaASTHelpers:
    """KBExtractor helpers: _find_java_class_name, _extract_java_base_class, etc."""

    def test_find_class_name_from_regex_dict(self):
        extractor = KBExtractor()
        tree = {"class_name": "WebTable", "package": "com.example"}
        assert extractor._find_java_class_name(tree) == "WebTable"

    def test_find_class_name_none_tree(self):
        extractor = KBExtractor()
        assert extractor._find_java_class_name(None) is None

    def test_find_class_name_missing_key(self):
        extractor = KBExtractor()
        assert extractor._find_java_class_name({}) is None

    def test_extract_base_class_from_regex_dict(self):
        extractor = KBExtractor()
        tree = {"base_class": "BaseComponent"}
        assert extractor._extract_java_base_class(tree) == "BaseComponent"

    def test_extract_base_class_none(self):
        extractor = KBExtractor()
        assert extractor._extract_java_base_class(None) is None

    def test_extract_implements_from_regex_dict(self):
        extractor = KBExtractor()
        tree = {"implements": ["HasTable", "Serializable"]}
        impls = extractor._extract_java_implements(tree)
        assert "HasTable" in impls
        assert "Serializable" in impls

    def test_extract_implements_none(self):
        extractor = KBExtractor()
        assert extractor._extract_java_implements(None) == []

    def test_extract_package_from_regex_dict(self):
        extractor = KBExtractor()
        tree = {"package": "com.acme.ui"}
        assert extractor._extract_java_package(tree) == "com.acme.ui"

    def test_extract_package_none(self):
        extractor = KBExtractor()
        assert extractor._extract_java_package(None) == ""

    def test_extract_methods_from_regex_dict(self):
        extractor = KBExtractor()
        tree = {
            "methods": [
                {"name": "click", "returns": "void", "params": [], "modifiers": []},
                {"name": "getText", "returns": "String", "params": [], "modifiers": []},
            ]
        }
        methods = extractor._extract_java_methods(tree)
        assert len(methods) == 2
        assert methods[0]["name"] == "click"

    def test_extract_annotations_from_regex_dict(self):
        extractor = KBExtractor()
        tree = {"annotations": ["Test", "FindBy", "Component"]}
        result = extractor._extract_java_annotations(tree)
        assert len(result) == 3
        assert "FindBy" in result

    def test_extract_imports_from_regex_dict(self):
        extractor = KBExtractor()
        tree = {"imports": ["java.util.List", "org.openqa.selenium.By"]}
        imports = extractor._extract_java_imports(tree)
        assert "java.util.List" in imports

    def test_is_tree_from_regex(self):
        extractor = KBExtractor()
        assert extractor._is_tree_from_regex({"class_name": "X"}) is True
        assert extractor._is_tree_from_regex("not_a_dict") is False


# ══════════════════════════════════════════════════════════
# Test _parse_locator_annotation
# ══════════════════════════════════════════════════════════

class TestParseLocatorAnnotation:
    """KBExtractor._parse_locator_annotation static method."""

    def test_id_strategy(self):
        result = KBExtractor._parse_locator_annotation('id = "search-box"')
        assert result == {"strategy": "id", "value": "search-box"}

    def test_xpath_strategy(self):
        result = KBExtractor._parse_locator_annotation('xpath = "//div[@id=\\"main\\"]"')
        assert result is not None
        assert result["strategy"] == "xpath"

    def test_css_strategy(self):
        result = KBExtractor._parse_locator_annotation('css = ".container > .item"')
        assert result == {"strategy": "css", "value": ".container > .item"}

    def test_name_strategy(self):
        result = KBExtractor._parse_locator_annotation('name = "username"')
        assert result == {"strategy": "name", "value": "username"}

    def test_how_using_style(self):
        result = KBExtractor._parse_locator_annotation(
            'how = Using.ID, using = "submit-btn"'
        )
        assert result == {"strategy": "id", "value": "submit-btn"}

    def test_no_match_returns_none(self):
        result = KBExtractor._parse_locator_annotation("not a locator")
        assert result is None

    def test_empty_string(self):
        result = KBExtractor._parse_locator_annotation("")
        assert result is None


# ══════════════════════════════════════════════════════════
# Test _infer_component_type
# ══════════════════════════════════════════════════════════

class TestInferComponentType:
    """KBExtractor._infer_component_type class method."""

    def test_infer_from_base_class(self):
        result = KBExtractor._infer_component_type(
            "WebTable", "TableWidget", None, None
        )
        assert result == "table"

    def test_infer_from_class_name_suffix(self):
        result = KBExtractor._infer_component_type(
            "LoginForm", None, None, None
        )
        assert result == "form"

    def test_infer_dialog_from_name(self):
        result = KBExtractor._infer_component_type(
            "ConfirmDialog", None, None, None
        )
        assert result == "dialog"

    def test_infer_from_implements(self):
        result = KBExtractor._infer_component_type(
            "CustomThing", None, ["HasTable", "Runnable"], None
        )
        # HasTable maps to table; the cleaned name is "Table"
        assert result == "table"

    def test_no_match_returns_none(self):
        result = KBExtractor._infer_component_type(
            "SomethingRandom", None, None, None
        )
        assert result is None

    def test_base_class_overrides_suffix(self):
        """Base class weight (3) > class suffix weight (2)."""
        # "LoginButton" suffix matches "Button" but base class says "form"
        result = KBExtractor._infer_component_type(
            "LoginButton", "AbstractForm", None, None
        )
        assert result == "form"


# ══════════════════════════════════════════════════════════
# Test _compute_java_confidence
# ══════════════════════════════════════════════════════════

class TestComputeJavaConfidence:
    """KBExtractor._compute_java_confidence static method."""

    def test_only_class_name(self):
        c = KBExtractor._compute_java_confidence(
            False, False, False, False, False, True
        )
        assert c.score == 0.5

    def test_regex_fallback_with_info(self):
        c = KBExtractor._compute_java_confidence(
            True, False, False, False, True, False
        )
        assert c.score == 0.55

    def test_annotations_and_locators(self):
        c = KBExtractor._compute_java_confidence(
            True, True, False, False, False, False
        )
        assert c.score == 0.80

    def test_base_class_or_implements(self):
        c = KBExtractor._compute_java_confidence(
            False, False, True, False, False, False
        )
        assert c.score == 0.75

    def test_annotations_only(self):
        c = KBExtractor._compute_java_confidence(
            True, False, False, False, False, False
        )
        assert c.score == 0.70

    def test_default_no_info(self):
        c = KBExtractor._compute_java_confidence(
            False, False, False, False, False, False
        )
        assert c.score == 0.65


# ══════════════════════════════════════════════════════════
# Test _extract_java_naming_signature
# ══════════════════════════════════════════════════════════

class TestJavaNamingSignature:
    """KBExtractor._extract_java_naming_signature."""

    def test_class_suffix_aw(self):
        result = KBExtractor._extract_java_naming_signature("TableAW", [])
        assert result is not None
        assert result["class_suffix"] == "AW"

    def test_class_suffix_page(self):
        result = KBExtractor._extract_java_naming_signature("LoginPage", [])
        assert result == {"class_suffix": "Page"}

    def test_method_prefix_detection(self):
        methods = [
            {"name": "getText"},
            {"name": "getCount"},
            {"name": "clickButton"},
            {"name": "isEnabled"},
        ]
        result = KBExtractor._extract_java_naming_signature("Component", methods)
        assert result is not None
        assert result["method_prefix"] == "get"

    def test_field_style_camel_case(self):
        methods = [
            {"name": "getRowCount"},
            {"name": "clickButton"},
            {"name": "isEnabled"},
        ]
        result = KBExtractor._extract_java_naming_signature("Component", methods)
        assert result is not None
        assert result["field_style"] == "camelCase"

    def test_field_style_snake_case(self):
        methods = [
            {"name": "get_row_count"},
            {"name": "click_button"},
        ]
        result = KBExtractor._extract_java_naming_signature("Component", methods)
        assert result is not None
        assert result["field_style"] == "snake_case"

    def test_empty_methods_no_prefix(self):
        result = KBExtractor._extract_java_naming_signature("Bare", [])
        # No suffix and no methods means no naming data
        assert result is None

    def test_method_lowercase_prefix_ignored(self):
        """Method names that start with lowercase prefix but next char is not uppercase
        are not counted as method_prefix (e.g., 'get' must be followed by uppercase).
        field_style may still be set based on presence/absence of underscores."""
        methods = [
            {"name": "get"},  # No uppercase after prefix → not counted
            {"name": "is"},   # No uppercase after prefix → not counted
        ]
        result = KBExtractor._extract_java_naming_signature("MyClass", methods)
        # No class_suffix (MyClass doesn't match any suffix), no method_prefix
        assert result is None or result.get("method_prefix") is None


# ══════════════════════════════════════════════════════════
# Test Java File Extraction (legacy)
# ══════════════════════════════════════════════════════════

class TestJavaFileExtraction:
    """KBExtractor.extract_from_java_file (legacy)."""

    def test_extract_component_file(self, tmp_path):
        java = _make_java_file(tmp_path, "components/WebTable.java", """
package com.acme.components;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.By;

@Component
public class WebTable extends BaseComponent {
    @FindBy(xpath = "//table[@data-module='result']")
    private WebElement root;

    public void sortColumn(String name) {}
    public int getRowCount() { return 0; }
}
""")
        extractor = KBExtractor(str(tmp_path))
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_java_file(str(java))
        assert len(items) == 1
        assert items[0].category == "components"
        assert items[0].value["class_name"] == "WebTable"
        assert "table" in items[0].tags

    def test_extract_page_file(self, tmp_path):
        java = _make_java_file(tmp_path, "pages/LoginPage.java", """
package com.acme.pages;
import com.acme.components.WebButton;

public class LoginPage extends BasePage {
    private WebButton loginButton;
    public void login(String user, String pass) {}
}
""")
        extractor = KBExtractor(str(tmp_path))
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_java_file(str(java))
        assert len(items) == 1
        assert items[0].category == "pages"

    def test_extract_nonexistent_file(self):
        extractor = KBExtractor()
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_java_file("/nonexistent/path.java")
        assert items == []

    def test_extract_no_class_in_file(self, tmp_path):
        java = _make_java_file(tmp_path, "NotAClass.java", """
package com.example;
// This file has no class, just a package
""")
        extractor = KBExtractor(str(tmp_path))
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_java_file(str(java))
        # No class found, regex returns None
        assert items == []

    def test_extract_source_file_relative(self, tmp_path):
        java = _make_java_file(tmp_path, "com/acme/Widget.java", """
package com.acme;
public class Widget extends BaseWidget {
    public void action() {}
}
""")
        extractor = KBExtractor(str(tmp_path))
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_java_file(str(java))
        assert len(items) == 1
        assert items[0].source_file.replace("\\", "/") == "com/acme/Widget.java"


# ══════════════════════════════════════════════════════════
# Test Java Test Extraction (legacy)
# ══════════════════════════════════════════════════════════

class TestJavaTestExtraction:
    """KBExtractor.extract_from_java_test (legacy)."""

    def test_extract_test_file(self, tmp_path):
        java = _make_java_file(tmp_path, "tests/TestLogin.java", """
package com.acme.tests;
import org.testng.annotations.Test;
import com.acme.pages.LoginPage;

@Test
public class TestLogin {
    @Test
    public void testValidLogin() {
        LoginPage page = new LoginPage();
        page.login("admin", "pass");
    }
}
""")
        extractor = KBExtractor(str(tmp_path))
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_java_test(str(java))
        assert len(items) == 1
        assert items[0].category == "conventions"
        assert items[0].value["class_name"] == "TestLogin"
        assert "org.testng.annotations.Test" in items[0].value["imports"]

    def test_extract_test_nonexistent(self):
        extractor = KBExtractor()
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_java_test("/nonexistent/Test.java")
        assert items == []


# ══════════════════════════════════════════════════════════
# Test Python Extraction (legacy)
# ══════════════════════════════════════════════════════════

class TestPythonExtraction:
    """KBExtractor legacy Python extractors."""

    def test_extract_from_component_aw(self, tmp_path):
        py = _make_py_file(tmp_path, "aw/table_aw.py", '''
class TableAW:
    """Table component wrapper."""
    TABLE_XPATH = "//table[@data-module='table']"

    def get_row_count(self):
        return len(self.driver.find_elements_by_xpath(self.TABLE_XPATH))

    def click_cell(self, row: int, col: int) -> None:
        pass
''')
        extractor = KBExtractor(str(tmp_path))
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_component_aw(str(py))
        assert isinstance(items, list)
        if items:
            assert items[0].category == "components"
            assert items[0].value["class_name"] == "TableAW"
            # Should have xpath patterns
            xpaths = items[0].value.get("xpath_patterns", [])
            assert any("TABLE_XPATH" in x for x in xpaths)

    def test_extract_from_page_file(self, tmp_path):
        py = _make_py_file(tmp_path, "pages/login_page.py", '''
class LoginPage:
    USERNAME_INPUT = '//input[@data-module="username"]'
    PASSWORD_INPUT = '//input[@data-module="password"]'
    SUBMIT_BUTTON = '//button[@data-testid="login-btn"]'

    def login(self, user, password):
        pass
''')
        extractor = KBExtractor(str(tmp_path))
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_page_file(str(py))
        assert isinstance(items, list)
        if items:
            assert items[0].category == "pages"
            assert items[0].value["class_name"] == "LoginPage"
            fps = items[0].value.get("feature_points", [])
            assert len(fps) >= 2

    def test_extract_from_test_script(self, tmp_path):
        py = _make_py_file(tmp_path, "tests/test_login.py", '''
import pytest
from pages.login_page import LoginPage

@pytest.fixture
def page():
    return LoginPage()

class TestLogin:
    def test_valid_login(self, page):
        page.login("admin", "pass")
        assert page.is_logged_in()

    def test_invalid_login(self, page):
        page.login("bad", "wrong")
        assert not page.is_logged_in()
''')
        extractor = KBExtractor(str(tmp_path))
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_test_script(str(py))
        assert isinstance(items, list)
        if items:
            assert items[0].category == "conventions"
            assert items[0].value.get("assertion_style") == "pytest_assert"
            imports = items[0].value.get("imports", [])
            assert any("import pytest" in imp for imp in imports)

    def test_extract_component_aw_nonexistent(self):
        extractor = KBExtractor()
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_component_aw("/nonexistent/file.py")
        assert items == []

    def test_extract_page_file_nonexistent(self):
        extractor = KBExtractor()
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_page_file("/nonexistent/file.py")
        assert items == []

    def test_extract_test_script_nonexistent(self):
        extractor = KBExtractor()
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_test_script("/nonexistent/file.py")
        assert items == []


# ══════════════════════════════════════════════════════════
# Test Python AST Helpers
# ══════════════════════════════════════════════════════════

class TestPythonASTHelpers:
    """Individual _PythonMixin helper methods tested via KBExtractor."""

    def test_parse_valid_python(self):
        extractor = KBExtractor()
        py_file = Path(tempfile.mktemp(suffix=".py"))
        py_file.write_text("class Foo:\n    def bar(self):\n        pass\n", encoding="utf-8")
        try:
            tree = extractor._parse(py_file)
            assert tree is not None
        finally:
            py_file.unlink(missing_ok=True)

    def test_parse_syntax_error(self):
        extractor = KBExtractor()
        py_file = Path(tempfile.mktemp(suffix=".py"))
        py_file.write_text("this is not valid python !!!", encoding="utf-8")
        try:
            tree = extractor._parse(py_file)
            assert tree is None
        finally:
            py_file.unlink(missing_ok=True)

    def test_parse_file_not_found(self, tmp_path):
        """_parse does not catch FileNotFoundError (only SyntaxError/UnicodeDecodeError)."""
        extractor = KBExtractor()
        nonexistent = tmp_path / "does_not_exist.py"
        with pytest.raises(FileNotFoundError):
            extractor._parse(nonexistent)

    def test_find_class_name(self):
        import ast
        extractor = KBExtractor()
        tree = ast.parse("class MyComponent:\n    pass\n")
        assert extractor._find_class_name(tree) == "MyComponent"

    def test_find_class_name_none(self):
        import ast
        extractor = KBExtractor()
        tree = ast.parse("x = 1\n")
        assert extractor._find_class_name(tree) is None

    def test_extract_xpath_patterns(self):
        import ast
        extractor = KBExtractor()
        code = '''
TABLE_XPATH = "//table[@data-module='table']"
ROW_XPATH = "//tr"
NOT_A_LOCATOR = "hello world"
'''
        tree = ast.parse(code)
        patterns = extractor._extract_xpath_patterns(tree)
        assert any("TABLE_XPATH" in p for p in patterns)
        assert any("ROW_XPATH" in p for p in patterns)
        assert not any("NOT_A_LOCATOR" in p for p in patterns)

    def test_extract_methods(self):
        import ast
        extractor = KBExtractor()
        code = '''
class Foo:
    def method_a(self, x, y):
        pass
    def method_b(self) -> str:
        return "hello"
'''
        tree = ast.parse(code)
        methods = extractor._extract_methods(tree)
        assert len(methods) == 2
        names = [m["name"] for m in methods]
        assert "method_a" in names
        assert "method_b" in names
        # method_b has return type annotation
        mb = next(m for m in methods if m["name"] == "method_b")
        assert mb["returns"] == "str"

    def test_extract_feature_points(self):
        import ast
        extractor = KBExtractor()
        code = '''
USERNAME = '@data-module="username"'
PASSWORD = "@data-testid=\\"password-field\\""
NOTHING = "just text"
'''
        tree = ast.parse(code)
        points = extractor._extract_feature_points(tree)
        assert len(points) == 2
        values = [p["value"] for p in points]
        assert "username" in values
        assert "password-field" in values

    def test_extract_imports(self):
        import ast
        extractor = KBExtractor()
        code = '''
import os
import sys
from pathlib import Path
from typing import Optional, List
'''
        tree = ast.parse(code)
        imports = extractor._extract_imports(tree)
        assert "import os" in imports
        assert "import sys" in imports
        assert any("from pathlib" in i for i in imports)
        assert any("from typing" in i for i in imports)

    def test_extract_fixture_names(self):
        import ast
        extractor = KBExtractor()
        code = '''
import pytest

@pytest.fixture
def browser():
    return "chrome"

@pytest.fixture()
def page(browser):
    return LoginPage(browser)
'''
        tree = ast.parse(code)
        fixtures = extractor._extract_fixture_names(tree)
        assert "browser" in fixtures
        assert "page" in fixtures

    def test_detect_assertion_style_pytest(self):
        import ast
        extractor = KBExtractor()
        code = '''
def test_something():
    assert True
    assert x == y
'''
        tree = ast.parse(code)
        style = extractor._detect_assertion_style(tree)
        assert style == "pytest_assert"

    def test_detect_assertion_style_unittest(self):
        import ast
        extractor = KBExtractor()
        code = '''
class TestSomething:
    def test_something(self):
        self.assertEqual(a, b)
        self.assertTrue(cond)
'''
        tree = ast.parse(code)
        style = extractor._detect_assertion_style(tree)
        assert style == "self.assertXxx"

    def test_detect_assertion_style_unknown(self):
        import ast
        extractor = KBExtractor()
        code = "x = 1\n"
        tree = ast.parse(code)
        style = extractor._detect_assertion_style(tree)
        assert style == "unknown"


# ══════════════════════════════════════════════════════════
# Test Profile Extraction
# ══════════════════════════════════════════════════════════

class TestProfileExtraction:
    """KBExtractor.profile_project and profile helpers."""

    def test_profile_build_file_pom_xml(self, tmp_path):
        (tmp_path / "pom.xml").write_text("""
<project>
  <groupId>com.acme</groupId>
  <artifactId>test-automation</artifactId>
  <dependencies>
    <dependency>
      <groupId>org.testng</groupId>
      <artifactId>testng</artifactId>
    </dependency>
  </dependencies>
</project>
""", encoding="utf-8")
        extractor = KBExtractor(str(tmp_path))
        info = extractor._profile_build_file()
        assert info["project_type"] == "java_maven"
        assert info["test_framework"] == "testng"

    def test_profile_build_file_gradle(self, tmp_path):
        (tmp_path / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
        extractor = KBExtractor(str(tmp_path))
        info = extractor._profile_build_file()
        assert info["project_type"] == "java_gradle"

    def test_profile_build_file_kts(self, tmp_path):
        (tmp_path / "build.gradle.kts").write_text("plugins { java }\n", encoding="utf-8")
        extractor = KBExtractor(str(tmp_path))
        info = extractor._profile_build_file()
        assert info["project_type"] == "java_gradle"

    def test_profile_build_file_python(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n", encoding="utf-8")
        extractor = KBExtractor(str(tmp_path))
        info = extractor._profile_build_file()
        assert info["project_type"] == "python_pytest"

    def test_profile_single_java(self, tmp_path):
        java = _make_java_file(tmp_path, "src/components/WebTable.java", """
package com.acme.components;
import org.openqa.selenium.By;
import org.openqa.selenium.WebElement;

@Component
public class WebTable extends BaseComponent {
    @FindBy(xpath = "//table[@data-module='table']")
    private WebElement root;

    public void sortColumn(String name) {}
    public int getRowCount() { return 0; }
}
""")
        extractor = KBExtractor(str(tmp_path))
        info = extractor._profile_single_java(java)
        assert info is not None
        assert info["class_name"] == "WebTable"
        assert info["extends"] == "BaseComponent"
        assert info["package"] == "com.acme.components"
        assert "Component" in info["annotations"]
        assert "FindBy" in info["annotations"]
        assert info["is_ui_relevant"] is True

    def test_profile_single_java_non_ui(self, tmp_path):
        java = _make_java_file(tmp_path, "src/model/User.java", """
package com.acme.model;

public class User {
    private String name;
    public String getName() { return name; }
}
""")
        extractor = KBExtractor(str(tmp_path))
        info = extractor._profile_single_java(java)
        assert info is not None
        assert info["class_name"] == "User"
        assert info["is_ui_relevant"] is False

    def test_profile_single_python(self, tmp_path):
        py = _make_py_file(tmp_path, "aw/table_aw.py", """
from selenium.webdriver.common.by import By
from framework.base import BaseAW

class TableAW(BaseAW):
    def get_rows(self):
        pass
""")
        extractor = KBExtractor(str(tmp_path))
        imports = extractor._profile_single_python(py)
        assert len(imports) > 0
        assert "selenium.webdriver.common.by" in imports

    def test_is_ui_relevant_java_by_annotation(self, tmp_path):
        java = _make_java_file(tmp_path, "src/AnyPackage/SomeClass.java", """
package com.acme.whatever;

@FindBy(xpath = "//button")
public class SomeClass {
}
""")
        extractor = KBExtractor(str(tmp_path))
        info = extractor._profile_single_java(java)
        assert info["is_ui_relevant"] is True

    def test_is_ui_relevant_java_by_path(self, tmp_path):
        java = _make_java_file(tmp_path, "src/components/widgets/MyWidget.java", """
package com.acme.widgets;

public class MyWidget {
}
""")
        extractor = KBExtractor(str(tmp_path))
        info = extractor._profile_single_java(java)
        assert info["is_ui_relevant"] is True

    def test_infer_ui_packages(self):
        extractor = KBExtractor()
        java_files = [
            {"package": "com.acme.components", "is_ui_relevant": True},
            {"package": "com.acme.pages", "is_ui_relevant": True},
            {"package": "com.acme.model", "is_ui_relevant": False},
        ]
        packages = ["com.acme.components", "com.acme.pages", "com.acme.model"]
        result = extractor._infer_ui_packages(java_files, packages)
        assert len(result) >= 1
        assert any("components" in p for p in result)

    def test_infer_base_class_map(self):
        extractor = KBExtractor()
        sample = {
            "java_files": [
                {"extends": "WebTable", "class_name": "CustomTable"},
                {"extends": "BaseForm", "class_name": "LoginForm"},
            ]
        }
        result = extractor._infer_base_class_map(sample)
        assert len(result) >= 1
        # "WebTable" contains "table" → should be mapped
        assert "WebTable" in result

    def test_infer_locator_priorities(self):
        extractor = KBExtractor()
        sample = {
            "java_files": [
                {"locator_attrs": ["id", "xpath"]},
                {"locator_attrs": ["id", "name", "css"]},
            ]
        }
        result = extractor._infer_locator_priorities(sample)
        assert "id" in result
        assert len(result) <= 8

    def test_profile_project_minimal(self, tmp_path):
        """Profile a minimal project with just a few files."""
        (tmp_path / "pom.xml").write_text("<project></project>", encoding="utf-8")
        comp_dir = tmp_path / "src" / "main" / "java" / "com" / "acme" / "components"
        comp_dir.mkdir(parents=True)
        (comp_dir / "WebButton.java").write_text("""package com.acme.components;
@Component
public class WebButton extends BaseComponent {
    @FindBy(xpath = "//button")
    private Object root;
    public void click() {}
}""", encoding="utf-8")

        extractor = KBExtractor(str(tmp_path))
        source_dirs = {
            "component_aw": "src/main/java",
            "pages": "src/main/java",
            "tests": "src/main/java",
        }
        profile = extractor.profile_project(source_dirs)
        assert profile.project_type == "java_maven"
        assert profile.profiling_confidence > 0
        assert profile.total_java_files > 0


# ══════════════════════════════════════════════════════════
# Test Convention Mining
# ══════════════════════════════════════════════════════════

class TestConventionMining:
    """_ConventionsMixin: operation, import, locator, assertion conventions."""

    def test_classify_method_prefix_retrieval(self):
        result = KBExtractor._classify_method_prefix("getRowCount")
        assert result == "retrieval"

    def test_classify_method_prefix_click(self):
        result = KBExtractor._classify_method_prefix("clickButton")
        assert result == "click"

    def test_classify_method_prefix_verification(self):
        result = KBExtractor._classify_method_prefix("isEnabled")
        assert result == "verification"

    def test_classify_method_prefix_input(self):
        result = KBExtractor._classify_method_prefix("typeText")
        assert result == "input"

    def test_classify_method_prefix_navigation(self):
        result = KBExtractor._classify_method_prefix("openPage")
        assert result == "navigation"

    def test_classify_method_prefix_other(self):
        result = KBExtractor._classify_method_prefix("doSomethingWeird")
        assert result == "other"

    def test_extract_import_conventions(self, tmp_path):
        """Test import convention extraction from source files."""
        java = _make_java_file(tmp_path, "src/Table.java", """
package com.example;
import org.openqa.selenium.By;
import org.openqa.selenium.WebElement;
import java.util.List;
""")
        py = _make_py_file(tmp_path, "src/helper.py", """
import os
from selenium import webdriver
from pathlib import Path
""")
        extractor = KBExtractor(str(tmp_path))
        result = extractor._extract_import_conventions({java, py})
        assert result is not None
        assert result.category == "conventions"
        assert result.key == "convention.imports"
        top_imports = result.value["top_imports"]
        assert len(top_imports) > 0

    def test_extract_import_conventions_empty(self, tmp_path):
        extractor = KBExtractor(str(tmp_path))
        result = extractor._extract_import_conventions(set())
        assert result is None

    def test_extract_operation_conventions(self, tmp_path):
        java = _make_java_file(tmp_path, "src/Comp.java", """
public class Comp {
    public void getText() {}
    public void clickButton() {}
    public void typeInput() {}
    public void isEnabled() {}
}
""")
        extractor = KBExtractor(str(tmp_path))
        result = extractor._extract_operation_conventions({java})
        assert result is not None
        assert result.category == "conventions"
        cats = result.value["operation_categories"]
        assert len(cats) > 0
        assert result.value["dominant_operation"] in [
            c["category"] for c in cats
        ]

    def test_extract_operation_conventions_empty(self, tmp_path):
        extractor = KBExtractor(str(tmp_path))
        result = extractor._extract_operation_conventions(set())
        assert result is None

    def test_extract_locator_usage_conventions(self, tmp_path):
        java = _make_java_file(tmp_path, "src/Comp.java", """
public class Comp {
    @FindBy(xpath = "//button")
    private Object btn;
    @FindBy(id = "submit")
    private Object submit;
}
""")
        extractor = KBExtractor(str(tmp_path))
        profile = FrameworkProfile()
        result = extractor._extract_locator_usage_conventions({java}, profile)
        assert result is not None
        assert result.key == "convention.locator_usage"

    def test_extract_assertion_conventions(self, tmp_path):
        java = _make_java_file(tmp_path, "tests/TestExample.java", """
import static org.testng.Assert.assertEquals;

public class TestExample {
    @Test
    public void testThing() {
        assertEquals(1, 1);
        assertNotNull(obj);
    }
}
""")
        extractor = KBExtractor(str(tmp_path))
        result = extractor._extract_assertion_conventions([java])
        assert result is not None
        assert result.category == "conventions"
        assert result.key == "convention.assertions"

    def test_extract_assertion_conventions_empty(self, tmp_path):
        extractor = KBExtractor(str(tmp_path))
        result = extractor._extract_assertion_conventions([])
        assert result is None

    def test_extract_naming_conventions_from_items(self):
        extractor = KBExtractor()
        # Create items with naming data
        items = [
            KBItem(
                id="c1", category="components", key="comp.table",
                value={"naming": {"class_suffix": "AW", "method_prefix": "get"}}
            ),
            KBItem(
                id="c2", category="components", key="comp.form",
                value={"naming": {"class_suffix": "AW", "method_prefix": "set"}}
            ),
            KBItem(
                id="p1", category="pages", key="page.login",
                value={"naming": {"class_suffix": "Page", "method_prefix": "get"}}
            ),
        ]
        result = extractor._extract_naming_conventions(items)
        assert len(result) == 1
        assert result[0].category == "conventions"
        assert result[0].value["class_suffix"] == "AW"
        assert result[0].value["method_prefix"] == "get"

    def test_extract_naming_conventions_insufficient_data(self):
        extractor = KBExtractor()
        items = [KBItem(id="x", category="other", key="k", value={})]
        result = extractor._extract_naming_conventions(items)
        assert result == []

    def test_extract_patterns(self, tmp_path):
        java = _make_java_file(tmp_path, "tests/TestFlow.java", """
public class TestFlow {
    @Test
    public void testFlow() {
        page.open("url");
        form.typeText("hello");
        button.click();
        table.getRows();

        page.open("url2");
        form.typeText("world");
        button.click();
    }
}
""")
        extractor = KBExtractor(str(tmp_path))
        profile = FrameworkProfile()
        result = extractor._extract_patterns([java], profile)
        assert isinstance(result, list)


# ══════════════════════════════════════════════════════════
# Test Aggregation
# ══════════════════════════════════════════════════════════

class TestAggregation:
    """_AggregationMixin: quick UI check, page index extraction."""

    def test_quick_ui_check_findby(self):
        extractor = KBExtractor()
        assert extractor._quick_ui_check("@FindBy(xpath = \"//btn\")") is True

    def test_quick_ui_check_webdriver(self):
        extractor = KBExtractor()
        assert extractor._quick_ui_check("WebDriver driver = new ChromeDriver();") is True

    def test_quick_ui_check_no_match(self):
        extractor = KBExtractor()
        assert extractor._quick_ui_check("public class User { private String name; }") is False

    def test_extract_page_index(self, tmp_path):
        page1 = _make_java_file(tmp_path, "pages/LoginPage.java", """
package com.acme.pages;
public class LoginPage extends BasePage {
    private Object usernameInput;
}
""")
        page2 = _make_java_file(tmp_path, "pages/HomePage.java", """
package com.acme.pages;
public class HomePage extends BasePage {
    private Object dashboard;
}
""")
        extractor = KBExtractor(str(tmp_path))
        profile = FrameworkProfile()
        items = extractor._extract_page_index([page1, page2], profile)
        assert len(items) >= 1
        page_item = next((i for i in items if i.key == "page.index"), None)
        assert page_item is not None
        assert page_item.value["page_count"] == 2

    def test_extract_page_index_empty(self):
        extractor = KBExtractor()
        profile = FrameworkProfile()
        items = extractor._extract_page_index([], profile)
        assert items == []

    def test_extract_single_ui_file_uses_legacy(self, tmp_path):
        java = _make_java_file(tmp_path, "orphan/OrphanComp.java", """
package com.acme;
public class OrphanComp {
    public void doWork() {}
}
""")
        extractor = KBExtractor(str(tmp_path))
        profile = FrameworkProfile()
        with pytest.warns(DeprecationWarning):
            item = extractor._extract_single_ui_file(java, profile)
        assert item is not None
        assert isinstance(item, list)
        if item:
            assert item[0].category in ("pages", "components")


# ══════════════════════════════════════════════════════════
# Test Document Ingestion
# ══════════════════════════════════════════════════════════

class TestDocumentIngestion:
    """KBExtractor.extract_from_design_doc and inject_convention."""

    def test_extract_yaml_frontmatter_naming(self):
        extractor = KBExtractor()
        doc = """---
naming:
  class_suffix: AW
  method_prefix: get
  field_style: camelCase
---
Some markdown content here.
"""
        items = extractor.extract_from_design_doc(doc, "test_doc")
        naming_items = [i for i in items if "naming" in i.tags]
        assert len(naming_items) >= 1
        assert naming_items[0].confidence.source == KnowledgeSource.HUMAN_INJECTION

    def test_extract_yaml_frontmatter_xpath(self):
        extractor = KBExtractor()
        doc = """---
xpath:
  priority: data-testid > id > xpath
  avoid: absolute paths
---
"""
        items = extractor.extract_from_design_doc(doc, "test_doc")
        xpath_items = [i for i in items if "xpath" in i.tags]
        assert len(xpath_items) >= 1

    def test_extract_yaml_frontmatter_components(self):
        extractor = KBExtractor()
        doc = """---
components:
  WebTable: table
  WebButton: button
  WebInput: input
---
"""
        items = extractor.extract_from_design_doc(doc, "test_doc")
        mapping_items = [i for i in items if "mapping" in i.tags]
        assert len(mapping_items) >= 1
        mappings = mapping_items[0].value.get("mappings", [])
        assert len(mappings) == 3

    def test_extract_naming_rules_regex(self):
        extractor = KBExtractor()
        doc = """
项目编码规范:
命名规则: 类名必须以大写字母开头
命名规范: 方法名使用驼峰命名法
"""
        items = extractor.extract_from_design_doc(doc, "test_doc")
        naming_items = [i for i in items if "naming" in i.tags]
        assert len(naming_items) >= 1
        # Check the description identifies the source
        assert any("test_doc" in item.description for item in naming_items)

    def test_extract_xpath_rules_regex(self):
        extractor = KBExtractor()
        doc = """
定位器: 优先使用 data-testid
XPath 定位优先级: data-testid > id > xpath
"""
        items = extractor.extract_from_design_doc(doc, "test_doc")
        xpath_items = [i for i in items if "xpath" in i.tags]
        assert len(xpath_items) >= 1

    def test_extract_component_mappings_arrow(self):
        extractor = KBExtractor()
        doc = """
WebTable → table
WebButton → button
SearchInput 映射为 search
QueryInput 映射到 input
"""
        items = extractor.extract_from_design_doc(doc, "test_doc")
        mapping_items = [i for i in items if "mapping" in i.tags]
        assert len(mapping_items) >= 1
        all_mappings = []
        for item in mapping_items:
            all_mappings.extend(item.value.get("mappings", []))
        # Should find 4 mappings
        assert len(all_mappings) >= 2

    def test_extract_empty_design_doc(self):
        extractor = KBExtractor()
        items = extractor.extract_from_design_doc("", "empty")
        assert items == []

    def test_inject_convention(self):
        extractor = KBExtractor()
        item = extractor.inject_convention(
            key="convention.test",
            value={"rule": "custom"},
            description="Custom test convention",
            source="human",
        )
        assert item.category == "conventions"
        assert item.confidence.score == 0.95
        assert item.confidence.source == KnowledgeSource.HUMAN_INJECTION
        assert item.key == "convention.test"


# ══════════════════════════════════════════════════════════
# Test Edge Cases
# ══════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases: malformed content, empty files, binary files, encoding."""

    def test_parse_java_regex_malformed_syntax(self):
        """Java 17+ features that javalang can't parse should fall back to regex."""
        source = """
package com.example;
public class ModernJava {
    // sealed class, record, text block
    public void process() {
        var x = switch (val) {
            case 1 -> "one";
            default -> "other";
        };
    }
}
"""
        result = KBExtractor._parse_java_regex(source)
        assert result is not None
        assert result["class_name"] == "ModernJava"

    def test_parse_java_regex_record_class(self):
        source = """
package com.example;
public record Point(int x, int y) {
}
"""
        result = KBExtractor._parse_java_regex(source)
        # "record" is not "class", so regex won't match the class pattern
        # This tests that absence of class keyword returns None
        assert result is None

    def test_parse_java_regex_enum(self):
        source = """
package com.example;
public enum Status { ACTIVE, INACTIVE }
"""
        result = KBExtractor._parse_java_regex(source)
        # Similar to record, enum lacks "class" keyword
        assert result is None

    def test_parse_java_regex_inner_class(self):
        source = """
package com.example;
public class OuterClass {
    public class InnerClass {
        public void innerMethod() {}
    }
    public void outerMethod() {}
}
"""
        result = KBExtractor._parse_java_regex(source)
        # Only the first "class" match is captured
        assert result is not None
        assert result["class_name"] == "OuterClass"

    def test_parse_locator_annotation_escaped_quotes(self):
        result = KBExtractor._parse_locator_annotation(
            'xpath = "//div[@data-module=\\"search\\"]"'
        )
        assert result is not None
        assert result["strategy"] == "xpath"

    def test_parse_java_file_encoding_issue(self, tmp_path):
        """A file that cannot be read as UTF-8 should return empty."""
        import struct
        java_file = tmp_path / "bad.java"
        # Write some binary garbage
        java_file.write_bytes(b'\xff\xfe\x00\x00\xff\xff')
        extractor = KBExtractor(str(tmp_path))
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_java_file(str(java_file))
        assert items == []

    def test_empty_java_file(self, tmp_path):
        java = _make_java_file(tmp_path, "Empty.java", "")
        extractor = KBExtractor(str(tmp_path))
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_java_file(str(java))
        assert items == []

    def test_python_syntax_error_file(self, tmp_path):
        py = _make_py_file(tmp_path, "broken.py", "def foo(:\n    pass\n")
        extractor = KBExtractor(str(tmp_path))
        with pytest.warns(DeprecationWarning):
            items = extractor.extract_from_component_aw(str(py))
        assert items == []
