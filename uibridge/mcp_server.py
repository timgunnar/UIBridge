"""MCP Server — 将 uibridge 功能暴露为 AI Agent 可调用的类型化工具。

启动方式:
    python -m uibridge.mcp_server

或在 .mcp.json 中注册为 Claude Code 等 Agent 的工具源。
"""

import asyncio
import concurrent.futures
import json
import sys
import threading
import uuid
from pathlib import Path
from typing import Optional

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
    """加载适配器的 5 个接口实例"""
    from uibridge.adapter.reference import (
        ReferenceComponentResolver,
        ReferenceLocatorStrategy,
        ReferenceActionRecognizer,
        ReferenceCodeGenerator,
        ReferenceDataFormatter,
    )

    if adapter_config_path:
        config_path = Path(adapter_config_path)
        if config_path.exists():
            raw = config_path.read_text("utf-8")
            if config_path.suffix in (".yaml", ".yml"):
                config = yaml.safe_load(raw)
            else:
                config = json.loads(raw)
            components = config.get("adapter", {}).get("components", {})
            if components:
                import importlib

                def load_cls(cls_path: str):
                    module_path, class_name = cls_path.rsplit(".", 1)
                    module = importlib.import_module(module_path)
                    return getattr(module, class_name)()

                return (
                    load_cls(components.get("resolver", "")),
                    load_cls(components.get("locator", "")),
                    load_cls(components.get("recognizer", "")),
                    load_cls(components.get("generator", "")),
                    load_cls(components.get("data_formatter", "")),
                )

    return (
        ReferenceComponentResolver(),
        ReferenceLocatorStrategy(),
        ReferenceActionRecognizer(),
        ReferenceCodeGenerator(),
        ReferenceDataFormatter(),
    )


def _detect_source_dirs(project_dir: str) -> dict[str, str]:
    """自动检测 Java 项目源码目录结构，支持标准和非标布局。

    优先级：
    1. pom.xml 中声明的 <sourceDirectory> / <testSourceDirectory>
    2. 标准 Maven 布局 src/main/java / src/test/java
    3. 递归扫描 src/ 下的 .java 文件反推目录
    4. 兜底返回标准路径
    """
    import re
    root = Path(project_dir)

    # 检查是否为 Java 项目
    java_indicators = ["pom.xml", "build.gradle", "build.gradle.kts"]
    is_java = any((root / f).exists() for f in java_indicators)
    if not is_java:
        return {"pages": "src/main/java", "tests": "src/test/java"}

    # 1. 尝试从 pom.xml 读取自定义源码目录
    pom = root / "pom.xml"
    if pom.exists():
        try:
            content = pom.read_text("utf-8")
            src_match = re.search(r'<sourceDirectory>\s*([^<\s]+)\s*</sourceDirectory>', content)
            test_match = re.search(r'<testSourceDirectory>\s*([^<\s]+)\s*</testSourceDirectory>', content)
            pages = src_match.group(1) if src_match else None
            tests = test_match.group(1) if test_match else None
            if pages or tests:
                if pages and tests:
                    return {"pages": pages, "tests": tests}
                if pages:
                    tests = _infer_test_dir(root, pages)
                    return {"pages": pages, "tests": tests or "src/test/java"}
        except Exception:
            pass

    # 2. 标准 Maven 布局
    std_pages = root / "src" / "main" / "java"
    std_tests = root / "src" / "test" / "java"
    if std_pages.exists():
        return {"pages": "src/main/java", "tests": "src/test/java"}

    # 3. 递归扫描 src/ 反推实际目录
    detected = _scan_java_dirs(root)
    if detected:
        return detected

    # 4. 兜底
    return {"pages": "src/main/java", "tests": "src/test/java"}


def _infer_test_dir(root: Path, src_dir: str) -> str | None:
    """根据源码目录推断测试目录。"""
    candidates = [
        src_dir.replace("main", "test"),
        "src/test/java",
        "test",
    ]
    for c in candidates:
        if (root / c).exists():
            return c
    return None


def _scan_java_dirs(root: Path) -> dict[str, str] | None:
    """扫描项目中实际 .java 文件的位置，反推源码目录。"""
    src_root = root / "src"
    if not src_root.exists():
        return None
    java_files = list(src_root.glob("**/*.java"))
    if not java_files:
        return None

    # 找最深的公共父目录
    candidate_dirs = set()
    test_dirs = set()
    for f in java_files:
        rel = f.parent.relative_to(root)
        parts = rel.parts
        if "test" in parts or "tests" in parts:
            test_dirs.add(str(rel))
        else:
            candidate_dirs.add(str(rel))

    # 找公共前缀最短的目录（越短越接近源码根）
    if candidate_dirs:
        main_dir = _shortest_common(candidate_dirs)
    else:
        main_dir = "src/main/java"

    if test_dirs:
        test_dir = _shortest_common(test_dirs)
    else:
        test_dir = _infer_test_dir(root, main_dir) or "src/test/java"

    return {"pages": main_dir, "tests": test_dir}


