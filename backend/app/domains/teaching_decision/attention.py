from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class AttentionInput:
    student_id: str
    practice_count: int
    accuracy: float
    resource_completion: float
    effective_tutoring_count: int
    practice_confidence: float = 1.0
    accuracy_confidence: float = 1.0
    resource_confidence: float = 1.0
    tutoring_confidence: float = 1.0
    last_activity_at: datetime | None = None


@dataclass(frozen=True)
class AttentionResult:
    student_id: str
    score: float
    confidence: float
    practice_score: float
    accuracy_score: float
    resource_score: float
    tutoring_score: float
    last_activity_at: datetime | None
    policy_version: str = "tides-attention-1.0.0"


def _bounded(value: float) -> float:
    return max(0.0, min(float(value), 100.0))


def _confidence(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def attention_score(value: AttentionInput) -> AttentionResult:
    practice = 100.0 * min(max(value.practice_count, 0) / 40.0, 1.0)
    accuracy = _bounded(value.accuracy)
    resource = _bounded(value.resource_completion)
    tutoring = 100.0 * min(max(value.effective_tutoring_count, 0) / 6.0, 1.0)
    score = 0.25 * practice + 0.30 * accuracy + 0.25 * resource + 0.20 * tutoring
    confidence = (
        0.25 * _confidence(value.practice_confidence)
        + 0.30 * _confidence(value.accuracy_confidence)
        + 0.25 * _confidence(value.resource_confidence)
        + 0.20 * _confidence(value.tutoring_confidence)
    )
    return AttentionResult(
        student_id=value.student_id,
        score=round(score, 2),
        confidence=round(confidence, 4),
        practice_score=round(practice, 2),
        accuracy_score=round(accuracy, 2),
        resource_score=round(resource, 2),
        tutoring_score=round(tutoring, 2),
        last_activity_at=value.last_activity_at,
    )


def priority_students(results: list[AttentionResult], limit: int = 3) -> list[AttentionResult]:
    if limit <= 0:
        return []
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return sorted(
        results,
        key=lambda item: (
            item.score,
            item.last_activity_at or epoch,
            item.confidence,
            item.student_id,
        ),
    )[:limit]
