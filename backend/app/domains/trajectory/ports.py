from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class TemporalPrediction:
    probability: float
    gate: float
    model_version: str


class TemporalResidualPort(Protocol):
    def predict(
        self,
        *,
        student_id: str,
        course_id: str,
        concept_id: str,
        as_of: datetime,
    ) -> TemporalPrediction | None: ...


class NullTemporalResidual:
    """冷启动降级：无受训模型时显式返回None，不伪造深度预测。"""

    def predict(
        self,
        *,
        student_id: str,
        course_id: str,
        concept_id: str,
        as_of: datetime,
    ) -> None:
        return None


class GraphConstraintPort(Protocol):
    def constrain(self, *, student_id: str, course_id: str, concept_id: str, probability: float) -> tuple[float, bool]: ...

    def dependent_concepts(self, *, course_id: str, prerequisite_ids: set[str]) -> list[str]: ...


class NullGraphConstraint:
    """A2尚无已审核先修图时禁用图约束。"""

    def constrain(self, *, student_id: str, course_id: str, concept_id: str, probability: float) -> tuple[float, bool]:
        return probability, False

    def dependent_concepts(self, *, course_id: str, prerequisite_ids: set[str]) -> list[str]:
        return []
