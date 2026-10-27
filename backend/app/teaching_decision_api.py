from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from sqlalchemy import func, select

from .dependencies import DbSession, StudentUser, TeacherUser
from .domains.teaching_decision.contracts import (
    AttentionComponents,
    AudienceCandidateView,
    AudienceDraftCreate,
    AudienceDraftView,
    ConceptLearningStateView,
    DecisionSnapshotView,
    ExposureEventCreate,
    PersonalizedJobCreate,
    PersonalizedJobView,
    PublicationCreate,
    PublicationView,
    ResourceInboxItem,
    SnapshotRefresh,
    StudentAttentionView,
    StudentLearningStateView,
    StudentListView,
)
from .domains.teaching_decision.publication import (
    create_audience_draft,
    create_personalized_job,
    get_teacher_draft,
    publish_draft,
    withdraw_publication,
)
from .domains.teaching_decision.service import (
    create_snapshot,
    latest_snapshot,
    require_enrolled_student,
    require_teacher_course,
    snapshot_students,
    student_concept_states,
)
from .domains.trajectory.service import ConceptContribution, EventCommand, TrajectoryService
from .learning_support_models import (
    AttentionScoreSnapshot,
    AudienceCandidate,
    AudienceDraft,
    DecisionSnapshot,
    DecisionPublication,
    DecisionPublicationConcept,
    PersonalizedResourceJob,
    ResourceExposure,
)
from .models import AuditEvent, CourseEnrollment, User


router = APIRouter(prefix="/api/v1", tags=["A6 教学决策与资源定向推送"])


def _components(row: AttentionScoreSnapshot) -> AttentionComponents:
    raw = row.raw_components_json
    normalized = row.normalized_components_json
    return AttentionComponents(
        practice_count=int(raw["practice_count"]),
        accuracy=float(raw["accuracy"]),
        accuracy_samples=raw.get("accuracy_samples", 0),
        resource_completion=float(raw["resource_completion"]),
        effective_tutoring_count=int(raw["effective_tutoring_count"]),
        practice_score=float(normalized["practice_score"]),
        accuracy_score=float(normalized["accuracy_score"]),
        resource_score=float(normalized["resource_score"]),
        tutoring_score=float(normalized["tutoring_score"]),
    )


def _student_attention(
    row: AttentionScoreSnapshot,
    user: User,
) -> StudentAttentionView:
    return StudentAttentionView(
        student_id=user.id, student_name=user.name, initials=user.initials,
        rank=row.rank, score=row.score, confidence=row.confidence,
        components=_components(row), last_activity_at=row.last_activity_at,
        priority=row.rank <= 3,
    )


def _snapshot_view(db: DbSession, snapshot) -> DecisionSnapshotView:
    students = snapshot_students(db, snapshot)
    priority = sorted(students, key=lambda item: item.row.rank)[:3]
    return DecisionSnapshotView(
        snapshot_id=snapshot.id, course_id=snapshot.course_id,
        as_of=snapshot.as_of, snapshot_hash=snapshot.snapshot_hash,
        student_count=snapshot.student_count, aggregate=snapshot.aggregate_json,
        algorithm_version=snapshot.algorithm_version,
        priority_students=[_student_attention(item.row, item.user) for item in priority],
        created_at=snapshot.created_at,
    )


def _draft_view(db: DbSession, draft: AudienceDraft) -> AudienceDraftView:
    rows = db.execute(
        select(AudienceCandidate, User)
        .join(User, User.id == AudienceCandidate.student_id)
        .where(AudienceCandidate.draft_id == draft.id)
        .order_by(User.name, User.id)
    ).all()
    candidates = [AudienceCandidateView(
        student_id=user.id, student_name=user.name,
        suggested=candidate.suggested, selected=candidate.selected,
        override_action=candidate.override_action,
        matched_concept_ids=candidate.matched_concept_ids_json,
        matched_states=candidate.matched_states_json,
        reason_codes=candidate.reason_codes_json,
        warnings=candidate.warnings_json,
    ) for candidate, user in rows]
    return AudienceDraftView(
        id=draft.id, course_id=draft.course_id,
        resource=draft.resource_snapshot_json,
        audience_mode=draft.audience_mode,
        selected_concept_ids=draft.selected_concept_ids_json,
        selected_states=draft.selected_states_json,
        suggested_student_ids=draft.suggested_student_ids_json,
        final_student_ids=draft.final_student_ids_json,
        candidates=candidates, status=draft.status,
        snapshot_hash=draft.snapshot_hash, version=draft.version,
        expires_at=draft.expires_at,
        warnings_require_confirmation=any(
            item.selected and bool(item.warnings_json) for item, _ in rows
        ),
    )


