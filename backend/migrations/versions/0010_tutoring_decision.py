"""增加A5辅导记忆与A6教学决策、定向发布闭环。

Revision ID: 0010_tutoring_decision
Revises: 0009_video_recommendation
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_tutoring_decision"
down_revision: Union[str, None] = "0009_video_recommendation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "tutor_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("selected_mode", sa.String(24), nullable=False),
        sa.Column("requested_profile_id", sa.String(80), nullable=False),
        sa.Column("experience_mode", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("tutor_conversations", ("student_id", "course_id", "updated_at"))

    op.create_table(
        "tutor_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("tutor_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_turn_id", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("selected_mode", sa.String(24), nullable=False),
        sa.Column("requested_profile_id", sa.String(80), nullable=False),
        sa.Column("model_run_id", sa.String(36), sa.ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("read_answer_history", sa.Boolean(), nullable=False),
        sa.Column("read_conversation_history", sa.Boolean(), nullable=False),
        sa.Column("experience_mode", sa.String(16), nullable=False),
        sa.Column("resolved_concept_ids_json", sa.JSON(), nullable=False),
        sa.Column("strategy_plan_json", sa.JSON(), nullable=False),
        sa.Column("experience_decision_json", sa.JSON(), nullable=False),
        sa.Column("quality_json", sa.JSON(), nullable=False),
        sa.Column("version_before", sa.Integer(), nullable=False),
        sa.Column("version_after", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("safe_error_message", sa.String(500), nullable=True),
        sa.Column("trajectory_event_id", sa.String(36), sa.ForeignKey("learning_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version_after = version_before + 1", name="ck_tutor_turn_version"),
        sa.UniqueConstraint("conversation_id", "client_turn_id", name="uq_tutor_turn_client_id"),
    )
    _indexes("tutor_turns", ("conversation_id", "student_id", "course_id", "model_run_id", "status"))

    op.create_table(
        "tutor_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("tutor_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("tutor_turns.id", ondelete="CASCADE"), nullable=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("strategy", sa.String(24), nullable=True),
        sa.Column("checkpoint_json", sa.JSON(), nullable=False),
        sa.Column("visual_json", sa.JSON(), nullable=True),
        sa.Column("citations_json", sa.JSON(), nullable=False),
        sa.Column("inline_practice_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "ordinal", name="uq_tutor_message_ordinal"),
    )
    _indexes("tutor_messages", ("conversation_id", "turn_id", "student_id", "course_id", "role"))

    op.create_table(
        "tutor_tool_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("tutor_turns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("tool_kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result_metadata_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _indexes("tutor_tool_calls", ("turn_id", "student_id", "course_id", "tool_kind", "status"))

    op.create_table(
        "tutor_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_kind", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("conflict_group", sa.String(64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_tutor_memory_confidence"),
    )
    _indexes("tutor_memories", ("student_id", "course_id", "memory_kind", "content_hash", "status", "conflict_group", "expires_at", "deleted_at"))

    op.create_table(
        "tutor_memory_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("memory_id", sa.String(36), sa.ForeignKey("tutor_memories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_id", sa.String(80), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("tutor_conversations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("tutor_turns.id", ondelete="CASCADE"), nullable=True),
        sa.Column("evidence_quote_hash", sa.String(64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("memory_id", "source_kind", "source_id", name="uq_tutor_memory_source"),
    )
    _indexes("tutor_memory_sources", ("memory_id", "source_id", "conversation_id", "active"))

    op.create_table(
        "tutor_experiences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("generation_mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("model_run_id", sa.String(36), sa.ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_tutor_experience_confidence"),
        sa.UniqueConstraint("student_id", "course_id", "idempotency_key", name="uq_tutor_experience_idempotency"),
    )
    _indexes("tutor_experiences", ("student_id", "course_id", "fingerprint", "status"))

    op.create_table(
        "tutor_experience_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experience_id", sa.String(36), sa.ForeignKey("tutor_experiences.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_id", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("experience_id", "source_kind", "source_id", name="uq_tutor_experience_source"),
    )
    _indexes("tutor_experience_sources", ("experience_id", "source_id"))

    op.create_table(
        "decision_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_state_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("student_count", sa.Integer(), nullable=False),
        sa.Column("aggregate_json", sa.JSON(), nullable=False),
        sa.Column("algorithm_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("decision_snapshots", ("course_id", "created_by", "as_of"))

    op.create_table(
        "attention_score_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("decision_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("raw_components_json", sa.JSON(), nullable=False),
        sa.Column("normalized_components_json", sa.JSON(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_attention_score"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_attention_confidence"),
        sa.UniqueConstraint("snapshot_id", "student_id", name="uq_attention_snapshot_student"),
    )
    _indexes("attention_score_snapshots", ("snapshot_id", "student_id"))

    op.create_table(
        "audience_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("teacher_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("resource_type", sa.String(24), nullable=False),
        sa.Column("resource_id", sa.String(80), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column("resource_hash", sa.String(64), nullable=False),
        sa.Column("resource_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("audience_mode", sa.String(24), nullable=False),
        sa.Column("selected_concept_ids_json", sa.JSON(), nullable=False),
        sa.Column("selected_states_json", sa.JSON(), nullable=False),
        sa.Column("teacher_selected_student_ids_json", sa.JSON(), nullable=False),
        sa.Column("suggested_student_ids_json", sa.JSON(), nullable=False),
        sa.Column("final_student_ids_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("audience_drafts", ("course_id", "teacher_id", "resource_type", "resource_id", "audience_mode", "status", "expires_at"))

    op.create_table(
        "audience_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("draft_id", sa.String(36), sa.ForeignKey("audience_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("suggested", sa.Boolean(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("override_action", sa.String(16), nullable=True),
        sa.Column("matched_concept_ids_json", sa.JSON(), nullable=False),
        sa.Column("matched_states_json", sa.JSON(), nullable=False),
        sa.Column("reason_codes_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("draft_id", "student_id", name="uq_audience_candidate_student"),
    )
    _indexes("audience_candidates", ("draft_id", "student_id"))

    op.create_table(
        "decision_publications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("draft_id", sa.String(36), sa.ForeignKey("audience_drafts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("teacher_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("resource_type", sa.String(24), nullable=False),
        sa.Column("resource_id", sa.String(80), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column("resource_hash", sa.String(64), nullable=False),
        sa.Column("resource_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("audience_mode", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("algorithm_version", sa.String(40), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("teacher_id", "course_id", "idempotency_key", name="uq_decision_publication_idempotency"),
        sa.UniqueConstraint("draft_id", name="uq_decision_publication_draft"),
    )
    _indexes("decision_publications", ("draft_id", "course_id", "teacher_id", "resource_type", "resource_id", "audience_mode", "status"))

    op.create_table(
        "decision_publication_concepts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("publication_id", sa.String(36), sa.ForeignKey("decision_publications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=False),
        sa.UniqueConstraint("publication_id", "concept_id", name="uq_decision_publication_concept"),
    )
    _indexes("decision_publication_concepts", ("publication_id", "concept_id"))

    op.create_table(
        "decision_publication_recipients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("publication_id", sa.String(36), sa.ForeignKey("decision_publications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("suggested", sa.Boolean(), nullable=False),
        sa.Column("override_action", sa.String(16), nullable=True),
        sa.Column("matched_concept_ids_json", sa.JSON(), nullable=False),
        sa.Column("matched_states_json", sa.JSON(), nullable=False),
        sa.Column("reason_codes_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("publication_id", "student_id", name="uq_decision_publication_recipient"),
    )
    _indexes("decision_publication_recipients", ("publication_id", "student_id"))

    op.create_table(
        "resource_exposures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("publication_id", sa.String(36), sa.ForeignKey("decision_publications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delivery_status", sa.String(24), nullable=False),
        sa.Column("personalized", sa.Boolean(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_event_id", sa.String(36), sa.ForeignKey("learning_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("completion_event_id", sa.String(36), sa.ForeignKey("learning_events.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("publication_id", "student_id", name="uq_resource_exposure_recipient"),
    )
    _indexes("resource_exposures", ("publication_id", "student_id", "course_id", "delivery_status", "personalized"))

    op.create_table(
        "personalized_resource_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("teacher_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(24), nullable=False),
        sa.Column("concept_ids_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("upstream_job_id", sa.String(80), nullable=False),
        sa.Column("upstream_status_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("teacher_id", "course_id", "idempotency_key", name="uq_personalized_resource_job_idempotency"),
    )
    _indexes("personalized_resource_jobs", ("teacher_id", "student_id", "course_id", "resource_type", "upstream_job_id", "status"))


def downgrade() -> None:
    for table in (
        "personalized_resource_jobs",
        "resource_exposures",
        "decision_publication_recipients",
        "decision_publication_concepts",
        "decision_publications",
        "audience_candidates",
        "audience_drafts",
        "attention_score_snapshots",
        "decision_snapshots",
        "tutor_experience_sources",
        "tutor_experiences",
        "tutor_memory_sources",
        "tutor_memories",
        "tutor_tool_calls",
        "tutor_messages",
        "tutor_turns",
        "tutor_conversations",
    ):
        op.drop_table(table)
