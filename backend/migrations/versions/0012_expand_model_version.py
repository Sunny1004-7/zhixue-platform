"""Preserve complete trajectory, temporal and graph model version identifiers.

Revision ID: 0012_expand_model_version
Revises: 0011_open_concept_registry
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "0012_expand_model_version"
down_revision: Union[str, None] = "0011_open_concept_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VERSION_TABLES = ("knowledge_states", "mastery_evidence")


def upgrade() -> None:
    for table_name in VERSION_TABLES:
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column(
                "model_version",
                existing_type=sa.String(40),
                type_=sa.String(128),
                existing_nullable=False,
            )


def downgrade() -> None:
    # Check both tables before changing either, so rollback cannot truncate
    # identifiers or leave the two version columns with different capacities.
    if not context.is_offline_mode():
        connection = op.get_bind()
        for table_name in VERSION_TABLES:
            oversized = connection.execute(sa.text(
                f"SELECT 1 FROM {table_name} "
                "WHERE length(model_version) > 40 LIMIT 1"
            )).first()
            if oversized is not None:
                raise RuntimeError(
                    f"Cannot reduce {table_name}.model_version to 40 characters: "
                    "existing model versions exceed that length."
                )
    for table_name in reversed(VERSION_TABLES):
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column(
                "model_version",
                existing_type=sa.String(128),
                type_=sa.String(40),
                existing_nullable=False,
            )
