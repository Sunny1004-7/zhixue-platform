from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...resource_metrics import resource_completion
from ...learning_support_models import AttentionScoreSnapshot, DecisionSnapshot
from ...models import (
    AuditEvent,
    Concept,
    Course,
    CourseEnrollment,
    KnowledgeState,
    LearningEvent,
    User,
)
from .attention import AttentionInput, AttentionResult, attention_score, priority_students
from .audience import StudentConceptState, classify_state
from .snapshots import stable_snapshot_hash


ALGORITHM_VERSION = "tides-attention-1.1.0"
WINDOW_DAYS = 28


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class SnapshotStudent:
    row: AttentionScoreSnapshot
    user: User


def require_teacher_course(db: Session, teacher_id: str, course_id: str) -> Course:
    course = db.scalar(select(Course).where(
        Course.id == course_id,
        Course.teacher_id == teacher_id,
    ))
    if course is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")
    return course


def require_enrolled_student(
    db: Session,
    *,
    course_id: str,
    student_id: str,
) -> tuple[User, CourseEnrollment]:
    row = db.execute(
        select(User, CourseEnrollment)
        .join(CourseEnrollment, CourseEnrollment.student_id == User.id)
        .where(
            User.id == student_id,
            User.role == "student",
            User.active.is_(True),
            CourseEnrollment.course_id == course_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="学生不存在或不属于当前课程")
    return row[0], row[1]


def _metric_inputs(
    db: Session,
    *,
    enrollment: CourseEnrollment,
    as_of: datetime,
) -> tuple[AttentionInput, dict[str, Any]]:
    since = as_of - timedelta(days=WINDOW_DAYS)
    events = list(db.scalars(select(LearningEvent).where(
        LearningEvent.student_id == enrollment.student_id,
        LearningEvent.course_id == enrollment.course_id,
        LearningEvent.occurred_at >= since,
        LearningEvent.occurred_at <= as_of,
    )).all())
    practice_count = sum(
        1 for item in events
        if item.event_type == "answer_scored" and item.processing_status == "accepted"
    )
    effective_tutoring_count = sum(
        1 for item in events
        if item.event_type == "tutor_message_received"
        and item.processing_status == "accepted"
        and float(item.evidence_reliability or 0.0) > 0
    )
    last_activity = max((as_utc(item.occurred_at) for item in events), default=None)
    state_confidences = list(db.scalars(select(KnowledgeState.confidence).where(
        KnowledgeState.student_id == enrollment.student_id,
        KnowledgeState.course_id == enrollment.course_id,
    )).all())
    accuracy_confidence = (
        sum(float(item) for item in state_confidences) / len(state_confidences)
        if state_confidences else 0.0
    )
    completion = resource_completion(db, enrollment.student_id, enrollment.course_id).percent
    attention_input = AttentionInput(
        student_id=enrollment.student_id,
        practice_count=practice_count,
        accuracy=float(enrollment.recent_accuracy),
        resource_completion=completion,
        effective_tutoring_count=effective_tutoring_count,
        practice_confidence=1.0,
        accuracy_confidence=accuracy_confidence,
        resource_confidence=1.0,
        tutoring_confidence=1.0,
        last_activity_at=last_activity,
    )
    raw = {
        "window_days": WINDOW_DAYS,
        "practice_count": practice_count,
        "accuracy": round(float(enrollment.recent_accuracy), 4),
        "resource_completion": round(completion, 4),
        "effective_tutoring_count": effective_tutoring_count,
        "practice_confidence": 1.0,
        "accuracy_confidence": round(accuracy_confidence, 4),
        "resource_confidence": 1.0,
        "tutoring_confidence": 1.0,
        "last_activity_at": last_activity.isoformat() if last_activity else None,
    }
    return attention_input, raw


def create_snapshot(
    db: Session,
    *,
    teacher_id: str,
    course_id: str,
    as_of: datetime | None = None,
) -> DecisionSnapshot:
    require_teacher_course(db, teacher_id, course_id)
    timestamp = as_utc(as_of or datetime.now(timezone.utc))
    if timestamp > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="快照时间不能位于未来")
    enrollments = list(db.scalars(
        select(CourseEnrollment)
        .join(User, User.id == CourseEnrollment.student_id)
        .where(
            CourseEnrollment.course_id == course_id,
            User.role == "student",
            User.active.is_(True),
        )
        .order_by(CourseEnrollment.student_id)
    ).all())
    evaluated: list[tuple[AttentionResult, dict[str, Any]]] = []
    for enrollment in enrollments:
        metric_input, raw = _metric_inputs(db, enrollment=enrollment, as_of=timestamp)
        evaluated.append((attention_score(metric_input), raw))
    source_payload = {
        "course_id": course_id,
        "as_of": timestamp.isoformat(),
        "algorithm_version": ALGORITHM_VERSION,
        "students": [{
            "student_id": result.student_id,
            "raw": raw,
        } for result, raw in evaluated],
    }
    source_hash = stable_snapshot_hash(source_payload)
    snapshot_payload = {
        "source_state_hash": source_hash,
        "weights": {
            "practice": 0.25,
            "accuracy": 0.30,
            "resource": 0.25,
            "tutoring": 0.20,
        },
        "practice_saturation": 40,
        "tutoring_saturation": 6,
    }
    scores = [item[0] for item in evaluated]
    priority_order = priority_students(scores, limit=len(scores))
    rank_by_student = {
        item.student_id: index for index, item in enumerate(priority_order, start=1)
    }
    aggregate = {
        "average_score": round(sum(item.score for item in scores) / max(1, len(scores)), 2),
        "average_confidence": round(sum(item.confidence for item in scores) / max(1, len(scores)), 4),
        "average_practice_count": round(
            sum(raw["practice_count"] for _, raw in evaluated) / max(1, len(evaluated)), 2
        ),
        "average_accuracy": round(
            sum(raw["accuracy"] for _, raw in evaluated) / max(1, len(evaluated)), 2
        ),
        "average_resource_completion": round(
            sum(raw["resource_completion"] for _, raw in evaluated) / max(1, len(evaluated)), 2
        ),
        "average_effective_tutoring_count": round(
            sum(raw["effective_tutoring_count"] for _, raw in evaluated) / max(1, len(evaluated)), 2
        ),
        "priority_student_ids": [item.student_id for item in priority_order[:3]],
        "window_days": WINDOW_DAYS,
    }
    snapshot = DecisionSnapshot(
        id=str(uuid4()), course_id=course_id, created_by=teacher_id,
        as_of=timestamp, source_state_hash=source_hash,
        snapshot_hash=stable_snapshot_hash(snapshot_payload),
        student_count=len(evaluated), aggregate_json=aggregate,
        algorithm_version=ALGORITHM_VERSION,
    )
    db.add(snapshot)
    db.flush()
    for result, raw in evaluated:
        db.add(AttentionScoreSnapshot(
            id=str(uuid4()), snapshot_id=snapshot.id,
            student_id=result.student_id,
            rank=rank_by_student[result.student_id],
            score=result.score, confidence=result.confidence,
            raw_components_json=raw,
            normalized_components_json={
                "practice_score": result.practice_score,
                "accuracy_score": result.accuracy_score,
                "resource_score": result.resource_score,
                "tutoring_score": result.tutoring_score,
            },
            last_activity_at=result.last_activity_at,
        ))
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=teacher_id, action="decision.snapshot.created",
        object_type="decision_snapshot", object_id=snapshot.id,
        course_id=course_id, outcome="success",
        metadata_json={
            "student_count": len(evaluated),
            "algorithm_version": ALGORITHM_VERSION,
            "source_state_hash": source_hash,
        },
    ))
    db.commit()
    return snapshot


