from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import (
    AuditEvent,
    Concept,
    Course,
    CourseEnrollment,
    GraphNode,
    GraphRevision,
    KnowledgeGraph,
    KnowledgeState,
    ParsedDocument,
    SourceAsset,
    User,
)
from ...video_models import (
    PublicationRecipient,
    VideoCandidateConcept,
    VideoCandidateRecord,
    VideoInteractionEvent,
    VideoLinkCheck,
    VideoPreviewEvent,
    VideoProgress,
    VideoPublication,
    VideoPublicationConcept,
    VideoSearchJob,
)
from ..teaching_decision.audience import StudentConceptState, resolve_audience
from ..trajectory.service import ConceptContribution, EventCommand, TrajectoryService
from .api_schemas import (
    LinkCheckView,
    PreviewEventView,
    PublicationAudience,
    VideoCandidateView,
    VideoEventResult,
    VideoPlayerEventCreate,
    VideoProgressView,
    VideoPublicationCreate,
    VideoPublicationView,
    VideoScoresView,
    VideoSearchJobCreate,
    VideoSearchJobView,
    VideoSearchSourcesView,
    VideoSourceAssetView,
    VideoSourceGraphView,
    VideoSourceTopicView,
)
from .provider import VideoDiscoveryError
from .ranking import rank_candidates
from .schemas import DiscoveredVideo, TopicRef, VideoMetadata, VideoSearchIntent
from .urls import UnsafeVideoUrl, validate_public_https_url


SEARCH_ALGORITHM_VERSION = "vista-search-1.0.0"
PROGRESS_ALGORITHM_VERSION = "vista-progress-1.0.0"
VERIFICATION_TTL = timedelta(hours=24)


class VideoServiceError(RuntimeError):
    def __init__(self, code: str, safe_message: str, status_code: int):
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def _metadata_hash(value: VideoMetadata | VideoCandidateRecord) -> str:
    return stable_hash({
        "title": value.title,
        "creator": value.creator,
        "duration_seconds": value.duration_seconds,
        "final_url": value.final_url if isinstance(value, VideoMetadata) else value.canonical_url,
        "license_name": value.license_name,
    })


def _content_kind(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    if any(term in text for term in ("案例", "case study", "case analysis")):
        return "case"
    if any(term in text for term in ("实操", "教程", "tutorial", "walkthrough", "how to")):
        return "tutorial"
    if any(term in text for term in ("公开课", "课程", "讲座", "lecture", "course")):
        return "lecture"
    return "video"


def _safe_teaching_intent(value: str) -> str:
    """只把教学目的标签发往检索适配器，不外发教师自由文本。"""
    labels = {
        "课前": "课前引入",
        "引入": "概念引入",
        "课后": "课后巩固",
        "巩固": "课后巩固",
        "推导": "公式推导",
        "案例": "案例讲解",
        "实操": "实践演示",
        "复习": "复习总结",
        "误区": "误区辨析",
    }
    return " ".join(dict.fromkeys(label for term, label in labels.items() if term in value))


def _provider_output_safe(discovered: DiscoveredVideo, metadata: VideoMetadata) -> bool:
    blocked_terms = {
        "porn", "sexual content", "adult only", "赌博", "博彩", "色情",
    }
    text = f"{metadata.title} {metadata.description}".lower()
    if any(term in text for term in blocked_terms):
        return False
    try:
        validate_public_https_url(discovered.canonical_url, resolve_dns=False)
        for optional_url in (metadata.embed_url, metadata.thumbnail_url):
            if optional_url:
                validate_public_https_url(optional_url, resolve_dns=False)
    except UnsafeVideoUrl:
        return False
    return True


def _audit(
    db: Session,
    *,
    actor_id: str,
    action: str,
    object_type: str,
    object_id: str,
    course_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=actor_id, action=action,
        object_type=object_type, object_id=object_id, course_id=course_id,
        outcome="success", metadata_json=metadata or {},
    ))


def _teacher_course(db: Session, teacher_id: str, course_id: str) -> Course:
    course = db.scalar(select(Course).where(Course.id == course_id, Course.teacher_id == teacher_id))
    if course is None:
        raise VideoServiceError("VIDEO_COURSE_NOT_FOUND", "课程不存在或无权访问", 404)
    return course


def _student_enrollment(db: Session, student_id: str, course_id: str) -> CourseEnrollment:
    enrollment = db.scalar(select(CourseEnrollment).where(
        CourseEnrollment.student_id == student_id,
        CourseEnrollment.course_id == course_id,
    ))
    if enrollment is None:
        raise VideoServiceError("VIDEO_COURSE_NOT_FOUND", "课程不存在或无权访问", 404)
    return enrollment


