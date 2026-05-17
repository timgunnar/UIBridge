"""MCP Server — 将 uibridge 功能暴露为 AI Agent 可调用的类型化工具。

启动方式:
    python -m uibridge.mcp_server

或在 .mcp.json 中注册为 Claude Code 等 Agent 的工具源。
"""

import json
import threading
from pathlib import Path
from typing import Optional

import yaml
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "uibridge",
    instructions="UI 自动化测试脚本智能生成系统 — 录制浏览器操作 → 自动生成测试代码",
)

# ── 模块级录制状态（跨 MCP 工具调用保持）──────────
_active_recording: dict | None = None
_recording_lock = threading.Lock()


# ── 辅助函数 ──────────────────────────────────────────────

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
    """自动检测项目类型并返回对应的源码目录映射。

    支持 Python（pyproject.toml / setup.py）、Java Maven（pom.xml）、
    Java Gradle（build.gradle）。"""
    root = Path(project_dir)

    # Python 项目检测
    py_indicators = ["pyproject.toml", "setup.py", "setup.cfg"]
    is_python = any((root / f).exists() for f in py_indicators)

    # Java 项目检测
    java_indicators = ["pom.xml", "build.gradle", "build.gradle.kts"]
    is_java = any((root / f).exists() for f in java_indicators)

    if is_python or (not is_java and _has_python_src(root)):
        return {
            "component_aw": "aaw",
            "pages": "pages",
            "tests": "tests",
        }

    if is_java:
        # Maven 标准布局
        if (root / "src" / "main" / "java").exists():
            return {
                "pages": "src/main/java",
                "tests": "src/test/java",
            }
        # Gradle / 其他 Java 布局
        return {
            "pages": "src/main/java",
            "tests": "src/test/java",
        }

    # Fallback：扫描常见目录
    result = {}
    for key, candidate in [("component_aw", "aaw"), ("pages", "pages"), ("tests", "tests")]:
        if (root / candidate).exists():
            result[key] = candidate
    if not result:
        result = {"pages": "src/main/java", "tests": "src/test/java"}
    return result


def _has_python_src(root: Path) -> bool:
    """检查目录树中是否有 Python 源码（用于无 pyproject.toml 的项目）。"""
    for pattern in ["**/*.py", "aaw/**/*.py", "pages/**/*.py", "tests/**/*.py"]:
        if list(root.glob(pattern)):
            return True
    return False


def _build_pipeline(adapter_config_path: Optional[str] = None):
    from uibridge.pipeline import Pipeline
    resolver, locator, recognizer, code_gen, data_fmt = _load_adapter(adapter_config_path)
    return Pipeline(resolver, locator, recognizer, code_gen, data_fmt)


# ── MCP Tools ─────────────────────────────────────────────

@mcp.tool()
def analyze_page(
    url: str,
    adapter_config: Optional[str] = None,
) -> str:
    """分析一个页面，发现其中的 UI 组件（表格、输入框、按钮等）并输出注册表。

    用于：在录制或生成测试之前，了解页面有哪些组件、它们叫什么、怎么定位。
    返回：JSON 格式的组件列表，每个组件包含 type/name/xpath/aria_role。
    """
    from playwright.sync_api import sync_playwright

    resolver, locator, recognizer, code_gen, data_fmt = _load_adapter(adapter_config)
    pipeline = _build_pipeline(adapter_config)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")

        components = pipeline.discover_components(page)
        browser.close()

    return json.dumps(components, indent=2, ensure_ascii=False)


