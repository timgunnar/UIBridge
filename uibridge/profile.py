"""FrameworkProfile — 项目级 UI 框架画像（独立于 KB 的运行时配置源）。

画像定义项目宏观结构：UI 包在哪、基类叫什么、代码分几层、生成什么文件。
Phase 1 自动推断后经用户确认，成为 uibridge 运行时唯一决策源。
"""

import time
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProfileField:
    """画像中的单个字段，带来源追踪和独立置信度。

    source 取值: auto | human_dialogue | document | runtime
    description: 该字段控制什么，Agent 对照解释给用户
    """

    value: any = None
    source: str = "auto"
    confidence: float = 0.6
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileField":
        if isinstance(d, dict) and "value" in d:
            return cls(
                value=d.get("value"),
                source=d.get("source", "auto"),
                confidence=d.get("confidence", 0.6),
                description=d.get("description", ""),
            )
        # 兼容旧格式：裸值
        return cls(value=d)


@dataclass
class FrameworkProfile:
    """Phase 1 输出：项目级 UI 框架画像。

    每个字段是 ProfileField，记录自动推断结果及置信度，
    可由 NL 对话或文档持续增强。
    存储为 .uibridge/profile.yaml。
    """

    project_type: str = "unknown"  # java_maven | java_gradle | python_pytest
    ui_packages: ProfileField = field(default_factory=ProfileField)
    base_classes: ProfileField = field(default_factory=ProfileField)
    annotations: ProfileField = field(default_factory=ProfileField)
    locator_priorities: ProfileField = field(default_factory=ProfileField)
    naming_conventions: ProfileField = field(default_factory=ProfileField)
    source_dirs: ProfileField = field(default_factory=ProfileField)
    layer_structure: ProfileField = field(default_factory=lambda: ProfileField(
        value=[
            {"name": "component_aw", "dir": "components", "role": "UI 组件封装",
             "enabled": False, "managed_by_user": True,
             "maps_to": "", "description": "现有组件封装层，由用户维护，uibridge 不生成"},
            {"name": "page", "dir": "pages", "role": "页面对象",
             "enabled": True, "managed_by_user": True,
             "maps_to": "", "description": "页面对象层，由用户维护"},
            {"name": "test", "dir": "tests", "role": "测试脚本",
             "enabled": True, "managed_by_user": False,
             "maps_to": "test_script", "description": "录制后 uibridge 生成的测试脚本"},
            {"name": "test_data", "dir": "data", "role": "测试数据",
             "enabled": True, "managed_by_user": False,
             "maps_to": "test_data", "description": "录制后 uibridge 生成的测试数据"},
        ],
        source="auto",
        confidence=0.60,
        description="项目代码分层结构。maps_to 指出该层对应 output_config 中哪个生成类型。"
                    "managed_by_user=true 表示该层由用户维护，uibridge 不为其生成文件。"
                    "通过 NL 对话修改层名和目录名以匹配项目实际命名",
    ))
    reference_directories: ProfileField = field(default_factory=lambda: ProfileField(
        value={"mature": [], "developing": [], "deprecated": []},
        source="auto",
        confidence=0.55,
        description="成熟目录代码作为框架权威参考，开发中目录仅作辅助，过时目录忽略",
    ))
    output_config: ProfileField = field(default_factory=lambda: ProfileField(
        value={"generate": [
            {"type": "test_script", "dir": "tests", "template": "default"},
            {"type": "test_data", "dir": "data", "template": "default"},
        ]},
        source="auto",
        confidence=0.65,
        description="录制完成后自动生成的文件类型及输出位置。"
                    "template 字段指定代码生成模板，适配器可据此切换生成风格",
    ))
    component_monitoring: ProfileField = field(default_factory=lambda: ProfileField(
        value={"enabled": False, "components": [], "check_interval_days": 7},
        source="auto",
        confidence=0.50,
        description="组件过时检测。开启后定期对比 KB 中组件快照与源码，发现方法增删或定位器变更时告警",
    ))
    profiling_confidence: float = 0.5
    updated_by: str = ""
    created_at: float = field(default_factory=time.time)
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "project_type": self.project_type,
            "ui_packages": self.ui_packages.to_dict(),
            "base_classes": self.base_classes.to_dict(),
            "annotations": self.annotations.to_dict(),
            "locator_priorities": self.locator_priorities.to_dict(),
            "naming_conventions": self.naming_conventions.to_dict(),
            "source_dirs": self.source_dirs.to_dict(),
            "layer_structure": self.layer_structure.to_dict(),
            "reference_directories": self.reference_directories.to_dict(),
            "output_config": self.output_config.to_dict(),
            "component_monitoring": self.component_monitoring.to_dict(),
            "profiling_confidence": self.profiling_confidence,
            "updated_by": self.updated_by,
            "created_at": self.created_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FrameworkProfile":
        return cls(
            project_type=d.get("project_type", "unknown"),
            ui_packages=ProfileField.from_dict(d.get("ui_packages", [])),
            base_classes=ProfileField.from_dict(d.get("base_classes", {})),
            annotations=ProfileField.from_dict(d.get("annotations", [])),
            locator_priorities=ProfileField.from_dict(d.get("locator_priorities", [])),
            naming_conventions=ProfileField.from_dict(d.get("naming_conventions", {})),
            source_dirs=ProfileField.from_dict(d.get("source_dirs", {})),
            layer_structure=ProfileField.from_dict(d.get("layer_structure", {})),
            reference_directories=ProfileField.from_dict(d.get("reference_directories", {})),
            output_config=ProfileField.from_dict(d.get("output_config", {})),
            component_monitoring=ProfileField.from_dict(d.get("component_monitoring", {})),
            profiling_confidence=d.get("profiling_confidence", 0.5),
            updated_by=d.get("updated_by", ""),
            created_at=d.get("created_at", time.time()),
            version=d.get("version", 1),
        )
