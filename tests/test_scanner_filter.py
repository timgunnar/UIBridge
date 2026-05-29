"""Tests for scanner/filter.py — UIRelevanceFilter multi-signal scoring."""

import tempfile
from pathlib import Path

import pytest

from uibridge.scanner.filter import (
    UISignal,
    UIRelevanceScore,
    UIRelevanceFilter,
)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _make_file(tmpdir: str, relpath: str, content: str) -> Path:
    """Write a file under tmpdir, creating parent dirs as needed. Returns Path."""
    full = Path(tmpdir) / relpath
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


# ═══════════════════════════════════════════════════════════════
# TestUISignal
# ═══════════════════════════════════════════════════════════════


class TestUISignal:
    """Verify UISignal enum members."""

    def test_all_signals_exist(self):
        assert UISignal.PATH is not None
        assert UISignal.INHERITANCE is not None
        assert UISignal.ANNOTATION is not None
        assert UISignal.LOCATOR is not None
        assert UISignal.NAMING is not None

    def test_signal_values_are_strings(self):
        for signal in UISignal:
            assert isinstance(signal.value, str)

    def test_signal_count(self):
        assert len(list(UISignal)) == 5

    def test_signal_uniqueness(self):
        values = {s.value for s in UISignal}
        assert len(values) == 5


# ═══════════════════════════════════════════════════════════════
# TestUIRelevanceScore
# ═══════════════════════════════════════════════════════════════


class TestUIRelevanceScore:
    """Verify UIRelevanceScore dataclass."""

    def test_fields_accessible(self):
        score = UIRelevanceScore(
            path=Path("/fake/HomePage.java"),
            relevance="HIGH",
            signals=[UISignal.PATH, UISignal.NAMING, UISignal.LOCATOR],
            confidence=0.6,
            details={"path": "page", "naming": {"stem": "HomePage", "suffixes": ["page"], "prefixes": []}},
        )
        assert score.path == Path("/fake/HomePage.java")
        assert score.relevance == "HIGH"
        assert len(score.signals) == 3
        assert score.confidence == 0.6
        assert "path" in score.details
        assert "naming" in score.details

    def test_repr_includes_relevance(self):
        score = UIRelevanceScore(
            path=Path("file.java"),
            relevance="MEDIUM",
            signals=[UISignal.PATH],
            confidence=0.2,
            details={},
        )
        r = repr(score)
        assert "MEDIUM" in r
        assert "file.java" in r

    def test_default_empty_signals(self):
        score = UIRelevanceScore(
            path=Path("Empty.java"),
            relevance="NONE",
            signals=[],
            confidence=0.0,
            details={},
        )
        assert score.relevance == "NONE"
        assert score.signals == []
        assert score.confidence == 0.0


# ═══════════════════════════════════════════════════════════════
# TestPathSignal
# ═══════════════════════════════════════════════════════════════


