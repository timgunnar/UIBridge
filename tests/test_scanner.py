"""Tests for scanner module — auto-discovery, parser, and primitives."""

import os
import tempfile
from pathlib import Path

import pytest

from uibridge.scanner import (
    Scanner,
    ProjectProfile,
    ProfileField,
    UnifiedAST,
    parse_file,
    ASTNode,
)
from uibridge.scanner.discover import _is_ui_filename
from uibridge.scanner.primitives import (
    FileScanner,
    InheritanceAnalyzer,
    CallAnalyzer,
    AnnotationExtractor,
    PatternMiner,
    StatisticsCollector,
    LocatorExtractor,
)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _write_file(dir_path: str, filename: str, content: str) -> str:
    """Write a file under dir_path, creating parent dirs as needed."""
    full = Path(dir_path) / filename
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return str(full)


def _create_maven_project(root: str) -> None:
    """Create a minimal Maven + TestNG + Selenium project structure."""
    # pom.xml
    _write_file(root, "pom.xml", """<?xml version="1.0" encoding="UTF-8"?>
<project>
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>test-project</artifactId>
    <version>1.0.0</version>
    <dependencies>
        <dependency>
            <groupId>org.seleniumhq.selenium</groupId>
            <artifactId>selenium-java</artifactId>
        </dependency>
        <dependency>
            <groupId>org.testng</groupId>
            <artifactId>testng</artifactId>
        </dependency>
    </dependencies>
</project>""")

    # Base class (AW component)
    _write_file(root, "src/main/java/com/example/components/BaseTable.java", """package com.example.components;

import org.openqa.selenium.WebElement;
import org.openqa.selenium.support.FindBy;

public class BaseTable {
    @FindBy(id = "tableBody")
    protected WebElement tableBody;

    @FindBy(xpath = "//thead/tr")
    protected WebElement headerRow;

    public void clickRow(int rowIndex) {
        // click row
    }
}""")

    # A concrete TableAW
    _write_file(root, "src/main/java/com/example/components/UserTable.java", """package com.example.components;

public class UserTable extends BaseTable {
    @FindBy(id = "searchInput")
    private WebElement searchInput;

    public void search(String text) {
        searchInput.sendKeys(text);
    }
}""")

    # Another component
    _write_file(root, "src/main/java/com/example/components/LoginForm.java", """package com.example.components;

import org.openqa.selenium.WebElement;
import org.openqa.selenium.support.FindBy;

public class LoginForm {
    @FindBy(id = "username")
    private WebElement usernameInput;

    @FindBy(id = "password")
    private WebElement passwordInput;

    @FindBy(cssSelector = "button[type='submit']")
    private WebElement submitButton;

    public void login(String user, String pass) {
        usernameInput.sendKeys(user);
        passwordInput.sendKeys(pass);
        submitButton.click();
    }
}""")

    # Page object
    _write_file(root, "src/main/java/com/example/pages/HomePage.java", """package com.example.pages;

import org.openqa.selenium.WebDriver;
import com.example.components.UserTable;
import com.example.components.LoginForm;

public class HomePage {
    private WebDriver driver;
    private UserTable userTable;
    private LoginForm loginForm;

    public HomePage(WebDriver driver) {
        this.driver = driver;
    }

    public void searchUser(String name) {
        userTable.search(name);
    }
}""")

    # Test script
    _write_file(root, "src/test/java/com/example/tests/UserSearchTest.java", """package com.example.tests;

import org.testng.annotations.Test;
import org.testng.annotations.BeforeClass;
import org.testng.Assert;
import com.example.pages.HomePage;

public class UserSearchTest extends BaseTest {
    private HomePage homePage;

    @BeforeClass
    public void setUp() {
        homePage = new HomePage(driver);
    }

    @Test
    public void testSearchUser() {
        homePage.searchUser("john");
        Assert.assertTrue(true);
    }
}""")

    # Base test class
    _write_file(root, "src/test/java/com/example/tests/BaseTest.java", """package com.example.tests;

import org.openqa.selenium.WebDriver;
import org.openqa.selenium.chrome.ChromeDriver;
import org.testng.annotations.AfterClass;

public class BaseTest {
    protected WebDriver driver;

    public BaseTest() {
        driver = new ChromeDriver();
    }

    @AfterClass
    public void tearDown() {
        driver.quit();
    }
}""")


