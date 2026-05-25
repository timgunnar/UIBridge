"""Tests for AriaAnalyzer — ARIA snapshot analysis, DOM diff, scene segmentation."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from playwright.sync_api import sync_playwright
from playwright._impl._errors import Error as PlaywrightError

from uibridge.engine.aria_analyzer import AriaAnalyzer, DiscoveredComponent


def _require_browser():
    try:
        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
    except PlaywrightError as e:
        if "Executable doesn't exist" in str(e):
            pytest.skip("Playwright browser not installed — run: playwright install chromium")


# ══════════════════════════════════════════════════════════
# Sample HTML pages for testing
# ══════════════════════════════════════════════════════════

HTML_SIMPLE_TABLE = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Test Table</title></head>
<body>
  <table role="grid" id="user-table" data-testid="user-grid">
    <thead><tr><th>Name</th><th>Email</th></tr></thead>
    <tbody>
      <tr><td>Alice</td><td>alice@example.com</td></tr>
      <tr><td>Bob</td><td>bob@example.com</td></tr>
    </tbody>
  </table>
  <button id="add-btn" aria-label="Add user">Add</button>
</body>
</html>"""

HTML_SIMPLE_FORM = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Test Form</title></head>
<body>
  <form role="form" id="login-form">
    <label for="username">Username</label>
    <input id="username" type="text" name="user" placeholder="Enter username" required>
    <label for="password">Password</label>
    <input id="password" type="password" name="pass" required>
    <button type="submit" id="submit-btn" aria-label="Log in">Login</button>
  </form>
</body>
</html>"""

HTML_MIXED_ARIA = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Mixed ARIA</title></head>
<body>
  <div role="navigation" id="main-nav" data-testid="nav">
    <a href="/home" role="button">Home</a>
    <a href="/about" role="button">About</a>
  </div>
  <div role="combobox" id="country-select">
    <input type="text" placeholder="Select country">
  </div>
  <div role="dialog" id="confirm-dialog" aria-label="Confirm action">
    <p>Are you sure?</p>
    <button>Yes</button>
    <button>No</button>
  </div>
  <div role="tablist" id="settings-tabs">
    <button role="tab">General</button>
    <button role="tab">Security</button>
  </div>
</body>
</html>"""

HTML_DIV_CSS_COMPONENTS = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Div CSS</title></head>
<body>
  <div class="datatable-wrapper" id="div-table">
    <div class="row"><span>Col1</span><span>Col2</span></div>
  </div>
  <div class="form-group" id="div-form">
    <input type="text" placeholder="Name">
    <button class="btn-primary">Submit</button>
  </div>
  <div class="dropdown-menu" id="div-dropdown">
    <a href="#">Option 1</a>
    <a href="#">Option 2</a>
  </div>
  <div class="modal-overlay" id="div-modal">
    <p>Modal content</p>
  </div>
  <div class="sidebar-nav" id="div-sidebar">
    <a href="#">Link 1</a>
  </div>
  <div class="tab-bar" id="div-tabs">
    <span>Tab1</span><span>Tab2</span>
  </div>
  <div class="treeview-container" id="div-tree">
    <ul><li>Node1</li><li>Node2</li></ul>
  </div>
  <div class="text-field-wrapper" id="div-input">
    <input type="text">
  </div>
  <div class="checkbox-group" id="div-checkbox">
    <input type="checkbox">
  </div>
  <div class="card-panel" id="div-card">
    <p>Card content</p>
  </div>
</body>
</html>"""

HTML_CUSTOM_ATTRS = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Custom Attrs</title></head>
<body>
  <div data-module="user-table" id="custom-table">
    <table><tr><td>Data</td></tr></table>
  </div>
  <div data-testid="login-form" id="custom-form">
    <input type="text" name="user">
  </div>
  <div data-component="country-dropdown" id="custom-dropdown">
    <select><option>A</option></select>
  </div>
  <div data-module="confirm-dialog" id="custom-dialog">
    <button>OK</button>
  </div>
  <div data-testid="main-menu" id="custom-menu">
    <button>Item</button>
  </div>
  <div data-component="settings-tab" id="custom-tab">
    <button>Tab</button>
  </div>
  <div data-module="folder-tree" id="custom-tree">
    <ul><li>Item</li></ul>
  </div>
  <div data-testid="unknown-widget" id="custom-unknown">
    <p>Something</p>
  </div>
</body>
</html>"""

