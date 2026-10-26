"""建立X2模型网关与A2图谱抽取候选数据模型。

Revision ID: 0006_model_gateway
Revises: 0005_material_alignment
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_model_gateway"
down_revision: Union[str, None] = "0005_material_alignment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_profile_revisions",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("profile_id", sa.String(80), sa.ForeignKey("model_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("provider_kind", sa.String(40), nullable=False),
        sa.Column("credential_ref", sa.String(120), nullable=False),
        sa.Column("endpoint_ref", sa.String(120), nullable=False),
        sa.Column("model_id_ref", sa.String(120), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("data_region", sa.String(40), nullable=False),
        sa.Column("retention_policy", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("profile_id", "revision_no", name="uq_model_profile_revision_no"),
    )
    op.create_index("ix_model_profile_revisions_profile_id", "model_profile_revisions", ["profile_id"])
    op.create_index("ix_model_profile_revisions_status", "model_profile_revisions", ["status"])
    op.create_table(
        "task_policies",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("task_kind", sa.String(80), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("required_capabilities_json", sa.JSON(), nullable=False),
        sa.Column("selection_mode", sa.String(32), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("output_schema_version", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_kind", "version", name="uq_task_policy_version"),
    )
    op.create_index("ix_task_policies_task_kind", "task_policies", ["task_kind"])
    op.create_index("ix_task_policies_enabled", "task_policies", ["enabled"])
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("task_kind", sa.String(80), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("system_template", sa.Text(), nullable=False),
        sa.Column("user_template", sa.Text(), nullable=False),
        sa.Column("template_hash", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_kind", "version", name="uq_prompt_template_version"),
    )
    op.create_index("ix_prompt_templates_task_kind", "prompt_templates", ["task_kind"])
    op.create_index("ix_prompt_templates_active", "prompt_templates", ["active"])

    with op.batch_alter_table("model_runs") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(160), nullable=True))
        batch.add_column(sa.Column("input_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("prompt_template_version", sa.String(40), nullable=True))
        batch.add_column(sa.Column("prompt_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("output_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("error_code", sa.String(80), nullable=True))
        batch.add_column(sa.Column("safe_error", sa.String(500), nullable=True))
        batch.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("usage_json", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_unique_constraint(
            "uq_model_run_idempotency", ["actor_id", "course_id", "task_kind", "idempotency_key"]
        )

    op.create_table(
        "model_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("model_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("actual_profile_id", sa.String(80), nullable=False),
        sa.Column("provider_model_id", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("response_hash", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "attempt_no", name="uq_model_attempt_no"),
    )
    op.create_index("ix_model_attempts_run_id", "model_attempts", ["run_id"])
    op.create_index("ix_model_attempts_status", "model_attempts", ["status"])
    op.create_table(
        "structured_validations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("model_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("errors_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_structured_validations_run_id", "structured_validations", ["run_id"])
    op.create_index("ix_structured_validations_passed", "structured_validations", ["passed"])
    op.create_table(
        "model_quality_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("model_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hard_pass", sa.Boolean(), nullable=False),
        sa.Column("gate_version", sa.String(64), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("issues_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_quality_reports_run_id", "model_quality_reports", ["run_id"])
    op.create_index("ix_model_quality_reports_hard_pass", "model_quality_reports", ["hard_pass"])
    op.create_table(
        "graph_extraction_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("graph_id", sa.String(80), sa.ForeignKey("knowledge_graphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("graph_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alignment_run_id", sa.String(36), sa.ForeignKey("alignment_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model_run_id", sa.String(36), sa.ForeignKey("model_runs.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("course_id", "graph_id", "revision_id", "alignment_run_id", "status", "created_by"):
        op.create_index(f"ix_graph_extraction_artifacts_{column}", "graph_extraction_artifacts", [column])
    op.create_table(
        "graph_extraction_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("graph_extraction_artifacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("proposal_kind", sa.String(24), nullable=False),
        sa.Column("concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=True),
        sa.Column("from_concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=True),
        sa.Column("to_concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=True),
        sa.Column("relation", sa.String(24), nullable=True),
        sa.Column("evidence_span_ids", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.String(500), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_graph_extraction_proposals_artifact_id", "graph_extraction_proposals", ["artifact_id"])
    op.create_index("ix_graph_extraction_proposals_proposal_kind", "graph_extraction_proposals", ["proposal_kind"])
    op.create_index("ix_graph_extraction_proposals_status", "graph_extraction_proposals", ["status"])


def downgrade() -> None:
    op.drop_table("graph_extraction_proposals")
    op.drop_table("graph_extraction_artifacts")
    op.drop_table("model_quality_reports")
    op.drop_table("structured_validations")
    op.drop_table("model_attempts")
    with op.batch_alter_table("model_runs") as batch:
        batch.drop_constraint("uq_model_run_idempotency", type_="unique")
        for column in (
            "completed_at", "usage_json", "attempt_count", "safe_error", "error_code",
            "output_hash", "prompt_hash", "prompt_template_version", "input_hash", "idempotency_key",
        ):
            batch.drop_column(column)
    op.drop_table("prompt_templates")
    op.drop_table("task_policies")
    op.drop_table("model_profile_revisions")
