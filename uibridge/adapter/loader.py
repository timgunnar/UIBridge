"""适配器工厂 — 从配置文件加载 5 个接口实例，供 CLI 和 MCP Server 共用"""

import importlib
import json
from pathlib import Path
from typing import Optional

import yaml

from .reference import (
    ReferenceComponentResolver,
    ReferenceLocatorStrategy,
    ReferenceActionRecognizer,
    ReferenceCodeGenerator,
    ReferenceDataFormatter,
)

# 适配器接口全限定类名默认值 — 当配置文件中未指定时回退到参考实现
_DEFAULT_RESOLVER = "uibridge.adapter.reference.ReferenceComponentResolver"
_DEFAULT_LOCATOR = "uibridge.adapter.reference.ReferenceLocatorStrategy"
_DEFAULT_RECOGNIZER = "uibridge.adapter.reference.ReferenceActionRecognizer"
_DEFAULT_GENERATOR = "uibridge.adapter.reference.ReferenceCodeGenerator"
_DEFAULT_DATA_FORMATTER = "uibridge.adapter.reference.ReferenceDataFormatter"


def _import_class(cls_path: str):
    """动态导入类并实例化"""
    module_path, class_name = cls_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def load_adapter(adapter_config_path: Optional[str] = None) -> tuple:
    """加载适配器配置，返回 5 个接口实例

    Args:
        adapter_config_path: 适配器配置文件路径（YAML/JSON）。
            若为 None 或文件不存在，返回参考实现。

    Returns:
        (resolver, locator, recognizer, code_generator, data_formatter) 五元组
    """
    if adapter_config_path:
        config_path = Path(adapter_config_path)
        if config_path.exists():
            raw = config_path.read_text("utf-8")
            if config_path.suffix in (".yaml", ".yml"):
                config = yaml.safe_load(raw)
            else:
                config = json.loads(raw)
            components = config.get("adapter", {}).get("components", {})
            if components:
                return (
                    _import_class(components.get("resolver", _DEFAULT_RESOLVER)),
                    _import_class(components.get("locator", _DEFAULT_LOCATOR)),
                    _import_class(components.get("recognizer", _DEFAULT_RECOGNIZER)),
                    _import_class(components.get("generator", _DEFAULT_GENERATOR)),
                    _import_class(components.get("data_formatter", _DEFAULT_DATA_FORMATTER)),
                )

    # 默认：参考实现
    return (
        ReferenceComponentResolver(),
        ReferenceLocatorStrategy(),
        ReferenceActionRecognizer(),
        ReferenceCodeGenerator(),
        ReferenceDataFormatter(),
    )
