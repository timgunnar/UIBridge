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

    // ── 输入 / 选择变更（捕获阶段以穿透 Shadow DOM）──
    document.addEventListener('change', (e) => {
        const el = e.target;
        if (!visible(el)) return;
        const tag = (el.tagName || '').toLowerCase();
        const typ = (el.getAttribute('type') || '').toLowerCase();
        const d = describe(el);
        d.url = location.href;
        if (tag === 'input' && typ === 'checkbox') {
            d.checked = el.checked;
            window.__uibridge_report('checkbox_change', JSON.stringify(d));
        } else if (tag === 'input' && typ === 'radio') {
            d.checked = el.checked;
            window.__uibridge_report('radio_change', JSON.stringify(d));
        } else if (tag === 'input' && typ === 'file') {
            const files = [];
            for (const f of (el.files || [])) files.push(f.name);
            d.files = files;
            window.__uibridge_report('file_input', JSON.stringify(d));
        } else if (tag === 'input' && typ === 'range') {
            d.value = el.value;
            window.__uibridge_report('range_change', JSON.stringify(d));
        } else if (tag === 'input' || tag === 'textarea') {
            window.__uibridge_report('input', JSON.stringify(d));
        } else if (tag === 'select') {
            if (el.multiple) {
                const selected = [];
                for (const o of el.selectedOptions) selected.push(o.value || o.text);
                d.values = selected;
            }
            window.__uibridge_report('select', JSON.stringify(d));
        }
    }, true);

    // ── 键盘（功能键 + 组合键，普通字符不在此记录）──
    const _FUNCTIONAL_KEYS = new Set([
        'Enter', 'Tab', 'Escape', 'Backspace', 'Delete',
        'ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown',
        'PageUp', 'PageDown', 'Home', 'End',
        'F1', 'F2', 'F3', 'F4', 'F5', 'F6',
        'F7', 'F8', 'F9', 'F10', 'F11', 'F12',
    ]);
    document.addEventListener('keydown', (e) => {
        const is_mod = e.ctrlKey || e.metaKey || e.altKey;
        // 记录：功能键 OR 带修饰键的组合键。普通可打印字符由 input/change 事件记录。
        if (!_FUNCTIONAL_KEYS.has(e.key) && !is_mod) return;
        // 仅修饰键（Ctrl/Shift/Alt/Meta 单独按下）不记录
        if (e.key === 'Control' || e.key === 'Shift' || e.key === 'Alt' || e.key === 'Meta') return;
        const el = e.target;
        const d = el ? describe(el) : {};
        d.url = location.href;
        window.__uibridge_report('keydown', JSON.stringify({
            key: e.key,
            code: e.code,
            ctrlKey: e.ctrlKey || false,
            shiftKey: e.shiftKey || false,
            altKey: e.altKey || false,
            metaKey: e.metaKey || false,
            target: d,
        }));
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

    // ── 表单提交 ──────────────────────────────
    document.addEventListener('submit', (e) => {
        const el = e.target;
        const tag = (el.tagName || '').toLowerCase();
        if (tag !== 'form') return;
        const formId = el.id || el.getAttribute('name') || '';
        const action = el.getAttribute('action') || '';
        const method = el.getAttribute('method') || 'get';
        const inputs = [];
        el.querySelectorAll('input,select,textarea').forEach(ctl => {
            const ctlTag = (ctl.tagName || '').toLowerCase();
            const ctlType = (ctl.getAttribute('type') || 'text').toLowerCase();
            const name = ctl.getAttribute('name') || ctl.id || '';
            if (!name) return;
            if (ctlTag === 'input' && (ctlType === 'submit' || ctlType === 'button')) return;
            inputs.push({name, value: ctl.value || '', tag: ctlTag, type: ctlType});
        });
        window.__uibridge_report('submit', JSON.stringify({
            id: formId, action, method, inputs,
            url: location.href,
        }));
    }, true);

    // ── 焦点变化（Tab 键导航）───────────────
    document.addEventListener('focusin', (e) => {
        const el = e.target;
        if (!el) return;
        const tag = (el.tagName || '').toLowerCase();
        const focusable = ['input', 'select', 'textarea', 'button', 'a'];
        if (!focusable.includes(tag) && el.getAttribute('tabindex') == null) return;
        const d = describe(el);
        d.url = location.href;
        window.__uibridge_report('focus', JSON.stringify(d));
    }, true);

    // ── 剪贴板 ──────────────────────────────
    document.addEventListener('copy', (e) => {
        const el = e.target;
        const d = el ? describe(el) : {};
        const selection = window.getSelection ? window.getSelection().toString().substring(0, 200) : '';
        d.url = location.href;
        d.clipData = selection;
        window.__uibridge_report('clipboard', JSON.stringify({action: 'copy', target: d}));
    }, true);
    document.addEventListener('cut', (e) => {
        const el = e.target;
        const d = el ? describe(el) : {};
        const selection = window.getSelection ? window.getSelection().toString().substring(0, 200) : '';
        d.url = location.href;
        d.clipData = selection;
        window.__uibridge_report('clipboard', JSON.stringify({action: 'cut', target: d}));
    }, true);
    document.addEventListener('paste', (e) => {
        const el = e.target;
        const d = el ? describe(el) : {};
        d.url = location.href;
        const clipData = (e.clipboardData && e.clipboardData.getData('text'))
            ? e.clipboardData.getData('text').substring(0, 200)
            : '';
        d.clipData = clipData;
        window.__uibridge_report('clipboard', JSON.stringify({action: 'paste', target: d}));
    }, true);

    // ── 原生弹窗拦截 ────────────────────────
    if (!window.__uibridge_dialog_patched) {
        window.__uibridge_dialog_patched = true;
        const _orig_alert = window.alert;
        const _orig_confirm = window.confirm;
        const _orig_prompt = window.prompt;
        window.alert = function(msg) {
            window.__uibridge_report('dialog', JSON.stringify({
                type: 'alert', message: String(msg || ''),
            }));
            return _orig_alert.call(window, msg);
        };
        window.confirm = function(msg) {
            window.__uibridge_report('dialog', JSON.stringify({
                type: 'confirm', message: String(msg || ''),
            }));
            return _orig_confirm.call(window, msg);
        };
        window.prompt = function(msg, defaultText) {
            window.__uibridge_report('dialog', JSON.stringify({
                type: 'prompt', message: String(msg || ''),
                defaultValue: String(defaultText || ''),
            }));
            return _orig_prompt.call(window, msg, defaultText);
        };
    }

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

    // Turbolinks / Turbo 导航检测
    document.addEventListener('turbolinks:load', _report_url_change, true);
    document.addEventListener('turbo:load', _report_url_change, true);
    document.addEventListener('turbolinks:visit', _report_url_change, true);
    document.addEventListener('turbo:visit', _report_url_change, true);

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
    // 优先观察 documentElement（始终存在），body 异步就绪后再追加
    function _start_observing() {
        const target = document.body || document.documentElement;
        _mo.observe(target, {
            childList: true, subtree: true, attributes: true,
            attributeFilter: ['class', 'style', 'disabled', 'aria-expanded', 'aria-selected', 'hidden'],
        });
        if (!document.body) {
            // body 尚未就绪，轮询等待
            const _check = setInterval(() => {
                if (document.body) {
                    clearInterval(_check);
                    _mo.observe(document.body, {
                        childList: true, subtree: true, attributes: true,
                        attributeFilter: ['class', 'style', 'disabled', 'aria-expanded', 'aria-selected', 'hidden'],
                    });
                }
            }, 50);
            setTimeout(() => clearInterval(_check), 10000); // 超时保护
        }
    }
    _start_observing();

    // ── Shadow DOM 辅助：遍历所有 shadow root 执行查询 ──
    function _query_all_deep(root, selector) {
        const results = [];
        try {
            const els = root.querySelectorAll(selector);
            for (const el of els) results.push(el);
        } catch(e) {}
        // 递归遍历 shadow roots
        const all_els = root.querySelectorAll('*');
        for (const el of all_els) {
            if (el.shadowRoot) {
                const deep = _query_all_deep(el.shadowRoot, selector);
                for (const d of deep) results.push(d);
            }
        }
        return results;
    }

    // ── 布局信息采集（供快照位置对比，含 Shadow DOM）──
    window.__uibridge_get_layout = function(selector) {
        const q = selector || '[id],[data-testid],[data-module],[role],button,input,select,textarea,table,[aria-label]';
        const els = _query_all_deep(document, q);
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
        self._event_count = 0  # 收到的事件总数（诊断用）
        self._start_time = time.time()
        self._active = True
        self._lock = threading.Lock()
        self._spa_nav_pending = False
        # 在初始化时（安全线程）捕获当前 URL，避免后续在 transport 线程访问 page.url
        self._current_url = page.url
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

        # 刷新排队中的 expose_binding 回调（sync_playwright 调度器只在 API 调用时处理回调）
        try:
            self.page.wait_for_timeout(100)
        except Exception:
            pass

        self.page.on("framenavigated", self._on_navigate)
        self.page.on("console", self._on_console)
        self.page.on("frameattached", self._on_frame_attached)
        self.page.on("popup", self._on_popup)

        # 捕获初始页面快照
        self._capture_snapshot()

    # ── JS 事件处理（transport 线程，禁止调 page API）─────────

    def _handle_js_event(self, source, event_type: str, payload: str):
        """处理 JS 桥接过来的 DOM 事件（在 transport 线程调用，禁止访问 page API）"""
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return

        self._event_count += 1

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
                    target=Target(url=data.get("url", self._current_url)),
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
                values = data.get("values")
                if values is not None:
                    value = json.dumps(values)
                else:
                    value = data.get("value", "")
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.SELECT,
                    target=target,
                    value=value,
                    timestamp_ms=self._ts(),
                ))

            elif event_type == "keydown":
                target_data = data.get("target", {})
                target = self._build_target_from_js(target_data) if target_data else Target(url=self._current_url)
                value = data.get("key", "")  # 只存 key 名，value 可空
                input_type = "press"
                if data.get("ctrlKey"):
                    input_type = "shortcut"
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.KEYDOWN,
                    target=target,
                    value=value,
                    input_type=input_type,
                    modifiers=self._modifiers_from_event(data),
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "checkbox_change":
                target = self._build_target_from_js(data)
                checked = data.get("checked", False)
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.CHECK if checked else ActionType.UNCHECK,
                    target=target,
                    value=str(checked).lower(),
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "radio_change":
                target = self._build_target_from_js(data)
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.CHECK,
                    target=target,
                    value="true",
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "file_input":
                target = self._build_target_from_js(data)
                files = data.get("files", [])
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.FILE_UPLOAD,
                    target=target,
                    value=json.dumps(files),
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "range_change":
                target = self._build_target_from_js(data)
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.INPUT,
                    target=target,
                    value=str(data.get("value", "")),
                    input_type="range",
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "submit":
                form_id = data.get("id", "")
                form_action = data.get("action", "")
                form_method = data.get("method", "get")
                inputs = data.get("inputs", [])
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.SUBMIT,
                    target=Target(
                        label=form_id or form_action or "form",
                        url=data.get("url", self._current_url),
                    ),
                    value=json.dumps({
                        "action": form_action,
                        "method": form_method,
                        "inputs": inputs,
                    }),
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "focus":
                target = self._build_target_from_js(data)
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.FOCUS,
                    target=target,
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "clipboard":
                clipboard_action = data.get("action", "unknown")
                target_data = data.get("target", {})
                target = self._build_target_from_js(target_data) if target_data else Target(url=self._current_url)
                clip_data = target_data.get("clipData", "") if target_data else ""
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.CLIPBOARD,
                    target=target,
                    value=json.dumps({"action": clipboard_action, "data": clip_data}),
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "dialog":
                dialog_type = data.get("type", "alert")
                message = data.get("message", "")
                value = message
                if dialog_type == "prompt":
                    value = json.dumps({"message": message, "defaultValue": data.get("defaultValue", "")})
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.DIALOG,
                    target=Target(label=f"{dialog_type} dialog", url=self._current_url),
                    value=value,
                    input_type=dialog_type,
                    timestamp_ms=self._ts(),
                    before_snapshot_id=snap_id,
                ))

            elif event_type == "mutation":
                # 动态 DOM 变化（AJAX 加载、延迟渲染等）
                self.steps.append(RawStep(
                    id=self._step_id(),
                    action=ActionType.MUTATION,
                    target=Target(url=data.get("url", self._current_url)),
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
        self._current_url = url
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
        self._current_url = self.page.url
        snap = self._capture_snapshot()
        with self._lock:
            if not self._active:
                return
            self.steps.append(RawStep(
                id=self._step_id(),
                action=ActionType.NAVIGATE,
                target=Target(url=self._current_url),
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
            frame.add_init_script(RECORDER_JS)
        except Exception:
            pass
        try:
            frame.evaluate(RECORDER_JS)
        except Exception:
            pass

    def _on_popup(self, popup):
        """新标签页/窗口检测 — 注入录制桥接 + 注册所有事件监听，完全纳入录制"""
        if not self._active:
            return
        try:
            popup.expose_binding("__uibridge_report", self._handle_js_event)
        except Exception:
            pass
        try:
            popup.add_init_script(RECORDER_JS)
        except Exception:
            pass
        try:
            popup.evaluate(RECORDER_JS)
        except Exception:
            pass
        popup.on("framenavigated", self._on_navigate)
        popup.on("console", self._on_console)
        popup.on("frameattached", self._on_frame_attached)
        popup.on("popup", self._on_popup)
        with self._lock:
            self.steps.append(RawStep(
                id=self._step_id(),
                action=ActionType.TAB_SWITCH,
                target=Target(url=popup.url, page_hint="new_tab"),
                timestamp_ms=self._ts(),
            ))

    # ── 目标构建 ──────────────────────────────

    def _modifiers_from_event(self, data: dict) -> list[str]:
        """从 JS 键事件数据中提取修饰键列表。"""
        mods = []
        if data.get("ctrlKey"):
            mods.append("Ctrl")
        if data.get("shiftKey"):
            mods.append("Shift")
        if data.get("altKey"):
            mods.append("Alt")
        if data.get("metaKey"):
            mods.append("Meta")
        return mods

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
            url=data.get("url", self._current_url),
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
        errors = []
        try:
            aria = self.page.locator("html").aria_snapshot()
        except Exception as e:
            aria = ""
            errors.append(f"aria_snapshot: {e}")
        try:
            title = self.page.title()
        except Exception as e:
            title = ""
            errors.append(f"title: {e}")
        try:
            layout_raw = self.page.evaluate("window.__uibridge_get_layout && window.__uibridge_get_layout()")
            layout_info = layout_raw if isinstance(layout_raw, str) else json.dumps(layout_raw or {})
        except Exception as e:
            layout_info = "{}"
            errors.append(f"layout: {e}")
        url = self.page.url
        self._current_url = url
        snapshot = Snapshot(
            id=snap_id,
            url=url,
            title=title,
            aria_snapshot=aria,
            layout_info=layout_info,
            timestamp_ms=self._ts(),
        )
        if errors:
            snapshot.error = "; ".join(errors)
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
