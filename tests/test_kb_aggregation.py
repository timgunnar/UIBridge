"""Tests for two-phase KB aggregation extraction.

Covers: FrameworkProfile, profile persistence, component family grouping,
aggregated extraction, aggregated conventions, two-phase integration,
and backward compatibility with legacy extractors.
"""

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from uibridge.kb.item import KBItem, Confidence, KnowledgeSource
from uibridge.kb import FrameworkProfile, ProfileField
from uibridge.kb.store import KBStore
from uibridge.kb.extractor import KBExtractor
from uibridge.kb.manager import KBManager


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════

def _create_java_project(root: Path):
    """Create a mock Java Maven project with UI and non-UI files."""
    # pom.xml
    (root / "pom.xml").write_text("""<project>
  <groupId>com.acme</groupId>
  <artifactId>automation</artifactId>
  <version>1.0</version>
</project>""", encoding="utf-8")

    # UI component files
    comp_dir = root / "src" / "main" / "java" / "com" / "acme" / "components"
    comp_dir.mkdir(parents=True)

    (comp_dir / "WebTable.java").write_text("""package com.acme.components;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.By;

public class WebTable extends BaseComponent {
    @FindBy(xpath = "//table[@data-module='table']")
    private WebElement root;

    public void sortColumn(String name) {}
    public int getRowCount() { return 0; }
    public String getCellText(int row, int col) { return ""; }
}""", encoding="utf-8")

    (comp_dir / "CustomTable.java").write_text("""package com.acme.components;
import org.openqa.selenium.WebElement;

public class CustomTable extends WebTable {
    public void filterBy(String criteria) {}
    public void exportToCsv() {}
}""", encoding="utf-8")

    (comp_dir / "WebButton.java").write_text("""package com.acme.components;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.By;

public class WebButton extends BaseComponent {
    @FindBy(xpath = "//button[@data-module='button']")
    private WebElement root;

    public void click() {}
    public boolean isEnabled() { return true; }
}""", encoding="utf-8")

    (comp_dir / "WebInput.java").write_text("""package com.acme.components;
import org.openqa.selenium.WebElement;

public class WebInput extends BaseComponent {
    @FindBy(xpath = "//input[@data-module='input']")
    private WebElement root;

    public void type(String text) {}
    public void clear() {}
    public String getValue() { return ""; }
}""", encoding="utf-8")

    (comp_dir / "WebDropdown.java").write_text("""package com.acme.components;
import org.openqa.selenium.WebElement;

public class WebDropdown extends BaseComponent {
    @FindBy(xpath = "//select[@data-module='dropdown']")
    private WebElement root;

    public void select(String option) {}
    public String getSelected() { return ""; }
}""", encoding="utf-8")

    # Page files
    page_dir = root / "src" / "main" / "java" / "com" / "acme" / "pages"
    page_dir.mkdir(parents=True)

    (page_dir / "LoginPage.java").write_text("""package com.acme.pages;
import com.acme.components.*;

public class LoginPage extends BasePage {
    private WebInput usernameInput;
    private WebInput passwordInput;
    private WebButton loginButton;

    public void login(String user, String pass) {}
}""", encoding="utf-8")

    (page_dir / "UserManagementPage.java").write_text("""package com.acme.pages;
import com.acme.components.*;

public class UserManagementPage extends BasePage {
    private WebTable userTable;
    private WebButton addUserButton;
    private WebDropdown roleDropdown;

    public void addUser(String name) {}
    public void deleteUser(String name) {}
}""", encoding="utf-8")

    # Non-UI files (model, service, dto — should be filtered out)
    model_dir = root / "src" / "main" / "java" / "com" / "acme" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "User.java").write_text("""package com.acme.model;
public class User {
    private String name;
    private String email;
    public String getName() { return name; }
}""", encoding="utf-8")

    (model_dir / "Role.java").write_text("""package com.acme.model;
public class Role {
    private String roleName;
}""", encoding="utf-8")

    service_dir = root / "src" / "main" / "java" / "com" / "acme" / "service"
    service_dir.mkdir(parents=True)
    (service_dir / "UserService.java").write_text("""package com.acme.service;
public class UserService {
    public void createUser(String name) {}
}""", encoding="utf-8")

    dto_dir = root / "src" / "main" / "java" / "com" / "acme" / "dto"
    dto_dir.mkdir(parents=True)
    (dto_dir / "UserDTO.java").write_text("""package com.acme.dto;
public class UserDTO {
    public String name;
    public String email;
}""", encoding="utf-8")

    # Test files
    test_dir = root / "src" / "test" / "java" / "com" / "acme" / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "TestUserLogin.java").write_text("""package com.acme.tests;
import org.testng.annotations.Test;
import com.acme.pages.*;

public class TestUserLogin {
    @Test
    public void testValidLogin() {
        LoginPage page = new LoginPage();
        page.login("admin", "pass");
    }
}""", encoding="utf-8")

    return root