def _create_pytest_project(root: str) -> None:
    """Create a minimal Python + pytest + Playwright project structure."""
    # pyproject.toml
    _write_file(root, "pyproject.toml", """[project]
name = "test-project"
version = "1.0.0"
dependencies = [
    "pytest",
    "playwright",
]

[project.optional-dependencies]
test = ["pytest-playwright"]
""")

    # conftest.py
    _write_file(root, "tests/conftest.py", """import pytest
from playwright.sync_api import Page

@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()
""")

    # Page object
    _write_file(root, "tests/pages/home_page.py", """from playwright.sync_api import Page

class HomePage:
    def __init__(self, page: Page):
        self.page = page
        self.search_input = page.get_by_test_id("search-input")
        self.search_button = page.get_by_role("button", name="Search")

    def search(self, query: str):
        self.search_input.fill(query)
        self.search_button.click()
""")

    # Test
    _write_file(root, "tests/test_search.py", """import pytest
from tests.pages.home_page import HomePage

class TestSearch:
    def test_search_user(self, page):
        home = HomePage(page)
        home.search("john")
        assert True
""")


# ═══════════════════════════════════════════════════════════════
# TestScanner - Discovery
# ═══════════════════════════════════════════════════════════════


class TestScannerDiscoverEmpty:
    """Empty project or nonexistent dir → low-confidence profile."""

    def test_nonexistent_dir(self):
        scanner = Scanner()
        profile = scanner.discover("/nonexistent/path/12345")
        assert profile.project_type.value == "unknown"
        assert profile.profile_confidence <= 0.2

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            scanner = Scanner()
            profile = scanner.discover(tmp)
            assert profile.project_type.value == "unknown"
            assert profile.language.value == "unknown"
            assert profile.profile_confidence <= 0.2


