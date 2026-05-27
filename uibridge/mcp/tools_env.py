"""MCP tools for environment checks."""
import json

from .server import mcp


@mcp.tool()
async def check_environment() -> str:
    """检查 uibridge 运行环境：Playwright 浏览器、依赖等是否就绪。

    用于：Agent 在开始录制前验证环境，或用户排查安装问题。
    返回：JSON 格式环境状态报告。
    """
    from uibridge import check_browser_available

    chromium_ok, chromium_info = check_browser_available("chromium")
    firefox_ok, firefox_info = check_browser_available("firefox")

    issues = []
    if not chromium_ok:
        issues.append("chromium 未安装 — 运行 playwright install chromium")
    if not firefox_ok:
        issues.append("firefox 未安装 — 运行 playwright install firefox")

    return json.dumps({
        "status": "ok" if not issues else "issues_found",
        "browsers": {
            "chromium": {"available": chromium_ok, "path": chromium_info if chromium_ok else None},
            "firefox": {"available": firefox_ok, "path": firefox_info if firefox_ok else None},
        },
        "issues": issues,
        "uibridge_version": __import__("uibridge").__version__,
    }, indent=2, ensure_ascii=False)
