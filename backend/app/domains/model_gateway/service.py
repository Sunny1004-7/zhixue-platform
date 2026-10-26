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
    Concept,
    EvidenceSpan,
    GraphEdge,
    GraphEvidenceLink,
    GraphExtractionArtifact,
    GraphExtractionProposal,
    GraphNode,
    GraphRevision,
    GraphSemanticReviewArtifact,
    GraphSemanticReviewIssue,
    KnowledgeGraph,
    ModelAttempt,
    ModelProfile,
    ModelQualityReport,
    ModelRun,
    PromptTemplate,
    StructuredValidation,
)
from .adapters.openai_compatible import OpenAICompatibleAdapter
from .contracts import ModelAdapter, ProviderError, ProviderRequest
from .profile_catalog import active_policy, resolve_profile
from .schemas import GraphExtractionOutput, GraphSemanticReviewOutput


TASK_KIND = "a2.graph_extract"
GRAPH_EXTRACT_TASK_KIND = TASK_KIND
SEMANTIC_REVIEW_TASK_KIND = "a2.graph_semantic_review"
GATE_VERSION = "a2-graph-extract-gates-1.0.0"
SEMANTIC_REVIEW_GATE_VERSION = "a2-graph-semantic-review-gates-1.0.0"
RELATIONS = {"prerequisite", "contains", "application", "contrast"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return sha256(stable_json(value).encode("utf-8")).hexdigest()


class GatewayFailure(RuntimeError):
    def __init__(self, code: str, safe_message: str, status_code: int, run_id: str | None = None):
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code
        self.run_id = run_id


def _chosen_concept_id(db: Session, mention: AlignmentMention) -> str | None:
    review = db.scalar(select(AlignmentReview).where(AlignmentReview.mention_id == mention.id))
    if review and review.status == "decided":
        return review.selected_concept_id if review.decision == "matched" else None
    candidate = db.scalar(select(AlignmentCandidate).where(
        AlignmentCandidate.mention_id == mention.id,
        AlignmentCandidate.recommended.is_(True),
    ))
    return candidate.concept_id if candidate else None


def build_graph_extract_evidence(db: Session, alignment: AlignmentRun) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    mentions = db.scalars(
        select(AlignmentMention).where(
            AlignmentMention.run_id == alignment.id,
            AlignmentMention.status == "matched",
            AlignmentMention.evidence_span_id.is_not(None),
        ).order_by(AlignmentMention.ordinal)
    ).all()
    for mention in mentions:
        concept_id = _chosen_concept_id(db, mention)
        span = db.get(EvidenceSpan, mention.evidence_span_id) if mention.evidence_span_id else None
        concept = db.get(Concept, concept_id) if concept_id else None
        if concept is None or concept.course_id != alignment.course_id or span is None:
            continue
        item = grouped.setdefault(concept.id, {
            "concept_id": concept.id,
            "concept_name": concept.name,
            "evidence": [],
        })
        if all(existing["evidence_span_id"] != span.id for existing in item["evidence"]):
            item["evidence"].append({
                "evidence_span_id": span.id,
                "quote": span.quote[:1500],
                "locator": span.locator_json,
            })
    return list(grouped.values())


def _record_validation(
    db: Session,
    run: ModelRun,
    schema_version: str,
    passed: bool,
    errors: list[dict[str, Any]],
    payload_hash: str | None,
) -> None:
    db.add(StructuredValidation(
        id=str(uuid4()), run_id=run.id, schema_version=schema_version,
        passed=passed, errors_json=errors, payload_hash=payload_hash,
    ))


def _seal_audit(db: Session, run: ModelRun, *, status: str) -> str:
    previous = db.scalar(
        select(ModelRun.audit_hash)
        .where(
            ModelRun.course_id == run.course_id,
            ModelRun.id != run.id,
            ModelRun.audit_hash.is_not(None),
        )
        .order_by(ModelRun.created_at.desc())
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


def _fail_run(
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
    run.audit_hash = _seal_audit(db, run, status=status)
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=run.actor_id, action="model.run.failed",
        object_type="model_run", object_id=run.id, course_id=run.course_id,
        outcome="failed", metadata_json={"task_kind": run.task_kind, "error_code": code},
    ))
    db.commit()
    raise GatewayFailure(code, message, http_status, run.id)


def _business_issues(
    output: GraphExtractionOutput,
    allowed_concepts: set[str],
    allowed_evidence: set[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen_concepts: set[str] = set()
    seen_relations: set[tuple[str, str, str]] = set()
    for concept in output.concepts:
        if concept.concept_id not in allowed_concepts:
            issues.append({"code": "CONCEPT_OUT_OF_SCOPE", "target": concept.concept_id})
        if concept.concept_id in seen_concepts:
            issues.append({"code": "DUPLICATE_CONCEPT", "target": concept.concept_id})
        seen_concepts.add(concept.concept_id)
        invalid_evidence = sorted(set(concept.evidence_span_ids) - allowed_evidence)
        if invalid_evidence:
            issues.append({"code": "EVIDENCE_OUT_OF_SCOPE", "target": concept.concept_id})
    for relation in output.relations:
        key = (relation.from_concept_id, relation.to_concept_id, relation.relation)
        if relation.from_concept_id == relation.to_concept_id:
            issues.append({"code": "SELF_RELATION", "target": ":".join(key)})
        if relation.from_concept_id not in seen_concepts or relation.to_concept_id not in seen_concepts:
            issues.append({"code": "RELATION_ENDPOINT_NOT_EXTRACTED", "target": ":".join(key)})
        if relation.relation not in RELATIONS:
            issues.append({"code": "RELATION_NOT_ALLOWED", "target": relation.relation})
        if key in seen_relations:
            issues.append({"code": "DUPLICATE_RELATION", "target": ":".join(key)})
        seen_relations.add(key)
        if set(relation.evidence_span_ids) - allowed_evidence:
            issues.append({"code": "EVIDENCE_OUT_OF_SCOPE", "target": ":".join(key)})
    return issues


def run_graph_extraction(
    db: Session,
    *,
    settings: Settings,
    adapter_registry: dict[str, ModelAdapter],
    actor_id: str,
    graph: KnowledgeGraph,
    revision: GraphRevision,
    alignment: AlignmentRun,
    requested_profile_id: str,
    idempotency_key: str,
) -> GraphExtractionArtifact:
    policy = active_policy(db, TASK_KIND)
    prompt = db.scalar(select(PromptTemplate).where(
        PromptTemplate.task_kind == TASK_KIND,
        PromptTemplate.active.is_(True),
    ).order_by(PromptTemplate.created_at.desc()))
    if policy is None or prompt is None:
        raise GatewayFailure("MODEL_TASK_NOT_CONFIGURED", "图谱抽取任务尚未完成配置", 503)
    evidence = build_graph_extract_evidence(db, alignment)
    if not evidence:
        raise GatewayFailure(
            "GRAPH_EXTRACTION_EVIDENCE_REQUIRED",
            "图谱结构抽取需要来自教学文件的原文证据；自然语言对齐可直接加入知识点",
            422,
        )
    request_basis = {
        "course_id": graph.course_id,
        "graph_id": graph.id,
        "revision_id": revision.id,
        "revision_version": revision.version,
        "alignment_run_id": alignment.id,
        "requested_profile_id": requested_profile_id,
        "evidence": evidence,
        "policy_version": policy.version,
        "prompt_version": prompt.version,
    }
    input_hash = stable_hash(request_basis)
    prior = db.scalar(select(ModelRun).where(
        ModelRun.actor_id == actor_id,
        ModelRun.course_id == graph.course_id,
        ModelRun.task_kind == TASK_KIND,
        ModelRun.idempotency_key == idempotency_key,
    ))
    if prior:
        if prior.input_hash != input_hash:
            raise GatewayFailure(
                "MODEL_REQUEST_IDEMPOTENCY_CONFLICT",
                "同一幂等键已用于不同的图谱抽取输入",
                409,
                prior.id,
            )
        artifact = db.scalar(select(GraphExtractionArtifact).where(
            GraphExtractionArtifact.model_run_id == prior.id
        ))
        if artifact:
            if artifact.status == "invalidated":
                raise GatewayFailure(
                    "MODEL_DERIVATION_INVALIDATED",
                    "原始教学材料已删除，该抽取结果不能继续复用",
                    410,
                    prior.id,
                )
            return artifact
        raise GatewayFailure(
            prior.error_code or "MODEL_RUN_NOT_REUSABLE",
            prior.safe_error or "该模型运行未生成可复用候选",
            409,
            prior.id,
        )
    profile = db.get(ModelProfile, requested_profile_id)
    if profile is None:
        raise GatewayFailure("MODEL_PROFILE_NOT_FOUND", "所选模型Profile不存在", 404)
    resolved = resolve_profile(db, profile, TASK_KIND)
    run = ModelRun(
        id=str(uuid4()), actor_id=actor_id, course_id=graph.course_id, task_kind=TASK_KIND,
        requested_profile_id=requested_profile_id,
        actual_profile_id=requested_profile_id if resolved.available else None,
        provider_model_id=resolved.provider_model_id if resolved.available else None,
        task_policy_version=policy.version, prompt_template_version=prompt.version,
        status="running", idempotency_key=idempotency_key, input_hash=input_hash,
        attempt_count=0, usage_json={},
    )
    db.add(run)
    db.flush()
    if not resolved.available or not resolved.revision:
        _fail_run(
            db, run, code="MODEL_PROFILE_NOT_FEASIBLE",
            message=resolved.unavailable_reason or "所选模型当前不可用", http_status=503,
        )
    evidence_json = stable_json(evidence)
    schema_json = stable_json(GraphExtractionOutput.model_json_schema())
    user_prompt = prompt.user_template.format(
        course_id=graph.course_id,
        revision_id=revision.id,
        evidence_json=evidence_json,
    ) + f"\n必须满足的JSON Schema：\n{schema_json}"
    run.prompt_hash = stable_hash({"system": prompt.system_template, "user": user_prompt})
    # 在外部调用前提交运行信封，使进程中断或网络故障仍保留可恢复状态。
    db.commit()
    adapter = adapter_registry.get(resolved.revision.provider_kind) or OpenAICompatibleAdapter()
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
                max_output_tokens=3000,
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
                _fail_run(db, run, code=error.code, message=error.safe_message, http_status=503)
            delay = error.retry_after_seconds
            if delay is None:
                delay = 0.25 * (2 ** (attempt_no - 1))
            time.sleep(max(0.0, min(delay, 2.0)))
            continue
        attempt.completed_at = utcnow()
        attempt.latency_ms = round((time.perf_counter() - started) * 1000)
        run.attempt_count = attempt_no
        break
    if raw_content is None:
        _fail_run(
            db, run, code="MODEL_PROVIDER_UNAVAILABLE",
            message="模型服务未能返回结果", http_status=503,
        )
    payload_hash = sha256(raw_content.encode("utf-8")).hexdigest()
    try:
        raw_payload = json.loads(raw_content)
        output = GraphExtractionOutput.model_validate(raw_payload)
    except (json.JSONDecodeError, ValidationError) as error:
        errors = error.errors(include_url=False) if isinstance(error, ValidationError) else [{
            "type": "json_invalid", "msg": "输出不是合法JSON",
        }]
        _record_validation(db, run, policy.output_schema_version, False, errors, payload_hash)
        _fail_run(
            db, run, code="MODEL_OUTPUT_SCHEMA_INVALID",
            message="模型结果未通过结构校验，未写入图谱候选", status="rejected", http_status=422,
        )
    _record_validation(db, run, policy.output_schema_version, True, [], payload_hash)
    allowed_concepts = {item["concept_id"] for item in evidence}
    allowed_evidence = {
        span["evidence_span_id"] for item in evidence for span in item["evidence"]
    }
    issues = _business_issues(output, allowed_concepts, allowed_evidence)
    quality = ModelQualityReport(
        id=str(uuid4()), run_id=run.id, hard_pass=not issues, gate_version=GATE_VERSION,
        metrics_json={
            "concept_count": len(output.concepts),
            "relation_count": len(output.relations),
            "evidence_span_count": len(allowed_evidence),
            "reference_validity": 1.0 if not issues else 0.0,
        },
        issues_json=issues,
    )
    db.add(quality)
    if issues:
        _fail_run(
            db, run, code="MODEL_OUTPUT_HARD_GATE_FAILED",
            message="模型结果包含候选范围外的知识点、证据或关系，已阻止写入",
            status="rejected", http_status=422,
        )
    artifact = GraphExtractionArtifact(
        id=str(uuid4()), course_id=graph.course_id, graph_id=graph.id,
        revision_id=revision.id, alignment_run_id=alignment.id, model_run_id=run.id,
        status="awaiting_review", created_by=actor_id,
        base_revision_version=revision.version, version=1,
    )
    db.add(artifact)
    db.flush()
    for concept in output.concepts:
        db.add(GraphExtractionProposal(
            id=str(uuid4()), artifact_id=artifact.id, proposal_kind="concept",
            concept_id=concept.concept_id, evidence_span_ids=concept.evidence_span_ids,
            confidence=concept.confidence, rationale="材料中识别到该规范知识点",
            status="pending",
        ))
    for relation in output.relations:
        db.add(GraphExtractionProposal(
            id=str(uuid4()), artifact_id=artifact.id, proposal_kind="relation",
            from_concept_id=relation.from_concept_id, to_concept_id=relation.to_concept_id,
            relation=relation.relation, evidence_span_ids=relation.evidence_span_ids,
            confidence=relation.confidence, rationale=relation.rationale,
            status="pending",
        ))
    run.output_hash = stable_hash(output.model_dump(mode="json"))
    run.status = "validated"
    run.completed_at = utcnow()
    run.audit_hash = _seal_audit(db, run, status=run.status)
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=actor_id, action="model.run.validated",
        object_type="graph_extraction_artifact", object_id=artifact.id,
        course_id=graph.course_id, outcome="success",
        metadata_json={
            "task_kind": TASK_KIND,
            "requested_profile_id": requested_profile_id,
            "actual_profile_id": requested_profile_id,
            "proposal_count": len(output.concepts) + len(output.relations),
        },
    ))
    db.commit()
    return artifact


def build_graph_semantic_review_context(
    db: Session,
    graph: KnowledgeGraph,
    revision: GraphRevision,
) -> tuple[dict[str, Any], dict[str, set[str]], dict[str, set[str]]]:
    nodes = list(db.scalars(
        select(GraphNode).where(GraphNode.revision_id == revision.id).order_by(GraphNode.label)
    ).all())
    edges = list(db.scalars(
        select(GraphEdge).where(GraphEdge.revision_id == revision.id).order_by(GraphEdge.relation, GraphEdge.id)
    ).all())
    node_by_id = {node.id: node for node in nodes}
    links = list(db.scalars(select(GraphEvidenceLink).where(
        GraphEvidenceLink.revision_id == revision.id,
        GraphEvidenceLink.active.is_(True),
    )).all())
    evidence_by_target: dict[str, set[str]] = {}
    for link in links:
        target_key = f"node:{link.node_id}" if link.node_id else f"edge:{link.edge_id}"
        if link.evidence_span_id:
            evidence_by_target.setdefault(target_key, set()).add(link.evidence_span_id)
    edge_views = []
    for edge in edges:
        from_node = node_by_id.get(edge.from_node_id)
        to_node = node_by_id.get(edge.to_node_id)
        edge_views.append({
            "id": edge.id,
            "from_node_id": edge.from_node_id,
            "from_label": from_node.label if from_node else "",
            "to_node_id": edge.to_node_id,
            "to_label": to_node.label if to_node else "",
            "relation": edge.relation,
            "origin": edge.origin,
            "confidence": edge.confidence,
            "evidence_span_ids": sorted(evidence_by_target.get(f"edge:{edge.id}", set())),
        })
    context = {
        "graph": {
            "id": graph.id,
            "title": graph.title,
            "revision_id": revision.id,
            "revision_version": revision.version,
            "mode": revision.mode,
        },
        "allowed_targets": {
            "graph": [graph.id],
            "node": [node.id for node in nodes],
            "edge": [edge.id for edge in edges],
        },
        "nodes": [{
            "id": node.id,
            "concept_id": node.concept_id,
            "label": node.label,
            "node_type": node.node_type,
            "definition": node.definition,
            "key_point": node.key_point,
            "misconception": node.misconception,
            "origin": node.origin,
            "confidence": node.confidence,
            "evidence_span_ids": sorted(evidence_by_target.get(f"node:{node.id}", set())),
        } for node in nodes],
        "edges": edge_views,
        "review_boundary": (
            "只允许指出当前graph/node/edge目标上的语义、证据、方向或教学表达问题；"
            "不得新增节点、关系或直接修改图谱。"
        ),
    }
    target_ids = {
        "graph": {graph.id},
        "node": {node.id for node in nodes},
        "edge": {edge.id for edge in edges},
    }
    return context, target_ids, evidence_by_target


def _semantic_business_issues(
    output: GraphSemanticReviewOutput,
    *,
    graph_id: str,
    target_ids: dict[str, set[str]],
    evidence_by_target: dict[str, set[str]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    all_evidence = set().union(*evidence_by_target.values()) if evidence_by_target else set()
    seen: set[tuple[str, str, str, str]] = set()
    for item in output.issues:
        key = (item.issue_code, item.severity, item.target_type, item.target_id)
        if key in seen:
            issues.append({"code": "DUPLICATE_REVIEW_ISSUE", "target": ":".join(key)})
        seen.add(key)
        if item.target_type == "graph":
            if item.target_id != graph_id:
                issues.append({"code": "TARGET_OUT_OF_SCOPE", "target": item.target_id})
            allowed_evidence = all_evidence
        else:
            if item.target_id not in target_ids.get(item.target_type, set()):
                issues.append({"code": "TARGET_OUT_OF_SCOPE", "target": item.target_id})
                allowed_evidence = set()
            else:
                allowed_evidence = evidence_by_target.get(f"{item.target_type}:{item.target_id}", set())
        invalid_evidence = sorted(set(item.evidence_span_ids) - allowed_evidence)
        if invalid_evidence:
            issues.append({
                "code": "EVIDENCE_OUT_OF_SCOPE",
                "target": item.target_id,
                "evidence_span_ids": invalid_evidence,
            })
    return issues


def run_graph_semantic_review(
    db: Session,
    *,
    settings: Settings,
    adapter_registry: dict[str, ModelAdapter],
    actor_id: str,
    graph: KnowledgeGraph,
    revision: GraphRevision,
    requested_profile_id: str,
    idempotency_key: str,
) -> GraphSemanticReviewArtifact:
    policy = active_policy(db, SEMANTIC_REVIEW_TASK_KIND)
    prompt = db.scalar(select(PromptTemplate).where(
        PromptTemplate.task_kind == SEMANTIC_REVIEW_TASK_KIND,
        PromptTemplate.active.is_(True),
    ).order_by(PromptTemplate.created_at.desc()))
    if policy is None or prompt is None:
        raise GatewayFailure("MODEL_TASK_NOT_CONFIGURED", "图谱语义预审任务尚未完成配置", 503)
    context, target_ids, evidence_by_target = build_graph_semantic_review_context(db, graph, revision)
    if not context["nodes"]:
        raise GatewayFailure(
            "GRAPH_SEMANTIC_REVIEW_EMPTY_GRAPH",
            "当前图谱没有知识点，无法进行语义预审",
            422,
        )
    request_basis = {
        "course_id": graph.course_id,
        "graph_id": graph.id,
        "revision_id": revision.id,
        "revision_version": revision.version,
        "requested_profile_id": requested_profile_id,
        "context": context,
        "policy_version": policy.version,
        "prompt_version": prompt.version,
    }
    input_hash = stable_hash(request_basis)
    prior = db.scalar(select(ModelRun).where(
        ModelRun.actor_id == actor_id,
        ModelRun.course_id == graph.course_id,
        ModelRun.task_kind == SEMANTIC_REVIEW_TASK_KIND,
        ModelRun.idempotency_key == idempotency_key,
    ))
    if prior:
        if prior.input_hash != input_hash:
            raise GatewayFailure(
                "MODEL_REQUEST_IDEMPOTENCY_CONFLICT",
                "同一幂等键已用于不同的图谱语义预审输入",
                409,
                prior.id,
            )
        artifact = db.scalar(select(GraphSemanticReviewArtifact).where(
            GraphSemanticReviewArtifact.model_run_id == prior.id
        ))
        if artifact:
            if artifact.status == "superseded":
                raise GatewayFailure(
                    "MODEL_DERIVATION_SUPERSEDED",
                    "图谱已更新，该语义预审结果需要重新生成",
                    410,
                    prior.id,
                )
            return artifact
        raise GatewayFailure(
            prior.error_code or "MODEL_RUN_NOT_REUSABLE",
            prior.safe_error or "该模型运行未生成可复用语义预审结果",
            409,
            prior.id,
        )
    profile = db.get(ModelProfile, requested_profile_id)
    if profile is None:
        raise GatewayFailure("MODEL_PROFILE_NOT_FOUND", "所选模型Profile不存在", 404)
    resolved = resolve_profile(db, profile, SEMANTIC_REVIEW_TASK_KIND)
    run = ModelRun(
        id=str(uuid4()), actor_id=actor_id, course_id=graph.course_id,
        task_kind=SEMANTIC_REVIEW_TASK_KIND,
        requested_profile_id=requested_profile_id,
        actual_profile_id=requested_profile_id if resolved.available else None,
        provider_model_id=resolved.provider_model_id if resolved.available else None,
        task_policy_version=policy.version, prompt_template_version=prompt.version,
        status="running", idempotency_key=idempotency_key, input_hash=input_hash,
        attempt_count=0, usage_json={},
    )
    db.add(run)
    db.flush()
    if not resolved.available or not resolved.revision:
        _fail_run(
            db, run, code="MODEL_PROFILE_NOT_FEASIBLE",
            message=resolved.unavailable_reason or "所选模型当前不可用", http_status=503,
        )
    context_json = stable_json(context)
    schema_json = stable_json(GraphSemanticReviewOutput.model_json_schema())
    user_prompt = prompt.user_template.format(
        course_id=graph.course_id,
        graph_id=graph.id,
        revision_id=revision.id,
        context_json=context_json,
    ) + f"\n必须满足的JSON Schema：\n{schema_json}"
    run.prompt_hash = stable_hash({"system": prompt.system_template, "user": user_prompt})
    db.commit()
    adapter = adapter_registry.get(resolved.revision.provider_kind) or OpenAICompatibleAdapter()
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
                max_output_tokens=2500,
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
                _fail_run(db, run, code=error.code, message=error.safe_message, http_status=503)
            delay = error.retry_after_seconds
            if delay is None:
                delay = 0.25 * (2 ** (attempt_no - 1))
            time.sleep(max(0.0, min(delay, 2.0)))
            continue
        attempt.completed_at = utcnow()
        attempt.latency_ms = round((time.perf_counter() - started) * 1000)
        run.attempt_count = attempt_no
        break
    if raw_content is None:
        _fail_run(
            db, run, code="MODEL_PROVIDER_UNAVAILABLE",
            message="模型服务未能返回结果", http_status=503,
        )
    payload_hash = sha256(raw_content.encode("utf-8")).hexdigest()
    try:
        raw_payload = json.loads(raw_content)
        output = GraphSemanticReviewOutput.model_validate(raw_payload)
    except (json.JSONDecodeError, ValidationError) as error:
        errors = error.errors(include_url=False) if isinstance(error, ValidationError) else [{
            "type": "json_invalid", "msg": "输出不是合法JSON",
        }]
        _record_validation(db, run, policy.output_schema_version, False, errors, payload_hash)
        _fail_run(
            db, run, code="MODEL_OUTPUT_SCHEMA_INVALID",
            message="模型语义预审结果未通过结构校验", status="rejected", http_status=422,
        )
    _record_validation(db, run, policy.output_schema_version, True, [], payload_hash)
    gate_issues = _semantic_business_issues(
        output, graph_id=graph.id, target_ids=target_ids, evidence_by_target=evidence_by_target,
    )
    db.add(ModelQualityReport(
        id=str(uuid4()), run_id=run.id, hard_pass=not gate_issues,
        gate_version=SEMANTIC_REVIEW_GATE_VERSION,
        metrics_json={
            "review_issue_count": len(output.issues),
            "error_count": sum(1 for item in output.issues if item.severity == "error"),
            "warning_count": sum(1 for item in output.issues if item.severity == "warning"),
            "reference_validity": 1.0 if not gate_issues else 0.0,
        },
        issues_json=gate_issues,
    ))
    if gate_issues:
        _fail_run(
            db, run, code="MODEL_OUTPUT_HARD_GATE_FAILED",
            message="模型语义预审引用了当前图谱范围外的对象或证据，已阻止保存",
            status="rejected", http_status=422,
        )
    summary = dict(output.summary)
    summary.update({
        "issue_count": len(output.issues),
        "error_count": sum(1 for item in output.issues if item.severity == "error"),
        "warning_count": sum(1 for item in output.issues if item.severity == "warning"),
        "node_count": len(context["nodes"]),
        "edge_count": len(context["edges"]),
    })
    artifact_status = "awaiting_review" if output.issues else "passed"
    completed_at = utcnow() if not output.issues else None
    artifact = GraphSemanticReviewArtifact(
        id=str(uuid4()), course_id=graph.course_id, graph_id=graph.id,
        revision_id=revision.id, model_run_id=run.id,
        base_revision_version=revision.version,
        independence_status="independent_model_advisory",
        status=artifact_status, summary_json=summary,
        created_by=actor_id, version=1, completed_at=completed_at,
    )
    db.add(artifact)
    db.flush()
    for issue in output.issues:
        db.add(GraphSemanticReviewIssue(
            id=str(uuid4()), artifact_id=artifact.id,
            issue_code=issue.issue_code, severity=issue.severity,
            target_type=issue.target_type, target_id=issue.target_id,
            evidence_span_ids=issue.evidence_span_ids,
            claim=issue.claim, suggestion=issue.suggestion,
            confidence=issue.confidence, status="pending",
        ))
    run.output_hash = stable_hash(output.model_dump(mode="json"))
    run.status = "validated"
    run.completed_at = utcnow()
    run.audit_hash = _seal_audit(db, run, status=run.status)
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=actor_id, action="model.run.validated",
        object_type="graph_semantic_review_artifact", object_id=artifact.id,
        course_id=graph.course_id, outcome="success",
        metadata_json={
            "task_kind": SEMANTIC_REVIEW_TASK_KIND,
            "requested_profile_id": requested_profile_id,
            "actual_profile_id": requested_profile_id,
            "issue_count": len(output.issues),
        },
    ))
    db.commit()
    return artifact
