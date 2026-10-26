"""增加A4视频检索、核验、发布、收件人与学习进度闭环。

Revision ID: 0009_video_recommendation
Revises: 0008_traceq_practice
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_video_recommendation"
down_revision: Union[str, None] = "0008_traceq_practice"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "video_search_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("teacher_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("source_mode", sa.String(24), nullable=False),
        sa.Column("source_payload_json", sa.JSON(), nullable=False),
        sa.Column("topic_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("teaching_intent", sa.String(500), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("requested_profile_id", sa.String(80), nullable=True),
        sa.Column("actual_profile_id", sa.String(80), nullable=True),
        sa.Column("deterministic_degrade", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("provider_status_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("safe_error_message", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("teacher_id", "course_id", "idempotency_key", name="uq_video_search_job_idempotency"),
    )
    _indexes("video_search_jobs", ("course_id", "teacher_id", "source_mode", "status"))

    op.create_table(
        "video_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("video_search_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(240), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        sa.Column("embed_url", sa.String(2048), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("creator", sa.String(240), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.String(2048), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(120), nullable=True),
        sa.Column("content_kind", sa.String(24), nullable=False),
        sa.Column("license_name", sa.String(120), nullable=True),
        sa.Column("license_url", sa.String(2048), nullable=True),
        sa.Column("scores_json", sa.JSON(), nullable=False),
        sa.Column("matched_topic_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_level", sa.String(8), nullable=False),
        sa.Column("verified_scope", sa.JSON(), nullable=False),
        sa.Column("uncertainty_reason", sa.String(500), nullable=True),
        sa.Column("critical_metadata_hash", sa.String(64), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("lifecycle_status", sa.String(32), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "provider", "external_id", name="uq_video_candidate_job_external"),
    )
    _indexes("video_candidates", ("job_id", "course_id", "provider", "content_kind", "verification_status", "lifecycle_status"))

    op.create_table(
        "video_candidate_concepts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("video_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=False),
        sa.Column("support", sa.Float(), nullable=False),
        sa.UniqueConstraint("candidate_id", "concept_id", name="uq_video_candidate_concept"),
    )
    _indexes("video_candidate_concepts", ("candidate_id", "concept_id"))

    op.create_table(
        "video_preview_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("video_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("teacher_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("teacher_id", "candidate_id", "idempotency_key", name="uq_video_preview_idempotency"),
    )
    _indexes("video_preview_events", ("candidate_id", "teacher_id"))

    op.create_table(
        "video_link_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("video_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("final_url", sa.String(2048), nullable=True),
        sa.Column("critical_metadata_hash", sa.String(64), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id", "idempotency_key", name="uq_video_link_check_idempotency"),
    )
    _indexes("video_link_checks", ("candidate_id", "status"))

    op.create_table(
        "video_publications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("video_candidates.id"), nullable=False),
        sa.Column("teacher_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("intervention_plan_id", sa.String(80), nullable=True),
        sa.Column("audience_spec_json", sa.JSON(), nullable=False),
        sa.Column("resource_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("teacher_id", "course_id", "idempotency_key", name="uq_video_publication_idempotency"),
    )
    _indexes("video_publications", ("course_id", "candidate_id", "teacher_id", "status"))

    op.create_table(
        "video_publication_concepts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("publication_id", sa.String(36), sa.ForeignKey("video_publications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=False),
        sa.Column("support", sa.Float(), nullable=False),
        sa.UniqueConstraint("publication_id", "concept_id", name="uq_video_publication_concept"),
    )
    _indexes("video_publication_concepts", ("publication_id", "concept_id"))

    op.create_table(
        "publication_recipients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("publication_id", sa.String(36), sa.ForeignKey("video_publications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason_json", sa.JSON(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("publication_id", "student_id", name="uq_publication_recipient"),
    )
    _indexes("publication_recipients", ("publication_id", "student_id"))

    op.create_table(
        "video_progress",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("publication_id", sa.String(36), sa.ForeignKey("video_publications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("player_capabilities_json", sa.JSON(), nullable=False),
        sa.Column("max_position_seconds", sa.Float(), nullable=True),
        sa.Column("active_seconds", sa.Float(), nullable=False),
        sa.Column("progress_ratio", sa.Float(), nullable=False),
        sa.Column("foreground_ratio", sa.Float(), nullable=False),
        sa.Column("reliability", sa.Float(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("publication_id", "student_id", name="uq_video_progress_student"),
    )
    _indexes("video_progress", ("publication_id", "student_id"))

    op.create_table(
        "video_interaction_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("publication_id", sa.String(36), sa.ForeignKey("video_publications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("normalized_payload_json", sa.JSON(), nullable=False),
        sa.Column("trajectory_event_id", sa.String(36), sa.ForeignKey("learning_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("publication_id", "student_id", "idempotency_key", name="uq_video_interaction_idempotency"),
    )
    _indexes("video_interaction_events", ("publication_id", "student_id", "event_type"))


def downgrade() -> None:
    for table in (
        "video_interaction_events",
        "video_progress",
        "publication_recipients",
        "video_publication_concepts",
        "video_publications",
        "video_link_checks",
        "video_preview_events",
        "video_candidate_concepts",
        "video_candidates",
        "video_search_jobs",
    ):
        op.drop_table(table)