class TestPathSignal:
    """FileScanner.classify() → PATH signal for AW/PAGE/TEST dirs."""

    def test_pages_dir_gives_path_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/HomePage.java", "public class HomePage {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.PATH in score.signals
            assert score.details["path"] in ("page", "aw", "test")

    def test_components_dir_gives_path_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "components/UserTable.java", "public class UserTable {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.PATH in score.signals

    def test_tests_dir_gives_path_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "tests/MyTest.java", "public class MyTest {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.PATH in score.signals

    def test_utils_dir_no_path_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "utils/Helper.java", "public class Helper {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.PATH not in score.signals

    def test_config_dir_no_path_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "config/Settings.java", "public class Settings {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.PATH not in score.signals

    def test_root_level_file_no_path_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "Main.java", "public class Main {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.PATH not in score.signals


# ═══════════════════════════════════════════════════════════════
# TestNamingSignal
# ═══════════════════════════════════════════════════════════════


class TestNamingSignal:
    """File naming conventions → NAMING signal."""

    def test_page_suffix_gives_naming_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "HomePage.java", "public class HomePage {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.NAMING in score.signals

    def test_aw_suffix_gives_naming_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "UserTableAW.java", "public class UserTableAW {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.NAMING in score.signals

    def test_component_suffix_gives_naming_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "SearchComponent.java", "public class SearchComponent {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.NAMING in score.signals

    def test_widget_suffix_gives_naming_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "HeaderWidget.java", "public class HeaderWidget {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.NAMING in score.signals

    def test_screen_suffix_gives_naming_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "LoginScreen.java", "public class LoginScreen {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.NAMING in score.signals

    def test_view_suffix_gives_naming_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "ProfileView.java", "public class ProfileView {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.NAMING in score.signals

    def test_test_suffix_gives_naming_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "UserSpec.java", "public class UserSpec {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.NAMING in score.signals

    def test_test_prefix_gives_naming_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "TestUserSearch.java", "public class TestUserSearch {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.NAMING in score.signals

    def test_plain_util_name_no_naming_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "StringUtils.java", "public class StringUtils {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.NAMING not in score.signals

    def test_stem_equals_suffix_no_naming_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "Page.java", "public class Page {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.NAMING not in score.signals

    def test_stem_only_prefix_no_naming_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "Test.java", "public class Test {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.NAMING not in score.signals

    def test_naming_details_include_matched_suffixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "HomePage.java", "public class HomePage {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert "page" in score.details["naming"]["suffixes"]

    def test_naming_details_include_matched_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "TestSearch.java", "public class TestSearch {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert "test" in score.details["naming"]["prefixes"]


# ═══════════════════════════════════════════════════════════════
# TestInheritanceSignal
# ═══════════════════════════════════════════════════════════════


class TestInheritanceSignal:
    """Inheritance patterns → INHERITANCE signal."""

    def test_java_extends_basepage_gives_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyPage.java",
                           "public class MyPage extends BasePage {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE in score.signals

    def test_java_extends_basecomponent_gives_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyComponent.java",
                           "public class MyComponent extends BaseComponent {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE in score.signals

    def test_java_extends_pageobject_gives_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "LoginPO.java",
                           "public class LoginPO extends PageObject {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE in score.signals

    def test_java_extends_aw_class_gives_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "UserTable.java",
                           "public class UserTable extends BaseTableAW {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE in score.signals

    def test_java_extends_widget_gives_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "Header.java",
                           "public class Header extends BaseWidget {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE in score.signals

    def test_java_extends_screen_keyword_gives_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "Login.java",
                           "public class Login extends BaseScreen {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE in score.signals

    def test_java_extends_non_ui_base_no_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "UserTable.java",
                           "public class UserTable extends BaseTable {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE not in score.signals

    def test_java_extends_plain_object_no_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "DataObj.java",
                           "public class DataObj extends HashMap {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE not in score.signals

    def test_python_class_with_ui_base_gives_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "login_page.py",
                           "class LoginPage(BasePage):\n    pass\n")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE in score.signals

    def test_python_class_with_basecomponent_gives_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "my_component.py",
                           "class MyComponent(BaseComponent):\n    pass\n")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE in score.signals

    def test_python_plain_class_no_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "utils.py",
                           "class StringHelper:\n    pass\n")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE not in score.signals

    def test_java_implements_ui_interface_gives_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyPage.java",
                           "public class MyPage implements IPageObject {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE in score.signals

    def test_no_class_definition_no_inheritance_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "Config.java",
                           "// Just some config constants\npublic interface Config { String HOST = \"localhost\"; }")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.INHERITANCE not in score.signals


# ═══════════════════════════════════════════════════════════════
# TestAnnotationSignal
# ═══════════════════════════════════════════════════════════════