class TestScannerDiscoverMaven:
    """Maven project detection + Java inference."""

    def test_detects_maven_and_java(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_maven_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            assert profile.build_system.value == "maven"
            assert profile.language.value == "java"
            assert profile.project_type.value == "java_maven"
            assert profile.build_system.confidence >= 0.8

    def test_detects_aw_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_maven_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            aw_dirs = profile.aw_dirs.value
            assert len(aw_dirs) >= 1
            # Should find the components directory
            found_components = any("components" in d for d in aw_dirs)
            assert found_components, f"Expected components dir in {aw_dirs}"

    def test_detects_base_classes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_maven_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            base_classes = profile.base_classes.value
            assert "BaseTable" in base_classes or "BaseTest" in base_classes

    def test_detects_test_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_maven_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            test_dirs = profile.test_dirs.value
            assert len(test_dirs) >= 1
            found_tests = any("test" in d.lower() for d in test_dirs)
            assert found_tests, f"Expected test dir in {test_dirs}"

    def test_detects_locator_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_maven_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            strategy = profile.locator_strategy.value
            assert strategy != "unknown"
            # @FindBy(id=...) and @FindBy(xpath=...) present
            priorities = profile.locator_priorities.value
            assert len(priorities) >= 1

    def test_detects_naming_camelcase(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_maven_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            naming = profile.naming_style.value
            assert naming in ("camelCase", "mixed")

    def test_overall_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_maven_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            assert profile.profile_confidence >= 0.4


class TestScannerDiscoverPytest:
    """Python/pytest project detection."""

    def test_detects_python_and_pytest(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_pytest_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            assert profile.build_system.value in ("poetry", "setuptools")
            assert profile.language.value == "python"
            assert "python" in profile.project_type.value
            assert profile.build_system.confidence >= 0.8

    def test_detects_test_dirs_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_pytest_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            test_dirs = profile.test_dirs.value
            assert len(test_dirs) >= 1
            found_tests = any("test" in d.lower() for d in test_dirs)
            assert found_tests, f"Expected test dir in {test_dirs}"

    def test_naming_snake_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_pytest_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            naming = profile.naming_style.value
            # Python test files have test_ prefix → snake_case
            assert naming in ("snake_case", "mixed", "unknown")

    def test_overall_confidence_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_pytest_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            assert profile.profile_confidence >= 0.3


class TestScannerDiscoverEdgeCases:
    """Edge cases for the scanner."""

    def test_gradle_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "build.gradle", "// empty gradle")

            scanner = Scanner()
            profile = scanner.discover(tmp)

            assert profile.build_system.value == "gradle"
            assert profile.language.value == "java"
            assert profile.project_type.value == "java_gradle"

    def test_setup_py_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "setup.py", "# empty")

            scanner = Scanner()
            profile = scanner.discover(tmp)

            assert profile.build_system.value == "setuptools"
            assert profile.language.value == "python"

    def test_source_dirs_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            _create_maven_project(tmp)

            scanner = Scanner()
            profile = scanner.discover(tmp)

            source_dirs = profile.source_dirs.value
            assert isinstance(source_dirs, dict)
            assert len(source_dirs) >= 1


# ═══════════════════════════════════════════════════════════════
# ProfileField
# ═══════════════════════════════════════════════════════════════


class TestProfileField:
    """ProfileField value/confidence/source tests."""

    def test_defaults(self):
        pf = ProfileField()
        assert pf.value is None
        assert pf.confidence == 0.5
        assert pf.source == "auto"

    def test_custom_values(self):
        pf = ProfileField(value="java_maven", confidence=0.9, source="pom.xml")
        assert pf.value == "java_maven"
        assert pf.confidence == 0.9
        assert pf.source == "pom.xml"

    def test_to_dict(self):
        pf = ProfileField(value=["a", "b"], confidence=0.7, source="inference")
        d = pf.to_dict()
        assert d == {"value": ["a", "b"], "confidence": 0.7, "source": "inference"}

    def test_from_dict(self):
        d = {"value": "test_value", "confidence": 0.85, "source": "test_source"}
        pf = ProfileField.from_dict(d)
        assert pf.value == "test_value"
        assert pf.confidence == 0.85
        assert pf.source == "test_source"

    def test_from_dict_partial(self):
        d = {"value": "only_value"}
        pf = ProfileField.from_dict(d)
        assert pf.value == "only_value"
        assert pf.confidence == 0.5
        assert pf.source == "auto"

    def test_equality(self):
        a = ProfileField(value="x", confidence=0.5, source="auto")
        b = ProfileField(value="x", confidence=0.5, source="auto")
        c = ProfileField(value="y", confidence=0.5, source="auto")
        assert a == b
        assert a != c
        assert a != "not_a_profile_field"

    def test_repr(self):
        pf = ProfileField(value="hello", confidence=0.75, source="test")
        r = repr(pf)
        assert "hello" in r
        assert "0.75" in r
        assert "test" in r


# ═══════════════════════════════════════════════════════════════
# ProjectProfile
# ═══════════════════════════════════════════════════════════════


class TestProjectProfile:
    """ProjectProfile to_dict/from_dict round-trip."""

    def test_to_dict_all_fields(self):
        p = ProjectProfile()
        d = p.to_dict()
        expected_keys = [
            "project_type", "build_system", "language", "aw_dirs",
            "base_classes", "locator_strategy", "locator_priorities",
            "test_dirs", "naming_style", "source_dirs", "profile_confidence",
        ]
        for key in expected_keys:
            assert key in d, f"Missing key: {key}"

    def test_round_trip_default(self):
        p1 = ProjectProfile()
        d = p1.to_dict()
        p2 = ProjectProfile.from_dict(d)
        assert p2.project_type.value == p1.project_type.value
        assert p2.profile_confidence == p1.profile_confidence

    def test_round_trip_populated(self):
        p1 = ProjectProfile()
        p1.project_type = ProfileField("java_maven", 0.85, "pom.xml")
        p1.build_system = ProfileField("maven", 0.9, "pom.xml")
        p1.language = ProfileField("java", 0.95, "pom.xml")
        p1.aw_dirs = ProfileField(["components/", "pages/"], 0.6, "auto")
        p1.base_classes = ProfileField(["BaseTable", "BasePage"], 0.55, "auto")
        p1.locator_strategy = ProfileField("id", 0.7, "auto")
        p1.locator_priorities = ProfileField(["id", "xpath", "cssSelector"], 0.6, "auto")
        p1.test_dirs = ProfileField(["src/test/java/"], 0.8, "auto")
        p1.naming_style = ProfileField("camelCase", 0.75, "auto")
        p1.source_dirs = ProfileField({"component_aw": "src/main/java/"}, 0.7, "auto")
        p1.profile_confidence = 0.72

        d = p1.to_dict()
        p2 = ProjectProfile.from_dict(d)

        assert p2.project_type.value == "java_maven"
        assert p2.project_type.confidence == 0.85
        assert p2.build_system.value == "maven"
        assert p2.language.value == "java"
        assert p2.aw_dirs.value == ["components/", "pages/"]
        assert p2.base_classes.value == ["BaseTable", "BasePage"]
        assert p2.locator_strategy.value == "id"
        assert p2.locator_priorities.value == ["id", "xpath", "cssSelector"]
        assert p2.test_dirs.value == ["src/test/java/"]
        assert p2.naming_style.value == "camelCase"
        assert p2.source_dirs.value == {"component_aw": "src/main/java/"}
        assert p2.profile_confidence == 0.72

    def test_repr(self):
        p = ProjectProfile()
        p.project_type = ProfileField("java")
        p.language = ProfileField("java")
        r = repr(p)
        assert "java" in r


# ═══════════════════════════════════════════════════════════════
# Parser — UnifiedAST
# ═══════════════════════════════════════════════════════════════


class TestParser:
    """UnifiedAST and parse_file tests."""

    def test_parse_java_class(self):
        java_code = """package com.example;
import java.util.List;

public class MyPage extends BasePage {
    @FindBy(id = "submit")
    private WebElement submitButton;

    public void clickSubmit() {
        submitButton.click();
    }
}"""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = _write_file(tmp, "MyPage.java", java_code)
            ast = parse_file(fpath)

            assert ast.language == "java"
            assert len(ast.classes) == 1
            assert ast.classes[0].name == "MyPage"
            assert ast.classes[0].extends == "BasePage"
            assert len(ast.imports) >= 1

    def test_parse_java_multiple_classes(self):
        java_code = """package com.example;
public class ClassA { }
public class ClassB extends ClassA { }"""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = _write_file(tmp, "Multi.java", java_code)
            ast = parse_file(fpath)

            assert len(ast.classes) == 2
            assert ast.classes[1].extends == "ClassA"

    def test_parse_java_methods(self):
        java_code = """public class TestPage {
    @Test
    public void testSearch() {
        System.out.println("hi");
    }

    private void helper() {
    }
}"""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = _write_file(tmp, "TestPage.java", java_code)
            ast = parse_file(fpath)

            assert len(ast.classes) == 1
            methods = ast.classes[0].methods
            assert len(methods) >= 1
            method_names = [m.name for m in methods]
            assert "testSearch" in method_names

    def test_parse_java_fields(self):
        java_code = """public class MyPage {
    @FindBy(id = "user")
    private WebElement userInput;

    @FindBy(xpath = "//button")
    private WebElement submitButton;
}"""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = _write_file(tmp, "MyPage.java", java_code)
            ast = parse_file(fpath)

            fields = ast.classes[0].fields
            assert len(fields) >= 2
            field_names = [f.name for f in fields]
            assert "userInput" in field_names

    def test_parse_python_class(self):
        py_code = """import pytest
from playwright.sync_api import Page

class HomePage:
    def __init__(self, page: Page):
        self.page = page
        self.search_input = page.get_by_test_id("search-input")

    def search(self, query: str) -> None:
        self.search_input.fill(query)
"""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = _write_file(tmp, "home_page.py", py_code)
            ast = parse_file(fpath)

            assert ast.language == "python"
            assert len(ast.classes) == 1
            assert ast.classes[0].name == "HomePage"
            assert len(ast.classes[0].methods) >= 1

    def test_parse_python_test(self):
        py_code = """import pytest

class TestUserSearch:
    def test_search_by_name(self):
        assert True

    def test_search_empty(self):
        assert False
"""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = _write_file(tmp, "test_search.py", py_code)
            ast = parse_file(fpath)

            cls = ast.classes[0]
            method_names = [m.name for m in cls.methods]
            assert "test_search_by_name" in method_names
            assert "test_search_empty" in method_names

    def test_parse_nonexistent_file(self):
        ast = parse_file("/nonexistent/file.java")
        assert ast.language == "unknown"
        assert len(ast.classes) == 0

    def test_parse_unknown_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            fpath = _write_file(tmp, "readme.txt", "hello world")
            ast = parse_file(fpath)
            assert ast.language == "unknown"

    def test_get_class_names(self):
        java_code = """public class A {} public class B {} public class C {}"""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = _write_file(tmp, "Multi.java", java_code)
            ast = parse_file(fpath)
            assert set(ast.get_class_names()) == {"A", "B", "C"}

    def test_get_all_methods(self):
        java_code = """public class PageA {
    public void methodA() {}
    public void methodB() {}
}
public class PageB {
    public void methodC() {}
}"""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = _write_file(tmp, "Pages.java", java_code)
            ast = parse_file(fpath)
            all_methods = ast.get_all_methods()
            method_names = {m.name for m in all_methods}
            assert method_names >= {"methodA", "methodB", "methodC"}

    def test_find_class(self):
        java_code = """public class LoginPage {} public class HomePage {}"""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = _write_file(tmp, "Pages.java", java_code)
            ast = parse_file(fpath)
            assert ast.find_class("LoginPage") is not None
            assert ast.find_class("HomePage") is not None
            assert ast.find_class("NonExistent") is None

    def test_to_dict(self):
        java_code = """public class TestClass {}"""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = _write_file(tmp, "TestClass.java", java_code)
            ast = parse_file(fpath)
            d = ast.to_dict()
            assert d["language"] == "java"
            assert len(d["classes"]) == 1

    def test_astnode_attrs(self):
        node = ASTNode("method", "testFunc", return_type="void", params=[])
        assert node.type == "method"
        assert node.name == "testFunc"
        assert node.return_type == "void"
        assert node.params == []

    def test_astnode_getitem(self):
        node = ASTNode("class", "MyClass", extends="BaseClass")
        assert node["type"] == "class"
        assert node["name"] == "MyClass"
        assert node["extends"] == "BaseClass"

    def test_astnode_get_default(self):
        node = ASTNode("class", "MyClass")
        assert node.get("extends", "none") == "none"
        assert node.get("type") == "class"


# ═══════════════════════════════════════════════════════════════
# Primitives
# ═══════════════════════════════════════════════════════════════


class TestFileScanner:
    """FileScanner classification tests."""

    def test_scan_finds_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "src/test/MyTest.java", "class MyTest {}")
            _write_file(tmp, "src/main/HomePage.java", "class HomePage {}")
            _write_file(tmp, "src/main/TableAW.java", "class TableAW {}")

            scanner = FileScanner(tmp)
            files = scanner.scan("**/*.java")
            assert len(files) == 3

    def test_classify_aw(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "UserTable.java", "class UserTable {}")
            scanner = FileScanner(tmp)
            assert scanner.classify(f) == "aw"

    def test_classify_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "HomePage.java", "class HomePage {}")
            scanner = FileScanner(tmp)
            assert scanner.classify(f) == "page"

    def test_classify_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "tests/MyTest.java", "class MyTest {}")
            scanner = FileScanner(tmp)
            assert scanner.classify(f) == "test"

    def test_classify_by_parent_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "pages/SomeFile.java", "class SomeFile {}")
            scanner = FileScanner(tmp)
            assert scanner.classify(f) == "page"

    def test_classify_util(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "utils/Helper.java", "class Helper {}")
            scanner = FileScanner(tmp)
            assert scanner.classify(f) == "util"

    def test_classify_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "config/Settings.java", "class Settings {}")
            scanner = FileScanner(tmp)
            assert scanner.classify(f) == "config"

    def test_classify_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "pages/HomePage.java", "class HomePage {}")
            _write_file(tmp, "components/TableAW.java", "class TableAW {}")
            _write_file(tmp, "tests/MyTest.java", "class MyTest {}")

            scanner = FileScanner(tmp)
            classified = scanner.classify_all("**/*.java")
            assert len(classified["page"]) == 1
            assert len(classified["aw"]) == 1
            assert len(classified["test"]) == 1

    def test_count_by_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "pages/A.java", "class A {}")
            _write_file(tmp, "pages/B.java", "class B {}")
            _write_file(tmp, "tests/C.java", "class C {}")

            scanner = FileScanner(tmp)
            counts = scanner.count_by_class("**/*.java")
            assert counts["page"] == 2
            assert counts["test"] == 1


