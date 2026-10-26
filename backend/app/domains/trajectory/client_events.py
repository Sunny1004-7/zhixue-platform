from __future__ import annotations

import math

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ...models import GraphNode, GraphRevision, KnowledgeGraph, User
from ...repositories import CourseRepository
from ...schemas import LearningEventCreate
from .service import ConceptContribution, EventCommand


def client_observation_command(
    db: Session, *, student: User, course_id: str, payload: LearningEventCreate,
) -> EventCommand:
    """Resolve browser observations against a published, course-owned source.

    Grades, video completion and tutoring outcomes are emitted by their business
    services. Browser-supplied scores and confidence values are never trusted.
    """
    if CourseRepository(db).get_student_course(student.id, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权写入")
    if payload.event_type not in {"graph_node_viewed", "knowledge_card_opened"}:
        raise HTTPException(status_code=403, detail={
            "code": "SERVER_RESULT_REQUIRED",
            "message": "请通过作答、视频或辅导功能提交相应学习结果",
        })
    if any(value is not None for value in (
        payload.outcome, payload.difficulty, payload.hint_level, payload.attempt_no,
        payload.strategy, payload.correction_of_event_id,
    )):
        raise HTTPException(status_code=422, detail="浏览记录不能包含评分或更正结果")
    graph_id = payload.payload.get("graph_id")
    if not isinstance(graph_id, str) or not graph_id or len(graph_id) > 80:
        raise HTTPException(status_code=422, detail="浏览记录必须包含有效图谱编号")
    graph = db.get(KnowledgeGraph, graph_id)
    if (graph is None or graph.course_id != course_id or graph.status != "published"
            or not graph.published_revision_id):
        raise HTTPException(status_code=404, detail="图谱资源不存在或尚未发布")
    revision = db.get(GraphRevision, graph.published_revision_id)
    node = db.get(GraphNode, payload.object_id)
    if (payload.object_type != "knowledge_graph_node" or revision is None
            or revision.graph_id != graph.id or revision.status != "published" or node is None
            or node.revision_id != revision.id):
        raise HTTPException(status_code=422, detail="浏览对象不属于当前已发布图谱")
    if (len(payload.concepts) != 1 or payload.concepts[0].concept_id != node.concept_id
            or payload.concepts[0].weight != 1):
        raise HTTPException(status_code=422, detail="浏览记录的知识点与图谱节点不一致")

    try:
        dwell = float(payload.payload.get("dwell_seconds", 0))
        foreground = float(payload.payload.get("foreground_ratio", 0))
        if not math.isfinite(dwell) or not math.isfinite(foreground):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=422, detail="浏览时长和可见比例必须为有效数值") from None
    dwell = min(120.0, max(0.0, dwell)) if payload.event_type == "knowledge_card_opened" else 0.0
    foreground = min(1.0, max(0.0, foreground))
    confidence = min(1.0, max(0.0, float(node.confidence)))
    return EventCommand(
        idempotency_key=payload.idempotency_key, event_type=payload.event_type,
        object_type="knowledge_graph_node", object_id=node.id,
        concepts=[ConceptContribution(node.concept_id, 1.0)],
        outcome=None, difficulty=None, hint_level=None, attempt_no=None,
        completion=dwell / 120.0, strategy=None,
        upstream_confidence=confidence, alignment_confidence=confidence,
        occurred_at=payload.occurred_at, correction_of_event_id=None,
        payload={"graph_id": graph.id, "revision_id": revision.id,
                 "dwell_seconds": dwell, "foreground_ratio": foreground,
                 "client_observation": True},
    )
