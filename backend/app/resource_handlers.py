from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domains.practice.blueprint import compile_blueprint
from .domains.practice.schemas import (
    BlueprintConceptRequest,
    CompileBlueprintRequest,
    GenerateQuestionSetRequest,
    QuestionTypeCounts,
)
from .domains.practice.service import generate_question_set
from .domains.video_search.api_schemas import VideoSearchJobCreate
from .domains.video_search.provider import (
    InternetArchiveVideoProvider,
    PeerTubeVideoProvider,
    WikimediaVideoProvider,
)
from .domains.video_search.service import VideoSearchService
from .models import AuditEvent, Concept, GraphNode, GraphRevision, KnowledgeGraph, User
from .domains.teaching_decision.service import require_teacher_course


def _teacher(db: Session, teacher_id: str) -> User:
    teacher = db.scalar(select(User).where(User.id == teacher_id, User.role == "teacher"))
    if teacher is None:
        raise ValueError("教师身份不存在")
    return teacher


def _graph_handler(**kwargs: Any) -> dict[str, Any]:
    db: Session = kwargs["db"]
    teacher_id = str(kwargs["teacher_id"])
    course_id = str(kwargs["course_id"])
    student_id = str(kwargs["student_id"])
    concept_ids = list(kwargs["concept_ids"])
    payload = dict(kwargs.get("request_payload") or {})
    teacher = _teacher(db, teacher_id)
    require_teacher_course(db, teacher_id, course_id)
    concepts = list(db.scalars(select(Concept).where(
        Concept.course_id == course_id,
        Concept.id.in_(concept_ids),
    ).order_by(Concept.sort_order)).all())
    if len(concepts) != len(set(concept_ids)):
        raise ValueError("个性化图谱知识点不属于当前课程")
    title = str(payload.get("title") or f"学生 {student_id[:8]} 定向知识图谱").strip()
    if db.scalar(select(KnowledgeGraph).where(
        KnowledgeGraph.course_id == course_id,
        KnowledgeGraph.title == title,
    )) is not None:
        title = f"{title} · {uuid4().hex[:6]}"
    graph = KnowledgeGraph(
        id=f"graph-{uuid4()}", course_id=course_id, title=title, owner_id=teacher.id,
    )
    revision = GraphRevision(
        id=str(uuid4()), graph_id=graph.id, revision_no=1, mode="new", status="draft",
        review_status="pending", source_type="student_state",
        source_summary=f"依据学生 {student_id} 的课程学情状态生成，需教师审核后发布。",
        created_by=teacher.id,
    )
    graph.working_revision_id = revision.id
    db.add_all([graph, revision])
    for position, concept in enumerate(concepts):
        db.add(GraphNode(
            id=str(uuid4()), revision_id=revision.id, concept_id=concept.id,
            label=concept.name, node_type="core", origin="student_state",
            confidence=1.0, position_x=float((position % 4) * 220),
            position_y=float((position // 4) * 150),
        ))
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=teacher.id, action="graph.personalized.draft_created",
        object_type="knowledge_graph", object_id=graph.id, course_id=course_id,
        outcome="success", metadata_json={
            "student_id": student_id, "concept_count": len(concepts),
            "requires_teacher_review": True,
        },
    ))
    db.commit()
    return {
        "job_id": graph.id, "status": "awaiting_review", "resource_id": graph.id,
        "message": "个性化图谱草稿已创建，需教师审核后发布。",
    }


def _question_set_handler(*, settings: Any, adapter_registry: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    db: Session = kwargs["db"]
    teacher_id = str(kwargs["teacher_id"])
    course_id = str(kwargs["course_id"])
    concept_ids = list(kwargs["concept_ids"])
    payload = dict(kwargs.get("request_payload") or {})
    teacher = _teacher(db, teacher_id)
    profile_id = str(payload.get("requested_profile_id") or "gpt-5")
    concepts = [BlueprintConceptRequest(
        concept_id=concept_id,
        counts=QuestionTypeCounts(single=1, judgment=1),
    ) for concept_id in concept_ids]
    blueprint = compile_blueprint(
        db, actor=teacher, course_id=course_id,
        payload=CompileBlueprintRequest(
            source_method="recorded", difficulty_mode="standard",
            requested_profile_id=profile_id, concepts=concepts,
        ),
    )
    generated = generate_question_set(
        db, settings=settings, adapter_registry=adapter_registry,
        actor=teacher, course_id=course_id,
        payload=GenerateQuestionSetRequest(
            blueprint_id=blueprint.id,
            title=str(payload.get("title") or "学生定向巩固练习"),
            requested_profile_id=profile_id,
            idempotency_key=str(kwargs["idempotency_key"]),
        ),
    )
    return {
        "job_id": generated.id, "status": "awaiting_review", "resource_id": generated.id,
        "message": "个性化题组已生成，需教师审核后发布。",
    }


def _video_handler(**kwargs: Any) -> dict[str, Any]:
    db: Session = kwargs["db"]
    teacher_id = str(kwargs["teacher_id"])
    course_id = str(kwargs["course_id"])
    concept_ids = list(kwargs["concept_ids"])
    payload = dict(kwargs.get("request_payload") or {})
    teacher = _teacher(db, teacher_id)
    providers = {
        item.provider_id: item for item in (
            InternetArchiveVideoProvider(), WikimediaVideoProvider(), PeerTubeVideoProvider()
        )
    }
    try:
        job = VideoSearchService(db).create_job(
            teacher=teacher, course_id=course_id,
            payload=VideoSearchJobCreate(
                source_mode="records", topic_ids=concept_ids,
                teaching_intent=str(payload.get("teaching_intent") or "针对学生薄弱知识点检索可核验教学视频"),
                language="zh-CN", requested_profile_id=None,
                allow_deterministic_degrade=True, max_candidates_per_provider=12,
            ),
            idempotency_key=str(kwargs["idempotency_key"]), providers=providers,
        )
    finally:
        for provider in providers.values():
            client = getattr(provider, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()
    if job.status == "failed":
        raise RuntimeError(job.safe_error_message or "视频检索任务失败")
    return {
        "job_id": job.id, "status": "awaiting_review", "resource_id": job.id,
        "message": "视频检索任务已完成，候选结果需教师核验后发布。",
    }


def build_resource_handlers(*, settings: Any, adapter_registry: dict[str, Any]) -> dict[str, Any]:
    def question_handler(**kwargs: Any) -> dict[str, Any]:
        return _question_set_handler(
            settings=settings, adapter_registry=adapter_registry, **kwargs,
        )

    return {
        "graph": _graph_handler,
        "question_set": question_handler,
        "video": _video_handler,
    }
