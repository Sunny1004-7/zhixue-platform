from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    Concept,
    GraphNode,
    GraphQualityReport,
    GraphRevision,
    KnowledgeGraph,
    QuestionConcept,
    QuestionQualityReport,
    QuestionSet,
)
from ...video_models import VideoCandidateConcept, VideoCandidateRecord
from .snapshots import stable_snapshot_hash


@dataclass(frozen=True)
class ResourceManifest:
    resource_type: str
    resource_id: str
    course_id: str
    version: int
    title: str
    concept_ids: tuple[str, ...]
    content_hash: str
    snapshot: dict[str, Any]


def _verify_concepts(db: Session, course_id: str, concept_ids: list[str]) -> tuple[str, ...]:
    ordered = tuple(dict.fromkeys(concept_ids))
    if not ordered:
        raise HTTPException(status_code=422, detail={
            "code": "NO_ALIGNED_CONCEPT",
            "message": "资源没有可发布的规范知识点",
        })
    valid = set(db.scalars(select(Concept.id).where(
        Concept.course_id == course_id,
        Concept.id.in_(ordered),
    )).all())
    if len(valid) != len(ordered):
        raise HTTPException(status_code=422, detail={
            "code": "COURSE_SCOPE_MISMATCH",
            "message": "资源包含其他课程知识点",
        })
    return ordered


def _graph_manifest(db: Session, resource_id: str, course_id: str) -> ResourceManifest:
    graph = db.scalar(select(KnowledgeGraph).where(
        KnowledgeGraph.id == resource_id,
        KnowledgeGraph.course_id == course_id,
    ))
    if graph is None:
        raise HTTPException(status_code=404, detail="知识图谱不存在或不属于当前课程")
    if graph.status != "published" or graph.published_revision_id is None:
        raise HTTPException(status_code=409, detail={
            "code": "RESOURCE_NOT_APPROVED", "message": "知识图谱尚未发布",
        })
    revision = db.get(GraphRevision, graph.published_revision_id)
    report = db.scalar(select(GraphQualityReport).where(
        GraphQualityReport.revision_id == graph.published_revision_id,
        GraphQualityReport.hard_pass.is_(True),
    ).order_by(GraphQualityReport.created_at.desc()))
    if revision is None or revision.status != "published" or report is None:
        raise HTTPException(status_code=409, detail={
            "code": "RESOURCE_NOT_APPROVED", "message": "知识图谱未通过发布质量门",
        })
    concept_ids = _verify_concepts(db, course_id, list(db.scalars(
        select(GraphNode.concept_id)
        .where(GraphNode.revision_id == revision.id)
        .order_by(GraphNode.concept_id)
    ).all()))
    snapshot = {
        "resource_type": "graph", "resource_id": graph.id,
        "title": graph.title, "revision_id": revision.id,
        "version": revision.revision_no, "concept_ids": list(concept_ids),
        "quality_report_id": report.id,
    }
    return ResourceManifest(
        "graph", graph.id, course_id, revision.revision_no,
        graph.title, concept_ids, stable_snapshot_hash(snapshot), snapshot,
    )


