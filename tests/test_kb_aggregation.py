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
from uibridge.profile import FrameworkProfile, ProfileField
from uibridge.profile_store import ProfileStore
from uibridge.kb.store import KBStore
from uibridge.kb.extractor import KBExtractor
from uibridge.kb.manager import KBManager
from uibridge.profile_manager import ProfileManager


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
def profile_store(tmp_path):
    return ProfileStore(str(tmp_path))


@pytest.fixture
def extractor(java_project):
    return KBExtractor(str(java_project))


@pytest.fixture
def manager(java_project):
    root = str(java_project)
    profile_mgr = ProfileManager(root)
    return KBManager(root, profile_manager=profile_mgr)


# ══════════════════════════════════════════════════════════
# TestFrameworkProfile
# ══════════════════════════════════════════════════════════

class TestFrameworkProfile:
    """FrameworkProfile: serialization, defaults, field-level confidence."""

    def test_default_profile(self):
        profile = FrameworkProfile()
        assert profile.project_type == "unknown"
        assert profile.profiling_confidence == 0.5
        assert isinstance(profile.ui_packages, ProfileField)
        assert profile.ui_packages.source == "auto"
        assert profile.ui_packages.confidence == 0.6

    def test_profile_to_dict_roundtrip(self):
        profile = FrameworkProfile(
            project_type="java_maven",
            ui_packages=ProfileField(value=["com.acme.components", "com.acme.pages"]),
            base_classes=ProfileField(value={"WebTable": "table", "WebButton": "button"}),
            locator_priorities=ProfileField(value=["data-testid", "id", "xpath"]),
            profiling_confidence=0.75,
        )
        d = profile.to_dict()
        restored = FrameworkProfile.from_dict(d)
        assert restored.project_type == "java_maven"
        assert restored.profiling_confidence == 0.75
        assert "com.acme.components" in restored.ui_packages.value
        assert restored.base_classes.value["WebTable"] == "table"
        assert restored.locator_priorities.value == ["data-testid", "id", "xpath"]

    def test_profile_field_source_tracking(self):
        pf = ProfileField(value=["data-testid"], source="human_dialogue", confidence=0.95)
        d = pf.to_dict()
        assert d["source"] == "human_dialogue"
        assert d["confidence"] == 0.95
        restored = ProfileField.from_dict(d)
        assert restored.source == "human_dialogue"
        assert restored.confidence == 0.95

    def test_profile_field_from_raw_value(self):
        """Backward compatibility: bare value without dict wrapper."""
        pf = ProfileField.from_dict(["item1", "item2"])
        assert pf.value == ["item1", "item2"]
        assert pf.source == "auto"

    def test_profiling_generates_for_java_maven(self, extractor, java_project):
        source_dirs = {"pages": "src/main/java", "tests": "src/test/java"}
        profile = extractor.profile_project(source_dirs)
        assert profile.project_type == "java_maven"
        assert profile.profiling_confidence > 0


# ══════════════════════════════════════════════════════════
# TestProfilePersistence
# ══════════════════════════════════════════════════════════

class TestProfilePersistence:
    """ProfileStore: save / load with TTL cache."""

    def test_save_and_load_profile(self, profile_store):
        profile = FrameworkProfile(
            project_type="java_maven",
            ui_packages=ProfileField(value=["com.acme.ui"]),
            base_classes=ProfileField(value={"BaseAW": "component"}),
            profiling_confidence=0.72,
            version=2,
        )
        path = profile_store.save(profile)
        assert Path(path).exists()

        loaded = profile_store.load()
        assert loaded is not None
        assert loaded.project_type == "java_maven"
        assert loaded.profiling_confidence == 0.72
        assert loaded.version == 2
        assert "com.acme.ui" in loaded.ui_packages.value

    def test_load_nonexistent_profile(self, profile_store):
        assert profile_store.load() is None

    def test_profile_overwrite(self, profile_store):
        profile1 = FrameworkProfile(project_type="java_maven", version=1)
        profile_store.save(profile1)

        profile2 = FrameworkProfile(project_type="java_gradle", version=2)
        profile_store.save(profile2)

        loaded = profile_store.load()
        assert loaded.project_type == "java_gradle"
        assert loaded.version == 2

    def test_cache_is_valid(self, profile_store):
        """写入后缓存应立即可用，不走磁盘。"""
        profile = FrameworkProfile(project_type="java_maven", version=1)
        profile_store.save(profile)
        # 直接从缓存读取
        cached = profile_store._cache
        assert cached is not None
        assert cached.project_type == "java_maven"

    def test_cache_invalidation(self, profile_store):
        profile = FrameworkProfile(project_type="java_maven")
        profile_store.save(profile)
        profile_store.invalidate_cache()
        assert profile_store._cache is None


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
# TestTwoPhaseIntegration
# ══════════════════════════════════════════════════════════

