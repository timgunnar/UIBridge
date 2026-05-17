"""Enter — Screenplay 交互: 输入文本"""

from ..actor import Task, Actor


class Enter(Task):
    def __init__(self, text: str):
        self.text = text
        self._target = None

    def into(self, target):
        self._target = target
        return self

    def perform_as(self, actor: Actor):
        browser = actor.using("BrowseTheWeb")
        browser.page.locator(self._target.locator).fill(self.text)

    @staticmethod
    def text(value: str):
        return Enter(value)
