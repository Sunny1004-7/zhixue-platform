"""冻结历史正确率基线，支持事件纠错后重算。

Revision ID: 0003_baseline_correct_rate
Revises: 0002_eglt_trajectory
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_baseline_correct_rate"
down_revision: Union[str, None] = "0002_eglt_trajectory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_states") as batch:
        batch.add_column(sa.Column("baseline_correct_rate", sa.Float(), nullable=False, server_default="0"))
    op.execute(sa.text("UPDATE knowledge_states SET baseline_correct_rate = correct_rate"))


def downgrade() -> None:
    with op.batch_alter_table("knowledge_states") as batch:
        batch.drop_column("baseline_correct_rate")
