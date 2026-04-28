from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MergeSource(StrEnum):
    USER_EDIT = "USER_EDIT"
    PARSED_TEXT = "PARSED_TEXT"
    WEAK_INFERENCE = "WEAK_INFERENCE"


@dataclass(frozen=True, slots=True)
class ProfileFact:
    key: str
    value: Any
    source: MergeSource
    confidence: float
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalProfileBuilder:
    facts: list[ProfileFact] = field(default_factory=list)

    def merge(self) -> dict[str, Any]:
        ranked: dict[str, ProfileFact] = {}
        for fact in self.facts:
            if fact.confidence < 0 or fact.confidence > 1:
                raise ValueError(f"confidence out of range for {fact.key}")
            current = ranked.get(fact.key)
            if current is None or self._wins(fact, current):
                ranked[fact.key] = fact

        return {
            key: {
                "value": fact.value,
                "source": fact.source.value,
                "confidence": fact.confidence,
                "evidence": fact.evidence,
                "requires_review": fact.source == MergeSource.WEAK_INFERENCE or fact.confidence < 0.65,
            }
            for key, fact in ranked.items()
        }

    @staticmethod
    def _wins(candidate: ProfileFact, current: ProfileFact) -> bool:
        source_rank = {
            MergeSource.USER_EDIT: 3,
            MergeSource.PARSED_TEXT: 2,
            MergeSource.WEAK_INFERENCE: 1,
        }
        candidate_rank = source_rank[candidate.source]
        current_rank = source_rank[current.source]
        if candidate_rank != current_rank:
            return candidate_rank > current_rank
        return candidate.confidence > current.confidence
