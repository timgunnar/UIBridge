"""UserFactory — 用户测试数据工厂"""


class UserFactory:
    @staticmethod
    def valid_user() -> dict:
        return {"name": "张三", "age": "25"}

    @staticmethod
    def admin_user() -> dict:
        return {"name": "管理员", "age": "30"}

    @staticmethod
    def minimal_user() -> dict:
        return {"name": "测试", "age": "18"}
