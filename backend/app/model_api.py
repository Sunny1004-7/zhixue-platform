from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from .dependencies import CurrentUser, DbSession, TeacherUser
from .domains.model_gateway.schemas import (
    GraphExtractionApply,
    GraphExtractionArtifactView,
    GraphExtractionCreate,
    GraphExtractionProposalView,
    GraphSemanticReviewArtifactView,
    GraphSemanticReviewCreate,
    GraphSemanticReviewIssueDecision,
    GraphSemanticReviewIssueView,
    ModelRunView,
    ProposalDecision,
)
from .domains.model_gateway.service import GatewayFailure, run_graph_extraction, run_graph_semantic_review
from .domains.knowledge_graph.revisions import RevisionConflict, claim_revision_change
from .models import (
    AlignmentRun,
    AuditEvent,
    Concept,
    Derivation,
    GraphEdge,
    GraphEvidenceLink,
    GraphExtractionArtifact,
    GraphExtractionProposal,
    GraphNode,
    GraphRevision,
    GraphSemanticReviewArtifact,
    GraphSemanticReviewIssue,
    KnowledgeGraph,
    ModelRun,
)
from .repositories import CourseRepository


router = APIRouter(prefix="/api/v1")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_view(run: ModelRun) -> ModelRunView:
    return ModelRunView(
        id=run.id, task_kind=run.task_kind,
        requested_profile_id=run.requested_profile_id,
        actual_profile_id=run.actual_profile_id,
        provider_model_id=run.provider_model_id,
        task_policy_version=run.task_policy_version,
        prompt_template_version=run.prompt_template_version,
        status=run.status, fallback_reason=run.fallback_reason,
        error_code=run.error_code, safe_error=run.safe_error,
        attempt_count=run.attempt_count, usage=run.usage_json or {},
        audit_hash=run.audit_hash, created_at=run.created_at,
        completed_at=run.completed_at,
    )


def _teacher_artifact(db, user, artifact_id: str) -> GraphExtractionArtifact:
    artifact = db.get(GraphExtractionArtifact, artifact_id)
    if artifact is None or CourseRepository(db).get_teacher_course(user.id, artifact.course_id) is None:
        raise HTTPException(status_code=404, detail="图谱抽取候选不存在或无权访问")
    return artifact


def _teacher_semantic_artifact(db, user, artifact_id: str) -> GraphSemanticReviewArtifact:
    artifact = db.get(GraphSemanticReviewArtifact, artifact_id)
    if artifact is None or CourseRepository(db).get_teacher_course(user.id, artifact.course_id) is None:
        raise HTTPException(status_code=404, detail="图谱语义预审不存在或无权访问")
    return artifact


def _add_material_evidence(
    db,
    *,
    revision_id: str,
    actor_id: str,
    model_run_id: str,
    evidence_span_id: str,
    confidence: float,
    assertion_note: str,
    node_id: str | None = None,
    edge_id: str | None = None,
) -> None:
    existing = db.scalar(select(GraphEvidenceLink).where(
        GraphEvidenceLink.revision_id == revision_id,
        GraphEvidenceLink.node_id == node_id,
        GraphEvidenceLink.edge_id == edge_id,
        GraphEvidenceLink.evidence_span_id == evidence_span_id,
        GraphEvidenceLink.source_kind == "material_span",
        GraphEvidenceLink.active.is_(True),
    ))
    if existing:
        return
    db.add(GraphEvidenceLink(
        id=str(uuid4()), revision_id=revision_id, node_id=node_id, edge_id=edge_id,
        evidence_span_id=evidence_span_id, source_kind="material_span",
        assertion_note=assertion_note, confidence=confidence,
        source_model_run_id=model_run_id, created_by=actor_id, active=True,
    ))


