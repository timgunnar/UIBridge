"""InputAW — 输入框组件"""

from .base_aw import BaseAW


class InputAW(BaseAW):
    def __init__(self, page, xpath: str):
        super().__init__(page, xpath)

    def enter(self, text: str):
        self.page.locator(f"xpath={self.xpath}").fill(text)

    def clear(self):
        self.page.locator(f"xpath={self.xpath}").clear()

    def get_value(self) -> str:
        return self.page.locator(f"xpath={self.xpath}").input_value()

    def assert_value(self, expected: str):
        actual = self.get_value()
        assert actual == expected, f"Expected '{expected}', got '{actual}'"
