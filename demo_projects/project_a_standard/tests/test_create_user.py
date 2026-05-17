"""用户创建测试"""

import pytest
from baw.user_crud import UserCRUD
from pages.user_management_page import UserManagementPage
from test_data.user_data import VALID_USER


class TestUserCreate:
    @pytest.fixture
    def user_page(self, page):
        pg = UserManagementPage(page)
        pg.goto()
        return pg

    def test_create_single_user(self, user_page):
        UserCRUD.create(user_page, VALID_USER)
        user_page.table.assert_row_contains(VALID_USER["name"])

    def test_search_user(self, user_page):
        UserCRUD.search(user_page, VALID_USER["name"])
        user_page.table.assert_row_contains(VALID_USER["name"])
