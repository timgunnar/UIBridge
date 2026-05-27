"""Dialogue manager — decide when and how to ask the user questions.

Policy: ask only when critical.  Stay silent otherwise.  This module does not
make any API/LLM calls — all decisions are rule-based.
"""

from typing import Optional


class DialogueManager:
    """Manage when to ask the user questions vs. stay silent.

    Three conditions must ALL be true to initiate dialogue:
    1. Two or more mutually exclusive findings with confidence < 0.4
    2. The ambiguity affects code generation correctness
    3. Silent verification (browser) can't resolve in 1-2 operations

    Otherwise, we stay silent.
    """

    # Confidence threshold: findings below this are considered "low confidence"
    LOW_CONFIDENCE = 0.4

    # Minimum number of conflicting findings to trigger a question
    MIN_CONFLICT_COUNT = 2

    # Categories where ambiguity directly impacts code correctness
    CRITICAL_CATEGORIES = frozenset({
        "naming_convention",
        "locator_strategy",
        "component",
        "locator",
        "convention",
    })

    def __init__(self):
        pass

    # ── public API ──────────────────────────────────────────────────

    def should_ask(self, conflicts: list[dict]) -> bool:
        """Check if we should ask the user about the given conflicts.

        Args:
            conflicts: List of conflict dicts, each with at least:
                - "findings": list of dicts with "confidence" and "category"

        Returns:
            True if we should initiate a dialogue question.
        """
        if not conflicts:
            return False

        # Must have at least MIN_CONFLICT_COUNT conflicting findings
        all_findings = []
        for c in conflicts:
            findings = c.get("findings", [c]) if isinstance(c, dict) else []
            all_findings.extend(findings)

        if len(all_findings) < self.MIN_CONFLICT_COUNT:
            return False

        # Check condition 1: two+ mutually exclusive findings with low confidence
        low_conf_count = sum(
            1 for f in all_findings
            if f.get("confidence", 0) < self.LOW_CONFIDENCE
        )
        if low_conf_count < self.MIN_CONFLICT_COUNT:
            return False

        # Check condition 2: ambiguity affects code generation correctness
        if not self._affects_correctness(all_findings):
            return False

        # Check condition 3: can't be resolved silently in 1-2 browser ops
        if self._resolvable_silently(all_findings):
            return False

        return True

    def format_question(self, conflict: dict) -> str:
        """Format a clear, single question about a conflict.

        Args:
            conflict: A conflict dict with at least "findings" list.

        Returns:
            A concise question string in Chinese.
        """
        findings = conflict.get("findings", [conflict])
        if not findings:
            return ""

        category = findings[0].get("category", "unknown") if findings else "unknown"
        descriptions = [
            f.get("description", f.get("value", "?")) for f in findings
        ]

        if len(descriptions) == 1:
            return (
                f"关于 {category}，发现以下信息但置信度较低：\n"
                f"  - {descriptions[0]}\n"
                f"请确认是否正确？"
            )

        lines = "\n".join(f"  - {d}" for d in descriptions)
        return (
            f"关于 {category}，存在以下相互矛盾的信息：\n"
            f"{lines}\n"
            f"请选择正确的理解，或补充说明。"
        )

    def process_answer(self, question_context: dict, answer: str) -> dict:
        """Process the user's answer and produce KB-ready knowledge.

        Args:
            question_context: The conflict dict that was presented to the user.
            answer: The user's text response.

        Returns:
            A dict with resolved knowledge, including:
            category, key, value, description, confidence
        """
        findings = question_context.get("findings", [question_context])
        category = findings[0].get("category", "unknown") if findings else "unknown"

        # Heuristic: if answer names a specific keyword/class name, use it
        # Otherwise, treat the entire answer as the value
        import re

        # Try to extract an identifier from the answer
        id_match = re.search(r'[A-Z][A-Za-z0-9_]{2,}', answer)
        value = id_match.group(0) if id_match else answer.strip()

        # Higher confidence for explicit confirmations
        confirm_patterns = [r'对', r'正确', r'是的', r'没错', r'确认', r'yes', r'correct']
        is_confirmed = any(
            re.search(p, answer, re.IGNORECASE) for p in confirm_patterns
        )

        confidence = 0.94 if is_confirmed else 0.85

        return {
            "category": category,
            "key": f"dialogue:{category}:{value[:30]}",
            "value": value,
            "description": f"通过对话确认: {answer.strip()[:150]}",
            "confidence": confidence,
            "tags": ["dialogue_confirmed" if is_confirmed else "dialogue_answered"],
        }

    # ── internal checks ─────────────────────────────────────────────

    def _affects_correctness(self, findings: list[dict]) -> bool:
        """Check if any finding's category impacts code generation correctness."""
        for f in findings:
            cat = f.get("category", "")
            if cat in self.CRITICAL_CATEGORIES:
                return True
        return False

    @staticmethod
    def _resolvable_silently(findings: list[dict]) -> bool:
        """Heuristic: can the ambiguity be resolved without asking?

        Currently always returns False — browser-based silent verification
        is not implemented.  When it is, this method will check:
        - Can the browser confirm the locator strategy in 1 operation?
        - Can the component name be verified from source in 1 operation?
        """
        # Future: check if findings can be verified via browser snapshot
        # or source-code grep in 1-2 operations.
        # For now, if there's ambiguity, we ask.
        return False
