"""Shared helpers and constants for MCP tools."""
from pathlib import Path

# 禁止的协议前缀，防止 URL 注入
_BLOCKED_URL_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")

# 允许的输出基础目录：调用方 CWD（即 Agent / 企业项目根目录）
_OUTPUT_BASE = Path.cwd()

# 超时与阈值常量
OPEN_BROWSER_TIMEOUT = 1800  # 打开浏览器后等待开始录制的最长时间（秒）
RECORDING_TIMEOUT = 600       # 录制会话的最长时间（秒）
MAX_RECORDING_STEPS = 200     # MCP 模式下允许的最大录制步骤数


def _validate_url(url: str) -> str:
    """校验 URL，拒绝危险协议和空 URL。返回规范化字符串或抛 ValueError。"""
    if not url or not url.strip():
        raise ValueError("URL 不能为空")
    stripped = url.strip()
    lowered = stripped.lower()
    for scheme in _BLOCKED_URL_SCHEMES:
        if lowered.startswith(scheme):
            raise ValueError(f"禁止的 URL 协议: {scheme}")
    if not (lowered.startswith("http://") or lowered.startswith("https://") or lowered == "about:blank"):
        raise ValueError("URL 必须以 http:// 或 https:// 开头")
    return stripped


def _sanitize_output_path(raw: str) -> Path:
    """将用户输入的路径安全化，限制在 _OUTPUT_BASE 内。"""
    p = Path(raw).resolve()
    if not str(p).startswith(str(_OUTPUT_BASE)):
        p = _OUTPUT_BASE / p.name
    return p


def _sanitize_input_path(raw: str) -> Path:
    """安全解析输入路径，禁止相对路径穿越。"""
    p = Path(raw).resolve()
    return p


def _load_adapter(adapter_config_path=None):
    """[DEPRECATED v0.4.0] Adapter functionality dispersed to scanner + generator."""
    raise NotImplementedError(
        "Adapter system removed in v0.4.0. "
        "Framework features are now auto-discovered by scanner/ and rendered by generator/."
    )


def _build_pipeline(adapter_config_path=None, project_dir="."):
    """[DEPRECATED v0.4.0] Pipeline removed. Use direct module calls instead."""
    raise NotImplementedError(
        "Pipeline removed in v0.4.0. "
        "Use browser/, scanner/, kb/, generator/ modules directly."
    )
