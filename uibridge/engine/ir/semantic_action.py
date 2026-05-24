"""IR v2: SemanticActionSequence — 语义理解层的输出，将 DOM 操作聚合为业务动作"""

from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class SemanticAction:
    """语义动作"""
    type: str  # page_action | assertion | navigation
    page: str  # 页面名
    action: str = ""  # 动作名
    params: dict = field(default_factory=dict)
    source_steps: list[str] = field(default_factory=list)


@dataclass
class SemanticScenario:
    """语义场景 — 一组页面流中的连续动作"""
    name: str
    page_flow: list[str] = field(default_factory=list)
    actions: list[SemanticAction] = field(default_factory=list)
    description: str = ""


@dataclass
class SemanticActionSequence:
    """IR v2"""
    version: str = "2.0"
    meta: dict = field(default_factory=dict)
    scenarios: list[SemanticScenario] = field(default_factory=list)

    def to_dict(self) -> dict:
        import dataclasses

        def _convert(obj):
            if dataclasses.is_dataclass(obj):
                return {k: _convert(v) for k, v in dataclasses.asdict(obj).items()}
            if isinstance(obj, list):
                return [_convert(i) for i in obj]
            if isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            return obj

        return _convert(self)