def _artifact_view(db, artifact: GraphExtractionArtifact) -> GraphExtractionArtifactView:
    run = db.get(ModelRun, artifact.model_run_id)
    proposals = list(db.scalars(
        select(GraphExtractionProposal).where(
            GraphExtractionProposal.artifact_id == artifact.id
        ).order_by(GraphExtractionProposal.proposal_kind, GraphExtractionProposal.id)
    ).all())
    concept_ids = {
        value for item in proposals
        for value in (item.concept_id, item.from_concept_id, item.to_concept_id)
        if value
    }
    names = {
        item.id: item.name for item in db.scalars(
            select(Concept).where(Concept.id.in_(concept_ids))
        ).all()
    } if concept_ids else {}
    return GraphExtractionArtifactView(
        id=artifact.id, course_id=artifact.course_id, graph_id=artifact.graph_id,
        revision_id=artifact.revision_id, alignment_run_id=artifact.alignment_run_id,
        status=artifact.status, version=artifact.version,
        base_revision_version=artifact.base_revision_version,
        model_run=_run_view(run), created_at=artifact.created_at,
        applied_at=artifact.applied_at,
        proposals=[GraphExtractionProposalView(
            id=item.id, proposal_kind=item.proposal_kind,
            concept_id=item.concept_id,
            concept_label=names.get(item.concept_id) if item.concept_id else None,
            from_concept_id=item.from_concept_id,
            from_label=names.get(item.from_concept_id) if item.from_concept_id else None,
            to_concept_id=item.to_concept_id,
            to_label=names.get(item.to_concept_id) if item.to_concept_id else None,
            relation=item.relation, evidence_span_ids=item.evidence_span_ids,
            confidence=item.confidence, rationale=item.rationale,
            status=item.status, review_note=item.review_note,
        ) for item in proposals],
    )


def _semantic_review_view(db, artifact: GraphSemanticReviewArtifact) -> GraphSemanticReviewArtifactView:
    run = db.get(ModelRun, artifact.model_run_id)
    issues = list(db.scalars(
        select(GraphSemanticReviewIssue).where(
            GraphSemanticReviewIssue.artifact_id == artifact.id
        ).order_by(GraphSemanticReviewIssue.severity.desc(), GraphSemanticReviewIssue.id)
    ).all())
    node_ids = [item.target_id for item in issues if item.target_type == "node"]
    edge_ids = [item.target_id for item in issues if item.target_type == "edge"]
    node_labels = {
        item.id: item.label for item in db.scalars(
            select(GraphNode).where(GraphNode.id.in_(node_ids))
        ).all()
    } if node_ids else {}
    edges = list(db.scalars(select(GraphEdge).where(GraphEdge.id.in_(edge_ids))).all()) if edge_ids else []
    edge_node_ids = {value for edge in edges for value in (edge.from_node_id, edge.to_node_id)}
    edge_nodes = {
        item.id: item.label for item in db.scalars(
            select(GraphNode).where(GraphNode.id.in_(edge_node_ids))
        ).all()
    } if edge_node_ids else {}
    edge_labels = {
        edge.id: f"{edge_nodes.get(edge.from_node_id, '起点')} → {edge_nodes.get(edge.to_node_id, '终点')}"
        for edge in edges
    }
    return GraphSemanticReviewArtifactView(
        id=artifact.id, course_id=artifact.course_id, graph_id=artifact.graph_id,
        revision_id=artifact.revision_id, base_revision_version=artifact.base_revision_version,
        independence_status=artifact.independence_status, status=artifact.status,
        summary=artifact.summary_json or {}, version=artifact.version,
        model_run=_run_view(run), created_at=artifact.created_at,
        completed_at=artifact.completed_at,
        issues=[GraphSemanticReviewIssueView(
            id=item.id, issue_code=item.issue_code, severity=item.severity,
            target_type=item.target_type, target_id=item.target_id,
            target_label=(
                "整张图谱" if item.target_type == "graph"
                else node_labels.get(item.target_id) if item.target_type == "node"
                else edge_labels.get(item.target_id)
            ),
            evidence_span_ids=item.evidence_span_ids,
            claim=item.claim, suggestion=item.suggestion,
            confidence=item.confidence, status=item.status,
            review_note=item.review_note,
        ) for item in issues],
    )


