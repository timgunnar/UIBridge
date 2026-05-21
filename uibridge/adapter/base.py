"""适配器抽象接口 — 每个公司实现一次，注入框架知识"""

import re
from pathlib import Path
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


def scan_java_source_for_package(project_root: str) -> Optional[str]:
    """扫描项目 .java 源码中的 package 声明，推断基础包名。

    返回值：
    - 包名字符串（如 "com.enterprise"）：检测到统一包名
    - ""（空字符串）：存在 .java 文件但无 package 声明（默认包）
    - None：未找到任何 .java 文件，无法推断
    """
    root = Path(project_root)
    java_files = list(root.glob("**/*.java"))
    if not java_files:
        return None

    packages: list[str] = []
    for f in java_files[:50]:
        try:
            content = f.read_text(encoding="utf-8")
            m = re.search(r'^\s*package\s+([a-zA-Z_][\w.]*)\s*;', content, re.MULTILINE)
            if m:
                packages.append(m.group(1))
        except Exception:
            pass

    if not packages:
        return ""  # 默认包

    if len(packages) == 1:
        return packages[0]

    parts_list = [p.split(".") for p in packages]
    common = parts_list[0]
    for p in parts_list[1:]:
        i = 0
        while i < min(len(common), len(p)) and common[i] == p[i]:
            i += 1
        common = common[:i]
    return ".".join(common) if common else max(set(packages), key=packages.count)


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


def _to_java_type(value) -> str:
    """Map Python type to Java primitive/boxed type name.

    Used by Java adapters to declare correct field types in generated code.
    """
    mapping = {bool: "boolean", int: "int", float: "double", str: "String", type(None): "String"}
    return mapping.get(type(value), "String")


def to_java_class_name(name: str) -> str:
    """将 snake_case / kebab-case 转为 PascalCase（Java 类名）"""
    parts = re.split(r'[-_\s]', name)
    return "".join(p.capitalize() for p in parts if p)


def post_process_java_code(code: str, package: str) -> str:
    """后处理 Java 生成代码：默认包时移除 package 行和以 . 开头的 import。

    若 package 非空（有包名），直接返回；否则清理默认包残留。
    """
    if package:
        return code
    code = re.sub(r'^\s*package\s+\.[^;]+;\s*\n?', '', code, flags=re.MULTILINE)
    code = re.sub(r'^\s*import\s+\.[^;]+;\s*\n?', '', code, flags=re.MULTILINE)
    code = re.sub(r'\n{3,}', '\n\n', code)
    return code.strip() + '\n'


def format_action_params(call) -> str:
    """将 call.args / call.kwargs 格示为 Java 方法调用的参数串。

    args 中的字符串用双引号包裹，kwargs 的值同理。
    返回如 '"user", "pass"' 这样的参数字符串。
    """
    parts = []
    for a in call.args:
        parts.append(f'"{a}"' if isinstance(a, str) else str(a))
    for v in call.kwargs.values():
        parts.append(f'"{v}"' if isinstance(v, str) else str(v))
    return ", ".join(parts)


def sanitize_identifier(name: str, fallback_tag: str = "elem", fallback_index: int = 0) -> str:
    """Convert raw label/text to a valid Python/Java identifier.

    Strips non-ASCII characters, punctuation, and CSS selector fragments.
    Falls back to tag+index when the sanitized result is empty.
    """
    if not name:
        return f"{fallback_tag}_{fallback_index}" if fallback_tag else f"elem_{fallback_index}"
    # Replace spaces and hyphens with underscores
    safe = name.replace(" ", "_").replace("-", "_")
    # Remove any character that is not ASCII alphanumeric or underscore
    safe = re.sub(r'[^a-zA-Z0-9_]', '', safe)
    # Collapse multiple underscores
    safe = re.sub(r'_+', '_', safe).strip('_')
    # Ensure it doesn't start with a digit
    if safe and safe[0].isdigit():
        safe = '_' + safe
    if not safe:
        safe = f"{fallback_tag}_{fallback_index}" if fallback_tag else f"elem_{fallback_index}"
    return safe.lower() if safe else "unnamed"


@dataclass
class AssertionStyle:
    type: str = "pytest_assert"  # pytest_assert / self_assert / expect


# ── 断言候选解析：字符串 → 结构化数据 → 可执行代码 ──────────

ASSERT_PATTERNS = [
    (r"assert page\.url == \"(.+?)\"", "url_equals"),
    (r"assert element '([^']+)' \((\w+)\) is visible", "element_visible"),
    (r"assert element '([^']+)' \((\w+)\) is absent", "element_absent"),
    (r"assert text of '([^']+)' == \"(.+?)\"", "text_equals"),
    (r"assert count of (\w+) elements (increased|decreased)", "count_changed"),
    (r"assert layout of '([^']+)' is stable", "layout_stable"),
]


