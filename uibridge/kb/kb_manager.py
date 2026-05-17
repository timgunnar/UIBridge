"""KBManager — lifecycle management: seed → query → feedback → evolve"""

import time
from pathlib import Path
from typing import Optional

from .kb_item import KBItem, Confidence, KnowledgeSource
from .kb_store import KBStore
from .kb_extractor import KBExtractor


class KBManager:
    """Manages the full KB lifecycle with confidence scoring and NL interaction."""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.store = KBStore(project_root)
        self.extractor = KBExtractor(project_root)

    # ══════════════════════════════════════════════════════════
    # Seed Phase
    # ══════════════════════════════════════════════════════════

    def seed_from_static_analysis(self, source_dirs: dict[str, str]) -> list[KBItem]:
        """Bulk seed KB from static analysis of source directories.

        source_dirs: {"component_aw": "aaw/", "pages": "pages/", "tests": "tests/"}

        自动检测 Python (.py) 和 Java (.java) 文件并使用对应的提取器。
        """
        seeded = []

        for category, dir_path in source_dirs.items():
            target_dir = self.project_root / dir_path
            if not target_dir.exists():
                continue

            # 优先 Python，其次 Java
            py_files = list(target_dir.glob("**/*.py"))
            java_files = list(target_dir.glob("**/*.java"))

            if py_files:
                for path in py_files:
                    if category == "component_aw":
                        items = self.extractor.extract_from_component_aw(str(path))
                    elif category == "pages":
                        items = self.extractor.extract_from_page_file(str(path))
                    elif category == "tests":
                        items = self.extractor.extract_from_test_script(str(path))
                    else:
                        continue
                    for item in items:
                        self.store.save(item)
                        seeded.append(item)

            if java_files:
                for path in java_files:
                    if category == "tests":
                        items = self.extractor.extract_from_java_test(str(path))
                    else:
                        items = self.extractor.extract_from_java_file(str(path))
                    for item in items:
                        self.store.save(item)
                        seeded.append(item)

        return seeded

    def seed_from_runtime(self, component_type: str, method_traces: list[dict],
                          page_url: str) -> list[KBItem]:
        """Seed from runtime execution traces."""
        items = self.extractor.extract_from_runtime_trace(component_type, method_traces, page_url)
        for item in items:
            existing = self.store.get_by_key(item.category, item.key)
            if existing:
                # Merge: update confidence and add new xpaths
                existing.value.update(item.value)
                existing.confidence.score = max(existing.confidence.score, item.confidence.score)
                existing.confidence.source = item.confidence.source
                existing.version += 1
                self.store.save(existing)
            else:
                self.store.save(item)
        return items

    def seed_from_document(self, text: str, source_name: str = "design_doc") -> list[KBItem]:
        """Seed from NL design document."""
        items = self.extractor.extract_from_design_doc(text, source_name)
        for item in items:
            self.store.save(item)
        return items

    def inject(self, category: str, key: str, value: dict, description: str) -> KBItem:
        """Direct human injection of a KB entry."""
        item = self.extractor.inject_convention(key, value, description)
        item.category = category
        item.id = f"human_{category}_{key.replace('.', '_')}"
        self.store.save(item)
        return item

    # ══════════════════════════════════════════════════════════
    # Query Phase
    # ══════════════════════════════════════════════════════════

    def query(self, query_text: str, min_confidence: float = 0.4) -> list[KBItem]:
        """Search KB with NL text query."""
        results = self.store.search(query_text)
        return [r for r in results if r.confidence.effective_score >= min_confidence]

    def get_component_type(self, aria_role: str, dom_attrs: dict) -> Optional[dict]:
        """Query KB: what component type maps to this ARIA role?"""
        # First try exact match on data-module
        data_module = dom_attrs.get("data-module", "")
        if data_module:
            for item in self.store.list_category("components"):
                patterns = item.value.get("xpath_patterns", [])
                for p in patterns:
                    if data_module in p:
                        return {"type": item.value.get("class_name", "UnknownAW"), "kb_item": item}

        # Then try ARIA role mapping from conventions
        for item in self.store.list_category("conventions"):
            mappings = item.value.get("component_type_mappings", [])
            if isinstance(mappings, list):
                pass  # need structured mapping
            if item.key == "convention.component_types":
                role_map = item.value.get("aria_role_map", {})
                if aria_role in role_map:
                    return {"type": role_map[aria_role], "kb_item": item}

        return None

    def get_locator_conventions(self) -> dict:
        """Query KB: what locator strategies are configured?"""
        for item in self.store.list_category("conventions"):
            if item.key == "convention.locator_priority":
                return item.value
        return {}

    def get_naming_rules(self) -> list[str]:
        """Query KB: what naming conventions exist?"""
        for item in self.store.list_category("conventions"):
            if item.key == "convention.naming":
                return item.value.get("naming_rules", [])
        return []

    def get_pattern(self, pattern_key: str) -> Optional[dict]:
        """Query KB: get a specific pattern."""
        for item in self.store.list_category("patterns"):
            if item.key == pattern_key:
                return item.value
        return None

    # ══════════════════════════════════════════════════════════
    # Feedback Phase
    # ══════════════════════════════════════════════════════════

    def record_self_test_result(self, item_id: str, category: str, passed: bool):
        """Update confidence based on self-test result."""
        item = self.store.get(category, item_id)
        if item:
            if passed:
                item.confidence.record_pass()
            else:
                item.confidence.record_failure()
            self.store.save(item)

    def correct(self, category: str, item_id: str, corrections: dict,
                nl_note: str = "") -> KBItem:
        """Apply human correction to a KB item via NL feedback."""
        item = self.store.get(category, item_id)
        if not item:
            raise KeyError(f"KB item not found: {category}/{item_id}")

        item.value.update(corrections)
        item.confidence.manual_override = corrections.get("confidence_override",
                                                          item.confidence.effective_score)
        item.description = nl_note or item.description
        item.version += 1
        item.tags.append("corrected")
        self.store.save(item)
        return item

    def apply_nl_feedback(self, natural_language_feedback: str) -> list[KBItem]:
        """Apply NL feedback: parse intent and update relevant KB items.

        Examples:
          "TableAW's XPath should use data-module, not class" → update component convention
          "搜索框 should use data-test='search-box'" → update locator priority
        """
        affected = []
        feedback_lower = natural_language_feedback.lower()

        # Match against existing KB items by keyword
        for item in self.store.list_all():
            if any(tag.lower() in feedback_lower for tag in item.tags):
                if "should" in feedback_lower or "must" in feedback_lower:
                    item.confidence.score = max(0.8, item.confidence.score + 0.1)
                    item.confidence.source = KnowledgeSource.HUMAN_INJECTION
                    item.tags.append("nl-corrected")
                    item.version += 1
                    self.store.save(item)
                    affected.append(item)

        return affected

    # ══════════════════════════════════════════════════════════
    # Evolve Phase
    # ══════════════════════════════════════════════════════════

    def evolve(self):
        """Run KB evolution cycle: decay, generalize, archive."""
        self._apply_decay()
        self._generalize_patterns()
        self._archive_low_confidence()

    def _apply_decay(self):
        """Apply confidence decay to items not recently validated."""
        for item in self.store.list_all():
            if item.confidence.decay_rate > 0 and not item.archived:
                # Force re-read of effective_score (which applies decay)
                score_before = item.confidence.score
                score_after = item.confidence.effective_score
                if score_after < score_before:
                    item.confidence.score = score_after
                    self.store.save(item)

    def _generalize_patterns(self):
        """Generalize: if 3+ items share the same value pattern, create a convention."""
        categories = [("components", "component_type"),
                       ("pages", "page_structure"),
                       ("patterns", "business_pattern")]

        for category, key_prefix in categories:
            items = self.store.list_category(category)
            value_signatures = {}
            for item in items:
                sig = self._value_signature(item.value)
                value_signatures.setdefault(sig, []).append(item)

            for sig, group in value_signatures.items():
                if len(group) >= 3:
                    # Pattern confirmed by 3+ items — boost confidence
                    for item in group:
                        item.confidence.score = min(1.0, item.confidence.score + 0.05)
                        item.tags.append("generalized")
                        self.store.save(item)

    def _archive_low_confidence(self, threshold: float = 0.2):
        """Archive items with sustained low confidence."""
        for item in self.store.list_all():
            if (item.confidence.effective_score < threshold
                    and not item.archived
                    and item.confidence.self_test_failures >= 3):
                self.store.archive(item)

    def _value_signature(self, value: dict) -> str:
        """Create a structural signature of a value dict for pattern detection."""
        return "|".join(sorted(f"{k}:{type(v).__name__}" for k, v in value.items()))

    # ══════════════════════════════════════════════════════════
    # NL Interaction
    # ══════════════════════════════════════════════════════════

    def query_nl(self, question: str) -> str:
        """Answer a NL question about the KB. Returns a text summary."""
        results = self.query(question, min_confidence=0.3)
        if not results:
            return f"No KB entries found matching: '{question}'"

        lines = [f"Found {len(results)} relevant KB entries for: '{question}'\n"]
        for item in results[:5]:
            conf = item.confidence.effective_score
            lines.append(
                f"- [{item.category}] {item.key}: {item.description} "
                f"(confidence: {conf:.2f})"
            )
        return "\n".join(lines)

    def summarize_kb(self) -> str:
        """Generate a full NL summary of the KB."""
        return self.store.summarize()

    def get_high_confidence_knowledge(self) -> dict[str, dict]:
        """Return all high-confidence knowledge as a structured dict, keyed by category."""
        result = {}
        for item in self.store.get_high_confidence(0.7):
            result.setdefault(item.category, {})[item.key] = item.value
        return result