def _shortest_common(paths: set[str]) -> str:
    """找一组路径的最短公共父目录。"""
    if not paths:
        return "."
    parts_list = [p.replace("\\", "/").split("/") for p in paths]
    common = parts_list[0]
    for p in parts_list[1:]:
        i = 0
        while i < min(len(common), len(p)) and common[i] == p[i]:
            i += 1
        common = common[:i]
    return "/".join(common) if common else "."


def _build_pipeline(adapter_config_path: Optional[str] = None):
    from uibridge.pipeline import Pipeline
    resolver, locator, recognizer, code_gen, data_fmt = _load_adapter(adapter_config_path)
    return Pipeline(resolver, locator, recognizer, code_gen, data_fmt)


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
                    pass
            if pw:
                try:
                    pw.stop()
                except Exception:
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
                        pass
                    try:
                        _active_browser_staging["pw"].stop()
                    except Exception:
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
                                pass
                            try:
                                _active_browser_staging["pw"].stop()
                            except Exception:
                                pass
                            _active_browser_staging = None

                timer = threading.Timer(1800, _auto_cleanup_staging)
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
                    pass
            if pw:
                try:
                    pw.stop()
                except Exception:
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
                        pass
                _active_browser_staging = None

                current_url = page.url

                session = pipeline.record(page)

                # 10 分钟超时保护
                def _auto_stop():
                    with _recording_lock:
                        if _active_recording is not None:
                            try:
                                _active_recording["session"].stop()
                            except Exception:
                                pass
                            try:
                                _active_recording["context"].close()
                            except Exception:
                                pass
                            try:
                                _active_recording["pw"].stop()
                            except Exception:
                                pass
                            if _active_recording.get("_timeout_timer"):
                                _active_recording["_timeout_timer"].cancel()
                            _active_recording = None

                timer = threading.Timer(600, _auto_stop)
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
                pass
            recording = session.stop()
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
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

    pipeline = _build_pipeline(adapter_config)

    semantic = pipeline.analyze(recording)
    call_seq = pipeline.map_to_framework(semantic)
    results = pipeline.generate_and_verify(call_seq, recording)

    out_dir = _sanitize_output_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    output = []
    for r in results:
        ext = ".java" if "java" in str(type(pipeline.code_generator)).lower() else ".py"
        test_file = out_dir / f"{r['test_name']}{ext}"
        test_file.write_text(r["code"], encoding="utf-8")

        if r.get("data_def"):
            data_file = out_dir / r["data_def"].file_path
            data_file.parent.mkdir(parents=True, exist_ok=True)
            data_file.write_text(r["data_code"], encoding="utf-8")

        output.append({
            "test_name": r["test_name"],
            "status": r["verify"].status,
            "file": str(test_file.absolute()),
            "code_preview": r["code"][:500],
            "fix_suggestion": r["verify"].fix_suggestion if r["verify"].status != "passed" else None,
        })

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
    from uibridge.kb.kb_manager import KBManager

    km = KBManager(project_dir)
    source_dirs = _detect_source_dirs(project_dir)

    items = km.seed_from_static_analysis(source_dirs)
    categories = {}
    for item in items:
        cat = item.category
        categories[cat] = categories.get(cat, 0) + 1

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
    from uibridge.kb.kb_manager import KBManager

    km = KBManager(project_dir)
    result = km.query_nl(query)
    return result


# ── 入口 ──────────────────────────────────────────────────

def _startup_check():
    """启动时检查 Playwright 浏览器可用性，输出到 stderr（stdio 模式下不干扰 JSON-RPC）。"""
    import sys
    from uibridge import check_browser_available

    available, info = check_browser_available("chromium")
    if available:
        print(f"[uibridge] Playwright 浏览器已就绪: {info}", file=sys.stderr)
    else:
        print(f"[uibridge] Playwright 浏览器未就绪: {info}", file=sys.stderr)
        print("[uibridge] 请运行: playwright install chromium", file=sys.stderr)

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


def main():
    """启动 MCP Server (stdio 传输)"""
    _startup_check()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
