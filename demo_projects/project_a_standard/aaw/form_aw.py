"""FormAW — 表单组件"""

from .base_aw import BaseAW


class FormAW(BaseAW):
    def __init__(self, page, xpath: str):
        super().__init__(page, xpath)

    def wait_loaded(self):
        self.page.locator(f"xpath={self.xpath}").wait_for(state="visible")

    def submit(self):
        submit_btn = f"{self.xpath}//button[@type='submit']"
        self.page.locator(f"xpath={submit_btn}").click()

    def reset(self):
        reset_btn = f"{self.xpath}//button[@type='reset']"
        self.page.locator(f"xpath={reset_btn}").click()
