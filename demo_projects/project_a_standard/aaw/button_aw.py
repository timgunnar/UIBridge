"""ButtonAW — 按钮组件"""

from .base_aw import BaseAW


class ButtonAW(BaseAW):
    def __init__(self, page, xpath: str):
        super().__init__(page, xpath)

    def click(self):
        self.page.locator(f"xpath={self.xpath}").click()

    def assert_enabled(self):
        assert self.page.locator(f"xpath={self.xpath}").is_enabled()

    def assert_disabled(self):
        assert not self.page.locator(f"xpath={self.xpath}").is_enabled()