@pytest.fixture
def java_project(tmp_path):
    """Create a temporary Java project for testing."""
    return _create_java_project(tmp_path)


@pytest.fixture
def kb_store(tmp_path):
    return KBStore(str(tmp_path))


@pytest.fixture
def extractor(java_project):
    return KBExtractor(str(java_project))


# ══════════════════════════════════════════════════════════
# TestComponentFamilyGrouping
# ══════════════════════════════════════════════════════════

class TestComponentFamilyGrouping:
    """KBExtractor: _group_by_component_family."""

    def test_groups_by_keyword_in_filename(self, extractor, java_project):
        comp_dir = java_project / "src" / "main" / "java" / "com" / "acme" / "components"
        files = list(comp_dir.glob("*.java"))
        profile = FrameworkProfile(
            base_classes=ProfileField(value={})
        )
        families = extractor._group_by_component_family(files, profile)
        assert "table" in families
        assert "button" in families
        assert "input" in families
        assert "dropdown" in families
        # WebTable + CustomTable should both be in "table" family
        table_names = [f.stem for f in families["table"]]
        assert "WebTable" in table_names
        assert "CustomTable" in table_names

    def test_groups_by_base_class_mapping(self, extractor, java_project):
        profile = FrameworkProfile(
            base_classes=ProfileField(value={"BaseComponent": "component"})
        )
        comp_dir = java_project / "src" / "main" / "java" / "com" / "acme" / "components"
        files = list(comp_dir.glob("*.java"))
        families = extractor._group_by_component_family(files, profile)
        # Files still group by keyword since keyword takes priority
        assert "table" in families

    def test_extract_component_family_produces_kbitem(self, extractor, java_project):
        comp_dir = java_project / "src" / "main" / "java" / "com" / "acme" / "components"
        table_files = [comp_dir / "WebTable.java", comp_dir / "CustomTable.java"]
        profile = FrameworkProfile(
            base_classes=ProfileField(value={"WebTable": "table"})
        )
        item = extractor._extract_component_family("table", table_files, profile)
        assert item is not None
        assert item.category == "components"
        assert "table" in item.key
        assert item.aggregation == "component_family"
        assert len(item.source_files) == 2


# ══════════════════════════════════════════════════════════
# TestAggregatedExtraction
# ══════════════════════════════════════════════════════════

class TestAggregatedExtraction:
    """KBExtractor: extract_aggregated filters non-UI and aggregates."""

    def test_filters_non_ui_files(self, extractor, java_project):
        profile = FrameworkProfile(
            ui_packages=ProfileField(value=["com/acme/components", "com/acme/pages"]),
            source_dirs=ProfileField(value={
                "pages": "src/main/java",
                "tests": "src/test/java",
            }),
        )
        all_java = list((java_project / "src" / "main" / "java").glob("**/*.java"))
        ui_files = extractor._filter_ui_files(all_java, profile)
        # model, service, dto files should be filtered out
        ui_paths = [str(f) for f in ui_files]
        assert not any("model" in p for p in ui_paths)
        assert not any("service" in p for p in ui_paths)
        assert not any("dto" in p for p in ui_paths)
        # UI files should remain
        assert any("components" in str(f) for f in ui_files)
        assert any("pages" in str(f) for f in ui_files)

    def test_extract_aggregated_output(self, extractor, java_project):
        profile = FrameworkProfile(
            project_type="java_maven",
            ui_packages=ProfileField(value=["com/acme/components", "com/acme/pages"]),
            base_classes=ProfileField(value={"WebTable": "table", "WebButton": "button"}),
            source_dirs=ProfileField(value={
                "pages": "src/main/java",
                "tests": "src/test/java",
            }),
            profiling_confidence=0.7,
        )
        items = extractor.extract_aggregated(profile)
        assert len(items) > 0
        # Should have component families
        comp_items = [i for i in items if i.category == "components"]
        assert len(comp_items) > 0
        # Should have aggregation markers
        aggregated = [i for i in items if i.aggregation]
        assert len(aggregated) > 0

    def test_extract_aggregated_item_count_reasonable(self, extractor, java_project):
        """Output should be far less than total file count."""
        profile = FrameworkProfile(
            project_type="java_maven",
            ui_packages=ProfileField(value=["com/acme/components", "com/acme/pages"]),
            base_classes=ProfileField(value={}),
            source_dirs=ProfileField(value={
                "pages": "src/main/java",
                "tests": "src/test/java",
            }),
            profiling_confidence=0.7,
        )
        items = extractor.extract_aggregated(profile)
        total_java = len(list((java_project / "src").glob("**/*.java")))
        # Items should be much fewer than total files
        assert len(items) < total_java


