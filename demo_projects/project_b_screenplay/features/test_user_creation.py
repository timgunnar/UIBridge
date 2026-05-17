"""用户创建测试 — Screenplay 风格"""

import pytest
from playwright.sync_api import Page

from screenplay.actor import Actor
from screenplay.abilities import BrowseTheWeb
from screenplay.tasks.create_user import CreateUser, SearchUser
from screenplay.questions.page_questions import IsPageLoaded, HasRowContaining
from pages.user_page_elements import UserPage
from factories.user_factory import UserFactory


class DescribeUserCreation:
    """作为一个管理员，我希望能够创建新用户"""

    @pytest.fixture
    def actor(self, page: Page):
        user = Actor("管理员").who_can(BrowseTheWeb(page))
        user.using("BrowseTheWeb").navigate_to("/user/manage")
        return user

    def test_should_create_a_single_user(self, actor: Actor):
        data = UserFactory.valid_user()
        actor.attempts_to(CreateUser(data["name"], data["age"]))
        assert actor.asks_about(HasRowContaining(data["name"]))

    def test_should_search_for_existing_user(self, actor: Actor):
        data = UserFactory.valid_user()
        actor.attempts_to(SearchUser(data["name"]))
        assert actor.asks_about(HasRowContaining(data["name"]))
