from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...models import Concept
from .names import normalize_concept_name


class InvalidConceptName(ValueError):
    pass


@dataclass(frozen=True)
class ConceptResolution:
    concept: Concept
    created: bool


def resolve_open_concept(
    db: Session,
    *,
    course_id: str,
    name: str,
) -> ConceptResolution:
    clean_name = name.strip()
    normalized_name = normalize_concept_name(clean_name)
    if len(clean_name) < 2 or not normalized_name:
        raise InvalidConceptName("概念名称规范化后不能为空")

    existing = db.scalar(select(Concept).where(
        Concept.course_id == course_id,
        Concept.normalized_name == normalized_name,
    ))
    if existing is not None:
        return ConceptResolution(existing, False)

    next_sort_order = int(db.scalar(select(func.max(Concept.sort_order)).where(
        Concept.course_id == course_id,
    )) or 0) + 1
    concept = Concept(
        id=f"{course_id}:concept:custom:{uuid4().hex[:12]}",
        course_id=course_id,
        name=clean_name,
        sort_order=next_sort_order,
    )
    try:
        with db.begin_nested():
            db.add(concept)
            db.flush()
    except IntegrityError:
        existing = db.scalar(select(Concept).where(
            Concept.course_id == course_id,
            Concept.normalized_name == normalized_name,
        ))
        if existing is None:
            raise
        return ConceptResolution(existing, False)
    return ConceptResolution(concept, True)
