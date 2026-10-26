from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, or_, select

from .config import Settings
from .dependencies import (
    CurrentUser,
    DbSession,
    StudentUser,
    TeacherUser,
    current_session_and_user,
)
from .domains.trajectory.service import TrajectoryService
from .domains.trajectory.evidence import classify_state
from .domains.trajectory.client_events import client_observation_command
from .domains.model_gateway.profile_catalog import resolve_profile
from .domains.teaching_decision.service import create_snapshot
from .learning_support_models import DecisionSnapshot
from .models import (
    AuditEvent,
    AuthSession,
    CourseEnrollment,
    LearningEvent,
    LearningResource,
    MasteryEvidence,
    ModelProfile,
    User,
)
from .repositories import CourseRepository
from .schemas import (
    ActivityView,
    AuthResponse,
    CourseListItem,
    CrossCourseSummary,
    KnowledgeStateView,
    LearningEventCreate,
    LoginRequest,
    ModelProfileView,
    ResourceView,
    StudentCourseOverview,
    TeacherCourseOverview,
    TrajectoryUpdateResponse,
    TrendMetric,
    UserView,
)
from .security import create_session_token, hash_token, verify_password


router = APIRouter(prefix="/api/v1")


def audit(
    db: DbSession,
    *,
    actor_id: str | None,
    action: str,
    object_type: str,
    object_id: str | None = None,
    course_id: str | None = None,
    outcome: str = "success",
    metadata: dict | None = None,
) -> None:
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=actor_id, action=action, object_type=object_type,
        object_id=object_id, course_id=course_id, outcome=outcome,
        metadata_json=metadata or {},
    ))


def course_item(course, teacher, enrollment=None) -> CourseListItem:
    return CourseListItem(
        id=course.id, code=course.code, title=course.title, short_title=course.short_title,
        term=course.term, accent=course.accent, teacher=teacher.name,
        mastery=enrollment.mastery if enrollment else None,
        progress=enrollment.progress if enrollment else None,
        weekly_minutes=enrollment.weekly_minutes if enrollment else None,
        streak_days=enrollment.streak_days if enrollment else None,
        goal=enrollment.goal if enrollment else None,
        focus=enrollment.focus if enrollment else None,
    )


def knowledge_state_view(db, concept, state) -> KnowledgeStateView:
    top_evidence = list(db.scalars(
        select(MasteryEvidence.event_id)
        .where(MasteryEvidence.state_id == state.id)
        .order_by(func.abs(MasteryEvidence.delta).desc(), MasteryEvidence.created_at.desc())
        .limit(3)
    ).all())
    return KnowledgeStateView(
        concept_id=concept.id, label=concept.name, mastery=state.mastery,
        correct_rate=state.correct_rate, evidence_count=state.evidence_count,
        confidence=state.confidence,
        state=classify_state(state.mastery / 100.0, state.effective_evidence, state.uncertainty),
        uncertainty=state.uncertainty, effective_evidence=state.effective_evidence,
        trend_30d=state.trend_30d, last_evidence_at=state.last_evidence_at,
        top_evidence=top_evidence, model_version=state.model_version,
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "zhixing-api"}


@router.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, db: DbSession) -> AuthResponse:
    account = payload.account.strip().lower()
    user = db.scalar(select(User).where(User.email == account))
    if user is None or not verify_password(payload.password, user.password_hash):
        audit(db, actor_id=user.id if user else None, action="auth.login", object_type="session", outcome="denied", metadata={"reason": "invalid_credentials"})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    if user.role != payload.role:
        audit(db, actor_id=user.id, action="auth.login", object_type="session", outcome="denied", metadata={"reason": "role_mismatch", "requested_role": payload.role})
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号与所选身份不匹配")
    if not user.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")

    settings: Settings = request.app.state.settings
    token = create_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.session_ttl_hours)
    auth_session = AuthSession(
        id=str(uuid4()), user_id=user.id, token_hash=hash_token(token), expires_at=expires_at,
    )
    db.add(auth_session)
    audit(db, actor_id=user.id, action="auth.login", object_type="session", object_id=auth_session.id)
    db.commit()
    return AuthResponse(access_token=token, expires_at=expires_at, user=UserView.model_validate(user))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    db: DbSession,
    pair=Depends(current_session_and_user),
):
    auth_session, user = pair
    auth_session.revoked_at = datetime.now(timezone.utc)
    audit(db, actor_id=user.id, action="auth.logout", object_type="session", object_id=auth_session.id)
    db.commit()
    return None


@router.get("/me", response_model=UserView)
def me(user: CurrentUser) -> UserView:
    return UserView.model_validate(user)


@router.get("/auth/me", response_model=UserView, include_in_schema=False)
def legacy_auth_me(user: CurrentUser) -> UserView:
    """兼容首个开发切片；正式OpenAPI使用 `/me`。"""
    return UserView.model_validate(user)


