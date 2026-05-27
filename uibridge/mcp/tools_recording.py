"""MCP tools for browser recording."""
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .server import mcp
from .state import _state
from .helpers import (
    _validate_url,
    _sanitize_output_path,
    # Removed: _build_pipeline (adapter/pipeline deleted)
    OPEN_BROWSER_TIMEOUT,
    RECORDING_TIMEOUT,
)


@mcp.tool()
async def analyze_page(
    url: str,
    adapter_config: Optional[str] = None,
) -> str:
    """[REDESIGNING v0.4.0] 页面分析功能正在重构中。

页面分析将作为 browser/ 模块的一部分重新实现（v0.4.0）。
当前可通过 get_profile / get_project_layout 查看项目结构，
通过 query_knowledge_base 查询组件信息。
"""
    return json.dumps({
        "status": "unavailable",
        "version": "0.4.0",
        "message": "页面分析功能正在重构中（v0.4.0）。analyze_page 将被 browser/ 模块的新 API 替代。",
        "hint": "当前可通过 open_browser 打开浏览器手动探索，通过 KB 工具查询组件信息。",
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def open_browser(
    url: str = "about:blank",
) -> str:
    """打开可见浏览器窗口（不录制）。

    这是三段式录制的第一步。仅打开浏览器并导航到 URL，不注入录制脚本。
    用户在此阶段可进行预置操作（登录、导航到目标页面等）。

    预置完成后，调用 start_recording() 开始录制。

    三段式流程: open_browser → [用户预置] → start_recording → [用户操作] → stop_recording

    参数：
    - url: 起始页面 URL
    返回：会话状态 JSON。
    """
    _validate_url(url)

    # 预检浏览器是否可用
    available, path_or_error = check_browser_available("chromium")
    if not available:
        return json.dumps({"error": f"浏览器不可用: {path_or_error}"}, indent=2, ensure_ascii=False)

    def _sync():
        from playwright.sync_api import sync_playwright

        pw = None
        context = None
        try:
            with _state.get_recording_lock():
                # 录制进行中时拒绝打开新浏览器，防止误杀
                if _state.get_active_recording():
                    return json.dumps({
                        "error": "录制正在进行中。请先调用 stop_recording 结束当前录制，再打开新浏览器。",
                    }, indent=2, ensure_ascii=False)
                staging = _state.get_active_browser_staging()
                if staging:
                    try:
                        staging["context"].close()
                    except Exception:
                        logger.warning("Failed to close existing staging browser context", exc_info=True)
                        pass
                    try:
                        staging["pw"].stop()
                    except Exception:
                        logger.warning("Failed to stop existing staging playwright", exc_info=True)
                        pass

                pw = sync_playwright().start()

                # 持久化用户目录 — 模拟真实浏览器（cookie/localStorage 持久化，防反爬）
                user_data_dir = Path.home() / ".uibridge" / "browser_profile"
                user_data_dir.mkdir(parents=True, exist_ok=True)

                context = pw.chromium.launch_persistent_context(
                    user_data_dir=str(user_data_dir),
                    headless=False,
                    no_viewport=True,
                    # 去掉自动化标记，防止被反爬检测
                    ignore_default_args=[
                        "--enable-automation",           # 移除 "Chrome 正受到自動測試軟體控制"
                    ],
                    args=[
                        "--disable-blink-features=AutomationControlled",  # 移除 navigator.webdriver
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                )
                page = context.pages[0] if context.pages else context.new_page()

                # 注入反检测脚本（在所有页面 JS 之前执行），覆盖自动化特征
                page.add_init_script("""
                    // 隐藏 webdriver 标记
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    // 伪造 chrome.runtime（自动化模式下为空）
                    window.chrome = window.chrome || {};
                    window.chrome.runtime = window.chrome.runtime || {};
                    // 伪造 plugins 数组（自动化模式通常为空）
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5],
                    });
                    // 伪造 languages
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['zh-CN', 'zh', 'en'],
                    });
                """)
                page.goto(url)

                session_id = str(uuid.uuid4())[:8]

                # 30 分钟超时保护：用户打开浏览器后长时间未开始录制，自动清理
                def _auto_cleanup_staging():
                    with _state.get_recording_lock():
                        staging = _state.get_active_browser_staging()
                        if staging and staging.get("session_id") == session_id:
                            try:
                                staging["context"].close()
                            except Exception:
                                logger.warning("Failed to close staging browser context on auto-cleanup", exc_info=True)
                                pass
                            try:
                                staging["pw"].stop()
                            except Exception:
                                logger.warning("Failed to stop staging playwright on auto-cleanup", exc_info=True)
                                pass
                            _state.set_active_browser_staging(None)

                timer = threading.Timer(OPEN_BROWSER_TIMEOUT, _auto_cleanup_staging)
                timer.daemon = True
                timer.start()

                _state.set_active_browser_staging({
                    "session_id": session_id,
                    "page": page,
                    "context": context,
                    "pw": pw,
                    "_timeout_timer": timer,
                })

            return json.dumps({
                "status": "browser_ready",
                "session_id": session_id,
                "url": url,
                "hint": "浏览器已打开。用户可进行预置操作（登录、导航等），完成后调用 start_recording 开始录制。",
            }, indent=2, ensure_ascii=False)
        except Exception:
            if context:
                try:
                    context.close()
                except Exception:
                    logger.warning("Failed to close browser context on error", exc_info=True)
                    pass
            if pw:
                try:
                    pw.stop()
                except Exception:
                    logger.warning("Failed to stop playwright on error", exc_info=True)
                    pass
            with _state.get_recording_lock():
                _state.set_active_browser_staging(None)
            raise

    return await _state.run_pw(_sync)


@mcp.tool()
async def start_recording(
    adapter_config: Optional[str] = None,
) -> str:
    """[REDESIGNING v0.4.0] 录制功能暂不可用。

录制引擎 (adapter/pipeline) 已移除，正在由 browser/ 模块重新实现（v0.4.0）。
当前仅支持 open_browser → stop_recording 的基本浏览器控制流，
录制功能将在 browser/ 模块完成后恢复。

Args:
    adapter_config: 暂未使用
"""
    return json.dumps({
        "status": "unavailable",
        "version": "0.4.0",
        "message": "录制功能正在重构中（v0.4.0）。start_recording 将在 browser/ 模块完成后恢复。",
        "hint": "当前可通过 open_browser 打开浏览器手动探索，或使用 KB 工具维护知识库。",
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def stop_recording(
    output_file: str = "recording.json",
) -> str:
    """停止当前活跃的录制会话，保存录制文件，关闭浏览器。

    用于：录制两步曲的第二步。用户在浏览器中完成操作后，Agent 调用此工具
    结束录制。录制数据保存到 JSON 文件，浏览器窗口关闭。

    参数：
    - output_file: 录制输出文件路径，默认 recording.json
    返回：录制结果摘要（步骤数、文件路径、每步简要描述）。
    """

    def _sync():

        with _state.get_recording_lock():
            recording_state = _state.get_active_recording()
            if not recording_state:
                return json.dumps({
                    "error": "没有活跃的录制会话。请先调用 start_recording。",
                }, indent=2, ensure_ascii=False)

            # 先取消超时定时器，防止与正常 stop 并发
            timer = recording_state.get("_timeout_timer")
            if timer:
                try:
                    timer.cancel()
                except Exception:
                    logger.warning("Failed to cancel recording timeout timer", exc_info=True)
                    pass

            session = recording_state["session"]
            context = recording_state["context"]
            pw = recording_state["pw"]
            page = recording_state["page"]
            _state.set_active_recording(None)

        recording = None
        try:
            # 刷新排队中的 expose_binding 回调（sync_playwright 调度器只在 API 调用时处理回调）
            try:
                page.wait_for_timeout(300)
            except Exception:
                logger.warning("Failed to flush callbacks before stopping recording", exc_info=True)
                pass
            recording = session.stop()
        finally:
            try:
                context.close()
            except Exception:
                logger.warning("Failed to close browser context after stopping recording", exc_info=True)
                pass
            try:
                pw.stop()
            except Exception:
                logger.warning("Failed to stop playwright after stopping recording", exc_info=True)
                pass

        if recording is None:
            return json.dumps({"error": "录制停止失败。"}, indent=2, ensure_ascii=False)

        output_path = _sanitize_output_path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(recording.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        event_count = getattr(session, '_event_count', 0)

        return json.dumps({
            "status": "ok",
            "steps": len(recording.steps),
            "events_received": event_count,
            "file": str(output_path.absolute()),
            "summary": [f"{s.action.value}: {s.target.label or s.target.url or ''}" for s in recording.steps],
        }, indent=2, ensure_ascii=False)

    return await _state.run_pw(_sync)
