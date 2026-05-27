"""录制引擎 — Playwright 事件监听，捕获用户操作"""

import json
import time
import threading
import logging

logger = logging.getLogger(__name__)
from playwright.sync_api import Page

from .ir.raw_recording import (
    RawRecording, RawRecordingMeta, RawStep, ActionType,
    Target, SelectorSet, Snapshot,
)
from .runtime_analyzer import RuntimeAnalyzer, RuntimeReport

from .recorder_js import RECORDER_JS


class RecordingSession:
    """录制会话。注入 Playwright page，监听交互事件并输出标准化 IR v1。

    使用 expose_binding + add_init_script 实现 DOM 事件捕获。
    快照通过 capture_snapshot() 显式触发，避免 expose_binding 回调中
    调用 page API 导致的死锁。
    SPA 导航通过 console.log 桥接 → page.on("console") 在安全线程捕获。
    """

    def __init__(self, page: Page, enable_runtime: bool = True, locator_attrs: list[str] | None = None):
        self.page = page
        self.steps: list[RawStep] = []
        self.snapshots: dict[str, Snapshot] = {}
        self._snap_counter = 0
        self._event_count = 0  # 收到的事件总数（诊断用）
        self._start_time = time.time()
        self._active = True
        self._lock = threading.Lock()
        self._spa_nav_pending = False
        self.locator_attrs = locator_attrs  # KB 驱动噪声过滤：定位器属性白名单
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
            logger.warning("Failed to evaluate recorder JS on page", exc_info=True)
            pass

        # KB 驱动噪声过滤：将定位器属性白名单注入浏览器
        if self.locator_attrs:
            try:
                self.page.evaluate(
                    "window.__uibridge_locator_attrs = " + json.dumps(self.locator_attrs)
                )
            except Exception:
                logger.warning("Failed to inject locator attrs whitelist", exc_info=True)
                pass

        # 刷新排队中的 expose_binding 回调（sync_playwright 调度器只在 API 调用时处理回调）
        try:
            self.page.wait_for_timeout(100)
        except Exception:
            logger.warning("Failed to flush expose_binding callbacks", exc_info=True)
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

        # 大规模录制警告：每 100 条事件输出提示
        if self._event_count % 100 == 0:
            logger.warning(
                "录制事件已达 %s 条。大规模录制可能导致生成耗时较长，"
                "建议拆分录制为多个较短的操作序列。",
                self._event_count
            )

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
            logger.warning("Failed to expose binding on attached frame", exc_info=True)
            pass
        try:
            frame.add_init_script(RECORDER_JS)
        except Exception:
            logger.warning("Failed to add init script to attached frame", exc_info=True)
            pass
        try:
            frame.evaluate(RECORDER_JS)
        except Exception:
            logger.warning("Failed to evaluate recorder JS on attached frame", exc_info=True)
            pass

    def _on_popup(self, popup):
        """新标签页/窗口检测 — 注入录制桥接 + 注册所有事件监听，完全纳入录制"""
        if not self._active:
            return
        try:
            popup.expose_binding("__uibridge_report", self._handle_js_event)
        except Exception:
            logger.warning("Failed to expose binding on popup", exc_info=True)
            pass
        try:
            popup.add_init_script(RECORDER_JS)
        except Exception:
            logger.warning("Failed to add init script to popup", exc_info=True)
            pass
        try:
            popup.evaluate(RECORDER_JS)
        except Exception:
            logger.warning("Failed to evaluate recorder JS on popup", exc_info=True)
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
            logger.warning("Failed to capture ARIA snapshot", exc_info=True)
            aria = ""
            errors.append(f"aria_snapshot: {e}")
        try:
            title = self.page.title()
        except Exception as e:
            logger.warning("Failed to capture page title", exc_info=True)
            title = ""
            errors.append(f"title: {e}")
        try:
            layout_raw = self.page.evaluate("window.__uibridge_get_layout && window.__uibridge_get_layout()")
            layout_info = layout_raw if isinstance(layout_raw, str) else json.dumps(layout_raw or {})
        except Exception as e:
            logger.warning("Failed to capture layout info", exc_info=True)
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
        # 刷新 JS 端待处理的 mutation（去抖窗口内的数据）
        # 必须在设置 _active = False 之前，否则 _handle_js_event 会拒绝事件
        try:
            self.page.evaluate("window.__uibridge_flush_mutations && window.__uibridge_flush_mutations()")
            self.page.wait_for_timeout(300)
        except Exception:
            logger.warning("Failed to flush pending mutations before stop", exc_info=True)
            pass
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