class TestInheritanceAnalyzer:
    """InheritanceAnalyzer tests."""

    def test_analyze_java_extends(self):
        java_code = "public class UserTable extends BaseTable {}"
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "UserTable.java", java_code)
            analyzer = InheritanceAnalyzer(use_ast=False)
            node = analyzer.analyze_file(f)
            assert node is not None
            assert node.class_name == "UserTable"
            assert node.extends_list == ["BaseTable"]

    def test_analyze_java_implements(self):
        java_code = "public class MyPage extends BasePage implements Clickable, Scrollable {}"
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "MyPage.java", java_code)
            analyzer = InheritanceAnalyzer(use_ast=False)
            node = analyzer.analyze_file(f)
            assert node is not None
            assert "BasePage" in node.extends_list
            assert "Clickable" in node.implements_list

    def test_analyze_python_bases(self):
        py_code = "class HomePage(BasePage):\n    pass"
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "home_page.py", py_code)
            analyzer = InheritanceAnalyzer(use_ast=False)
            node = analyzer.analyze_file(f)
            assert node is not None
            assert node.class_name == "HomePage"
            assert "BasePage" in node.extends_list

    def test_base_class_frequencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "A.java", "class A extends Base {}")
            _write_file(tmp, "B.java", "class B extends Base {}")
            _write_file(tmp, "C.java", "class C extends Other {}")

            analyzer = InheritanceAnalyzer(use_ast=False)
            analyzer.analyze_files([
                str(Path(tmp) / "A.java"),
                str(Path(tmp) / "B.java"),
                str(Path(tmp) / "C.java"),
            ])
            freqs = analyzer.get_base_class_frequencies()
            assert freqs.get("Base") == 2
            assert freqs.get("Other") == 1

    def test_inheritance_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "A.java", "class A extends Base {}")
            _write_file(tmp, "B.java", "class B extends Base {}")

            analyzer = InheritanceAnalyzer(use_ast=False)
            analyzer.analyze_files([
                str(Path(tmp) / "A.java"),
                str(Path(tmp) / "B.java"),
            ])
            tree = analyzer.get_inheritance_tree()
            assert "Base" in tree
            assert "A" in tree["Base"]
            assert "B" in tree["Base"]

    def test_interface_implementations(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "A.java",
                         "class A implements Clickable {}")

            analyzer = InheritanceAnalyzer(use_ast=False)
            analyzer.analyze_files([str(Path(tmp) / "A.java")])
            impls = analyzer.get_interface_implementations()
            assert "Clickable" in impls


