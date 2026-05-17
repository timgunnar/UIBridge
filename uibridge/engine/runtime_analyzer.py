"""运行时分析器 — Playwright 页面插桩，捕获网络、JS 错误、性能指标。

在 RecordingSession 中集成：监听网络请求（XHR/fetch）、控制台错误、
性能条目（FP/FCP/LCP），生成运行时行为报告供测试断言增强使用。
"""

import json
import time
from dataclasses import dataclass, field
from playwright.sync_api import Page


@dataclass
class NetworkEntry:
    """网络请求条目"""
    url: str
    method: str = "GET"
    status: int = 0
    duration_ms: float = 0
    request_type: str = ""  # xhr / fetch / document / script / stylesheet
    ok: bool = False


@dataclass
class RuntimeReport:
    """运行时分析报告"""
    network_requests: list[NetworkEntry] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    performance_metrics: dict = field(default_factory=dict)
    start_time: float = 0
    end_time: float = 0

    @property
    def total_requests(self) -> int:
        return len(self.network_requests)

    @property
    def failed_requests(self) -> int:
        return len([r for r in self.network_requests if not r.ok])

    @property
    def xhr_requests(self) -> int:
        return len([r for r in self.network_requests
                    if r.request_type in ("xhr", "fetch")])

    def to_dict(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "xhr_requests": self.xhr_requests,
            "api_endpoints": list(set(
                r.url for r in self.network_requests
                if r.request_type in ("xhr", "fetch")
            )),
            "console_errors": self.console_errors,
            "performance_metrics": self.performance_metrics,
        }


class RuntimeAnalyzer:
    """运行时分析器 — 注入 Playwright 监听器，实时捕获运行时信息。

    用法:
        analyzer = RuntimeAnalyzer(page)
        analyzer.start()
        # ... 用户操作 ...
        report = analyzer.stop()
    """

    def __init__(self, page: Page):
        self.page = page
        self._report = RuntimeReport(start_time=time.time())
        self._active = False

    def start(self):
        """开始监听"""
        if self._active:
            return
        self._active = True
        self._report = RuntimeReport(start_time=time.time())

        # 网络请求监听
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)
        # 控制台错误
        self.page.on("console", self._on_console_for_error)

    def stop(self) -> RuntimeReport:
        """停止监听，返回分析报告"""
        self._active = False
        self._report.end_time = time.time()

        # 采集性能指标
        try:
            metrics = self.page.evaluate("""() => {
                const result = {};
                try {
                    const nav = performance.getEntriesByType('navigation')[0];
                    if (nav) {
                        result.domContentLoaded = Math.round(nav.domContentLoadedEventEnd);
                        result.loadComplete = Math.round(nav.loadEventEnd);
                        result.firstPaint = 0;
                    }
                } catch(e) {}
                try {
                    const paint = performance.getEntriesByType('paint');
                    for (const p of paint) {
                        result[p.name] = Math.round(p.startTime);
                    }
                } catch(e) {}
                try {
                    const lcp = performance.getEntriesByType('largest-contentful-paint');
                    if (lcp.length > 0) {
                        result.LCP = Math.round(lcp[lcp.length-1].startTime);
                    }
                } catch(e) {}
                return result;
            }""")
            if metrics:
                self._report.performance_metrics = metrics
        except Exception:
            pass

        return self._report

    def _on_request(self, request):
        if not self._active:
            return
        rt = request.resource_type.lower()
        entry = NetworkEntry(
            url=request.url,
            method=request.method,
            request_type=rt,
        )
        self._report.network_requests.append(entry)

    def _on_response(self, response):
        if not self._active:
            return
        url = response.url
        for entry in reversed(self._report.network_requests):
            if entry.url == url and entry.status == 0:
                entry.status = response.status
                entry.ok = response.ok
                end = time.time()
                entry.duration_ms = (end - self._report.start_time) * 1000
                break

    def _on_console_for_error(self, msg):
        if not self._active:
            return
        if msg.type in ("error", "warning"):
            # 过滤掉 uibridge 内部日志
            if "__uibridge_" in msg.text:
                return
            self._report.console_errors.append(
                f"[{msg.type}] {msg.text[:200]}"
            )
