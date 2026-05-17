"""LoginBAW — 登录业务 AW"""


class LoginBAW:
    @staticmethod
    def login(page, username: str, password: str):
        page.username_input.enter(username)
        page.password_input.enter(password)
        page.login_btn.click()
        page.wait_for_url("/dashboard")
