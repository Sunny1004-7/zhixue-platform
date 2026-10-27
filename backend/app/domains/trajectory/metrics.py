"""Current score rates use accepted course events, excluding corrected scores.

The window is the latest 30 effective scores as of the requested instant, not
30 calendar days. Seed arrays do not establish dated mastery observations.
"""
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...models import LearningEvent


def active_scores(db: Session, student_id: str, course_id: str,
                  as_of: datetime | None = None) -> list[LearningEvent]:
    rows = list(db.scalars(select(LearningEvent).where(
        LearningEvent.student_id == student_id,
        LearningEvent.course_id == course_id,
        LearningEvent.processing_status == "accepted",
        LearningEvent.occurred_at <= (as_of or datetime.now(timezone.utc)),
    ).order_by(LearningEvent.occurred_at.desc(), LearningEvent.id.desc())))
    superseded = {r.correction_of_event_id for r in rows if r.correction_of_event_id}
    return [r for r in rows if r.event_type == "answer_scored"
            and r.outcome is not None and r.id not in superseded]


def recent_score_rate(db: Session, student_id: str, course_id: str,
                      as_of: datetime | None = None) -> tuple[float | None, int]:
    scores = active_scores(db, student_id, course_id, as_of)[:30]
    return ((100.0 * sum(float(r.outcome) for r in scores) / len(scores), len(scores))
            if scores else (None, 0))
