"""适配器抽象接口 — 每个公司实现一次，注入框架知识"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ── 跨接口共享的数据类型 ──────────────────────

@dataclass
class MethodTemplate:
    """方法模板"""
    name: str
    params: list[dict] = field(default_factory=list)
    action_type: str = ""  # click / input / assertion / wait / read
    returns: str = "None"


@dataclass
class ComponentDef:
    """组件定义"""
    class_name: str
    module: str = ""
    xpath: str = ""
    methods: list[MethodTemplate] = field(default_factory=list)
    base_class: str = ""


@dataclass
class PageComponent:
    """页面中的组件实例"""
    name: str  # search_box, table
    type: str  # InputAW, TableAW
    xpath: str


@dataclass
class PageDef:
    """页面定义"""
    class_name: str
    module: str = ""
    url_pattern: str = ""
    components: list[PageComponent] = field(default_factory=list)


@dataclass
class CallDef:
    """业务 AW 中的调用"""
    component: str = ""
    method: str = ""
    args: list = field(default_factory=list)
    data_binding: str = ""


@dataclass
class BAWOperationDef:
    """业务 AW 操作定义"""
    name: str
    params: list[dict] = field(default_factory=list)
    calls: list[CallDef] = field(default_factory=list)


@dataclass
class BAWDef:
    """业务 AW 定义"""
    class_name: str
    module: str = ""
    operations: list[BAWOperationDef] = field(default_factory=list)


@dataclass
class ImportStyle:
    from_imports: list[str] = field(default_factory=list)  # "from X import Y"
    direct_imports: list[str] = field(default_factory=list)  # "import X"


@dataclass
class FixtureStyle:
    type: str = "function"  # function / class_method / conftest
    template: str = ""


@dataclass
class AssertionStyle:
    type: str = "pytest_assert"  # pytest_assert / self_assert / expect


@dataclass
class ElementInfo:
    tag: str = ""
    attrs: dict = field(default_factory=dict)
    text: str = ""
    ancestor_chain: list[str] = field(default_factory=list)


@dataclass
class TestDataDef:
    file_path: str = ""
    variable_name: str = ""
    fields: dict = field(default_factory=dict)


@dataclass
class ScriptDef:
    class_name: str = ""
    test_name: str = ""
    description: str = ""
    imports: list[str] = field(default_factory=list)
    fixtures: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    data_refs: list[str] = field(default_factory=list)


# ── 五大接口 ────────────────────────────────

class ComponentResolver(ABC):
    """接口 1: 组件解析器 — ARIA role / DOM 信息 → 组件类型"""

    @abstractmethod
    def resolve_type(self, aria_role: str, dom_attrs: dict, snapshot_context: str) -> str:
        ...

    @abstractmethod
    def suggest_name(self, url: str, aria_role: str, dom_attrs: dict) -> str:
        ...

    @abstractmethod
    def get_methods_for_role(self, component_type: str, aria_role: str) -> list[MethodTemplate]:
        ...


class LocatorStrategy(ABC):
    """接口 2: 定位策略 — 元素 → 框架约定的 XPath/选择器"""

    @abstractmethod
    def build_xpath(self, element_info: ElementInfo, dom_context: dict) -> str:
        ...

    @abstractmethod
    def extract_feature_point(self, xpath: str) -> dict:
        ...

    @abstractmethod
    def get_locator_priority(self) -> list[str]:
        ...


class ActionRecognizer(ABC):
    """接口 3: 动作识别器 — DOM 操作序列 → 业务语义"""

    @abstractmethod
    def aggregate(self, raw_steps: list, page_context: dict) -> list:
        ...

    @abstractmethod
    def recognize_pattern(self, sequences: list) -> list[dict]:
        ...


class CodeGenerator(ABC):
    """接口 4: 代码生成器 — 框架级 IR → 代码文件"""

    @abstractmethod
    def generate_component_aw(self, comp_def: ComponentDef) -> str:
        ...

    @abstractmethod
    def generate_business_aw(self, baw_def: BAWDef) -> str:
        ...

    @abstractmethod
    def generate_test_script(self, script_def: ScriptDef) -> str:
        ...

    @abstractmethod
    def generate_test_data(self, data_def: TestDataDef) -> str:
        ...

    @abstractmethod
    def get_import_style(self) -> ImportStyle:
        ...

    @abstractmethod
    def get_assertion_style(self) -> AssertionStyle:
        ...

    @abstractmethod
    def render_step(self, step) -> str:
        """将 FrameworkStep 渲染为目标语言的一行代码。

        参数 step 为 FrameworkStep（engine.ir.framework_call），
        使用 duck typing 接收以避免循环导入。
        """
        ...


class DataFormatter(ABC):
    """接口 5: 测试数据格式化器 — 录制值 → 测试数据文件"""

    @abstractmethod
    def format(self, captured_values: dict, data_context: dict) -> TestDataDef:
        ...

    @abstractmethod
    def get_data_ref_style(self, domain: str) -> str:
        ...


class _PrefixSpan:
    """频繁子序列挖掘算法 — 供所有适配器共享使用"""

    def __init__(self, min_support: int = 3, max_length: int = 8):
        self.min_support = min_support
        self.max_length = max_length

    def mine(self, sequences: list[list[str]]) -> list[tuple]:
        results = []
        self._mine_recursive([], sequences, results)
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _mine_recursive(self, prefix: list, sequences: list[list[str]],
                        results: list[tuple]):
        if len(prefix) >= self.max_length:
            return
        items = {}
        for seq in sequences:
            seen = set()
            for item in seq:
                if item not in seen:
                    items[item] = items.get(item, 0) + 1
                    seen.add(item)
        for item, count in items.items():
            if count >= self.min_support:
                new_prefix = prefix + [item]
                results.append((tuple(new_prefix), count))
                projected = self._project(sequences, item)
                self._mine_recursive(new_prefix, projected, results)

    def _project(self, sequences: list[list[str]], item: str) -> list[list[str]]:
        projected = []
        for seq in sequences:
            for i, s in enumerate(seq):
                if s == item and i + 1 < len(seq):
                    projected.append(seq[i + 1:])
                    break
        return projected