# ══════════════════════════════════════════════════════════
# TestAggregatedConventions
# ══════════════════════════════════════════════════════════

class TestAggregatedConventions:
    """KBExtractor: _extract_aggregated_conventions."""

    def test_generates_convention_items(self, extractor, java_project):
        profile = FrameworkProfile(
            project_type="java_maven",
            ui_packages=ProfileField(value=["com/acme/components", "com/acme/pages"]),
            base_classes=ProfileField(value={"WebTable": "table"}),
            locator_priorities=ProfileField(value=["data-module", "xpath"]),
            naming_conventions=ProfileField(value={"prefix": "Web"}),
            source_dirs=ProfileField(value={
                "pages": "src/main/java",
                "tests": "src/test/java",
            }),
            profiling_confidence=0.7,
        )
        # Generate some component items first
        items = extractor.extract_aggregated(profile)
        convention_items = [i for i in items if i.category == "conventions"]
        # Should produce convention entries
        assert len(convention_items) >= 1
        # Conventions should have aggregation marker
        for item in convention_items:
            assert item.aggregation == "convention_batch"


# ══════════════════════════════════════════════════════════
# TestBackwardCompatibility
# ══════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """Legacy extractor and old YAML format still work."""

    def test_legacy_extract_from_java_file(self, extractor, java_project):
        comp_file = java_project / "src" / "main" / "java" / "com" / "acme" / "components" / "WebTable.java"
        items = extractor.extract_from_java_file(str(comp_file))
        assert len(items) > 0
        # Old-style items have no aggregation
        for item in items:
            assert item.aggregation == ""

    def test_legacy_extract_from_component_aw(self, extractor, java_project):
        # extract_from_component_aw is for Python files, create a minimal one
        py_dir = java_project / "aw"
        py_dir.mkdir()
        (py_dir / "table_aw.py").write_text("""class TableAW:
    \"\"\"Table component wrapper.\"\"\"
    def get_row_count(self):
        return self.driver.find_elements_by_xpath("//tr")

    def click_cell(self, row, col):
        pass
""", encoding="utf-8")
        items = extractor.extract_from_component_aw(str(py_dir / "table_aw.py"))
        # May produce 0 items if the Python extractor needs more structure;
        # the key test is that the wrapper doesn't crash
        assert isinstance(items, list)

    def test_old_kbitem_without_aggregation_loads(self):
        """KBItem.from_dict works without aggregation/source_files fields."""
        d = {
            "id": "old_item_001",
            "category": "components",
            "key": "component.table",
            "value": {"class_name": "WebTable"},
            "confidence": {"score": 0.7, "source": "static_analysis"},
            "description": "Table component",
            "tags": ["table"],
        }
        item = KBItem.from_dict(d)
        assert item.id == "old_item_001"
        assert item.aggregation == ""
        assert item.source_files == []

    def test_new_kbitem_with_aggregation_serializes(self):
        """KBItem with aggregation and source_files round-trips correctly."""
        item = KBItem(
            id="agg_001",
            category="components",
            key="component_family.table",
            value={"classes": ["WebTable", "CustomTable"]},
            description="Table component family",
            aggregation="component_family",
            source_files=["WebTable.java", "CustomTable.java"],
        )
        d = item.to_dict()
        assert d["aggregation"] == "component_family"
        assert d["source_files"] == ["WebTable.java", "CustomTable.java"]

        restored = KBItem.from_dict(d)
        assert restored.aggregation == "component_family"
        assert restored.source_files == ["WebTable.java", "CustomTable.java"]

    def test_merge_or_save_new_item(self, kb_store):
        item = KBItem(
            id="merge_test_001",
            category="components",
            key="component.merge_test",
            value={"methods": ["click"]},
        )
        path, merged = kb_store.merge_or_save(item)
        assert not merged
        assert Path(path).exists()

    def test_merge_or_save_existing_key(self, kb_store):
        item1 = KBItem(
            id="merge_test_002",
            category="components",
            key="component.merge_target",
            value={"methods": ["click"]},
            confidence=Confidence(score=0.6, source=KnowledgeSource.STATIC_ANALYSIS),
        )
        kb_store.save(item1)

        item2 = KBItem(
            id="merge_test_003",
            category="components",
            key="component.merge_target",
            value={"methods": ["type"], "extra": True},
            confidence=Confidence(score=0.8, source=KnowledgeSource.RUNTIME_ANALYSIS),
        )
        path, merged = kb_store.merge_or_save(item2)
        assert merged
        # Verify merge result
        loaded = kb_store.get("components", "merge_test_002")
        assert loaded is not None
        assert "type" in loaded.value["methods"] or "extra" in loaded.value
        assert loaded.confidence.score >= 0.8