def _validate_source(
    db: Session,
    *,
    teacher: User,
    course_id: str,
    payload: VideoSearchJobCreate,
) -> list[Concept]:
    _teacher_course(db, teacher.id, course_id)
    concepts = list(db.scalars(select(Concept).where(
        Concept.course_id == course_id,
        Concept.id.in_(payload.topic_ids),
    )).all())
    by_id = {item.id: item for item in concepts}
    if len(by_id) != len(payload.topic_ids):
        raise VideoServiceError(
            "VIDEO_TOPIC_OUT_OF_SCOPE", "知识点不存在或不属于当前课程", 422,
        )
    if payload.source_mode == "records":
        recorded = {item.id for item in concepts if item.sort_order <= 10}
        if recorded != set(payload.topic_ids):
            raise VideoServiceError(
                "VIDEO_RECORDED_TOPIC_REQUIRED", "所选知识点不属于当前课程的作答记录口径", 422,
            )
    elif payload.source_mode == "graph":
        revision = db.scalar(
            select(GraphRevision)
            .join(KnowledgeGraph, KnowledgeGraph.id == GraphRevision.graph_id)
            .where(
                GraphRevision.id == payload.graph_revision_id,
                GraphRevision.status == "published",
                KnowledgeGraph.course_id == course_id,
                KnowledgeGraph.published_revision_id == GraphRevision.id,
            )
        )
        if revision is None:
            raise VideoServiceError(
                "VIDEO_GRAPH_REVISION_REQUIRED", "只能使用当前课程已发布的知识图谱修订", 422,
            )
        graph_topic_ids = set(db.scalars(select(GraphNode.concept_id).where(
            GraphNode.revision_id == revision.id,
            GraphNode.concept_id.in_(payload.topic_ids),
        )).all())
        if graph_topic_ids != set(payload.topic_ids):
            raise VideoServiceError(
                "VIDEO_GRAPH_TOPIC_OUT_OF_SCOPE", "所选知识点不属于指定图谱修订", 422,
            )
    elif payload.source_mode == "files":
        assets = list(db.scalars(select(SourceAsset).where(
            SourceAsset.id.in_(payload.asset_ids),
            SourceAsset.course_id == course_id,
            SourceAsset.owner_id == teacher.id,
            SourceAsset.status == "accepted",
            SourceAsset.security_status == "accepted",
            SourceAsset.deleted_at.is_(None),
        )).all())
        if len(assets) != len(payload.asset_ids):
            raise VideoServiceError(
                "VIDEO_SOURCE_ASSET_NOT_READY", "教学文件不存在、未通过安全检查或无权访问", 422,
            )
        parsed = db.scalar(select(func.count()).select_from(ParsedDocument).where(
            ParsedDocument.asset_id.in_(payload.asset_ids), ParsedDocument.status == "parsed",
        )) or 0
        if parsed != len(payload.asset_ids):
            raise VideoServiceError(
                "VIDEO_SOURCE_ASSET_NOT_PARSED", "教学文件尚未完成解析", 409,
            )
    return [by_id[topic_id] for topic_id in payload.topic_ids]


def _source_snapshot(payload: VideoSearchJobCreate) -> dict[str, Any]:
    # 原始手动输入只保留在课程内审计快照，绝不传给外部检索提供方。
    return {
        "graph_revision_id": payload.graph_revision_id,
        "asset_ids": payload.asset_ids,
        "raw_text": payload.raw_text,
        "max_candidates_per_provider": payload.max_candidates_per_provider,
        "algorithm_version": SEARCH_ALGORITHM_VERSION,
    }


def _resolve_provider(provider: Any, intent: VideoSearchIntent, limit: int) -> tuple[list[tuple[DiscoveredVideo, VideoMetadata]], int, list[str]]:
    if hasattr(provider, "search_resolved"):
        resolved = provider.search_resolved(intent, max_candidates=limit)
        return list(resolved), len(resolved), []
    if not hasattr(provider, "search") or not hasattr(provider, "resolve"):
        raise VideoDiscoveryError(
            "VIDEO_PROVIDER_CONTRACT_INVALID", "视频检索提供方配置无效",
        )
    discovered = list(provider.search(intent, max_candidates=limit))
    resolved: list[tuple[DiscoveredVideo, VideoMetadata]] = []
    failures: list[str] = []
    for candidate in discovered:
        try:
            resolved.append((candidate, provider.resolve(candidate)))
        except VideoDiscoveryError as error:
            failures.append(error.code)
    return resolved, len(discovered), failures


def _deduplicate(
    resolved: list[tuple[DiscoveredVideo, VideoMetadata]],
) -> list[tuple[DiscoveredVideo, VideoMetadata]]:
    chosen: dict[tuple[str, str], tuple[DiscoveredVideo, VideoMetadata]] = {}
    canonical_seen: set[str] = set()
    for discovered, metadata in resolved:
        identity = (discovered.provider, discovered.external_id)
        if identity in chosen or discovered.canonical_url in canonical_seen:
            continue
        chosen[identity] = (discovered, metadata)
        canonical_seen.add(discovered.canonical_url)
    return list(chosen.values())


