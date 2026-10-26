from __future__ import annotations

import re
from datetime import timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select

from .dependencies import DbSession, StudentUser
from .domains.model_gateway.service import GatewayFailure, stable_hash, utcnow
from .domains.tutoring.contracts import (
    ConversationCreate,
    ConversationListItem,
    ConversationRename,
    ConversationView,
    ExperienceGenerate,
    ExperienceView,
    MemoryResolve,
    MemoryView,
    MessageView,
    TutorTurnCreate,
    TurnView,
)
from .domains.tutoring.service import (
    delete_conversation,
    execute_turn,
    generate_experience,
)
from .learning_support_models import (
    TutorConversation,
    TutorExperience,
    TutorMemory,
    TutorMemorySource,
    TutorMessage,
    TutorTurn,
)
from .models import AuditEvent, CourseEnrollment, ModelRun


router = APIRouter(prefix="/api/v1", tags=["A5 智伴辅导"])


def _require_enrollment(db: DbSession, student_id: str, course_id: str) -> None:
    enrollment = db.scalar(select(CourseEnrollment.id).where(
        CourseEnrollment.student_id == student_id,
        CourseEnrollment.course_id == course_id,
    ))
    if enrollment is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")


def _gateway_http(error: GatewayFailure) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail={
        "code": error.code,
        "message": error.safe_message,
        "model_run_id": error.run_id,
    })


def _message_view(item: TutorMessage) -> MessageView:
    return MessageView(
        id=item.id, turn_id=item.turn_id, ordinal=item.ordinal, role=item.role,
        title=item.title, body=item.body, strategy=item.strategy,
        checkpoint=item.checkpoint_json or {}, visual=item.visual_json,
        citations=item.citations_json or [], inline_practice=item.inline_practice_json,
        created_at=item.created_at,
    )


def _conversation_item(db: DbSession, item: TutorConversation) -> ConversationListItem:
    count = int(db.scalar(select(func.count()).select_from(TutorMessage).where(
        TutorMessage.conversation_id == item.id
    )) or 0)
    preview = db.scalar(select(TutorMessage.body).where(
        TutorMessage.conversation_id == item.id,
        TutorMessage.role == "user",
    ).order_by(TutorMessage.ordinal.desc())) or ""
    return ConversationListItem(
        id=item.id, course_id=item.course_id, title=item.title,
        selected_mode=item.selected_mode, requested_profile_id=item.requested_profile_id,
        experience_mode=item.experience_mode, version=item.version,
        preview=preview[:160], message_count=count,
        created_at=item.created_at, updated_at=item.updated_at,
    )


def _conversation_view(db: DbSession, item: TutorConversation) -> ConversationView:
    base = _conversation_item(db, item)
    messages = list(db.scalars(select(TutorMessage).where(
        TutorMessage.conversation_id == item.id
    ).order_by(TutorMessage.ordinal)).all())
    return ConversationView(
        **base.model_dump(), messages=[_message_view(message) for message in messages]
    )


def _turn_view(db: DbSession, turn: TutorTurn, duplicate: bool) -> TurnView:
    answer = db.scalar(select(TutorMessage).where(
        TutorMessage.turn_id == turn.id,
        TutorMessage.role == "assistant",
    ))
    if answer is None:
        raise HTTPException(status_code=409, detail="辅导回合尚未产生可读取回复")
    run = db.get(ModelRun, turn.model_run_id) if turn.model_run_id else None
    return TurnView(
        turn_id=turn.id,
        conversation_id=turn.conversation_id,
        conversation_version=turn.version_after,
        duplicate=duplicate,
        model_execution={
            "model_run_id": run.id if run else None,
            "requested_profile_id": turn.requested_profile_id,
            "actual_profile_id": run.actual_profile_id if run else None,
            "provider_model_id": run.provider_model_id if run else None,
            "fallback_reason": run.fallback_reason if run else None,
        },
        resolved_concept_ids=turn.resolved_concept_ids_json,
        strategy_plan=turn.strategy_plan_json,
        answer=_message_view(answer),
        experience_decision=turn.experience_decision_json,
        quality=turn.quality_json,
    )


def _memory_view(db: DbSession, item: TutorMemory) -> MemoryView:
    source_count = int(db.scalar(select(func.count()).select_from(TutorMemorySource).where(
        TutorMemorySource.memory_id == item.id,
        TutorMemorySource.active.is_(True),
    )) or 0)
    return MemoryView(
        id=item.id, course_id=item.course_id, memory_kind=item.memory_kind,
        content=item.content, confidence=item.confidence, status=item.status,
        conflict_group=item.conflict_group, expires_at=item.expires_at,
        created_at=item.created_at, updated_at=item.updated_at,
        source_count=source_count,
    )


