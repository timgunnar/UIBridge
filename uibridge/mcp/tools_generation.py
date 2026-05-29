"""MCP tools for code generation.

generate_test_code provides minimal test code generation from recording files.
list_sessions works independently and is fully functional.
"""
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .server import mcp


@mcp.tool()
async def generate_test_code(
    input_file: str = "recording.json",
    output_dir: str = "generated",
    adapter_config: Optional[str] = None,
) -> str:
    """Generate test code and component AW from a recording file.

    Loads a recording JSON, extracts component definitions and test steps,
    then generates Python test script and component AW code.
    """
    recording_path = Path(input_file)
    if not recording_path.exists():
        sessions_dir = Path(".uibridge") / "sessions"
        if sessions_dir.exists():
            for d in sorted(sessions_dir.iterdir(), reverse=True):
                candidate = (
                    d / input_file
                    if input_file != "recording.json"
                    else d / "raw_recording.json"
                )
                if candidate.exists():
                    recording_path = candidate
                    break

    if not recording_path.exists():
        return json.dumps({
            "status": "error",
            "message": f"录制文件未找到: {input_file}",
            "hint": (
                "请先通过浏览器录制生成 recording.json，"
                "或指定 --input-file 路径"
            ),
        }, indent=2, ensure_ascii=False)

    try:
        with open(recording_path, "r", encoding="utf-8") as f:
            recording = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return json.dumps({
            "status": "error",
            "message": f"无法解析录制文件: {e}",
        }, indent=2, ensure_ascii=False)

    components = _extract_components(recording)
    steps = _extract_steps(recording)

    if not components and not steps:
        return json.dumps({
            "status": "empty",
            "message": "录制文件未包含可识别的组件或步骤",
            "file": str(recording_path),
        }, indent=2, ensure_ascii=False)

    from uibridge.generator.engine import CodeGenerator
    from uibridge.generator.component_aw_gen import ComponentDef, MethodTemplate
    from uibridge.generator.test_script_gen import ScriptDef

    code_gen = CodeGenerator(".")

    generated = {}
    for comp in components:
        comp_def = ComponentDef(
            class_name=comp.get("class_name", "GeneratedAW"),
            module=comp.get("module", ""),
            xpath=comp.get("xpath", "//*"),
            methods=[
                MethodTemplate(
                    name=m.get("name", "action"),
                    params=m.get("params", []),
                    action_type=m.get("action_type", "click"),
                )
                for m in comp.get("methods", [])
            ],
        )
        generated[f"component_{comp_def.class_name}"] = (
            code_gen.generate_component_aw(comp_def)
        )

    if steps:
        test_name = recording.get("name") or recording_path.stem
        script_def = ScriptDef(
            class_name=_to_class_name(test_name),
            test_name=test_name,
            description=recording.get("description", ""),
            imports=["import pytest"],
            fixtures=[],
            steps=steps,
        )
        generated["test_script"] = code_gen.generate_test_script(script_def)

    return json.dumps({
        "status": "ok",
        "file": str(recording_path),
        "components_count": len(components),
        "steps_count": len(steps),
        "generated": generated,
    }, indent=2, ensure_ascii=False)


def _extract_components(recording: dict) -> list[dict]:
    """Extract component definitions from recording events."""
    components = []
    for event in recording.get("events", []):
        meta = event.get("component_meta") or event.get("component")
        if meta and isinstance(meta, dict):
            comp_name = meta.get("type") or meta.get("class_name") or "ComponentAW"
            method_name = _event_to_method(event)
            if comp_name and method_name:
                existing = next(
                    (c for c in components if c.get("class_name") == comp_name),
                    None,
                )
                if existing:
                    names = [m["name"] for m in existing["methods"]]
                    if method_name not in names:
                        existing["methods"].append({
                            "name": method_name,
                            "params": [],
                            "action_type": event.get("action", "click"),
                        })
                else:
                    components.append({
                        "class_name": comp_name,
                        "xpath": meta.get("xpath", "//*"),
                        "module": f"aaw.{comp_name.lower()}",
                        "methods": [{
                            "name": method_name,
                            "params": [],
                            "action_type": event.get("action", "click"),
                        }],
                    })
    return components