def _question_set_manifest(
    db: Session,
    resource_id: str,
    course_id: str,
) -> ResourceManifest:
    question_set = db.scalar(select(QuestionSet).where(
        QuestionSet.id == resource_id,
        QuestionSet.course_id == course_id,
    ))
    if question_set is None:
        raise HTTPException(status_code=404, detail="题组不存在或不属于当前课程")
    if question_set.status != "published" or question_set.published_revision_id is None:
        raise HTTPException(status_code=409, detail={
            "code": "RESOURCE_NOT_APPROVED", "message": "题组尚未发布",
        })
    report = db.scalar(select(QuestionQualityReport).where(
        QuestionQualityReport.revision_id == question_set.published_revision_id,
        QuestionQualityReport.hard_pass.is_(True),
    ).order_by(QuestionQualityReport.created_at.desc()))
    if report is None:
        raise HTTPException(status_code=409, detail={
            "code": "RESOURCE_NOT_APPROVED", "message": "题组未通过发布质量门",
        })
    from ...models import Question

    concept_ids = _verify_concepts(db, course_id, list(db.scalars(
        select(QuestionConcept.concept_id)
        .join(Question, Question.id == QuestionConcept.question_id)
        .where(Question.revision_id == question_set.published_revision_id)
        .order_by(QuestionConcept.concept_id)
    ).all()))
    from ...models import QuestionSetRevision

    revision = db.get(QuestionSetRevision, question_set.published_revision_id)
    if revision is None or revision.status != "published":
        raise HTTPException(status_code=409, detail={
            "code": "RESOURCE_NOT_APPROVED", "message": "题组修订状态不可发布",
        })
    snapshot = {
        "resource_type": "question_set", "resource_id": question_set.id,
        "title": question_set.title, "revision_id": revision.id,
        "version": revision.revision_no, "concept_ids": list(concept_ids),
        "quality_report_id": report.id,
    }
    return ResourceManifest(
        "question_set", question_set.id, course_id, revision.revision_no,
        question_set.title, concept_ids, stable_snapshot_hash(snapshot), snapshot,
    )


def _video_manifest(db: Session, resource_id: str, course_id: str) -> ResourceManifest:
    candidate = db.scalar(select(VideoCandidateRecord).where(
        VideoCandidateRecord.id == resource_id,
        VideoCandidateRecord.course_id == course_id,
    ))
    if candidate is None:
        raise HTTPException(status_code=404, detail="视频候选不存在或不属于当前课程")
    verified_statuses = {"verified", "passed", "metadata_verified"}
    active_statuses = {"ranked", "approved", "active", "published"}
    expires_at = candidate.verification_expires_at
    if (
        candidate.verification_status not in verified_statuses
        or candidate.lifecycle_status not in active_statuses
        or (expires_at is not None and _as_utc(expires_at) <= datetime.now(timezone.utc))
    ):
        raise HTTPException(status_code=409, detail={
            "code": "RESOURCE_NOT_APPROVED", "message": "视频核验状态已失效或不可发布",
        })
    concept_ids = _verify_concepts(db, course_id, list(db.scalars(
        select(VideoCandidateConcept.concept_id)
        .where(VideoCandidateConcept.candidate_id == candidate.id)
        .order_by(VideoCandidateConcept.concept_id)
    ).all()))
    snapshot = {
        "resource_type": "video", "resource_id": candidate.id,
        "title": candidate.title, "version": 1,
        "concept_ids": list(concept_ids),
        "url": candidate.canonical_url,
        "provider": candidate.provider,
        "creator": candidate.creator,
        "license_name": candidate.license_name,
        "license_url": candidate.license_url,
        "verified_at": _as_utc(candidate.verified_at).isoformat(),
        "verification_expires_at": _as_utc(expires_at).isoformat() if expires_at else None,
        "critical_metadata_hash": candidate.critical_metadata_hash,
    }
    return ResourceManifest(
        "video", candidate.id, course_id, 1, candidate.title,
        concept_ids, stable_snapshot_hash(snapshot), snapshot,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resolve_manifest(
    db: Session,
    *,
    resource_type: str,
    resource_id: str,
    course_id: str,
    requested_version: int | None = None,
) -> ResourceManifest:
    resolver = {
        "graph": _graph_manifest,
        "question_set": _question_set_manifest,
        "video": _video_manifest,
    }.get(resource_type)
    if resolver is None:
        raise HTTPException(status_code=422, detail="不支持的资源类型")
    manifest = resolver(db, resource_id, course_id)
    if requested_version is not None and requested_version != manifest.version:
        raise HTTPException(status_code=409, detail={
            "code": "MANIFEST_VERSION_CHANGED",
            "message": "资源版本已更新，请重新预览接收者",
            "actual_version": manifest.version,
        })
    return manifest