@router.get("/model-runs/{run_id}", response_model=ModelRunView)
def get_model_run(run_id: str, user: CurrentUser, db: DbSession):
    run = db.get(ModelRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="模型运行不存在")
    allowed = run.actor_id == user.id
    if user.role == "teacher":
        allowed = allowed or CourseRepository(db).get_teacher_course(user.id, run.course_id) is not None
    if not allowed:
        raise HTTPException(status_code=404, detail="模型运行不存在")
    return _run_view(run)


@router.post(
    "/teacher/graphs/{graph_id}/extract-candidates",
    response_model=GraphExtractionArtifactView,
    status_code=status.HTTP_201_CREATED,
)
def create_graph_extraction(
    graph_id: str,
    payload: GraphExtractionCreate,
    request: Request,
    user: TeacherUser,
    db: DbSession,
):
    graph = db.get(KnowledgeGraph, graph_id)
    if graph is None or CourseRepository(db).get_teacher_course(user.id, graph.course_id) is None:
        raise HTTPException(status_code=404, detail="图谱不存在或无权访问")
    revision = db.get(GraphRevision, graph.working_revision_id) if graph.working_revision_id else None
    if revision is None or revision.status != "draft":
        raise HTTPException(status_code=409, detail="请先进入可编辑的图谱草稿")
    if revision.version != payload.expected_revision_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "GRAPH_REVISION_CONFLICT",
                "message": "图谱已被其他操作更新，请刷新后重新提取",
                "expected_version": payload.expected_revision_version,
                "actual_version": revision.version,
            },
        )
    alignment = db.get(AlignmentRun, payload.alignment_run_id)
    if alignment is None or alignment.course_id != graph.course_id:
        raise HTTPException(status_code=404, detail="知识点对齐任务不存在于当前课程")
    if alignment.status != "completed":
        raise HTTPException(status_code=409, detail="请先完成全部知识点歧义复核")
    if not alignment.source_asset_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "GRAPH_EXTRACTION_EVIDENCE_REQUIRED", "message": "自然语言输入可完成知识点对齐；图谱结构抽取需要教学文件原文证据"},
        )
    try:
        artifact = run_graph_extraction(
            db, settings=request.app.state.settings,
            adapter_registry=request.app.state.model_adapter_registry,
            actor_id=user.id, graph=graph, revision=revision, alignment=alignment,
            requested_profile_id=payload.requested_profile_id,
            idempotency_key=payload.idempotency_key,
        )
    except GatewayFailure as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.safe_message, "model_run_id": exc.run_id},
        ) from exc
    return _artifact_view(db, artifact)


@router.get(
    "/teacher/graph-extractions/{artifact_id}",
    response_model=GraphExtractionArtifactView,
)
def get_graph_extraction(artifact_id: str, user: TeacherUser, db: DbSession):
    return _artifact_view(db, _teacher_artifact(db, user, artifact_id))


@router.post(
    "/teacher/graphs/{graph_id}/semantic-review",
    response_model=GraphSemanticReviewArtifactView,
    status_code=status.HTTP_201_CREATED,
)
def create_graph_semantic_review(
    graph_id: str,
    payload: GraphSemanticReviewCreate,
    request: Request,
    user: TeacherUser,
    db: DbSession,
):
    graph = db.get(KnowledgeGraph, graph_id)
    if graph is None or CourseRepository(db).get_teacher_course(user.id, graph.course_id) is None:
        raise HTTPException(status_code=404, detail="图谱不存在或无权访问")
    revision = db.get(GraphRevision, graph.working_revision_id) if graph.working_revision_id else None
    if revision is None or revision.status != "draft":
        raise HTTPException(status_code=409, detail="请先进入可编辑的图谱草稿")
    if revision.version != payload.expected_revision_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "GRAPH_REVISION_CONFLICT",
                "message": "图谱已被其他操作更新，请刷新后重新预审",
                "expected_version": payload.expected_revision_version,
                "actual_version": revision.version,
            },
        )
    try:
        artifact = run_graph_semantic_review(
            db, settings=request.app.state.settings,
            adapter_registry=request.app.state.model_adapter_registry,
            actor_id=user.id, graph=graph, revision=revision,
            requested_profile_id=payload.requested_profile_id,
            idempotency_key=payload.idempotency_key,
        )
    except GatewayFailure as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.safe_message, "model_run_id": exc.run_id},
        ) from exc
    return _semantic_review_view(db, artifact)


