from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import utcnow


class VideoSearchJob(Base):
    __tablename__ = "video_search_jobs"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "course_id", "idempotency_key",
            name="uq_video_search_job_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True,
    )
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    source_mode: Mapped[str] = mapped_column(String(24), index=True)
    source_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    topic_snapshot_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    teaching_intent: Mapped[str] = mapped_column(String(500), default="")
    language: Mapped[str] = mapped_column(String(16), default="zh-CN")
    requested_profile_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actual_profile_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    deterministic_degrade: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(24), default="created", index=True)
    provider_status_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VideoCandidateRecord(Base):
    __tablename__ = "video_candidates"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "provider", "external_id", name="uq_video_candidate_job_external",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("video_search_jobs.id", ondelete="CASCADE"), index=True,
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str] = mapped_column(String(240))
    canonical_url: Mapped[str] = mapped_column(String(2048))
    embed_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    creator: Mapped[str | None] = mapped_column(String(240), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    thumbnail_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content_kind: Mapped[str] = mapped_column(String(24), default="video", index=True)
    license_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    license_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    scores_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    matched_topic_ids: Mapped[list[str]] = mapped_column(JSON)
    evidence_level: Mapped[str] = mapped_column(String(8), default="E1")
    verified_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    uncertainty_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    critical_metadata_hash: Mapped[str] = mapped_column(String(64))
    verification_status: Mapped[str] = mapped_column(String(32), index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="ranked", index=True)
    rank: Mapped[int] = mapped_column(Integer)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verification_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoCandidateConcept(Base):
    __tablename__ = "video_candidate_concepts"
    __table_args__ = (
        UniqueConstraint("candidate_id", "concept_id", name="uq_video_candidate_concept"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("video_candidates.id", ondelete="CASCADE"), index=True,
    )
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    support: Mapped[float] = mapped_column(Float)


class VideoPreviewEvent(Base):
    __tablename__ = "video_preview_events"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "candidate_id", "idempotency_key",
            name="uq_video_preview_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("video_candidates.id", ondelete="CASCADE"), index=True,
    )
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoLinkCheck(Base):
    __tablename__ = "video_link_checks"
    __table_args__ = (
        UniqueConstraint("candidate_id", "idempotency_key", name="uq_video_link_check_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("video_candidates.id", ondelete="CASCADE"), index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32), index=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    final_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    critical_metadata_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoPublication(Base):
    __tablename__ = "video_publications"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "course_id", "idempotency_key",
            name="uq_video_publication_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True,
    )
    candidate_id: Mapped[str] = mapped_column(ForeignKey("video_candidates.id"), index=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    intervention_plan_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    audience_spec_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    resource_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoPublicationConcept(Base):
    __tablename__ = "video_publication_concepts"
    __table_args__ = (
        UniqueConstraint("publication_id", "concept_id", name="uq_video_publication_concept"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        ForeignKey("video_publications.id", ondelete="CASCADE"), index=True,
    )
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    support: Mapped[float] = mapped_column(Float)


class PublicationRecipient(Base):
    __tablename__ = "publication_recipients"
    __table_args__ = (
        UniqueConstraint("publication_id", "student_id", name="uq_publication_recipient"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        ForeignKey("video_publications.id", ondelete="CASCADE"), index=True,
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    reason_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoProgress(Base):
    __tablename__ = "video_progress"
    __table_args__ = (
        UniqueConstraint("publication_id", "student_id", name="uq_video_progress_student"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        ForeignKey("video_publications.id", ondelete="CASCADE"), index=True,
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    player_capabilities_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_position_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    progress_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    foreground_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    reliability: Mapped[float] = mapped_column(Float, default=0.0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoInteractionEvent(Base):
    __tablename__ = "video_interaction_events"
    __table_args__ = (
        UniqueConstraint(
            "publication_id", "student_id", "idempotency_key",
            name="uq_video_interaction_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        ForeignKey("video_publications.id", ondelete="CASCADE"), index=True,
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    normalized_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    trajectory_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_events.id", ondelete="SET NULL"), nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
