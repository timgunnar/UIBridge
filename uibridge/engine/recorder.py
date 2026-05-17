"""录制引擎 — Playwright 事件监听，捕获用户操作"""

import json
import time
import threading
from playwright.sync_api import Page

from .ir.raw_recording import (
    RawRecording, RawRecordingMeta, RawStep, ActionType,
    Target, SelectorSet, Snapshot,
)
from .runtime_analyzer import RuntimeAnalyzer, RuntimeReport

# JavaScript 注入：监听 DOM 事件并桥接到 Python
# 注意：expose_binding 回调中不能调用 page API（会死锁），因此 JS 侧
# 直接提供完整元素信息，Python 侧只记录数据，快照由外部显式触发。
# SPA 导航使用 console.log 桥接，因为 page.on("console") 在安全线程触发。
RECORDER_JS = r"""
(() => {
    if (window.__uibridge_recorder_ready) return;
    window.__uibridge_recorder_ready = true;

    function describe(el) {
        if (!el || el === document || el === document.body) return {};
        const tag = (el.tagName || '').toLowerCase();
        const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : {};
        let label = el.getAttribute('aria-label') || el.getAttribute('placeholder')
                 || el.getAttribute('title') || '';
        if (!label) {
            const prev = el.previousElementSibling;
            if (prev && prev.tagName === 'LABEL')
                label = (prev.textContent || '').trim().substring(0, 50);
        }
        if (!label) label = (el.textContent || '').trim().substring(0, 50);
        return {
            tag,
            id: el.id || '',
            name: el.getAttribute('name') || '',
            role: el.getAttribute('role') || '',
            ariaLabel: el.getAttribute('aria-label') || '',
            dataTestid: el.getAttribute('data-testid') || '',
            dataModule: el.getAttribute('data-module') || '',
            css: el.id ? ('#' + el.id)
               : (el.getAttribute('data-testid') ? '[data-testid="' + el.getAttribute('data-testid') + '"]'
               : (el.getAttribute('data-module') ? '[data-module="' + el.getAttribute('data-module') + '"]' : '')),
            label,
            value: el.value || '',
            x: Math.round(rect.x || 0),
            y: Math.round(rect.y || 0),
            w: Math.round(rect.width || 0),
            h: Math.round(rect.height || 0),
        };
    }

    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden'
            && !!(el.offsetParent || el.getClientRects().length);
    }

    // ── 点击 ──────────────────────────────────
    document.addEventListener('click', (e) => {
        const el = e.target;
        if (!visible(el)) return;
        const d = describe(el);
        d.url = location.href;
        window.__uibridge_report('click', JSON.stringify(d));
    }, true);

    // ── 双击 ──────────────────────────────────
    document.addEventListener('dblclick', (e) => {
        const el = e.target;
        if (!visible(el)) return;
        const d = describe(el);
        d.url = location.href;
        window.__uibridge_report('dblclick', JSON.stringify(d));
    }, true);

    // ── 输入 / 选择变更 ───────────────────────
    document.addEventListener('change', (e) => {
        const el = e.target;
        if (!visible(el)) return;
        const tag = (el.tagName || '').toLowerCase();
        const d = describe(el);
        d.url = location.href;
        if (tag === 'input' || tag === 'textarea') {
            window.__uibridge_report('input', JSON.stringify(d));
        } else if (tag === 'select') {
            window.__uibridge_report('select', JSON.stringify(d));
        }
    }, true);

    // ── Enter 键 ──────────────────────────────
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const el = e.target;
            if (!visible(el)) return;
            const d = describe(el);
            d.url = location.href;
            window.__uibridge_report('keydown', JSON.stringify({key: 'Enter', target: d}));
        }
    }, true);

    // ── 右键 ──────────────────────────────────
    document.addEventListener('contextmenu', (e) => {
        const el = e.target;
        if (!visible(el)) return;
        const d = describe(el);
        d.url = location.href;
        window.__uibridge_report('rightclick', JSON.stringify(d));
    }, true);

    // ── 悬停（防抖 300ms）─────────────────────
    let _hover_timer = null;
    let _last_hover_el = null;
    document.addEventListener('mouseenter', (e) => {
        const el = e.target;
        if (!visible(el) || el === _last_hover_el) return;
        _last_hover_el = el;
        if (_hover_timer) clearTimeout(_hover_timer);
        _hover_timer = setTimeout(() => {
            const d = describe(el);
            d.url = location.href;
            window.__uibridge_report('hover', JSON.stringify(d));
        }, 300);
    }, true);

    // ── 拖拽 ──────────────────────────────────
    let _drag_source = null;
    document.addEventListener('dragstart', (e) => {
        const el = e.target;
        if (!visible(el)) return;
        _drag_source = describe(el);
        _drag_source.url = location.href;
    }, true);
    document.addEventListener('dragover', (e) => {
        e.preventDefault();
    }, true);
    document.addEventListener('drop', (e) => {
        e.preventDefault();
        const el = e.target;
        if (!visible(el) || !_drag_source) return;
        const target_desc = describe(el);
        target_desc.url = location.href;
        window.__uibridge_report('drop', JSON.stringify({
            source: _drag_source,
            target: target_desc,
        }));
        _drag_source = null;
    }, true);

    // ── 滚动（防抖 500ms）─────────────────────
    let _scroll_timer = null;
    let _last_scroll = {x: 0, y: 0};
    document.addEventListener('scroll', (e) => {
        if (_scroll_timer) clearTimeout(_scroll_timer);
        _scroll_timer = setTimeout(() => {
            const s = {x: Math.round(window.scrollX), y: Math.round(window.scrollY)};
            if (Math.abs(s.x - _last_scroll.x) > 50 || Math.abs(s.y - _last_scroll.y) > 50) {
                _last_scroll = s;
                window.__uibridge_report('scroll', JSON.stringify({...s, url: location.href}));
            }
        }, 500);
    }, true);

    // ── SPA 路由变化 — 用 console.log 桥接（安全线程可捕获）──
    let _last_url = location.href;
    function _report_url_change() {
        if (location.href !== _last_url) {
            _last_url = location.href;
            console.log('__uibridge_nav__:' + JSON.stringify({url: location.href}));
        }
    }
    window.addEventListener('popstate', _report_url_change, true);
    window.addEventListener('hashchange', _report_url_change, true);

    // 拦截 history.pushState / replaceState（React Router / Vue Router 依赖它们）
    const _orig_pushState = history.pushState;
    const _orig_replaceState = history.replaceState;
    history.pushState = function(...args) {
        _orig_pushState.apply(this, args);
        _report_url_change();
    };
    history.replaceState = function(...args) {
        _orig_replaceState.apply(this, args);
        _report_url_change();
    };

    // ── MutationObserver：动态内容变化 ─────────
    const _mo = new MutationObserver((mutations) => {
        let added = 0, removed = 0, attr_changed = 0;
        for (const m of mutations) {
            added += m.addedNodes.length;
            removed += m.removedNodes.length;
            if (m.type === 'attributes') attr_changed++;
        }
        if (added > 0 || removed > 0 || attr_changed > 0) {
            const summary = {added, removed, attrChanged: attr_changed, url: location.href};
            window.__uibridge_report('mutation', JSON.stringify(summary));
        }
    });
    _mo.observe(document.body || document.documentElement, {
        childList: true, subtree: true, attributes: true,
        attributeFilter: ['class', 'style', 'disabled', 'aria-expanded', 'aria-selected', 'hidden'],
    });

    // ── 布局信息采集（供快照位置对比）─────────
    window.__uibridge_get_layout = function(selector) {
        const els = document.querySelectorAll(selector || '[id],[data-testid],[data-module],[role],button,input,select,textarea,table,[aria-label]');
        const result = {};
        const seen = new Set();
        for (const el of els) {
            if (!visible(el)) continue;
            const key = el.id || el.getAttribute('data-testid') || el.getAttribute('data-module')
                     || el.getAttribute('aria-label') || el.getAttribute('name') || el.getAttribute('role') || el.tagName;
            if (!key || seen.has(key)) continue;
            seen.add(key);
            const r = el.getBoundingClientRect();
            result[key] = {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)};
        }
        return JSON.stringify(result);
    };
})()
"""