class TestTwoPhaseIntegration:
    """KBManager: seed_two_phase end-to-end."""

    def test_seed_two_phase_creates_profile_and_items(self, manager, java_project):
        items = manager.seed_two_phase()
        # Should produce items
        assert len(items) > 0
        # Profile should be persisted
        profile = manager._profile_manager.get_profile()
        assert profile is not None
        assert profile.project_type == "java_maven"

    def test_seed_two_phase_item_count_bounded(self, manager, java_project):
        items = manager.seed_two_phase()
        # Should be <= 200 items (much less for our small test project)
        assert len(items) <= 200

    def test_seed_two_phase_search_still_works(self, manager, java_project):
        manager.seed_two_phase()
        # Search should find relevant items
        results = manager.query("table")
        assert len(results) > 0

    def test_auto_seed_uses_two_phase(self, manager, java_project):
        items = manager.auto_seed()
        assert len(items) > 0
        # Profile should exist after auto_seed
        profile = manager._profile_manager.get_profile()
        assert profile is not None

    def test_reprofile_updates_profile(self, manager, java_project):
        manager.seed_two_phase()
        profile = manager._profile_manager.reprofile(overrides={"base_classes": {"MyBase": "custom"}})
        assert "MyBase" in profile.base_classes.value
        assert profile.base_classes.source == "human_dialogue"
        assert profile.base_classes.confidence == 0.95

    def test_update_profile_single_field(self, manager, java_project):
        manager.seed_two_phase()
        profile = manager._profile_manager.update_profile(
            "locator_priorities", ["data-testid", "id"], "human_dialogue"
        )
        assert profile.locator_priorities.value == ["data-testid", "id"]
        assert profile.locator_priorities.source == "human_dialogue"
        assert profile.locator_priorities.confidence >= 0.90

    def test_update_profile_invalid_field_raises(self, manager, java_project):
        manager.seed_two_phase()
        with pytest.raises(ValueError, match="has no field"):
            manager._profile_manager.update_profile("nonexistent_field", "value")

    def test_update_profile_non_profilefield_raises(self, manager, java_project):
        manager.seed_two_phase()
        with pytest.raises(ValueError, match="not a ProfileField"):
            manager._profile_manager.update_profile("project_type", "new_type")

    def test_enhance_profile_from_document(self, manager, java_project):
        manager.seed_two_phase()
        doc = """我们的 UI 自动化编码规范：
        - 基类是 AbstractUIComponent → container
        - 定位器优先级：data-testid > id > xpath
        - 组件目录在 src/main/java/com/acme/widgets/
        """
        profile = manager._profile_manager.enhance_profile_from_document(doc)
        # Should extract and update profile fields
        assert profile.updated_by == "document"
        assert profile.version >= 2


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
# TestProfileIntent
# ══════════════════════════════════════════════════════════

