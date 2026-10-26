from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...models import (
    AuditEvent,
    Concept,
    CourseEnrollment,
    EventConcept,
    KnowledgeState,
    LearningEvent,
    MasteryEvidence,
    User,
)
from .evidence import beta_statistics, classify_state, combined_uncertainty, decay_beta, score_event
from .graph_constraint import PublishedGraphConstraint
from .numerics import OnlineUpdateConfig, mix_probabilities, smooth_probability
from .ports import GraphConstraintPort, TemporalResidualPort
from .temporal_residual import EvidenceTemporalResidual


MODEL_VERSION = "eglt-0.4.0"


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ConceptContribution:
    concept_id: str
    weight: float


@dataclass(frozen=True)
class EventCommand:
    idempotency_key: str
    event_type: str
    object_type: str
    object_id: str
    concepts: list[ConceptContribution]
    outcome: float | None
    difficulty: float | None
    hint_level: int | None
    attempt_no: int | None
    completion: float | None
    strategy: str | None
    upstream_confidence: float
    alignment_confidence: float
    occurred_at: datetime
    correction_of_event_id: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class StateChange:
    concept_id: str
    mastery: float
    uncertainty: float
    effective_evidence: float
    status: str
    delta: float
    model_version: str


@dataclass(frozen=True)
class IngestionResult:
    event_id: str
    duplicate: bool
    processing_status: str
    evidence_success: float | None
    evidence_reliability: float | None
    evidence_reason: str
    changes: list[StateChange]