class TestCallAnalyzer:
    """CallAnalyzer tests."""

    def test_extract_java_calls(self):
        java_code = """public class MyTest {
    public void testSearch() {
        homePage.searchUser("john");
        resultPage.verifyResult("john");
    }
}"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "MyTest.java", java_code)
            analyzer = CallAnalyzer(use_ast=False)
            calls = analyzer.analyze_file(f)
            assert len(calls) >= 2
            target_methods = {c.target_method for c in calls}
            assert "searchUser" in target_methods

    def test_extract_python_calls(self):
        py_code = """class TestSearch:
    def test_search(self):
        self.home_page.search("john")
        self.home_page.click_search()
"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "test_search.py", py_code)
            analyzer = CallAnalyzer(use_ast=False)
            calls = analyzer.analyze_file(f)
            assert len(calls) >= 1

    def test_call_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "TestA.java",
                         """public class TestA {
    public void testA() { page.doA(); }
}""")
            _write_file(tmp, "TestB.java",
                         """public class TestB {
    public void testB() { page.doB(); }
}""")
            analyzer = CallAnalyzer(use_ast=False)
            analyzer.analyze_files([
                str(Path(tmp) / "TestA.java"),
                str(Path(tmp) / "TestB.java"),
            ])
            graph = analyzer.get_call_graph()
            assert len(graph) >= 1

    def test_most_called(self):
        java_code = """public class TestPage {
    public void test1() { page.click(); page.click(); }
    public void test2() { page.click(); }
}"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "TestPage.java", java_code)
            analyzer = CallAnalyzer(use_ast=False)
            analyzer.analyze_file(f)
            most = analyzer.get_most_called(5)
            # "click" should appear (called from "page")
            assert len(most) >= 1


class TestAnnotationExtractor:
    """AnnotationExtractor tests."""

    def test_extract_java_annotations(self):
        java_code = """public class MyTest {
    @Test(priority = 1)
    @FindBy(id = "user")
    private WebElement user;
}"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "MyTest.java", java_code)
            extractor = AnnotationExtractor(use_ast=False)
            annotations = extractor.analyze_file(f)
            names = {a.name for a in annotations}
            assert "Test" in names
            assert "FindBy" in names

    def test_classify_annotations(self):
        java_code = """public class MyTest {
    @Test
    @BeforeClass
    @FindBy(id = "x")
    @Override
    @Component
    public void myTest() {}
}"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "MyTest.java", java_code)
            extractor = AnnotationExtractor(use_ast=False)
            extractor.analyze_file(f)
            cats = extractor.get_category_counts()
            assert cats.get("test", 0) >= 1
            assert cats.get("locator", 0) >= 1

    def test_get_frequencies(self):
        java_code = """@Test @Test @Test
