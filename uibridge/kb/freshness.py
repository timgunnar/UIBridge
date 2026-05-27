"""FreshnessMonitor — component snapshot freshness detection"""

import re
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

from .profile_extractor import ProfileField
from .store import KBStore


class FreshnessMonitor:
    """组件新鲜度监控：对比 KB 快照与源码，检测过时组件。"""

    def __init__(self, kb_store: KBStore, profile_manager=None,
                 project_root: str = "."):
        self.store = kb_store
        self.profile_mgr = profile_manager
        self.project_root = Path(project_root)

    def check_component_freshness(self) -> list[dict]:
        """遍历监控组件，对比快照与源码，返回差异报告。"""
        if not self.profile_mgr:
            return []

        profile = self.profile_mgr.get_profile()
        if profile is None:
            return []

        monitoring = profile.component_monitoring
        if not isinstance(monitoring, ProfileField):
            return []

        config = monitoring.value
        if not isinstance(config, dict) or not config.get("enabled"):
            return []

        components = config.get("components", [])
        if not components:
            return []

        reports = []
        for comp_name in components:
            existing = self.store.load_component_snapshot(comp_name)
            if existing is None:
                reports.append({
                    "component": comp_name, "stale": False,
                    "status": "no_snapshot",
                    "message": f"组件 {comp_name} 无历史快照，跳过检测",
                })
                continue

            current = self._analyze_current_state(comp_name, existing)
            if current is None:
                reports.append({
                    "component": comp_name, "stale": False,
                    "status": "source_not_found",
                    "message": f"组件 {comp_name} 源文件不存在或无法分析",
                })
                continue

            diff = KBStore.compare_snapshot(existing, current)
            diff["component"] = comp_name
            diff["status"] = "checked"
            reports.append(diff)

        return reports

    def _analyze_current_state(self, component_name: str,
                                snapshot: dict) -> dict | None:
        source_file = snapshot.get("source_file", "")
        if not source_file:
            return None

        filepath = self.project_root / source_file
        if not filepath.exists():
            return None

        try:
            content = filepath.read_text("utf-8")
        except Exception:
            logger.warning("Failed to read source file for freshness check: %s", filepath, exc_info=True)
            return None

        methods = []
        locators = {}
        base_class = ""

        if filepath.suffix == ".java":
            methods, locators, base_class = self._parse_java_component(content)
        elif filepath.suffix == ".py":
            methods, locators, base_class = self._parse_python_component(content)
        else:
            return None

        return {
            "component": component_name,
            "source_file": source_file,
            "base_class": base_class,
            "methods": methods,
            "locators": locators,
        }

    @staticmethod
    def _parse_java_component(content: str) -> tuple[list[str], dict, str]:
        methods = []
        locators = {}
        base_class = ""

        m = re.search(r'class\s+\w+\s+extends\s+(\w+)', content)
        if m:
            base_class = m.group(1)

        for m in re.finditer(
            r'(?:public|protected|private)\s+(?:static\s+)?(\w+(?:<[^>]+>)?)\s+(\w+)\s*\(([^)]*)\)',
            content
        ):
            ret_type, name, params = m.group(1), m.group(2), m.group(3).strip()
            methods.append(f"{ret_type} {name}({params})")

        for m in re.finditer(r'@FindBy\s*\(\s*(\w+)\s*=\s*"([^"]+)"', content):
            locators[m.group(1)] = m.group(2)

        for m in re.finditer(r'(?:data-testid|data-test|data-module)\s*[=:]\s*["\']([^"\']+)', content):
            locators.setdefault("data_testid", m.group(1))

        return methods, locators, base_class

    @staticmethod
    def _parse_python_component(content: str) -> tuple[list[str], dict, str]:
        methods = []
        locators = {}
        base_class = ""

        m = re.search(r'class\s+\w+\s*\(([^)]+)\)', content)
        if m:
            bases = [b.strip() for b in m.group(1).split(",")]
            base_class = bases[0] if bases else ""

        for m in re.finditer(r'def\s+(\w+)\s*\(([^)]*)\)', content):
            name, params = m.group(1), m.group(2).strip()
            if not name.startswith("_"):
                methods.append(f"def {name}({params})")

        for m in re.finditer(r'By\.(\w+)\s*,\s*["\']([^"\']+)', content):
            locators[m.group(1)] = m.group(2)

        for m in re.finditer(r'(?:data-testid|data-test)\s*[=:]\s*["\']([^"\']+)', content):
            locators.setdefault("data_testid", m.group(1))

        return methods, locators, base_class