@router.get(
    "/teacher/graph-semantic-reviews/{artifact_id}",
    response_model=GraphSemanticReviewArtifactView,
)
def get_graph_semantic_review(artifact_id: str, user: TeacherUser, db: DbSession):
    return _semantic_review_view(db, _teacher_semantic_artifact(db, user, artifact_id))


@router.patch(
    "/teacher/graph-semantic-reviews/{artifact_id}/issues/{issue_id}",
    response_model=GraphSemanticReviewArtifactView,
)
def decide_graph_semantic_review_issue(
    artifact_id: str,
    issue_id: str,
    payload: GraphSemanticReviewIssueDecision,
    user: TeacherUser,
    db: DbSession,
):
    artifact = _teacher_semantic_artifact(db, user, artifact_id)
    if artifact.status == "superseded":
        raise HTTPException(status_code=410, detail="图谱已变化，请重新生成语义预审")
    if artifact.version != payload.expected_artifact_version:
        raise HTTPException(status_code=409, detail="语义预审结果已被更新，请刷新后重试")
    issue = db.get(GraphSemanticReviewIssue, issue_id)
    if issue is None or issue.artifact_id != artifact.id:
        raise HTTPException(status_code=404, detail="语义预审问题不存在")
    issue.status = payload.decision
    issue.reviewed_by = user.id
    issue.review_note = payload.note.strip()
    issue.reviewed_at = _now()
    artifact.version += 1
    pending = db.scalar(select(func.count()).select_from(GraphSemanticReviewIssue).where(
        GraphSemanticReviewIssue.artifact_id == artifact.id,
        GraphSemanticReviewIssue.id != issue.id,
        GraphSemanticReviewIssue.status == "pending",
    )) or 0
    confirmed = db.scalar(select(func.count()).select_from(GraphSemanticReviewIssue).where(
        GraphSemanticReviewIssue.artifact_id == artifact.id,
        GraphSemanticReviewIssue.id != issue.id,
        GraphSemanticReviewIssue.status == "confirmed",
    )) or 0
    confirmed += 1 if payload.decision == "confirmed" else 0
    if pending:
        artifact.status = "awaiting_review"
    else:
        artifact.status = "changes_required" if confirmed else "reviewed"
        artifact.completed_at = _now()
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=user.id, action="graph.semantic_review.issue_decide",
        object_type="graph_semantic_review_issue", object_id=issue.id,
        course_id=artifact.course_id, outcome="success",
        metadata_json={"decision": payload.decision, "artifact_id": artifact.id},
    ))
    db.commit()
    return _semantic_review_view(db, artifact)