public class MyTest {
    @BeforeClass
    public void setUp() {}
}"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "MyTest.java", java_code)
            extractor = AnnotationExtractor(use_ast=False)
            extractor.analyze_file(f)
            freqs = extractor.get_frequencies()
            assert freqs.get("Test") >= 2
            assert freqs.get("BeforeClass") >= 1

    def test_get_locator_annotations(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "Page.java",
                         """public class Page {
    @FindBy(id = "x")
    private WebElement el;
}""")
            extractor = AnnotationExtractor(use_ast=False)
            extractor.analyze_file(str(Path(tmp) / "Page.java"))
            locator_anns = extractor.get_locator_annotations()
            assert len(locator_anns) >= 1
            assert locator_anns[0].name == "FindBy"

    def test_get_test_annotations(self):
        java_code = """public class TestClass {
    @Test
    public void test1() {}
    @Test
    public void test2() {}
}"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "TestClass.java", java_code)
            extractor = AnnotationExtractor(use_ast=False)
            extractor.analyze_file(f)
            test_anns = extractor.get_test_annotations()
            assert len(test_anns) >= 2

    def test_python_decorators(self):
        py_code = """import pytest
@pytest.fixture
def browser():
    pass

@pytest.mark.slow
def test_slow():
    pass
"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "test_decorators.py", py_code)
            extractor = AnnotationExtractor(use_ast=False)
            annotations = extractor.analyze_file(f)
            names = {a.name for a in annotations}
            assert "pytest.fixture" in names or "pytest.mark.slow" in names or "pytest" in names or "fixture" in names


class TestPatternMiner:
    """PatternMiner tests."""

    def test_mine_simple(self):
        sequences = [
            ["open", "click", "type"],
            ["open", "click", "verify"],
            ["open", "type", "close"],
        ]
        miner = PatternMiner(min_support=0.5, max_pattern_length=3)
        patterns = miner.mine(sequences)
        assert len(patterns) >= 1
        # "open" should appear in at least 2 sequences
        open_patterns = [p for p in patterns if p[0] == ("open",)]
        assert len(open_patterns) >= 1

    def test_mine_empty(self):
        miner = PatternMiner()
        patterns = miner.mine([])
        assert patterns == []

    def test_mine_single_sequence(self):
        sequences = [["a", "b", "c"]]
        miner = PatternMiner(min_support=0.1, max_pattern_length=2)
        patterns = miner.mine(sequences)
        assert len(patterns) >= 1

    def test_sequence_to_string(self):
        assert PatternMiner.sequence_to_string(("a", "b", "c")) == "a → b → c"

    def test_mine_maximal(self):
        sequences = [
            ["open", "click", "type"],
            ["open", "click", "verify"],
        ]
        miner = PatternMiner(min_support=0.5, max_pattern_length=2)
        patterns = miner.mine_maximal_patterns(sequences)
        assert len(patterns) >= 1

    def test_min_support_filter(self):
        sequences = [
            ["a", "b"],  # "c" only in one → filtered
            ["a", "c"],
        ]
        miner = PatternMiner(min_support=1.0, max_pattern_length=2)
        patterns = miner.mine(sequences)
        # Only items with support >= 2.0 should appear (i.e. in both)
        # a appears in both
        a_patterns = [p for p in patterns if p[0] == ("a",)]
        assert len(a_patterns) >= 1