def _experience_view(item: TutorExperience) -> ExperienceView:
    return ExperienceView(
        id=item.id, course_id=item.course_id, title=item.title,
        context=item.context, method=item.method,
        evidence_summary=item.evidence_summary, confidence=item.confidence,
        generation_mode=item.generation_mode, status=item.status,
        created_at=item.created_at, updated_at=item.updated_at,
    )


@router.post(
    "/student/courses/{course_id}/tutor/conversations",
    response_model=ConversationView,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    course_id: str,
    payload: ConversationCreate,
    student: StudentUser,
    db: DbSession,
) -> ConversationView:
    _require_enrollment(db, student.id, course_id)
    conversation = TutorConversation(
        id=str(uuid4()), student_id=student.id, course_id=course_id,
        title=payload.title or "新对话", selected_mode=payload.selected_mode,
        requested_profile_id=payload.requested_profile_id,
        experience_mode=payload.experience_mode, version=1,
    )
    db.add(conversation)
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=student.id, action="tutor.conversation.created",
        object_type="tutor_conversation", object_id=conversation.id,
        course_id=course_id, outcome="success",
        metadata_json={"selected_mode": payload.selected_mode},
    ))
    db.commit()
    return _conversation_view(db, conversation)


@router.get(
    "/student/courses/{course_id}/tutor/conversations",
    response_model=list[ConversationListItem],
)
def list_conversations(
    course_id: str,
    student: StudentUser,
    db: DbSession,
    q: str = Query(default="", max_length=160),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ConversationListItem]:
    _require_enrollment(db, student.id, course_id)
    statement = select(TutorConversation).where(
        TutorConversation.student_id == student.id,
        TutorConversation.course_id == course_id,
    )
    cleaned = q.strip()
    if cleaned:
        matching_conversations = select(TutorMessage.conversation_id).where(
            TutorMessage.student_id == student.id,
            TutorMessage.course_id == course_id,
            TutorMessage.body.ilike(f"%{cleaned}%"),
        )
        statement = statement.where(or_(
            TutorConversation.title.ilike(f"%{cleaned}%"),
            TutorConversation.id.in_(matching_conversations),
        ))
    rows = list(db.scalars(
        statement.order_by(TutorConversation.updated_at.desc(), TutorConversation.id).limit(limit)
    ).all())
    return [_conversation_item(db, item) for item in rows]


@router.get(
    "/student/courses/{course_id}/tutor/conversations/{conversation_id}",
    response_model=ConversationView,
)
def get_conversation(
    course_id: str,
    conversation_id: str,
    student: StudentUser,
    db: DbSession,
) -> ConversationView:
    _require_enrollment(db, student.id, course_id)
    conversation = db.scalar(select(TutorConversation).where(
        TutorConversation.id == conversation_id,
        TutorConversation.student_id == student.id,
        TutorConversation.course_id == course_id,
    ))
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在或无权访问")
    return _conversation_view(db, conversation)


@router.patch(
    "/student/courses/{course_id}/tutor/conversations/{conversation_id}",
    response_model=ConversationView,
)
def rename_conversation(
    course_id: str,
    conversation_id: str,
    payload: ConversationRename,
    student: StudentUser,
    db: DbSession,
) -> ConversationView:
    _require_enrollment(db, student.id, course_id)
    conversation = db.scalar(select(TutorConversation).where(
        TutorConversation.id == conversation_id,
        TutorConversation.student_id == student.id,
        TutorConversation.course_id == course_id,
    ).with_for_update())
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在或无权访问")
    if conversation.version != payload.version:
        raise HTTPException(status_code=409, detail="对话版本已更新，请刷新后重试")
    conversation.title = payload.title
    conversation.version += 1
    conversation.updated_at = utcnow()
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=student.id, action="tutor.conversation.renamed",
        object_type="tutor_conversation", object_id=conversation.id,
        course_id=course_id, outcome="success", metadata_json={"version": conversation.version},
    ))
    db.commit()
    return _conversation_view(db, conversation)


@router.delete(
    "/student/courses/{course_id}/tutor/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_conversation(
    course_id: str,
    conversation_id: str,
    student: StudentUser,
    db: DbSession,
):
    _require_enrollment(db, student.id, course_id)
    delete_conversation(
        db, student_id=student.id, course_id=course_id,
        conversation_id=conversation_id,
    )
    return None


