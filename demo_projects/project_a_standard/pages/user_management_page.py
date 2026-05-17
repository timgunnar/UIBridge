"""UserManagementPage — 用户管理页面"""

from aaw.table_aw import TableAW
from aaw.form_aw import FormAW
from aaw.input_aw import InputAW
from aaw.button_aw import ButtonAW
from aaw.dropdown_aw import DropdownAW
from aaw.dialog_aw import DialogAW


class UserManagementPage:
    def __init__(self, page):
        self.page = page
        # 组件 XPath 特征点
        self.table = TableAW(page, "//div[@data-module='user-table']")
        self.form = FormAW(page, "//div[@data-module='user-form']")
        self.name_input = InputAW(page, "//form//input[@name='userName']")
        self.age_select = DropdownAW(page, "//form//select[@name='age']")
        self.search_input = InputAW(page, "//div[@data-action='search']//input")
        self.search_btn = ButtonAW(page, "//div[@data-action='search']//button")
        self.confirm_btn = ButtonAW(page, "//form//button[contains(., '确认')]")
        self.confirm_dialog = DialogAW(page, "//div[@data-module='confirm-dialog']")

    def goto(self):
        self.page.goto("/user/manage")

    def wait_loaded(self):
        self.table.wait_loaded()
