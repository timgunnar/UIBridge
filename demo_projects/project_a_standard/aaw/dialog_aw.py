"""DialogAW — 弹窗组件"""

from .base_aw import BaseAW


class DialogAW(BaseAW):
    def __init__(self, page, xpath: str):
        super().__init__(page, xpath)

    def wait_visible(self):
        self.page.locator(f"xpath={self.xpath}").wait_for(state="visible")

    def confirm(self):
        confirm_btn = f"{self.xpath}//button[contains(@class, 'confirm')]"
        self.page.locator(f"xpath={confirm_btn}").click()

    def cancel(self):
        cancel_btn = f"{self.xpath}//button[contains(@class, 'cancel')]"
        self.page.locator(f"xpath={cancel_btn}").click()
