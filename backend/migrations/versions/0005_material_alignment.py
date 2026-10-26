"""增加X1多源材料、安全解析、证据定位与知识点对齐数据模型。

Revision ID: 0005_material_alignment
Revises: 0004_graph_foundation
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_material_alignment"
down_revision: Union[str, None] = "0004_graph_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("extension", sa.String(12), nullable=False),
        sa.Column("declared_mime", sa.String(120), nullable=False),
        sa.Column("detected_mime", sa.String(120), nullable=True),
        sa.Column("expected_size", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("expected_sha256", sa.String(64), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("storage_key", sa.String(500), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="prepared"),
        sa.Column("security_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("rejection_code", sa.String(64), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("course_id", "owner_id", "purpose", "sha256", "status", "security_status"):
        op.create_index(f"ix_source_assets_{column}", "source_assets", [column])

    op.create_table(
        "parsed_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("parser_name", sa.String(40), nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="parsed"),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("segment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_parsed_documents_asset_id", "parsed_documents", ["asset_id"], unique=True)
    op.create_index("ix_parsed_documents_status", "parsed_documents", ["status"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("parsed_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("locator_json", sa.JSON(), nullable=False),
        sa.Column("section_title", sa.String(255), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.UniqueConstraint("document_id", "sequence_no", name="uq_chunk_document_sequence"),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])

    op.create_table(
        "evidence_spans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chunk_id", sa.String(36), sa.ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("locator_json", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
    )
    op.create_index("ix_evidence_spans_chunk_id", "evidence_spans", ["chunk_id"])

    op.create_table(
        "alignment_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("source_asset_id", sa.String(36), sa.ForeignKey("source_assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("raw_input", sa.Text(), nullable=True),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False, server_default="concept_alignment"),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("parser_version", sa.String(40), nullable=True),
        sa.Column("ontology_version", sa.String(40), nullable=False),
        sa.Column("aligner_version", sa.String(40), nullable=False),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("course_id", "actor_id", "source_asset_id", "purpose", "status"):
        op.create_index(f"ix_alignment_runs_{column}", "alignment_runs", [column])

    op.create_table(
        "alignment_mentions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("alignment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.String(500), nullable=False),
        sa.Column("normalized_text", sa.String(500), nullable=False),
        sa.Column("context", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_span_id", sa.String(36), sa.ForeignKey("evidence_spans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_alignment_mention_order"),
    )
    for column in ("run_id", "normalized_text", "evidence_span_id", "status"):
        op.create_index(f"ix_alignment_mentions_{column}", "alignment_mentions", [column])

    op.create_table(
        "alignment_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mention_id", sa.String(36), sa.ForeignKey("alignment_mentions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("lexical_score", sa.Float(), nullable=False),
        sa.Column("context_score", sa.Float(), nullable=False),
        sa.Column("graph_score", sa.Float(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("mention_id", "concept_id", name="uq_alignment_candidate_concept"),
        sa.UniqueConstraint("mention_id", "rank", name="uq_alignment_candidate_rank"),
    )
    op.create_index("ix_alignment_candidates_mention_id", "alignment_candidates", ["mention_id"])
    op.create_index("ix_alignment_candidates_concept_id", "alignment_candidates", ["concept_id"])

    op.create_table(
        "alignment_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mention_id", sa.String(36), sa.ForeignKey("alignment_mentions.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("decision", sa.String(24), nullable=True),
        sa.Column("selected_concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=True),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alignment_reviews_mention_id", "alignment_reviews", ["mention_id"], unique=True)
    op.create_index("ix_alignment_reviews_status", "alignment_reviews", ["status"])
    op.create_index("ix_alignment_reviews_selected_concept_id", "alignment_reviews", ["selected_concept_id"])

    op.create_table(
        "derivations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_asset_id", sa.String(36), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("derived_type", sa.String(64), nullable=False),
        sa.Column("derived_id", sa.String(80), nullable=False),
        sa.Column("relation", sa.String(40), nullable=False, server_default="derived_from"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_asset_id", "derived_type", "derived_id", name="uq_derivation_target"),
    )
    for column in ("source_asset_id", "derived_type", "derived_id", "active"):
        op.create_index(f"ix_derivations_{column}", "derivations", [column])

    op.create_table(
        "deletion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_asset_id", sa.String(36), sa.ForeignKey("source_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("invalidated_derivations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_removed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deletion_jobs_source_asset_id", "deletion_jobs", ["source_asset_id"])
    op.create_index("ix_deletion_jobs_requested_by", "deletion_jobs", ["requested_by"])
    op.create_index("ix_deletion_jobs_status", "deletion_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("deletion_jobs")
    op.drop_table("derivations")
    op.drop_table("alignment_reviews")
    op.drop_table("alignment_candidates")
    op.drop_table("alignment_mentions")
    op.drop_table("alignment_runs")
    op.drop_table("evidence_spans")
    op.drop_table("document_chunks")
    op.drop_table("parsed_documents")
    op.drop_table("source_assets")
