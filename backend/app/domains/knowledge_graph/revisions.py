from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from ...models import GraphRevision, GraphSemanticReviewArtifact


@dataclass(frozen=True)
class RevisionConflict(RuntimeError):
    expected_version: int
    actual_version: int


def claim_revision_change(
    db: Session,
    revision: GraphRevision,
    expected_version: int,
    *,
    review_status: str = "pending",
    clear_quality: bool = True,
    extra_values: dict[str, Any] | None = None,
    increment_version: bool = True,
    supersede_semantic: bool = True,
) -> int:
    """以版本条件原子取得一次草稿写权，并使旧语义审核失效。

    调用方应先完成无副作用校验，再调用本函数，随后在同一事务中写入节点、
    关系或质量制品。若其他会话已修改修订，条件更新不会命中任何行。
    """

    next_version = expected_version + 1 if increment_version else expected_version
    values: dict[str, Any] = {
        "version": next_version,
        "review_status": review_status,
    }
    if clear_quality:
        values["quality_score"] = None
    if extra_values:
        values.update(extra_values)
    result = db.execute(
        update(GraphRevision)
        .where(
            GraphRevision.id == revision.id,
            GraphRevision.status == "draft",
            GraphRevision.version == expected_version,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.expire(revision)
        actual = revision.version
        raise RevisionConflict(expected_version=expected_version, actual_version=actual)
    if supersede_semantic:
        db.execute(
            update(GraphSemanticReviewArtifact)
            .where(
                GraphSemanticReviewArtifact.revision_id == revision.id,
                GraphSemanticReviewArtifact.status.in_([
                    "awaiting_review", "reviewed", "changes_required", "passed",
                ]),
            )
            .values(status="superseded")
        )
    db.expire(revision)
    return next_version
