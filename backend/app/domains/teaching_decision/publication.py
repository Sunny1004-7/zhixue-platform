from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...learning_support_models import (
    AudienceCandidate,
    AudienceDraft,
    DecisionPublication,
    DecisionPublicationConcept,
    DecisionPublicationRecipient,
    PersonalizedResourceJob,
    ResourceExposure,
)
from ...models import AuditEvent, Concept, CourseEnrollment, KnowledgeState, User
from .audience import StudentConceptState, classify_state, resolve_audience
from .contracts import AudienceDraftCreate, PersonalizedJobCreate, PublicationCreate
from .manifests import ResourceManifest, resolve_manifest
from .service import latest_snapshot, require_enrolled_student, require_teacher_course
from .snapshots import stable_snapshot_hash


PUBLICATION_ALGORITHM_VERSION = "tides-publication-1.0.0"
PersonalizedHandler = Callable[..., dict[str, Any]]


def _enrolled_students(db: Session, course_id: str) -> list[User]:
    return list(db.scalars(
        select(User)
        .join(CourseEnrollment, CourseEnrollment.student_id == User.id)
        .where(
            CourseEnrollment.course_id == course_id,
            User.role == "student",
            User.active.is_(True),
        )
        .order_by(User.id)
    ).all())


def _state_rows(
    db: Session,
    *,
    course_id: str,
    student_ids: list[str],
    concept_ids: list[str],
) -> list[StudentConceptState]:
    rows = list(db.scalars(select(KnowledgeState).where(
        KnowledgeState.course_id == course_id,
        KnowledgeState.student_id.in_(student_ids),
        KnowledgeState.concept_id.in_(concept_ids),
    )).all())
    by_key = {(item.student_id, item.concept_id): item for item in rows}
    result: list[StudentConceptState] = []
    for student_id in student_ids:
        for concept_id in concept_ids:
            state = by_key.get((student_id, concept_id))
            result.append(StudentConceptState(
                student_id=student_id,
                course_id=course_id,
                concept_id=concept_id,
                mastery=float(state.mastery) if state else 50.0,
                evidence_count=state.evidence_count if state else 0,
                confidence=float(state.confidence) if state else 0.0,
                effective_evidence=float(state.effective_evidence) if state else 0.0,
                uncertainty=float(state.uncertainty) if state else 1.0,
            ))
    return result


def _recent_warnings(
    db: Session,
    *,
    student_id: str,
    manifest: ResourceManifest,
) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=14)
    rows = db.execute(
        select(ResourceExposure, DecisionPublication)
        .join(DecisionPublication, DecisionPublication.id == ResourceExposure.publication_id)
        .where(
            ResourceExposure.student_id == student_id,
            ResourceExposure.course_id == manifest.course_id,
            ResourceExposure.delivered_at >= since,
            ResourceExposure.withdrawn_at.is_(None),
            DecisionPublication.status == "published",
        )
    ).all()
    warnings: list[dict[str, Any]] = []
    same_type_overlap = 0
    target_concepts = set(manifest.concept_ids)
    for exposure, publication in rows:
        concepts = set(db.scalars(select(DecisionPublicationConcept.concept_id).where(
            DecisionPublicationConcept.publication_id == publication.id
        )).all())
        if publication.resource_type == manifest.resource_type and concepts & target_concepts:
            same_type_overlap += 1
        if publication.resource_type == manifest.resource_type and publication.resource_id == manifest.resource_id:
            warnings.append({
                "code": "DUPLICATE_RESOURCE_RECENT",
                "publication_id": publication.id,
                "delivered_at": exposure.delivered_at.isoformat(),
            })
    if same_type_overlap >= 3:
        warnings.append({
            "code": "FREQUENCY_LIMIT",
            "recent_similar_count": same_type_overlap,
            "window_days": 14,
        })
    return warnings


