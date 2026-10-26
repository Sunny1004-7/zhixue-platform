from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, validates

from .database import Base
from .domains.knowledge_graph.names import normalize_concept_name


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(80))
    initials: Mapped[str] = mapped_column(String(12))
    profile_title: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    short_title: Mapped[str] = mapped_column(String(40))
    term: Mapped[str] = mapped_column(String(40))
    accent: Mapped[str] = mapped_column(String(24))
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)


class CourseEnrollment(Base):
    __tablename__ = "course_enrollments"
    __table_args__ = (UniqueConstraint("student_id", "course_id", name="uq_enrollment_student_course"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    mastery: Mapped[float] = mapped_column(Float)
    progress: Mapped[float] = mapped_column(Float)
    weekly_minutes: Mapped[int] = mapped_column(Integer)
    streak_days: Mapped[int] = mapped_column(Integer)
    goal: Mapped[str] = mapped_column(String(240))
    focus: Mapped[str] = mapped_column(String(160))
    focus_summary: Mapped[str] = mapped_column(Text)
    resource_completion: Mapped[float] = mapped_column(Float)
    recent_accuracy: Mapped[float] = mapped_column(Float)
    mastery_delta: Mapped[str] = mapped_column(String(40))
    resource_delta: Mapped[str] = mapped_column(String(60))
    accuracy_delta: Mapped[str] = mapped_column(String(60))
    streak_delta: Mapped[str] = mapped_column(String(60))
    mastery_trend: Mapped[list[int]] = mapped_column(JSON)
    resource_trend: Mapped[list[int]] = mapped_column(JSON)
    accuracy_trend: Mapped[list[int]] = mapped_column(JSON)
    streak_trend: Mapped[list[int]] = mapped_column(JSON)
    weekly_activity: Mapped[list[int]] = mapped_column(JSON)
    daily_average: Mapped[int] = mapped_column(Integer)
    efficient_sessions: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Concept(Base):
    __tablename__ = "concepts"
    __table_args__ = (
        UniqueConstraint("course_id", "name", name="uq_concept_course_name"),
        UniqueConstraint(
            "course_id", "normalized_name", name="uq_concept_course_normalized_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    normalized_name: Mapped[str] = mapped_column(String(240))
    sort_order: Mapped[int] = mapped_column(Integer)

    @validates("name")
    def normalize_name(self, _key: str, value: str) -> str:
        self.normalized_name = normalize_concept_name(value)
        return value


class KnowledgeState(Base):
    __tablename__ = "knowledge_states"
    __table_args__ = (UniqueConstraint("student_id", "concept_id", name="uq_state_student_concept"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), index=True)
    mastery: Mapped[float] = mapped_column(Float)
    correct_rate: Mapped[float] = mapped_column(Float)
    evidence_count: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    baseline_correct_rate: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_alpha: Mapped[float] = mapped_column(Float, default=1.0)
    baseline_beta: Mapped[float] = mapped_column(Float, default=1.0)
    alpha: Mapped[float] = mapped_column(Float, default=1.0)
    beta: Mapped[float] = mapped_column(Float, default=1.0)
    uncertainty: Mapped[float] = mapped_column(Float, default=1.0)
    effective_evidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(24), default="unseen")
    trend_30d: Mapped[float] = mapped_column(Float, default=0.0)
    last_evidence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_version: Mapped[str] = mapped_column(String(128), default="eglt-0.1.0")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningResource(Base):
    __tablename__ = "learning_resources"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    resource_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(240))
    detail: Mapped[str] = mapped_column(String(300))
    progress_completed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer)
    published: Mapped[bool] = mapped_column(Boolean, default=True)


class LearningActivity(Base):
    __tablename__ = "learning_activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    detail: Mapped[str] = mapped_column(String(300))
    activity_type: Mapped[str] = mapped_column(String(24))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LearningEvent(Base):
    __tablename__ = "learning_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    object_type: Mapped[str] = mapped_column(String(80))
    object_id: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_type: Mapped[str] = mapped_column(String(32), default="real")
    outcome: Mapped[float | None] = mapped_column(Float, nullable=True)
    difficulty: Mapped[float | None] = mapped_column(Float, nullable=True)
    hint_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy: Mapped[str | None] = mapped_column(String(40), nullable=True)
    upstream_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    alignment_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    evidence_success: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_reliability: Mapped[float | None] = mapped_column(Float, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(32), default="accepted")
    correction_of_event_id: Mapped[str | None] = mapped_column(ForeignKey("learning_events.id"), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(24), default="learning-event-1.0")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("student_id", "course_id", "idempotency_key", name="uq_learning_event_idempotency"),
    )