class TrajectoryService:
    def __init__(
        self,
        db: Session,
        *,
        temporal: TemporalResidualPort | None = None,
        graph: GraphConstraintPort | None = None,
        online_update: OnlineUpdateConfig | None = None,
        course_online_updates: Mapping[str, OnlineUpdateConfig] | None = None,
    ):
        self.db = db
        self.temporal = temporal or EvidenceTemporalResidual(db)
        self.graph = graph or PublishedGraphConstraint(db)
        self.online_update = online_update or OnlineUpdateConfig()
        self.course_online_updates = dict(course_online_updates or {})

    def _online_config(self, course_id: str) -> OnlineUpdateConfig:
        return self.course_online_updates.get(course_id, self.online_update)

    def ingest(self, *, student: User, course_id: str, command: EventCommand) -> IngestionResult:
        enrollment = self.db.scalar(select(CourseEnrollment).where(
            CourseEnrollment.student_id == student.id,
            CourseEnrollment.course_id == course_id,
        ))
        if enrollment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课程不存在或无权写入")
        now = datetime.now(timezone.utc)
        if as_utc(command.occurred_at) > now + timedelta(minutes=5):
            raise HTTPException(status_code=422, detail="事件时间不能位于未来")
        existing = self.db.scalar(select(LearningEvent).where(
            LearningEvent.student_id == student.id,
            LearningEvent.course_id == course_id,
            LearningEvent.idempotency_key == command.idempotency_key,
        ))
        if existing is not None:
            return self._duplicate_result(existing)

        contributions = self._validate_concepts(course_id, command.concepts)
        correction = None
        if command.correction_of_event_id:
            correction = self.db.scalar(select(LearningEvent).where(
                LearningEvent.id == command.correction_of_event_id,
                LearningEvent.student_id == student.id,
                LearningEvent.course_id == course_id,
            ))
            if correction is None:
                raise HTTPException(status_code=404, detail="待纠正事件不存在")

        evidence = score_event(
            event_type=command.event_type, outcome=command.outcome, difficulty=command.difficulty,
            hint_level=command.hint_level, attempt_no=command.attempt_no,
            completion=command.completion, upstream_confidence=command.upstream_confidence,
            alignment_confidence=command.alignment_confidence, payload=command.payload,
        )
        event = LearningEvent(
            id=str(uuid4()), actor_id=student.id, student_id=student.id, course_id=course_id,
            idempotency_key=command.idempotency_key, event_type=command.event_type,
            object_type=command.object_type, object_id=command.object_id,
            payload=command.payload, source_type="real", outcome=command.outcome,
            difficulty=command.difficulty, hint_level=command.hint_level,
            attempt_no=command.attempt_no, completion=command.completion,
            strategy=command.strategy, upstream_confidence=command.upstream_confidence,
            alignment_confidence=command.alignment_confidence,
            evidence_success=evidence.success, evidence_reliability=evidence.reliability,
            processing_status=evidence.processing_status,
            correction_of_event_id=correction.id if correction else None,
            schema_version="learning-event-1.0", occurred_at=as_utc(command.occurred_at),
        )
        self.db.add(event)
        self.db.flush()
        for contribution in contributions:
            self.db.add(EventConcept(
                id=str(uuid4()), event_id=event.id, concept_id=contribution.concept_id,
                contribution_weight=contribution.weight,
            ))
        self.db.flush()

        changes: list[StateChange] = []
        if evidence.reliability > 0 and evidence.processing_status == "accepted":
            affected = {item.concept_id: item for item in contributions}
            if correction is not None:
                for original in self.db.scalars(select(EventConcept).where(EventConcept.event_id == correction.id)).all():
                    affected.setdefault(
                        original.concept_id,
                        ConceptContribution(original.concept_id, original.contribution_weight),
                    )
            for contribution in affected.values():
                state = self._state_for_update(student.id, course_id, contribution.concept_id)
                out_of_order = state.last_evidence_at is not None and as_utc(event.occurred_at) < as_utc(state.last_evidence_at)
                if correction is not None or out_of_order:
                    change = self.replay_concept(student.id, course_id, contribution.concept_id)
                else:
                    change = self._apply_event(state, event, contribution.weight)
                changes.append(change)
            self.db.flush()
            changed_ids = set(affected)
            for dependent_id in self.graph.dependent_concepts(
                course_id=course_id,
                prerequisite_ids=set(affected),
            ):
                if dependent_id in changed_ids:
                    continue
                dependent_state = self.db.scalar(select(KnowledgeState).where(
                    KnowledgeState.student_id == student.id,
                    KnowledgeState.course_id == course_id,
                    KnowledgeState.concept_id == dependent_id,
                    KnowledgeState.evidence_count > 0,
                ))
                if dependent_state is None:
                    continue
                has_event_evidence = self.db.scalar(select(MasteryEvidence.id).where(
                    MasteryEvidence.state_id == dependent_state.id,
                    MasteryEvidence.concept_id == dependent_id,
                ).limit(1))
                if has_event_evidence is None:
                    continue
                changes.append(self.replay_concept(student.id, course_id, dependent_id))
                changed_ids.add(dependent_id)
            self.db.flush()
            for concept_id in changed_ids:
                self._refresh_correct_rate(student.id, course_id, concept_id)
                self._refresh_trend(student.id, course_id, concept_id)
            self._refresh_enrollment(student.id, course_id)

        self.db.add(AuditEvent(
            id=str(uuid4()), actor_id=student.id, action="trajectory.event.ingested",
            object_type="learning_event", object_id=event.id, course_id=course_id,
            outcome="success", metadata_json={
                "event_type": event.event_type,
                "processing_status": event.processing_status,
                "changed_concepts": [change.concept_id for change in changes],
                "model_version": MODEL_VERSION,
                "online_update": {
                    "eta_max": self._online_config(course_id).eta_max,
                    "kappa": self._online_config(course_id).kappa,
                    "effective_evidence_definition": "alpha+beta",
                },
            },
        ))
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(select(LearningEvent).where(
                LearningEvent.student_id == student.id,
                LearningEvent.course_id == course_id,
                LearningEvent.idempotency_key == command.idempotency_key,
            ))
            if existing is None:
                raise
            return self._duplicate_result(existing)
        return IngestionResult(
            event_id=event.id, duplicate=False, processing_status=event.processing_status,
            evidence_success=event.evidence_success, evidence_reliability=event.evidence_reliability,
            evidence_reason=evidence.reason, changes=changes,
        )

    def replay_concept(self, student_id: str, course_id: str, concept_id: str) -> StateChange:
        state = self._state_for_update(student_id, course_id, concept_id)
        original_mastery = state.mastery / 100.0
        self.db.execute(delete(MasteryEvidence).where(
            MasteryEvidence.state_id == state.id,
            MasteryEvidence.concept_id == concept_id,
        ))
        state.alpha = state.baseline_alpha
        state.beta = state.baseline_beta
        state.last_evidence_at = None
        state.mastery = 100.0 * state.alpha / (state.alpha + state.beta)
        state.evidence_count = max(0, round(state.baseline_alpha + state.baseline_beta - 2.0))

        rows = self.db.execute(
            select(LearningEvent, EventConcept)
            .join(EventConcept, EventConcept.event_id == LearningEvent.id)
            .where(
                LearningEvent.student_id == student_id,
                LearningEvent.course_id == course_id,
                EventConcept.concept_id == concept_id,
                LearningEvent.processing_status == "accepted",
                LearningEvent.evidence_reliability > 0,
            )
            .order_by(LearningEvent.occurred_at, LearningEvent.id)
        ).all()
        corrected_ids = self._corrected_event_ids(student_id, course_id)
        for event, contribution in rows:
            if event.id in corrected_ids:
                continue
            self._apply_event(state, event, contribution.contribution_weight)
        current = state.mastery / 100.0
        return StateChange(
            concept_id=concept_id, mastery=current, uncertainty=state.uncertainty,
            effective_evidence=state.effective_evidence, status=state.status,
            delta=current - original_mastery, model_version=state.model_version,
        )

    def _apply_event(
        self,
        state: KnowledgeState,
        event: LearningEvent,
        weight: float,
    ) -> StateChange:
        before = state.mastery / 100.0
        if state.last_evidence_at is not None:
            delta_days = max(0.0, (as_utc(event.occurred_at) - as_utc(state.last_evidence_at)).total_seconds() / 86400.0)
            alpha, beta = decay_beta(state.alpha, state.beta, delta_days)
        else:
            alpha, beta = state.alpha, state.beta
        success = float(event.evidence_success if event.evidence_success is not None else 0.5)
        reliability = float(event.evidence_reliability or 0.0)
        alpha += weight * reliability * success
        beta += weight * reliability * (1.0 - success)
        bayes_probability, variance = beta_statistics(alpha, beta)
        effective_evidence = alpha + beta
        online_config = self._online_config(state.course_id)
        probability = smooth_probability(
            before, bayes_probability, effective_evidence,
            eta_max=online_config.eta_max, kappa=online_config.kappa,
        )

        temporal = self.temporal.predict(
            student_id=state.student_id, course_id=state.course_id, concept_id=state.concept_id,
            as_of=as_utc(event.occurred_at),
        )
        model_version = MODEL_VERSION
        if temporal is not None:
            probability = mix_probabilities(probability, temporal.probability, temporal.gate)
            model_version = f"{MODEL_VERSION}+{temporal.model_version}"
        probability, graph_applied = self.graph.constrain(
            student_id=state.student_id, course_id=state.course_id,
            concept_id=state.concept_id, probability=probability,
        )
        if graph_applied:
            model_version = f"{model_version}+a2-graph"
        uncertainty = combined_uncertainty(variance, event.alignment_confidence)
        state.alpha = alpha
        state.beta = beta
        state.mastery = probability * 100.0
        state.uncertainty = uncertainty
        state.effective_evidence = effective_evidence
        state.status = classify_state(probability, effective_evidence, uncertainty)
        state.confidence = 1.0 - uncertainty
        state.evidence_count += 1
        state.trend_30d = probability - before
        state.last_evidence_at = as_utc(event.occurred_at)
        state.model_version = model_version
        state.version += 1
        state.updated_at = datetime.now(timezone.utc)
        delta = probability - before
        self.db.add(MasteryEvidence(
            id=str(uuid4()), state_id=state.id, event_id=event.id, concept_id=state.concept_id,
            contribution_weight=weight, success=success, reliability=reliability,
            mastery_before=before, mastery_after=probability, delta=delta,
            model_version=model_version, created_at=datetime.now(timezone.utc),
        ))
        return StateChange(
            concept_id=state.concept_id, mastery=probability, uncertainty=uncertainty,
            effective_evidence=effective_evidence, status=state.status, delta=delta,
            model_version=model_version,
        )

    def _refresh_enrollment(self, student_id: str, course_id: str) -> None:
        self.db.flush()
        states = self.db.scalars(select(KnowledgeState).where(
            KnowledgeState.student_id == student_id,
            KnowledgeState.course_id == course_id,
            KnowledgeState.status != "unseen",
        )).all()
        if not states:
            return
        weights = [max(0.05, 1.0 - state.uncertainty) for state in states]
        composite = sum((state.mastery / 100.0) * weight for state, weight in zip(states, weights)) / sum(weights)
        enrollment = self.db.scalar(select(CourseEnrollment).where(
            CourseEnrollment.student_id == student_id,
            CourseEnrollment.course_id == course_id,
        ))
        if enrollment is not None:
            enrollment.mastery = composite * 100.0
            answers = self.db.scalars(select(LearningEvent).where(
                LearningEvent.student_id == student_id,
                LearningEvent.course_id == course_id,
                LearningEvent.event_type == "answer_scored",
                LearningEvent.processing_status == "accepted",
                LearningEvent.outcome.is_not(None),
            ).order_by(LearningEvent.occurred_at.desc())).all()
            corrected = self._corrected_event_ids(student_id, course_id)
            active_outcomes = [
                float(event.outcome) for event in answers
                if event.id not in corrected and event.outcome is not None
            ][:30]
            if active_outcomes:
                enrollment.recent_accuracy = 100.0 * sum(active_outcomes) / len(active_outcomes)
            enrollment.updated_at = datetime.now(timezone.utc)

    def _refresh_correct_rate(self, student_id: str, course_id: str, concept_id: str) -> None:
        events = [row[0] for row in self.db.execute(
            select(LearningEvent, EventConcept)
            .join(EventConcept, EventConcept.event_id == LearningEvent.id)
            .where(
                LearningEvent.student_id == student_id,
                LearningEvent.course_id == course_id,
                LearningEvent.event_type == "answer_scored",
                LearningEvent.processing_status == "accepted",
                LearningEvent.outcome.is_not(None),
                EventConcept.concept_id == concept_id,
            )
            .order_by(LearningEvent.occurred_at)
        ).all()]
        corrected = self._corrected_event_ids(student_id, course_id)
        outcomes = [float(event.outcome) for event in events if event.id not in corrected and event.outcome is not None]
        state = self._state_for_update(student_id, course_id, concept_id)
        baseline_count = max(0, round(state.baseline_alpha + state.baseline_beta - 2.0))
        baseline_success = state.baseline_correct_rate / 100.0 * baseline_count
        denominator = baseline_count + len(outcomes)
        if denominator:
            state.correct_rate = 100.0 * (baseline_success + sum(outcomes)) / denominator

    def _refresh_trend(self, student_id: str, course_id: str, concept_id: str) -> None:
        state = self._state_for_update(student_id, course_id, concept_id)
        since = datetime.now(timezone.utc) - timedelta(days=30)
        first = self.db.scalar(select(MasteryEvidence).where(
            MasteryEvidence.state_id == state.id,
            MasteryEvidence.concept_id == concept_id,
            MasteryEvidence.created_at >= since,
        ).order_by(MasteryEvidence.created_at, MasteryEvidence.id))
        state.trend_30d = 0.0 if first is None else state.mastery / 100.0 - first.mastery_before

    def _corrected_event_ids(self, student_id: str, course_id: str) -> set[str]:
        return set(self.db.scalars(select(LearningEvent.correction_of_event_id).where(
            LearningEvent.student_id == student_id,
            LearningEvent.course_id == course_id,
            LearningEvent.correction_of_event_id.is_not(None),
        )).all())

    def _validate_concepts(
        self,
        course_id: str,
        contributions: Iterable[ConceptContribution],
    ) -> list[ConceptContribution]:
        items = list(contributions)
        if not items:
            raise HTTPException(status_code=422, detail="事件必须关联至少一个知识点")
        if len({item.concept_id for item in items}) != len(items):
            raise HTTPException(status_code=422, detail="同一事件不能重复关联知识点")
        if any(item.weight <= 0 for item in items):
            raise HTTPException(status_code=422, detail="知识点贡献权重必须大于0")
        total = sum(item.weight for item in items)
        normalized = [ConceptContribution(item.concept_id, item.weight / total) for item in items]
        valid_ids = set(self.db.scalars(select(Concept.id).where(
            Concept.course_id == course_id,
            Concept.id.in_([item.concept_id for item in normalized]),
        )).all())
        if len(valid_ids) != len(normalized):
            raise HTTPException(status_code=422, detail="知识点不存在或不属于当前课程")
        return normalized

    def _state_for_update(self, student_id: str, course_id: str, concept_id: str) -> KnowledgeState:
        state = self.db.scalar(select(KnowledgeState).where(
            KnowledgeState.student_id == student_id,
            KnowledgeState.course_id == course_id,
            KnowledgeState.concept_id == concept_id,
        ).with_for_update())
        if state is None:
            state = KnowledgeState(
                id=str(uuid4()), student_id=student_id, course_id=course_id, concept_id=concept_id,
                mastery=50.0, correct_rate=0.0, evidence_count=0, confidence=0.0,
                baseline_correct_rate=0.0,
                baseline_alpha=1.0, baseline_beta=1.0, alpha=1.0, beta=1.0,
                uncertainty=1.0, effective_evidence=2.0, status="unseen",
                trend_30d=0.0, model_version=MODEL_VERSION, version=1,
            )
            self.db.add(state)
            self.db.flush()
        return state

    def _duplicate_result(self, event: LearningEvent) -> IngestionResult:
        evidence_rows = self.db.execute(
            select(MasteryEvidence, KnowledgeState)
            .join(KnowledgeState, KnowledgeState.id == MasteryEvidence.state_id)
            .where(MasteryEvidence.event_id == event.id)
        ).all()
        return IngestionResult(
            event_id=event.id, duplicate=True, processing_status=event.processing_status,
            evidence_success=event.evidence_success, evidence_reliability=event.evidence_reliability,
            evidence_reason="幂等命中，未重复更新状态",
            changes=[StateChange(
                concept_id=evidence.concept_id, mastery=state.mastery / 100.0,
                uncertainty=state.uncertainty, effective_evidence=state.effective_evidence,
                status=state.status, delta=0.0, model_version=state.model_version,
            ) for evidence, state in evidence_rows],
        )
