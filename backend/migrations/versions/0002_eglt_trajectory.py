"""增加EGLT学习事件与可重算状态字段。

Revision ID: 0002_eglt_trajectory
Revises: 0001_initial
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_eglt_trajectory"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("learning_events") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(160), nullable=True))
        batch.add_column(sa.Column("outcome", sa.Float(), nullable=True))
        batch.add_column(sa.Column("difficulty", sa.Float(), nullable=True))
        batch.add_column(sa.Column("hint_level", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("attempt_no", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("completion", sa.Float(), nullable=True))
        batch.add_column(sa.Column("strategy", sa.String(40), nullable=True))
        batch.add_column(sa.Column("upstream_confidence", sa.Float(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("alignment_confidence", sa.Float(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("evidence_success", sa.Float(), nullable=True))
        batch.add_column(sa.Column("evidence_reliability", sa.Float(), nullable=True))
        batch.add_column(sa.Column("processing_status", sa.String(32), nullable=False, server_default="accepted"))
        batch.add_column(sa.Column("correction_of_event_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("schema_version", sa.String(24), nullable=False, server_default="learning-event-1.0"))
        batch.create_foreign_key("fk_learning_event_correction", "learning_events", ["correction_of_event_id"], ["id"])
        batch.create_index("ix_learning_events_idempotency_key", ["idempotency_key"], unique=False)

    op.execute(sa.text("UPDATE learning_events SET idempotency_key = id WHERE idempotency_key IS NULL"))
    with op.batch_alter_table("learning_events") as batch:
        batch.alter_column("idempotency_key", existing_type=sa.String(160), nullable=False)
        batch.create_unique_constraint(
            "uq_learning_event_idempotency", ["student_id", "course_id", "idempotency_key"],
        )

    with op.batch_alter_table("knowledge_states") as batch:
        batch.add_column(sa.Column("baseline_alpha", sa.Float(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("baseline_beta", sa.Float(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("alpha", sa.Float(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("beta", sa.Float(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("uncertainty", sa.Float(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("effective_evidence", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("status", sa.String(24), nullable=False, server_default="unseen"))
        batch.add_column(sa.Column("trend_30d", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("last_evidence_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("model_version", sa.String(40), nullable=False, server_default="eglt-0.1.0"))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

    op.execute(sa.text(
        "UPDATE knowledge_states SET "
        "baseline_alpha = (mastery / 100.0) * (evidence_count + 2.0), "
        "baseline_beta = (1.0 - mastery / 100.0) * (evidence_count + 2.0), "
        "alpha = (mastery / 100.0) * (evidence_count + 2.0), "
        "beta = (1.0 - mastery / 100.0) * (evidence_count + 2.0), "
        "uncertainty = 1.0 - confidence, "
        "effective_evidence = 2.0 + evidence_count, "
        "status = CASE WHEN evidence_count = 0 THEN 'unseen' WHEN mastery < 50 THEN 'weak' ELSE 'mastered' END"
    ))

    op.create_table(
        "event_concepts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("learning_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=False),
        sa.Column("contribution_weight", sa.Float(), nullable=False),
        sa.UniqueConstraint("event_id", "concept_id", name="uq_event_concept"),
    )
    op.create_index("ix_event_concepts_event_id", "event_concepts", ["event_id"])
    op.create_index("ix_event_concepts_concept_id", "event_concepts", ["concept_id"])

    op.create_table(
        "mastery_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_id", sa.String(36), sa.ForeignKey("knowledge_states.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("learning_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("concept_id", sa.String(80), sa.ForeignKey("concepts.id"), nullable=False),
        sa.Column("contribution_weight", sa.Float(), nullable=False),
        sa.Column("success", sa.Float(), nullable=False),
        sa.Column("reliability", sa.Float(), nullable=False),
        sa.Column("mastery_before", sa.Float(), nullable=False),
        sa.Column("mastery_after", sa.Float(), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "concept_id", name="uq_mastery_evidence_event_concept"),
    )
    op.create_index("ix_mastery_evidence_state_id", "mastery_evidence", ["state_id"])
    op.create_index("ix_mastery_evidence_event_id", "mastery_evidence", ["event_id"])
    op.create_index("ix_mastery_evidence_concept_id", "mastery_evidence", ["concept_id"])


def downgrade() -> None:
    op.drop_table("mastery_evidence")
    op.drop_table("event_concepts")
    with op.batch_alter_table("knowledge_states") as batch:
        for column in (
            "version", "model_version", "last_evidence_at", "trend_30d", "status",
            "effective_evidence", "uncertainty", "beta", "alpha", "baseline_beta", "baseline_alpha",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("learning_events") as batch:
        batch.drop_constraint("uq_learning_event_idempotency", type_="unique")
        batch.drop_index("ix_learning_events_idempotency_key")
        batch.drop_constraint("fk_learning_event_correction", type_="foreignkey")
        for column in (
            "schema_version", "correction_of_event_id", "processing_status", "evidence_reliability",
            "evidence_success", "alignment_confidence", "upstream_confidence", "strategy", "completion",
            "attempt_no", "hint_level", "difficulty", "outcome", "idempotency_key",
        ):
            batch.drop_column(column)