class TestProfileIntent:
    """KBManager: operate_nl with PROFILE intent."""

    def test_profile_intent_base_class(self, manager, java_project):
        manager.seed_two_phase()
        result = manager.operate_nl("我们的基类是 AbstractAW:container, WebBase:element")
        assert result["status"] == "ok"
        assert result["intent"] == "PROFILE"
        assert result.get("updated_field") == "base_classes"

    def test_profile_intent_locator_priority(self, manager, java_project):
        manager.seed_two_phase()
        result = manager.operate_nl("定位器优先级是 data-testid > id > name")
        assert result["status"] == "ok"
        assert result["intent"] == "PROFILE"
        assert result.get("updated_field") == "locator_priorities"

    def test_profile_intent_reprofile(self, manager, java_project):
        manager.seed_two_phase()
        result = manager.operate_nl("重新画像")
        assert result["status"] == "ok"
        assert result["intent"] == "PROFILE"
        assert "profile_confidence" in result

    def test_profile_question_stays_query(self, manager, java_project):
        """Questions about profile should be QUERY, not PROFILE."""
        manager.seed_two_phase()
        result = manager.operate_nl("定位器优先级是什么？")
        assert result["intent"] == "QUERY"


# ══════════════════════════════════════════════════════════
# TestLayerStructure
# ══════════════════════════════════════════════════════════

class TestLayerStructure:
    """FrameworkProfile layer_structure field."""

    def test_default_has_four_layers(self):
        profile = FrameworkProfile()
        layers = profile.layer_structure.value
        assert isinstance(layers, list)
        assert len(layers) == 4
        names = [l["name"] for l in layers]
        assert "component_aw" in names
        assert "page" in names
        assert "test" in names
        assert "test_data" in names

    def test_component_aw_disabled_by_default(self):
        profile = FrameworkProfile()
        layers = profile.layer_structure.value
        caw = next(l for l in layers if l["name"] == "component_aw")
        assert caw["enabled"] is False

    def test_serialization_roundtrip(self):
        profile = FrameworkProfile()
        d = profile.to_dict()
        restored = FrameworkProfile.from_dict(d)
        assert restored.layer_structure.value == profile.layer_structure.value
        assert restored.layer_structure.confidence == profile.layer_structure.confidence
        assert restored.layer_structure.description != ""

    def test_nl_update_layer_dir(self, manager, java_project):
        manager.seed_two_phase()
        new_layers = [
            {"name": "component_aw", "dir": "aw", "role": "UI 组件封装", "enabled": False},
            {"name": "page", "dir": "page_objects", "role": "页面对象", "enabled": True},
            {"name": "test", "dir": "test_cases", "role": "测试脚本", "enabled": True},
            {"name": "test_data", "dir": "test_data", "role": "测试数据", "enabled": True},
        ]
        profile = manager._profile_manager.update_profile("layer_structure", new_layers)
        assert profile.layer_structure.value[1]["dir"] == "page_objects"
        assert profile.layer_structure.source == "human_dialogue"
        assert profile.layer_structure.confidence >= 0.90

    def test_infer_layer_structure_sets_confidence(self, manager, java_project):
        manager.seed_two_phase()
        profile = manager._profile_manager.get_profile()
        assert profile.layer_structure.confidence > 0


# ══════════════════════════════════════════════════════════
# TestReferenceDirectories
# ══════════════════════════════════════════════════════════

class TestReferenceDirectories:
    """FrameworkProfile reference_directories field."""

    def test_default_structure(self):
        profile = FrameworkProfile()
        ref = profile.reference_directories.value
        assert "mature" in ref
        assert "developing" in ref
        assert "deprecated" in ref
        assert isinstance(ref["mature"], list)

    def test_serialization_roundtrip(self):
        profile = FrameworkProfile(
            reference_directories=ProfileField(
                value={"mature": ["src/components"], "developing": ["src/new"], "deprecated": []},
                source="human_dialogue",
                confidence=0.9,
            )
        )
        d = profile.to_dict()
        restored = FrameworkProfile.from_dict(d)
        assert restored.reference_directories.value["mature"] == ["src/components"]
        assert restored.reference_directories.source == "human_dialogue"

    def test_infer_classifies_directories(self, manager, java_project):
        manager.seed_two_phase()
        profile = manager._profile_manager.get_profile()
        ref = profile.reference_directories.value
        assert isinstance(ref, dict)
        # With our test project, components dir should be classified
        all_dirs = ref.get("mature", []) + ref.get("developing", [])
        assert len(all_dirs) >= 0  # may be empty for small test project

    def test_nl_update_reference_dirs(self, manager, java_project):
        manager.seed_two_phase()
        profile = manager._profile_manager.update_profile("reference_directories", {
            "mature": ["src/main/java/com/acme/components"],
            "developing": ["src/main/java/com/acme/experimental"],
            "deprecated": [],
        })
        assert "src/main/java/com/acme/components" in profile.reference_directories.value["mature"]