class EventConcept(Base):
    __tablename__ = "event_concepts"
    __table_args__ = (UniqueConstraint("event_id", "concept_id", name="uq_event_concept"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("learning_events.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    contribution_weight: Mapped[float] = mapped_column(Float)


class MasteryEvidence(Base):
    __tablename__ = "mastery_evidence"
    __table_args__ = (UniqueConstraint("event_id", "concept_id", name="uq_mastery_evidence_event_concept"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state_id: Mapped[str] = mapped_column(ForeignKey("knowledge_states.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("learning_events.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    contribution_weight: Mapped[float] = mapped_column(Float)
    success: Mapped[float] = mapped_column(Float)
    reliability: Mapped[float] = mapped_column(Float)
    mastery_before: Mapped[float] = mapped_column(Float)
    mastery_after: Mapped[float] = mapped_column(Float)
    delta: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeGraph(Base):
    __tablename__ = "knowledge_graphs"
    __table_args__ = (UniqueConstraint("course_id", "title", name="uq_graph_course_title"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    working_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    published_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GraphRevision(Base):
    __tablename__ = "graph_revisions"
    __table_args__ = (UniqueConstraint("graph_id", "revision_no", name="uq_graph_revision_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    graph_id: Mapped[str] = mapped_column(ForeignKey("knowledge_graphs.id", ondelete="CASCADE"), index=True)
    parent_revision_id: Mapped[str | None] = mapped_column(ForeignKey("graph_revisions.id"), nullable=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(24), default="new")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    source_summary: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (
        UniqueConstraint("revision_id", "concept_id", name="uq_graph_node_revision_concept"),
        UniqueConstraint("revision_id", "label", name="uq_graph_node_revision_label"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("graph_revisions.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    node_type: Mapped[str] = mapped_column(String(24), default="core")
    definition: Mapped[str] = mapped_column(Text, default="")
    key_point: Mapped[str] = mapped_column(Text, default="")
    misconception: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(32), default="teacher")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    position_x: Mapped[float] = mapped_column(Float, default=0.0)
    position_y: Mapped[float] = mapped_column(Float, default=0.0)


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint("revision_id", "from_node_id", "to_node_id", "relation", name="uq_graph_edge_semantics"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("graph_revisions.id", ondelete="CASCADE"), index=True)
    from_node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"), index=True)
    to_node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"), index=True)
    relation: Mapped[str] = mapped_column(String(24))
    origin: Mapped[str] = mapped_column(String(32), default="teacher")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class GraphQualityReport(Base):
    __tablename__ = "graph_quality_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("graph_revisions.id", ondelete="CASCADE"), index=True)
    hard_pass: Mapped[bool] = mapped_column(Boolean)
    quality_score: Mapped[float] = mapped_column(Float)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    issues_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    validator_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceAsset(Base):
    __tablename__ = "source_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(12))
    declared_mime: Mapped[str] = mapped_column(String(120))
    detected_mime: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expected_size: Mapped[int] = mapped_column(Integer)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="prepared", index=True)
    security_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    rejection_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ParsedDocument(Base):
    __tablename__ = "parsed_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("source_assets.id", ondelete="CASCADE"), unique=True, index=True
    )
    parser_name: Mapped[str] = mapped_column(String(40))
    parser_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32), default="parsed", index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    segment_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    text_length: Mapped[int] = mapped_column(Integer, default=0)
    warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "sequence_no", name="uq_chunk_document_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_documents.id", ondelete="CASCADE"), index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer)
    locator_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    section_title: Mapped[str] = mapped_column(String(255), default="")
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    token_estimate: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))


class EvidenceSpan(Base):
    __tablename__ = "evidence_spans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), index=True
    )
    start_char: Mapped[int] = mapped_column(Integer)
    end_char: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    locator_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))


class GraphEvidenceLink(Base):
    __tablename__ = "graph_evidence_links"
    __table_args__ = (
        CheckConstraint(
            "(node_id IS NOT NULL AND edge_id IS NULL) OR "
            "(node_id IS NULL AND edge_id IS NOT NULL)",
            name="ck_graph_evidence_one_target",
        ),
        UniqueConstraint(
            "revision_id", "node_id", "edge_id", "evidence_span_id", "source_kind",
            name="uq_graph_evidence_target_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("graph_revisions.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[str | None] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    edge_id: Mapped[str | None] = mapped_column(
        ForeignKey("graph_edges.id", ondelete="CASCADE"), nullable=True, index=True
    )
    evidence_span_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_spans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_kind: Mapped[str] = mapped_column(String(32), index=True)
    assertion_note: Mapped[str] = mapped_column(String(1000), default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source_model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlignmentRun(Base):
    __tablename__ = "alignment_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(24))
    source_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    mode: Mapped[str] = mapped_column(String(32), default="concept_alignment")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    parser_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ontology_version: Mapped[str] = mapped_column(String(40))
    aligner_version: Mapped[str] = mapped_column(String(40))
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlignmentMention(Base):
    __tablename__ = "alignment_mentions"
    __table_args__ = (UniqueConstraint("run_id", "ordinal", name="uq_alignment_mention_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("alignment_runs.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(String(500))
    normalized_text: Mapped[str] = mapped_column(String(500), index=True)
    context: Mapped[str] = mapped_column(Text, default="")
    evidence_span_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_spans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)


class AlignmentCandidate(Base):
    __tablename__ = "alignment_candidates"
    __table_args__ = (
        UniqueConstraint("mention_id", "concept_id", name="uq_alignment_candidate_concept"),
        UniqueConstraint("mention_id", "rank", name="uq_alignment_candidate_rank"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mention_id: Mapped[str] = mapped_column(
        ForeignKey("alignment_mentions.id", ondelete="CASCADE"), index=True
    )
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    lexical_score: Mapped[float] = mapped_column(Float)
    context_score: Mapped[float] = mapped_column(Float)
    graph_score: Mapped[float] = mapped_column(Float)
    final_score: Mapped[float] = mapped_column(Float)
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)


class AlignmentReview(Base):
    __tablename__ = "alignment_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mention_id: Mapped[str] = mapped_column(
        ForeignKey("alignment_mentions.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    decision: Mapped[str | None] = mapped_column(String(24), nullable=True)
    selected_concept_id: Mapped[str | None] = mapped_column(
        ForeignKey("concepts.id"), nullable=True, index=True
    )
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Derivation(Base):
    __tablename__ = "derivations"
    __table_args__ = (
        UniqueConstraint("source_asset_id", "derived_type", "derived_id", name="uq_derivation_target"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_asset_id: Mapped[str] = mapped_column(
        ForeignKey("source_assets.id", ondelete="CASCADE"), index=True
    )
    derived_type: Mapped[str] = mapped_column(String(64), index=True)
    derived_id: Mapped[str] = mapped_column(String(80), index=True)
    relation: Mapped[str] = mapped_column(String(40), default="derived_from")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeletionJob(Base):
    __tablename__ = "deletion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_asset_id: Mapped[str] = mapped_column(
        ForeignKey("source_assets.id", ondelete="CASCADE"), index=True
    )
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    invalidated_derivations: Mapped[int] = mapped_column(Integer, default=0)
    storage_removed: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelProfile(Base):
    __tablename__ = "model_profiles"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    task_kinds: Mapped[list[str]] = mapped_column(JSON)
    config_revision: Mapped[str] = mapped_column(String(40))


class ModelProfileRevision(Base):
    __tablename__ = "model_profile_revisions"
    __table_args__ = (
        UniqueConstraint("profile_id", "revision_no", name="uq_model_profile_revision_no"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("model_profiles.id", ondelete="CASCADE"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    provider_kind: Mapped[str] = mapped_column(String(40))
    credential_ref: Mapped[str] = mapped_column(String(120))
    endpoint_ref: Mapped[str] = mapped_column(String(120))
    model_id_ref: Mapped[str] = mapped_column(String(120))
    capabilities_json: Mapped[list[str]] = mapped_column(JSON)
    data_region: Mapped[str] = mapped_column(String(40), default="configurable")
    retention_policy: Mapped[str] = mapped_column(String(80), default="provider_configured")
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaskPolicy(Base):
    __tablename__ = "task_policies"
    __table_args__ = (UniqueConstraint("task_kind", "version", name="uq_task_policy_version"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    task_kind: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(40))
    required_capabilities_json: Mapped[list[str]] = mapped_column(JSON)
    selection_mode: Mapped[str] = mapped_column(String(32), default="required")
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=45.0)
    output_schema_version: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("task_kind", "version", name="uq_prompt_template_version"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    task_kind: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(40))
    system_template: Mapped[str] = mapped_column(Text)
    user_template: Mapped[str] = mapped_column(Text)
    template_hash: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelRun(Base):
    __tablename__ = "model_runs"
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "course_id", "task_kind", "idempotency_key",
            name="uq_model_run_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    task_kind: Mapped[str] = mapped_column(String(80), index=True)
    requested_profile_id: Mapped[str] = mapped_column(String(80))
    actual_profile_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_model_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    task_policy_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32), index=True)
    fallback_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    audit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_template_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelAttempt(Base):
    __tablename__ = "model_attempts"
    __table_args__ = (UniqueConstraint("run_id", "attempt_no", name="uq_model_attempt_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("model_runs.id", ondelete="CASCADE"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    actual_profile_id: Mapped[str] = mapped_column(String(80))
    provider_model_id: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32), index=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StructuredValidation(Base):
    __tablename__ = "structured_validations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("model_runs.id", ondelete="CASCADE"), index=True)
    schema_version: Mapped[str] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column(Boolean, index=True)
    errors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelQualityReport(Base):
    __tablename__ = "model_quality_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("model_runs.id", ondelete="CASCADE"), index=True)
    hard_pass: Mapped[bool] = mapped_column(Boolean, index=True)
    gate_version: Mapped[str] = mapped_column(String(64))
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    issues_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GraphExtractionArtifact(Base):
    __tablename__ = "graph_extraction_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    graph_id: Mapped[str] = mapped_column(ForeignKey("knowledge_graphs.id", ondelete="CASCADE"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("graph_revisions.id", ondelete="CASCADE"), index=True)
    alignment_run_id: Mapped[str] = mapped_column(ForeignKey("alignment_runs.id", ondelete="RESTRICT"), index=True)
    model_run_id: Mapped[str] = mapped_column(ForeignKey("model_runs.id", ondelete="RESTRICT"), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="awaiting_review", index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    base_revision_version: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GraphExtractionProposal(Base):
    __tablename__ = "graph_extraction_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("graph_extraction_artifacts.id", ondelete="CASCADE"), index=True
    )
    proposal_kind: Mapped[str] = mapped_column(String(24), index=True)
    concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    from_concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    to_concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    relation: Mapped[str | None] = mapped_column(String(24), nullable=True)
    evidence_span_ids: Mapped[list[str]] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str] = mapped_column(String(500), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GraphSemanticReviewArtifact(Base):
    __tablename__ = "graph_semantic_review_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    graph_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_graphs.id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("graph_revisions.id", ondelete="CASCADE"), index=True
    )
    model_run_id: Mapped[str] = mapped_column(
        ForeignKey("model_runs.id", ondelete="RESTRICT"), unique=True
    )
    base_revision_version: Mapped[int] = mapped_column(Integer)
    independence_status: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="awaiting_review", index=True)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GraphSemanticReviewIssue(Base):
    __tablename__ = "graph_semantic_review_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("graph_semantic_review_artifacts.id", ondelete="CASCADE"), index=True
    )
    issue_code: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    evidence_span_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    claim: Mapped[str] = mapped_column(String(1000))
    suggestion: Mapped[str] = mapped_column(String(1000), default="")
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str] = mapped_column(String(500), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuestionBlueprint(Base):
    __tablename__ = "question_blueprints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    owner_type: Mapped[str] = mapped_column(String(16), index=True)
    source_method: Mapped[str] = mapped_column(String(24), index=True)
    difficulty_mode: Mapped[str] = mapped_column(String(24))
    requested_profile_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    total: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="compiled", index=True)
    compiler_version: Mapped[str] = mapped_column(String(40), default="traceq-blueprint-1.0.0")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BlueprintCell(Base):
    __tablename__ = "blueprint_cells"
    __table_args__ = (
        UniqueConstraint("blueprint_id", "concept_id", "question_type", name="uq_blueprint_cell"),
        CheckConstraint("count >= 0", name="ck_blueprint_cell_count_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    blueprint_id: Mapped[str] = mapped_column(ForeignKey("question_blueprints.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    question_type: Mapped[str] = mapped_column(String(24), index=True)
    count: Mapped[int] = mapped_column(Integer)
    difficulty_target: Mapped[float] = mapped_column(Float)
    cognitive_level: Mapped[str] = mapped_column(String(24), default="understand")
    position: Mapped[int] = mapped_column(Integer)


class QuestionSet(Base):
    __tablename__ = "question_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    owner_student_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    visibility: Mapped[str] = mapped_column(String(24), default="private", index=True)
    working_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    published_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class QuestionSetRevision(Base):
    __tablename__ = "question_set_revisions"
    __table_args__ = (UniqueConstraint("question_set_id", "revision_no", name="uq_question_set_revision_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_set_id: Mapped[str] = mapped_column(ForeignKey("question_sets.id", ondelete="CASCADE"), index=True)
    parent_revision_id: Mapped[str | None] = mapped_column(ForeignKey("question_set_revisions.id"), nullable=True)
    blueprint_id: Mapped[str | None] = mapped_column(ForeignKey("question_blueprints.id"), nullable=True, index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    quality_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    source_kind: Mapped[str] = mapped_column(String(32), default="model")
    source_summary: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("revision_id", "position", name="uq_question_revision_position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("question_set_revisions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    question_type: Mapped[str] = mapped_column(String(24), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    answer_spec_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    rubric_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    cognitive_level: Mapped[str] = mapped_column(String(24), default="understand")
    difficulty_prior: Mapped[float] = mapped_column(Float, default=0.5)
    difficulty_calibrated: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuestionOption(Base):
    __tablename__ = "question_options"
    __table_args__ = (UniqueConstraint("question_id", "position", name="uq_question_option_position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    misconception_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class QuestionConcept(Base):
    __tablename__ = "question_concepts"
    __table_args__ = (UniqueConstraint("question_id", "concept_id", name="uq_question_concept"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"), index=True)
    weight: Mapped[float] = mapped_column(Float)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)


class Hint(Base):
    __tablename__ = "hints"
    __table_args__ = (UniqueConstraint("question_id", "level", name="uq_question_hint_level"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    leakage_score: Mapped[float] = mapped_column(Float, default=0.0)
    information_gain: Mapped[float] = mapped_column(Float, default=0.0)
    validation_status: Mapped[str] = mapped_column(String(24), default="passed")
    validator_version: Mapped[str] = mapped_column(String(40), default="traceq-hint-1.0.0")


class QuestionGenerationRun(Base):
    __tablename__ = "question_generation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    blueprint_id: Mapped[str] = mapped_column(ForeignKey("question_blueprints.id", ondelete="CASCADE"), index=True)
    model_run_id: Mapped[str | None] = mapped_column(ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    requested_profile_id: Mapped[str] = mapped_column(String(80))
    actual_profile_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    safe_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuestionQualityReport(Base):
    __tablename__ = "question_quality_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("question_set_revisions.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=True, index=True)
    hard_pass: Mapped[bool] = mapped_column(Boolean, index=True)
    hard_gates_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    dimension_scores_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    issues_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    validator_version: Mapped[str] = mapped_column(String(40), default="traceq-quality-1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("student_id", "question_id", "idempotency_key", name="uq_attempt_idempotency"),
        UniqueConstraint("student_id", "question_id", "attempt_no", name="uq_attempt_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    question_set_id: Mapped[str] = mapped_column(ForeignKey("question_sets.id", ondelete="CASCADE"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("question_set_revisions.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    answer_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    hint_level: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="submitted", index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), unique=True, index=True)
    score: Mapped[float] = mapped_column(Float)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    grading_mode: Mapped[str] = mapped_column(String(32))
    review_status: Mapped[str] = mapped_column(String(24), index=True)
    feedback_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    grader_model_run_id: Mapped[str | None] = mapped_column(ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True)
    graded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    object_type: Mapped[str] = mapped_column(String(80))
    object_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(24))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
