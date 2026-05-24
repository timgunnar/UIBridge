"""MCP Server — 将 uibridge 功能暴露为 AI Agent 可调用的类型化工具。

启动方式:
    python -m uibridge.mcp_server

或在 .mcp.json 中注册为 Claude Code 等 Agent 的工具源。
"""

import asyncio
import concurrent.futures
import json
import logging
import sys
import threading
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 超时与阈值常量 ──────────────────────────────────────
OPEN_BROWSER_TIMEOUT = 1800  # 打开浏览器后等待开始录制的最长时间（秒）
RECORDING_TIMEOUT = 600       # 录制会话的最长时间（秒）
MAX_RECORDING_STEPS = 200     # MCP 模式下允许的最大录制步骤数

# 将 editable finders 提升到 meta_path 最前面，
# 防止 CWD 下同名目录被 PathFinder 优先匹配为命名空间包。
_editable_finders = [f for f in sys.meta_path if hasattr(f, '__name__') and '__editable__' in f.__name__]
for _ef in reversed(_editable_finders):
    sys.meta_path.remove(_ef)
    sys.meta_path.insert(0, _ef)

import yaml
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "uibridge",
    instructions="UI 自动化测试脚本智能生成系统 — 录制浏览器操作 → 自动生成测试代码",
)

# ── 单线程执行器：所有 sync Playwright 操作在此线程运行 ──
#   max_workers=1 保证 start_recording / stop_recording 在同一线程，
#   sync_playwright() 在此线程无 asyncio 事件循环，不会冲突。
_pw_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="uibridge_pw")


