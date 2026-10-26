from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from .dependencies import DbSession, StudentUser, TeacherUser
from .domains.video_search.api_schemas import (
    LinkCheckView,
    PreviewEventCreate,
    PreviewEventView,
    VideoCandidateView,
    VideoEventResult,
    VideoPlayerEventCreate,
    VideoProgressView,
    VideoPublicationCreate,
    VideoPublicationView,
    VideoSearchJobCreate,
    VideoSearchJobView,
    VideoSearchSourcesView,
)
from .domains.video_search.provider import (
    InternetArchiveVideoProvider,
    PeerTubeVideoProvider,
    WikimediaVideoProvider,
)
from .domains.video_search.service import (
    VideoSearchService,
    VideoServiceError,
    candidate_view,
    job_view,
    link_check_view,
    preview_view,
)


router = APIRouter(prefix="/api/v1", tags=["video-recommendation"])


def _idempotency_key(
    value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    key = (value or "").strip()
    if not key:
        raise HTTPException(
            status_code=422,
            detail={"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "写请求必须提供Idempotency-Key"},
        )
    if len(key) > 160 or any(ord(character) < 32 for character in key):
        raise HTTPException(
            status_code=422,
            detail={"code": "IDEMPOTENCY_KEY_INVALID", "message": "Idempotency-Key格式无效"},
        )
    return key


IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key")]


def _checked_key(value: str) -> str:
    key = value.strip()
    if not key or len(key) > 160 or any(ord(character) < 32 for character in key):
        raise HTTPException(
            status_code=422,
            detail={"code": "IDEMPOTENCY_KEY_INVALID", "message": "写请求必须提供有效的Idempotency-Key"},
        )
    return key


def _providers(request: Request) -> tuple[dict[str, object], bool]:
    injected = getattr(request.app.state, "video_provider_registry", None)
    if injected is not None:
        return dict(injected), False
    providers = [
        InternetArchiveVideoProvider(),
        WikimediaVideoProvider(),
        PeerTubeVideoProvider(),
    ]
    return {item.provider_id: item for item in providers}, True


def _close_providers(providers: dict[str, object], owned: bool) -> None:
    if not owned:
        return
    for provider in providers.values():
        client = getattr(provider, "client", None)
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _raise(error: VideoServiceError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.safe_message},
    ) from error


@router.post(
    "/courses/{course_id}/video-search-jobs",
    response_model=VideoSearchJobView,
    status_code=status.HTTP_201_CREATED,
)
def create_video_search_job(
    course_id: str,
    payload: VideoSearchJobCreate,
    request: Request,
    user: TeacherUser,
    db: DbSession,
    idempotency_key: IdempotencyKey,
) -> VideoSearchJobView:
    providers, owned = _providers(request)
    try:
        job = VideoSearchService(db).create_job(
            teacher=user, course_id=course_id, payload=payload,
            idempotency_key=_checked_key(idempotency_key), providers=providers,
        )
    except VideoServiceError as error:
        _raise(error)
    finally:
        _close_providers(providers, owned)
    if job.status == "failed":
        raise HTTPException(
            status_code=503,
            detail={
                "code": job.safe_error_code,
                "message": job.safe_error_message,
                "job_id": job.id,
            },
        )
    return job_view(job)


@router.get(
    "/teacher/courses/{course_id}/video-search-sources",
    response_model=VideoSearchSourcesView,
)
def get_video_search_sources(
    course_id: str,
    user: TeacherUser,
    db: DbSession,
) -> VideoSearchSourcesView:
    try:
        return VideoSearchService(db).source_options(user, course_id)
    except VideoServiceError as error:
        _raise(error)


@router.get("/video-search-jobs/{job_id}", response_model=VideoSearchJobView)
def get_video_search_job(job_id: str, user: TeacherUser, db: DbSession) -> VideoSearchJobView:
    try:
        return job_view(VideoSearchService(db).teacher_job(user, job_id))
    except VideoServiceError as error:
        _raise(error)


@router.get(
    "/video-search-jobs/{job_id}/candidates",
    response_model=list[VideoCandidateView],
)
def list_video_candidates(
    job_id: str,
    user: TeacherUser,
    db: DbSession,
    min_duration: Annotated[int | None, Query(ge=0)] = None,
    max_duration: Annotated[int | None, Query(ge=0)] = None,
    content_kind: Annotated[Literal["video", "lecture", "tutorial", "case"] | None, Query()] = None,
) -> list[VideoCandidateView]:
    if min_duration is not None and max_duration is not None and min_duration > max_duration:
        raise HTTPException(status_code=422, detail="最小时长不能大于最大时长")
    service = VideoSearchService(db)
    try:
        rows = service.list_candidates(
            user, job_id, min_duration=min_duration,
            max_duration=max_duration, content_kind=content_kind,
        )
    except VideoServiceError as error:
        _raise(error)
    return [candidate_view(db, item, user.id) for item in rows]


@router.get("/video-candidates/{candidate_id}", response_model=VideoCandidateView)
def get_video_candidate(candidate_id: str, user: TeacherUser, db: DbSession) -> VideoCandidateView:
    service = VideoSearchService(db)
    try:
        return candidate_view(db, service.teacher_candidate(user, candidate_id), user.id)
    except VideoServiceError as error:
        _raise(error)


@router.post(
    "/video-candidates/{candidate_id}/preview-events",
    response_model=PreviewEventView,
    status_code=status.HTTP_201_CREATED,
)
def create_preview_event(
    candidate_id: str,
    payload: PreviewEventCreate,
    user: TeacherUser,
    db: DbSession,
    idempotency_key: IdempotencyKey,
) -> PreviewEventView:
    try:
        event, duplicate = VideoSearchService(db).record_preview(
            teacher=user, candidate_id=candidate_id,
            action=payload.action, idempotency_key=_checked_key(idempotency_key),
        )
        return preview_view(event, duplicate=duplicate)
    except VideoServiceError as error:
        _raise(error)


@router.post(
    "/video-candidates/{candidate_id}/recheck",
    response_model=LinkCheckView,
    status_code=status.HTTP_201_CREATED,
)
def recheck_video_candidate(
    candidate_id: str,
    request: Request,
    user: TeacherUser,
    db: DbSession,
    idempotency_key: IdempotencyKey,
) -> LinkCheckView:
    service = VideoSearchService(db)
    try:
        candidate = service.teacher_candidate(user, candidate_id)
    except VideoServiceError as error:
        _raise(error)
    providers, owned = _providers(request)
    provider = providers.get(candidate.provider)
    if provider is None:
        _close_providers(providers, owned)
        raise HTTPException(
            status_code=503,
            detail={"code": "VIDEO_PROVIDER_UNAVAILABLE", "message": "该视频来源当前没有可用核验适配器"},
        )
    try:
        check = service.recheck(
            teacher=user, candidate_id=candidate_id, provider=provider,
            idempotency_key=_checked_key(idempotency_key),
        )
        return link_check_view(check)
    except VideoServiceError as error:
        _raise(error)
    finally:
        _close_providers(providers, owned)


@router.post(
    "/video-publications",
    response_model=VideoPublicationView,
    status_code=status.HTTP_201_CREATED,
)
def publish_video(
    payload: VideoPublicationCreate,
    request: Request,
    user: TeacherUser,
    db: DbSession,
    idempotency_key: IdempotencyKey,
) -> VideoPublicationView:
    service = VideoSearchService(db)
    try:
        candidate = service.teacher_candidate(user, payload.candidate_id)
    except VideoServiceError as error:
        _raise(error)
    providers, owned = _providers(request)
    provider = providers.get(candidate.provider)
    if provider is None:
        _close_providers(providers, owned)
        raise HTTPException(
            status_code=503,
            detail={"code": "VIDEO_PROVIDER_UNAVAILABLE", "message": "该视频来源当前没有可用核验适配器"},
        )
    try:
        publication, duplicate = service.publish(
            teacher=user, payload=payload,
            idempotency_key=_checked_key(idempotency_key), provider=provider,
        )
        return service.publication_view(publication, duplicate=duplicate)
    except VideoServiceError as error:
        _raise(error)
    finally:
        _close_providers(providers, owned)


@router.get(
    "/courses/{course_id}/resources",
    response_model=list[VideoPublicationView],
)
def list_student_video_resources(
    course_id: str,
    user: StudentUser,
    db: DbSession,
    resource_type: Annotated[Literal["video"], Query(alias="type")] = "video",
) -> list[VideoPublicationView]:
    del resource_type
    service = VideoSearchService(db)
    try:
        return [service.publication_view(item) for item in service.student_resources(user, course_id)]
    except VideoServiceError as error:
        _raise(error)


@router.get("/video-publications/{publication_id}", response_model=VideoPublicationView)
def get_student_video_publication(
    publication_id: str,
    user: StudentUser,
    db: DbSession,
) -> VideoPublicationView:
    service = VideoSearchService(db)
    try:
        return service.publication_view(service.student_publication(user, publication_id))
    except VideoServiceError as error:
        _raise(error)


@router.post(
    "/video-publications/{publication_id}/events",
    response_model=VideoEventResult,
    status_code=status.HTTP_201_CREATED,
)
def create_video_player_event(
    publication_id: str,
    payload: VideoPlayerEventCreate,
    user: StudentUser,
    db: DbSession,
    idempotency_key: IdempotencyKey,
) -> VideoEventResult:
    try:
        return VideoSearchService(db).ingest_event(
            student=user, publication_id=publication_id,
            payload=payload, idempotency_key=_checked_key(idempotency_key),
        )
    except VideoServiceError as error:
        _raise(error)


@router.get(
    "/video-publications/{publication_id}/progress",
    response_model=VideoProgressView,
)
def get_video_progress(
    publication_id: str,
    user: StudentUser,
    db: DbSession,
) -> VideoProgressView:
    service = VideoSearchService(db)
    try:
        publication = service.student_publication(user, publication_id)
        progress = service._get_progress(user.id, publication_id)
        return service.progress_view(progress, publication)
    except VideoServiceError as error:
        _raise(error)