HTML_EMPTY = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Empty</title></head>
<body>
  <p>No ARIA roles here.</p>
</body>
</html>"""

HTML_DEEPLY_NESTED = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Deep Nest</title></head>
<body>
  <div>
    <div>
      <div>
        <div>
          <div>
            <form role="form" id="deep-form">
              <div>
                <div>
                  <input id="deep-input" type="text" name="field1">
                  <button id="deep-btn" type="submit">Go</button>
                </div>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>"""

HTML_SINGLE_ELEMENT = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Single</title></head>
<body>
  <button role="button" id="only-btn">Click me</button>
</body>
</html>"""


# ══════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════

def _new_page_with_html(browser, html: str):
    """Create a new page loaded with the given HTML content."""
    page = browser.new_page()
    page.set_content(html)
    page.wait_for_load_state("networkidle")
    return page


# ══════════════════════════════════════════════════════════
# Test DiscoveredComponent dataclass
# ══════════════════════════════════════════════════════════

class TestDiscoveredComponent:
    """DiscoveredComponent dataclass construction and defaults."""

    def test_defaults(self):
        dc = DiscoveredComponent(type="TableAW", aria_role="grid", xpath="//table")
        assert dc.type == "TableAW"
        assert dc.aria_role == "grid"
        assert dc.xpath == "//table"
        assert dc.children == []
        assert dc.inputs == []
        assert dc.interactables == []

    def test_with_children(self):
        dc = DiscoveredComponent(
            type="FormAW", aria_role="form", xpath="//form",
            children=[{"tag": "input", "type": "text"}],
            inputs=[{"tag": "input", "name": "username"}],
            interactables=[{"tag": "button", "text": "Submit"}],
        )
        assert len(dc.children) == 1
        assert len(dc.inputs) == 1
        assert len(dc.interactables) == 1

    def test_equality(self):
        a = DiscoveredComponent(type="TableAW", aria_role="table", xpath="//table")
        b = DiscoveredComponent(type="TableAW", aria_role="table", xpath="//table")
        assert a == b

    def test_inequality_different_type(self):
        a = DiscoveredComponent(type="TableAW", aria_role="table", xpath="//table")
        b = DiscoveredComponent(type="FormAW", aria_role="form", xpath="//form")
        assert a != b


# ══════════════════════════════════════════════════════════
# Test AriaAnalyzer class attributes
# ══════════════════════════════════════════════════════════

class TestAriaAnalyzerClassAttrs:
    """ARIA_TO_COMPONENT and CSS_CLASS_PATTERNS are well-formed."""

    def test_aria_to_component_has_entries(self):
        assert len(AriaAnalyzer.ARIA_TO_COMPONENT) >= 10

    def test_aria_to_component_maps_standard_roles(self):
        mapping = AriaAnalyzer.ARIA_TO_COMPONENT
        assert mapping["table"] == "TableAW"
        assert mapping["grid"] == "TableAW"
        assert mapping["form"] == "FormAW"
        assert mapping["combobox"] == "DropdownAW"
        assert mapping["listbox"] == "DropdownAW"
        assert mapping["menu"] == "MenuAW"
        assert mapping["dialog"] == "DialogAW"
        assert mapping["tablist"] == "TabAW"
        assert mapping["tree"] == "TreeAW"
        assert mapping["navigation"] == "NavAW"

    def test_css_class_patterns_are_tuples(self):
        for pattern in AriaAnalyzer.CSS_CLASS_PATTERNS:
            assert isinstance(pattern, tuple)
            assert len(pattern) == 2
            assert isinstance(pattern[0], str)
            assert isinstance(pattern[1], str)

    def test_css_class_patterns_count(self):
        assert len(AriaAnalyzer.CSS_CLASS_PATTERNS) == 11

    def test_css_class_patterns_regex_compile(self):
        import re
        for regex_str, _ in AriaAnalyzer.CSS_CLASS_PATTERNS:
            re.compile(regex_str)  # should not raise


# ══════════════════════════════════════════════════════════
# Test _guess_component_type (pure function)
# ══════════════════════════════════════════════════════════

class TestGuessComponentType:
    """_guess_component_type classifies attribute values correctly."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _require_browser()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            self.analyzer = AriaAnalyzer(page)
            browser.close()

    def test_table_keywords(self):
        assert self.analyzer._guess_component_type("user-table") == "TableAW"
        assert self.analyzer._guess_component_type("data-grid") == "TableAW"
        assert self.analyzer._guess_component_type("item-list") == "TableAW"

    def test_form_keywords(self):
        assert self.analyzer._guess_component_type("login-form") == "FormAW"
        assert self.analyzer._guess_component_type("edit-panel") == "FormAW"
        assert self.analyzer._guess_component_type("create-dialog") == "FormAW"

    def test_dropdown_keywords(self):
        assert self.analyzer._guess_component_type("country-select") == "DropdownAW"
        assert self.analyzer._guess_component_type("color-dropdown") == "DropdownAW"
        assert self.analyzer._guess_component_type("date-combo") == "DropdownAW"
        assert self.analyzer._guess_component_type("file-picker") == "DropdownAW"

    def test_dialog_keywords(self):
        assert self.analyzer._guess_component_type("confirm-dialog") == "DialogAW"
        assert self.analyzer._guess_component_type("alert-modal") == "DialogAW"
        assert self.analyzer._guess_component_type("info-popup") == "DialogAW"

    def test_menu_keywords(self):
        assert self.analyzer._guess_component_type("main-menu") == "MenuAW"
        assert self.analyzer._guess_component_type("top-nav") == "MenuAW"
        assert self.analyzer._guess_component_type("left-sidebar") == "MenuAW"

    def test_tab_keywords(self):
        assert self.analyzer._guess_component_type("settings-tab") == "TabAW"
        assert self.analyzer._guess_component_type("detail-tabpanel") == "TabAW"

    def test_tree_keywords(self):
        assert self.analyzer._guess_component_type("folder-tree") == "TreeAW"
        assert self.analyzer._guess_component_type("file-treeview") == "TreeAW"

    def test_unknown_fallback(self):
        assert self.analyzer._guess_component_type("random-widget") == "UnknownAW"
        assert self.analyzer._guess_component_type("") == "UnknownAW"
        assert self.analyzer._guess_component_type("xyz-foobar") == "UnknownAW"

    def test_case_insensitive(self):
        assert self.analyzer._guess_component_type("USER-TABLE") == "TableAW"
        assert self.analyzer._guess_component_type("Login-FORM") == "FormAW"


