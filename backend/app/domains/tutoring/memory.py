from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", value.lower()))


@dataclass(frozen=True)
class MemoryCandidate:
    id: str
    student_id: str
    course_id: str
    content: str
    confidence: float
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    deleted_at: datetime | None = None
    conflict_group: str | None = None


@dataclass(frozen=True)
class RecalledMemory:
    memory: MemoryCandidate
    score: float
    reason_codes: tuple[str, ...]


def recall_memories(
    candidates: list[MemoryCandidate],
    *,
    student_id: str,
    course_id: str,
    query: str,
    authorized: bool,
    now: datetime | None = None,
    limit: int = 8,
) -> list[RecalledMemory]:
    if not authorized or limit <= 0:
        return []
    timestamp = now or datetime.now(timezone.utc)
    query_tokens = _tokens(query)
    scored: list[RecalledMemory] = []
    for memory in candidates:
        if memory.student_id != student_id or memory.course_id != course_id:
            continue
        if memory.deleted_at is not None or memory.status not in {"active", "confirmed"}:
            continue
        if memory.expires_at is not None and memory.expires_at <= timestamp:
            continue
        if memory.confidence < 0.35:
            continue
        tokens = _tokens(memory.content)
        overlap = len(tokens & query_tokens) / max(1, len(tokens | query_tokens))
        age_days = max(0.0, (timestamp - memory.created_at).total_seconds() / 86400.0)
        recency = math.exp(-math.log(2) * age_days / 90.0)
        score = 0.55 * overlap + 0.3 * memory.confidence + 0.15 * recency
        reasons = ["COURSE_SCOPED", "AUTHORIZED"]
        if overlap > 0:
            reasons.append("SEMANTIC_OVERLAP")
        if memory.status == "confirmed":
            reasons.append("STUDENT_CONFIRMED")
            score += 0.05
        scored.append(RecalledMemory(memory, round(min(score, 1.0), 4), tuple(reasons)))
    scored.sort(key=lambda item: (-item.score, -item.memory.created_at.timestamp(), item.memory.id))
    selected: list[RecalledMemory] = []
    seen_conflicts: set[str] = set()
    for item in scored:
        conflict_group = item.memory.conflict_group
        if conflict_group and conflict_group in seen_conflicts:
            continue
        if conflict_group:
            seen_conflicts.add(conflict_group)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected
