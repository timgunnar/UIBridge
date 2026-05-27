"""MCP tools for code generation.

Code generation is being redesigned as KB-driven generation in generator/.
Tools that depend on generator/ return helpful status messages.
list_sessions works independently and is fully functional.
"""
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .server import mcp

_GENERATION_REDESIGN_MSG = (
    "代码生成引擎正在重构中（v0.4.0）。当前可通过 NL 对话维护知识库，"
    "生成功能将在后续版本补全。"
)


@mcp.tool()
async def generate_test_code(
    input_file: str = "recording.json",
    output_dir: str = "generated",
    adapter_config: Optional[str] = None,
) -> str:
    """Generate test code from a recording file (redesigning for v0.4.0)."""
    return json.dumps({
        "status": "unavailable",
        "version": "0.4.0",
        "message": _GENERATION_REDESIGN_MSG,
        "hint": "当前可通过 query_knowledge_base / update_knowledge_base 维护知识库，"
                "或通过 get_profile / get_project_layout 查看项目结构。",
    }, indent=2, ensure_ascii=False)


@mcp.tool()
async def diff_snapshots(
    input_file: str = "recording.json",
    adapter_config: Optional[str] = None,
) -> str:
    """Diff snapshots in a recording (redesigning for v0.4.0)."""
    return json.dumps({
        "status": "unavailable",
        "version": "0.4.0",
        "message": _GENERATION_REDESIGN_MSG,
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
        "message": _GENERATION_REDESIGN_MSG,
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
        "message": _GENERATION_REDESIGN_MSG,
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
        "message": _GENERATION_REDESIGN_MSG,
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
            # Add file list for the session
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
