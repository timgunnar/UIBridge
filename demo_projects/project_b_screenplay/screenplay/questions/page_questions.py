"""PageQuestions — Screenplay Question: 查询页面状态"""

from ..actor import Question, Actor
from ...pages.user_page_elements import UserPage


class IsPageLoaded(Question):
    def __init__(self, target):
        self.target = target

    def answered_by(self, actor: Actor) -> bool:
        browser = actor.using("BrowseTheWeb")
        try:
            browser.page.locator(self.target.locator).wait_for(state="visible", timeout=5000)
            return True
        except Exception:
            return False


class HasRowContaining(Question):
    def __init__(self, text: str):
        self.text = text

    def answered_by(self, actor: Actor) -> bool:
        browser = actor.using("BrowseTheWeb")
        row = UserPage.TABLE_ROW.format(text=self.text)
        return browser.page.locator(row).count() > 0