class TestAnnotationSignal:
    """UI annotations → ANNOTATION signal."""

    def test_findby_on_field_gives_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyPage.java", """public class MyPage {
    @FindBy(id = "x")
    private WebElement el;
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION in score.signals

    def test_test_annotation_on_method_gives_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyTest.java", """public class MyTest {
    @Test
    public void testSearch() {}
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION in score.signals

    def test_component_annotation_gives_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyComponent.java", """@Component
public class MyComponent {}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION in score.signals

    def test_page_annotation_gives_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "LoginPage.java", """@Page
public class LoginPage {}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION in score.signals

    def test_step_annotation_gives_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "Steps.java", """public class Steps {
    @Step("click submit")
    public void clickSubmit() {}
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION in score.signals

    def test_pageobject_annotation_gives_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "HomePO.java", """@PageObject
public class HomePO {}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION in score.signals

    def test_screen_annotation_gives_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MainScreen.java", """@Screen
public class MainScreen {}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION in score.signals

    def test_widget_annotation_gives_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "Sidebar.java", """@Widget
public class Sidebar {}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION in score.signals

    def test_override_only_no_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "SubClass.java", """public class SubClass extends Base {
    @Override
    public void doThing() {}
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION not in score.signals

    def test_no_annotations_no_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "Plain.java", "public class Plain { private int x; }")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION not in score.signals

    def test_framework_annotation_autowired_gives_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyService.java", """@Service
public class MyService {
    @Autowired
    private Repo repo;
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION in score.signals

    def test_pytest_decorator_gives_annotation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "test_stuff.py", """import pytest

@pytest.fixture
def browser():
    pass

@pytest.mark.slow
def test_slow():
    pass
""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.ANNOTATION in score.signals

    def test_details_list_matched_annotation_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyPage.java", """public class MyPage {
    @FindBy(id = "x")
    private WebElement el;
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert "FindBy" in score.details["annotation"]


# ═══════════════════════════════════════════════════════════════
# TestLocatorSignal
# ═══════════════════════════════════════════════════════════════


class TestLocatorSignal:
    """Locator API usage → LOCATOR signal."""

    def test_java_findby_gives_locator_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyPage.java", """public class MyPage {
    @FindBy(id = "submit")
    private WebElement submitBtn;
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.LOCATOR in score.signals

    def test_java_by_xpath_gives_locator_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyTest.java", """public class MyTest {
    public void test() {
        driver.findElement(By.xpath("//button")).click();
    }
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.LOCATOR in score.signals

    def test_java_by_id_gives_locator_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyTest.java", """public class MyTest {
    public void test() {
        driver.findElement(By.id("search")).click();
    }
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.LOCATOR in score.signals

    def test_python_get_by_test_id_gives_locator_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "home_page.py", """from playwright.sync_api import Page

class HomePage:
    def __init__(self, page: Page):
        self.page = page
        self.search = page.get_by_test_id("search")
""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.LOCATOR in score.signals

    def test_python_page_locator_gives_locator_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "home_page.py", """from playwright.sync_api import Page

class HomePage:
    def __init__(self, page: Page):
        self.title = page.locator(".header")
""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.LOCATOR in score.signals

    def test_python_get_by_role_gives_locator_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "home_page.py", """from playwright.sync_api import Page

class HomePage:
    def __init__(self, page: Page):
        self.btn = page.get_by_role("button", name="Submit")
""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.LOCATOR in score.signals

    def test_pure_data_class_no_locator_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "UserDTO.java", """public class UserDTO {
    private String name;
    private int age;

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.LOCATOR not in score.signals

    def test_python_class_no_locators_no_locator_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "utils.py", """class StringHelper:
    @staticmethod
    def capitalize(s: str) -> str:
        return s.capitalize()
""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.LOCATOR not in score.signals

    def test_non_code_file_no_locator_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "readme.xml", "<project><name>test</name></project>")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.LOCATOR not in score.signals

    def test_locator_details_list_strategies(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "MyPage.java", """public class MyPage {
    @FindBy(id = "submit")
    @FindBy(xpath = "//button")
    private WebElement el;
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            strategies = score.details["locator"]
            assert "id" in strategies
            assert "xpath" in strategies


# ═══════════════════════════════════════════════════════════════
# TestScoreFile
# ═══════════════════════════════════════════════════════════════


class TestScoreFile:
    """Full integration scoring — score_file() combines all signals."""

    def test_high_relevance_page_object_with_three_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/HomePage.java", """package com.example.pages;

import org.openqa.selenium.WebElement;
import org.openqa.selenium.support.FindBy;

public class HomePage extends BasePage {
    @FindBy(id = "submit")
    private WebElement submitButton;
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert score.relevance == "HIGH"
            assert len(score.signals) >= 3
            assert UISignal.PATH in score.signals       # in pages/
            assert UISignal.NAMING in score.signals      # HomePage suffix
            assert UISignal.INHERITANCE in score.signals  # extends BasePage
            assert UISignal.ANNOTATION in score.signals   # @FindBy
            assert UISignal.LOCATOR in score.signals      # @FindBy(id=...)
            assert score.confidence == 1.0

    def test_high_relevance_test_file_in_test_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "tests/TestUserSearch.java", """package com.example.tests;

import org.testng.annotations.Test;
import com.example.pages.HomePage;

public class TestUserSearch extends BaseTest {
    @Test
    public void testSearch() {
        driver.findElement(By.id("search")).click();
    }
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert score.relevance == "HIGH"
            assert len(score.signals) >= 3

    def test_medium_relevance_component_with_two_signals(self):
        # A file with PATH + NAMING but no content signals = 2 signals = MEDIUM
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "components/SidebarWidget.java", """package com.example.components;

public class SidebarWidget {
    private String title;
    private int width;
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert score.relevance == "MEDIUM"
            assert len(score.signals) == 2
            assert UISignal.PATH in score.signals     # in components/
            assert UISignal.NAMING in score.signals    # "Widget" suffix

    def test_low_relevance_dto_in_pages_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/UserDTO.java", """package com.example.pages;

public class UserDTO {
    private String name;
    private int age;
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert score.relevance == "LOW"
            assert len(score.signals) == 1
            assert UISignal.PATH in score.signals  # only PATH, just in pages/ dir

    def test_none_relevance_utility_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "utils/StringHelper.java", """package com.example.utils;

public class StringHelper {
    public static String capitalize(String s) {
        return s.substring(0, 1).toUpperCase() + s.substring(1);
    }
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert score.relevance == "NONE"
            assert len(score.signals) == 0
            assert score.confidence == 0.0

    def test_none_relevance_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "config/AppConfig.java", """package com.example.config;

public class AppConfig {
    public static final String BASE_URL = "http://localhost";
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert score.relevance == "NONE"

    def test_confidence_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/HomePage.java", """public class HomePage extends BasePage {
    @FindBy(id = "x")
    private WebElement el;
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            # PATH + NAMING + INHERITANCE + ANNOTATION + LOCATOR = 5 signals
            assert score.confidence == 1.0

    def test_confidence_two_signals(self):
        # PATH + NAMING = 2 signals → 2/5 = 0.4
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/ProfileScreen.java", """public class ProfileScreen {
    private String name;
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert score.confidence == 0.4
            assert len(score.signals) == 2

    def test_python_page_object_high_relevance(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/home_page.py", """from playwright.sync_api import Page

class HomePage(BasePage):
    def __init__(self, page: Page):
        self.page = page
        self.search = page.get_by_test_id("search-input")
        self.submit = page.get_by_role("button", name="Submit")

    def search(self, query: str):
        self.search.fill(query)
        self.submit.click()
""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert score.relevance == "HIGH"
            assert len(score.signals) >= 3


# ═══════════════════════════════════════════════════════════════
# TestScoreFiles
# ═══════════════════════════════════════════════════════════════


class TestScoreFiles:
    """Batch scoring — score_files() sorts by confidence descending."""

    def test_returns_all_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            f1 = _make_file(tmp, "pages/HomePage.java", """public class HomePage extends BasePage {
    @FindBy(id = "x")
    private WebElement el;
}""")
            f2 = _make_file(tmp, "utils/Helper.java", "public class Helper {}")
            flt = UIRelevanceFilter(tmp)
            scores = flt.score_files([f1, f2])
            assert len(scores) == 2

    def test_sorted_by_confidence_descending(self):
        with tempfile.TemporaryDirectory() as tmp:
            f_high = _make_file(tmp, "pages/HomePage.java", """public class HomePage extends BasePage {
    @FindBy(id = "x")
    private WebElement el;
}""")
            f_low = _make_file(tmp, "pages/UserDTO.java", """public class UserDTO {
    private String name;
}""")
            f_none = _make_file(tmp, "utils/Helper.java", "public class Helper {}")
            flt = UIRelevanceFilter(tmp)
            scores = flt.score_files([f_low, f_none, f_high])
            confidences = [s.confidence for s in scores]
            assert confidences == sorted(confidences, reverse=True)

    def test_highest_confidence_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            f_high = _make_file(tmp, "pages/HomePage.java", """public class HomePage extends BasePage {
    @FindBy(id = "x")
    private WebElement el;
}""")
            f_none = _make_file(tmp, "utils/Helper.java", "public class Helper {}")
            flt = UIRelevanceFilter(tmp)
            scores = flt.score_files([f_none, f_high])
            assert scores[0].confidence >= scores[-1].confidence
            assert scores[0].relevance == "HIGH"

    def test_empty_files_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            flt = UIRelevanceFilter(tmp)
            scores = flt.score_files([])
            assert scores == []

    def test_preserves_file_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            f1 = _make_file(tmp, "pages/HomePage.java", "public class HomePage {}")
            f2 = _make_file(tmp, "utils/Helper.java", "public class Helper {}")
            flt = UIRelevanceFilter(tmp)
            scores = flt.score_files([f1, f2])
            paths = {s.path for s in scores}
            assert f1 in paths
            assert f2 in paths


# ═══════════════════════════════════════════════════════════════
# TestFilter
# ═══════════════════════════════════════════════════════════════


class TestFilter:
    """filter() — keep files with signal count >= min_signals."""

    def test_default_min_signals_2_excludes_low_and_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            f_high = _make_file(tmp, "pages/HomePage.java", """public class HomePage extends BasePage {
    @FindBy(id = "x")
    private WebElement el;
}""")
            f_medium = _make_file(tmp, "components/SearchForm.java", """public class SearchForm {
    @FindBy(id = "x")
    private WebElement el;
}""")
            f_low = _make_file(tmp, "pages/UserDTO.java", "public class UserDTO { private String name; }")
            f_none = _make_file(tmp, "utils/Helper.java", "public class Helper {}")
            flt = UIRelevanceFilter(tmp)
            result = flt.filter([f_high, f_medium, f_low, f_none])
            assert f_high in result
            assert f_medium in result
            assert f_low not in result
            assert f_none not in result

    def test_min_signals_1_keeps_low_and_above(self):
        with tempfile.TemporaryDirectory() as tmp:
            f_low = _make_file(tmp, "pages/UserDTO.java", "public class UserDTO { private String name; }")
            f_none = _make_file(tmp, "utils/Helper.java", "public class Helper {}")
            flt = UIRelevanceFilter(tmp)
            result = flt.filter([f_low, f_none], min_signals=1)
            assert f_low in result
            assert f_none not in result

    def test_min_signals_3_keeps_only_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            f_high = _make_file(tmp, "pages/HomePage.java", """public class HomePage extends BasePage {
    @FindBy(id = "x")
    private WebElement el;
}""")
            # Only PATH + NAMING = MEDIUM (2 signals), no content extras
            f_medium = _make_file(tmp, "pages/ProfileScreen.java", """public class ProfileScreen {
    private String name;
}""")
            flt = UIRelevanceFilter(tmp)
            result = flt.filter([f_high, f_medium], min_signals=3)
            assert f_high in result
            assert f_medium not in result

    def test_empty_input_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            flt = UIRelevanceFilter(tmp)
            result = flt.filter([])
            assert result == []

    def test_all_files_excluded_when_none_meet_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            f1 = _make_file(tmp, "utils/Helper.java", "public class Helper {}")
            f2 = _make_file(tmp, "config/Settings.java", "public class Settings {}")
            flt = UIRelevanceFilter(tmp)
            result = flt.filter([f1, f2], min_signals=1)
            assert result == []

    def test_all_files_included_when_all_meet_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            f_high = _make_file(tmp, "pages/HomePage.java", """public class HomePage extends BasePage {
    @FindBy(id = "x")
    private WebElement el;
}""")
            f_medium = _make_file(tmp, "components/SearchForm.java", """public class SearchForm {
    @FindBy(id = "x")
    private WebElement el;
}""")
            flt = UIRelevanceFilter(tmp)
            result = flt.filter([f_high, f_medium], min_signals=2)
            assert len(result) == 2


# ═══════════════════════════════════════════════════════════════
# TestEdgeCases
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases: binary files, non-code, empty, nonexistent."""

    def test_binary_file_gets_only_path_and_naming_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/HomePage.class", "\x00\x01\x02\x03\x04")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            # PATH signal still works (in pages/)
            assert UISignal.PATH in score.signals
            # NAMING signal still works (HomePage suffix)
            assert UISignal.NAMING in score.signals
            # Content signals should be empty
            assert UISignal.INHERITANCE not in score.signals
            assert UISignal.ANNOTATION not in score.signals
            assert UISignal.LOCATOR not in score.signals
            # Details should have empty lists for content signals
            assert score.details["inheritance"] == []
            assert score.details["annotation"] == []
            assert score.details["locator"] == []

    def test_non_code_file_no_content_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/readme.xml",
                           '<?xml version="1.0"?><project><name>test</name></project>')
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            # PATH + NAMING may still fire
            # But content signals for INHERITANCE/ANNOTATION depend on .java/.py patterns
            assert UISignal.LOCATOR not in score.signals

    def test_empty_file_content_signals_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/Empty.java", "")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            # PATH should fire
            assert UISignal.PATH in score.signals
            # NAMING may fire (Empty doesn't match any suffix)
            # Content signals should all be empty
            assert UISignal.INHERITANCE not in score.signals
            assert UISignal.ANNOTATION not in score.signals
            assert UISignal.LOCATOR not in score.signals

    def test_nonexistent_file_returns_none_or_low(self):
        with tempfile.TemporaryDirectory() as tmp:
            flt = UIRelevanceFilter(tmp)
            fake_path = Path(tmp) / "nonexistent" / "File.java"
            # Filter gracefully handles unreadable files: only PATH+NAMING
            # signals apply, content signals are empty
            score = flt.score_file(fake_path)
            assert score.relevance in ("LOW", "NONE")
            assert score.details["inheritance"] == []
            assert score.details["annotation"] == []
            assert score.details["locator"] == []

    def test_spaces_only_file_no_content_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/Blank.java", "   \n  \n   ")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.PATH in score.signals
            # Content signals should all be empty (no class, no annotations, no locators)
            assert UISignal.INHERITANCE not in score.signals
            assert UISignal.ANNOTATION not in score.signals
            assert UISignal.LOCATOR not in score.signals

    def test_file_with_unicode_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/HomePage.java",
                           '﻿public class HomePage extends BasePage {\n    @FindBy(id = "x")\n    private WebElement el;\n}')
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.PATH in score.signals
            assert UISignal.NAMING in score.signals

    def test_very_long_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            deep_dir = "a" * 10
            for _ in range(5):
                deep_dir += "/" + "b" * 10
            f = _make_file(tmp, f"{deep_dir}/HomePage.java",
                           "public class HomePage extends BasePage {}")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert score.relevance in ("HIGH", "MEDIUM", "LOW", "NONE")

    def test_file_with_only_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/HomePage.java", """// Copyright 2024
/* This is a comment block
 * spanning multiple lines
 */
// Another comment line
""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert UISignal.PATH in score.signals
            assert UISignal.NAMING in score.signals


# ═══════════════════════════════════════════════════════════════
# TestMixedProject
# ═══════════════════════════════════════════════════════════════


class TestMixedProject:
    """Java + Python mixed project with UI and non-UI files."""

    def _create_mixed_project(self, tmp: str) -> list[Path]:
        """Create a mixed Java + Python project. Returns list of file paths."""
        files = []

        # Java UI files
        files.append(_make_file(tmp, "pages/HomePage.java", """package com.example.pages;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.support.FindBy;

public class HomePage extends BasePage {
    @FindBy(id = "submit")
    private WebElement submitButton;

    public void submit() {
        submitButton.click();
    }
}"""))

        files.append(_make_file(tmp, "components/UserTable.java", """package com.example.components;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.support.FindBy;

public class UserTable extends BaseComponent {
    @FindBy(id = "searchInput")
    private WebElement searchInput;
}"""))

        files.append(_make_file(tmp, "tests/TestUserSearch.java", """package com.example.tests;
import org.testng.annotations.Test;
import com.example.pages.HomePage;

public class TestUserSearch extends BaseTest {
    @Test
    public void testSearch() {
        driver.findElement(By.id("search")).click();
    }
}"""))

        # Java non-UI files
        files.append(_make_file(tmp, "utils/StringHelper.java", """package com.example.utils;

public class StringHelper {
    public static String trim(String s) { return s.trim(); }
}"""))

        files.append(_make_file(tmp, "config/AppConfig.java", """package com.example.config;

public class AppConfig {
    public static final int TIMEOUT = 30;
}"""))

        files.append(_make_file(tmp, "model/UserDTO.java", """package com.example.model;

public class UserDTO {
    private String name;
    private int age;
    public String getName() { return name; }
}"""))

        # Python UI files
        files.append(_make_file(tmp, "pages/home_page.py", """from playwright.sync_api import Page

class HomePage(BasePage):
    def __init__(self, page: Page):
        self.page = page
        self.search_input = page.get_by_test_id("search-input")
        self.submit_btn = page.get_by_role("button", name="Submit")

    def search(self, query: str):
        self.search_input.fill(query)
        self.submit_btn.click()
"""))

        files.append(_make_file(tmp, "components/header_widget.py", """from playwright.sync_api import Page

class HeaderWidget(BaseWidget):
    def __init__(self, page: Page):
        self.page = page
        self.logo = page.locator(".logo")
"""))

        files.append(_make_file(tmp, "tests/test_search.py", """import pytest
from pages.home_page import HomePage

class TestSearch:
    def test_search_user(self, page):
        home = HomePage(page)
        home.search("john")
        assert page.locator(".result").is_visible()
"""))

        # Python non-UI files
        files.append(_make_file(tmp, "utils/helpers.py", """def format_currency(amount: float) -> str:
    return f"${amount:,.2f}"
"""))

        files.append(_make_file(tmp, "config/settings.py", """BASE_URL = "http://localhost:8080"
TIMEOUT = 30
"""))

        return files

    def test_filter_keeps_ui_files_excludes_non_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            all_files = self._create_mixed_project(tmp)
            flt = UIRelevanceFilter(tmp)

            scores = flt.score_files(all_files)

            ui_paths = set()
            non_ui_paths = set()
            for s in scores:
                if s.relevance in ("HIGH", "MEDIUM"):
                    ui_paths.add(s.path)
                else:
                    non_ui_paths.add(s.path)

            # UI files should be HIGH or MEDIUM
            for p in ui_paths:
                rel = str(p.relative_to(tmp)).replace("\\", "/")
                assert any(d in rel for d in ("pages/", "components/", "tests/")), \
                    f"Expected UI file to be in pages/components/tests: {rel}"

            # Non-UI files should be in utils/ config/ model/
            for p in non_ui_paths:
                rel = str(p.relative_to(tmp)).replace("\\", "/")
                assert any(d in rel for d in ("utils/", "config/", "model/")), \
                    f"Expected non-UI file in utils/config/model: {rel}"

    def test_filter_default_min_2_finds_correct_ui_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            all_files = self._create_mixed_project(tmp)
            flt = UIRelevanceFilter(tmp)
            ui_files = flt.filter(all_files, min_signals=2)

            # The DTO in model/ and the config files should be excluded
            for f in ui_files:
                rel = str(f.relative_to(tmp)).replace("\\", "/")
                assert "model/" not in rel
                assert "config/" not in rel
                assert "utils/" not in rel

            # UI files should be included
            assert len(ui_files) >= 6  # At least the 6 clear UI files

    def test_score_files_sorted_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            all_files = self._create_mixed_project(tmp)
            flt = UIRelevanceFilter(tmp)
            scores = flt.score_files(all_files)

            # First scores should be HIGH
            high_count = sum(1 for s in scores if s.relevance == "HIGH")
            medium_count = sum(1 for s in scores if s.relevance == "MEDIUM")
            low_count = sum(1 for s in scores if s.relevance == "LOW")
            none_count = sum(1 for s in scores if s.relevance == "NONE")

            assert high_count >= 3  # HomePage.java, TestUserSearch.java, home_page.py at minimum
            # Medium or high combined should cover all UI files
            assert high_count + medium_count >= 6  # All 6 UI files
            assert none_count >= 2  # utils and config files

            # Verify sort order: confidence descending
            confidences = [s.confidence for s in scores]
            assert confidences == sorted(confidences, reverse=True)

    def test_individual_file_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/HomePage.java", """public class HomePage extends BasePage {
    @FindBy(id = "submit")
    private WebElement submitButton;
}""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert score.relevance == "HIGH"
            assert len(score.signals) == 5
            assert UISignal.PATH in score.signals
            assert UISignal.NAMING in score.signals
            assert UISignal.INHERITANCE in score.signals
            assert UISignal.ANNOTATION in score.signals
            assert UISignal.LOCATOR in score.signals

    def test_python_ui_file_full_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _make_file(tmp, "pages/home_page.py", """from playwright.sync_api import Page

class HomePage(BasePage):
    def __init__(self, page: Page):
        self.search = page.get_by_test_id("search")
""")
            flt = UIRelevanceFilter(tmp)
            score = flt.score_file(f)
            assert score.relevance in ("HIGH", "MEDIUM")
            # At minimum: PATH + NAMING + INHERITANCE + LOCATOR
            assert len(score.signals) >= 3
