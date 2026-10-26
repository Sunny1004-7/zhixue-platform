from __future__ import annotations

import json
import time
from hashlib import sha256
from typing import Any, Callable, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import Settings
from ...models import (
    AuditEvent,
    ModelAttempt,
    ModelProfile,
    ModelQualityReport,
    ModelRun,
    PromptTemplate,
    StructuredValidation,
)
from ..model_gateway.adapters.openai_compatible import OpenAICompatibleAdapter
from ..model_gateway.contracts import ModelAdapter, ProviderError, ProviderRequest
from ..model_gateway.profile_catalog import active_policy, resolve_profile
from ..model_gateway.service import GatewayFailure, stable_hash, stable_json, utcnow


OutputT = TypeVar("OutputT", bound=BaseModel)
BusinessValidator = Callable[[OutputT], list[dict[str, Any]]]


def _seal_audit(db: Session, run: ModelRun, status: str) -> str:
    previous = db.scalar(
        select(ModelRun.audit_hash)
        .where(
            ModelRun.course_id == run.course_id,
            ModelRun.id != run.id,
            ModelRun.audit_hash.is_not(None),
        )
        .order_by(ModelRun.created_at.desc(), ModelRun.id.desc())
    ) or "GENESIS"
    return stable_hash({
        "previous": previous,
        "run_id": run.id,
        "task_kind": run.task_kind,
        "policy_version": run.task_policy_version,
        "prompt_hash": run.prompt_hash,
        "input_hash": run.input_hash,
        "requested_profile_id": run.requested_profile_id,
        "actual_profile_id": run.actual_profile_id,
        "provider_model_id": run.provider_model_id,
        "output_hash": run.output_hash,
        "status": status,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    })


def _fail(
    db: Session,
    run: ModelRun,
    *,
    code: str,
    message: str,
    status: str = "failed",
    http_status: int = 503,
) -> None:
    run.status = status
    run.error_code = code
    run.safe_error = message
    run.completed_at = utcnow()
    run.audit_hash = _seal_audit(db, run, status)
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=run.actor_id, action="model.run.failed",
        object_type="model_run", object_id=run.id, course_id=run.course_id,
        outcome="failed", metadata_json={"task_kind": run.task_kind, "error_code": code},
    ))
    db.commit()
    raise GatewayFailure(code, message, http_status, run.id)


