"""KBEvolution — KB lifecycle evolution: decay, generalize, archive"""

import time
import logging

logger = logging.getLogger(__name__)

from .item import KBItem, KnowledgeSource


class KBEvolution:
    """管理 KB 条目的置信度演化周期：衰减 → 泛化 → 归档。"""

    def __init__(self, store):
        self.store = store

    def evolve(self):
        """运行完整的 KB 演化周期。"""
        self._apply_decay()
        self._generalize_patterns()
        self._archive_low_confidence()

    def _apply_decay(self):
        now = time.time()
        for item in self.store.list_all():
            if item.confidence.decay_rate > 0 and not item.archived:
                score_after = item.confidence.effective_score
                if score_after < item.confidence.score:
                    item.confidence.score = score_after
                    item.confidence.last_validated_at = now
                    self.store.save(item)

    def _generalize_patterns(self):
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
                    for item in group:
                        item.confidence.score = min(1.0, item.confidence.score + 0.05)
                        item.tags.append("generalized")
                        self.store.save(item)

    def _archive_low_confidence(self, threshold: float = 0.2):
        for item in self.store.list_all():
            if (item.confidence.effective_score < threshold
                    and not item.archived
                    and item.confidence.self_test_failures >= 3):
                self.store.archive(item)

    @staticmethod
    def _value_signature(value: dict) -> str:
        return "|".join(sorted(f"{k}:{type(v).__name__}" for k, v in value.items()))