def create_audience_draft(
    db: Session,
    *,
    teacher_id: str,
    course_id: str,
    payload: AudienceDraftCreate,
) -> AudienceDraft:
    require_teacher_course(db, teacher_id, course_id)
    state_snapshot = latest_snapshot(db, course_id)
    manifest = resolve_manifest(
        db, resource_type=payload.resource_type, resource_id=payload.resource_id,
        course_id=course_id, requested_version=payload.resource_version,
    )
    actual_concepts = set(manifest.concept_ids)
    selected_concepts = (
        list(payload.selected_concept_ids)
        if payload.selected_concept_ids else list(manifest.concept_ids)
    )
    if not set(selected_concepts).issubset(actual_concepts):
        raise HTTPException(status_code=422, detail={
            "code": "COURSE_SCOPE_MISMATCH",
            "message": "所选知识点不属于当前资源实际覆盖集",
        })
    students = _enrolled_students(db, course_id)
    student_ids = [item.id for item in students]
    if not students:
        raise HTTPException(status_code=422, detail="当前课程没有在籍学生")
    states = _state_rows(
        db, course_id=course_id, student_ids=student_ids,
        concept_ids=selected_concepts,
    )
    state_by_student: dict[str, list[StudentConceptState]] = {}
    for item in states:
        state_by_student.setdefault(item.student_id, []).append(item)
    matched: dict[str, dict[str, Any]] = {}
    if payload.audience_mode == "class":
        suggested_ids = student_ids
        final_ids = student_ids
        candidate_students = students
    elif payload.audience_mode == "single":
        locked_id = payload.locked_student_id or ""
        require_enrolled_student(db, course_id=course_id, student_id=locked_id)
        suggested_ids = [locked_id]
        final_ids = [locked_id]
        candidate_students = [item for item in students if item.id == locked_id]
    else:
        matches = resolve_audience(
            states,
            course_id=course_id,
            resource_concept_ids=selected_concepts,
            selected_states=set(payload.selected_states),
        )
        for item in matches:
            matched[item.student_id] = {
                "concept_ids": list(item.matched_concepts),
                "states": list(item.matched_states),
                "low_evidence": item.low_evidence,
            }
        suggested_ids = [item.student_id for item in matches]
        explicitly_selected = "teacher_selected_student_ids" in payload.model_fields_set
        final_ids = (
            list(payload.teacher_selected_student_ids)
            if explicitly_selected else list(suggested_ids)
        )
        invalid_students = set(final_ids) - set(student_ids)
        if invalid_students:
            raise HTTPException(status_code=422, detail={
                "code": "COURSE_SCOPE_MISMATCH",
                "message": "接收者包含其他课程学生",
            })
        candidate_students = students
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=30)
    resource_snapshot = dict(manifest.snapshot)
    resource_snapshot["decision_snapshot_id"] = state_snapshot.id
    resource_snapshot["decision_snapshot_hash"] = state_snapshot.snapshot_hash
    draft_payload = {
        "course_id": course_id,
        "teacher_id": teacher_id,
        "resource_hash": manifest.content_hash,
        "decision_snapshot_id": state_snapshot.id,
        "audience_mode": payload.audience_mode,
        "selected_concept_ids": selected_concepts,
        "selected_states": list(payload.selected_states),
        "suggested_student_ids": suggested_ids,
        "final_student_ids": final_ids,
        "expires_at": expires_at.isoformat(),
        "algorithm_version": PUBLICATION_ALGORITHM_VERSION,
    }
    draft = AudienceDraft(
        id=str(uuid4()), course_id=course_id, teacher_id=teacher_id,
        resource_type=manifest.resource_type, resource_id=manifest.resource_id,
        resource_version=manifest.version, resource_hash=manifest.content_hash,
        resource_snapshot_json=resource_snapshot,
        audience_mode=payload.audience_mode,
        selected_concept_ids_json=selected_concepts,
        selected_states_json=list(payload.selected_states),
        teacher_selected_student_ids_json=list(payload.teacher_selected_student_ids),
        suggested_student_ids_json=suggested_ids,
        final_student_ids_json=final_ids,
        status="previewed", snapshot_hash=stable_snapshot_hash(draft_payload),
        version=1, expires_at=expires_at,
    )
    db.add(draft)
    db.flush()
    suggested = set(suggested_ids)
    selected = set(final_ids)
    for student in candidate_students:
        detail = matched.get(student.id)
        if detail is None:
            student_states = state_by_student.get(student.id, [])
            detail = {
                "concept_ids": [item.concept_id for item in student_states],
                "states": [classify_state(item) for item in student_states],
                "low_evidence": any(
                    classify_state(item) == "unseen" or item.evidence_count <= 1 or item.confidence < 0.45
                    for item in student_states
                ),
            }
        is_suggested = student.id in suggested
        is_selected = student.id in selected
        if is_selected and not is_suggested:
            override = "added"
        elif is_suggested and not is_selected:
            override = "removed"
        else:
            override = None
        reason_codes = [
            "CLASS_AUDIENCE" if payload.audience_mode == "class" else
            "LOCKED_STUDENT" if payload.audience_mode == "single" else
            "CONCEPT_STATE_OR_MATCH"
        ]
        if detail["low_evidence"]:
            reason_codes.append("LOW_EVIDENCE")
        warnings = _recent_warnings(
            db, student_id=student.id, manifest=manifest
        ) if is_selected else []
        db.add(AudienceCandidate(
            id=str(uuid4()), draft_id=draft.id, student_id=student.id,
            suggested=is_suggested, selected=is_selected,
            override_action=override,
            matched_concept_ids_json=detail["concept_ids"],
            matched_states_json=detail["states"],
            reason_codes_json=reason_codes,
            warnings_json=warnings,
        ))
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=teacher_id, action="audience.draft.previewed",
        object_type="audience_draft", object_id=draft.id, course_id=course_id,
        outcome="success", metadata_json={
            "resource_type": manifest.resource_type,
            "resource_id": manifest.resource_id,
            "audience_mode": payload.audience_mode,
            "suggested_count": len(suggested_ids),
            "final_count": len(final_ids),
            "decision_snapshot_id": state_snapshot.id,
        },
    ))
    db.commit()
    return draft


