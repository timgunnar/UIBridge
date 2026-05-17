"""KBItem — the core knowledge entry with confidence scoring"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class KnowledgeSource(Enum):
    STATIC_ANALYSIS = "static_analysis"      # 0.6-0.8 confidence
    RUNTIME_ANALYSIS = "runtime_analysis"    # 0.8-0.95 confidence
    HUMAN_INJECTION = "human_injection"      # 0.9-0.99 confidence
    PATTERN_MINING = "pattern_mining"        # 0.5-0.7 confidence
    LLM_INFERENCE = "llm_inference"          # 0.4-0.6 confidence


@dataclass
class Confidence:
    """Confidence score with dynamic adjustment, decay, and manual override."""
    score: float = 0.5
    source: KnowledgeSource = KnowledgeSource.LLM_INFERENCE
    self_test_passes: int = 0
    self_test_failures: int = 0
    last_validated_at: float = 0.0
    decay_rate: float = 0.0  # points per day, 0 = no decay
    manual_override: Optional[float] = None
    history: list[dict] = field(default_factory=list)

    @property
    def effective_score(self) -> float:
        if self.manual_override is not None:
            return self.manual_override
        score = self.score
        if self.decay_rate > 0 and self.last_validated_at > 0:
            days = (time.time() - self.last_validated_at) / 86400
            score -= self.decay_rate * days
        return max(0.0, min(1.0, score))

    def record_pass(self):
        self.self_test_passes += 1
        self.score = min(1.0, self.score + 0.02)
        self.last_validated_at = time.time()
        self.history.append({"event": "pass", "score": self.score, "ts": self.last_validated_at})

    def record_failure(self):
        self.self_test_failures += 1
        self.score = max(0.0, self.score - 0.25)
        self.last_validated_at = time.time()
        self.history.append({"event": "failure", "score": self.score, "ts": self.last_validated_at})


@dataclass
class KBItem:
    """A single knowledge entry in the KB."""
    id: str                          # unique identifier
    category: str                    # conventions | components | patterns | pages
    key: str                         # e.g. "component_type.table"
    value: dict                      # the actual knowledge payload
    confidence: Confidence = field(default_factory=Confidence)
    description: str = ""            # NL description for query/summary
    tags: list[str] = field(default_factory=list)
    source_file: str = ""            # which file this knowledge came from
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    version: int = 1
    archived: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "confidence": {
                "score": self.confidence.score,
                "source": self.confidence.source.value,
                "self_test_passes": self.confidence.self_test_passes,
                "self_test_failures": self.confidence.self_test_failures,
                "effective_score": self.confidence.effective_score,
                "last_validated_at": self.confidence.last_validated_at,
                "decay_rate": self.confidence.decay_rate,
                "manual_override": self.confidence.manual_override,
                "history": self.confidence.history,
            },
            "description": self.description,
            "tags": self.tags,
            "source_file": self.source_file,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "archived": self.archived,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KBItem":
        conf = d.get("confidence", {})
        return cls(
            id=d["id"],
            category=d["category"],
            key=d["key"],
            value=d["value"],
            confidence=Confidence(
                score=conf.get("score", 0.5),
                source=KnowledgeSource(conf.get("source", "llm_inference")),
                self_test_passes=conf.get("self_test_passes", 0),
                self_test_failures=conf.get("self_test_failures", 0),
                last_validated_at=conf.get("last_validated_at", 0.0),
                decay_rate=conf.get("decay_rate", 0.0),
                manual_override=conf.get("manual_override"),
                history=conf.get("history", []),
            ),
            description=d.get("description", ""),
            tags=d.get("tags", []),
            source_file=d.get("source_file", ""),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            version=d.get("version", 1),
            archived=d.get("archived", False),
        )
