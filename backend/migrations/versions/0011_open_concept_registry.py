"""Add canonical course concept names for exact open-concept merging.

Revision ID: 0011_open_concept_registry
Revises: 0010_tutoring_decision
"""
from __future__ import annotations

import unicodedata
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_open_concept_registry"
down_revision: Union[str, None] = "0010_tutoring_decision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        char for char in normalized
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    )


def upgrade() -> None:
    with op.batch_alter_table("concepts") as batch:
        batch.add_column(sa.Column("normalized_name", sa.String(240), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, course_id, name FROM concepts ORDER BY course_id, id")
    ).mappings()
    seen: dict[tuple[str, str], str] = {}
    for row in rows:
        normalized_name = _normalize(row["name"])
        if not normalized_name:
            raise RuntimeError(f"Concept {row['id']} has an empty canonical name")
        key = (row["course_id"], normalized_name)
        if key in seen:
            raise RuntimeError(
                "Canonical concept collision in course "
                f"{row['course_id']}: {seen[key]} and {row['id']}"
            )
        seen[key] = row["id"]
        connection.execute(
            sa.text("UPDATE concepts SET normalized_name = :name WHERE id = :id"),
            {"name": normalized_name, "id": row["id"]},
        )

    with op.batch_alter_table("concepts") as batch:
        batch.alter_column(
            "normalized_name", existing_type=sa.String(240), nullable=False,
        )
        batch.create_unique_constraint(
            "uq_concept_course_normalized_name",
            ["course_id", "normalized_name"],
        )


def downgrade() -> None:
    with op.batch_alter_table("concepts") as batch:
        batch.drop_constraint(
            "uq_concept_course_normalized_name", type_="unique",
        )
        batch.drop_column("normalized_name")
