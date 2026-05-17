"""UserCRUD — 用户管理业务 AW"""


class UserCRUD:
    @staticmethod
    def create(page, data: dict):
        """创建用户: 打开搜索 → 填写表单 → 确认 → 等待刷新"""
        page.search_btn.click()
        page.form.wait_loaded()
        page.form.name_input.enter(data["name"])
        page.form.age_select.select_by_value(data["age"])
        page.form.confirm_btn.click()
        page.table.wait_loaded()

    @staticmethod
    def search(page, keyword: str):
        page.search_input.enter(keyword)
        page.search_btn.click()
        page.table.wait_loaded()

    @staticmethod
    def delete(page, row_index: int):
        page.table.click_action(row_index, "删除")
        page.confirm_dialog.wait_visible()
        page.confirm_dialog.confirm()
        page.table.wait_loaded()