@mcp.tool()
def start_recording(
    url: str = "about:blank",
    adapter_config: Optional[str] = None,
) -> str:
    """启动交互式浏览器录制。打开可见浏览器窗口，注入事件监听，开始捕获用户操作。

    用于：用户想录制某个功能的操作流程时，作为第一步调用。
    调用后浏览器打开，用户在浏览器中操作页面。操作完成后，Agent 调用 stop_recording()
    结束录制并保存文件。

    这是录制两步曲的第一步，与 stop_recording 配对使用。
    支持同时只有一个活跃录制会话（重复调用会替换旧会话）。

    参数：
    - url: 起始页面 URL
    返回：会话状态 JSON，含 session_id 和 url。
    """
    global _active_recording
    from playwright.sync_api import sync_playwright

    resolver, locator, recognizer, code_gen, data_fmt = _load_adapter(adapter_config)
    pipeline = _build_pipeline(adapter_config)

    with _recording_lock:
        # 如果已有活跃会话，先清理
        if _active_recording:
            try:
                _active_recording["browser"].close()
            except Exception:
                pass
            try:
                _active_recording["pw"].stop()
            except Exception:
                pass
            if _active_recording.get("_timeout_timer"):
                _active_recording["_timeout_timer"].cancel()

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.goto(url)

        session = pipeline.record(page)

        # 10 分钟超时保护：如果用户忘记停止录制，自动清理
        _this_session = None

        def _auto_stop():
            with _recording_lock:
                nonlocal _this_session
                if _active_recording is not None and _active_recording.get("session") is _this_session:
                    try:
                        _active_recording["session"].stop()
                    except Exception:
                        pass
                    try:
                        _active_recording["browser"].close()
                    except Exception:
                        pass
                    try:
                        _active_recording["pw"].stop()
                    except Exception:
                        pass
                    _active_recording = None

        timer = threading.Timer(600, _auto_stop)
        timer.daemon = True
        timer.start()

        _active_recording = {
            "session": session,
            "page": page,
            "browser": browser,
            "pw": pw,
            "_timeout_timer": timer,
        }
        _this_session = session

    return json.dumps({
        "status": "recording",
        "session_id": "active",
        "url": url,
        "hint": "用户在浏览器中操作。完成后 Agent 调用 stop_recording。",
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def stop_recording(
    output_file: str = "recording.json",
) -> str:
    """停止当前活跃的录制会话，保存录制文件，关闭浏览器。

    用于：录制两步曲的第二步。用户在浏览器中完成操作后，Agent 调用此工具
    结束录制。录制数据保存到 JSON 文件，浏览器窗口关闭。

    参数：
    - output_file: 录制输出文件路径，默认 recording.json
    返回：录制结果摘要（步骤数、文件路径、每步简要描述）。
    """
    global _active_recording

    with _recording_lock:
        if not _active_recording:
            return json.dumps({
                "error": "没有活跃的录制会话。请先调用 start_recording。",
            }, indent=2, ensure_ascii=False)

        session = _active_recording["session"]
        browser = _active_recording["browser"]
        pw = _active_recording["pw"]

        recording = session.stop()

        output_path = Path(output_file)
        output_path.write_text(
            json.dumps(recording.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        browser.close()
        pw.stop()
        _active_recording = None

    return json.dumps({
        "status": "ok",
        "steps": len(recording.steps),
        "file": str(output_path.absolute()),
        "summary": [f"{s.action.value}: {s.target.label or s.target.url or ''}" for s in recording.steps],
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def record_browser_operations(
    url: str = "about:blank",
    output_file: str = "recording.json",
    adapter_config: Optional[str] = None,
) -> str:
    """[CLI 用] 一次性录制：打开浏览器 → 等待用户按 Enter → 停止录制。

    对于 MCP/Agent 场景，推荐使用 start_recording + stop_recording 两步工具，
    这样可以支持用户在浏览器操作后通过对话告知 Agent 完成。

    参数：
    - url: 起始页面 URL
    - output_file: 录制输出文件路径，默认 recording.json
    返回：录制结果摘要。
    """
    global _active_recording

    # 使用交互式两步工具完成录制（阻塞等待 stdin）
    start_result = json.loads(start_recording(url=url, adapter_config=adapter_config))
    if start_result.get("status") != "recording":
        return json.dumps({"error": "启动录制失败", "detail": start_result})

    try:
        input("\n[uibridge] 浏览器已打开。请在浏览器中操作，完成后按 Enter 结束录制...\n")
    except (EOFError, OSError):
        # stdin 不可用（MCP 场景），返回提示让 Agent 用两步工具
        stop_recording(output_file=output_file)
        return json.dumps({
            "error": "此工具在 MCP 模式下不可用。请使用 start_recording + stop_recording 两步工具。",
            "hint": "录制会话已自动停止。",
        })

    return stop_recording(output_file=output_file)


@mcp.tool()
def generate_test_code(
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

    data = json.loads(Path(input_file).read_text("utf-8"))
    recording = RawRecording.from_dict(data)

    pipeline = _build_pipeline(adapter_config)

    semantic = pipeline.analyze(recording)
    call_seq = pipeline.map_to_framework(semantic)
    results = pipeline.generate_and_verify(call_seq, recording)

    out_dir = Path(output_dir)
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
def diff_snapshots(
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

    data = json.loads(Path(input_file).read_text("utf-8"))
    recording = RawRecording.from_dict(data)

    pipeline = _build_pipeline(adapter_config)
    candidates = pipeline.diff_snapshots(recording)

    return json.dumps({
        "count": len(candidates),
        "candidates": candidates,
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def seed_knowledge_base(
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
def query_knowledge_base(
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

def main():
    """启动 MCP Server (stdio 传输)"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
