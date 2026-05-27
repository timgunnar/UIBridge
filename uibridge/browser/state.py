"""Browser state management for MCP server."""
import asyncio
import concurrent.futures
import threading


class BrowserState:
    """Encapsulates mutable browser/recording state for the MCP server."""

    def __init__(self):
        self._active_browser_staging = None   # open_browser 阶段：浏览器已打开但未开始录制
        self._active_recording = None          # start_recording 阶段：录制进行中
        self._recording_lock = threading.Lock()
        # 单线程执行器：所有 sync Playwright 操作在此线程运行
        #   max_workers=1 保证 start_recording / stop_recording 在同一线程，
        #   sync_playwright() 在此线程无 asyncio 事件循环，不会冲突。
        self._pw_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="uibridge_pw"
        )

    def get_active_browser_staging(self):
        return self._active_browser_staging

    def set_active_browser_staging(self, value):
        self._active_browser_staging = value

    def get_active_recording(self):
        return self._active_recording

    def set_active_recording(self, value):
        self._active_recording = value

    def get_recording_lock(self):
        return self._recording_lock

    async def run_pw(self, func, *args, **kwargs):
        """在专用 Playwright 线程中执行同步函数，返回结果或传播异常。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pw_executor, lambda: func(*args, **kwargs))


_state = BrowserState()