def _publication_view(db: DbSession, publication: DecisionPublication) -> PublicationView:
    count = int(db.scalar(select(func.count()).select_from(ResourceExposure).where(
        ResourceExposure.publication_id == publication.id
    )) or 0)
    return PublicationView(
        id=publication.id, draft_id=publication.draft_id,
        course_id=publication.course_id, resource=publication.resource_snapshot_json,
        audience_mode=publication.audience_mode, recipient_count=count,
        status=publication.status, snapshot_hash=publication.snapshot_hash,
        algorithm_version=publication.algorithm_version,
        published_at=publication.published_at,
        withdrawn_at=publication.withdrawn_at,
    )


def _inbox_item(exposure: ResourceExposure, publication: DecisionPublication) -> ResourceInboxItem:
    return ResourceInboxItem(
        exposure_id=exposure.id, publication_id=publication.id,
        course_id=exposure.course_id, resource_type=publication.resource_type,
        resource=publication.resource_snapshot_json,
        personalized=exposure.personalized,
        delivery_status=exposure.delivery_status,
        delivered_at=exposure.delivered_at, opened_at=exposure.opened_at,
        completed_at=exposure.completed_at,
    )


@router.post(
    "/courses/{course_id}/decision-snapshots:refresh",
    response_model=DecisionSnapshotView,
    status_code=status.HTTP_201_CREATED,
)
def refresh_decision_snapshot(
    course_id: str,
    payload: SnapshotRefresh,
    teacher: TeacherUser,
    db: DbSession,
) -> DecisionSnapshotView:
    snapshot = create_snapshot(
        db, teacher_id=teacher.id, course_id=course_id, as_of=payload.as_of
    )
    return _snapshot_view(db, snapshot)


@router.get(
    "/courses/{course_id}/teacher/overview",
    response_model=DecisionSnapshotView,
)
def decision_overview(
    course_id: str,
    teacher: TeacherUser,
    db: DbSession,
) -> DecisionSnapshotView:
    require_teacher_course(db, teacher.id, course_id)
    snapshot = db.scalar(
        select(DecisionSnapshot)
        .where(DecisionSnapshot.course_id == course_id)
        .order_by(DecisionSnapshot.as_of.desc(), DecisionSnapshot.created_at.desc())
    )
    if snapshot is None:
        snapshot = create_snapshot(db, teacher_id=teacher.id, course_id=course_id, as_of=None)
    return _snapshot_view(db, snapshot)


@router.get(
    "/courses/{course_id}/students",
    response_model=StudentListView,
)
def list_course_students(
    course_id: str,
    teacher: TeacherUser,
    db: DbSession,
    sort: Literal["score_desc", "score_asc", "name"] = "score_desc",
    q: str = Query(default="", max_length=80),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> StudentListView:
    require_teacher_course(db, teacher.id, course_id)
    snapshot = latest_snapshot(db, course_id)
    rows = snapshot_students(db, snapshot)
    cleaned = q.strip().lower()
    if cleaned:
        rows = [item for item in rows if cleaned in item.user.name.lower()]
    if sort == "name":
        rows.sort(key=lambda item: (item.user.name, item.user.id))
    else:
        reverse = sort == "score_desc"
        rows.sort(key=lambda item: (
            item.row.score,
            item.user.name,
            item.user.id,
        ), reverse=reverse)
    total = len(rows)
    start = (page - 1) * page_size
    selected = rows[start:start + page_size]
    return StudentListView(
        snapshot_id=snapshot.id, snapshot_hash=snapshot.snapshot_hash,
        page=page, page_size=page_size, total=total,
        items=[_student_attention(item.row, item.user) for item in selected],
    )


@router.get(
    "/courses/{course_id}/students/{student_id}/learning-state",
    response_model=StudentLearningStateView,
)
def student_learning_state(
    course_id: str,
    student_id: str,
    teacher: TeacherUser,
    db: DbSession,
) -> StudentLearningStateView:
    require_teacher_course(db, teacher.id, course_id)
    student, _ = require_enrolled_student(
        db, course_id=course_id, student_id=student_id
    )
    snapshot = latest_snapshot(db, course_id)
    row = db.scalar(select(AttentionScoreSnapshot).where(
        AttentionScoreSnapshot.snapshot_id == snapshot.id,
        AttentionScoreSnapshot.student_id == student_id,
    ))
    if row is None:
        raise HTTPException(status_code=409, detail="该学生不在当前快照中，请刷新快照")
    concept_rows = student_concept_states(
        db, student_id=student_id, course_id=course_id, limit=10
    )
    concepts = [ConceptLearningStateView(**item) for item in concept_rows]
    return StudentLearningStateView(
        snapshot_id=snapshot.id, course_id=course_id,
        student_id=student.id, student_name=student.name,
        rank=row.rank, score=row.score, confidence=row.confidence,
        components=_components(row), concepts=concepts,
        weak_concept_ids=[item.concept_id for item in concepts if item.state == "weak"],
        privacy_boundary="仅返回课程内学习状态与聚合证据，不返回辅导对话、个人记忆或教学经验正文。",
    )


@router.post(
    "/teacher/courses/{course_id}/resources/{resource_id}/audience-drafts",
    response_model=AudienceDraftView,
    status_code=status.HTTP_201_CREATED,
)
def preview_audience(
    course_id: str,
    resource_id: str,
    payload: AudienceDraftCreate,
    teacher: TeacherUser,
    db: DbSession,
) -> AudienceDraftView:
    if payload.resource_id != resource_id:
        raise HTTPException(status_code=422, detail="路径资源ID与请求体不一致")
    draft = create_audience_draft(
        db, teacher_id=teacher.id, course_id=course_id, payload=payload
    )
    return _draft_view(db, draft)


@router.get(
    "/audience-drafts/{draft_id}",
    response_model=AudienceDraftView,
)
def get_audience_draft(
    draft_id: str,
    teacher: TeacherUser,
    db: DbSession,
) -> AudienceDraftView:
    draft = get_teacher_draft(db, teacher_id=teacher.id, draft_id=draft_id)
    require_teacher_course(db, teacher.id, draft.course_id)
    return _draft_view(db, draft)


@router.post(
    "/audience-drafts/{draft_id}/publications",
    response_model=PublicationView,
    status_code=status.HTTP_201_CREATED,
)
def create_publication(
    draft_id: str,
    payload: PublicationCreate,
    teacher: TeacherUser,
    db: DbSession,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=160),
) -> PublicationView:
    publication, _duplicate = publish_draft(
        db, teacher_id=teacher.id, draft_id=draft_id,
        idempotency_key=idempotency_key, payload=payload,
    )
    return _publication_view(db, publication)


