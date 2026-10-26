"""Read current resource completion from published resources and learner records.

The catalog and directed inbox may point to the same resource; count that resource
once. A resource completion marks the learning task complete, not mastery gain.
"""
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .learning_support_models import DecisionPublication, ResourceExposure
from .models import Attempt, KnowledgeGraph, Question, QuestionSet
from .video_models import PublicationRecipient, VideoProgress, VideoPublication


@dataclass(frozen=True)
class ResourceCompletion:
    total: int
    completed: int

    @property
    def percent(self) -> float:
        return round(100.0 * self.completed / self.total, 2) if self.total else 0.0


def resource_completion(db: Session, student_id: str, course_id: str) -> ResourceCompletion:
    available: set[tuple[str, str]] = {
        ("graph", key) for key in db.scalars(select(KnowledgeGraph.id).where(
            KnowledgeGraph.course_id == course_id,
            KnowledgeGraph.status == "published",
            KnowledgeGraph.published_revision_id.is_not(None),
        ))
    }
    completed: set[tuple[str, str]] = set()
    sets = db.scalars(select(QuestionSet).where(
        QuestionSet.course_id == course_id,
        or_(QuestionSet.owner_student_id == student_id,
            (QuestionSet.owner_student_id.is_(None))
            & (QuestionSet.status == "published")
            & (QuestionSet.visibility == "course")),
    )).all()
    for item in sets:
        revision = item.published_revision_id or item.working_revision_id
        if not revision:
            continue
        key = ("question_set", item.id)
        available.add(key)
        questions = set(db.scalars(select(Question.id).where(Question.revision_id == revision)))
        answered = set(db.scalars(select(Attempt.question_id).where(
            Attempt.student_id == student_id, Attempt.question_id.in_(questions),
        ))) if questions else set()
        if questions and questions.issubset(answered):
            completed.add(key)
    videos = db.execute(select(VideoPublication, VideoProgress.completed)
        .join(PublicationRecipient, PublicationRecipient.publication_id == VideoPublication.id)
        .outerjoin(VideoProgress, (VideoProgress.publication_id == VideoPublication.id)
                   & (VideoProgress.student_id == student_id))
        .where(VideoPublication.course_id == course_id,
               VideoPublication.status == "active", PublicationRecipient.student_id == student_id)).all()
    for item, done in videos:
        key = ("video", item.candidate_id)
        available.add(key)
        if done:
            completed.add(key)
    exposures = db.execute(select(DecisionPublication, ResourceExposure.completed_at)
        .join(ResourceExposure, ResourceExposure.publication_id == DecisionPublication.id)
        .where(ResourceExposure.student_id == student_id, ResourceExposure.course_id == course_id,
               ResourceExposure.withdrawn_at.is_(None), DecisionPublication.status == "published")).all()
    for item, finished_at in exposures:
        key = (item.resource_type, item.resource_id)
        available.add(key)
        if finished_at:
            completed.add(key)
    return ResourceCompletion(len(available), len(completed & available))