class VideoSearchService:
    def __init__(self, db: Session):
        self.db = db

    def create_job(
        self,
        *,
        teacher: User,
        course_id: str,
        payload: VideoSearchJobCreate,
        idempotency_key: str,
        providers: Mapping[str, Any],
    ) -> VideoSearchJob:
        concepts = _validate_source(
            self.db, teacher=teacher, course_id=course_id, payload=payload,
        )
        request_basis = {
            "course_id": course_id,
            "payload": payload.model_dump(mode="json"),
        }
        request_hash = stable_hash(request_basis)
        prior = self.db.scalar(select(VideoSearchJob).where(
            VideoSearchJob.teacher_id == teacher.id,
            VideoSearchJob.course_id == course_id,
            VideoSearchJob.idempotency_key == idempotency_key,
        ))
        if prior is not None:
            if prior.request_hash != request_hash:
                raise VideoServiceError(
                    "VIDEO_SEARCH_IDEMPOTENCY_CONFLICT",
                    "同一幂等键已用于不同的视频检索输入",
                    409,
                )
            return prior

        warnings: list[dict[str, Any]] = []
        if payload.requested_profile_id:
            if not payload.allow_deterministic_degrade:
                raise VideoServiceError(
                    "VIDEO_QUERY_PLANNER_UNAVAILABLE",
                    "所选模型的A4查询规划任务当前不可用，未发起检索且未生成替代结果",
                    503,
                )
            warnings.append({
                "code": "DETERMINISTIC_QUERY_PLAN",
                "message": "所选模型未用于本次查询规划；已按教师明确允许使用标准知识点确定性检索",
            })
        job = VideoSearchJob(
            id=str(uuid4()), course_id=course_id, teacher_id=teacher.id,
            idempotency_key=idempotency_key, request_hash=request_hash,
            source_mode=payload.source_mode, source_payload_json=_source_snapshot(payload),
            topic_snapshot_json=[{"concept_id": item.id, "label": item.name} for item in concepts],
            teaching_intent=payload.teaching_intent, language=payload.language,
            requested_profile_id=payload.requested_profile_id, actual_profile_id=None,
            deterministic_degrade=True, status="retrieving",
            provider_status_json=[], warnings_json=warnings, candidate_count=0,
        )
        self.db.add(job)
        _audit(
            self.db, actor_id=teacher.id, action="video.search.created",
            object_type="video_search_job", object_id=job.id, course_id=course_id,
            metadata={"source_mode": payload.source_mode, "topic_count": len(concepts)},
        )
        self.db.commit()

        intent = VideoSearchIntent(
            course_id=course_id,
            source_mode=payload.source_mode,
            topics=[TopicRef(concept_id=item.id, label=item.name) for item in concepts],
            teaching_intent=_safe_teaching_intent(payload.teaching_intent),
            language=payload.language,
            requested_profile_id=payload.requested_profile_id,
        )
        all_resolved: list[tuple[DiscoveredVideo, VideoMetadata]] = []
        statuses: list[dict[str, Any]] = []
        for provider_id, provider in providers.items():
            try:
                resolved, discovered_count, item_failures = _resolve_provider(
                    provider, intent, payload.max_candidates_per_provider,
                )
                all_resolved.extend(resolved)
                state = "partial" if item_failures else "completed"
                statuses.append({
                    "provider": provider_id,
                    "status": state,
                    "discovered_count": discovered_count,
                    "accepted_count": len(resolved),
                    "error_code": item_failures[0] if item_failures else None,
                    "safe_message": "部分候选链接无法核验" if item_failures else None,
                })
            except VideoDiscoveryError as error:
                statuses.append({
                    "provider": provider_id,
                    "status": "unavailable",
                    "discovered_count": 0,
                    "accepted_count": 0,
                    "error_code": error.code,
                    "safe_message": error.safe_message,
                })
            except Exception:
                statuses.append({
                    "provider": provider_id,
                    "status": "unavailable",
                    "discovered_count": 0,
                    "accepted_count": 0,
                    "error_code": "VIDEO_SEARCH_PROVIDER_UNAVAILABLE",
                    "safe_message": "视频检索提供方当前不可用",
                })

        safe_resolved = [
            item for item in _deduplicate(all_resolved)
            if _provider_output_safe(item[0], item[1])
        ]
        ranked = rank_candidates(intent, safe_resolved, diversify=True)
        accepted = [
            item for item in ranked
            if item.matched_topic_ids and {"source", "metadata"}.issubset(set(item.verified_scope))
        ]
        accepted_by_provider = Counter(item.provider for item in accepted)
        for item in statuses:
            item["accepted_count"] = accepted_by_provider.get(item["provider"], 0)
        now = utcnow()
        for index, item in enumerate(accepted, start=1):
            scope = list(dict.fromkeys(item.verified_scope))
            verified = "link" in scope
            record = VideoCandidateRecord(
                id=str(uuid4()), job_id=job.id, course_id=course_id,
                provider=item.provider, external_id=item.external_id,
                canonical_url=item.canonical_url, embed_url=item.embed_url,
                title=item.title, creator=item.creator, description=item.description,
                thumbnail_url=item.thumbnail_url, duration_seconds=item.duration_seconds,
                content_type=None, content_kind=_content_kind(item.title, item.description),
                license_name=item.license_name, license_url=item.license_url,
                scores_json={
                    "match": item.match_score,
                    "completeness": item.completeness_score,
                    "trust": item.trust_score,
                    "clarity": item.clarity_score,
                    "final": item.final_score,
                },
                matched_topic_ids=item.matched_topic_ids,
                evidence_level=item.evidence_level, verified_scope=scope,
                uncertainty_reason=item.uncertainty_reason,
                critical_metadata_hash=stable_hash({
                    "title": item.title, "creator": item.creator,
                    "duration_seconds": item.duration_seconds,
                    "canonical_url": item.canonical_url,
                    "license_name": item.license_name,
                }),
                verification_status="verified" if verified else "needs_recheck",
                lifecycle_status="ranked", rank=index, verified_at=item.verified_at,
                verification_expires_at=now + VERIFICATION_TTL if verified else None,
            )
            self.db.add(record)
            self.db.flush()
            support = item.match_score / max(len(item.matched_topic_ids), 1)
            for concept_id in item.matched_topic_ids:
                self.db.add(VideoCandidateConcept(
                    id=str(uuid4()), candidate_id=record.id,
                    concept_id=concept_id, support=support,
                ))
        job.provider_status_json = statuses
        job.candidate_count = len(accepted)
        job.completed_at = now
        unavailable = sum(item["status"] == "unavailable" for item in statuses)
        if not accepted:
            job.status = "failed"
            job.safe_error_code = (
                "VIDEO_ALL_PROVIDERS_UNAVAILABLE"
                if statuses and unavailable == len(statuses)
                else "VIDEO_NO_ELIGIBLE_CANDIDATES"
            )
            job.safe_error_message = (
                "外部视频检索服务当前不可用"
                if statuses and unavailable == len(statuses)
                else "检索已完成，但没有候选通过知识点与来源检查"
            )
        elif unavailable or any(item["status"] == "partial" for item in statuses):
            job.status = "partial"
        else:
            job.status = "completed"
        _audit(
            self.db, actor_id=teacher.id, action="video.search.completed",
            object_type="video_search_job", object_id=job.id, course_id=course_id,
            metadata={
                "status": job.status, "candidate_count": len(accepted),
                "provider_statuses": [item["status"] for item in statuses],
            },
        )
        self.db.commit()
        return job

    def source_options(self, teacher: User, course_id: str) -> VideoSearchSourcesView:
        _teacher_course(self.db, teacher.id, course_id)
        recorded_rows = self.db.execute(
            select(
                Concept,
                func.avg(KnowledgeState.correct_rate),
                func.sum(KnowledgeState.evidence_count),
            )
            .outerjoin(
                KnowledgeState,
                (KnowledgeState.concept_id == Concept.id)
                & (KnowledgeState.course_id == course_id),
            )
            .where(Concept.course_id == course_id, Concept.sort_order <= 10)
            .group_by(Concept.id)
            .order_by(Concept.sort_order)
        ).all()
        recorded = [VideoSourceTopicView(
            concept_id=concept.id,
            label=concept.name,
            correct_rate=round(float(correct_rate), 2) if correct_rate is not None else None,
            evidence_count=int(evidence_count or 0),
        ) for concept, correct_rate, evidence_count in recorded_rows]
        graph_rows = self.db.execute(
            select(KnowledgeGraph, GraphRevision)
            .join(GraphRevision, GraphRevision.id == KnowledgeGraph.published_revision_id)
            .where(
                KnowledgeGraph.course_id == course_id,
                KnowledgeGraph.status == "published",
                GraphRevision.status == "published",
            )
            .order_by(KnowledgeGraph.title)
        ).all()
        graphs: list[VideoSourceGraphView] = []
        for graph, revision in graph_rows:
            nodes = self.db.execute(
                select(GraphNode, Concept)
                .join(Concept, Concept.id == GraphNode.concept_id)
                .where(GraphNode.revision_id == revision.id)
                .order_by(Concept.sort_order, GraphNode.label)
            ).all()
            graphs.append(VideoSourceGraphView(
                graph_id=graph.id,
                title=graph.title,
                published_revision_id=revision.id,
                topics=[VideoSourceTopicView(
                    concept_id=concept.id, label=node.label,
                ) for node, concept in nodes],
            ))
        asset_rows = self.db.execute(
            select(SourceAsset, ParsedDocument)
            .join(ParsedDocument, ParsedDocument.asset_id == SourceAsset.id)
            .where(
                SourceAsset.course_id == course_id,
                SourceAsset.owner_id == teacher.id,
                SourceAsset.status == "accepted",
                SourceAsset.security_status == "accepted",
                SourceAsset.deleted_at.is_(None),
                ParsedDocument.status == "parsed",
            )
            .order_by(SourceAsset.accepted_at.desc(), SourceAsset.created_at.desc())
        ).all()
        return VideoSearchSourcesView(
            course_id=course_id,
            recorded_topics=recorded,
            graphs=graphs,
            parsed_assets=[VideoSourceAssetView(
                asset_id=asset.id,
                original_name=asset.original_name,
                parsed_title=document.title,
                accepted_at=asset.accepted_at,
            ) for asset, document in asset_rows],
        )

    def teacher_job(self, teacher: User, job_id: str) -> VideoSearchJob:
        job = self.db.get(VideoSearchJob, job_id)
        if job is None:
            raise VideoServiceError("VIDEO_SEARCH_JOB_NOT_FOUND", "视频检索任务不存在", 404)
        _teacher_course(self.db, teacher.id, job.course_id)
        return job

    def teacher_candidate(self, teacher: User, candidate_id: str) -> VideoCandidateRecord:
        candidate = self.db.get(VideoCandidateRecord, candidate_id)
        if candidate is None:
            raise VideoServiceError("VIDEO_CANDIDATE_NOT_FOUND", "视频候选不存在", 404)
        _teacher_course(self.db, teacher.id, candidate.course_id)
        return candidate

    def list_candidates(
        self,
        teacher: User,
        job_id: str,
        *,
        min_duration: int | None,
        max_duration: int | None,
        content_kind: str | None,
    ) -> list[VideoCandidateRecord]:
        self.teacher_job(teacher, job_id)
        query = select(VideoCandidateRecord).where(VideoCandidateRecord.job_id == job_id)
        if min_duration is not None:
            query = query.where(VideoCandidateRecord.duration_seconds >= min_duration)
        if max_duration is not None:
            query = query.where(VideoCandidateRecord.duration_seconds <= max_duration)
        if content_kind is not None:
            query = query.where(VideoCandidateRecord.content_kind == content_kind)
        return list(self.db.scalars(query.order_by(VideoCandidateRecord.rank)).all())

    def record_preview(
        self,
        *,
        teacher: User,
        candidate_id: str,
        action: str,
        idempotency_key: str,
    ) -> tuple[VideoPreviewEvent, bool]:
        candidate = self.teacher_candidate(teacher, candidate_id)
        prior = self.db.scalar(select(VideoPreviewEvent).where(
            VideoPreviewEvent.teacher_id == teacher.id,
            VideoPreviewEvent.candidate_id == candidate_id,
            VideoPreviewEvent.idempotency_key == idempotency_key,
        ))
        if prior:
            if prior.action != action:
                raise VideoServiceError(
                    "VIDEO_PREVIEW_IDEMPOTENCY_CONFLICT",
                    "同一幂等键已用于不同的预览动作",
                    409,
                )
            return prior, True
        event = VideoPreviewEvent(
            id=str(uuid4()), candidate_id=candidate_id, teacher_id=teacher.id,
            idempotency_key=idempotency_key, action=action,
        )
        self.db.add(event)
        _audit(
            self.db, actor_id=teacher.id, action="video.candidate.previewed",
            object_type="video_candidate", object_id=candidate.id,
            course_id=candidate.course_id, metadata={"preview_action": action},
        )
        self.db.commit()
        return event, False

    def recheck(
        self,
        *,
        teacher: User,
        candidate_id: str,
        provider: Any,
        idempotency_key: str,
    ) -> VideoLinkCheck:
        candidate = self.teacher_candidate(teacher, candidate_id)
        prior = self.db.scalar(select(VideoLinkCheck).where(
            VideoLinkCheck.candidate_id == candidate.id,
            VideoLinkCheck.idempotency_key == idempotency_key,
        ))
        if prior is not None:
            if prior.status == "metadata_changed":
                raise VideoServiceError(
                    prior.safe_error_code or "VIDEO_METADATA_CHANGED",
                    "视频关键元数据已变化，需要教师复核后再发布",
                    409,
                )
            if prior.status != "available":
                raise VideoServiceError(
                    prior.safe_error_code or "VIDEO_LINK_UNAVAILABLE",
                    "视频页面当前无法访问",
                    503,
                )
            return prior
        discovered = DiscoveredVideo(
            provider=candidate.provider,
            external_id=candidate.external_id,
            canonical_url=candidate.canonical_url,
            title=candidate.title,
            description=candidate.description,
        )
        try:
            if hasattr(provider, "recheck"):
                metadata = provider.recheck(discovered)
            elif hasattr(provider, "resolve"):
                metadata = provider.resolve(discovered)
            else:
                raise VideoDiscoveryError(
                    "VIDEO_RECHECK_UNSUPPORTED", "当前来源不支持安全的发布前复核",
                )
            if not metadata.link_verified:
                raise VideoDiscoveryError(
                    "VIDEO_LINK_NOT_VERIFIED", "视频链接尚未通过实时可访问性核验",
                )
        except VideoDiscoveryError as error:
            check = VideoLinkCheck(
                id=str(uuid4()), candidate_id=candidate.id,
                idempotency_key=idempotency_key,
                status="temporary_failure", safe_error_code=error.code,
                final_url=None, critical_metadata_hash=None,
            )
            self.db.add(check)
            candidate.verification_status = "temporary_failure"
            candidate.lifecycle_status = "needs_review"
            self.db.commit()
            raise VideoServiceError(error.code, error.safe_message, 503) from error
        except Exception as error:
            check = VideoLinkCheck(
                id=str(uuid4()), candidate_id=candidate.id,
                idempotency_key=idempotency_key,
                status="temporary_failure",
                safe_error_code="VIDEO_LINK_UNAVAILABLE",
                final_url=None, critical_metadata_hash=None,
            )
            self.db.add(check)
            candidate.verification_status = "temporary_failure"
            candidate.lifecycle_status = "needs_review"
            self.db.commit()
            raise VideoServiceError(
                "VIDEO_LINK_UNAVAILABLE", "视频页面当前无法访问", 503,
            ) from error
        fresh_hash = _metadata_hash(metadata)
        old_hash = _metadata_hash(candidate)
        now = utcnow()
        if fresh_hash != old_hash:
            check = VideoLinkCheck(
                id=str(uuid4()), candidate_id=candidate.id,
                idempotency_key=idempotency_key,
                status="metadata_changed", safe_error_code="VIDEO_METADATA_CHANGED",
                final_url=metadata.final_url, critical_metadata_hash=fresh_hash,
            )
            self.db.add(check)
            candidate.verification_status = "needs_review"
            candidate.lifecycle_status = "needs_review"
            self.db.commit()
            raise VideoServiceError(
                "VIDEO_METADATA_CHANGED", "视频关键元数据已变化，需要教师复核后再发布", 409,
            )
        candidate.verified_at = now
        candidate.verification_expires_at = now + VERIFICATION_TTL
        candidate.verification_status = "verified"
        candidate.lifecycle_status = "ranked"
        candidate.verified_scope = list(dict.fromkeys([*candidate.verified_scope, "link"]))
        check = VideoLinkCheck(
            id=str(uuid4()), candidate_id=candidate.id,
            idempotency_key=idempotency_key, status="available",
            safe_error_code=None, final_url=metadata.final_url,
            critical_metadata_hash=fresh_hash,
        )
        self.db.add(check)
        self.db.commit()
        return check

    def publish(
        self,
        *,
        teacher: User,
        payload: VideoPublicationCreate,
        idempotency_key: str,
        provider: Any,
    ) -> tuple[VideoPublication, bool]:
        candidate = self.teacher_candidate(teacher, payload.candidate_id)
        request_hash = stable_hash(payload.model_dump(mode="json"))
        prior = self.db.scalar(select(VideoPublication).where(
            VideoPublication.teacher_id == teacher.id,
            VideoPublication.course_id == candidate.course_id,
            VideoPublication.idempotency_key == idempotency_key,
        ))
        if prior:
            if prior.request_hash != request_hash:
                raise VideoServiceError(
                    "VIDEO_PUBLICATION_IDEMPOTENCY_CONFLICT",
                    "同一幂等键已用于不同的视频发布输入",
                    409,
                )
            return prior, True
        self.recheck(
            teacher=teacher, candidate_id=candidate.id, provider=provider,
            idempotency_key=f"publish:{idempotency_key}",
        )
        self.db.refresh(candidate)
        now = utcnow()
        expires_at = candidate.verification_expires_at
        if (
            candidate.verification_status != "verified"
            or expires_at is None
            or as_utc(expires_at) <= now
            or not candidate.matched_topic_ids
        ):
            raise VideoServiceError(
                "VIDEO_NOT_PUBLISHABLE", "视频未通过发布时刻的链接、来源或知识点硬门", 409,
            )
        previewed = self.db.scalar(select(func.count()).select_from(VideoPreviewEvent).where(
            VideoPreviewEvent.candidate_id == candidate.id,
            VideoPreviewEvent.teacher_id == teacher.id,
        )) or 0
        if candidate.evidence_level == "E1" and previewed == 0:
            raise VideoServiceError(
                "VIDEO_PREVIEW_REQUIRED", "E1候选必须由教师预览后才能发布", 409,
            )
        allowed_topics = set(candidate.matched_topic_ids)
        if payload.audience.mode == "states" and not set(payload.audience.topic_ids) <= allowed_topics:
            raise VideoServiceError(
                "VIDEO_AUDIENCE_TOPIC_OUT_OF_SCOPE",
                "定向发布只能使用所选视频实际覆盖的知识点",
                422,
            )
        recipients = self._resolve_recipients(candidate, payload.audience)
        if not recipients:
            raise VideoServiceError(
                "VIDEO_PUBLICATION_EMPTY_AUDIENCE", "当前定向条件没有可接收学生", 422,
            )
        snapshot = {
            "title": candidate.title,
            "creator": candidate.creator,
            "canonical_url": candidate.canonical_url,
            "embed_url": candidate.embed_url,
            "thumbnail_url": candidate.thumbnail_url,
            "duration_seconds": candidate.duration_seconds,
            "content_kind": candidate.content_kind,
            "license_name": candidate.license_name,
            "license_url": candidate.license_url,
            "matched_topic_ids": candidate.matched_topic_ids,
            "evidence_level": candidate.evidence_level,
            "verified_scope": candidate.verified_scope,
            "verified_at": candidate.verified_at.isoformat(),
            "verification_expires_at": candidate.verification_expires_at.isoformat(),
            "known_limitations": [candidate.uncertainty_reason] if candidate.uncertainty_reason else [],
            "chapters": [],
        }
        publication = VideoPublication(
            id=str(uuid4()), course_id=candidate.course_id,
            candidate_id=candidate.id, teacher_id=teacher.id,
            idempotency_key=idempotency_key, request_hash=request_hash,
            intervention_plan_id=payload.intervention_plan_id,
            audience_spec_json=payload.audience.model_dump(mode="json"),
            resource_snapshot_json=snapshot, status="active",
        )
        self.db.add(publication)
        self.db.flush()
        support_by_id = {
            row.concept_id: row.support for row in self.db.scalars(
                select(VideoCandidateConcept).where(VideoCandidateConcept.candidate_id == candidate.id)
            ).all()
        }
        for concept_id in candidate.matched_topic_ids:
            self.db.add(VideoPublicationConcept(
                id=str(uuid4()), publication_id=publication.id,
                concept_id=concept_id, support=support_by_id.get(concept_id, 1.0),
            ))
        for student_id, reason in recipients:
            self.db.add(PublicationRecipient(
                id=str(uuid4()), publication_id=publication.id,
                student_id=student_id, reason_json=reason,
            ))
        candidate.lifecycle_status = "published"
        _audit(
            self.db, actor_id=teacher.id, action="video.publication.created",
            object_type="video_publication", object_id=publication.id,
            course_id=publication.course_id,
            metadata={
                "candidate_id": candidate.id, "recipient_count": len(recipients),
                "audience_mode": payload.audience.mode,
            },
        )
        self.db.commit()
        return publication, False

    def _resolve_recipients(
        self,
        candidate: VideoCandidateRecord,
        audience: PublicationAudience,
    ) -> list[tuple[str, dict[str, Any]]]:
        student_ids = list(self.db.scalars(select(CourseEnrollment.student_id).where(
            CourseEnrollment.course_id == candidate.course_id,
        ).order_by(CourseEnrollment.student_id)).all())
        if audience.mode == "all":
            return [(student_id, {"mode": "all", "resolved_from": "course_enrollment"}) for student_id in student_ids]
        state_rows = list(self.db.scalars(select(KnowledgeState).where(
            KnowledgeState.student_id.in_(student_ids),
            KnowledgeState.course_id == candidate.course_id,
            KnowledgeState.concept_id.in_(audience.topic_ids),
        )).all())
        by_key = {(item.student_id, item.concept_id): item for item in state_rows}
        normalized: list[StudentConceptState] = []
        for student_id in student_ids:
            for concept_id in audience.topic_ids:
                state = by_key.get((student_id, concept_id))
                normalized.append(StudentConceptState(
                    student_id=student_id, course_id=candidate.course_id,
                    concept_id=concept_id,
                    mastery=state.mastery if state else 50.0,
                    evidence_count=state.evidence_count if state else 0,
                    confidence=state.confidence if state else 0.0,
                    effective_evidence=state.effective_evidence if state else 0.0,
                    uncertainty=state.uncertainty if state else 1.0,
                ))
        matches = resolve_audience(
            normalized,
            course_id=candidate.course_id,
            resource_concept_ids=audience.topic_ids,
            selected_states=set(audience.states),
        )
        return [(
            item.student_id,
            {
                "mode": "states",
                "matched_concepts": list(item.matched_concepts),
                "matched_states": list(item.matched_states),
                "low_evidence": item.low_evidence,
                "resolved_from": "a6_deterministic_audience_v1",
            },
        ) for item in matches]

    def publication_view(self, publication: VideoPublication, *, duplicate: bool = False) -> VideoPublicationView:
        count = self.db.scalar(select(func.count()).select_from(PublicationRecipient).where(
            PublicationRecipient.publication_id == publication.id,
        )) or 0
        return VideoPublicationView(
            id=publication.id, course_id=publication.course_id,
            candidate_id=publication.candidate_id, status=publication.status,
            resource=publication.resource_snapshot_json,
            audience=publication.audience_spec_json,
            recipient_count=count, created_at=publication.created_at, duplicate=duplicate,
        )

    def student_publication(self, student: User, publication_id: str) -> VideoPublication:
        publication = self.db.scalar(
            select(VideoPublication)
            .join(PublicationRecipient, PublicationRecipient.publication_id == VideoPublication.id)
            .where(
                VideoPublication.id == publication_id,
                PublicationRecipient.student_id == student.id,
            )
        )
        if publication is None:
            raise VideoServiceError("VIDEO_PUBLICATION_NOT_FOUND", "视频资源不存在或无权访问", 404)
        return publication

    def student_resources(self, student: User, course_id: str) -> list[VideoPublication]:
        _student_enrollment(self.db, student.id, course_id)
        return list(self.db.scalars(
            select(VideoPublication)
            .join(PublicationRecipient, PublicationRecipient.publication_id == VideoPublication.id)
            .where(
                VideoPublication.course_id == course_id,
                PublicationRecipient.student_id == student.id,
                VideoPublication.status.in_(["active", "needs_review", "unavailable"]),
            )
            .order_by(VideoPublication.created_at.desc())
        ).all())

    def ingest_event(
        self,
        *,
        student: User,
        publication_id: str,
        payload: VideoPlayerEventCreate,
        idempotency_key: str,
    ) -> VideoEventResult:
        publication = self.student_publication(student, publication_id)
        request_hash = stable_hash(payload.model_dump(mode="json"))
        prior = self.db.scalar(select(VideoInteractionEvent).where(
            VideoInteractionEvent.publication_id == publication_id,
            VideoInteractionEvent.student_id == student.id,
            VideoInteractionEvent.idempotency_key == idempotency_key,
        ))
        if prior is not None:
            if prior.request_hash != request_hash:
                raise VideoServiceError(
                    "VIDEO_EVENT_IDEMPOTENCY_CONFLICT",
                    "同一幂等键已用于不同的视频学习事件",
                    409,
                )
            trajectory = self._ensure_trajectory_event(student, publication, prior)
            progress = self._get_progress(student.id, publication.id)
            prior.trajectory_event_id = trajectory.event_id
            self.db.commit()
            return VideoEventResult(
                event_id=prior.id, duplicate=True,
                trajectory_event_id=trajectory.event_id,
                trajectory_processing_status=trajectory.processing_status,
                progress=self.progress_view(progress, publication),
            )
        occurred_at = as_utc(payload.occurred_at)
        if occurred_at > utcnow() + timedelta(minutes=5):
            raise VideoServiceError("VIDEO_EVENT_IN_FUTURE", "事件时间不能位于未来", 422)
        progress = self._get_progress(student.id, publication.id, create=True)
        normalized = self._apply_progress(progress, publication, payload)
        interaction = VideoInteractionEvent(
            id=str(uuid4()), publication_id=publication.id,
            student_id=student.id, idempotency_key=idempotency_key,
            request_hash=request_hash,
            event_type=payload.event_type, normalized_payload_json=normalized,
            occurred_at=occurred_at,
        )
        self.db.add(interaction)
        self.db.flush()
        trajectory = self._ensure_trajectory_event(student, publication, interaction)
        interaction.trajectory_event_id = trajectory.event_id
        self.db.commit()
        return VideoEventResult(
            event_id=interaction.id, duplicate=False,
            trajectory_event_id=trajectory.event_id,
            trajectory_processing_status=trajectory.processing_status,
            progress=self.progress_view(progress, publication),
        )

    def _get_progress(
        self,
        student_id: str,
        publication_id: str,
        *,
        create: bool = False,
    ) -> VideoProgress | None:
        progress = self.db.scalar(select(VideoProgress).where(
            VideoProgress.student_id == student_id,
            VideoProgress.publication_id == publication_id,
        ))
        if progress is None and create:
            progress = VideoProgress(
                id=str(uuid4()), publication_id=publication_id,
                student_id=student_id, player_capabilities_json=[],
                active_seconds=0.0, progress_ratio=0.0,
                foreground_ratio=0.0, reliability=0.0, completed=False,
            )
            self.db.add(progress)
            self.db.flush()
        return progress

    def _apply_progress(
        self,
        progress: VideoProgress,
        publication: VideoPublication,
        event: VideoPlayerEventCreate,
    ) -> dict[str, Any]:
        snapshot = publication.resource_snapshot_json
        duration = snapshot.get("duration_seconds")
        duration = float(duration) if isinstance(duration, (int, float)) and duration > 0 else None
        capabilities = set(progress.player_capabilities_json or [])
        capabilities.add(event.player_signal)
        progress.player_capabilities_json = sorted(capabilities)
        signal_weight = {
            "official_sdk": 0.95,
            "heartbeat": 0.65,
            "chapter": 0.20,
            "page_only": 0.05,
        }[event.player_signal]
        reliable_playback = event.player_signal in {"official_sdk", "heartbeat"}
        active_delta = event.active_seconds_delta if reliable_playback and event.foreground_ratio >= 0.55 else 0.0
        if event.event_type in {"playback", "heartbeat", "completed"} and reliable_playback:
            progress.active_seconds = max(0.0, progress.active_seconds + active_delta)
            if event.position_seconds is not None:
                bounded = min(event.position_seconds, duration) if duration else event.position_seconds
                progress.max_position_seconds = max(progress.max_position_seconds or 0.0, bounded)
                if duration:
                    progress.progress_ratio = max(progress.progress_ratio, min(1.0, bounded / duration))
        if event.event_type == "chapter_opened":
            chapter_ids = {item.get("id") for item in snapshot.get("chapters", []) if isinstance(item, dict)}
            if event.chapter_id not in chapter_ids:
                raise VideoServiceError(
                    "VIDEO_CHAPTER_NOT_VERIFIED", "该视频没有可核验的章节时间证据", 422,
                )
        progress.foreground_ratio = max(progress.foreground_ratio, event.foreground_ratio)
        progress.reliability = max(
            progress.reliability,
            signal_weight * event.foreground_ratio if reliable_playback else signal_weight,
        )
        if (
            event.event_type == "completed"
            and reliable_playback
            and progress.active_seconds >= 20
            and progress.progress_ratio >= 0.85
            and event.foreground_ratio >= 0.55
        ):
            progress.completed = True
        progress.last_event_at = as_utc(event.occurred_at)
        progress.updated_at = utcnow()
        return {
            "event_type": event.event_type,
            "player_signal": event.player_signal,
            "position_seconds": event.position_seconds,
            "active_seconds_delta": active_delta,
            "active_seconds": progress.active_seconds,
            "duration_seconds": duration or 0.0,
            "progress_ratio": progress.progress_ratio,
            "foreground_ratio": event.foreground_ratio,
            "reliability": progress.reliability,
            "completed": progress.completed,
            "chapter_id": event.chapter_id,
            "feedback": event.feedback,
            "algorithm_version": PROGRESS_ALGORITHM_VERSION,
        }

    def _ensure_trajectory_event(
        self,
        student: User,
        publication: VideoPublication,
        event: VideoInteractionEvent,
    ):
        normalized = event.normalized_payload_json
        mapping = {
            "playback": "video_progressed",
            "heartbeat": "video_progressed",
            "completed": "video_completed",
            "opened": "video_opened",
            "chapter_opened": "video_chapter_viewed",
            "feedback": "video_feedback",
        }
        concept_rows = list(self.db.scalars(select(VideoPublicationConcept).where(
            VideoPublicationConcept.publication_id == publication.id,
        )).all())
        command = EventCommand(
            idempotency_key=f"a4:{publication.id}:{event.idempotency_key}",
            event_type=mapping[event.event_type],
            object_type="video_publication", object_id=publication.id,
            concepts=[ConceptContribution(item.concept_id, item.support) for item in concept_rows],
            outcome=None, difficulty=None, hint_level=None, attempt_no=None,
            completion=float(normalized.get("progress_ratio", 0.0)),
            strategy=None,
            upstream_confidence=float(normalized.get("reliability", 0.0)),
            alignment_confidence=1.0,
            occurred_at=event.occurred_at,
            correction_of_event_id=None,
            payload={
                "active_seconds": normalized.get("active_seconds", 0.0),
                "duration_seconds": normalized.get("duration_seconds", 0.0),
                "foreground_ratio": normalized.get("foreground_ratio", 0.0),
                "player_signal": normalized.get("player_signal"),
                "feedback": normalized.get("feedback"),
                "a4_algorithm_version": PROGRESS_ALGORITHM_VERSION,
            },
        )
        return TrajectoryService(self.db).ingest(
            student=student, course_id=publication.course_id, command=command,
        )

    def progress_view(
        self,
        progress: VideoProgress | None,
        publication: VideoPublication,
    ) -> VideoProgressView:
        if progress is None:
            return VideoProgressView(
                publication_id=publication.id, active_seconds=0.0,
                max_position_seconds=None, progress_ratio=0.0,
                foreground_ratio=0.0, reliability=0.0, completed=False,
                evidence_scope="resource_interaction_only", last_event_at=None,
            )
        return VideoProgressView(
            publication_id=publication.id,
            active_seconds=round(progress.active_seconds, 3),
            max_position_seconds=progress.max_position_seconds,
            progress_ratio=round(progress.progress_ratio, 6),
            foreground_ratio=round(progress.foreground_ratio, 4),
            reliability=round(progress.reliability, 4),
            completed=progress.completed,
            evidence_scope=(
                "verified_playback"
                if any(item in {"official_sdk", "heartbeat"} for item in progress.player_capabilities_json)
                else "resource_interaction_only"
            ),
            last_event_at=progress.last_event_at,
        )


