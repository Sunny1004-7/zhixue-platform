"""建立首个系统数据模型。

Revision ID: 0001_initial
Revises:

注意：本迁移使用冻结的初始Metadata，不导入当前ORM Metadata；否则后续新增模型会
反向改变0001并导致全新数据库与增量数据库得到不同结构。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def initial_metadata() -> sa.MetaData:
    metadata = sa.MetaData()
    users = sa.Table(
        "users", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True, index=True),
        sa.Column("role", sa.String(16), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("initials", sa.String(12), nullable=False),
        sa.Column("profile_title", sa.String(160), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    courses = sa.Table(
        "courses", metadata,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("short_title", sa.String(40), nullable=False),
        sa.Column("term", sa.String(40), nullable=False),
        sa.Column("accent", sa.String(24), nullable=False),
        sa.Column("teacher_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
    )
    sa.Table(
        "auth_sessions", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    sa.Table(
        "course_enrollments", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("mastery", sa.Float(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("weekly_minutes", sa.Integer(), nullable=False),
        sa.Column("streak_days", sa.Integer(), nullable=False),
        sa.Column("goal", sa.String(240), nullable=False),
        sa.Column("focus", sa.String(160), nullable=False),
        sa.Column("focus_summary", sa.Text(), nullable=False),
        sa.Column("resource_completion", sa.Float(), nullable=False),
        sa.Column("recent_accuracy", sa.Float(), nullable=False),
        sa.Column("mastery_delta", sa.String(40), nullable=False),
        sa.Column("resource_delta", sa.String(60), nullable=False),
        sa.Column("accuracy_delta", sa.String(60), nullable=False),
        sa.Column("streak_delta", sa.String(60), nullable=False),
        sa.Column("mastery_trend", sa.JSON(), nullable=False),
        sa.Column("resource_trend", sa.JSON(), nullable=False),
        sa.Column("accuracy_trend", sa.JSON(), nullable=False),
        sa.Column("streak_trend", sa.JSON(), nullable=False),
        sa.Column("weekly_activity", sa.JSON(), nullable=False),
        sa.Column("daily_average", sa.Integer(), nullable=False),
        sa.Column("efficient_sessions", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "course_id", name="uq_enrollment_student_course"),
    )
    concepts = sa.Table(
        "concepts", metadata,
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.UniqueConstraint("course_id", "name", name="uq_concept_course_name"),
    )
    sa.Table(
        "knowledge_states", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("concept_id", sa.String(80), sa.ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("mastery", sa.Float(), nullable=False),
        sa.Column("correct_rate", sa.Float(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "concept_id", name="uq_state_student_concept"),
    )
    sa.Table(
        "learning_resources", metadata,
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("detail", sa.String(300), nullable=False),
        sa.Column("progress_completed", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
    )
    sa.Table(
        "learning_activities", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("detail", sa.String(300), nullable=False),
        sa.Column("activity_type", sa.String(24), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    sa.Table(
        "learning_events", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id"), nullable=False, index=True),
        sa.Column("event_type", sa.String(80), nullable=False, index=True),
        sa.Column("object_type", sa.String(80), nullable=False),
        sa.Column("object_id", sa.String(120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    sa.Table(
        "model_profiles", metadata,
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("task_kinds", sa.JSON(), nullable=False),
        sa.Column("config_revision", sa.String(40), nullable=False),
    )
    sa.Table(
        "model_runs", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id"), nullable=False, index=True),
        sa.Column("task_kind", sa.String(80), nullable=False, index=True),
        sa.Column("requested_profile_id", sa.String(80), nullable=False),
        sa.Column("actual_profile_id", sa.String(80), nullable=True),
        sa.Column("provider_model_id", sa.String(160), nullable=True),
        sa.Column("task_policy_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("fallback_reason", sa.String(240), nullable=True),
        sa.Column("audit_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    sa.Table(
        "audit_events", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("action", sa.String(100), nullable=False, index=True),
        sa.Column("object_type", sa.String(80), nullable=False),
        sa.Column("object_id", sa.String(160), nullable=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id"), nullable=True, index=True),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    assert users is not None and courses is not None and concepts is not None
    return metadata


def upgrade() -> None:
    initial_metadata().create_all(bind=op.get_bind())


def downgrade() -> None:
    initial_metadata().drop_all(bind=op.get_bind())