def get_teacher_draft(
    db: Session,
    *,
    teacher_id: str,
    draft_id: str,
) -> AudienceDraft:
    draft = db.scalar(select(AudienceDraft).where(
        AudienceDraft.id == draft_id,
        AudienceDraft.teacher_id == teacher_id,
    ))
    if draft is None:
        raise HTTPException(status_code=404, detail="接收者草稿不存在或无权访问")
    return draft


def publish_draft(
    db: Session,
    *,
    teacher_id: str,
    draft_id: str,
    idempotency_key: str,
    payload: PublicationCreate,
) -> tuple[DecisionPublication, bool]:
    draft = get_teacher_draft(db, teacher_id=teacher_id, draft_id=draft_id)
    require_teacher_course(db, teacher_id, draft.course_id)
    existing = db.scalar(select(DecisionPublication).where(
        DecisionPublication.teacher_id == teacher_id,
        DecisionPublication.course_id == draft.course_id,
        DecisionPublication.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        if existing.draft_id != draft.id:
            raise HTTPException(status_code=409, detail="同一发布幂等键已用于其他草稿")
        return existing, True
    now = datetime.now(timezone.utc)
    expires_at = draft.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if draft.status != "previewed" or expires_at <= now:
        raise HTTPException(status_code=409, detail="接收者草稿已失效，请重新预览")
    if draft.version != payload.draft_version:
        raise HTTPException(status_code=409, detail={
            "code": "DRAFT_VERSION_CONFLICT",
            "message": "草稿版本已更新，请刷新后重试",
        })
    manifest = resolve_manifest(
        db, resource_type=draft.resource_type, resource_id=draft.resource_id,
        course_id=draft.course_id, requested_version=draft.resource_version,
    )
    if manifest.content_hash != draft.resource_hash:
        raise HTTPException(status_code=409, detail={
            "code": "MANIFEST_VERSION_CHANGED",
            "message": "资源内容已更新，请重新预览接收者",
        })
    final_ids = list(draft.final_student_ids_json)
    if not final_ids:
        raise HTTPException(status_code=422, detail={
            "code": "EMPTY_AUDIENCE", "message": "最终接收者不能为空",
        })
    valid_students = set(db.scalars(select(CourseEnrollment.student_id).where(
        CourseEnrollment.course_id == draft.course_id,
        CourseEnrollment.student_id.in_(final_ids),
    )).all())
    if len(valid_students) != len(set(final_ids)):
        raise HTTPException(status_code=409, detail={
            "code": "COURSE_SCOPE_MISMATCH",
            "message": "接收者课程关系已变化，请重新预览",
        })
    candidates = list(db.scalars(select(AudienceCandidate).where(
        AudienceCandidate.draft_id == draft.id,
        AudienceCandidate.selected.is_(True),
    )).all())
    if any(item.warnings_json for item in candidates) and not payload.acknowledge_warnings:
        raise HTTPException(status_code=409, detail={
            "code": "FREQUENCY_WARNING_REQUIRES_CONFIRMATION",
            "message": "存在重复或频控警告，需要教师明确确认",
        })
    published_at = now
    snapshot_payload = {
        "draft_snapshot_hash": draft.snapshot_hash,
        "resource_hash": draft.resource_hash,
        "recipient_ids": sorted(final_ids),
        "concept_ids": list(draft.selected_concept_ids_json),
        "published_at": published_at.isoformat(),
        "algorithm_version": PUBLICATION_ALGORITHM_VERSION,
    }
    publication = DecisionPublication(
        id=str(uuid4()), draft_id=draft.id, course_id=draft.course_id,
        teacher_id=teacher_id, resource_type=draft.resource_type,
        resource_id=draft.resource_id, resource_version=draft.resource_version,
        resource_hash=draft.resource_hash,
        resource_snapshot_json=draft.resource_snapshot_json,
        audience_mode=draft.audience_mode, idempotency_key=idempotency_key,
        status="published", snapshot_hash=stable_snapshot_hash(snapshot_payload),
        algorithm_version=PUBLICATION_ALGORITHM_VERSION,
        published_at=published_at,
    )
    db.add(publication)
    db.flush()
    for concept_id in draft.selected_concept_ids_json:
        db.add(DecisionPublicationConcept(
            id=str(uuid4()), publication_id=publication.id, concept_id=concept_id,
        ))
    candidate_by_student = {item.student_id: item for item in candidates}
    for student_id in final_ids:
        candidate = candidate_by_student[student_id]
        db.add(DecisionPublicationRecipient(
            id=str(uuid4()), publication_id=publication.id, student_id=student_id,
            suggested=candidate.suggested, override_action=candidate.override_action,
            matched_concept_ids_json=candidate.matched_concept_ids_json,
            matched_states_json=candidate.matched_states_json,
            reason_codes_json=candidate.reason_codes_json,
        ))
        db.add(ResourceExposure(
            id=str(uuid4()), publication_id=publication.id, student_id=student_id,
            course_id=draft.course_id, delivery_status="delivered",
            personalized=draft.audience_mode != "class", delivered_at=published_at,
        ))
    draft.status = "published"
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=teacher_id, action="resource.publication.published",
        object_type="decision_publication", object_id=publication.id,
        course_id=draft.course_id, outcome="success",
        metadata_json={
            "resource_type": draft.resource_type,
            "resource_id": draft.resource_id,
            "recipient_count": len(final_ids),
            "audience_mode": draft.audience_mode,
            "warning_acknowledged": payload.acknowledge_warnings,
        },
    ))
    db.commit()
    return publication, False