async def _run_pw(func, *args, **kwargs):
    """在专用 Playwright 线程中执行同步函数，返回结果或传播异常。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_pw_executor, lambda: func(*args, **kwargs))


# ── 模块级状态 ──────────────────────────────────────
# 三段式录制: open_browser → start_recording → stop_recording
_active_browser_staging: dict | None = None  # open_browser 阶段：浏览器已打开但未开始录制
_active_recording: dict | None = None        # start_recording 阶段：录制进行中
_recording_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════
# 辅助函数（线程安全，不调 Playwright API）
# ═══════════════════════════════════════════════════════════

# 禁止的协议前缀，防止 URL 注入
_BLOCKED_URL_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")

# 允许的输出基础目录：调用方 CWD（即 Agent / 企业项目根目录）
_OUTPUT_BASE = Path.cwd()


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


def _load_adapter(adapter_config_path: Optional[str] = None):
    """加载适配器的 5 个接口实例（委托给共享工厂）"""
    from uibridge.adapter.loader import load_adapter
    return load_adapter(adapter_config_path)


def _build_pipeline(adapter_config_path: Optional[str] = None, project_dir: str = "."):
    from uibridge.pipeline import Pipeline
    from uibridge.profile_manager import ProfileManager
    from uibridge.kb.manager import KBManager
    resolver, locator, recognizer, code_gen, data_fmt = _load_adapter(adapter_config_path)
    profile_mgr = ProfileManager(project_dir)
    kb = KBManager(project_dir, profile_manager=profile_mgr)
    return Pipeline(resolver, locator, recognizer, code_gen, data_fmt,
                    project_root=project_dir, kb_manager=kb, profile_manager=profile_mgr)


# ═══════════════════════════════════════════════════════════
# MCP Tools
# ═══════════════════════════════════════════════════════════

@mcp.tool()
async def analyze_page(
    url: str,
    adapter_config: Optional[str] = None,
) -> str:
    """分析一个页面，发现其中的 UI 组件（表格、输入框、按钮等）并输出注册表。

    用于：在录制或生成测试之前，了解页面有哪些组件、它们叫什么、怎么定位。
    返回：JSON 格式的组件列表，每个组件包含 type/name/xpath/aria_role。
    """

    _validate_url(url)

    available, path_or_error = check_browser_available("chromium")
    if not available:
        return json.dumps({"error": f"浏览器不可用: {path_or_error}"}, indent=2, ensure_ascii=False)

    def _sync():
        from playwright.sync_api import sync_playwright

        pipeline = _build_pipeline(adapter_config)

        pw = None
        browser = None
        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url)
            page.wait_for_load_state("networkidle")
            components = pipeline.discover_components(page)
            return json.dumps(components, indent=2, ensure_ascii=False)
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    logger.warning("Failed to close browser in discover_components cleanup", exc_info=True)
                    pass
            if pw:
                try:
                    pw.stop()
                except Exception:
                    logger.warning("Failed to stop playwright in discover_components cleanup", exc_info=True)
                    pass

    return await _run_pw(_sync)


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
        global _active_browser_staging, _active_recording
        from playwright.sync_api import sync_playwright

        pw = None
        context = None
        try:
            with _recording_lock:
                # 录制进行中时拒绝打开新浏览器，防止误杀
                if _active_recording:
                    return json.dumps({
                        "error": "录制正在进行中。请先调用 stop_recording 结束当前录制，再打开新浏览器。",
                    }, indent=2, ensure_ascii=False)
                if _active_browser_staging:
                    try:
                        _active_browser_staging["context"].close()
                    except Exception:
                        logger.warning("Failed to close existing staging browser context", exc_info=True)
                        pass
                    try:
                        _active_browser_staging["pw"].stop()
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
                    with _recording_lock:
                        if _active_browser_staging and _active_browser_staging.get("session_id") == session_id:
                            try:
                                _active_browser_staging["context"].close()
                            except Exception:
                                logger.warning("Failed to close staging browser context on auto-cleanup", exc_info=True)
                                pass
                            try:
                                _active_browser_staging["pw"].stop()
                            except Exception:
                                logger.warning("Failed to stop staging playwright on auto-cleanup", exc_info=True)
                                pass
                            _active_browser_staging = None

                timer = threading.Timer(OPEN_BROWSER_TIMEOUT, _auto_cleanup_staging)
                timer.daemon = True
                timer.start()

                _active_browser_staging = {
                    "session_id": session_id,
                    "page": page,
                    "context": context,
                    "pw": pw,
                    "_timeout_timer": timer,
                }

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
            with _recording_lock:
                _active_browser_staging = None
            raise

    return await _run_pw(_sync)


@mcp.tool()
async def start_recording(
    adapter_config: Optional[str] = None,
) -> str:
    """在已打开的浏览器上开始录制。必须先调用 open_browser 打开浏览器。

    这是三段式录制的第二步。在 open_browser 打开的浏览器上注入事件监听，
    开始捕获用户在浏览器中的操作。

    如果用户在调用 start_recording 前做了预置操作（登录、导航等），
    这些预置操作不会被录制，只录制 start_recording 之后的操作。

    三段式流程: open_browser → [用户预置] → start_recording → [用户操作] → stop_recording

    返回：会话状态 JSON，含 session_id。
    """

    def _sync():
        global _active_browser_staging, _active_recording
        from playwright.sync_api import sync_playwright

        pipeline = _build_pipeline(adapter_config)

        # KB 驱动噪声过滤：查询 KB 获取定位器属性白名单
        locator_attrs = None
        if pipeline.kb_manager:
            try:
                locator_conventions = pipeline.kb_manager.get_locator_conventions()
                if locator_conventions:
                    priority = locator_conventions.get("priority", [])
                    if priority:
                        locator_attrs = priority[:5]  # Top 5 定位器属性
            except Exception:
                logger.warning("Failed to get locator conventions from KB", exc_info=True)
                pass

        try:
            with _recording_lock:
                if not _active_browser_staging:
                    return json.dumps({
                        "error": "没有已打开的浏览器。请先调用 open_browser 打开浏览器。",
                    }, indent=2, ensure_ascii=False)

                page = _active_browser_staging["page"]
                context = _active_browser_staging["context"]
                pw = _active_browser_staging["pw"]
                session_id = _active_browser_staging["session_id"]
                staging_timer = _active_browser_staging.get("_timeout_timer")
                if staging_timer:
                    try:
                        staging_timer.cancel()
                    except Exception:
                        logger.warning("Failed to cancel staging timeout timer", exc_info=True)
                        pass
                _active_browser_staging = None

                current_url = page.url

                session = pipeline.record(page, locator_attrs=locator_attrs)

                # 10 分钟超时保护
                def _auto_stop():
                    with _recording_lock:
                        if _active_recording is not None:
                            try:
                                _active_recording["session"].stop()
                            except Exception:
                                logger.warning("Failed to stop recording session on auto-stop", exc_info=True)
                                pass
                            try:
                                _active_recording["context"].close()
                            except Exception:
                                logger.warning("Failed to close browser context on auto-stop", exc_info=True)
                                pass
                            try:
                                _active_recording["pw"].stop()
                            except Exception:
                                logger.warning("Failed to stop playwright on auto-stop", exc_info=True)
                                pass
                            if _active_recording.get("_timeout_timer"):
                                _active_recording["_timeout_timer"].cancel()
                            _active_recording = None

                timer = threading.Timer(RECORDING_TIMEOUT, _auto_stop)
                timer.daemon = True
                timer.start()

                _active_recording = {
                    "session": session,
                    "session_id": session_id,
                    "page": page,
                    "context": context,
                    "pw": pw,
                    "_timeout_timer": timer,
                }

            return json.dumps({
                "status": "recording",
                "session_id": session_id,
                "current_url": current_url,
                "hint": "录制中。用户在浏览器中操作，完成后 Agent 调用 stop_recording。",
            }, indent=2, ensure_ascii=False)
        except Exception:
            logger.warning("Failed to start recording session", exc_info=True)
            with _recording_lock:
                _active_browser_staging = None
                _active_recording = None
            raise

    return await _run_pw(_sync)


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
        global _active_recording

        with _recording_lock:
            if not _active_recording:
                return json.dumps({
                    "error": "没有活跃的录制会话。请先调用 start_recording。",
                }, indent=2, ensure_ascii=False)

            # 先取消超时定时器，防止与正常 stop 并发
            timer = _active_recording.get("_timeout_timer")
            if timer:
                try:
                    timer.cancel()
                except Exception:
                    logger.warning("Failed to cancel recording timeout timer", exc_info=True)
                    pass

            session = _active_recording["session"]
            context = _active_recording["context"]
            pw = _active_recording["pw"]
            page = _active_recording["page"]
            _active_recording = None

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

    return await _run_pw(_sync)


# record_browser_operations 是 CLI 专用工具，不作为 MCP 工具暴露。
# MCP/Agent 场景使用三段式: open_browser → start_recording → stop_recording


@mcp.tool()
async def generate_test_code(
    input_file: str = "recording.json",
    output_dir: str = "generated",
    adapter_config: Optional[str] = None,
) -> str:
    """从录制文件生成测试脚本代码。

    这是核心工具：读取录制 JSON → 语义分析 → 框架映射 → 代码生成 → 自检。

    参数：
    - input_file: 录制文件路径，默认 recording.json
    - output_dir: 生成代码输出目录，默认 generated/
    - adapter_config: 适配器配置文件路径（默认自动选择）
    返回：每个生成文件的测试名、自检状态、代码片段。
    """
    from uibridge.engine.ir.raw_recording import RawRecording

    input_path = Path(input_file)
    if not input_path.exists():
        return json.dumps({
            "error": f"录制文件不存在: {input_file}",
            "hint": "请先录制浏览器操作（start_recording → 用户操作 → stop_recording）",
        }, indent=2, ensure_ascii=False)

    data = json.loads(input_path.read_text("utf-8"))
    recording = RawRecording.from_dict(data)

    # 大规模录制保护：超过阈值时返回提示而非直接超时
    actionable_steps = [s for s in recording.steps if s.action.value not in ("mutation",)]
    if len(actionable_steps) > MAX_RECORDING_STEPS:
        return json.dumps({
            "warning": f"录制包含 {len(actionable_steps)} 个有效步骤（共 {len(recording.steps)} 个事件），"
                       f"MCP 模式下可能超时。",
            "suggestion": "建议使用 CLI 生成：uibridge generate -i recording.json -o generated/",
            "step_count": len(actionable_steps),
            "total_events": len(recording.steps),
            "estimated_scenes": len(actionable_steps) // 50 + 1,
        }, indent=2, ensure_ascii=False)

    pipeline = _build_pipeline(adapter_config)

    semantic = pipeline.analyze(recording)
    call_seq = pipeline.map_to_framework(semantic)
    results = pipeline.generate_and_verify(call_seq, recording)

    # Channel 3: Persist IR for regeneration
    try:
        pipeline.persist_ir(input_file, recording, semantic, call_seq, results)
    except Exception:
        logger.warning("Failed to persist IR for regeneration", exc_info=True)

    # 自动模式挖掘：每次生成后从语义序列中挖掘可复用的 BAW 模式，写入 KB
    pattern_count = 0
    if pipeline.kb_manager:
        try:
            patterns = pipeline.mine_baw_patterns(semantic)
            from uibridge.kb.item import KBItem, Confidence, KnowledgeSource
            for p in patterns:
                key = f"pattern.{p.get('baw_name', 'auto').lower()}"
                existing = pipeline.kb_manager.store.get_by_key("patterns", key)
                if existing:
                    existing.value["frequency"] = existing.value.get("frequency", 0) + p.get("frequency", 0)
                    existing.version += 1
                    pipeline.kb_manager.store.save(existing)
                else:
                    item = KBItem(
                        id=f"auto_pattern_{key}",
                        category="patterns",
                        key=key,
                        value={"actions": p.get("actions", []), "frequency": p.get("frequency", 0),
                               "suggestion": p.get("suggestion", "")},
                        confidence=Confidence(score=0.55, source=KnowledgeSource.PATTERN_MINING),
                        description=p.get("pattern", ""),
                        tags=["auto-mined", "pattern"],
                    )
                    pipeline.kb_manager.store.save(item)
                    pattern_count += 1
        except Exception:
            logger.warning("Failed to save auto-mined pattern to KB", exc_info=True)
            pass

    out_dir = _sanitize_output_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    output = []
    for r in results:
        ext = ".java" if getattr(pipeline.code_generator, "target_language", "python") == "java" else ".py"
        test_file = out_dir / f"{r['test_name']}{ext}"
        test_file.write_text(r["code"], encoding="utf-8")

        if r.get("data_def"):
            data_file = out_dir / r["data_def"].file_path
            data_file.parent.mkdir(parents=True, exist_ok=True)
            data_file.write_text(r["data_code"], encoding="utf-8")

        output.append({
            "test_name": r["test_name"],
            "status": r["verify"].status,
            "review_needed": r.get("review_needed", False),
            "kb_items_updated": r.get("kb_items_updated", 0),
            "file": str(test_file.absolute()),
            "code_preview": r["code"][:500],
            "fix_suggestion": r["verify"].fix_suggestion if r["verify"].status != "passed" else None,
        })

    if pattern_count > 0:
        output.append({"pattern_mining": f"发现 {pattern_count} 个新模式，已写入 KB"})

    return json.dumps(output, indent=2, ensure_ascii=False)


@mcp.tool()
async def diff_snapshots(
    input_file: str = "recording.json",
    adapter_config: Optional[str] = None,
) -> str:
    """对比录制中的前后快照差异，生成断言候选列表。

    用于：录制完成后，想知道"操作后页面发生了什么变化，应该断言什么"。

    参数：
    - input_file: 录制文件路径
    返回：断言候选列表（如 "新增了 1 个 table row"、"button 从 disabled 变为 enabled"）。
    """
    from uibridge.engine.ir.raw_recording import RawRecording

    input_path = Path(input_file)
    if not input_path.exists():
        return json.dumps({
            "error": f"录制文件不存在: {input_file}",
            "hint": "请先录制浏览器操作（start_recording → 用户操作 → stop_recording）",
        }, indent=2, ensure_ascii=False)

    data = json.loads(input_path.read_text("utf-8"))
    recording = RawRecording.from_dict(data)

    pipeline = _build_pipeline(adapter_config)
    candidates = pipeline.diff_snapshots(recording)

    return json.dumps({
        "count": len(candidates),
        "candidates": candidates,
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def seed_knowledge_base(
    project_dir: str,
) -> str:
    """从企业项目的源码目录提取知识，播种知识库。

    用于：首次接入新项目时，扫描源码提取组件、页面、约定等信息。
    支持 Python（AST）和 Java（javalang）源码。

    参数：
    - project_dir: 项目根目录路径
    返回：播种的 KB 条目数量和分类。
    """
    from uibridge.kb.manager import KBManager

    km = KBManager(project_dir)
    items = km.auto_seed()
    if not items:
        # KB 已有足够条目，返回当前状态
        existing = km.store.list_all()
        categories = {}
        for item in existing:
            categories[item.category] = categories.get(item.category, 0) + 1
        return json.dumps({
            "status": "ok",
            "message": "KB 已有足够条目，跳过自动播种",
            "total_items": len(existing),
            "by_category": categories,
            "kb_dir": str(Path(project_dir) / ".uibridge" / "kb"),
        }, indent=2, ensure_ascii=False)

    categories = {}
    for item in items:
        categories[item.category] = categories.get(item.category, 0) + 1

    return json.dumps({
        "status": "ok",
        "total_items": len(items),
        "by_category": categories,
        "kb_dir": str(Path(project_dir) / ".uibridge" / "kb"),
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def query_knowledge_base(
    query: str,
    project_dir: str = ".",
) -> str:
    """查询知识库，获取框架约定、组件信息等。

    用于：Agent 需要了解"这个项目的定位器优先级是什么"、"TableAW 用什么 XPath"等。

    参数：
    - query: 自然语言查询词（如 "定位器约定"、"TableAW"）
    - project_dir: 项目根目录路径
    返回：匹配的 KB 条目。
    """
    from uibridge.kb.manager import KBManager

    km = KBManager(project_dir)
    result = km.query_nl(query)
    return result


@mcp.tool()
async def update_knowledge_base(
    instruction: str,
    project_dir: str = ".",
) -> str:
    """通过自然语言指令操作知识库：查询、新增、修改、删除条目。

    用于：用户通过 Agent 对话来管理 KB，Agent 将此工具暴露给用户。
    支持 4 种意图：
    - QUERY: "表格组件的定位方式是什么？"
    - ADD:   "新增规则：弹窗用 role='dialog' 识别"
    - MODIFY:"把表格组件的定位方式改为 data-testid"
    - DELETE:"删掉表格排序的规则"

    KB 文件存储在 project_dir/.uibridge/kb/ 下，可 commit 到版本控制。

    参数：
    - instruction: 自然语言指令（中文/英文）
    - project_dir: 项目根目录路径
    返回：操作结果。
    """
    import json
    from uibridge.kb.manager import KBManager

    km = KBManager(project_dir)
    result = km.operate_nl(instruction)
    return json.dumps(result, indent=2, ensure_ascii=False)


# ── 入口 ──────────────────────────────────────────────────

def _startup_check():
    """启动时检查 Playwright 浏览器可用性，输出到 stderr（stdio 模式下不干扰 JSON-RPC）。"""
    import sys
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


# ── Structured KB CRUD Tools ────────────────────────────


@mcp.tool()
async def add_kb_rule(
    category: str,
    key: str,
    value_json: str,
    description: str = "",
    project_dir: str = ".",
) -> str:
    """新增 KB 规则。结构化参数，由 LLM 客户端解析用户的 NL 输入后填入。

    Args:
        category: conventions | components | patterns | pages
        key: 人类可读的规则键名，如 "locator.table"
        value_json: JSON 字符串，知识载荷，如 '{"preferred_attribute": "data-module"}'
        description: 可读描述
        project_dir: 项目根目录
    """
    from uibridge.kb.manager import KBManager
    from uibridge.kb.item import KnowledgeSource
    from uibridge.kb.audit import AuditLogger

    valid_cats = {"conventions", "components", "patterns", "pages"}
    if category not in valid_cats:
        return json.dumps({"error": f"Invalid category. Must be one of: {valid_cats}"},
                          indent=2, ensure_ascii=False)
    try:
        value = json.loads(value_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid value_json: {e}"}, indent=2, ensure_ascii=False)

    audit = AuditLogger(project_dir)
    km = KBManager(project_dir, audit_logger=audit)
    item = km.inject(category=category, key=key, value=value, description=description)
    item.confidence.source = KnowledgeSource.HUMAN_INJECTION
    km.store.save(item)

    return json.dumps({"status": "ok", "message": f"Added [{category}] {key}",
                       "item_id": item.id, "category": category, "key": key},
                      indent=2, ensure_ascii=False)


@mcp.tool()
async def modify_kb_rule(
    category: str,
    item_key: str,
    corrections_json: str,
    nl_note: str = "",
    project_dir: str = ".",
) -> str:
    """修改已有 KB 规则。按 key 查找，按 corrections_json 更新 value 字段。

    Args:
        category: conventions | components | patterns | pages
        item_key: 规则的 key（如 "locator.table"），非 ID
        corrections_json: JSON 字符串，要更新的字段，如 '{"preferred_attribute": "role"}'
        nl_note: 用户 NL 原文，记录在审计日志中
        project_dir: 项目根目录
    """
    from uibridge.kb.manager import KBManager
    from uibridge.kb.audit import AuditLogger

    try:
        corrections = json.loads(corrections_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid corrections_json: {e}"}, indent=2, ensure_ascii=False)

    audit = AuditLogger(project_dir)
    km = KBManager(project_dir, audit_logger=audit)

    item = km.store.get_by_key(category, item_key)
    if not item:
        return json.dumps({"error": f"KB item not found: {category}/{item_key}"},
                          indent=2, ensure_ascii=False)

    before = {"value": item.value.copy(), "description": item.description}
    km.correct(category, item.id, corrections, nl_note=nl_note)
    after_item = km.store.get(category, item.id)

    return json.dumps({"status": "ok", "message": f"Modified [{category}] {item_key}",
                       "old_value": before["value"],
                       "new_value": after_item.value if after_item else {}},
                      indent=2, ensure_ascii=False)


@mcp.tool()
async def delete_kb_rule(
    category: str,
    item_key: str,
    project_dir: str = ".",
) -> str:
    """删除（归档）KB 规则。按 key 查找。

    Args:
        category: conventions | components | patterns | pages
        item_key: 规则的 key
        project_dir: 项目根目录
    """
    from uibridge.kb.manager import KBManager
    from uibridge.kb.audit import AuditLogger

    audit = AuditLogger(project_dir)
    km = KBManager(project_dir, audit_logger=audit)

    item = km.store.get_by_key(category, item_key)
    if not item:
        return json.dumps({"error": f"KB item not found: {category}/{item_key}"},
                          indent=2, ensure_ascii=False)

    before = {"category": item.category, "key": item.key,
              "value": item.value.copy(), "description": item.description}
    km.store.archive(item)
    audit.log("kb.delete", f"{category}/{item_key}", before, {},
              source="delete_kb_rule")

    return json.dumps({"status": "ok", "message": f"Deleted [{category}] {item_key}",
                       "deleted": before}, indent=2, ensure_ascii=False)


@mcp.tool()
async def query_kb_rules(
    query: str = "",
    category: str = "",
    min_confidence: float = 0.3,
    project_dir: str = ".",
) -> str:
    """查询 KB 规则，返回结构化 JSON。

    Args:
        query: 搜索词（留空返回全部）
        category: 按分类过滤（留空返回全部）
        min_confidence: 最低置信度阈值
        project_dir: 项目根目录
    """
    from uibridge.kb.manager import KBManager

    km = KBManager(project_dir)

    if category:
        items = km.store.list_category(category)
        if query:
            q_lower = query.lower()
            items = [i for i in items
                     if q_lower in f"{i.key} {i.description} {str(i.value)}".lower()]
    elif query:
        items = km.store.search(query)
    else:
        items = km.store.list_all()

    items = [i for i in items
             if i.confidence.effective_score >= min_confidence and not i.archived]

    return json.dumps({
        "status": "ok",
        "count": len(items),
        "items": [{"category": i.category, "key": i.key, "id": i.id,
                   "value": i.value, "description": i.description,
                   "confidence": i.confidence.effective_score,
                   "source": i.confidence.source.value} for i in items],
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def update_profile_field(
    field: str,
    value_json: str,
    project_dir: str = ".",
) -> str:
    """更新单个画像字段。

    Valid fields: base_classes, locator_priorities, source_dirs, naming_conventions,
                  ui_packages, annotations, layer_structure, reference_directories,
                  output_config, component_monitoring.

    Args:
        field: 字段名
        value_json: JSON 字符串（dict 字段传 JSON object, list 字段传 JSON array）
        project_dir: 项目根目录
    """
    from uibridge.profile_manager import ProfileManager
    from uibridge.kb.audit import AuditLogger

    try:
        value = json.loads(value_json)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid value_json: {e}"}, indent=2, ensure_ascii=False)

    audit = AuditLogger(project_dir)
    pm = ProfileManager(project_dir)
    old_profile = pm.get_profile()
    before = getattr(old_profile, field).to_dict() if old_profile and hasattr(old_profile, field) else {}

    try:
        profile = pm.update_profile(field, value, source="human_dialogue")
        after = getattr(profile, field).to_dict()
        audit.log("profile.update", f"profile/{field}", before, after,
                  source="update_profile_field")
        return json.dumps({"status": "ok", "field": field,
                           "old_value": before, "new_value": after,
                           "confidence": getattr(profile, field).confidence},
                          indent=2, ensure_ascii=False)
    except (ValueError, KeyError) as e:
        return json.dumps({"error": str(e)}, indent=2, ensure_ascii=False)


@mcp.tool()
async def confirm_profile_fields(
    threshold: float = 0.7,
    project_dir: str = ".",
) -> str:
    """返回置信度低于阈值的画像字段，供用户确认。

    Args:
        threshold: 置信度阈值（0.0-1.0），低于此值的字段需要确认
        project_dir: 项目根目录
    """
    from uibridge.profile_manager import ProfileManager

    pm = ProfileManager(project_dir)
    result = pm.confirm_profile(threshold)
    return json.dumps(result, indent=2, ensure_ascii=False)


# ── Code Review & Regeneration Tools ─────────────────────


@mcp.tool()
async def review_generated_code(
    input_file: str = "recording.json",
    project_dir: str = ".",
) -> str:
    """查看已生成的测试代码及其 IR 结构，用于审查和纠正。

    返回生成代码、review_needed 标记、IR 结构摘要。
    用户审查后通过 regenerate_code 纠正问题。

    Args:
        input_file: 录制文件路径
        project_dir: 项目根目录
    """
    from uibridge.pipeline.ir_persistence import IRPersistence

    ir_persist = IRPersistence(project_dir)
    generated = ir_persist.load_generated_code(input_file)
    if generated is None:
        return json.dumps({
            "error": f"No generated code found for {input_file}. Run generate_test_code first.",
        }, indent=2, ensure_ascii=False)

    ir_data = ir_persist.load(input_file)
    framework_summary = None
    if ir_data:
        _, _, fcs = ir_data
        framework_summary = {
            "test_case_count": len(fcs.test_cases),
            "test_cases": [{"name": tc.name, "review_needed": tc.review_needed,
                            "step_count": len(tc.steps)}
                           for tc in fcs.test_cases],
        }

    return json.dumps({
        "status": "ok",
        "input_file": input_file,
        "generated": generated,
        "framework_summary": framework_summary,
        "hint": "Use regenerate_code to correct issues. If your NL feedback contains "
                "KB knowledge (e.g., 'TableAW base class is BaseWidget'), the KB "
                "will be automatically updated alongside regeneration.",
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def regenerate_code(
    input_file: str = "recording.json",
    nl_feedback: str = "",
    project_dir: str = ".",
) -> str:
    """从持久化 IR 重新生成代码。支持自然语言纠正。

    NL feedback 同时触发两个信道：
    - 信道 2：如果 feedback 中包含 KB 知识，自动更新 KB
    - 信道 3：从持久化 IR 重新生成代码

    Args:
        input_file: 录制文件路径
        nl_feedback: 自然语言纠正（如 "TableAW 的定位器应该用 data-module"）
        project_dir: 项目根目录
    """
    from uibridge.pipeline import Pipeline
    from uibridge.pipeline.ir_persistence import IRPersistence
    from uibridge.kb.manager import KBManager
    from uibridge.kb.audit import AuditLogger
    from uibridge.adapter.loader import load_adapter

    # Channel 2: NL feedback may contain KB knowledge
    kb_updates = None
    if nl_feedback:
        try:
            audit = AuditLogger(project_dir)
            km = KBManager(project_dir, audit_logger=audit)
            kb_result = km.operate_nl(nl_feedback)
            if kb_result.get("status") == "ok" and kb_result.get("intent") in ("MODIFY", "ADD", "PROFILE"):
                kb_updates = kb_result
                logger.info("Auto-updated KB from NL feedback: %s", kb_result.get("message"))
        except Exception:
            logger.warning("Failed to process NL feedback for KB update", exc_info=True)

    ir_persist = IRPersistence(project_dir)
    ir_data = ir_persist.load(input_file)
    if ir_data is None:
        return json.dumps({
            "error": f"No persisted IR found for {input_file}. Run generate_test_code first.",
        }, indent=2, ensure_ascii=False)

    recording, semantic, framework = ir_data

    # Rebuild pipeline with current KB (may have been updated by NL feedback)
    pipeline = _build_pipeline(None, project_dir)

    # Re-run stages 3+4
    call_seq = pipeline.map_to_framework(semantic)
    results = pipeline.generate_and_verify(call_seq, recording)
    pipeline.persist_ir(input_file, recording, semantic, call_seq, results)

    out_dir = _sanitize_output_path("generated")
    out_dir.mkdir(parents=True, exist_ok=True)
    output = []
    for r in results:
        ext = ".java" if getattr(pipeline.code_generator, "target_language", "python") == "java" else ".py"
        test_file = out_dir / f"{r['test_name']}{ext}"
        test_file.write_text(r["code"], encoding="utf-8")
        output.append({
            "test_name": r["test_name"],
            "status": r["verify"].status,
            "review_needed": r.get("review_needed", False),
            "kb_items_updated": r.get("kb_items_updated", 0),
            "file": str(test_file.absolute()),
            "code_preview": r["code"][:500],
        })

    return json.dumps({
        "status": "ok",
        "regenerated": len(output),
        "kb_updates": kb_updates,
        "results": output,
    }, indent=2, ensure_ascii=False)


def main():
    """启动 MCP Server (stdio 传输)"""
    _startup_check()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