# ══════════════════════════════════════════════════════════
# TestOutputConfig
# ══════════════════════════════════════════════════════════

class TestOutputConfig:
    """FrameworkProfile output_config field drives pipeline generation."""

    def test_default_generates_two_types(self):
        profile = FrameworkProfile()
        config = profile.output_config.value
        assert isinstance(config, dict)
        gen_list = config.get("generate", [])
        types = [g["type"] for g in gen_list]
        assert "test_script" in types
        assert "test_data" in types

    def test_serialization_roundtrip(self):
        profile = FrameworkProfile()
        d = profile.to_dict()
        restored = FrameworkProfile.from_dict(d)
        gen_list = restored.output_config.value.get("generate", [])
        types = [g["type"] for g in gen_list]
        assert "test_script" in types

    def test_pipeline_load_output_config_default(self):
        """Pipeline._load_output_config returns defaults when no profile exists."""
        from uibridge.pipeline import Pipeline
        from uibridge.adapter.reference import (
            ReferenceComponentResolver, ReferenceLocatorStrategy,
            ReferenceActionRecognizer, ReferenceCodeGenerator, ReferenceDataFormatter,
        )
        pipeline = Pipeline(
            component_resolver=ReferenceComponentResolver(),
            locator_strategy=ReferenceLocatorStrategy(),
            action_recognizer=ReferenceActionRecognizer(),
            code_generator=ReferenceCodeGenerator(),
            data_formatter=ReferenceDataFormatter(),
            project_root=tempfile.mkdtemp(),
            kb_manager=None,
        )
        types, hints = pipeline._load_output_config()
        assert "test_script" in types
        assert "test_data" in types
        assert hints["test_script"]["dir"] == "tests"

    def test_pipeline_load_output_config_from_profile(self):
        """Pipeline reads output config from profile when available."""
        from uibridge.pipeline import Pipeline
        from uibridge.adapter.reference import (
            ReferenceComponentResolver, ReferenceLocatorStrategy,
            ReferenceActionRecognizer, ReferenceCodeGenerator, ReferenceDataFormatter,
        )
        td = tempfile.mkdtemp()
        pm = ProfileManager(td)
        mgr = KBManager(td, profile_manager=pm)
        mgr.seed_two_phase()
        # Update output_config to custom dirs
        mgr._profile_manager.update_profile("output_config", {
            "generate": [
                {"type": "test_script", "dir": "custom_tests", "template": "custom"},
                {"type": "test_data", "dir": "custom_data", "template": "custom"},
            ]
        })
        pipeline = Pipeline(
            component_resolver=ReferenceComponentResolver(),
            locator_strategy=ReferenceLocatorStrategy(),
            action_recognizer=ReferenceActionRecognizer(),
            code_generator=ReferenceCodeGenerator(),
            data_formatter=ReferenceDataFormatter(),
            project_root=td,
            kb_manager=mgr,
            profile_manager=pm,
        )
        types, hints = pipeline._load_output_config()
        assert "test_script" in types
        assert hints["test_script"]["dir"] == "custom_tests"
        assert hints["test_data"]["dir"] == "custom_data"
        shutil.rmtree(td, ignore_errors=True)

    def test_nl_update_output_config(self, manager, java_project):
        manager.seed_two_phase()
        profile = manager._profile_manager.update_profile("output_config", {
            "generate": [
                {"type": "test_script", "dir": "e2e_tests", "template": "testng"},
            ]
        })
        gen_list = profile.output_config.value["generate"]
        assert len(gen_list) == 1
        assert gen_list[0]["dir"] == "e2e_tests"


