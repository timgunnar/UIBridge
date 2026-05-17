"""Actor — Screenplay 模式的核心"""


class Actor:
    """执行 Task 和 Question 的演员"""

    def __init__(self, name: str):
        self.name = name
        self.abilities = {}

    def who_can(self, *abilities):
        for ability in abilities:
            self.abilities[ability.__class__.__name__] = ability
        return self

    def attempts_to(self, *tasks):
        """执行一系列 Task"""
        for task in tasks:
            task.perform_as(self)

    def asks_about(self, question):
        """提出一个 Question，返回答案"""
        return question.answered_by(self)

    def using(self, ability_name: str):
        return self.abilities.get(ability_name)


class Task:
    """Task 基类 — 封装一个业务流程步骤"""
    def perform_as(self, actor: Actor):
        raise NotImplementedError


class Question:
    """Question 基类 — 查询页面状态"""
    def answered_by(self, actor: Actor) -> object:
        raise NotImplementedError