def _extract_steps(recording: dict) -> list[str]:
    """Extract test step descriptions from recording events."""
    steps = []
    for event in recording.get("events", []):
        action = event.get("action", "")
        desc = event.get("description") or event.get("selector") or ""
        if action == "navigate":
            steps.append(f"# 导航到: {event.get('url', '')}")
        elif desc:
            steps.append(f"# {action}: {desc}")
        else:
            steps.append(f"# {action}")
    return steps


def _event_to_method(event: dict) -> str:
    """Convert a recording event to a method name."""
    action = event.get("action", "")
    target = event.get("selector") or event.get("text") or ""
    clean = "".join(c for c in target if c.isalnum() or c == "_")[:30]
    if action == "click":
        return f"click_{clean}" if clean else "click"
    if action in ("fill", "type", "input"):
        return f"enter_{clean}" if clean else "enter"
    if action == "navigate":
        return "navigate"
    return f"do_{action}" if action else "action"


def _to_class_name(name: str) -> str:
    """Convert a test name to a class name."""
    import re
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    parts = [w.capitalize() for w in name.split("_") if w]
    return "".join(parts) or "GeneratedTest"


@mcp.tool()
async def diff_snapshots(
    input_file: str = "recording.json",
    adapter_config: Optional[str] = None,
) -> str:
    """Diff snapshots in a recording (redesigning for v0.4.0)."""
    return json.dumps({
        "status": "unavailable",
        "version": "0.4.0",
        "message": "代码生成引擎正在重构中（v0.4.0）。当前可通过 NL 对话维护知识库，生成功能将在后续版本补全。",
        "hint": "快照比对功能将在生成引擎重构完成后恢复。",
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def review_generated_code(
    input_file: str = "recording.json",
    project_dir: str = ".",
) -> str:
    """Review generated code (redesigning for v0.4.0)."""
    return json.dumps({
        "status": "unavailable",
        "version": "0.4.0",
        "message": "代码生成引擎正在重构中（v0.4.0）。当前可通过 NL 对话维护知识库，生成功能将在后续版本补全。",
        "hint": "代码审查功能将在生成引擎重构完成后恢复。",
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def regenerate_code(
    input_file: str = "recording.json",
    nl_feedback: str = "",
    project_dir: str = ".",
) -> str:
    """Regenerate code from persisted IR (redesigning for v0.4.0)."""
    return json.dumps({
        "status": "unavailable",
        "version": "0.4.0",
        "message": "代码生成引擎正在重构中（v0.4.0）。当前可通过 NL 对话维护知识库，生成功能将在后续版本补全。",
        "hint": "重新生成功能将在生成引擎重构完成后恢复。",
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def regenerate_from_session(
    session_name: str,
    project_dir: str = ".",
) -> str:
    """Regenerate from a persisted session (redesigning for v0.4.0)."""
    return json.dumps({
        "status": "unavailable",
        "version": "0.4.0",
        "message": "代码生成引擎正在重构中（v0.4.0）。当前可通过 NL 对话维护知识库，生成功能将在后续版本补全。",
        "hint": "会话重新生成功能将在生成引擎重构完成后恢复。",
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def list_sessions(project_dir: str = ".") -> str:
    """List persisted recording sessions under .uibridge/sessions/."""
    sessions_dir = Path(project_dir) / ".uibridge" / "sessions"
    if not sessions_dir.exists():
        return json.dumps({"sessions": [], "count": 0}, indent=2, ensure_ascii=False)

    sessions = []
    for d in sorted(sessions_dir.iterdir(), reverse=True):
        if d.is_dir():
            session_info = {
                "name": d.name,
                "has_recording": (d / "raw_recording.json").exists(),
            }
            try:
                files = [f.name for f in d.iterdir() if f.is_file()]
                session_info["files"] = sorted(files)
            except Exception:
                pass
            sessions.append(session_info)

    return json.dumps({
        "sessions": sessions,
        "count": len(sessions),
    }, indent=2, ensure_ascii=False)