@router.post(
    "/student/courses/{course_id}/tutor/conversations/{conversation_id}/turns",
    response_model=TurnView,
)
def send_turn(
    course_id: str,
    conversation_id: str,
    payload: TutorTurnCreate,
    request: Request,
    student: StudentUser,
    db: DbSession,
) -> TurnView:
    _require_enrollment(db, student.id, course_id)
    try:
        turn, duplicate = execute_turn(
            db,
            settings=request.app.state.settings,
            adapter_registry=request.app.state.model_adapter_registry,
            student=student, course_id=course_id,
            conversation_id=conversation_id, payload=payload,
            citation_verifier=getattr(request.app.state, "tutor_citation_verifier", None),
        )
    except GatewayFailure as error:
        raise _gateway_http(error) from error
    return _turn_view(db, turn, duplicate)


@router.get(
    "/student/courses/{course_id}/tutor/memories",
    response_model=list[MemoryView],
)
def list_memories(
    course_id: str,
    student: StudentUser,
    db: DbSession,
    include_expired: bool = False,
) -> list[MemoryView]:
    _require_enrollment(db, student.id, course_id)
    statement = select(TutorMemory).where(
        TutorMemory.student_id == student.id,
        TutorMemory.course_id == course_id,
        TutorMemory.deleted_at.is_(None),
        TutorMemory.status.not_in(("deleted", "superseded")),
    )
    if not include_expired:
        now = utcnow()
        statement = statement.where(or_(
            TutorMemory.expires_at.is_(None),
            TutorMemory.expires_at > now,
        ))
    rows = list(db.scalars(statement.order_by(
        TutorMemory.status.desc(), TutorMemory.updated_at.desc(), TutorMemory.id
    )).all())
    return [_memory_view(db, item) for item in rows]


@router.post(
    "/student/courses/{course_id}/tutor/memories/{memory_id}:resolve",
    response_model=MemoryView,
)
def resolve_memory(
    course_id: str,
    memory_id: str,
    payload: MemoryResolve,
    student: StudentUser,
    db: DbSession,
) -> MemoryView:
    _require_enrollment(db, student.id, course_id)
    memory = db.scalar(select(TutorMemory).where(
        TutorMemory.id == memory_id,
        TutorMemory.student_id == student.id,
        TutorMemory.course_id == course_id,
        TutorMemory.deleted_at.is_(None),
    ).with_for_update())
    if memory is None:
        raise HTTPException(status_code=404, detail="记忆不存在或无权访问")
    now = utcnow()
    result = memory
    if payload.action == "confirm":
        memory.status = "confirmed"
        memory.confidence = max(memory.confidence, 0.9)
        memory.version += 1
        memory.updated_at = now
    elif payload.action == "delete":
        memory.status = "deleted"
        memory.deleted_at = now
        memory.version += 1
        memory.updated_at = now
    else:
        conflict_group = memory.conflict_group or str(uuid4())
        memory.status = "conflicted"
        memory.conflict_group = conflict_group
        memory.version += 1
        memory.updated_at = now
        replacement = payload.replacement_content or ""
        result = TutorMemory(
            id=str(uuid4()), student_id=student.id, course_id=course_id,
            memory_kind=memory.memory_kind, content=replacement,
            content_hash=stable_hash(replacement), confidence=1.0,
            status="confirmed", conflict_group=conflict_group, version=1,
        )
        db.add(result)
        db.flush()
        db.add(TutorMemorySource(
            id=str(uuid4()), memory_id=result.id,
            source_kind="student_correction", source_id=memory.id,
            evidence_quote_hash=stable_hash(replacement), active=True,
        ))
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=student.id, action=f"tutor.memory.{payload.action}",
        object_type="tutor_memory", object_id=memory.id, course_id=course_id,
        outcome="success", metadata_json={"result_memory_id": result.id},
    ))
    db.commit()
    return _memory_view(db, result)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", value.lower()))