@router.patch(
    "/teacher/graph-extractions/{artifact_id}/proposals/{proposal_id}",
    response_model=GraphExtractionArtifactView,
)
def decide_graph_extraction_proposal(
    artifact_id: str,
    proposal_id: str,
    payload: ProposalDecision,
    user: TeacherUser,
    db: DbSession,
):
    artifact = _teacher_artifact(db, user, artifact_id)
    if artifact.status == "invalidated":
        raise HTTPException(status_code=410, detail="候选来源材料已删除")
    if artifact.status == "applied":
        raise HTTPException(status_code=409, detail="该候选制品已经写入图谱")
    if artifact.version != payload.expected_artifact_version:
        raise HTTPException(status_code=409, detail="候选制品已被更新，请刷新后重试")
    proposal = db.get(GraphExtractionProposal, proposal_id)
    if proposal is None or proposal.artifact_id != artifact.id:
        raise HTTPException(status_code=404, detail="候选项不存在")
    proposal.status = payload.decision
    proposal.reviewed_by = user.id
    proposal.review_note = payload.note.strip()
    proposal.reviewed_at = _now()
    artifact.version += 1
    pending = db.scalar(select(func.count()).select_from(GraphExtractionProposal).where(
        GraphExtractionProposal.artifact_id == artifact.id,
        GraphExtractionProposal.id != proposal.id,
        GraphExtractionProposal.status == "pending",
    )) or 0
    accepted = db.scalar(select(func.count()).select_from(GraphExtractionProposal).where(
        GraphExtractionProposal.artifact_id == artifact.id,
        GraphExtractionProposal.id != proposal.id,
        GraphExtractionProposal.status == "accepted",
    )) or 0
    accepted += 1 if payload.decision == "accepted" else 0
    artifact.status = "awaiting_review" if pending else ("ready_to_apply" if accepted else "rejected")
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=user.id, action="graph.extraction.review",
        object_type="graph_extraction_proposal", object_id=proposal.id,
        course_id=artifact.course_id, outcome="success",
        metadata_json={"decision": payload.decision, "artifact_id": artifact.id},
    ))
    db.commit()
    return _artifact_view(db, artifact)