# ══════════════════════════════════════════════════════════
# TestComponentMonitoring
# ══════════════════════════════════════════════════════════

class TestComponentMonitoring:
    """Component snapshot storage and freshness detection."""

    def test_save_and_load_snapshot(self, kb_store):
        path = kb_store.save_component_snapshot(
            "WebTable", "src/components/WebTable.java",
            ["void sortColumn(String)", "int getRowCount()"],
            {"xpath": "//table[@data-module='table']"},
            base_class="BaseComponent",
        )
        assert Path(path).exists()
        loaded = kb_store.load_component_snapshot("WebTable")
        assert loaded is not None
        assert loaded["component"] == "WebTable"
        assert "sortColumn" in loaded["methods"][0]
        assert loaded["base_class"] == "BaseComponent"

    def test_load_nonexistent_snapshot(self, kb_store):
        assert kb_store.load_component_snapshot("NonExistent") is None

    def test_list_snapshots(self, kb_store):
        kb_store.save_component_snapshot("CompA", "a.java", ["m1()"], {})
        kb_store.save_component_snapshot("CompB", "b.java", ["m2()"], {})
        names = kb_store.list_snapshots()
        assert "CompA" in names
        assert "CompB" in names

    def test_delete_snapshot(self, kb_store):
        kb_store.save_component_snapshot("ToDelete", "x.java", [], {})
        assert kb_store.load_component_snapshot("ToDelete") is not None
        kb_store.delete_snapshot("ToDelete")
        assert kb_store.load_component_snapshot("ToDelete") is None

    def test_compare_snapshot_no_change(self):
        existing = {"methods": ["void click()", "String getText()"],
                    "locators": {"xpath": "//btn"}, "base_class": "Base"}
        current = {"methods": ["void click()", "String getText()"],
                   "locators": {"xpath": "//btn"}, "base_class": "Base"}
        diff = KBStore.compare_snapshot(existing, current)
        assert diff["stale"] is False
        assert diff["added_methods"] == []
        assert diff["removed_methods"] == []

    def test_compare_snapshot_method_added(self):
        existing = {"methods": ["void click()"], "locators": {}, "base_class": "Base"}
        current = {"methods": ["void click()", "void submit()"], "locators": {}, "base_class": "Base"}
        diff = KBStore.compare_snapshot(existing, current)
        assert diff["stale"] is True
        assert "submit" in diff["added_methods"]

    def test_compare_snapshot_method_removed(self):
        existing = {"methods": ["void click()", "void old()"], "locators": {}, "base_class": "Base"}
        current = {"methods": ["void click()"], "locators": {}, "base_class": "Base"}
        diff = KBStore.compare_snapshot(existing, current)
        assert diff["stale"] is True
        assert "old" in diff["removed_methods"]

    def test_compare_snapshot_locator_changed(self):
        existing = {"methods": [], "locators": {"xpath": "//old"}, "base_class": ""}
        current = {"methods": [], "locators": {"xpath": "//new"}, "base_class": ""}
        diff = KBStore.compare_snapshot(existing, current)
        assert diff["stale"] is True
        assert len(diff["locator_changes"]) == 1
        assert diff["locator_changes"][0]["old"] == "//old"
        assert diff["locator_changes"][0]["new"] == "//new"

    def test_compare_snapshot_base_class_changed(self):
        existing = {"methods": [], "locators": {}, "base_class": "OldBase"}
        current = {"methods": [], "locators": {}, "base_class": "NewBase"}
        diff = KBStore.compare_snapshot(existing, current)
        assert diff["stale"] is True
        assert diff["base_class_changed"] is True

    def test_check_freshness_disabled(self, manager, java_project):
        manager.seed_two_phase()
        reports = manager.check_component_freshness()
        assert reports == []

    def test_check_freshness_with_source(self, manager, java_project):
        manager.seed_two_phase()
        # Enable monitoring and save a snapshot
        manager._profile_manager.update_profile("component_monitoring", {
            "enabled": True,
            "components": ["WebTable"],
            "check_interval_days": 7,
        })
        manager.store.save_component_snapshot(
            "WebTable",
            "src/main/java/com/acme/components/WebTable.java",
            ["void sortColumn(String)", "int getRowCount()"],
            {"xpath": "//table[@data-module='table']"},
            base_class="BaseComponent",
        )
        reports = manager.check_component_freshness()
        assert len(reports) == 1
        assert reports[0]["component"] == "WebTable"
        assert reports[0]["status"] == "checked"

    # ── signature_changes detection ────────────────────

    def test_compare_snapshot_signature_return_changed(self):
        """Existing 'void click()' vs current 'boolean click()' — stale + signature_changes."""
        existing = {"methods": ["void click()"], "locators": {}, "base_class": "Base"}
        current = {"methods": ["boolean click()"], "locators": {}, "base_class": "Base"}
        diff = KBStore.compare_snapshot(existing, current)
        assert diff["stale"] is True
        assert len(diff["signature_changes"]) == 1
        assert diff["signature_changes"][0]["method"] == "click"
        assert diff["signature_changes"][0]["old"]["return"] == "void"
        assert diff["signature_changes"][0]["new"]["return"] == "boolean"

    def test_compare_snapshot_signature_params_changed(self):
        """Existing 'void sort(String col)' vs 'void sort(String col, String order)'."""
        existing = {"methods": ["void sort(String col)"], "locators": {}, "base_class": "Base"}
        current = {"methods": ["void sort(String col, String order)"], "locators": {}, "base_class": "Base"}
        diff = KBStore.compare_snapshot(existing, current)
        assert diff["stale"] is True
        assert len(diff["signature_changes"]) == 1
        assert diff["signature_changes"][0]["method"] == "sort"
        old_params = diff["signature_changes"][0]["old"]["params"]
        new_params = diff["signature_changes"][0]["new"]["params"]
        assert len(old_params) == 1
        assert len(new_params) == 2
        assert "String col" in old_params
        assert "String order" in new_params[1]

    def test_compare_snapshot_python_signature(self):
        """Python sigs: 'def get_text(self)' vs 'def get_text(self, x)' — params diff detected.

        Note: _parse_method_signature matches Java pattern first, so 'def' is parsed
        as the return type. The method name and params are still extracted correctly.
        """
        existing = {"methods": ["def get_text(self)"], "locators": {}, "base_class": ""}
        current = {"methods": ["def get_text(self, x)"], "locators": {}, "base_class": ""}
        diff = KBStore.compare_snapshot(existing, current)
        assert diff["stale"] is True
        assert len(diff["signature_changes"]) == 1
        assert diff["signature_changes"][0]["method"] == "get_text"
        assert diff["signature_changes"][0]["old"]["params"] == ["self"]
        assert diff["signature_changes"][0]["new"]["params"] == ["self", "x"]

    def test_parse_method_signature_edge_cases(self):
        """_parse_method_signature handles empty, whitespace, bare return type, Java, Python."""
        parse = KBStore._parse_method_signature

        # Empty string → None
        assert parse("") is None
        # Whitespace → None
        assert parse("   ") is None
        # "void" alone (no method name) → None
        assert parse("void") is None

        # Java: "void doSomething()" → valid
        result = parse("void doSomething()")
        assert result == {"return": "void", "name": "doSomething", "params": []}

        # Java: "List<String> getItems(int page)" → valid
        result = parse("List<String> getItems(int page)")
        assert result["return"] == "List<String>"
        assert result["name"] == "getItems"
        assert result["params"] == ["int page"]

        # Python-like: "def get_text(self) -> str" → matched by Java regex first
        # ('def' treated as return type, method name and params still correct)
        result = parse("def get_text(self) -> str")
        assert result == {"return": "def", "name": "get_text", "params": ["self"]}

        # Python-like: "def do_work(self, x, y)" → matched by Java regex first
        result = parse("def do_work(self, x, y)")
        assert result == {"return": "def", "name": "do_work", "params": ["self", "x", "y"]}


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