@router.get(
    "/publications/{publication_id}",
    response_model=PublicationView,
)
def get_publication(
    publication_id: str,
    teacher: TeacherUser,
    db: DbSession,
) -> PublicationView:
    publication = db.scalar(select(DecisionPublication).where(
        DecisionPublication.id == publication_id,
        DecisionPublication.teacher_id == teacher.id,
    ))
    if publication is None:
        raise HTTPException(status_code=404, detail="发布记录不存在或无权访问")
    require_teacher_course(db, teacher.id, publication.course_id)
    return _publication_view(db, publication)


@router.post(
    "/publications/{publication_id}:withdraw",
    response_model=PublicationView,
)
def withdraw(
    publication_id: str,
    teacher: TeacherUser,
    db: DbSession,
) -> PublicationView:
    publication = withdraw_publication(
        db, teacher_id=teacher.id, publication_id=publication_id
    )
    return _publication_view(db, publication)


@router.get(
    "/student/courses/{course_id}/resource-inbox",
    response_model=list[ResourceInboxItem],
)
def resource_inbox(
    course_id: str,
    student: StudentUser,
    db: DbSession,
    include_completed: bool = True,
) -> list[ResourceInboxItem]:
    require_enrolled_student(db, course_id=course_id, student_id=student.id)
    statement = (
        select(ResourceExposure, DecisionPublication)
        .join(DecisionPublication, DecisionPublication.id == ResourceExposure.publication_id)
        .where(
            ResourceExposure.student_id == student.id,
            ResourceExposure.course_id == course_id,
            ResourceExposure.withdrawn_at.is_(None),
            DecisionPublication.status == "published",
        )
    )
    if not include_completed:
        statement = statement.where(ResourceExposure.completed_at.is_(None))
    rows = db.execute(statement.order_by(ResourceExposure.delivered_at.desc())).all()
    return [_inbox_item(item[0], item[1]) for item in rows]