@router.get("/courses", response_model=list[CourseListItem])
def list_courses(user: CurrentUser, db: DbSession) -> list[CourseListItem]:
    repository = CourseRepository(db)
    if user.role == "student":
        result = [course_item(course, teacher, enrollment) for course, enrollment, teacher in repository.list_student_courses(user.id)]
    else:
        result = [course_item(course, teacher) for course, teacher in repository.list_teacher_courses(user.id)]
    return result


@router.get("/student/courses/summary", response_model=CrossCourseSummary)
def student_course_summary(user: StudentUser, db: DbSession) -> CrossCourseSummary:
    rows = CourseRepository(db).list_student_courses(user.id)
    if not rows:
        raise HTTPException(status_code=404, detail="尚未加入课程")
    enrollments = [row[1] for row in rows]
    all_states = []
    repository = CourseRepository(db)
    for course, _, _ in rows:
        all_states.extend(repository.knowledge_states(user.id, course.id))
    ranked = sorted(all_states, key=lambda pair: pair[1].mastery)
    weak_topics = [concept.name for concept, _ in ranked[:2]]
    strong_topics = [concept.name for concept, _ in reversed(ranked[-2:])]
    daily = [
        sum(enrollment.weekly_activity[index] for enrollment in enrollments)
        for index in range(7)
    ]
    course_ids = [course.id for course, _, _ in rows]
    pending_resources = db.scalar(
        select(func.count())
        .select_from(LearningResource)
        .where(
            LearningResource.course_id.in_(course_ids),
            LearningResource.published.is_(True),
            or_(
                LearningResource.progress_total.is_(None),
                LearningResource.progress_completed.is_(None),
                LearningResource.progress_completed < LearningResource.progress_total,
            ),
        )
    ) or 0
    trend_deltas = [
        float(enrollment.mastery_trend[-1] - enrollment.mastery_trend[0])
        for enrollment in enrollments
        if len(enrollment.mastery_trend) >= 2
    ]
    event_counts = dict(db.execute(
        select(LearningEvent.event_type, func.count())
        .where(
            LearningEvent.student_id == user.id,
            LearningEvent.course_id.in_(course_ids),
        )
        .group_by(LearningEvent.event_type)
    ).all())
    behavior_groups = {
        "知识图谱学习": sum(event_counts.get(kind, 0) for kind in (
            "graph_node_viewed", "knowledge_card_opened",
        )),
        "智适练习": sum(event_counts.get(kind, 0) for kind in (
            "question_generated", "hint_viewed", "answer_submitted", "answer_scored",
            "question_set_completed", "question_retried",
        )),
        "视频学习": sum(event_counts.get(kind, 0) for kind in (
            "video_started", "video_progressed", "video_completed",
        )),
        "智伴辅导": sum(event_counts.get(kind, 0) for kind in (
            "conversation_started", "tutor_message_received", "inline_practice_scored",
        )),
    }
    preferred_name, preferred_count = max(behavior_groups.items(), key=lambda item: item[1])
    preferred_pattern = (
        f"{preferred_name}行为记录最多（{preferred_count}条课程内事件）"
        if preferred_count
        else "尚无足够行为证据，暂不生成学习偏好结论"
    )
    return CrossCourseSummary(
        active_courses=len(enrollments),
        weekly_minutes=sum(item.weekly_minutes for item in enrollments),
        pending_resources=pending_resources,
        overall_mastery=round(sum(item.mastery for item in enrollments) / len(enrollments)),
        mastery_delta=round(sum(trend_deltas) / len(trend_deltas), 1) if trend_deltas else 0,
        strong_topics=strong_topics,
        weak_topics=weak_topics,
        daily_minutes=daily,
        daily_average=round(sum(daily) / 7),
        peak_day=["周一", "周二", "周三", "周四", "周五", "周六", "周日"][daily.index(max(daily))],
        streak_days=max(item.streak_days for item in enrollments),
        resource_completion=round(sum(item.resource_completion for item in enrollments) / len(enrollments)),
        preferred_pattern=preferred_pattern,
    )


