"""LoginPage — 登录页面"""

from aaw.input_aw import InputAW
from aaw.button_aw import ButtonAW


class LoginPage:
    def __init__(self, page):
        self.page = page
        self.username_input = InputAW(page, "//input[@name='username']")
        self.password_input = InputAW(page, "//input[@name='password']")
        self.login_btn = ButtonAW(page, "//button[@type='submit']")

    def goto(self):
        self.page.goto("/login")