class TestStatisticsCollector:
    """StatisticsCollector tests."""

    def test_collect_from_java(self):
        java_code = """package com.example;
// This is a comment
// Another comment
import java.util.List;

public class HomePage extends BasePage {
    /** doc comment */
    public void clickSubmit() {
        submitButton.click(); // inline comment
    }
}"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "HomePage.java", java_code)
            collector = StatisticsCollector()
            collector.analyze_file(f)
            summary = collector.get_summary()
            assert summary["file_count"] == 1
            assert summary["total_lines"] >= 5

    def test_collect_from_python(self):
        py_code = """# comment
# another comment
import pytest

class TestSearch:
    def test_search_by_name(self):
        # inline comment
        assert True
"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "test_search.py", py_code)
            collector = StatisticsCollector()
            collector.analyze_file(f)
            summary = collector.get_summary()
            assert summary["file_count"] == 1

    def test_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "A.java", "class A { void mA() {} }")
            _write_file(tmp, "B.java", "class B { void mB() {} }")
            _write_file(tmp, "C.java", "class C { void mC() {} }")

            collector = StatisticsCollector()
            collector.analyze_files([
                str(Path(tmp) / "A.java"),
                str(Path(tmp) / "B.java"),
                str(Path(tmp) / "C.java"),
            ])
            summary = collector.get_summary()
            assert summary["file_count"] == 3

    def test_naming_distribution(self):
        java_code = """public class UserTableTest {
    public void testSearchByName() {}
    public void testClickSubmitButton() {}
}"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "UserTableTest.java", java_code)
            collector = StatisticsCollector()
            collector.analyze_file(f)
            summary = collector.get_summary()
            assert summary["dominant_naming_style"] in ("camelCase", "snake_case", "unknown", "lowercase")

    def test_import_frequency(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "A.java",
                         """import java.util.List;
import java.util.Map;
public class A {}""")
            _write_file(tmp, "B.java",
                         """import java.util.List;
public class B {}""")

            collector = StatisticsCollector()
            collector.analyze_files([
                str(Path(tmp) / "A.java"),
                str(Path(tmp) / "B.java"),
            ])
            summary = collector.get_summary()
            top_imports = summary["top_imports"]
            assert "java.util.List" in top_imports


class TestLocatorExtractor:
    """LocatorExtractor tests."""

    def test_extract_java_findby(self):
        java_code = """public class MyPage {
    @FindBy(id = "username")
    private WebElement usernameInput;

    @FindBy(xpath = "//button[@type='submit']")
    private WebElement submitButton;
}"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "MyPage.java", java_code)
            extractor = LocatorExtractor()
            locators = extractor.extract_from_file(f)
            assert len(locators) >= 2
            strategies = {l.strategy for l in locators}
            assert "id" in strategies
            assert "xpath" in strategies

    def test_extract_java_by_calls(self):
        java_code = """public class MyTest {
    public void testClick() {
        driver.findElement(By.id("submitBtn")).click();
        driver.findElement(By.cssSelector(".btn-primary")).click();
    }
}"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "MyTest.java", java_code)
            extractor = LocatorExtractor()
            locators = extractor.extract_from_file(f)
            assert len(locators) >= 2
            values = {l.value for l in locators}
            assert "submitBtn" in values

    def test_extract_python_playwright(self):
        py_code = """from playwright.sync_api import Page

class HomePage:
    def __init__(self, page: Page):
        self.page = page
        self.search = page.get_by_test_id("search-input")
        self.button = page.get_by_role("button", name="Search")
        self.title = page.locator(".title")