@router.get("/student/courses/{course_id}/overview", response_model=StudentCourseOverview)
def student_overview(course_id: str, user: StudentUser, db: DbSession) -> StudentCourseOverview:
    repository = CourseRepository(db)
    row = repository.get_student_course(user.id, course_id)
    if row is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")
    course, enrollment, teacher = row
    states = [knowledge_state_view(db, concept, state) for concept, state in repository.knowledge_states(user.id, course_id)]
    resources = [ResourceView(
        id=item.id, resource_type=item.resource_type, title=item.title, detail=item.detail,
        progress_completed=item.progress_completed, progress_total=item.progress_total, accuracy=item.accuracy,
    ) for item in repository.resources(course_id)]
    activities = [ActivityView(
        id=item.id, title=item.title, detail=item.detail,
        activity_type=item.activity_type, occurred_at=item.occurred_at,
    ) for item in repository.activities(user.id, course_id)]
    audit(db, actor_id=user.id, action="student.overview.read", object_type="course", object_id=course_id, course_id=course_id)
    db.commit()
    return StudentCourseOverview(
        course=course_item(course, teacher, enrollment), focus_summary=enrollment.focus_summary,
        mastery=TrendMetric(value=enrollment.mastery, delta=enrollment.mastery_delta, trend=enrollment.mastery_trend),
        resource_completion=TrendMetric(value=enrollment.resource_completion, delta=enrollment.resource_delta, trend=enrollment.resource_trend),
        recent_accuracy=TrendMetric(value=enrollment.recent_accuracy, delta=enrollment.accuracy_delta, trend=enrollment.accuracy_trend),
        streak=TrendMetric(value=enrollment.streak_days, delta=enrollment.streak_delta, trend=enrollment.streak_trend),
        weekly_activity=enrollment.weekly_activity, daily_average=enrollment.daily_average,
        efficient_sessions=enrollment.efficient_sessions, knowledge_states=states,
        recent_resources=resources, recent_activities=activities,
    )


@router.get("/student/courses/{course_id}/mastery", response_model=list[KnowledgeStateView])
def student_mastery(course_id: str, user: StudentUser, db: DbSession) -> list[KnowledgeStateView]:
    repository = CourseRepository(db)
    if repository.get_student_course(user.id, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")
    return [knowledge_state_view(db, concept, state) for concept, state in repository.knowledge_states(user.id, course_id)]


@router.post("/student/courses/{course_id}/events", response_model=TrajectoryUpdateResponse)
def ingest_learning_event(
    course_id: str,
    payload: LearningEventCreate,
    user: StudentUser,
    db: DbSession,
) -> TrajectoryUpdateResponse:
    command = client_observation_command(db, student=user, course_id=course_id, payload=payload)
    result = TrajectoryService(db).ingest(student=user, course_id=course_id, command=command)
    return TrajectoryUpdateResponse.model_validate({
        "event_id": result.event_id,
        "duplicate": result.duplicate,
        "processing_status": result.processing_status,
        "evidence_success": result.evidence_success,
        "evidence_reliability": result.evidence_reliability,
        "evidence_reason": result.evidence_reason,
        "changes": [change.__dict__ for change in result.changes],
    })


@router.get("/teacher/courses/{course_id}/overview", response_model=TeacherCourseOverview)
def teacher_overview(course_id: str, user: TeacherUser, db: DbSession) -> TeacherCourseOverview:
    repository = CourseRepository(db)
    row = repository.get_teacher_course(user.id, course_id)
    if row is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")
    course, teacher = row
    enrollment_count = db.scalar(select(func.count()).select_from(CourseEnrollment).where(CourseEnrollment.course_id == course_id)) or 0
    average_mastery = db.scalar(select(func.avg(CourseEnrollment.mastery)).where(CourseEnrollment.course_id == course_id)) or 0
    average_accuracy = db.scalar(select(func.avg(CourseEnrollment.recent_accuracy)).where(CourseEnrollment.course_id == course_id)) or 0
    average_resource = db.scalar(select(func.avg(CourseEnrollment.resource_completion)).where(CourseEnrollment.course_id == course_id)) or 0
    snapshot = db.scalar(
        select(DecisionSnapshot)
        .where(DecisionSnapshot.course_id == course_id)
        .order_by(DecisionSnapshot.as_of.desc(), DecisionSnapshot.created_at.desc())
    )
    if snapshot is None:
        snapshot = create_snapshot(db, teacher_id=user.id, course_id=course_id)
    priority_student_count = len(snapshot.aggregate_json.get("priority_student_ids", []))
    audit(db, actor_id=user.id, action="teacher.overview.read", object_type="course", object_id=course_id, course_id=course_id)
    db.commit()
    return TeacherCourseOverview(
        course=course_item(course, teacher), class_name=f"{course.code} · {course.term}教学班",
        student_count=enrollment_count, average_mastery=round(float(average_mastery)),
        average_accuracy=round(float(average_accuracy)), resource_completion=round(float(average_resource)),
        priority_student_count=priority_student_count,
    )


@router.get("/model-profiles", response_model=list[ModelProfileView])
def model_profiles(user: CurrentUser, db: DbSession, task_kind: str | None = None) -> list[ModelProfileView]:
    profiles = db.scalars(select(ModelProfile).where(ModelProfile.enabled.is_(True)).order_by(ModelProfile.display_name)).all()
    result = []
    for item in profiles:
        if task_kind is not None and task_kind not in item.task_kinds:
            continue
        resolved = resolve_profile(db, item, task_kind)
        result.append(ModelProfileView(
            id=item.id, display_name=item.display_name, task_kinds=item.task_kinds,
            config_revision=item.config_revision,
            capabilities=resolved.revision.capabilities_json if resolved.revision else [],
            available=resolved.available,
            unavailable_reason=resolved.unavailable_reason,
        ))
    return result