def parse_assertion_candidate(candidate: str) -> dict:
    """将断言候选字符串解析为结构化数据，供适配器生成可执行代码。"""
    for pattern, atype in ASSERT_PATTERNS:
        m = re.match(pattern, candidate)
        if m:
            result = {"type": atype}
            if atype == "url_equals":
                result["url"] = m.group(1)
            elif atype in ("element_visible", "element_absent"):
                result["element"] = m.group(1)
                result["role"] = m.group(2)
            elif atype == "text_equals":
                result["element"] = m.group(1)
                result["text"] = m.group(2)
            elif atype == "count_changed":
                result["role"] = m.group(1)
                result["direction"] = m.group(2)
            elif atype == "layout_stable":
                result["element"] = m.group(1)
            return result
    # 通用匹配
    m = re.match(r"assert (.+)", candidate)
    if m:
        return {"type": "generic", "message": m.group(1)}
    return {"type": "unknown", "raw": candidate}


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

    def _resolve_aria_map(self) -> dict:
        """查询 KB 获取 ARIA role 映射，回退到子类的 ARIA_MAP 常量。"""
        kb = getattr(self, 'kb', None)
        aria_map = getattr(self, 'ARIA_MAP', {})
        if kb:
            for item in kb.store.list_category("conventions"):
                if "component_types" in item.key:
                    return item.value.get("aria_role_map", aria_map)
        return aria_map


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

    def _resolve_locator_priority(self) -> list[str]:
        """查询 KB 获取定位器优先级，回退到子类的 PRIORITY 常量。"""
        kb = getattr(self, 'kb', None)
        if kb:
            kb_conventions = kb.get_locator_conventions()
            if kb_conventions and "priority" in kb_conventions:
                return kb_conventions["priority"]
        return getattr(self, 'PRIORITY', ["id", "name", "css", "xpath"])


class ActionRecognizer(ABC):
    """接口 3: 动作识别器 — DOM 操作序列 → 业务语义"""

    @abstractmethod
    def aggregate(self, raw_steps: list, page_context: dict) -> list:
        ...

    def _match_kb_patterns(self, actions: list, kb_manager=None) -> list:
        """Match action sequences against KB patterns, merge recognized sub-sequences."""
        if not kb_manager or len(actions) < 2:
            return actions

        try:
            patterns = kb_manager.store.list_category("patterns")
        except Exception:
            return actions
        if not patterns:
            return actions

        # Build action name sequence for matching
        action_names = []
        for a in actions:
            name = a.get("action", "") if isinstance(a, dict) else str(a)
            action_names.append(name)

        # Check each KB pattern against the action sequence
        merged = list(actions)
        for pattern_item in patterns:
            pattern_actions = pattern_item.value.get("actions") or pattern_item.value.get("steps", [])
            if not pattern_actions or len(pattern_actions) < 2:
                continue

            # Simple subsequence match: find pattern_actions in action_names
            for i in range(len(action_names) - len(pattern_actions) + 1):
                match = True
                for j, pa in enumerate(pattern_actions):
                    if pa.lower() not in action_names[i + j].lower():
                        match = False
                        break
                if match:
                    # Merge the matching subsequence
                    pattern_name = pattern_item.key
                    # Strip "pattern." prefix if present
                    if pattern_name.startswith("pattern."):
                        pattern_name = pattern_name[len("pattern."):]
                    merged_step = {
                        "raw_steps": [],
                        "component": merged[i].get("component", "page") if isinstance(merged[i], dict) else "page",
                        "type": "kb_pattern",
                        "action": pattern_name,
                        "sub_actions": merged[i:i + len(pattern_actions)],
                    }
                    # Collect raw_steps from all merged items
                    for item in merged[i:i + len(pattern_actions)]:
                        if isinstance(item, dict) and "raw_steps" in item:
                            merged_step["raw_steps"].extend(item["raw_steps"])
                    merged = merged[:i] + [merged_step] + merged[i + len(pattern_actions):]
                    break

        return merged

    def recognize_pattern(self, sequences: list) -> list[dict]:
        """PrefixSpan 频繁子序列挖掘 — 发现可封装的 BAW 模式。

        所有适配器共用此实现。子类可覆盖以定制输出格式。
        """
        if len(sequences) < 3:
            return []

        # 将序列转为 action 名称列表
        action_seqs = []
        for seq in sequences:
            actions = []
            if isinstance(seq, list):
                for item in seq:
                    if isinstance(item, dict):
                        actions.append(item.get("action", "?"))
                    else:
                        actions.append(str(item))
            action_seqs.append(actions)

        miner = _PrefixSpan(min_support=3, max_length=8)
        frequent_patterns = miner.mine(action_seqs)

        patterns = []
        for pattern, count in frequent_patterns:
            pattern_key = " → ".join(pattern)
            patterns.append({
                "pattern": pattern_key,
                "actions": list(pattern),
                "frequency": count,
                "suggestion": f"Suggest wrapping into BusinessAW (appeared {count} times)",
            })

        return patterns


class CodeGenerator(ABC):
    """接口 4: 代码生成器 — 框架级 IR → 代码文件"""

    target_language: str = "python"  # 子类覆盖为 "java" 等
    default_base_class: str = "BaseAW"  # 子类覆盖为 "Target" / "BaseComponentAW" 等

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
