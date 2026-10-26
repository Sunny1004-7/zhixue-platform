from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import EventConcept, LearningEvent
from .ports import TemporalPrediction
from .numerics import temporal_statistics


MODEL_VERSION = "temporal-evidence-1.0"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class EvidenceTemporalResidual:
    """Cold-start temporal residual built only from accepted, auditable evidence.

    This adapter is deliberately deterministic. It gives the online A1 path a
    real sequential signal before a trained residual model has compliant data,
    while keeping the gate small enough that it cannot replace the Beta state.
    """

    def __init__(
        self,
        db: Session,
        *,
        max_events: int = 20,
        half_life_days: float = 30.0,
        max_gate: float = 0.18,
    ):
        self.db = db
        self.max_events = max(2, max_events)
        self.half_life_days = max(1.0, half_life_days)
        self.max_gate = max(0.0, min(0.30, max_gate))

    def predict(
        self,
        *,
        student_id: str,
        course_id: str,
        concept_id: str,
        as_of: datetime,
    ) -> TemporalPrediction | None:
        cutoff = _as_utc(as_of)
        rows = self.db.execute(
            select(LearningEvent, EventConcept)
            .join(EventConcept, EventConcept.event_id == LearningEvent.id)
            .where(
                LearningEvent.student_id == student_id,
                LearningEvent.course_id == course_id,
                EventConcept.concept_id == concept_id,
                LearningEvent.processing_status == "accepted",
                LearningEvent.evidence_reliability > 0,
                LearningEvent.occurred_at <= cutoff,
            )
            .order_by(LearningEvent.occurred_at.desc(), LearningEvent.id.desc())
            .limit(self.max_events * 2)
        ).all()
        if not rows:
            return None

        corrected_ids = {
            event.correction_of_event_id
            for event, _ in rows
            if event.correction_of_event_id is not None
        }
        active = [
            (event, link)
            for event, link in rows
            if event.id not in corrected_ids and event.evidence_success is not None
        ][: self.max_events]
        if len(active) < 2:
            return None

        result = temporal_statistics([
            {"occurred_at": _as_utc(event.occurred_at), "success": float(event.evidence_success),
             "reliability": float(event.evidence_reliability or 0.0),
             "weight": float(link.contribution_weight)} for event,link in active
        ], cutoff, max_events=self.max_events, half_life_days=self.half_life_days, max_gate=self.max_gate)
        if result is None:
            return None
        probability, gate = result
        return TemporalPrediction(
            probability=probability,
            gate=gate,
            model_version=MODEL_VERSION,
        )