def run_structured_task(
    db: Session,
    *,
    settings: Settings,
    adapter_registry: dict[str, ModelAdapter],
    actor_id: str,
    course_id: str,
    task_kind: str,
    requested_profile_id: str,
    idempotency_key: str,
    context: dict[str, Any],
    output_model: type[OutputT],
    business_validator: BusinessValidator[OutputT] | None = None,
    gate_version: str,
    max_output_tokens: int = 4000,
) -> tuple[OutputT, ModelRun]:
    policy = active_policy(db, task_kind)
    prompt = db.scalar(
        select(PromptTemplate)
        .where(PromptTemplate.task_kind == task_kind, PromptTemplate.active.is_(True))
        .order_by(PromptTemplate.created_at.desc(), PromptTemplate.id.desc())
    )
    if policy is None or prompt is None:
        raise GatewayFailure(
            "MODEL_TASK_NOT_CONFIGURED", "辅导模型任务尚未完成配置", 503
        )
    request_basis = {
        "course_id": course_id,
        "task_kind": task_kind,
        "requested_profile_id": requested_profile_id,
        "context": context,
        "policy_version": policy.version,
        "prompt_version": prompt.version,
    }
    input_hash = stable_hash(request_basis)
    prior = db.scalar(select(ModelRun).where(
        ModelRun.actor_id == actor_id,
        ModelRun.course_id == course_id,
        ModelRun.task_kind == task_kind,
        ModelRun.idempotency_key == idempotency_key,
    ))
    if prior is not None:
        if prior.input_hash != input_hash:
            raise GatewayFailure(
                "MODEL_REQUEST_IDEMPOTENCY_CONFLICT",
                "同一幂等键已用于不同的辅导输入",
                409,
                prior.id,
            )
        raise GatewayFailure(
            prior.error_code or "MODEL_REQUEST_ALREADY_EXECUTED",
            prior.safe_error or "该模型请求已经执行，请读取已持久化结果",
            409,
            prior.id,
        )
    profile = db.get(ModelProfile, requested_profile_id)
    if profile is None:
        raise GatewayFailure("MODEL_PROFILE_NOT_FOUND", "所选模型Profile不存在", 404)
    resolved = resolve_profile(db, profile, task_kind)
    run = ModelRun(
        id=str(uuid4()), actor_id=actor_id, course_id=course_id, task_kind=task_kind,
        requested_profile_id=requested_profile_id,
        actual_profile_id=requested_profile_id if resolved.available else None,
        provider_model_id=resolved.provider_model_id if resolved.available else None,
        task_policy_version=policy.version, prompt_template_version=prompt.version,
        status="running", idempotency_key=idempotency_key, input_hash=input_hash,
        attempt_count=0, usage_json={},
    )
    db.add(run)
    db.flush()
    if not resolved.available or resolved.revision is None:
        _fail(
            db, run, code="MODEL_PROFILE_NOT_FEASIBLE",
            message=resolved.unavailable_reason or "所选模型当前不可用", http_status=503,
        )
    schema_json = stable_json(output_model.model_json_schema())
    context_json = stable_json(context)
    try:
        user_prompt = prompt.user_template.format(
            course_id=course_id,
            context_json=context_json,
            schema_json=schema_json,
        )
    except (KeyError, IndexError, ValueError):
        _fail(
            db, run, code="MODEL_PROMPT_TEMPLATE_INVALID",
            message="辅导任务的提示词模板配置无效", http_status=503,
        )
    if "schema_json" not in prompt.user_template:
        user_prompt += f"\n必须满足的JSON Schema：\n{schema_json}"
    run.prompt_hash = stable_hash({"system": prompt.system_template, "user": user_prompt})
    # 先提交不含隐私正文的运行信息，外部故障仍有记录可查。
    db.commit()
    adapter = (
        adapter_registry.get(resolved.revision.provider_kind)
        or OpenAICompatibleAdapter()
    )
    max_attempts = min(policy.max_attempts, settings.model_max_attempts)
    raw_content: str | None = None
    for attempt_no in range(1, max_attempts + 1):
        attempt = ModelAttempt(
            id=str(uuid4()), run_id=run.id, attempt_no=attempt_no,
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
                max_output_tokens=max_output_tokens,
            ))
            raw_content = response.content
            attempt.status = "succeeded"
            attempt.input_tokens = response.input_tokens
            attempt.output_tokens = response.output_tokens
            attempt.response_hash = sha256(raw_content.encode("utf-8")).hexdigest()
            run.usage_json = {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            }
        except ProviderError as error:
            attempt.status = "failed"
            attempt.error_code = error.code
            attempt.completed_at = utcnow()
            attempt.latency_ms = round((time.perf_counter() - started) * 1000)
            run.attempt_count = attempt_no
            if not error.retryable or attempt_no >= max_attempts:
                _fail(db, run, code=error.code, message=error.safe_message, http_status=503)
            delay = error.retry_after_seconds
            if delay is None:
                delay = 0.25 * (2 ** (attempt_no - 1))
            time.sleep(max(0.0, min(delay, 2.0)))
            continue
        attempt.completed_at = utcnow()
        attempt.latency_ms = round((time.perf_counter() - started) * 1000)
        run.attempt_count = attempt_no
        db.flush()
        break
    if raw_content is None:
        _fail(
            db, run, code="MODEL_PROVIDER_UNAVAILABLE",
            message="模型服务未能返回结果", http_status=503,
        )
    payload_hash = sha256(raw_content.encode("utf-8")).hexdigest()
    try:
        payload = json.loads(raw_content)
        output = output_model.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as error:
        errors = (
            error.errors(include_url=False)
            if isinstance(error, ValidationError)
            else [{"type": "json_invalid", "msg": "输出不是合法JSON"}]
        )
        db.add(StructuredValidation(
            id=str(uuid4()), run_id=run.id,
            schema_version=policy.output_schema_version,
            passed=False, errors_json=errors, payload_hash=payload_hash,
        ))
        _fail(
            db, run, code="MODEL_OUTPUT_SCHEMA_INVALID",
            message="模型结果未通过结构校验", status="rejected", http_status=422,
        )
    db.add(StructuredValidation(
        id=str(uuid4()), run_id=run.id,
        schema_version=policy.output_schema_version,
        passed=True, errors_json=[], payload_hash=payload_hash,
    ))
    issues = business_validator(output) if business_validator else []
    db.add(ModelQualityReport(
        id=str(uuid4()), run_id=run.id, hard_pass=not issues,
        gate_version=gate_version,
        metrics_json={"schema_valid": 1.0, "business_issue_count": len(issues)},
        issues_json=issues,
    ))
    if issues:
        _fail(
            db, run, code="MODEL_OUTPUT_HARD_GATE_FAILED",
            message="模型结果未通过辅导质量硬门", status="rejected", http_status=422,
        )
    run.output_hash = stable_hash(output.model_dump(mode="json"))
    run.status = "validated"
    run.completed_at = utcnow()
    run.audit_hash = _seal_audit(db, run, run.status)
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=actor_id, action="model.run.validated",
        object_type="model_run", object_id=run.id, course_id=course_id,
        outcome="success", metadata_json={
            "task_kind": task_kind,
            "requested_profile_id": requested_profile_id,
            "actual_profile_id": requested_profile_id,
        },
    ))
    db.commit()
    return output, run