def withdraw_publication(
    db: Session,
    *,
    teacher_id: str,
    publication_id: str,
) -> DecisionPublication:
    publication = db.scalar(select(DecisionPublication).where(
        DecisionPublication.id == publication_id,
        DecisionPublication.teacher_id == teacher_id,
    ).with_for_update())
    if publication is None:
        raise HTTPException(status_code=404, detail="发布记录不存在或无权访问")
    require_teacher_course(db, teacher_id, publication.course_id)
    if publication.status == "withdrawn":
        return publication
    now = datetime.now(timezone.utc)
    publication.status = "withdrawn"
    publication.withdrawn_at = now
    exposures = list(db.scalars(select(ResourceExposure).where(
        ResourceExposure.publication_id == publication.id
    )).all())
    for item in exposures:
        item.delivery_status = "withdrawn"
        item.withdrawn_at = now
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=teacher_id, action="resource.publication.withdrawn",
        object_type="decision_publication", object_id=publication.id,
        course_id=publication.course_id, outcome="success",
        metadata_json={"recipient_count": len(exposures)},
    ))
    db.commit()
    return publication


def create_personalized_job(
    db: Session,
    *,
    teacher_id: str,
    course_id: str,
    student_id: str,
    payload: PersonalizedJobCreate,
    handlers: dict[str, PersonalizedHandler],
) -> tuple[PersonalizedResourceJob, bool]:
    require_teacher_course(db, teacher_id, course_id)
    require_enrolled_student(db, course_id=course_id, student_id=student_id)
    concepts = set(db.scalars(select(Concept.id).where(
        Concept.course_id == course_id,
        Concept.id.in_(payload.concept_ids),
    )).all())
    if len(concepts) != len(payload.concept_ids):
        raise HTTPException(status_code=422, detail="知识点不存在或不属于当前课程")
    request_hash = stable_snapshot_hash({
        "student_id": student_id,
        "course_id": course_id,
        **payload.model_dump(mode="json"),
    })
    existing = db.scalar(select(PersonalizedResourceJob).where(
        PersonalizedResourceJob.teacher_id == teacher_id,
        PersonalizedResourceJob.course_id == course_id,
        PersonalizedResourceJob.idempotency_key == payload.idempotency_key,
    ))
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="同一任务幂等键已用于不同输入")
        return existing, True
    handler = handlers.get(payload.resource_type)
    if handler is None:
        raise HTTPException(status_code=503, detail={
            "code": "UPSTREAM_RESOURCE_HANDLER_UNAVAILABLE",
            "message": "当前部署尚未接入该资源类型的生成服务",
        })
    try:
        upstream = handler(
            db=db,
            teacher_id=teacher_id,
            student_id=student_id,
            course_id=course_id,
            concept_ids=list(payload.concept_ids),
            request_payload=payload.request_payload,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail={
            "code": "UPSTREAM_RESOURCE_JOB_FAILED",
            "message": f"资源任务创建失败：{str(error)[:240]}",
        }) from error
    upstream_job_id = str(upstream.get("job_id") or "")
    upstream_status = str(upstream.get("status") or "")
    if not upstream_job_id or upstream_status not in {
        "created", "queued", "running", "awaiting_review", "completed"
    }:
        raise HTTPException(status_code=502, detail="上游资源服务返回了无效任务契约")
    job = PersonalizedResourceJob(
        id=str(uuid4()), teacher_id=teacher_id, student_id=student_id,
        course_id=course_id, resource_type=payload.resource_type,
        concept_ids_json=list(payload.concept_ids),
        idempotency_key=payload.idempotency_key, request_hash=request_hash,
        upstream_job_id=upstream_job_id,
        upstream_status_json=dict(upstream), status=upstream_status,
    )
    db.add(job)
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=teacher_id, action="personalized.resource_job.created",
        object_type="personalized_resource_job", object_id=job.id,
        course_id=course_id, outcome="success",
        metadata_json={
            "student_id": student_id,
            "resource_type": payload.resource_type,
            "concept_count": len(payload.concept_ids),
            "upstream_job_id": upstream_job_id,
        },
    ))
    db.commit()
    return job, False
