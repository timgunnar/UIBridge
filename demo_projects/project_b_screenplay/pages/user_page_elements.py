"""UserPage — Screenplay 页面元素定位（非 POM，只存 locator）"""


class Target:
    """定位目标"""
    def __init__(self, locator: str, description: str = ""):
        self.locator = locator
        self.description = description


class UserPage:
    """用户管理页面 — 元素定位器集合"""

    BASE = "//div[@data-module='user-table']"
    FORM_BASE = "//div[@data-module='user-form']"

    TABLE_ROW = f"({BASE}//tr[contains(@class, 'data-row')])[contains(., '{{text}}')]"

    NAME_INPUT = Target(
        "//form//input[@name='userName']",
        "用户名输入框"
    )
    AGE_SELECT = Target(
        "//form//select[@name='age']",
        "年龄下拉框"
    )
    SEARCH_INPUT = Target(
        "//div[@data-action='search']//input",
        "搜索输入框"
    )
    SEARCH_BUTTON = Target(
        "//div[@data-action='search']//button",
        "搜索按钮"
    )
    CONFIRM_BUTTON = Target(
        "//form//button[contains(., '确认')]",
        "确认按钮"
    )