def _record_exposure_event(
    db: DbSession,
    *,
    student: User,
    exposure_id: str,
    payload: ExposureEventCreate,
    action: Literal["open", "complete"],
) -> ResourceInboxItem:
    row = db.execute(
        select(ResourceExposure, DecisionPublication)
        .join(DecisionPublication, DecisionPublication.id == ResourceExposure.publication_id)
        .where(
            ResourceExposure.id == exposure_id,
            ResourceExposure.student_id == student.id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="资源收件记录不存在或无权访问")
    exposure, publication = row
    require_enrolled_student(db, course_id=exposure.course_id, student_id=student.id)
    if publication.status != "published" or exposure.withdrawn_at is not None:
        raise HTTPException(status_code=410, detail="该资源已撤回")
    existing_event_id = (
        exposure.open_event_id if action == "open" else exposure.completion_event_id
    )
    if existing_event_id is not None:
        return _inbox_item(exposure, publication)
    concept_ids = list(db.scalars(select(DecisionPublicationConcept.concept_id).where(
        DecisionPublicationConcept.publication_id == publication.id
    )).all())
    if not concept_ids:
        raise HTTPException(status_code=409, detail="发布快照缺少知识点，无法记录学习事件")
    if action == "open":
        exposure.opened_at = payload.occurred_at
        exposure.delivery_status = "opened"
        event_type = "resource_opened"
        completion = None
    else:
        if exposure.opened_at is None:
            exposure.opened_at = payload.occurred_at
        exposure.completed_at = payload.occurred_at
        exposure.delivery_status = "completed"
        event_type = "resource_completed"
        completion = 1.0
    result = TrajectoryService(db).ingest(
        student=student,
        course_id=exposure.course_id,
        command=EventCommand(
            idempotency_key=f"exposure:{exposure.id}:{action}:{payload.idempotency_key}",
            event_type=event_type,
            object_type="decision_publication",
            object_id=publication.id,
            concepts=[ConceptContribution(item, 1.0) for item in concept_ids],
            outcome=None, difficulty=None, hint_level=None, attempt_no=None,
            completion=completion, strategy=None,
            upstream_confidence=1.0, alignment_confidence=1.0,
            occurred_at=payload.occurred_at, correction_of_event_id=None,
            payload={
                "exposure_id": exposure.id,
                "resource_type": publication.resource_type,
                "personalized": exposure.personalized,
            },
        ),
    )
    if action == "open":
        exposure.open_event_id = result.event_id
    else:
        exposure.completion_event_id = result.event_id
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=student.id,
        action=f"resource.exposure.{action}", object_type="resource_exposure",
        object_id=exposure.id, course_id=exposure.course_id, outcome="success",
        metadata_json={
            "publication_id": publication.id,
            "trajectory_event_id": result.event_id,
        },
    ))
    db.commit()
    return _inbox_item(exposure, publication)


@router.post(
    "/student/resource-inbox/{exposure_id}:open",
    response_model=ResourceInboxItem,
)
def open_resource(
    exposure_id: str,
    payload: ExposureEventCreate,
    student: StudentUser,
    db: DbSession,
) -> ResourceInboxItem:
    return _record_exposure_event(
        db, student=student, exposure_id=exposure_id, payload=payload, action="open"
    )


@router.post(
    "/student/resource-inbox/{exposure_id}:complete",
    response_model=ResourceInboxItem,
)
def complete_resource(
    exposure_id: str,
    payload: ExposureEventCreate,
    student: StudentUser,
    db: DbSession,
) -> ResourceInboxItem:
    return _record_exposure_event(
        db, student=student, exposure_id=exposure_id, payload=payload, action="complete"
    )


def _job_view(job: PersonalizedResourceJob) -> PersonalizedJobView:
    return PersonalizedJobView(
        id=job.id, student_id=job.student_id, course_id=job.course_id,
        resource_type=job.resource_type, concept_ids=job.concept_ids_json,
        upstream_job_id=job.upstream_job_id,
        upstream_status=job.upstream_status_json, status=job.status,
        created_at=job.created_at, updated_at=job.updated_at,
    )


@router.post(
    "/courses/{course_id}/students/{student_id}/personalized-resource-jobs",
    response_model=PersonalizedJobView,
    status_code=status.HTTP_201_CREATED,
)
def start_personalized_resource_job(
    course_id: str,
    student_id: str,
    payload: PersonalizedJobCreate,
    request: Request,
    teacher: TeacherUser,
    db: DbSession,
) -> PersonalizedJobView:
    handlers = getattr(request.app.state, "personalized_resource_handlers", {})
    job, _duplicate = create_personalized_job(
        db, teacher_id=teacher.id, course_id=course_id,
        student_id=student_id, payload=payload, handlers=handlers,
    )
    return _job_view(job)


@router.get(
    "/personalized-resource-jobs/{job_id}",
    response_model=PersonalizedJobView,
)
def get_personalized_resource_job(
    job_id: str,
    teacher: TeacherUser,
    db: DbSession,
) -> PersonalizedJobView:
    job = db.scalar(select(PersonalizedResourceJob).where(
        PersonalizedResourceJob.id == job_id,
        PersonalizedResourceJob.teacher_id == teacher.id,
    ))
    if job is None:
        raise HTTPException(status_code=404, detail="个性化资源任务不存在或无权访问")
    require_teacher_course(db, teacher.id, job.course_id)
    return _job_view(job)
