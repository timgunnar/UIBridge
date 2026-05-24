"""AuditLogger — append-only YAML audit log for KB and profile changes."""
import time
from pathlib import Path
import logging
import yaml

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 2000


class AuditLogger:
    """Writes audit entries to .uibridge/audit.yaml with automatic truncation."""

    def __init__(self, project_root: str = "."):
        self._filepath = Path(project_root) / ".uibridge" / "audit.yaml"
        self._filepath.parent.mkdir(parents=True, exist_ok=True)

    def log(self, action: str, target: str, before: dict, after: dict,
            operator: str = "mcp_tool", source: str = "", note: str = ""):
        entry = {
            "timestamp": time.time(),
            "action": action,
            "target": target,
            "operator": operator,
            "source": source,
            "before": before,
            "after": after,
            "note": note,
        }
        entries = []
        if self._filepath.exists():
            with open(self._filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, list):
                    entries = data
        entries.append(entry)
        if len(entries) > _MAX_ENTRIES:
            entries = entries[-_MAX_ENTRIES:]
        with open(self._filepath, "w", encoding="utf-8") as f:
            yaml.safe_dump(entries, f, allow_unicode=True, sort_keys=False)

    def tail(self, n: int = 20) -> list[dict]:
        if not self._filepath.exists():
            return []
        with open(self._filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if isinstance(data, list):
                return data[-n:]
            return []
