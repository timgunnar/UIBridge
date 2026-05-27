"""CrossValidator — multi-source evidence merging and confidence re-evaluation.

Three-source validation: code inference x browser observation x user input.
"""

import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

from .store import KBStore
from .item import KBItem, Confidence, KnowledgeSource


# Source weights for confidence calculation
_SOURCE_WEIGHTS: dict[KnowledgeSource, float] = {
    KnowledgeSource.HUMAN_INJECTION:   0.95,
    KnowledgeSource.RUNTIME_ANALYSIS:  0.80,
    KnowledgeSource.STATIC_ANALYSIS:   0.65,
    KnowledgeSource.PATTERN_MINING:    0.50,
    KnowledgeSource.LLM_INFERENCE:     0.40,
}

# Evidence store keyed by item_id -> list of evidence records
_EVIDENCE_STORE: dict[str, list[dict]] = {}


class CrossValidator:
    """Merge evidence from multiple sources and adjust confidence.

    Confidence is not a single number — it's derived from all available
    evidence. Each piece of evidence contributes a weighted score,
    and the combined confidence is a weighted average of contributing sources,
    capped at 0.99.
    """

    def __init__(self, store: KBStore):
        self.store = store
        _EVIDENCE_STORE.clear()  # Fresh state per validator instance

    # ── Validation ─────────────────────────────────────────────

    def validate(self, item_id: str) -> float:
        """Re-evaluate confidence based on all available evidence.

        Looks up the KBItem in the store and combines evidence records
        with the item's intrinsic confidence.

        Returns:
            Confidence score in [0.0, 1.0]. Returns 0.0 if item not found.
        """
        item = self._find_item(item_id)
        if item is None:
            return 0.0

        evidence_list = _EVIDENCE_STORE.get(item_id, [])

        if not evidence_list:
            return item.confidence.effective_score

        return self._compute_combined_confidence(item, evidence_list)

    def merge_evidence(self, item_id: str, source: KnowledgeSource,
                       evidence_score: float, evidence_detail: str = ""):
        """Add evidence from a source and recalculate confidence.

        Args:
            item_id: Target KBItem ID.
            source: Which KnowledgeSource provided this evidence.
            evidence_score: How strong the evidence is [0.0, 1.0].
            evidence_detail: Optional description of the evidence.
        """
        item = self._find_item(item_id)
        if item is None:
            logger.warning("merge_evidence: item %s not found", item_id)
            return

        evidence_list = _EVIDENCE_STORE.setdefault(item_id, [])
        evidence_list.append({
            "source": source,
            "score": max(0.0, min(1.0, evidence_score)),
            "detail": evidence_detail,
            "timestamp": time.time(),
        })

        # Update the stored item's confidence
        new_score = self._compute_combined_confidence(item, evidence_list)
        item.confidence.score = new_score
        item.confidence.last_validated_at = time.time()
        self.store.save(item)

    def resolve_conflict(self, item1_id: str, item2_id: str) -> str:
        """When two items conflict, determine which has stronger evidence.

        Resolution strategy (in order):
          1. More evidence sources → wins
          2. Higher effective confidence → wins
          3. Human injection evidence present → wins
          4. Default to first item

        Returns:
            The ID of the item with stronger evidence.
        """
        conf1 = self.validate(item1_id)
        conf2 = self.validate(item2_id)

        ev1 = _EVIDENCE_STORE.get(item1_id, [])
        ev2 = _EVIDENCE_STORE.get(item2_id, [])

        # More evidence sources
        src1 = len(set(e["source"] for e in ev1))
        src2 = len(set(e["source"] for e in ev2))
        if src1 != src2:
            return item1_id if src1 > src2 else item2_id

        # Higher confidence
        if abs(conf1 - conf2) > 0.01:
            return item1_id if conf1 > conf2 else item2_id

        # Human injection trumps
        has_human1 = any(e["source"] == KnowledgeSource.HUMAN_INJECTION for e in ev1)
        has_human2 = any(e["source"] == KnowledgeSource.HUMAN_INJECTION for e in ev2)
        if has_human1 != has_human2:
            return item1_id if has_human1 else item2_id

        # Default: first item
        return item1_id

    # ── Bulk operations ────────────────────────────────────────

    def validate_all(self) -> dict[str, float]:
        """Re-evaluate confidence for all items in the store.

        Returns:
            Dict mapping item_id → new confidence score.
        """
        results = {}
        for item in self.store.list_all():
            results[item.id] = self.validate(item.id)
        return results

    # ── Helpers ────────────────────────────────────────────────

    def _find_item(self, item_id: str) -> Optional[KBItem]:
        """Find a KBItem by ID across all categories."""
        from .store import CATEGORIES
        for cat in CATEGORIES:
            item = self.store.get(cat, item_id)
            if item is not None:
                return item
        return None

    @staticmethod
    def _compute_combined_confidence(item: KBItem,
                                     evidence_list: list[dict]) -> float:
        """Compute a weighted confidence from item baseline + evidence.

        Formula: weighted average of (source_weight * evidence_score) for each
        evidence record, combined with the item's own confidence source weight.
        """
        if not evidence_list:
            return item.confidence.effective_score

        # Collect contributions from each piece of evidence
        contributions = []
        weights = []

        for ev in evidence_list:
            src = ev["source"]
            w = _SOURCE_WEIGHTS.get(src, 0.3)
            contributions.append(w * ev["score"])
            weights.append(w)

        # Also include the item's own confidence as a base source
        item_src_w = _SOURCE_WEIGHTS.get(item.confidence.source, 0.4)
        contributions.append(item_src_w * item.confidence.score)
        weights.append(item_src_w)

        if not weights:
            return item.confidence.effective_score

        combined = sum(contributions) / sum(weights)
        # Apply evidence count bonus: more evidence = slightly higher confidence
        bonus = min(0.1, len(evidence_list) * 0.02)
        return min(0.99, combined + bonus)
