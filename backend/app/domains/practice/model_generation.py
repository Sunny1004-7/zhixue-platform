from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import Settings
from ...models import (
    AlignmentCandidate,
    AlignmentMention,
    AlignmentReview,
    AlignmentRun,
    AuditEvent,
    BlueprintCell,
    Concept,
    EvidenceSpan,
    GraphNode,
    GraphRevision,
    KnowledgeState,
    ModelAttempt,
    ModelProfile,
    ModelQualityReport,
    ModelRun,
    PromptTemplate,
    QuestionBlueprint,
    QuestionGenerationRun,
)
from ..model_gateway.adapters.openai_compatible import OpenAICompatibleAdapter
from ..model_gateway.contracts import ModelAdapter, ProviderError, ProviderRequest
from ..model_gateway.profile_catalog import active_policy, resolve_profile
from ..model_gateway.service import (
    GatewayFailure,
    _fail_run,
    _record_validation,
    _seal_audit,
    stable_hash,
    stable_json,
)
from .quality import QUALITY_VALIDATOR_VERSION, validate_generation_output
from .schemas import QuestionGenerationOutput


TASK_KIND = "a3.question_generation"
GATE_VERSION = "traceq-generation-gates-1.0.0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _chosen_alignment_concept(db: Session, mention: AlignmentMention) -> str | None:
    review = db.scalar(select(AlignmentReview).where(AlignmentReview.mention_id == mention.id))
    if review is not None and review.status == "decided":
        return review.selected_concept_id if review.decision == "matched" else None
    candidate = db.scalar(select(AlignmentCandidate).where(
        AlignmentCandidate.mention_id == mention.id,
        AlignmentCandidate.recommended.is_(True),
    ))
    return candidate.concept_id if candidate is not None else None