@router.post(
    "/teacher/graph-extractions/{artifact_id}:apply",
    response_model=GraphExtractionArtifactView,
)
def apply_graph_extraction(
    artifact_id: str, payload: GraphExtractionApply,
    user: TeacherUser, db: DbSession,
):
    artifact = _teacher_artifact(db, user, artifact_id)
    if artifact.status == "invalidated":
        raise HTTPException(status_code=410, detail="候选来源材料已删除")
    if artifact.status == "applied":
        return _artifact_view(db, artifact)
    if artifact.status != "ready_to_apply":
        raise HTTPException(status_code=409, detail="请先完成全部候选项复核，并至少接受一项")
    graph = db.get(KnowledgeGraph, artifact.graph_id)
    revision = db.get(GraphRevision, artifact.revision_id)
    if graph is None or revision is None or graph.working_revision_id != revision.id or revision.status != "draft":
        raise HTTPException(status_code=409, detail="目标图谱草稿已变化，不能写入旧候选")
    if artifact.version != payload.expected_artifact_version:
        raise HTTPException(status_code=409, detail="候选制品已被更新，请刷新后重试")
    if (
        artifact.base_revision_version != revision.version
        or payload.expected_revision_version != revision.version
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "GRAPH_REVISION_CONFLICT",
                "message": "候选生成后图谱已变化，请刷新并重新提取",
                "expected_version": artifact.base_revision_version,
                "actual_version": revision.version,
            },
        )
    alignment = db.get(AlignmentRun, artifact.alignment_run_id)
    if alignment is None or alignment.status == "invalidated":
        raise HTTPException(status_code=410, detail="候选来源已失效")
    accepted = list(db.scalars(select(GraphExtractionProposal).where(
        GraphExtractionProposal.artifact_id == artifact.id,
        GraphExtractionProposal.status == "accepted",
    )).all())
    try:
        claim_revision_change(db, revision, payload.expected_revision_version)
    except RevisionConflict as conflict:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "GRAPH_REVISION_CONFLICT",
                "message": "图谱已被其他操作更新，请刷新后重试",
                "expected_version": conflict.expected_version,
                "actual_version": conflict.actual_version,
            },
        ) from conflict
    existing_nodes = list(db.scalars(select(GraphNode).where(
        GraphNode.revision_id == revision.id
    )).all())
    node_by_concept = {node.concept_id: node for node in existing_nodes}
    added_node_ids: list[str] = []
    added_edge_ids: list[str] = []
    for proposal in accepted:
        if proposal.proposal_kind != "concept" or not proposal.concept_id:
            continue
        node = node_by_concept.get(proposal.concept_id)
        if node is None:
            concept = db.get(Concept, proposal.concept_id)
            if concept is None or concept.course_id != artifact.course_id:
                raise HTTPException(status_code=422, detail="候选包含跨课程知识点")
            index = len(node_by_concept)
            node = GraphNode(
                id=str(uuid4()), revision_id=revision.id, concept_id=concept.id,
                label=concept.name, node_type="core", definition="", key_point="",
                misconception="", origin="model_extraction_review",
                confidence=proposal.confidence,
                position_x=200 + (index % 4) * 190,
                position_y=160 + (index // 4) * 125,
            )
            db.add(node)
            db.flush()
            node_by_concept[concept.id] = node
            added_node_ids.append(node.id)
            if alignment.source_asset_id:
                db.add(Derivation(
                    id=str(uuid4()), source_asset_id=alignment.source_asset_id,
                    derived_type="graph_node", derived_id=node.id,
                    relation="model_extracted_into", active=True,
                ))
        for evidence_span_id in proposal.evidence_span_ids:
            _add_material_evidence(
                db, revision_id=revision.id, actor_id=user.id,
                model_run_id=artifact.model_run_id, evidence_span_id=evidence_span_id,
                confidence=proposal.confidence, assertion_note=proposal.rationale,
                node_id=node.id,
            )
    for proposal in accepted:
        if proposal.proposal_kind != "relation" or not proposal.from_concept_id or not proposal.to_concept_id:
            continue
        from_node = node_by_concept.get(proposal.from_concept_id)
        to_node = node_by_concept.get(proposal.to_concept_id)
        if from_node is None or to_node is None:
            raise HTTPException(
                status_code=409,
                detail="已接受关系的端点尚未被接受或不在当前图谱中",
            )
        duplicate = db.scalar(select(GraphEdge).where(
            GraphEdge.revision_id == revision.id,
            GraphEdge.from_node_id == from_node.id,
            GraphEdge.to_node_id == to_node.id,
            GraphEdge.relation == proposal.relation,
        ))
        edge = duplicate
        if edge is None:
            edge = GraphEdge(
                id=str(uuid4()), revision_id=revision.id, from_node_id=from_node.id,
                to_node_id=to_node.id, relation=proposal.relation or "application",
                origin="model_extraction_review", confidence=proposal.confidence,
            )
            db.add(edge)
            db.flush()
            added_edge_ids.append(edge.id)
            if alignment.source_asset_id:
                db.add(Derivation(
                    id=str(uuid4()), source_asset_id=alignment.source_asset_id,
                    derived_type="graph_edge", derived_id=edge.id,
                    relation="model_extracted_into", active=True,
                ))
        for evidence_span_id in proposal.evidence_span_ids:
            _add_material_evidence(
                db, revision_id=revision.id, actor_id=user.id,
                model_run_id=artifact.model_run_id, evidence_span_id=evidence_span_id,
                confidence=proposal.confidence, assertion_note=proposal.rationale,
                edge_id=edge.id,
            )
    revision.source_type = "model_extraction_review"
    revision.source_summary = (
        f"教师复核后写入模型抽取候选：{len(added_node_ids)}个知识点、{len(added_edge_ids)}条关系"
    )
    artifact.status = "applied"
    artifact.version += 1
    artifact.applied_at = _now()
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=user.id, action="graph.extraction.apply",
        object_type="graph_extraction_artifact", object_id=artifact.id,
        course_id=artifact.course_id, outcome="success",
        metadata_json={"added_node_ids": added_node_ids, "added_edge_ids": added_edge_ids},
    ))
    db.commit()
    return _artifact_view(db, artifact)