def job_view(job: VideoSearchJob) -> VideoSearchJobView:
    return VideoSearchJobView(
        id=job.id, course_id=job.course_id, source_mode=job.source_mode,
        requested_profile_id=job.requested_profile_id,
        actual_profile_id=job.actual_profile_id,
        deterministic_degrade=job.deterministic_degrade,
        status=job.status, provider_statuses=job.provider_status_json,
        warnings=job.warnings_json, candidate_count=job.candidate_count,
        safe_error_code=job.safe_error_code,
        safe_error_message=job.safe_error_message,
        created_at=job.created_at, completed_at=job.completed_at,
    )


def candidate_view(
    db: Session,
    candidate: VideoCandidateRecord,
    teacher_id: str,
) -> VideoCandidateView:
    previewed = bool(db.scalar(select(func.count()).select_from(VideoPreviewEvent).where(
        VideoPreviewEvent.candidate_id == candidate.id,
        VideoPreviewEvent.teacher_id == teacher_id,
    )))
    return VideoCandidateView(
        id=candidate.id, job_id=candidate.job_id,
        provider=candidate.provider, external_id=candidate.external_id,
        canonical_url=candidate.canonical_url, embed_url=candidate.embed_url,
        title=candidate.title, creator=candidate.creator,
        description=candidate.description, thumbnail_url=candidate.thumbnail_url,
        duration_seconds=candidate.duration_seconds,
        content_type=candidate.content_type, content_kind=candidate.content_kind,
        license_name=candidate.license_name, license_url=candidate.license_url,
        scores=VideoScoresView(**candidate.scores_json),
        matched_topic_ids=candidate.matched_topic_ids,
        evidence_level=candidate.evidence_level,
        verified_scope=candidate.verified_scope,
        uncertainty_reason=candidate.uncertainty_reason,
        verification_status=candidate.verification_status,
        lifecycle_status=candidate.lifecycle_status,
        rank=candidate.rank, verified_at=candidate.verified_at,
        verification_expires_at=candidate.verification_expires_at,
        preview_required=candidate.evidence_level == "E1",
        previewed=previewed,
    )


def preview_view(event: VideoPreviewEvent, *, duplicate: bool) -> PreviewEventView:
    return PreviewEventView(
        id=event.id, candidate_id=event.candidate_id,
        action=event.action, created_at=event.created_at, duplicate=duplicate,
    )


def link_check_view(check: VideoLinkCheck) -> LinkCheckView:
    return LinkCheckView(
        id=check.id, candidate_id=check.candidate_id,
        status=check.status, safe_error_code=check.safe_error_code,
        final_url=check.final_url, checked_at=check.checked_at,
    )
