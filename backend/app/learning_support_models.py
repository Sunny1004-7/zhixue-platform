from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import utcnow


class TutorConversation(Base):
    __tablename__ = "tutor_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    selected_mode: Mapped[str] = mapped_column(String(24), default="adaptive")
    requested_profile_id: Mapped[str] = mapped_column(String(80))
    experience_mode: Mapped[str] = mapped_column(String(16), default="manual")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, index=True
    )


class TutorTurn(Base):
    __tablename__ = "tutor_turns"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "client_turn_id", name="uq_tutor_turn_client_id"
        ),
        CheckConstraint("version_after = version_before + 1", name="ck_tutor_turn_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("tutor_conversations.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    client_turn_id: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    selected_mode: Mapped[str] = mapped_column(String(24))
    requested_profile_id: Mapped[str] = mapped_column(String(80))
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    read_answer_history: Mapped[bool] = mapped_column(Boolean, default=False)
    read_conversation_history: Mapped[bool] = mapped_column(Boolean, default=False)
    experience_mode: Mapped[str] = mapped_column(String(16))
    resolved_concept_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    strategy_plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    experience_decision_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version_before: Mapped[int] = mapped_column(Integer)
    version_after: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), index=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    trajectory_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_events.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TutorMessage(Base):
    __tablename__ = "tutor_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "ordinal", name="uq_tutor_message_ordinal"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("tutor_conversations.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[str | None] = mapped_column(
        ForeignKey("tutor_turns.id", ondelete="CASCADE"), nullable=True, index=True
    )
    student_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    strategy: Mapped[str | None] = mapped_column(String(24), nullable=True)
    checkpoint_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    visual_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    inline_practice_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TutorToolCall(Base):
    __tablename__ = "tutor_tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    turn_id: Mapped[str] = mapped_column(
        ForeignKey("tutor_turns.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    tool_kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    result_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TutorMemory(Base):
    __tablename__ = "tutor_memories"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_tutor_memory_confidence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    memory_kind: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    conflict_group: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TutorMemorySource(Base):
    __tablename__ = "tutor_memory_sources"
    __table_args__ = (
        UniqueConstraint(
            "memory_id", "source_kind", "source_id", name="uq_tutor_memory_source"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("tutor_memories.id", ondelete="CASCADE"), index=True
    )
    source_kind: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("tutor_conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    turn_id: Mapped[str | None] = mapped_column(
        ForeignKey("tutor_turns.id", ondelete="CASCADE"), nullable=True
    )
    evidence_quote_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TutorExperience(Base):
    __tablename__ = "tutor_experiences"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "course_id", "idempotency_key",
            name="uq_tutor_experience_idempotency",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_tutor_experience_confidence"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(180))
    context: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    evidence_summary: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    generation_mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TutorExperienceSource(Base):
    __tablename__ = "tutor_experience_sources"
    __table_args__ = (
        UniqueConstraint(
            "experience_id", "source_kind", "source_id",
            name="uq_tutor_experience_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experience_id: Mapped[str] = mapped_column(
        ForeignKey("tutor_experiences.id", ondelete="CASCADE"), index=True
    )
    source_kind: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DecisionSnapshot(Base):
    __tablename__ = "decision_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_state_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64), unique=True)
    student_count: Mapped[int] = mapped_column(Integer)
    aggregate_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AttentionScoreSnapshot(Base):
    __tablename__ = "attention_score_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "student_id", name="uq_attention_snapshot_student"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_attention_score"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_attention_confidence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("decision_snapshots.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    raw_components_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    normalized_components_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AudienceDraft(Base):
    __tablename__ = "audience_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(24), index=True)
    resource_id: Mapped[str] = mapped_column(String(80), index=True)
    resource_version: Mapped[int] = mapped_column(Integer)
    resource_hash: Mapped[str] = mapped_column(String(64))
    resource_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    audience_mode: Mapped[str] = mapped_column(String(24), index=True)
    selected_concept_ids_json: Mapped[list[str]] = mapped_column(JSON)
    selected_states_json: Mapped[list[str]] = mapped_column(JSON)
    teacher_selected_student_ids_json: Mapped[list[str]] = mapped_column(JSON)
    suggested_student_ids_json: Mapped[list[str]] = mapped_column(JSON)
    final_student_ids_json: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="previewed", index=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AudienceCandidate(Base):
    __tablename__ = "audience_candidates"
    __table_args__ = (
        UniqueConstraint("draft_id", "student_id", name="uq_audience_candidate_student"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        ForeignKey("audience_drafts.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    suggested: Mapped[bool] = mapped_column(Boolean)
    selected: Mapped[bool] = mapped_column(Boolean)
    override_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    matched_concept_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    matched_states_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    reason_codes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class DecisionPublication(Base):
    __tablename__ = "decision_publications"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "course_id", "idempotency_key",
            name="uq_decision_publication_idempotency",
        ),
        UniqueConstraint("draft_id", name="uq_decision_publication_draft"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        ForeignKey("audience_drafts.id", ondelete="RESTRICT"), index=True
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(24), index=True)
    resource_id: Mapped[str] = mapped_column(String(80), index=True)
    resource_version: Mapped[int] = mapped_column(Integer)
    resource_hash: Mapped[str] = mapped_column(String(64))
    resource_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    audience_mode: Mapped[str] = mapped_column(String(24), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="published", index=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), unique=True)
    algorithm_version: Mapped[str] = mapped_column(String(40))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DecisionPublicationConcept(Base):
    __tablename__ = "decision_publication_concepts"
    __table_args__ = (
        UniqueConstraint(
            "publication_id", "concept_id", name="uq_decision_publication_concept"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        ForeignKey("decision_publications.id", ondelete="CASCADE"), index=True
    )
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)


class DecisionPublicationRecipient(Base):
    __tablename__ = "decision_publication_recipients"
    __table_args__ = (
        UniqueConstraint(
            "publication_id", "student_id", name="uq_decision_publication_recipient"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        ForeignKey("decision_publications.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    suggested: Mapped[bool] = mapped_column(Boolean)
    override_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    matched_concept_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    matched_states_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    reason_codes_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class ResourceExposure(Base):
    __tablename__ = "resource_exposures"
    __table_args__ = (
        UniqueConstraint(
            "publication_id", "student_id", name="uq_resource_exposure_recipient"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        ForeignKey("decision_publications.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    delivery_status: Mapped[str] = mapped_column(String(24), default="delivered", index=True)
    personalized: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_events.id", ondelete="SET NULL"), nullable=True
    )
    completion_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_events.id", ondelete="SET NULL"), nullable=True
    )


class PersonalizedResourceJob(Base):
    __tablename__ = "personalized_resource_jobs"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "course_id", "idempotency_key",
            name="uq_personalized_resource_job_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    resource_type: Mapped[str] = mapped_column(String(24), index=True)
    concept_ids_json: Mapped[list[str]] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    upstream_job_id: Mapped[str] = mapped_column(String(80), index=True)
    upstream_status_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