@router.post(
    "/student/courses/{course_id}/tutor/memories:compress",
    response_model=list[MemoryView],
)
def compress_memories(
    course_id: str,
    student: StudentUser,
    db: DbSession,
) -> list[MemoryView]:
    _require_enrollment(db, student.id, course_id)
    rows = list(db.scalars(select(TutorMemory).where(
        TutorMemory.student_id == student.id,
        TutorMemory.course_id == course_id,
        TutorMemory.deleted_at.is_(None),
        TutorMemory.status.in_(("active", "confirmed")),
    ).order_by(TutorMemory.memory_kind, TutorMemory.created_at, TutorMemory.id)).all())
    survivors: list[TutorMemory] = []
    for item in rows:
        item_tokens = _tokens(item.content)
        match = next((candidate for candidate in survivors if (
            candidate.memory_kind == item.memory_kind
            and len(item_tokens & _tokens(candidate.content))
            / max(1, len(item_tokens | _tokens(candidate.content))) >= 0.75
        )), None)
        if match is None:
            survivors.append(item)
            continue
        if (item.status == "confirmed", item.confidence, len(item.content)) > (
            match.status == "confirmed", match.confidence, len(match.content)
        ):
            survivors.remove(match)
            survivors.append(item)
            item, match = match, item
        sources = list(db.scalars(select(TutorMemorySource).where(
            TutorMemorySource.memory_id == item.id,
            TutorMemorySource.active.is_(True),
        )).all())
        for source in sources:
            duplicate = db.scalar(select(TutorMemorySource.id).where(
                TutorMemorySource.memory_id == match.id,
                TutorMemorySource.source_kind == source.source_kind,
                TutorMemorySource.source_id == source.source_id,
            ))
            if duplicate is None:
                db.add(TutorMemorySource(
                    id=str(uuid4()), memory_id=match.id,
                    source_kind=source.source_kind, source_id=source.source_id,
                    conversation_id=source.conversation_id, turn_id=source.turn_id,
                    evidence_quote_hash=source.evidence_quote_hash, active=True,
                ))
            source.active = False
        item.status = "superseded"
        item.version += 1
        match.confidence = max(match.confidence, item.confidence)
        match.version += 1
        match.updated_at = utcnow()
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=student.id, action="tutor.memory.compressed",
        object_type="course", object_id=course_id, course_id=course_id,
        outcome="success", metadata_json={
            "input_count": len(rows), "active_count": len(survivors),
        },
    ))
    db.commit()
    return [_memory_view(db, item) for item in survivors]


@router.get(
    "/student/courses/{course_id}/tutor/experiences",
    response_model=list[ExperienceView],
)
def list_experiences(
    course_id: str,
    student: StudentUser,
    db: DbSession,
) -> list[ExperienceView]:
    _require_enrollment(db, student.id, course_id)
    rows = list(db.scalars(select(TutorExperience).where(
        TutorExperience.student_id == student.id,
        TutorExperience.course_id == course_id,
        TutorExperience.deleted_at.is_(None),
        TutorExperience.status == "active",
    ).order_by(TutorExperience.updated_at.desc(), TutorExperience.id)).all())
    return [_experience_view(item) for item in rows]


@router.post(
    "/student/courses/{course_id}/tutor/conversations/{conversation_id}/experiences:generate",
)
def create_experience(
    course_id: str,
    conversation_id: str,
    payload: ExperienceGenerate,
    request: Request,
    student: StudentUser,
    db: DbSession,
) -> dict:
    _require_enrollment(db, student.id, course_id)
    try:
        decision, experience = generate_experience(
            db, settings=request.app.state.settings,
            adapter_registry=request.app.state.model_adapter_registry,
            student=student, course_id=course_id,
            conversation_id=conversation_id,
            idempotency_key=payload.idempotency_key,
            requested_profile_id=payload.requested_profile_id,
            conversation_version=payload.conversation_version,
        )
    except GatewayFailure as error:
        raise _gateway_http(error) from error
    return {
        "decision": decision,
        "experience": _experience_view(experience).model_dump(mode="json") if experience else None,
    }


@router.delete(
    "/student/courses/{course_id}/tutor/experiences/{experience_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_experience(
    course_id: str,
    experience_id: str,
    student: StudentUser,
    db: DbSession,
):
    _require_enrollment(db, student.id, course_id)
    experience = db.scalar(select(TutorExperience).where(
        TutorExperience.id == experience_id,
        TutorExperience.student_id == student.id,
        TutorExperience.course_id == course_id,
        TutorExperience.deleted_at.is_(None),
    ))
    if experience is None:
        raise HTTPException(status_code=404, detail="教学经验不存在或无权访问")
    experience.status = "deleted"
    experience.deleted_at = utcnow()
    experience.updated_at = utcnow()
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=student.id, action="tutor.experience.deleted",
        object_type="tutor_experience", object_id=experience.id, course_id=course_id,
        outcome="success", metadata_json={},
    ))
    db.commit()
    return None
