"""Click — Screenplay 交互: 点击元素"""

from ..actor import Task, Actor


class Click(Task):
    def __init__(self, target):
        self.target = target  # Target 对象（含 locator）

    def perform_as(self, actor: Actor):
        browser = actor.using("BrowseTheWeb")
        browser.page.locator(self.target.locator).click()

    @staticmethod
    def on(target):
        return Click(target)
