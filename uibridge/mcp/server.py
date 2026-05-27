"""MCP server instance and entry point."""
import logging
import sys

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# 将 editable finders 提升到 meta_path 最前面，
# 防止 CWD 下同名目录被 PathFinder 优先匹配为命名空间包。
_editable_finders = [f for f in sys.meta_path if hasattr(f, '__name__') and '__editable__' in f.__name__]
for _ef in reversed(_editable_finders):
    sys.meta_path.remove(_ef)
    sys.meta_path.insert(0, _ef)

mcp = FastMCP(
    "uibridge",
    instructions="UI 自动化测试脚本智能生成系统 — 录制浏览器操作 → 自动生成测试代码",
)


def main():
    """启动 MCP Server"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", default="stdio")
    args = parser.parse_args()
    _startup_check()
    print("[OK] uibridge MCP Server starting...", flush=True)
    mcp.run(transport=args.transport)


def _startup_check():
    """启动时检查 Playwright 浏览器可用性，输出到 stderr（stdio 模式下不干扰 JSON-RPC）。"""
    from uibridge import check_browser_available

    available, info = check_browser_available("chromium")
    if available:
        logger.info(f"Playwright 浏览器已就绪: {info}")
    else:
        logger.warning(f"Playwright 浏览器未就绪: {info}")
        logger.warning("请运行: playwright install chromium")

    # 检查 ffmpeg (录屏依赖，可选)
    available_ff, ff_info = check_browser_available("firefox")
    if not available_ff:
        pass  # Firefox 是可选的，不告警


# Import tool modules at bottom to register tools with mcp
from . import tools_recording  # noqa: E402
from . import tools_generation  # noqa: E402
from . import tools_kb  # noqa: E402
from . import tools_profile  # noqa: E402
from . import tools_env  # noqa: E402
