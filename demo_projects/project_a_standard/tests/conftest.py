"""pytest fixtures for project_a_standard demo tests"""

import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="session")
def browser():
    """Session-scoped browser instance."""
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b


@pytest.fixture
def page(browser):
    """Function-scoped page with clean context."""
    context = browser.new_context()
    pg = context.new_page()
    yield pg
    context.close()
