"""CreateUser — Screenplay Task: 创建用户"""

from ..actor import Task, Actor
from ..interactions.click import Click
from ..interactions.enter import Enter
from ..interactions.select_option import SelectOption
from ...pages.user_page_elements import UserPage


class CreateUser(Task):
    def __init__(self, name: str, age: str):
        self.name = name
        self.age = age

    def perform_as(self, actor: Actor):
        actor.attempts_to(
            Click.on(UserPage.SEARCH_BUTTON),
            Enter.text(self.name).into(UserPage.NAME_INPUT),
            SelectOption.by_value(self.age).from_dropdown(UserPage.AGE_SELECT),
            Click.on(UserPage.CONFIRM_BUTTON),
        )


class SearchUser(Task):
    def __init__(self, keyword: str):
        self.keyword = keyword

    def perform_as(self, actor: Actor):
        actor.attempts_to(
            Enter.text(self.keyword).into(UserPage.SEARCH_INPUT),
            Click.on(UserPage.SEARCH_BUTTON),
        )
