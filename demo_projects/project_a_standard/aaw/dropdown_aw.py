"""DropdownAW — 下拉选择组件"""

from .base_aw import BaseAW


class DropdownAW(BaseAW):
    def __init__(self, page, xpath: str):
        super().__init__(page, xpath)

    def select_by_value(self, value: str):
        self.page.locator(f"xpath={self.xpath}").select_option(value=value)

    def select_by_index(self, index: int):
        self.page.locator(f"xpath={self.xpath}").select_option(index=index)

    def get_selected(self) -> str:
        return self.page.locator(f"xpath={self.xpath}//option[@selected]").inner_text()
