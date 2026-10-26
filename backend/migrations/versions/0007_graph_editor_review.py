"""补齐A2图谱证据、并发基线与受限语义审核制品。

Revision ID: 0007_graph_editor_review
Revises: 0006_model_gateway
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_graph_editor_review"
down_revision: Union[str, None] = "0006_model_gateway"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("graph_extraction_artifacts") as batch:
        batch.add_column(
            sa.Column(
                "base_revision_version", sa.Integer(), nullable=False, server_default="1"
            )
        )

    op.create_table(
        "graph_evidence_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "revision_id",
            sa.String(36),
            sa.ForeignKey("graph_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            sa.String(36),
            sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "edge_id",
            sa.String(36),
            sa.ForeignKey("graph_edges.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "evidence_span_id",
            sa.String(36),
            sa.ForeignKey("evidence_spans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("assertion_note", sa.String(1000), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "source_model_run_id",
            sa.String(36),
            sa.ForeignKey("model_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(node_id IS NOT NULL AND edge_id IS NULL) OR "
            "(node_id IS NULL AND edge_id IS NOT NULL)",
            name="ck_graph_evidence_one_target",
        ),
        sa.UniqueConstraint(
            "revision_id", "node_id", "edge_id", "evidence_span_id", "source_kind",
            name="uq_graph_evidence_target_source",
        ),
    )
    for column in (
        "revision_id", "node_id", "edge_id", "evidence_span_id", "source_kind",
        "source_model_run_id", "created_by", "active",
    ):
        op.create_index(
            f"ix_graph_evidence_links_{column}", "graph_evidence_links", [column]
        )

    op.create_table(
        "graph_semantic_review_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "course_id", sa.String(64),
            sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "graph_id", sa.String(80),
            sa.ForeignKey("knowledge_graphs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "revision_id", sa.String(36),
            sa.ForeignKey("graph_revisions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "model_run_id", sa.String(36),
            sa.ForeignKey("model_runs.id", ondelete="RESTRICT"), nullable=False, unique=True,
        ),
        sa.Column("base_revision_version", sa.Integer(), nullable=False),
        sa.Column("independence_status", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in (
        "course_id", "graph_id", "revision_id", "independence_status", "status", "created_by",
    ):
        op.create_index(
            f"ix_graph_semantic_review_artifacts_{column}",
            "graph_semantic_review_artifacts",
            [column],
        )

    op.create_table(
        "graph_semantic_review_issues",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "artifact_id", sa.String(36),
            sa.ForeignKey("graph_semantic_review_artifacts.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("issue_code", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("evidence_span_ids", sa.JSON(), nullable=False),
        sa.Column("claim", sa.String(1000), nullable=False),
        sa.Column("suggestion", sa.String(1000), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("review_note", sa.String(500), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("artifact_id", "issue_code", "severity", "target_id", "status"):
        op.create_index(
            f"ix_graph_semantic_review_issues_{column}",
            "graph_semantic_review_issues",
            [column],
        )


def downgrade() -> None:
    op.drop_table("graph_semantic_review_issues")
    op.drop_table("graph_semantic_review_artifacts")
    op.drop_table("graph_evidence_links")
    with op.batch_alter_table("graph_extraction_artifacts") as batch:
        batch.drop_column("base_revision_version")
