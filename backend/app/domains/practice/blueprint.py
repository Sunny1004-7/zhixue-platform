from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import (
    AlignmentCandidate,
    AlignmentMention,
    AlignmentReview,
    AlignmentRun,
    AuditEvent,
    BlueprintCell,
    Concept,
    GraphNode,
    GraphRevision,
    KnowledgeGraph,
    KnowledgeState,
    QuestionBlueprint,
    User,
)
from ...repositories import CourseRepository
from .schemas import CompileBlueprintRequest, QuestionType


COMPILER_VERSION = "traceq-blueprint-1.0.0"
QUESTION_TYPES: tuple[QuestionType, ...] = (
    "single",
    "multiple",
    "judgment",
    "fill",
    "short",
    "scenario",
)


def _failure(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _authorize_course(db: Session, actor: User, course_id: str) -> None:
    repository = CourseRepository(db)
    allowed = (
        repository.get_student_course(actor.id, course_id)
        if actor.role == "student"
        else repository.get_teacher_course(actor.id, course_id)
    )
    if allowed is None:
        raise _failure(404, "PRACTICE_COURSE_NOT_FOUND", "课程不存在或无权访问")


def _chosen_alignment_concept(db: Session, mention: AlignmentMention) -> str | None:
    review = db.scalar(select(AlignmentReview).where(AlignmentReview.mention_id == mention.id))
    if review is not None and review.status == "decided":
        return review.selected_concept_id if review.decision == "matched" else None
    candidate = db.scalar(select(AlignmentCandidate).where(
        AlignmentCandidate.mention_id == mention.id,
        AlignmentCandidate.recommended.is_(True),
    ))
    return candidate.concept_id if candidate is not None else None


def _validate_course_concepts(
    db: Session,
    course_id: str,
    requested_ids: list[str],
) -> dict[str, Concept]:
    concepts = list(db.scalars(select(Concept).where(
        Concept.course_id == course_id,
        Concept.id.in_(requested_ids),
    )).all())
    by_id = {item.id: item for item in concepts}
    missing = [concept_id for concept_id in requested_ids if concept_id not in by_id]
    if missing:
        raise _failure(
            422,
            "BLUEPRINT_CONCEPT_OUT_OF_SCOPE",
            "蓝图包含不存在或不属于当前课程的知识点",
        )
    return by_id


def _history_summary(
    db: Session,
    actor: User,
    course_id: str,
    requested_ids: list[str],
    *,
    personalized: bool,
) -> tuple[dict[str, Any], dict[str, KnowledgeState]]:
    if actor.role == "student":
        states = list(db.scalars(select(KnowledgeState).where(
            KnowledgeState.student_id == actor.id,
            KnowledgeState.course_id == course_id,
            KnowledgeState.concept_id.in_(requested_ids),
        )).all())
        by_id = {item.concept_id: item for item in states}
        unsupported = [
            concept_id for concept_id in requested_ids
            if concept_id not in by_id or by_id[concept_id].evidence_count <= 0
        ]
        if unsupported:
            raise _failure(
                422,
                "HISTORY_EVIDENCE_REQUIRED",
                "所选知识点缺少真实学习证据，不能标记为历史个性化练习",
            )
        return ({
            "source_method": "history",
            "scope": "student_trajectory",
            "student_id": actor.id,
            "evidence_backed_concept_count": len(by_id),
            "personalization_applied": personalized,
            "selected_concept_ids": requested_ids,
        }, by_id)

    if personalized:
        raise _failure(
            422,
            "PERSONALIZED_DIFFICULTY_REQUIRES_STUDENT",
            "教师班级蓝图不能冒充单个学生的个性化难度",
        )
    evidence_counts = dict(db.execute(
        select(KnowledgeState.concept_id, func.count(KnowledgeState.id))
        .where(
            KnowledgeState.course_id == course_id,
            KnowledgeState.concept_id.in_(requested_ids),
            KnowledgeState.evidence_count > 0,
        )
        .group_by(KnowledgeState.concept_id)
    ).all())
    if any(evidence_counts.get(concept_id, 0) <= 0 for concept_id in requested_ids):
        raise _failure(
            422,
            "HISTORY_EVIDENCE_REQUIRED",
            "所选知识点没有班级作答证据",
        )
    return ({
        "source_method": "history",
        "scope": "course_trajectory_aggregate",
        "evidence_student_counts": evidence_counts,
        "personalization_applied": False,
        "selected_concept_ids": requested_ids,
    }, {})


def _source_summary(
    db: Session,
    actor: User,
    course_id: str,
    payload: CompileBlueprintRequest,
    requested_ids: list[str],
) -> tuple[dict[str, Any], dict[str, KnowledgeState]]:
    if payload.source_method == "history":
        return _history_summary(
            db,
            actor,
            course_id,
            requested_ids,
            personalized=payload.difficulty_mode == "personalized",
        )

    if payload.source_method == "recorded":
        recorded_count = db.scalar(
            select(func.count()).select_from(Concept).where(Concept.course_id == course_id)
        ) or 0
        return ({
            "source_method": "recorded",
            "recorded_concept_count": int(recorded_count),
            "selected_concept_count": len(requested_ids),
            "selected_concept_ids": requested_ids,
            "personalization_applied": False,
        }, {})

    if payload.source_method == "graph":
        graph = db.get(KnowledgeGraph, payload.graph_id)
        if graph is None or graph.course_id != course_id:
            raise _failure(404, "PRACTICE_GRAPH_NOT_FOUND", "知识图谱不存在于当前课程")
        if actor.role == "student":
            revision_id = graph.published_revision_id
        else:
            revision_id = graph.working_revision_id or graph.published_revision_id
        revision = db.get(GraphRevision, revision_id) if revision_id else None
        if revision is None or (actor.role == "student" and revision.status != "published"):
            raise _failure(409, "PRACTICE_GRAPH_REVISION_UNAVAILABLE", "当前图谱没有可用于出题的修订")
        nodes = list(db.scalars(select(GraphNode).where(
            GraphNode.revision_id == revision.id
        )).all())
        graph_concepts = {item.concept_id for item in nodes}
        if set(requested_ids) - graph_concepts:
            raise _failure(
                422,
                "BLUEPRINT_GRAPH_CONCEPT_OUT_OF_SCOPE",
                "蓝图知识点不属于所选图谱修订",
            )
        return ({
            "source_method": "graph",
            "graph_id": graph.id,
            "graph_revision_id": revision.id,
            "graph_node_count": len(nodes),
            "selected_concept_count": len(requested_ids),
            "selected_concept_ids": requested_ids,
            "personalization_applied": False,
        }, {})

    alignment = db.get(AlignmentRun, payload.alignment_run_id)
    if alignment is None or alignment.course_id != course_id:
        raise _failure(404, "PRACTICE_ALIGNMENT_NOT_FOUND", "材料对齐运行不存在于当前课程")
    if actor.role == "student" and alignment.actor_id != actor.id:
        raise _failure(404, "PRACTICE_ALIGNMENT_NOT_FOUND", "材料对齐运行不存在于当前课程")
    if alignment.status != "completed":
        raise _failure(409, "PRACTICE_ALIGNMENT_INCOMPLETE", "请先完成材料知识点对齐与歧义复核")
    mentions = list(db.scalars(select(AlignmentMention).where(
        AlignmentMention.run_id == alignment.id
    ).order_by(AlignmentMention.ordinal)).all())
    aligned_ids = {
        concept_id for mention in mentions
        if (concept_id := _chosen_alignment_concept(db, mention)) is not None
    }
    if set(requested_ids) - aligned_ids:
        raise _failure(
            422,
            "BLUEPRINT_ALIGNMENT_CONCEPT_OUT_OF_SCOPE",
            "蓝图知识点不属于该材料对齐结果",
        )
    return ({
        "source_method": "alignment",
        "alignment_run_id": alignment.id,
        "source_asset_id": alignment.source_asset_id,
        "mention_count": len(mentions),
        "aligned_concept_count": len(aligned_ids),
        "selected_concept_count": len(requested_ids),
        "selected_concept_ids": requested_ids,
        "personalization_applied": False,
    }, {})


def _difficulty_target(
    mode: str,
    *,
    state: KnowledgeState | None,
    position: int,
) -> float:
    if mode == "personalized":
        if state is None or state.evidence_count <= 0:
            raise _failure(
                422,
                "HISTORY_EVIDENCE_REQUIRED",
                "缺少学习证据，无法计算个性化难度",
            )
        mastery = max(0.0, min(1.0, state.mastery / 100.0))
        uncertainty = max(0.0, min(1.0, state.uncertainty))
        return round(max(0.2, min(0.8, 0.25 + 0.5 * mastery - 0.1 * uncertainty)), 4)
    if mode == "basic":
        return 0.3
    if mode == "standard":
        return 0.5
    if mode == "challenge":
        return 0.75
    return (0.3, 0.5, 0.75)[(position - 1) % 3]


def _cognitive_level(question_type: QuestionType, difficulty: float) -> str:
    if question_type in {"scenario"}:
        return "analyze"
    if question_type in {"short", "multiple"} or difficulty >= 0.7:
        return "apply"
    if question_type in {"fill", "single"}:
        return "understand"
    return "remember"


def compile_blueprint(
    db: Session,
    *,
    actor: User,
    course_id: str,
    payload: CompileBlueprintRequest,
) -> QuestionBlueprint:
    _authorize_course(db, actor, course_id)
    requested_ids = [item.concept_id for item in payload.concepts]
    _validate_course_concepts(db, course_id, requested_ids)
    source_summary, states = _source_summary(db, actor, course_id, payload, requested_ids)
    source_summary.update({
        "difficulty_mode": payload.difficulty_mode,
        "requested_concept_count": len(requested_ids),
        "total": sum(item.counts.total for item in payload.concepts),
    })
    blueprint = QuestionBlueprint(
        id=str(uuid4()),
        course_id=course_id,
        created_by=actor.id,
        owner_type=actor.role,
        source_method=payload.source_method,
        difficulty_mode=payload.difficulty_mode,
        requested_profile_id=payload.requested_profile_id,
        source_summary_json=source_summary,
        total=source_summary["total"],
        status="compiled",
        compiler_version=COMPILER_VERSION,
        version=1,
    )
    db.add(blueprint)
    db.flush()
    position = 0
    for configured in payload.concepts:
        counts = configured.counts.model_dump()
        for question_type in QUESTION_TYPES:
            count = counts[question_type]
            if count <= 0:
                continue
            position += 1
            target = _difficulty_target(
                payload.difficulty_mode,
                state=states.get(configured.concept_id),
                position=position,
            )
            db.add(BlueprintCell(
                id=str(uuid4()),
                blueprint_id=blueprint.id,
                concept_id=configured.concept_id,
                question_type=question_type,
                count=count,
                difficulty_target=target,
                cognitive_level=_cognitive_level(question_type, target),
                position=position,
            ))
    db.add(AuditEvent(
        id=str(uuid4()),
        actor_id=actor.id,
        action="practice.blueprint.compiled",
        object_type="question_blueprint",
        object_id=blueprint.id,
        course_id=course_id,
        outcome="success",
        metadata_json={
            "source_method": payload.source_method,
            "difficulty_mode": payload.difficulty_mode,
            "concept_count": len(requested_ids),
            "total": blueprint.total,
            "compiler_version": COMPILER_VERSION,
        },
    ))
    db.commit()
    return blueprint


def blueprint_cells(db: Session, blueprint_id: str) -> list[BlueprintCell]:
    return list(db.scalars(select(BlueprintCell).where(
        BlueprintCell.blueprint_id == blueprint_id
    ).order_by(BlueprintCell.position)).all())
