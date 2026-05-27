"""MCP tools for profile management.

Profile tools use KBManager to read/write profile data stored as KB convention items.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from .server import mcp


def _detect_project_type(project_path: Path) -> str:
    """Detect project type from build files."""
    if (project_path / "pom.xml").exists():
        return "java_maven"
    for gf in ["build.gradle", "build.gradle.kts"]:
        if (project_path / gf).exists():
            return "java_gradle"
    if (project_path / "pyproject.toml").exists() or (project_path / "setup.py").exists():
        return "python_pytest"
    return "unknown"


def _count_source_files(project_path: Path) -> dict:
    """Count source files by extension, limited to common source dirs."""
    counts = {}
    for ext in ["py", "java", "js", "ts", "yaml", "yml", "json"]:
        try:
            count = len(list(project_path.glob(f"**/*.{ext}")))
            if count > 0:
                counts[f".{ext}"] = count
        except Exception:
            pass
    return counts


def _get_kb_profile_fields(project_dir: str) -> dict:
    """Extract profile-relevant data from existing KB convention items."""
    try:
        from uibridge.kb.manager import KBManager
        km = KBManager(project_dir)
        fields = {}

        # locator_priorities
        loc_item = km.store.get_by_key("conventions", "convention.locator_priority")
        if loc_item:
            fields["locator_priorities"] = loc_item.value

        # naming conventions
        naming_item = km.store.get_by_key("conventions", "convention.naming")
        if naming_item:
            fields["naming_conventions"] = naming_item.value

        # component types
        comp_item = km.store.get_by_key("conventions", "convention.component_types")
        if comp_item:
            fields["component_types"] = comp_item.value

        # profile fields stored by update_profile
        for conv in km.store.list_category("conventions"):
            if conv.key.startswith("profile."):
                field_name = conv.key[len("profile."):]
                fields[field_name] = conv.value

        return fields
    except Exception:
        logger.warning("Failed to read KB profile fields", exc_info=True)
        return {}


@mcp.tool()
async def get_profile(project_dir: str = ".") -> str:
    """Get current project profile including project type, file counts, and KB-derived settings.

    Returns project_type, locator_priorities, base_classes, source_file_counts,
    and any profile fields stored in KB.
    """
    project_path = Path(project_dir).resolve()
    if not project_path.exists():
        return json.dumps({
            "status": "error",
            "message": f"Project directory not found: {project_path}",
        }, indent=2, ensure_ascii=False)

    # Detect project type and file counts
    project_type = _detect_project_type(project_path)
    file_counts = _count_source_files(project_path)

    # Get KB profile fields
    kb_fields = _get_kb_profile_fields(str(project_path))

    # Build profile response
    profile = {
        "status": "ok",
        "project_dir": str(project_path),
        "project_type": project_type,
        "source_file_counts": file_counts,
        "total_source_files": sum(file_counts.values()),
        "locator_priorities": kb_fields.get("locator_priorities", []),
        "naming_conventions": kb_fields.get("naming_conventions", {}),
        "component_types": kb_fields.get("component_types", {}),
        "base_classes": kb_fields.get("base_classes", {}),
        "source_dirs": kb_fields.get("source_dirs", {}),
        "custom_fields": {
            k: v for k, v in kb_fields.items()
            if k not in ("locator_priorities", "naming_conventions",
                         "component_types", "base_classes", "source_dirs")
        },
    }

    return json.dumps(profile, indent=2, ensure_ascii=False, default=str)


@mcp.tool()
async def update_profile(field: str, value_json: str, project_dir: str = ".") -> str:
    """Update a profile field. Stores the value as a KB convention item (profile.{field}).

    Args:
        field: Field name to update (e.g. "locator_priorities", "base_classes", "source_dirs")
        value_json: JSON-encoded value to store
        project_dir: Project root directory

    Returns:
        JSON with status and updated field info.
    """
    project_path = Path(project_dir).resolve()
    if not project_path.exists():
        return json.dumps({
            "status": "error",
            "message": f"Project directory not found: {project_path}",
        }, indent=2, ensure_ascii=False)

    # Parse value_json
    try:
        value = json.loads(value_json)
    except json.JSONDecodeError as e:
        return json.dumps({
            "status": "error",
            "message": f"Invalid value_json: {e}",
        }, indent=2, ensure_ascii=False)

    try:
        from uibridge.kb.manager import KBManager
        from uibridge.kb.item import KnowledgeSource
        from uibridge.kb.audit import AuditLogger

        audit = AuditLogger(str(project_path))
        km = KBManager(str(project_path), audit_logger=audit)

        profile_key = f"profile.{field}"

        # Check if profile field already exists
        existing = km.store.get_by_key("conventions", profile_key)
        before = existing.value.copy() if existing else None

        if existing:
            # Update existing
            existing.value = value
            existing.confidence.source = KnowledgeSource.HUMAN_INJECTION
            existing.confidence.score = max(0.9, existing.confidence.score)
            existing.version += 1
            km.store.save(existing)
        else:
            # Create new
            item = km.inject(
                category="conventions",
                key=profile_key,
                value=value,
                description=f"Profile field: {field}",
            )
            item.confidence.source = KnowledgeSource.HUMAN_INJECTION
            km.store.save(item)
            existing = item

        return json.dumps({
            "status": "ok",
            "field": field,
            "previous_value": before,
            "current_value": value,
            "message": f"Updated profile field '{field}'",
        }, indent=2, ensure_ascii=False, default=str)

    except Exception as e:
        logger.warning("Failed to update profile field", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": f"Failed to update profile: {e}",
        }, indent=2, ensure_ascii=False)


@mcp.tool()
async def get_project_layout(project_dir: str = ".") -> str:
    """Scan project layout: directory structure, build system, and source file distribution.

    Returns a summary of the project structure including top-level directories,
    build system, and source file counts by extension.
    """
    project_path = Path(project_dir).resolve()
    if not project_path.exists():
        return json.dumps({
            "status": "error",
            "message": f"Project directory not found: {project_path}",
        }, indent=2, ensure_ascii=False)

    # Top-level entries (excluding hidden and common non-source dirs)
    skip_dirs = {".git", ".uibridge", "__pycache__", "node_modules", ".venv",
                 "venv", ".idea", ".vscode", "target", "build", "dist",
                 ".pytest_cache", ".tox", ".mypy_cache"}
    top_entries = []
    try:
        for entry in sorted(project_path.iterdir()):
            if entry.name.startswith(".") and entry.name not in (".gitignore",):
                continue
            if entry.name in skip_dirs:
                continue
            top_entries.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
            })
    except PermissionError:
        pass

    # Source file counts by extension
    file_counts = _count_source_files(project_path)

    # Detect build system
    build_files = []
    for bf in ["pom.xml", "build.gradle", "build.gradle.kts", "pyproject.toml",
               "setup.py", "setup.cfg", "package.json", "Makefile", "CMakeLists.txt"]:
        if (project_path / bf).exists():
            build_files.append(bf)

    project_type = _detect_project_type(project_path)

    # Key source directories (common patterns)
    source_dirs = {}
    for sd in ["src", "tests", "test", "aaw", "pages", "components",
               "uibridge", "lib", "app"]:
        dir_path = project_path / sd
        if dir_path.is_dir():
            source_dirs[sd] = sum(1 for _ in dir_path.glob("**/*"))

    layout = {
        "status": "ok",
        "project_dir": str(project_path),
        "project_type": project_type,
        "build_files": build_files,
        "top_level_entries": top_entries,
        "source_file_counts": file_counts,
        "total_source_files": sum(file_counts.values()),
        "key_directories": source_dirs,
    }

    return json.dumps(layout, indent=2, ensure_ascii=False)
