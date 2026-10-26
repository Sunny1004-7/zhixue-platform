"""增加A3题目蓝图、题组修订、提示、作答、评分与质量报告。

Revision ID: 0008_traceq_practice
Revises: 0007_graph_editor_review
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_traceq_practice"
down_revision: Union[str, None] = "0007_graph_editor_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "question_blueprints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("owner_type", sa.String(16), nullable=False),
        sa.Column("source_method", sa.String(24), nullable=False),
        sa.Column("difficulty_mode", sa.String(24), nullable=False),
        sa.Column("requested_profile_id", sa.String(80), nullable=True),
        sa.Column("source_summary_json", sa.JSON(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("compiler_version", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("question_blueprints", ("course_id", "created_by", "owner_type", "source_method", "status"))

    op.create_table(
        "blueprint_cells",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("blueprint_id", sa.String(36), sa.ForeignKey("question_blueprints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=False),
        sa.Column("question_type", sa.String(24), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("difficulty_target", sa.Float(), nullable=False),
        sa.Column("cognitive_level", sa.String(24), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("count >= 0", name="ck_blueprint_cell_count_nonnegative"),
        sa.UniqueConstraint("blueprint_id", "concept_id", "question_type", name="uq_blueprint_cell"),
    )
    _indexes("blueprint_cells", ("blueprint_id", "concept_id", "question_type"))

    op.create_table(
        "question_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("owner_student_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("visibility", sa.String(24), nullable=False),
        sa.Column("working_revision_id", sa.String(36), nullable=True),
        sa.Column("published_revision_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("question_sets", ("course_id", "created_by", "owner_student_id", "status", "visibility"))

    op.create_table(
        "question_set_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("question_set_id", sa.String(36), sa.ForeignKey("question_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_revision_id", sa.String(36), sa.ForeignKey("question_set_revisions.id"), nullable=True),
        sa.Column("blueprint_id", sa.String(36), sa.ForeignKey("question_blueprints.id"), nullable=True),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("quality_status", sa.String(24), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_summary", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("question_set_id", "revision_no", name="uq_question_set_revision_no"),
    )
    _indexes("question_set_revisions", ("question_set_id", "blueprint_id", "status", "quality_status", "created_by"))

    op.create_table(
        "questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("question_set_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question_type", sa.String(24), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("answer_spec_json", sa.JSON(), nullable=False),
        sa.Column("rubric_json", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("cognitive_level", sa.String(24), nullable=False),
        sa.Column("difficulty_prior", sa.Float(), nullable=False),
        sa.Column("difficulty_calibrated", sa.Float(), nullable=True),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("revision_id", "position", name="uq_question_revision_position"),
    )
    _indexes("questions", ("revision_id", "question_type"))

    op.create_table(
        "question_options",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("misconception_code", sa.String(80), nullable=True),
        sa.UniqueConstraint("question_id", "position", name="uq_question_option_position"),
    )
    _indexes("question_options", ("question_id",))

    op.create_table(
        "question_concepts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.UniqueConstraint("question_id", "concept_id", name="uq_question_concept"),
    )
    _indexes("question_concepts", ("question_id", "concept_id"))

    op.create_table(
        "hints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("leakage_score", sa.Float(), nullable=False),
        sa.Column("information_gain", sa.Float(), nullable=False),
        sa.Column("validation_status", sa.String(24), nullable=False),
        sa.Column("validator_version", sa.String(40), nullable=False),
        sa.CheckConstraint("level BETWEEN 1 AND 3", name="ck_hint_level"),
        sa.UniqueConstraint("question_id", "level", name="uq_question_hint_level"),
    )
    _indexes("hints", ("question_id",))

    op.create_table(
        "question_generation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("blueprint_id", sa.String(36), sa.ForeignKey("question_blueprints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_run_id", sa.String(36), sa.ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requested_profile_id", sa.String(80), nullable=False),
        sa.Column("actual_profile_id", sa.String(80), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("safe_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _indexes("question_generation_runs", ("blueprint_id", "model_run_id", "status"))

    op.create_table(
        "question_quality_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("question_set_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("hard_pass", sa.Boolean(), nullable=False),
        sa.Column("hard_gates_json", sa.JSON(), nullable=False),
        sa.Column("dimension_scores_json", sa.JSON(), nullable=False),
        sa.Column("issues_json", sa.JSON(), nullable=False),
        sa.Column("validator_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("question_quality_reports", ("revision_id", "question_id", "hard_pass"))

    op.create_table(
        "attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_set_id", sa.String(36), sa.ForeignKey("question_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("question_set_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("answer_json", sa.JSON(), nullable=False),
        sa.Column("hint_level", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "question_id", "idempotency_key", name="uq_attempt_idempotency"),
        sa.UniqueConstraint("student_id", "question_id", "attempt_no", name="uq_attempt_number"),
    )
    _indexes("attempts", ("student_id", "course_id", "question_set_id", "revision_id", "question_id", "status"))

    op.create_table(
        "scores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("attempt_id", sa.String(36), sa.ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("grading_mode", sa.String(32), nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False),
        sa.Column("feedback_json", sa.JSON(), nullable=False),
        sa.Column("grader_model_run_id", sa.String(36), sa.ForeignKey("model_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_scores_attempt_id", "scores", ["attempt_id"], unique=True)
    _indexes("scores", ("review_status",))


def downgrade() -> None:
    for table in (
        "scores", "attempts", "question_quality_reports", "question_generation_runs", "hints",
        "question_concepts", "question_options", "questions", "question_set_revisions",
        "question_sets", "blueprint_cells", "question_blueprints",
    ):
        op.drop_table(table)
