"""uibridge — UI自动化测试脚本智能化自动生成系统"""
__version__ = "0.3.6"


def check_browser_available(browser_name: str = "chromium") -> tuple[bool, str]:
    """检查 Playwright 浏览器是否已安装。

    验证 Playwright 注册表中浏览器路径对应的文件确实存在。

    Returns:
        (available, path_or_error): available 为 True 时第二个元素是浏览器路径，
                                   为 False 时第二个元素是错误信息。
    """
    from playwright.sync_api import sync_playwright

    try:
        pw = sync_playwright().start()
        try:
            browser_type = getattr(pw, browser_name, None)
            if browser_type is None:
                return False, f"未知浏览器类型: {browser_name}"
            path = browser_type.executable_path
            if path and Path(path).exists():
                return True, str(path)
            if path:
                return False, f"浏览器注册表指向不存在的路径: {path}（运行 playwright install {browser_name}）"
            return False, "浏览器未安装"
        finally:
            pw.stop()
    except Exception as e:
        return False, str(e)


def ensure_browser_ready(browser_name: str = "chromium") -> tuple[bool, str]:
    """确保 Playwright 浏览器可用；已安装则直接返回，未安装则尝试安装。

    Returns:
        (ready, detail): ready 为 True 表示浏览器就绪，detail 为路径或安装信息。
    """
    available, path_or_error = check_browser_available(browser_name)
    if available:
        return True, path_or_error

    # 未安装 → 尝试自动安装
    import subprocess
    import sys
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", browser_name],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return check_browser_available(browser_name)
        return False, result.stderr.strip() or "playwright install 失败"
    except Exception as e:
        return False, str(e)
