"""TableAW — 表格组件"""

from .base_aw import BaseAW


class TableAW(BaseAW):
    def __init__(self, page, xpath: str):
        super().__init__(page, xpath)
        self._row_loc = f"({xpath}//tr[contains(@class, 'data-row')])"
        self._cell_loc = f"{xpath}//td"
        self._header_checkbox = f"{xpath}//thead//input[@type='checkbox']"

    def wait_loaded(self, timeout: int = 10):
        self.page.locator(f"xpath={self._row_loc}").first.wait_for(state="visible", timeout=timeout * 1000)

    def get_row_count(self) -> int:
        return self.page.locator(f"xpath={self._row_loc}").count()

    def click_row(self, index: int):
        self.page.locator(f"xpath={self._row_loc}[{index}]").click()

    def get_cell_text(self, row: int, col: int) -> str:
        return self.page.locator(f"xpath={self._row_loc}[{row}]{self._cell_loc}[{col}]").inner_text()

    def assert_row_contains(self, text: str):
        loc = f"{self._row_loc}[contains(., '{text}')]"
        self.page.locator(f"xpath={loc}").first.wait_for(state="visible")

    def filter_by_column(self, col: int, value: str):
        filt = f"{self.xpath}//thead//th[{col}]//input[@placeholder='筛选']"
        self.page.locator(f"xpath={filt}").fill(value)
        self.page.keyboard.press("Enter")

    def select_all(self):
        self.page.locator(f"xpath={self._header_checkbox}").click()

    def click_action(self, row_index: int, action_text: str):
        btn = f"{self._row_loc}[{row_index}]//button[contains(., '{action_text}')]"
        self.page.locator(f"xpath={btn}").click()