"""
        with tempfile.TemporaryDirectory() as tmp:
            f = _write_file(tmp, "home_page.py", py_code)
            extractor = LocatorExtractor()
            locators = extractor.extract_from_file(f)
            assert len(locators) >= 2

    def test_strategy_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "Page.java",
                         """public class Page {
    @FindBy(id = "a")
    @FindBy(id = "b")
    @FindBy(xpath = "//div")
    private WebElement el;
}""")
            extractor = LocatorExtractor()
            extractor.extract_from_file(str(Path(tmp) / "Page.java"))
            usage = extractor.get_strategy_usage()
            assert usage.get("id", 0) >= 2
            assert usage.get("xpath", 0) >= 1

    def test_strategy_priorities(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "Page.java",
                         """public class Page {
    @FindBy(id = "a")
    @FindBy(id = "b")
    @FindBy(xpath = "//c")
    private WebElement el;
}""")
            extractor = LocatorExtractor()
            extractor.extract_from_file(str(Path(tmp) / "Page.java"))
            priorities = extractor.get_strategy_priorities()
            assert priorities[0] == "id"  # most frequent

    def test_primary_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "Page.java",
                         """public class Page {
    @FindBy(xpath = "//a")
    @FindBy(xpath = "//b")
    @FindBy(xpath = "//c")
    @FindBy(id = "d")
    private WebElement el;
}""")
            extractor = LocatorExtractor()
            extractor.extract_from_file(str(Path(tmp) / "Page.java"))
            assert extractor.get_primary_strategy() == "xpath"

    def test_filter_by_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "Page.java",
                         """public class Page {
    @FindBy(id = "a")
    @FindBy(xpath = "//b")
    private WebElement el;
}""")
            extractor = LocatorExtractor()
            extractor.extract_from_file(str(Path(tmp) / "Page.java"))
            id_locs = extractor.get_locators_by_strategy("id")
            assert len(id_locs) == 1
            assert id_locs[0].value == "a"

    def test_unique_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "Page.java",
                         """public class Page {
    @FindBy(id = "a")
    @FindBy(id = "a")  // duplicate
    @FindBy(id = "b")
    private WebElement el;
}""")
            extractor = LocatorExtractor()
            extractor.extract_from_file(str(Path(tmp) / "Page.java"))
            unique = extractor.get_unique_values("id")
            assert unique == {"a", "b"}

    def test_empty_extraction(self):
        extractor = LocatorExtractor()
        locators = extractor.extract_from_file("/nonexistent/file.java")
        assert locators == []

    def test_locator_info_to_dict(self):
        from uibridge.scanner.primitives.locators import LocatorInfo
        li = LocatorInfo(strategy="id", value="submitBtn",
                         filepath="Page.java", class_name="Page",
                         method_name="click")
        d = li.to_dict()
        assert d["strategy"] == "id"
        assert d["value"] == "submitBtn"
        assert d["class_name"] == "Page"

    def test_get_locators_by_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            f1 = _write_file(tmp, "A.java",
                              "public class A { @FindBy(id = \"x\") WebElement el; }")
            f2 = _write_file(tmp, "B.java",
                              "public class B { @FindBy(id = \"y\") WebElement el; }")
            extractor = LocatorExtractor()
            extractor.extract_from_files([f1, f2])
            by_file = extractor.get_locators_by_file()
            assert f1 in by_file
            assert f2 in by_file
            assert len(by_file[f1]) >= 1
            assert len(by_file[f2]) >= 1


# ═══════════════════════════════════════════════════════════════
# Import path tests
# ═══════════════════════════════════════════════════════════════


class TestImportPaths:
    """Verify all public exports are importable."""

    def test_import_scanner(self):
        from uibridge.scanner import Scanner, ProjectProfile, ProfileField
        assert Scanner is not None
        assert ProjectProfile is not None
        assert ProfileField is not None

    def test_import_parser(self):
        from uibridge.scanner import UnifiedAST, parse_file, ASTNode
        assert UnifiedAST is not None
        assert parse_file is not None
        assert ASTNode is not None

    def test_import_primitives(self):
        from uibridge.scanner.primitives import (
            FileScanner, InheritanceAnalyzer, CallAnalyzer,
            AnnotationExtractor, PatternMiner, StatisticsCollector,
            LocatorExtractor,
        )
        assert FileScanner is not None
        assert InheritanceAnalyzer is not None
        assert CallAnalyzer is not None
        assert AnnotationExtractor is not None
        assert PatternMiner is not None
        assert StatisticsCollector is not None
        assert LocatorExtractor is not None


# ═══════════════════════════════════════════════════════════════
# Utility
# ═══════════════════════════════════════════════════════════════

class TestIsUiFilename:
    """_is_ui_filename helper tests."""

    def test_known_suffixes(self):
        assert _is_ui_filename("UserTable") is True
        assert _is_ui_filename("LoginPage") is True
        assert _is_ui_filename("SubmitButton") is True
        assert _is_ui_filename("SearchDialog") is True
        assert _is_ui_filename("FormComponent") is True

    def test_non_ui_names(self):
        assert _is_ui_filename("Helper") is False
        assert _is_ui_filename("Utils") is False
        assert _is_ui_filename("Config") is False
        assert _is_ui_filename("Data") is False
        assert _is_ui_filename("Model") is False
        assert _is_ui_filename("A") is False  # too short
        assert _is_ui_filename("") is False