class RecordingSession:
    """录制会话。注入 Playwright page，监听交互事件并输出标准化 IR v1。

    使用 expose_binding + add_init_script 实现 DOM 事件捕获。
    快照通过 capture_snapshot() 显式触发，避免 expose_binding 回调中
    调用 page API 导致的死锁。
    SPA 导航通过 console.log 桥接 → page.on("console") 在安全线程捕获。
    """

    def __init__(self, page: Page, enable_runtime: bool = True):
        self.page = page
        self.steps: list[RawStep] = []
        self.snapshots: dict[str, Snapshot] = {}
        self._snap_counter = 0
        self._start_time = time.time()
        self._active = True
        self._lock = threading.Lock()
        self._spa_nav_pending = False
        self.runtime: RuntimeAnalyzer | None = None
        self.runtime_report: RuntimeReport | None = None
        if enable_runtime:
            self.runtime = RuntimeAnalyzer(page)
            self.runtime.start()
        self._setup_bridge()

    def _setup_bridge(self):
        """建立 JS ↔ Python 事件桥接。

        expose_binding 用于不需要 page API 的事件（click/input/select/keydown/
        dblclick/hover/rightclick/drop/scroll/mutation）。

        console.log 桥接用于 SPA 导航事件 — page.on("console") 在安全线程触发，
        可以捕获快照。

        frameattached 确保 iframe 也注入录制脚本。
        popup 检测新标签页/窗口。
        """
        self.page.expose_binding("__uibridge_report", self._handle_js_event)
        self.page.add_init_script(RECORDER_JS)

        try:
            self.page.evaluate(RECORDER_JS)
        except Exception:
            pass

        self.page.on("framenavigated", self._on_navigate)
        self.page.on("console", self._on_console)
        self.page.on("frameattached", self._on_frame_attached)
        self.page.on("popup", self._on_popup)

    # ── JS 事件处理（transport 线程，禁止调 page API）─────────

    def _handle_js_event(self, source, event_type: str, payload: str):
        """处理 JS 桥接过来的 DOM 事件（在 transport 线程调用，禁止访问 page API）"""
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return

        snap_id = self._last_snapshot_id()

        with self._lock:
            if not self._active:
                return

            if event_type == "click":
                target = self._build_target_from_js(data)
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.CLICK,
                    target=target,
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "dblclick":
                target = self._build_target_from_js(data)
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.DBLCLICK,
                    target=target,
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "rightclick":
                target = self._build_target_from_js(data)
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.RIGHTCLICK,
                    target=target,
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "hover":
                target = self._build_target_from_js(data)
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.HOVER,
                    target=target,
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "drop":
                source_data = data.get("source", {})
                target_data = data.get("target", {})
                source_target = self._build_target_from_js(source_data) if source_data else Target()
                target_target = self._build_target_from_js(target_data) if target_data else Target()
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.DROP,
                    target=target_target,
                    value=json.dumps({"source_label": source_target.label, "source_tag": source_target.tag}),
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "scroll":
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.SCROLL,
                    target=Target(url=data.get("url", self.page.url)),
                    value=json.dumps({"x": data.get("x", 0), "y": data.get("y", 0)}),
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "input":
                target = self._build_target_from_js(data)
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.INPUT,
                    target=target,
                    value=data.get("value", ""),
                    input_type="fill",
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "select":
                target = self._build_target_from_js(data)
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.SELECT,
                    target=target,
                    value=data.get("value", ""),
                    timestamp_ms=self._ts(),
                ))

            elif event_type == "keydown":
                target_data = data.get("target", {})
                target = self._build_target_from_js(target_data) if target_data else Target(url=self.page.url)
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.KEYDOWN,
                    target=target,
                    value="Enter",
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "mutation":
                # 动态 DOM 变化（AJAX 加载、延迟渲染等）
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.MUTATION,
                    target=Target(url=data.get("url", self.page.url)),
                    value=json.dumps({
                        "added": data.get("added", 0),
                        "removed": data.get("removed", 0),
                        "attrChanged": data.get("attrChanged", 0),
                    }),
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

    # ── Console 事件处理（Playwright 安全线程，可以调 page API）──

    def _on_console(self, msg):
        """捕获 console.log 桥接的 SPA 导航事件。在 Playwright 事件线程调用，安全调 page API。"""
        text = msg.text
        if not text.startswith("__uibridge_nav__:"):
            return
        try:
            payload = text[len("__uibridge_nav__:"):]
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return

        url = data.get("url", self.page.url)
        snap = self._capture_snapshot()

        with self._lock:
            if not self._active:
                return
            self.steps.append(RawStep(
                id=self._step_id(),
                action=ActionType.NAVIGATE,
                target=Target(url=url),
                timestamp_ms=self._ts(),
                after_snapshot_id=snap.id,
            ))

    # ── 原生 Playwright 事件（安全线程）───────────────────────

    def _on_navigate(self, frame):
        """framenavigated 是 Playwright 原生事件，在安全时机触发，可以调用 page API"""
        if not self._active:
            return
        if frame != self.page.main_frame:
            return
        snap = self._capture_snapshot()
        with self._lock:
            if not self._active:
                return
            self.steps.append(RawStep(
                id=self._step_id(),
                action=ActionType.NAVIGATE,
                target=Target(url=self.page.url),
                timestamp_ms=self._ts(),
                after_snapshot_id=snap.id,
            ))

    def _on_frame_attached(self, frame):
        """iframe 注入：给新附加的 frame 也注入录制脚本"""
        try:
            frame.expose_binding("__uibridge_report", self._handle_js_event)
        except Exception:
            pass
        try:
            frame.evaluate(RECORDER_JS)
        except Exception:
            pass

    def _on_popup(self, popup):
        """新标签页/窗口检测"""
        if not self._active:
            return
        with self._lock:
            self.steps.append(RawStep(
                id=self._step_id(),
                action=ActionType.TAB_SWITCH,
                target=Target(url=popup.url, page_hint="new_tab"),
                timestamp_ms=self._ts(),
            ))

    # ── 目标构建 ──────────────────────────────

    def _build_target_from_js(self, data: dict) -> Target:
        return Target(
            selectors=SelectorSet(
                css=data.get("css", ""),
                xpath=None,
                text=data.get("label", "")[:50],
                role=data.get("role", ""),
                aria_label=data.get("ariaLabel", ""),
                data_testid=data.get("dataTestid", ""),
                data_module=data.get("dataModule", ""),
            ),
            label=data.get("label", "")[:50],
            tag=data.get("tag", ""),
            url=data.get("url", self.page.url),
        )

    # ── 快照管理（在安全的时机调用）───────────

    def capture_snapshot(self) -> Snapshot:
        """显式捕获当前页面的 ARIA 快照。在事件回调外部调用，安全无死锁。"""
        if not self._active:
            raise RuntimeError("RecordingSession is stopped")
        return self._capture_snapshot()

    def _capture_snapshot(self) -> Snapshot:
        self._snap_counter += 1
        snap_id = f"snap-{self._snap_counter:03d}"
        try:
            aria = self.page.locator("html").aria_snapshot()
        except Exception:
            aria = ""
        try:
            title = self.page.title()
        except Exception:
            title = ""
        try:
            layout_raw = self.page.evaluate("window.__uibridge_get_layout && window.__uibridge_get_layout()")
            layout_info = layout_raw if isinstance(layout_raw, str) else json.dumps(layout_raw or {})
        except Exception:
            layout_info = "{}"
        snapshot = Snapshot(
            id=snap_id,
            url=self.page.url,
            title=title,
            aria_snapshot=aria,
            layout_info=layout_info,
            timestamp_ms=self._ts(),
        )
        self.snapshots[snap_id] = snapshot
        return snapshot

    def _last_snapshot_id(self) -> str | None:
        if self._snap_counter > 0:
            return f"snap-{self._snap_counter:03d}"
        return None

    # ── 程序化控制 ────────────────────────────

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def is_active(self) -> bool:
        return self._active

    def stop(self) -> "RawRecording":
        """程序化停止录制，返回 RawRecording。同时停止运行时分析器。"""
        with self._lock:
            self._active = False
        if self.runtime:
            self.runtime_report = self.runtime.stop()
        return self.to_raw_recording()

    # ── 输出 ────────────────────────────────

    def to_raw_recording(self) -> RawRecording:
        return RawRecording(
            meta=RawRecordingMeta(
                duration_ms=self._ts(),
                generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ),
            steps=self.steps,
            snapshots=self.snapshots,
        )

    # ── 内部工具 ──────────────────────────────

    def _step_id(self) -> str:
        return f"step-{len(self.steps) + 1:03d}"

    def _ts(self) -> int:
        return int((time.time() - self._start_time) * 1000)
