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


@dataclass
class Decl:
    """变量声明"""
    var: str  # 变量名
    type: str  # 类型名
    factory: str = ""  # PageFactory.create / context.new_page
    resolver: str = ""  # PageResolver.resolve


@dataclass
class FrameworkStep:
    """框架级步骤"""
    kind: StepKind = StepKind.ACTION
    decl: Decl | None = None
    calls: list[MethodCall] = field(default_factory=list)
    comment: str = ""


@dataclass
class TestCaseIR:
    """框架级测试用例"""
    name: str
    description: str = ""
    imports: list[str] = field(default_factory=list)
    fixtures: list[str] = field(default_factory=list)
    steps: list[FrameworkStep] = field(default_factory=list)
    review_needed: bool = False


@dataclass
class FrameworkCallSequence:
    """IR v3"""
    version: str = "3.0"
    meta: dict = field(default_factory=dict)
    test_cases: list[TestCaseIR] = field(default_factory=list)
