from __future__ import annotations

from sqlalchemy import case, select
from sqlalchemy.orm import Session, aliased

from .models import (
    Concept,
    Course,
    CourseEnrollment,
    KnowledgeState,
    LearningActivity,
    LearningResource,
    User,
)


class CourseRepository:
    """将课程查询与存储实现隔离，后续可无损切换 PostgreSQL。"""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _course_order():
        return case(
            (Course.id == "machine-learning", 1),
            (Course.id == "ai-intro", 2),
            (Course.id == "data-intelligence", 3),
            else_=99,
        )

    def list_student_courses(self, student_id: str):
        teacher = aliased(User)
        return self.session.execute(
            select(Course, CourseEnrollment, teacher)
            .join(CourseEnrollment, CourseEnrollment.course_id == Course.id)
            .join(teacher, teacher.id == Course.teacher_id)
            .where(CourseEnrollment.student_id == student_id)
            .order_by(self._course_order())
        ).all()

    def list_teacher_courses(self, teacher_id: str):
        teacher = aliased(User)
        return self.session.execute(
            select(Course, teacher)
            .join(teacher, teacher.id == Course.teacher_id)
            .where(Course.teacher_id == teacher_id)
            .order_by(self._course_order())
        ).all()

    def get_student_course(self, student_id: str, course_id: str):
        teacher = aliased(User)
        return self.session.execute(
            select(Course, CourseEnrollment, teacher)
            .join(CourseEnrollment, CourseEnrollment.course_id == Course.id)
            .join(teacher, teacher.id == Course.teacher_id)
            .where(CourseEnrollment.student_id == student_id, Course.id == course_id)
        ).first()

    def get_teacher_course(self, teacher_id: str, course_id: str):
        teacher = aliased(User)
        return self.session.execute(
            select(Course, teacher)
            .join(teacher, teacher.id == Course.teacher_id)
            .where(Course.teacher_id == teacher_id, Course.id == course_id)
        ).first()

    def knowledge_states(self, student_id: str, course_id: str):
        return self.session.execute(
            select(Concept, KnowledgeState)
            .join(KnowledgeState, KnowledgeState.concept_id == Concept.id)
            .where(KnowledgeState.student_id == student_id, Concept.course_id == course_id)
            .order_by(Concept.sort_order)
        ).all()

    def resources(self, course_id: str):
        return self.session.scalars(
            select(LearningResource)
            .where(LearningResource.course_id == course_id, LearningResource.published.is_(True))
            .order_by(LearningResource.sort_order)
        ).all()

    def activities(self, student_id: str, course_id: str, limit: int = 3):
        return self.session.scalars(
            select(LearningActivity)
            .where(LearningActivity.student_id == student_id, LearningActivity.course_id == course_id)
            .order_by(LearningActivity.occurred_at.desc())
            .limit(limit)
        ).all()
