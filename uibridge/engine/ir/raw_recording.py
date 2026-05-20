"""IR v1: RawRecording — 录制操作的标准化序列，与框架无关"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    INPUT = "input"
    CLICK = "click"
    SELECT = "select"
    CHECK = "check"
    UNCHECK = "uncheck"
    KEYDOWN = "keydown"
    ASSERT = "assert"
    TAB_SWITCH = "tab_switch"
    DBLCLICK = "dblclick"
    HOVER = "hover"
    RIGHTCLICK = "rightclick"
    DRAGSTART = "dragstart"
    DROP = "drop"
    SCROLL = "scroll"
    MUTATION = "mutation"
    SUBMIT = "submit"
    FOCUS = "focus"
    BLUR = "blur"
    DIALOG = "dialog"
    CLIPBOARD = "clipboard"
    FILE_UPLOAD = "file_upload"


@dataclass
class SelectorSet:
    """多策略选择器集合"""
    css: Optional[str] = None
    xpath: Optional[str] = None
    text: Optional[str] = None
    role: Optional[str] = None
    aria_label: Optional[str] = None
    data_testid: Optional[str] = None
    data_module: Optional[str] = None

    def primary(self) -> tuple[str, str]:
        """返回 (策略名, 值) 按优先级"""
        for strategy, value in [
            ("data_testid", self.data_testid),
            ("data_module", self.data_module),
            ("css", self.css),
            ("xpath", self.xpath),
            ("text", self.text),
            ("role", self.role),
            ("aria_label", self.aria_label),
        ]:
            if value:
                return strategy, value
        return "css", self.css or ""


@dataclass
class Target:
    """操作目标元素描述"""
    selectors: SelectorSet = field(default_factory=SelectorSet)
    label: Optional[str] = None
    tag: Optional[str] = None
    url: Optional[str] = None
    page_hint: Optional[str] = None
    component_hint: Optional[str] = None


@dataclass
class Snapshot:
    """页面快照"""
    id: str
    url: str
    title: str = ""
    aria_snapshot: str = ""
    layout_info: str = "{}"
    timestamp_ms: int = 0
    error: str = ""


@dataclass
class RawStep:
    """单个录制步骤"""
    id: str
    action: ActionType
    target: Optional[Target] = None
    value: Optional[str] = None
    input_type: Optional[str] = None  # fill / press / type
    modifiers: list[str] = field(default_factory=list)
    timestamp_ms: int = 0
    before_snapshot_id: Optional[str] = None
    after_snapshot_id: Optional[str] = None
    navigation_triggered: bool = False
    tab_index: int = 0

    def __post_init__(self):
        if not isinstance(self.action, ActionType):
            object.__setattr__(self, 'action', ActionType(self.action))


@dataclass
class RawRecordingMeta:
    source: str = "browser_recording"
    duration_ms: int = 0
    viewport: dict = field(default_factory=lambda: {"width": 1280, "height": 800})
    generated_at: str = ""


@dataclass
class RawRecording:
    """IR v1: 录制会话的完整输出"""
    version: str = "1.0"
    meta: RawRecordingMeta = field(default_factory=RawRecordingMeta)
    steps: list[RawStep] = field(default_factory=list)
    snapshots: dict[str, Snapshot] = field(default_factory=dict)

    def to_dict(self) -> dict:
        import dataclasses

        def _convert(obj):
            if dataclasses.is_dataclass(obj):
                return {k: _convert(v) for k, v in dataclasses.asdict(obj).items()}
            if isinstance(obj, list):
                return [_convert(i) for i in obj]
            if isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            if isinstance(obj, Enum):
                return obj.value
            return obj

        return _convert(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RawRecording":
        meta = RawRecordingMeta(**data.get("meta", {}))
        steps = []
        for s in data.get("steps", []):
            target = None
            if s.get("target"):
                sel = SelectorSet(**s["target"].get("selectors", {}))
                target = Target(
                    selectors=sel,
                    label=s["target"].get("label"),
                    tag=s["target"].get("tag"),
                    url=s["target"].get("url"),
                    page_hint=s["target"].get("page_hint"),
                    component_hint=s["target"].get("component_hint"),
                )
            steps.append(RawStep(
                id=s["id"],
                action=ActionType(s["action"]),
                target=target,
                value=s.get("value"),
                input_type=s.get("input_type"),
                modifiers=s.get("modifiers", []),
                timestamp_ms=s.get("timestamp_ms", 0),
                before_snapshot_id=s.get("before_snapshot_id"),
                after_snapshot_id=s.get("after_snapshot_id"),
                navigation_triggered=s.get("navigation_triggered", False),
                tab_index=s.get("tab_index", 0),
            ))
        snapshots = {}
        for k, v in data.get("snapshots", {}).items():
            v = dict(v)
            v.setdefault("layout_info", "{}")
            snapshots[k] = Snapshot(**v)
        return cls(version=data.get("version", "1.0"), meta=meta, steps=steps, snapshots=snapshots)
