from __future__ import annotations

from dataclasses import dataclass

from .schemas import CompileBlueprintRequest, QUESTION_TYPES


COMPILER_VERSION = "traceq-blueprint-1.0.0"
DIFFICULTY_TARGETS = {
    "basic": 0.25,
    "standard": 0.5,
    "balanced": 0.55,
    "challenge": 0.78,
}
COGNITIVE_LEVELS = {
    "single": "understand",
    "multiple": "analyze",
    "judgment": "understand",
    "fill": "remember",
    "short": "apply",
    "scenario": "analyze",
}


@dataclass(frozen=True)
class CompiledCell:
    concept_id: str
    question_type: str
    count: int
    difficulty_target: float
    cognitive_level: str
    position: int


def _personalized_target(mastery: float | None, evidence_count: int | None) -> float:
    if mastery is None or evidence_count is None or evidence_count <= 0:
        raise ValueError("缺少历史证据，不能声称个性化难度")
    normalized = mastery / 100.0  # public state values use the 0–100 scale
    # 在当前能力上方给出可达的挑战，同时控制难度范围。
    return round(max(0.2, min(0.82, 0.72 - 0.35 * normalized)), 4)


def compile_cells(
    request: CompileBlueprintRequest,
    *,
    learner_evidence: dict[str, tuple[float | None, int | None]],
) -> list[CompiledCell]:
    cells: list[CompiledCell] = []
    position = 1
    for concept in request.concepts:
        if request.difficulty_mode == "personalized":
            mastery, evidence_count = learner_evidence.get(concept.concept_id, (None, None))
            target = _personalized_target(mastery, evidence_count)
        else:
            target = DIFFICULTY_TARGETS[request.difficulty_mode]
        for question_type in QUESTION_TYPES:
            count = int(getattr(concept.counts, question_type))
            if count <= 0:
                continue
            cells.append(CompiledCell(
                concept_id=concept.concept_id,
                question_type=question_type,
                count=count,
                difficulty_target=target,
                cognitive_level=COGNITIVE_LEVELS[question_type],
                position=position,
            ))
            position += 1
    return cells