# ══════════════════════════════════════════════════════════
# TestFreshnessMonitor
# ══════════════════════════════════════════════════════════

class TestFreshnessMonitor:
    """FreshnessMonitor: Java/Python source parsing and file-not-found handling."""

    def test_parse_java_component_methods(self):
        from uibridge.kb.freshness import FreshnessMonitor
        java_src = """
package com.acme.components;
import org.openqa.selenium.By;
import org.openqa.selenium.WebElement;

public class WebTable extends BaseComponent {
    @FindBy(xpath = "//table[@data-module='table']")
    private WebElement root;

    @FindBy(css = ".table-header")
    private WebElement header;

    public void sortColumn(String name) {}
    public int getRowCount() { return 0; }
    public String getCellText(int row, int col) { return ""; }
}
"""
        methods, locators, base_class = FreshnessMonitor._parse_java_component(java_src)
        assert base_class == "BaseComponent"
        assert "void sortColumn(String name)" in methods
        assert "int getRowCount()" in methods
        assert "String getCellText(int row, int col)" in methods
        assert len(methods) == 3
        assert locators.get("xpath") == "//table[@data-module='table']"
        assert locators.get("css") == ".table-header"

    def test_parse_python_component_methods(self):
        from uibridge.kb.freshness import FreshnessMonitor
        py_src = '''
from selenium.webdriver.common.by import By

class TableAW(BaseAW):
    """Table component wrapper."""

    def get_row_count(self):
        return len(self.driver.find_elements(By.XPATH, "//tr"))

    def click_cell(self, row, col):
        pass

    def _private_helper(self):
        pass
'''
        methods, locators, base_class = FreshnessMonitor._parse_python_component(py_src)
        assert base_class == "BaseAW"
        assert "def get_row_count(self)" in methods
        assert "def click_cell(self, row, col)" in methods
        # Private methods (starting with _) should be filtered out
        assert not any("private" in m for m in methods)
        assert len(methods) == 2

    def test_parse_java_component_empty(self):
        from uibridge.kb.freshness import FreshnessMonitor
        methods, locators, base_class = FreshnessMonitor._parse_java_component("")
        assert methods == []
        assert locators == {}
        assert base_class == ""

    def test_analyze_current_state_file_not_found(self):
        from uibridge.kb.freshness import FreshnessMonitor
        import tempfile
        td = tempfile.mkdtemp()
        try:
            kb_store = KBStore(td)
            monitor = FreshnessMonitor(kb_store, project_root=td)
            snapshot = {"source_file": "nonexistent/Component.java"}
            result = monitor._analyze_current_state("TestComp", snapshot)
            assert result is None
        finally:
            shutil.rmtree(td, ignore_errors=True)
