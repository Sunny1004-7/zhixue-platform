"""增加A2知识图谱工作区、修订、节点、关系与质量报告。

Revision ID: 0004_graph_foundation
Revises: 0003_baseline_correct_rate
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_graph_foundation"
down_revision: Union[str, None] = "0003_baseline_correct_rate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_graphs",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("working_revision_id", sa.String(36), nullable=True),
        sa.Column("published_revision_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("course_id", "title", name="uq_graph_course_title"),
    )
    op.create_index("ix_knowledge_graphs_course_id", "knowledge_graphs", ["course_id"])
    op.create_index("ix_knowledge_graphs_owner_id", "knowledge_graphs", ["owner_id"])
    op.create_index("ix_knowledge_graphs_status", "knowledge_graphs", ["status"])

    op.create_table(
        "graph_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("graph_id", sa.String(80), sa.ForeignKey("knowledge_graphs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_revision_id", sa.String(36), sa.ForeignKey("graph_revisions.id"), nullable=True),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False, server_default="new"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("review_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("source_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("graph_id", "revision_no", name="uq_graph_revision_no"),
    )
    op.create_index("ix_graph_revisions_graph_id", "graph_revisions", ["graph_id"])
    op.create_index("ix_graph_revisions_status", "graph_revisions", ["status"])
    op.create_index("ix_graph_revisions_created_by", "graph_revisions", ["created_by"])

    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("graph_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("node_type", sa.String(24), nullable=False, server_default="core"),
        sa.Column("definition", sa.Text(), nullable=False, server_default=""),
        sa.Column("key_point", sa.Text(), nullable=False, server_default=""),
        sa.Column("misconception", sa.Text(), nullable=False, server_default=""),
        sa.Column("origin", sa.String(32), nullable=False, server_default="teacher"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("position_x", sa.Float(), nullable=False, server_default="0"),
        sa.Column("position_y", sa.Float(), nullable=False, server_default="0"),
        sa.UniqueConstraint("revision_id", "concept_id", name="uq_graph_node_revision_concept"),
        sa.UniqueConstraint("revision_id", "label", name="uq_graph_node_revision_label"),
    )
    op.create_index("ix_graph_nodes_revision_id", "graph_nodes", ["revision_id"])
    op.create_index("ix_graph_nodes_concept_id", "graph_nodes", ["concept_id"])

    op.create_table(
        "graph_edges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("graph_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_node_id", sa.String(36), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_node_id", sa.String(36), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation", sa.String(24), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False, server_default="teacher"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.UniqueConstraint("revision_id", "from_node_id", "to_node_id", "relation", name="uq_graph_edge_semantics"),
    )
    op.create_index("ix_graph_edges_revision_id", "graph_edges", ["revision_id"])
    op.create_index("ix_graph_edges_from_node_id", "graph_edges", ["from_node_id"])
    op.create_index("ix_graph_edges_to_node_id", "graph_edges", ["to_node_id"])

    op.create_table(
        "graph_quality_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("graph_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hard_pass", sa.Boolean(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("issues_json", sa.JSON(), nullable=False),
        sa.Column("validator_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_graph_quality_reports_revision_id", "graph_quality_reports", ["revision_id"])


def downgrade() -> None:
    op.drop_table("graph_quality_reports")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
    op.drop_table("graph_revisions")
    op.drop_table("knowledge_graphs")
