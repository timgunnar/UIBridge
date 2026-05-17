"""Select — Screenplay 交互: 选择下拉选项"""

from ..actor import Task, Actor


class SelectOption(Task):
    def __init__(self, value: str):
        self.value = value
        self._target = None

    def from_dropdown(self, target):
        self._target = target
        return self

    def perform_as(self, actor: Actor):
        browser = actor.using("BrowseTheWeb")
        browser.page.locator(self._target.locator).select_option(value=self.value)

    @staticmethod
    def by_value(value: str):
        return SelectOption(value)
