"""Abilities — Actor 的能力（如浏览网页）"""

from playwright.sync_api import Page


class BrowseTheWeb:
    """浏览网页的能力"""

    def __init__(self, page: Page):
        self.page = page

    def navigate_to(self, url: str):
        self.page.goto(url)

    def current_url(self) -> str:
        return self.page.url