def latest_snapshot(db: Session, course_id: str) -> DecisionSnapshot:
    snapshot = db.scalar(select(DecisionSnapshot).where(
        DecisionSnapshot.course_id == course_id
    ).order_by(DecisionSnapshot.as_of.desc(), DecisionSnapshot.created_at.desc()))
    if snapshot is None:
        raise HTTPException(status_code=404, detail="尚无教学决策快照，请先刷新")
    return snapshot


def snapshot_students(
    db: Session,
    snapshot: DecisionSnapshot,
) -> list[SnapshotStudent]:
    rows = db.execute(
        select(AttentionScoreSnapshot, User)
        .join(User, User.id == AttentionScoreSnapshot.student_id)
        .where(AttentionScoreSnapshot.snapshot_id == snapshot.id)
    ).all()
    return [SnapshotStudent(row=item[0], user=item[1]) for item in rows]


def student_concept_states(
    db: Session,
    *,
    student_id: str,
    course_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    concepts = list(db.scalars(
        select(Concept)
        .where(Concept.course_id == course_id)
        .order_by(Concept.sort_order, Concept.id)
        .limit(limit)
    ).all())
    states = list(db.scalars(select(KnowledgeState).where(
        KnowledgeState.student_id == student_id,
        KnowledgeState.course_id == course_id,
        KnowledgeState.concept_id.in_([item.id for item in concepts]),
    )).all())
    state_by_concept = {item.concept_id: item for item in states}
    result: list[dict[str, Any]] = []
    for concept in concepts:
        state = state_by_concept.get(concept.id)
        evidence_count = state.evidence_count if state else 0
        mastery = float(state.mastery) if state else 50.0
        category = classify_state(StudentConceptState(
            student_id=student_id, course_id=course_id, concept_id=concept.id,
            mastery=mastery, evidence_count=evidence_count,
            confidence=float(state.confidence) if state else 0.0,
            effective_evidence=float(state.effective_evidence) if state else 0.0,
            uncertainty=float(state.uncertainty) if state else 1.0,
        ))
        result.append({
            "concept_id": concept.id,
            "label": concept.name,
            "state": category,
            "mastery": round(mastery, 2),
            "accuracy": round(float(state.correct_rate), 2) if state else 0.0,
            "evidence_count": evidence_count,
            "confidence": round(float(state.confidence), 4) if state else 0.0,
            "low_evidence": category == "unseen" or evidence_count <= 1 or state.confidence < 0.45,
            "trend_30d": round(float(state.trend_30d), 4) if state else 0.0,
            "last_evidence_at": state.last_evidence_at if state else None,
        })
    return result