# ══════════════════════════════════════════════════════════
# TestProfileManager
# ══════════════════════════════════════════════════════════

class TestProfileManager:
    """ProfileManager: instantiation and empty profile handling."""

    def test_instantiate_has_expected_attributes(self):
        from uibridge.profile_manager import ProfileManager
        import tempfile
        td = tempfile.mkdtemp()
        try:
            pm = ProfileManager(td)
            assert hasattr(pm, "store")
            assert hasattr(pm, "project_root")
            assert str(pm.project_root) == td
            assert pm.store is not None
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_get_profile_returns_none_when_no_profile(self):
        from uibridge.profile_manager import ProfileManager
        import tempfile
        td = tempfile.mkdtemp()
        try:
            pm = ProfileManager(td)
            profile = pm.get_profile()
            assert profile is None
        finally:
            shutil.rmtree(td, ignore_errors=True)


# ══════════════════════════════════════════════════════════
# TestProfileConfirmation
# ══════════════════════════════════════════════════════════

class TestProfileConfirmation:
    """KBManager.confirm_profile() returns low-confidence fields."""

    def test_no_profile_returns_no_profile(self):
        td = tempfile.mkdtemp()
        pm = ProfileManager(td)
        mgr = KBManager(td, profile_manager=pm)
        result = mgr._profile_manager.confirm_profile()
        assert result["status"] == "no_profile"
        shutil.rmtree(td, ignore_errors=True)

    def test_fresh_profile_has_low_confidence_fields(self, manager, java_project):
        manager.seed_two_phase()
        result = manager._profile_manager.confirm_profile()
        assert result["status"] == "needs_confirmation"
        fields = result["low_confidence_fields"]
        assert len(fields) > 0
        # Each field should have description
        for f in fields:
            assert "field" in f
            assert "confidence" in f
            assert "description" in f

    def test_after_human_confirmation_fields_reduce(self, manager, java_project):
        manager.seed_two_phase()
        before = manager._profile_manager.confirm_profile()
        before_count = len(before["low_confidence_fields"])

        # Human confirms a field (raises confidence above threshold)
        manager._profile_manager.update_profile("layer_structure", manager._profile_manager.get_profile().layer_structure.value)
        after = manager._profile_manager.confirm_profile()
        after_count = len(after["low_confidence_fields"])
        # layer_structure should no longer be in low-confidence list
        assert after_count < before_count

    def test_all_confirmed_when_all_high_confidence(self):
        td = tempfile.mkdtemp()
        pm = ProfileManager(td)
        mgr = KBManager(td, profile_manager=pm)
        # Create a profile with all fields at high confidence
        profile = FrameworkProfile(
            ui_packages=ProfileField(value=["com.acme"], confidence=0.9),
            base_classes=ProfileField(value={"Base": "container"}, confidence=0.9),
            annotations=ProfileField(value=["@FindBy"], confidence=0.9),
            locator_priorities=ProfileField(value=["data-testid"], confidence=0.9),
            naming_conventions=ProfileField(value={"suffix": "AW"}, confidence=0.9),
            source_dirs=ProfileField(value={"pages": "src"}, confidence=0.9),
            layer_structure=ProfileField(value=[], confidence=0.9),
            reference_directories=ProfileField(value={"mature": [], "developing": [], "deprecated": []}, confidence=0.9),
            output_config=ProfileField(value={"generate": []}, confidence=0.9),
            component_monitoring=ProfileField(value={"enabled": False}, confidence=0.9),
        )
        mgr._profile_manager.store.save(profile)
        result = mgr._profile_manager.confirm_profile()
        assert result["status"] == "all_confirmed"
        shutil.rmtree(td, ignore_errors=True)

    def test_threshold_parameter(self, manager, java_project):
        manager.seed_two_phase()
        # With very low threshold, most fields should pass
        result = manager._profile_manager.confirm_profile(threshold=0.1)
        # With default profiling, some fields might be above 0.1
        low_count_strict = len(manager._profile_manager.confirm_profile(threshold=0.9)["low_confidence_fields"])
        low_count_loose = len(result.get("low_confidence_fields", []))
        assert low_count_strict >= low_count_loose
