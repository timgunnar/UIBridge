"""PatternMiner — PrefixSpan stub for frequent subsequence mining.

For v0.4.0, provides a minimal interface for pattern mining.
The PrefixSpan algorithm will be implemented in a future version
for discovering common method-call sequences in test scripts.

Current implementation: simple n-gram frequency counting as a stand-in.
"""

from collections import Counter
from typing import Any, Optional


class PatternMiner:
    """Mines frequent subsequences from sequences of items.

    Uses simple n-gram counting as a PrefixSpan placeholder.
    Full PrefixSpan implementation planned for v0.5.0.
    """

    def __init__(self, min_support: float = 0.1, max_pattern_length: int = 5):
        self.min_support = min_support
        self.max_pattern_length = max_pattern_length

    def mine(self, sequences: list[list[Any]]) -> list[tuple[tuple, int]]:
        """Mine frequent subsequences from a list of sequences.

        Args:
            sequences: List of sequences, each being a list of items
                       e.g. [["open", "click", "type"], ["open", "check", "close"]]

        Returns:
            List of (pattern_tuple, count) sorted by count descending.
            Only patterns meeting min_support are returned.
        """
        if not sequences:
            return []

        total = len(sequences)
        min_count = max(1, int(total * self.min_support))

        # Count individual items first
        item_counts = Counter()
        for seq in sequences:
            item_counts.update(set(seq))  # count each item once per sequence

        # Filter to frequent items
        frequent_items = {item for item, count in item_counts.items()
                          if count >= min_count}

        # Build n-gram patterns up to max_pattern_length
        patterns: list[tuple[tuple, int]] = []

        # 1-grams
        for item, count in item_counts.most_common():
            if count >= min_count:
                patterns.append(((item,), count))

        # 2-grams to N-grams
        for n in range(2, self.max_pattern_length + 1):
            ngram_counts = Counter()
            for seq in sequences:
                if len(seq) < n:
                    continue
                for i in range(len(seq) - n + 1):
                    ngram = tuple(seq[i:i + n])
                    # Only count n-grams where all items are frequent
                    if all(item in frequent_items for item in ngram):
                        ngram_counts[ngram] += 1
            for ngram, count in ngram_counts.most_common():
                if count >= min_count:
                    patterns.append((ngram, count))

        # Sort by count descending, then by length
        patterns.sort(key=lambda x: (-x[1], -len(x[0]), x[0]))
        return patterns

    def mine_closed_patterns(self, sequences: list[list[Any]]
                              ) -> list[tuple[tuple, int]]:
        """Stub: mine closed patterns (where no super-pattern has the same support).

        For v0.4.0, delegates to mine() and marks all as potentially non-closed.
        """
        patterns = self.mine(sequences)
        return patterns  # Stub — no closed-pattern filtering yet

    def mine_maximal_patterns(self, sequences: list[list[Any]]
                               ) -> list[tuple[tuple, int]]:
        """Stub: mine maximal patterns (patterns that have no frequent super-pattern).

        For v0.4.0, returns patterns of max_pattern_length.
        """
        patterns = self.mine(sequences)
        max_len = self.max_pattern_length
        return [(p, c) for p, c in patterns if len(p) == max_len] or patterns

    @staticmethod
    def sequence_to_string(sequence: tuple) -> str:
        """Convert a pattern tuple to a readable string representation."""
        return " → ".join(str(item) for item in sequence)
