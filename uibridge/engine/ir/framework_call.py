"""IR v3: FrameworkCallSequence — 映射层的输出，框架级 API 调用序列"""

from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class StepKind(Enum):
    DECL = "decl"          # 变量声明
    ACTION = "action"      # 组件操作调用
    ASSERT = "assert"      # 断言
    NAVIGATE = "navigate"  # 页面导航
    COMMENT = "comment"    # 注释


@dataclass
class MethodCall:
    """框架方法调用 — 结构化的非 raw 调用"""
    method: str = ""            # 方法名: "click", "enter", "get_row_count"
    component: str = ""         # 组件变量名: "user_table", "search_box"
    args: list = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)
    is_raw: bool = False        # 仅用于兼容旧测试，新代码不使用

    def to_dict(self) -> dict:
        return {
            "method": self.method, "component": self.component,
            "args": self.args, "kwargs": self.kwargs, "is_raw": self.is_raw,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MethodCall":
        return cls(method=d.get("method", ""), component=d.get("component", ""),
                   args=d.get("args", []), kwargs=d.get("kwargs", {}),
                   is_raw=d.get("is_raw", False))


@dataclass
class Decl:
    """变量声明"""
    var: str  # 变量名
    type: str  # 类型名
    factory: str = ""  # PageFactory.create / context.new_page
    resolver: str = ""  # PageResolver.resolve

    def to_dict(self) -> dict:
        return {"var": self.var, "type": self.type,
                "factory": self.factory, "resolver": self.resolver}

    @classmethod
    def from_dict(cls, d: dict) -> "Decl":
        return cls(var=d.get("var", ""), type=d.get("type", ""),
                   factory=d.get("factory", ""), resolver=d.get("resolver", ""))


@dataclass
class FrameworkStep:
    """框架级步骤"""
    kind: StepKind = StepKind.ACTION
    decl: Decl | None = None
    calls: list[MethodCall] = field(default_factory=list)
    comment: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "decl": self.decl.to_dict() if self.decl else None,
            "calls": [c.to_dict() for c in self.calls],
            "comment": self.comment,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FrameworkStep":
        decl = Decl.from_dict(d["decl"]) if d.get("decl") else None
        calls = [MethodCall.from_dict(c) for c in d.get("calls", [])]
        return cls(kind=StepKind(d.get("kind", "action")),
                   decl=decl, calls=calls, comment=d.get("comment", ""))


@dataclass
class TestCaseIR:
    """框架级测试用例"""
    name: str
    description: str = ""
    imports: list[str] = field(default_factory=list)
    fixtures: list[str] = field(default_factory=list)
    steps: list[FrameworkStep] = field(default_factory=list)
    review_needed: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description,
            "imports": self.imports, "fixtures": self.fixtures,
            "steps": [s.to_dict() for s in self.steps],
            "review_needed": self.review_needed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TestCaseIR":
        return cls(name=d.get("name", ""), description=d.get("description", ""),
                   imports=d.get("imports", []), fixtures=d.get("fixtures", []),
                   steps=[FrameworkStep.from_dict(s) for s in d.get("steps", [])],
                   review_needed=d.get("review_needed", False))


@dataclass
class FrameworkCallSequence:
    """IR v3"""
    version: str = "3.0"
    meta: dict = field(default_factory=dict)
    test_cases: list[TestCaseIR] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version, "meta": self.meta,
            "test_cases": [tc.to_dict() for tc in self.test_cases],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FrameworkCallSequence":
        return cls(version=d.get("version", "3.0"), meta=d.get("meta", {}),
                   test_cases=[TestCaseIR.from_dict(tc) for tc in d.get("test_cases", [])])