def _concept_material(
    db: Session,
    blueprint: QuestionBlueprint,
    concept_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    concepts = {
        item.id: item for item in db.scalars(select(Concept).where(Concept.id.in_(concept_ids))).all()
    }
    nodes: dict[str, GraphNode] = {}
    graph_revision_id = (blueprint.source_summary_json or {}).get("graph_revision_id")
    if graph_revision_id:
        nodes = {
            item.concept_id: item for item in db.scalars(select(GraphNode).where(
                GraphNode.revision_id == graph_revision_id,
                GraphNode.concept_id.in_(concept_ids),
            )).all()
        }
    if len(nodes) < len(concept_ids):
        fallback_nodes = list(db.scalars(
            select(GraphNode)
            .join(GraphRevision, GraphRevision.id == GraphNode.revision_id)
            .where(
                GraphRevision.status == "published",
                GraphNode.concept_id.in_(concept_ids),
            )
            .order_by(GraphRevision.published_at.desc(), GraphRevision.id)
        ).all())
        for node in fallback_nodes:
            nodes.setdefault(node.concept_id, node)

    evidence_by_concept: dict[str, list[dict[str, Any]]] = {concept_id: [] for concept_id in concept_ids}
    allowed_evidence: dict[str, set[str]] = {concept_id: set() for concept_id in concept_ids}
    alignment_run_id = (blueprint.source_summary_json or {}).get("alignment_run_id")
    alignment = db.get(AlignmentRun, alignment_run_id) if alignment_run_id else None
    if alignment is not None:
        mentions = list(db.scalars(select(AlignmentMention).where(
            AlignmentMention.run_id == alignment.id,
            AlignmentMention.evidence_span_id.is_not(None),
        ).order_by(AlignmentMention.ordinal)).all())
        for mention in mentions:
            concept_id = _chosen_alignment_concept(db, mention)
            span = db.get(EvidenceSpan, mention.evidence_span_id) if mention.evidence_span_id else None
            if concept_id not in evidence_by_concept or span is None:
                continue
            if span.id in allowed_evidence[concept_id]:
                continue
            allowed_evidence[concept_id].add(span.id)
            evidence_by_concept[concept_id].append({
                "evidence_span_id": span.id,
                "quote": span.quote[:1200],
                "locator": span.locator_json,
            })

    states = {
        item.concept_id: item for item in db.scalars(select(KnowledgeState).where(
            KnowledgeState.student_id == blueprint.created_by,
            KnowledgeState.course_id == blueprint.course_id,
            KnowledgeState.concept_id.in_(concept_ids),
        )).all()
    } if blueprint.owner_type == "student" else {}
    material: list[dict[str, Any]] = []
    for concept_id in concept_ids:
        concept = concepts[concept_id]
        node = nodes.get(concept_id)
        state = states.get(concept_id)
        material.append({
            "concept_id": concept_id,
            "name": concept.name,
            "definition": node.definition[:1500] if node else "",
            "key_point": node.key_point[:1500] if node else "",
            "misconception": node.misconception[:1500] if node else "",
            "evidence": evidence_by_concept[concept_id],
            "learner_state": ({
                "mastery": round(state.mastery / 100.0, 4),
                "uncertainty": round(state.uncertainty, 4),
                "evidence_count": state.evidence_count,
                "status": state.status,
            } if state is not None else None),
        })
    return material, allowed_evidence


def generation_context(
    db: Session,
    blueprint: QuestionBlueprint,
    cells: list[BlueprintCell],
) -> tuple[dict[str, Any], dict[str, set[str]]]:
    concept_ids = list(dict.fromkeys(item.concept_id for item in cells))
    concepts, allowed_evidence = _concept_material(db, blueprint, concept_ids)
    return ({
        "course_id": blueprint.course_id,
        "blueprint_id": blueprint.id,
        "blueprint_version": blueprint.version,
        "source": blueprint.source_summary_json,
        "difficulty_mode": blueprint.difficulty_mode,
        "total": blueprint.total,
        "cells": [{
            "blueprint_cell_id": item.id,
            "concept_id": item.concept_id,
            "question_type": item.question_type,
            "count": item.count,
            "difficulty_target": item.difficulty_target,
            "cognitive_level": item.cognitive_level,
        } for item in cells],
        "concepts": concepts,
        "constraints": {
            "exact_cell_counts": True,
            "three_progressive_hints": True,
            "no_answer_leakage": True,
            "judgment_options": ["正确", "错误"],
            "subjective_rubric_weight_sum": 1.0,
        },
    }, allowed_evidence)


def request_input_hash(
    *,
    blueprint: QuestionBlueprint,
    cells: list[BlueprintCell],
    title: str,
    requested_profile_id: str,
    policy_version: str,
    prompt_version: str,
) -> str:
    return stable_hash({
        "blueprint_id": blueprint.id,
        "blueprint_version": blueprint.version,
        "cells": [{
            "id": item.id,
            "concept_id": item.concept_id,
            "question_type": item.question_type,
            "count": item.count,
            "difficulty_target": item.difficulty_target,
            "cognitive_level": item.cognitive_level,
        } for item in cells],
        "title": title,
        "requested_profile_id": requested_profile_id,
        "policy_version": policy_version,
        "prompt_version": prompt_version,
    })


def _fail_generation(
    db: Session,
    generation_run: QuestionGenerationRun,
    model_run: ModelRun,
    *,
    code: str,
    message: str,
    status: str = "failed",
    http_status: int = 503,
) -> None:
    generation_run.status = status
    generation_run.safe_error = message
    generation_run.completed_at = _now()
    _fail_run(
        db,
        model_run,
        code=code,
        message=message,
        status=status,
        http_status=http_status,
    )


def run_question_generation(
    db: Session,
    *,
    settings: Settings,
    adapter_registry: dict[str, ModelAdapter],
    actor_id: str,
    blueprint: QuestionBlueprint,
    cells: list[BlueprintCell],
    title: str,
    requested_profile_id: str,
    idempotency_key: str,
) -> tuple[QuestionGenerationOutput, ModelRun, QuestionGenerationRun]:
    policy = active_policy(db, TASK_KIND)
    if policy is None:
        raise GatewayFailure("MODEL_TASK_POLICY_MISSING", "习题生成任务政策尚未发布", 503)
    prompt = db.scalar(select(PromptTemplate).where(
        PromptTemplate.task_kind == TASK_KIND,
        PromptTemplate.active.is_(True),
    ).order_by(PromptTemplate.created_at.desc()))
    if prompt is None:
        raise GatewayFailure("MODEL_PROMPT_MISSING", "习题生成Prompt修订尚未发布", 503)
    input_hash = request_input_hash(
        blueprint=blueprint,
        cells=cells,
        title=title,
        requested_profile_id=requested_profile_id,
        policy_version=policy.version,
        prompt_version=prompt.version,
    )
    prior = db.scalar(select(ModelRun).where(
        ModelRun.actor_id == actor_id,
        ModelRun.course_id == blueprint.course_id,
        ModelRun.task_kind == TASK_KIND,
        ModelRun.idempotency_key == idempotency_key,
    ))
    if prior is not None:
        if prior.input_hash != input_hash:
            raise GatewayFailure(
                "MODEL_REQUEST_IDEMPOTENCY_CONFLICT",
                "同一幂等键已用于不同的习题生成输入",
                409,
                prior.id,
            )
        raise GatewayFailure(
            prior.error_code or "MODEL_RUN_ALREADY_COMPLETED",
            prior.safe_error or "该习题生成运行已完成，请读取原题组",
            409,
            prior.id,
        )

    profile = db.get(ModelProfile, requested_profile_id)
    if profile is None:
        raise GatewayFailure("MODEL_PROFILE_NOT_FOUND", "所选模型Profile不存在", 404)
    resolved = resolve_profile(db, profile, TASK_KIND)
    model_run = ModelRun(
        id=str(uuid4()),
        actor_id=actor_id,
        course_id=blueprint.course_id,
        task_kind=TASK_KIND,
        requested_profile_id=requested_profile_id,
        actual_profile_id=requested_profile_id if resolved.available else None,
        provider_model_id=resolved.provider_model_id if resolved.available else None,
        task_policy_version=policy.version,
        prompt_template_version=prompt.version,
        status="running",
        idempotency_key=idempotency_key,
        input_hash=input_hash,
        attempt_count=0,
        usage_json={},
    )
    db.add(model_run)
    db.flush()
    generation_run = QuestionGenerationRun(
        id=str(uuid4()),
        blueprint_id=blueprint.id,
        model_run_id=model_run.id,
        requested_profile_id=requested_profile_id,
        actual_profile_id=requested_profile_id if resolved.available else None,
        status="running",
        accepted_count=0,
        rejected_count=0,
    )
    db.add(generation_run)
    db.flush()
    if not resolved.available or resolved.revision is None:
        _fail_generation(
            db,
            generation_run,
            model_run,
            code="MODEL_PROFILE_NOT_FEASIBLE",
            message=resolved.unavailable_reason or "所选模型当前不可用",
            http_status=503,
        )

    context, allowed_evidence = generation_context(db, blueprint, cells)
    context_json = stable_json(context)
    schema_json = stable_json(QuestionGenerationOutput.model_json_schema())
    user_prompt = prompt.user_template.format(
        course_id=blueprint.course_id,
        blueprint_id=blueprint.id,
        context_json=context_json,
    ) + f"\n必须满足的JSON Schema：\n{schema_json}"
    model_run.prompt_hash = stable_hash({
        "system": prompt.system_template,
        "user": user_prompt,
    })
    db.commit()

    adapter = adapter_registry.get(resolved.revision.provider_kind) or OpenAICompatibleAdapter()
    max_attempts = min(policy.max_attempts, settings.model_max_attempts)
    raw_content: str | None = None
    for attempt_no in range(1, max_attempts + 1):
        attempt = ModelAttempt(
            id=str(uuid4()),
            run_id=model_run.id,
            attempt_no=attempt_no,
            actual_profile_id=requested_profile_id,
            provider_model_id=resolved.provider_model_id or "",
            status="running",
        )
        db.add(attempt)
        db.commit()
        started = time.perf_counter()
        try:
            response = adapter.invoke(ProviderRequest(
                endpoint=resolved.endpoint or "",
                api_key=resolved.api_key or "",
                model_id=resolved.provider_model_id or "",
                system_prompt=prompt.system_template,
                user_prompt=user_prompt,
                connect_timeout_seconds=settings.model_connect_timeout_seconds,
                timeout_seconds=min(policy.timeout_seconds, settings.model_read_timeout_seconds),
                temperature=0.1,
                max_output_tokens=12000,
            ))
            raw_content = response.content
            attempt.status = "succeeded"
            attempt.input_tokens = response.input_tokens
            attempt.output_tokens = response.output_tokens
            attempt.response_hash = sha256(raw_content.encode("utf-8")).hexdigest()
            model_run.usage_json = {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            }
        except ProviderError as error:
            attempt.status = "failed"
            attempt.error_code = error.code
            attempt.completed_at = _now()
            attempt.latency_ms = round((time.perf_counter() - started) * 1000)
            model_run.attempt_count = attempt_no
            if not error.retryable or attempt_no >= max_attempts:
                _fail_generation(
                    db,
                    generation_run,
                    model_run,
                    code=error.code,
                    message=error.safe_message,
                    http_status=503,
                )
            delay = error.retry_after_seconds
            if delay is None:
                delay = 0.25 * (2 ** (attempt_no - 1))
            time.sleep(max(0.0, min(delay, 2.0)))
            continue
        attempt.completed_at = _now()
        attempt.latency_ms = round((time.perf_counter() - started) * 1000)
        model_run.attempt_count = attempt_no
        break
    if raw_content is None:
        _fail_generation(
            db,
            generation_run,
            model_run,
            code="MODEL_PROVIDER_UNAVAILABLE",
            message="模型服务未能返回习题生成结果",
            http_status=503,
        )

    payload_hash = sha256(raw_content.encode("utf-8")).hexdigest()
    try:
        raw_payload = json.loads(raw_content)
        output = QuestionGenerationOutput.model_validate(raw_payload)
    except (json.JSONDecodeError, ValidationError) as error:
        errors = (
            error.errors(include_url=False, include_input=False)
            if isinstance(error, ValidationError)
            else [{"type": "json_invalid", "msg": "输出不是合法JSON"}]
        )
        _record_validation(db, model_run, policy.output_schema_version, False, errors, payload_hash)
        _fail_generation(
            db,
            generation_run,
            model_run,
            code="MODEL_OUTPUT_SCHEMA_INVALID",
            message="模型习题结果未通过六题型结构校验",
            status="rejected",
            http_status=422,
        )
    _record_validation(db, model_run, policy.output_schema_version, True, [], payload_hash)
    gate = validate_generation_output(
        output,
        cells=cells,
        allowed_evidence_by_concept=allowed_evidence,
    )
    db.add(ModelQualityReport(
        id=str(uuid4()),
        run_id=model_run.id,
        hard_pass=gate.hard_pass,
        gate_version=GATE_VERSION,
        metrics_json={**gate.metrics, "validator_version": QUALITY_VALIDATOR_VERSION},
        issues_json=list(gate.issues),
    ))
    if not gate.hard_pass:
        generation_run.rejected_count = len(output.questions)
        _fail_generation(
            db,
            generation_run,
            model_run,
            code="MODEL_OUTPUT_HARD_GATE_FAILED",
            message="模型习题结果未通过蓝图、答案、提示或量规质量门",
            status="rejected",
            http_status=422,
        )

    generation_run.status = "validated"
    generation_run.accepted_count = len(output.questions)
    model_run.output_hash = stable_hash(output.model_dump(mode="json"))
    model_run.status = "validated"
    model_run.completed_at = _now()
    model_run.audit_hash = _seal_audit(db, model_run, status=model_run.status)
    db.add(AuditEvent(
        id=str(uuid4()),
        actor_id=actor_id,
        action="model.run.validated",
        object_type="question_generation_run",
        object_id=generation_run.id,
        course_id=blueprint.course_id,
        outcome="success",
        metadata_json={
            "task_kind": TASK_KIND,
            "requested_profile_id": requested_profile_id,
            "actual_profile_id": requested_profile_id,
            "question_count": len(output.questions),
        },
    ))
    db.commit()
    return output, model_run, generation_run