# ══════════════════════════════════════════════════════════
# Test analyze() — standard components (requires browser)
# ══════════════════════════════════════════════════════════

class TestAnalyzeStandardComponents:
    """analyze() discovers standard ARIA role components."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _require_browser()

    def _analyze_html(self, html: str) -> list[DiscoveredComponent]:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, html)
            analyzer = AriaAnalyzer(page)
            result = analyzer.analyze()
            browser.close()
        return result

    def test_simple_table_discovered(self):
        components = self._analyze_html(HTML_SIMPLE_TABLE)
        types = [c.type for c in components]
        assert "TableAW" in types, f"Expected TableAW in {types}"

    def test_simple_form_discovered(self):
        components = self._analyze_html(HTML_SIMPLE_FORM)
        types = [c.type for c in components]
        assert "FormAW" in types, f"Expected FormAW in {types}"

    def test_mixed_aria_all_roles_found(self):
        components = self._analyze_html(HTML_MIXED_ARIA)
        types = set(c.type for c in components)
        assert "NavAW" in types
        assert "DropdownAW" in types
        assert "DialogAW" in types
        assert "TabAW" in types

    def test_empty_page_no_components(self):
        components = self._analyze_html(HTML_EMPTY)
        # No ARIA roles, no data-* attrs, no recognizable CSS classes -> no components
        assert len(components) == 0

    def test_single_button_role(self):
        components = self._analyze_html(HTML_SINGLE_ELEMENT)
        # role="button" is not in ARIA_TO_COMPONENT, but might be picked up by div/button detection
        # We just verify the analyzer runs without error
        assert isinstance(components, list)

    def test_deeply_nested_form_discovered(self):
        components = self._analyze_html(HTML_DEEPLY_NESTED)
        types = [c.type for c in components]
        assert "FormAW" in types, f"Expected FormAW in deeply nested page, got {types}"

    def test_analyze_returns_list(self):
        components = self._analyze_html(HTML_MIXED_ARIA)
        assert isinstance(components, list)
        for c in components:
            assert isinstance(c, DiscoveredComponent)


# ══════════════════════════════════════════════════════════
# Test custom component discovery (data-* attrs)
# ══════════════════════════════════════════════════════════

class TestCustomComponents:
    """_discover_custom_components discovers components from data-* attributes."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _require_browser()

    def test_custom_attrs_form(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        types = [c.type for c in custom]
        assert "FormAW" in types, f"Expected FormAW in custom components, got {types}"

    def test_custom_attrs_table(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        types = [c.type for c in custom]
        assert "TableAW" in types

    def test_custom_attrs_dropdown(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        types = [c.type for c in custom]
        assert "DropdownAW" in types

    def test_custom_attrs_dialog(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        types = [c.type for c in custom]
        assert "DialogAW" in types

    def test_custom_attrs_menu(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        types = [c.type for c in custom]
        assert "MenuAW" in types

    def test_custom_attrs_tab(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        types = [c.type for c in custom]
        assert "TabAW" in types

    def test_custom_attrs_tree(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        types = [c.type for c in custom]
        assert "TreeAW" in types

    def test_custom_attrs_unknown_fallback(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        types = [c.type for c in custom]
        assert "UnknownAW" in types

    def test_custom_attrs_have_correct_aria_role(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        for c in custom:
            assert c.aria_role == "custom"

    def test_custom_attrs_xpath_format(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        for c in custom:
            assert c.xpath  # non-empty
            assert c.xpath.startswith("//"), f"Expected XPath to start with //, got {c.xpath}"

    def test_custom_attrs_interactables_present(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        # At least some components should have interactable children
        interactable_counts = [len(c.interactables) for c in custom]
        assert sum(interactable_counts) > 0, "Expected at least some interactables"


# ══════════════════════════════════════════════════════════
# Test div+css component discovery
# ══════════════════════════════════════════════════════════

class TestDivCssComponents:
    """_discover_div_components finds components via CSS class patterns."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _require_browser()

    def test_div_components_count(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_DIV_CSS_COMPONENTS)
            analyzer = AriaAnalyzer(page)
            div_components = analyzer._discover_div_components()
            browser.close()

        # There are 9 div components in the test page
        # Some may be filtered by dupe XPath, but most should be found
        assert len(div_components) >= 5, f"Expected at least 5 div components, got {len(div_components)}"

    def test_div_table_detected(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_DIV_CSS_COMPONENTS)
            analyzer = AriaAnalyzer(page)
            div_components = analyzer._discover_div_components()
            browser.close()

        types = [c.type for c in div_components]
        assert "TableAW" in types, f"Expected TableAW in {types}"

    def test_div_form_detected(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_DIV_CSS_COMPONENTS)
            analyzer = AriaAnalyzer(page)
            div_components = analyzer._discover_div_components()
            browser.close()

        types = [c.type for c in div_components]
        assert "FormAW" in types

    def test_div_dropdown_detected(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_DIV_CSS_COMPONENTS)
            analyzer = AriaAnalyzer(page)
            div_components = analyzer._discover_div_components()
            browser.close()

        types = [c.type for c in div_components]
        assert "DropdownAW" in types

    def test_div_have_div_role_prefix(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_DIV_CSS_COMPONENTS)
            analyzer = AriaAnalyzer(page)
            div_components = analyzer._discover_div_components()
            browser.close()

        for c in div_components:
            assert c.aria_role.startswith("div+"), f"Expected div+ prefix, got {c.aria_role}"

    def test_div_components_include_children(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_DIV_CSS_COMPONENTS)
            analyzer = AriaAnalyzer(page)
            div_components = analyzer._discover_div_components()
            browser.close()

        # div-form has input + button children
        form_comp = next((c for c in div_components if c.type == "FormAW"), None)
        if form_comp:
            assert len(form_comp.children) > 0, "Form should have child inputs"

    def test_div_empty_page_returns_empty(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_EMPTY)
            analyzer = AriaAnalyzer(page)
            div_components = analyzer._discover_div_components()
            browser.close()

        assert div_components == []


# ══════════════════════════════════════════════════════════
# Test standard component details (XPath, children, inputs)
# ══════════════════════════════════════════════════════════

class TestStandardComponentDetails:
    """Components have correct XPaths, children, inputs, interactables."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _require_browser()

    def test_form_has_inputs(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_SIMPLE_FORM)
            analyzer = AriaAnalyzer(page)
            components = analyzer.analyze()
            browser.close()

        form = next((c for c in components if c.type == "FormAW"), None)
        assert form is not None, "Form not found"
        assert len(form.inputs) >= 2, f"Expected at least 2 inputs, got {len(form.inputs)}"

    def test_form_inputs_have_required_flag(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_SIMPLE_FORM)
            analyzer = AriaAnalyzer(page)
            components = analyzer.analyze()
            browser.close()

        form = next((c for c in components if c.type == "FormAW"), None)
        assert form is not None, "Form not found"
        required_inputs = [i for i in form.inputs if i.get("required")]
        assert len(required_inputs) >= 1, "Expected at least one required input"

    def test_dialog_has_interactables(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_MIXED_ARIA)
            analyzer = AriaAnalyzer(page)
            components = analyzer.analyze()
            browser.close()

        dialog = next((c for c in components if c.type == "DialogAW"), None)
        assert dialog is not None, "Dialog not found"
        assert len(dialog.interactables) >= 2, f"Expected at least 2 buttons, got {dialog.interactables}"

    def test_nav_has_interactables(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_MIXED_ARIA)
            analyzer = AriaAnalyzer(page)
            components = analyzer.analyze()
            browser.close()

        nav = next((c for c in components if c.type == "NavAW"), None)
        assert nav is not None, "Nav not found"
        assert len(nav.interactables) >= 2, "Expected nav links as interactables"

    def test_standard_xpath_not_empty(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_MIXED_ARIA)
            analyzer = AriaAnalyzer(page)
            components = analyzer.analyze()
            browser.close()

        for c in components:
            assert c.xpath, f"XPath should not be empty for {c.type}/{c.aria_role}"
            assert c.xpath.startswith("//"), f"XPath should start with //, got {c.xpath}"


# ══════════════════════════════════════════════════════════
# Edge cases
# ══════════════════════════════════════════════════════════

class TestEdgeCases:
    """Unusual inputs and edge case handling."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _require_browser()

    def test_analyze_does_not_raise_on_simple_page(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_EMPTY)
            analyzer = AriaAnalyzer(page)
            result = analyzer.analyze()
            browser.close()
        assert isinstance(result, list)

    def test_standard_components_no_duplicates(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_SIMPLE_TABLE)
            analyzer = AriaAnalyzer(page)
            standard = analyzer._discover_standard_components()
            browser.close()

        # Table should appear only once
        tables = [c for c in standard if c.type == "TableAW"]
        assert len(tables) <= 1, f"Expected at most 1 TableAW, got {len(tables)}"

    def test_custom_components_no_duplicate_values(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_CUSTOM_ATTRS)
            analyzer = AriaAnalyzer(page)
            custom = analyzer._discover_custom_components()
            browser.close()

        # Each component should have a unique xpath
        xpaths = [c.xpath for c in custom]
        assert len(xpaths) == len(set(xpaths)), f"Duplicate XPaths found: {xpaths}"

    def test_deeply_nested_still_finds_inputs(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, HTML_DEEPLY_NESTED)
            analyzer = AriaAnalyzer(page)
            components = analyzer.analyze()
            browser.close()

        form = next((c for c in components if c.type == "FormAW"), None)
        assert form is not None, "Form not found in deeply nested page"
        assert len(form.inputs) >= 1, "Expected input elements inside the form"

    def test_multiple_aria_roles_on_same_element(self):
        html = """<!DOCTYPE html>
        <html><head><meta charset="UTF-8"></head><body>
          <div role="dialog" aria-label="Multi" id="multi-dialog">
            <form><input type="text" name="q"><button>Go</button></form>
          </div>
        </body></html>"""
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = _new_page_with_html(browser, html)
            analyzer = AriaAnalyzer(page)
            result = analyzer.analyze()
            browser.close()
        assert isinstance(result, list)
        types = [c.type for c in result]
        assert "DialogAW" in types

    def test_guess_component_type_edge_cases(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            analyzer = AriaAnalyzer(page)
            browser.close()

        # Very long string
        assert analyzer._guess_component_type("table" * 50) == "TableAW"
        # String with special characters
        assert analyzer._guess_component_type("form-edit/create") == "FormAW"
        # Single char
        assert analyzer._guess_component_type("x") == "UnknownAW"
