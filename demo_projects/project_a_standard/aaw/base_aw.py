"""BaseAW — 所有组件 AW 的基类"""


class BaseAW:
    def __init__(self, page, xpath: str):
        self.page = page
        self.xpath = xpath

    def wait_visible(self, timeout: int = 10):
        self.page.locator(f"xpath={self.xpath}").wait_for(state="visible", timeout=timeout * 1000)
