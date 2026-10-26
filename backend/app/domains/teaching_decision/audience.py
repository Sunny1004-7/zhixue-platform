from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..trajectory.evidence import classify_state as classify_learning_state


ConceptState = Literal["weak", "mastered", "unseen"]


@dataclass(frozen=True)
class StudentConceptState:
    student_id: str
    course_id: str
    concept_id: str
    mastery: float
    evidence_count: int
    confidence: float
    effective_evidence: float
    uncertainty: float


@dataclass(frozen=True)
class AudienceMatch:
    student_id: str
    matched_concepts: tuple[str, ...]
    matched_states: tuple[ConceptState, ...]
    low_evidence: bool


def classify_state(state: StudentConceptState) -> ConceptState:
    return classify_learning_state(state.mastery / 100.0, state.effective_evidence, state.uncertainty)


def resolve_audience(
    states: list[StudentConceptState],
    *,
    course_id: str,
    resource_concept_ids: list[str],
    selected_states: set[ConceptState],
    minimum_confidence: float = 0.45,
) -> list[AudienceMatch]:
    if not resource_concept_ids or not selected_states:
        return []
    ordered_concepts = list(dict.fromkeys(resource_concept_ids))
    allowed = set(ordered_concepts)
    grouped: dict[str, list[StudentConceptState]] = {}
    for item in states:
        if item.course_id != course_id or item.concept_id not in allowed:
            continue
        if classify_state(item) not in selected_states:
            continue
        grouped.setdefault(item.student_id, []).append(item)
    results: list[AudienceMatch] = []
    order = {value: index for index, value in enumerate(ordered_concepts)}
    for student_id, items in grouped.items():
        items.sort(key=lambda item: order[item.concept_id])
        states_for_student = tuple(classify_state(item) for item in items)
        results.append(AudienceMatch(
            student_id=student_id,
            matched_concepts=tuple(item.concept_id for item in items),
            matched_states=states_for_student,
            low_evidence=any(
                classify_state(item) == "unseen" or item.confidence < minimum_confidence
                or item.evidence_count <= 1 for item in items
            ),
        ))
    return sorted(results, key=lambda item: item.student_id)
