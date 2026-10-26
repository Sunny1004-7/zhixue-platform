from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .dependencies import DbSession, StudentUser, TeacherUser
from .domains.knowledge_graph.names import normalize_concept_name
from .domains.knowledge_graph.revisions import RevisionConflict, claim_revision_change
from .domains.knowledge_graph.validation import validate_graph
from .domains.trajectory.evidence import classify_state
from .models import (
    AlignmentCandidate,
    AlignmentMention,
    AlignmentReview,
    AlignmentRun,
    AuditEvent,
    Concept,
    Derivation,
    DocumentChunk,
    EvidenceSpan,
    GraphEdge,
    GraphEvidenceLink,
    GraphNode,
    GraphQualityReport,
    GraphRevision,
    KnowledgeGraph,
    KnowledgeState,
    ParsedDocument,
    SourceAsset,
)
from .repositories import CourseRepository
from .schemas import (
    GraphCreateRequest,
    GraphDetailView,
    GraphEdgeCreate,
    GraphEdgeUpdate,
    GraphEdgeView,
    GraphEvidenceBundleView,
    GraphEvidenceSourceView,
    GraphListItem,
    GraphNodeCreate,
    GraphNodeUpdate,
    GraphNodeView,
    GraphMutationGuard,
    GraphQualityView,
    GraphRenameRequest,
)


router = APIRouter(prefix="/api/v1")
VALIDATOR_VERSION = "a2-structural-gates-0.1.0"


def _audit(db, *, actor_id: str, action: str, graph: KnowledgeGraph, object_id: str | None = None, metadata: dict | None = None) -> None:
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=actor_id, action=action, object_type="knowledge_graph",
        object_id=object_id or graph.id, course_id=graph.course_id, outcome="success",
        metadata_json=metadata or {},
    ))


def _teacher_graph(db, user, graph_id: str) -> KnowledgeGraph:
    graph = db.get(KnowledgeGraph, graph_id)
    if graph is None or CourseRepository(db).get_teacher_course(user.id, graph.course_id) is None:
        raise HTTPException(status_code=404, detail="图谱不存在或无权访问")
    return graph


def _editable_revision(db, user, graph_id: str) -> tuple[KnowledgeGraph, GraphRevision]:
    graph = _teacher_graph(db, user, graph_id)
    revision = db.get(GraphRevision, graph.working_revision_id) if graph.working_revision_id else None
    if revision is None:
        raise HTTPException(status_code=409, detail="当前图谱没有可编辑修订")
    if revision.status != "draft":
        raise HTTPException(status_code=409, detail="已发布修订不可直接修改，请先创建更新修订")
    return graph, revision


def _claim_or_conflict(
    db,
    revision: GraphRevision,
    expected_version: int,
    *,
    review_status: str = "pending",
    clear_quality: bool = True,
    extra_values: dict | None = None,
    increment_version: bool = True,
    supersede_semantic: bool = True,
) -> None:
    try:
        claim_revision_change(
            db, revision, expected_version,
            review_status=review_status,
            clear_quality=clear_quality,
            extra_values=extra_values,
            increment_version=increment_version,
            supersede_semantic=supersede_semantic,
        )
    except RevisionConflict as conflict:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "GRAPH_REVISION_CONFLICT",
                "message": "图谱已被其他操作更新，请刷新后再提交",
                "expected_version": conflict.expected_version,
                "actual_version": conflict.actual_version,
            },
        ) from conflict


def _replace_teacher_evidence(
    db,
    *,
    revision: GraphRevision,
    actor_id: str,
    node_id: str | None = None,
    edge_id: str | None = None,
    note: str | None,
) -> None:
    if note is None:
        return
    now = datetime.now(timezone.utc)
    links = db.scalars(select(GraphEvidenceLink).where(
        GraphEvidenceLink.revision_id == revision.id,
        GraphEvidenceLink.node_id == node_id,
        GraphEvidenceLink.edge_id == edge_id,
        GraphEvidenceLink.source_kind == "teacher_statement",
        GraphEvidenceLink.active.is_(True),
    )).all()
    for link in links:
        link.active = False
        link.invalidated_at = now
    cleaned = note.strip()
    if cleaned:
        db.add(GraphEvidenceLink(
            id=str(uuid4()), revision_id=revision.id,
            node_id=node_id, edge_id=edge_id, evidence_span_id=None,
            source_kind="teacher_statement", assertion_note=cleaned,
            confidence=1.0, source_model_run_id=None,
            created_by=actor_id, active=True,
        ))


def _ensure_alignment_evidence(
    db,
    *,
    revision: GraphRevision,
    node: GraphNode,
    mention: AlignmentMention,
    review: AlignmentReview | None,
    candidate: AlignmentCandidate | None,
    actor_id: str,
) -> bool:
    if mention.evidence_span_id:
        source_kind = "material_span"
        evidence_span_id = mention.evidence_span_id
        assertion_note = f"材料对齐识别：{mention.raw_text}"
    elif review is not None and review.note.strip():
        source_kind = "teacher_statement"
        evidence_span_id = None
        assertion_note = review.note.strip()
    else:
        return False

    statement = select(GraphEvidenceLink.id).where(
        GraphEvidenceLink.revision_id == revision.id,
        GraphEvidenceLink.node_id == node.id,
        GraphEvidenceLink.edge_id.is_(None),
        GraphEvidenceLink.source_kind == source_kind,
        GraphEvidenceLink.active.is_(True),
    )
    if evidence_span_id is None:
        statement = statement.where(
            GraphEvidenceLink.evidence_span_id.is_(None),
            GraphEvidenceLink.assertion_note == assertion_note,
        )
    else:
        statement = statement.where(
            GraphEvidenceLink.evidence_span_id == evidence_span_id,
        )
    if db.scalar(statement) is not None:
        return False

    db.add(GraphEvidenceLink(
        id=str(uuid4()), revision_id=revision.id,
        node_id=node.id, edge_id=None, evidence_span_id=evidence_span_id,
        source_kind=source_kind, assertion_note=assertion_note,
        confidence=candidate.final_score if candidate else 1.0,
        source_model_run_id=None, created_by=actor_id, active=True,
    ))
    return True


def _revision_parts(db, revision_id: str):
    nodes = list(db.scalars(select(GraphNode).where(GraphNode.revision_id == revision_id).order_by(GraphNode.position_y, GraphNode.position_x)).all())
    edges = list(db.scalars(select(GraphEdge).where(GraphEdge.revision_id == revision_id).order_by(GraphEdge.id)).all())
    quality = db.scalar(select(GraphQualityReport).where(GraphQualityReport.revision_id == revision_id).order_by(GraphQualityReport.created_at.desc()))
    return nodes, edges, quality


def _quality_view(quality: GraphQualityReport | None) -> GraphQualityView | None:
    if quality is None:
        return None
    return GraphQualityView(
        hard_pass=quality.hard_pass, quality_score=quality.quality_score,
        metrics=quality.metrics_json, issues=quality.issues_json,
        validator_version=quality.validator_version, created_at=quality.created_at,
    )


def _detail(db, graph: KnowledgeGraph, revision: GraphRevision, student_id: str | None = None) -> GraphDetailView:
    nodes, edges, quality = _revision_parts(db, revision.id)
    evidence_links = db.scalars(select(GraphEvidenceLink).where(
        GraphEvidenceLink.revision_id == revision.id,
        GraphEvidenceLink.active.is_(True),
    )).all()
    node_evidence_count: dict[str, int] = {}
    edge_evidence_count: dict[str, int] = {}
    for link in evidence_links:
        if link.node_id:
            node_evidence_count[link.node_id] = node_evidence_count.get(link.node_id, 0) + 1
        if link.edge_id:
            edge_evidence_count[link.edge_id] = edge_evidence_count.get(link.edge_id, 0) + 1
    mastery_by_concept = {}
    if student_id:
        states = db.scalars(select(KnowledgeState).where(
            KnowledgeState.student_id == student_id,
            KnowledgeState.course_id == graph.course_id,
        )).all()
        mastery_by_concept = {item.concept_id: item for item in states}
    return GraphDetailView(
        id=graph.id, course_id=graph.course_id, title=graph.title, status=graph.status,
        revision_id=revision.id, revision_no=revision.revision_no,
        revision_status=revision.status, review_status=revision.review_status,
        mode=revision.mode, source_type=revision.source_type, source_summary=revision.source_summary,
        version=revision.version,
        nodes=[GraphNodeView(
            id=node.id, concept_id=node.concept_id, label=node.label, node_type=node.node_type,
            definition=node.definition, key_point=node.key_point, misconception=node.misconception,
            origin=node.origin, confidence=node.confidence, position_x=node.position_x,
            position_y=node.position_y, evidence_count=node_evidence_count.get(node.id, 0),
            mastery=mastery_by_concept[node.concept_id].mastery if node.concept_id in mastery_by_concept else None,
            mastery_state=classify_state(
                mastery_by_concept[node.concept_id].mastery / 100.0,
                mastery_by_concept[node.concept_id].effective_evidence,
                mastery_by_concept[node.concept_id].uncertainty,
            ) if node.concept_id in mastery_by_concept else None,
        ) for node in nodes],
        edges=[GraphEdgeView(
            id=edge.id, from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
            relation=edge.relation, origin=edge.origin, confidence=edge.confidence,
            evidence_count=edge_evidence_count.get(edge.id, 0),
        ) for edge in edges],
        quality=_quality_view(quality),
    )


def _validate_and_store(db, revision: GraphRevision) -> GraphQualityReport:
    nodes, edges, _ = _revision_parts(db, revision.id)
    links = db.scalars(select(GraphEvidenceLink).where(
        GraphEvidenceLink.revision_id == revision.id,
        GraphEvidenceLink.active.is_(True),
    )).all()
    result = validate_graph(
        nodes, edges,
        evidenced_node_ids={link.node_id for link in links if link.node_id},
        evidenced_edge_ids={link.edge_id for link in links if link.edge_id},
    )
    quality = GraphQualityReport(
        id=str(uuid4()), revision_id=revision.id, hard_pass=result.hard_pass,
        quality_score=result.quality_score, metrics_json=result.metrics,
        issues_json=[issue.__dict__ for issue in result.issues], validator_version=VALIDATOR_VERSION,
    )
    revision.quality_score = result.quality_score
    revision.review_status = "passed" if result.hard_pass else "failed"
    db.add(quality)
    return quality


@router.get("/teacher/courses/{course_id}/graphs", response_model=list[GraphListItem])
def teacher_graphs(course_id: str, user: TeacherUser, db: DbSession):
    if CourseRepository(db).get_teacher_course(user.id, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")
    graphs = db.scalars(select(KnowledgeGraph).where(KnowledgeGraph.course_id == course_id).order_by(KnowledgeGraph.id)).all()
    items = []
    for graph in graphs:
        revision = db.get(GraphRevision, graph.working_revision_id) if graph.working_revision_id else None
        node_count = db.scalar(select(func.count()).select_from(GraphNode).where(GraphNode.revision_id == revision.id)) if revision else 0
        edge_count = db.scalar(select(func.count()).select_from(GraphEdge).where(GraphEdge.revision_id == revision.id)) if revision else 0
        items.append(GraphListItem(
            id=graph.id, course_id=graph.course_id, title=graph.title, status=graph.status,
            working_revision_id=graph.working_revision_id, published_revision_id=graph.published_revision_id,
            revision_no=revision.revision_no if revision else None, node_count=node_count or 0,
            edge_count=edge_count or 0, updated_at=graph.updated_at,
        ))
    return items


@router.post("/teacher/courses/{course_id}/graphs", response_model=GraphDetailView, status_code=status.HTTP_201_CREATED)
def create_graph(course_id: str, payload: GraphCreateRequest, user: TeacherUser, db: DbSession):
    if CourseRepository(db).get_teacher_course(user.id, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")
    title = payload.title.strip()
    if db.scalar(select(KnowledgeGraph).where(KnowledgeGraph.course_id == course_id, KnowledgeGraph.title == title)):
        raise HTTPException(status_code=409, detail="当前课程已存在同名图谱")
    graph = KnowledgeGraph(id=f"graph-{uuid4()}", course_id=course_id, title=title, owner_id=user.id)
    revision = GraphRevision(
        id=str(uuid4()), graph_id=graph.id, revision_no=1, mode="new", status="draft",
        review_status="pending", source_type="manual", source_summary=payload.source_summary.strip(),
        created_by=user.id,
    )
    db.add(graph)
    db.flush()
    db.add(revision)
    db.flush()
    graph.working_revision_id = revision.id
    _audit(db, actor_id=user.id, action="graph.create", graph=graph, object_id=revision.id)
    db.commit()
    return _detail(db, graph, revision)


@router.get("/teacher/graphs/{graph_id}", response_model=GraphDetailView)
def teacher_graph_detail(graph_id: str, user: TeacherUser, db: DbSession):
    graph = _teacher_graph(db, user, graph_id)
    revision = db.get(GraphRevision, graph.working_revision_id) if graph.working_revision_id else None
    if revision is None:
        raise HTTPException(status_code=404, detail="图谱修订不存在")
    return _detail(db, graph, revision)


@router.patch("/teacher/graphs/{graph_id}", response_model=GraphDetailView)
def rename_teacher_graph(
    graph_id: str, payload: GraphRenameRequest, user: TeacherUser, db: DbSession,
):
    graph = _teacher_graph(db, user, graph_id)
    revision = db.get(GraphRevision, graph.working_revision_id) if graph.working_revision_id else None
    if revision is None:
        raise HTTPException(status_code=409, detail="当前图谱没有可用修订")
    title = payload.title.strip()
    duplicate = db.scalar(select(KnowledgeGraph).where(
        KnowledgeGraph.course_id == graph.course_id,
        func.lower(KnowledgeGraph.title) == title.lower(),
        KnowledgeGraph.id != graph.id,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="当前课程已存在同名图谱")
    previous_title = graph.title
    graph.title = title
    graph.updated_at = datetime.now(timezone.utc)
    _audit(
        db, actor_id=user.id, action="graph.rename", graph=graph,
        metadata={"previous_title": previous_title, "title": title},
    )
    db.commit()
    return _detail(db, graph, revision)


@router.delete("/teacher/graphs/{graph_id}/draft", response_model=GraphDetailView)
def discard_teacher_graph_draft(
    graph_id: str, expected_revision_version: int, user: TeacherUser, db: DbSession,
):
    graph = _teacher_graph(db, user, graph_id)
    revision = db.get(GraphRevision, graph.working_revision_id) if graph.working_revision_id else None
    published = db.get(GraphRevision, graph.published_revision_id) if graph.published_revision_id else None
    if revision is None or revision.status != "draft":
        raise HTTPException(status_code=409, detail="当前图谱没有可放弃的草稿")
    if published is None or revision.id == published.id:
        raise HTTPException(status_code=409, detail="初始草稿不能单独放弃，请删除未发布图谱")
    if revision.version != expected_revision_version:
        raise HTTPException(status_code=409, detail={
            "code": "GRAPH_REVISION_CONFLICT",
            "message": "图谱已被其他操作更新，请刷新后再提交",
            "expected_version": expected_revision_version,
            "actual_version": revision.version,
        })
    discarded_revision_id = revision.id
    graph.working_revision_id = published.id
    graph.status = "published"
    graph.updated_at = datetime.now(timezone.utc)
    _audit(
        db, actor_id=user.id, action="graph.revision.discard", graph=graph,
        object_id=discarded_revision_id,
        metadata={"restored_revision_id": published.id},
    )
    db.flush()
    db.execute(delete(GraphRevision).where(GraphRevision.id == discarded_revision_id))
    db.commit()
    return _detail(db, graph, published)


@router.delete("/teacher/graphs/{graph_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_teacher_graph(
    graph_id: str, expected_revision_version: int, user: TeacherUser, db: DbSession,
):
    graph = _teacher_graph(db, user, graph_id)
    if graph.published_revision_id is not None:
        raise HTTPException(status_code=409, detail="已发布图谱不能直接删除，请保留其发布记录")
    revision = db.get(GraphRevision, graph.working_revision_id) if graph.working_revision_id else None
    if revision is None:
        raise HTTPException(status_code=409, detail="当前图谱没有可删除的草稿修订")
    if revision.version != expected_revision_version:
        raise HTTPException(status_code=409, detail={
            "code": "GRAPH_REVISION_CONFLICT",
            "message": "图谱已被其他操作更新，请刷新后再提交",
            "expected_version": expected_revision_version,
            "actual_version": revision.version,
        })
    _audit(
        db, actor_id=user.id, action="graph.delete", graph=graph,
        metadata={"revision_id": revision.id, "title": graph.title},
    )
    db.delete(graph)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/teacher/graphs/{graph_id}/evidence/{target_type}/{target_id}",
    response_model=GraphEvidenceBundleView,
)
def teacher_graph_evidence(
    graph_id: str,
    target_type: Literal["node", "edge"],
    target_id: str,
    user: TeacherUser,
    db: DbSession,
):
    graph = _teacher_graph(db, user, graph_id)
    revision = db.get(GraphRevision, graph.working_revision_id) if graph.working_revision_id else None
    if revision is None:
        raise HTTPException(status_code=404, detail="图谱修订不存在")
    target = db.get(GraphNode if target_type == "node" else GraphEdge, target_id)
    if target is None or target.revision_id != revision.id:
        raise HTTPException(status_code=404, detail="图谱对象不存在于当前修订")
    target_filter = (
        GraphEvidenceLink.node_id == target_id
        if target_type == "node"
        else GraphEvidenceLink.edge_id == target_id
    )
    evidence_links = list(db.scalars(select(GraphEvidenceLink).where(
        GraphEvidenceLink.revision_id == revision.id,
        target_filter,
        GraphEvidenceLink.active.is_(True),
    ).order_by(GraphEvidenceLink.created_at)).all())
    views: list[GraphEvidenceSourceView] = []
    for link in evidence_links:
        span = db.get(EvidenceSpan, link.evidence_span_id) if link.evidence_span_id else None
        source_name = None
        if span:
            chunk = db.get(DocumentChunk, span.chunk_id)
            document = db.get(ParsedDocument, chunk.document_id) if chunk else None
            asset = db.get(SourceAsset, document.asset_id) if document else None
            source_name = asset.original_name if asset else None
        views.append(GraphEvidenceSourceView(
            id=link.id, target_type=target_type, target_id=target_id,
            source_kind=link.source_kind, evidence_span_id=link.evidence_span_id,
            source_name=source_name, quote=span.quote if span else None,
            locator=span.locator_json if span else None,
            assertion_note=link.assertion_note, confidence=link.confidence,
            source_model_run_id=link.source_model_run_id,
            created_at=link.created_at,
        ))
    if not views and target.origin == "curated_seed":
        views.append(GraphEvidenceSourceView(
            id=f"curated-seed:{target_id}", target_type=target_type, target_id=target_id,
            source_kind="curated_seed", evidence_span_id=None, source_name=None,
            quote=None, locator=None,
            assertion_note="课程初始图谱内容，由教师发布修订确认",
            confidence=1.0, source_model_run_id=None,
            created_at=revision.created_at,
        ))
    _audit(
        db, actor_id=user.id, action="graph.evidence.read", graph=graph,
        object_id=target_id,
        metadata={"revision_id": revision.id, "target_type": target_type, "link_count": len(views)},
    )
    db.commit()
    return GraphEvidenceBundleView(
        graph_id=graph.id, revision_id=revision.id, revision_version=revision.version,
        target_type=target_type, target_id=target_id, links=views,
    )


@router.post("/teacher/graphs/{graph_id}/revisions", response_model=GraphDetailView, status_code=status.HTTP_201_CREATED)
def create_update_revision(graph_id: str, user: TeacherUser, db: DbSession):
    graph = _teacher_graph(db, user, graph_id)
    current = db.get(GraphRevision, graph.working_revision_id) if graph.working_revision_id else None
    if current and current.status == "draft":
        raise HTTPException(status_code=409, detail="已有未发布修订，请先完成或放弃当前编辑")
    source = db.get(GraphRevision, graph.published_revision_id) if graph.published_revision_id else current
    if source is None:
        raise HTTPException(status_code=409, detail="当前图谱没有可作为更新基础的修订")
    next_no = (db.scalar(select(func.max(GraphRevision.revision_no)).where(GraphRevision.graph_id == graph.id)) or 0) + 1
    revision = GraphRevision(
        id=str(uuid4()), graph_id=graph.id, parent_revision_id=source.id, revision_no=next_no,
        mode="update", status="draft", review_status="pending", source_type="manual",
        source_summary="基于已发布修订创建的教师更新工作区", created_by=user.id,
    )
    db.add(revision)
    db.flush()
    source_nodes = list(db.scalars(select(GraphNode).where(GraphNode.revision_id == source.id)).all())
    node_map = {}
    for node in source_nodes:
        clone = GraphNode(
            id=str(uuid4()), revision_id=revision.id, concept_id=node.concept_id, label=node.label,
            node_type=node.node_type, definition=node.definition, key_point=node.key_point,
            misconception=node.misconception, origin=node.origin, confidence=node.confidence,
            position_x=node.position_x, position_y=node.position_y,
        )
        node_map[node.id] = clone.id
        db.add(clone)
    db.flush()
    edge_map = {}
    for edge in db.scalars(select(GraphEdge).where(GraphEdge.revision_id == source.id)).all():
        clone_id = str(uuid4())
        edge_map[edge.id] = clone_id
        db.add(GraphEdge(
            id=clone_id, revision_id=revision.id, from_node_id=node_map[edge.from_node_id],
            to_node_id=node_map[edge.to_node_id], relation=edge.relation,
            origin=edge.origin, confidence=edge.confidence,
        ))
    db.flush()
    for link in db.scalars(select(GraphEvidenceLink).where(
        GraphEvidenceLink.revision_id == source.id,
        GraphEvidenceLink.active.is_(True),
    )).all():
        mapped_node = node_map.get(link.node_id) if link.node_id else None
        mapped_edge = edge_map.get(link.edge_id) if link.edge_id else None
        if not mapped_node and not mapped_edge:
            continue
        db.add(GraphEvidenceLink(
            id=str(uuid4()), revision_id=revision.id,
            node_id=mapped_node, edge_id=mapped_edge,
            evidence_span_id=link.evidence_span_id, source_kind=link.source_kind,
            assertion_note=link.assertion_note, confidence=link.confidence,
            source_model_run_id=link.source_model_run_id,
            created_by=user.id, active=True,
        ))
    graph.working_revision_id = revision.id
    graph.updated_at = datetime.now(timezone.utc)
    _audit(db, actor_id=user.id, action="graph.revision.create", graph=graph, object_id=revision.id, metadata={"parent_revision_id": source.id})
    db.commit()
    return _detail(db, graph, revision)


@router.post("/teacher/graphs/{graph_id}/nodes", response_model=GraphDetailView)
def add_graph_node(graph_id: str, payload: GraphNodeCreate, user: TeacherUser, db: DbSession):
    graph, revision = _editable_revision(db, user, graph_id)
    label = payload.label.strip()
    normalized_label = normalize_concept_name(label)
    if not normalized_label:
        raise HTTPException(status_code=422, detail="知识点名称必须包含文字或数字")
    revision_nodes = db.scalars(select(GraphNode).where(
        GraphNode.revision_id == revision.id,
    )).all()
    if any(normalize_concept_name(item.label) == normalized_label for item in revision_nodes):
        raise HTTPException(status_code=409, detail="当前修订已存在同名知识点")
    concept = db.scalar(select(Concept).where(
        Concept.course_id == graph.course_id,
        Concept.normalized_name == normalized_label,
    ))
    if concept is None:
        sort_order = (db.scalar(select(func.max(Concept.sort_order)).where(Concept.course_id == graph.course_id)) or 0) + 1
        concept = Concept(id=f"{graph.course_id}:concept:graph:{uuid4().hex[:12]}", course_id=graph.course_id, name=label, sort_order=sort_order)
        db.add(concept)
        db.flush()
    if db.scalar(select(GraphNode).where(GraphNode.revision_id == revision.id, GraphNode.concept_id == concept.id)):
        raise HTTPException(status_code=409, detail="该规范知识点已在当前修订中")
    _claim_or_conflict(db, revision, payload.expected_revision_version)
    node = GraphNode(
        id=str(uuid4()), revision_id=revision.id, concept_id=concept.id, label=label,
        node_type=payload.node_type, definition=payload.definition.strip(),
        key_point=payload.key_point.strip(), misconception=payload.misconception.strip(),
        origin="teacher", confidence=1.0, position_x=payload.position_x, position_y=payload.position_y,
    )
    db.add(node)
    db.flush()
    _replace_teacher_evidence(
        db, revision=revision, actor_id=user.id, node_id=node.id,
        note=payload.teacher_evidence_note,
    )
    _audit(
        db, actor_id=user.id, action="graph.node.create", graph=graph,
        object_id=node.id, metadata={"revision_id": revision.id},
    )
    db.commit()
    return _detail(db, graph, revision)


@router.patch("/teacher/graphs/{graph_id}/nodes/{node_id}", response_model=GraphDetailView)
def update_graph_node(graph_id: str, node_id: str, payload: GraphNodeUpdate, user: TeacherUser, db: DbSession):
    graph, revision = _editable_revision(db, user, graph_id)
    node = db.get(GraphNode, node_id)
    if node is None or node.revision_id != revision.id:
        raise HTTPException(status_code=404, detail="知识点不存在于当前修订")
    changes = payload.model_dump(exclude_unset=True)
    expected_version = changes.pop("expected_revision_version")
    teacher_note = changes.pop("teacher_evidence_note", None)
    if "label" in changes:
        changes["label"] = changes["label"].strip()
        duplicate = db.scalar(select(GraphNode).where(
            GraphNode.revision_id == revision.id,
            func.lower(GraphNode.label) == changes["label"].lower(),
            GraphNode.id != node.id,
        ))
        if duplicate:
            raise HTTPException(status_code=409, detail="当前修订已存在同名知识点")
    _claim_or_conflict(db, revision, expected_version)
    for field, value in changes.items():
        setattr(node, field, value.strip() if isinstance(value, str) else value)
    _replace_teacher_evidence(
        db, revision=revision, actor_id=user.id, node_id=node.id, note=teacher_note,
    )
    _audit(
        db, actor_id=user.id, action="graph.node.update", graph=graph,
        object_id=node.id,
        metadata={"revision_id": revision.id, "changed_fields": sorted(changes)},
    )
    db.commit()
    return _detail(db, graph, revision)


@router.delete("/teacher/graphs/{graph_id}/nodes/{node_id}", response_model=GraphDetailView)
def delete_graph_node(
    graph_id: str, node_id: str, expected_revision_version: int,
    user: TeacherUser, db: DbSession,
):
    graph, revision = _editable_revision(db, user, graph_id)
    node = db.get(GraphNode, node_id)
    if node is None or node.revision_id != revision.id:
        raise HTTPException(status_code=404, detail="知识点不存在于当前修订")
    _claim_or_conflict(db, revision, expected_revision_version)
    db.execute(delete(GraphEdge).where((GraphEdge.from_node_id == node.id) | (GraphEdge.to_node_id == node.id)))
    db.delete(node)
    _audit(
        db, actor_id=user.id, action="graph.node.delete", graph=graph,
        object_id=node.id, metadata={"revision_id": revision.id, "label": node.label},
    )
    db.commit()
    return _detail(db, graph, revision)


@router.post("/teacher/graphs/{graph_id}/edges", response_model=GraphDetailView)
def add_graph_edge(graph_id: str, payload: GraphEdgeCreate, user: TeacherUser, db: DbSession):
    graph, revision = _editable_revision(db, user, graph_id)
    endpoints = list(db.scalars(select(GraphNode).where(
        GraphNode.revision_id == revision.id,
        GraphNode.id.in_([payload.from_node_id, payload.to_node_id]),
    )).all())
    if len({node.id for node in endpoints}) != 2:
        raise HTTPException(status_code=422, detail="关系端点必须属于当前修订且不能相同")
    duplicate = db.scalar(select(GraphEdge).where(
        GraphEdge.revision_id == revision.id, GraphEdge.from_node_id == payload.from_node_id,
        GraphEdge.to_node_id == payload.to_node_id, GraphEdge.relation == payload.relation,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="当前修订已存在相同关系")
    _claim_or_conflict(db, revision, payload.expected_revision_version)
    edge = GraphEdge(
        id=str(uuid4()), revision_id=revision.id, from_node_id=payload.from_node_id,
        to_node_id=payload.to_node_id, relation=payload.relation, origin="teacher", confidence=1.0,
    )
    db.add(edge)
    db.flush()
    _replace_teacher_evidence(
        db, revision=revision, actor_id=user.id, edge_id=edge.id,
        note=payload.teacher_evidence_note,
    )
    _audit(
        db, actor_id=user.id, action="graph.edge.create", graph=graph,
        object_id=edge.id, metadata={"revision_id": revision.id},
    )
    db.commit()
    return _detail(db, graph, revision)


@router.patch("/teacher/graphs/{graph_id}/edges/{edge_id}", response_model=GraphDetailView)
def update_graph_edge(graph_id: str, edge_id: str, payload: GraphEdgeUpdate, user: TeacherUser, db: DbSession):
    graph, revision = _editable_revision(db, user, graph_id)
    edge = db.get(GraphEdge, edge_id)
    if edge is None or edge.revision_id != revision.id:
        raise HTTPException(status_code=404, detail="关系不存在于当前修订")
    changes = payload.model_dump(exclude_unset=True)
    expected_version = changes.pop("expected_revision_version")
    teacher_note = changes.pop("teacher_evidence_note", None)
    candidate_from = changes.get("from_node_id", edge.from_node_id)
    candidate_to = changes.get("to_node_id", edge.to_node_id)
    endpoints = list(db.scalars(select(GraphNode).where(
        GraphNode.revision_id == revision.id,
        GraphNode.id.in_([candidate_from, candidate_to]),
    )).all())
    if len({node.id for node in endpoints}) != 2:
        raise HTTPException(status_code=422, detail="关系端点必须属于当前修订且不能相同")
    duplicate = db.scalar(select(GraphEdge).where(
        GraphEdge.revision_id == revision.id,
        GraphEdge.from_node_id == candidate_from,
        GraphEdge.to_node_id == candidate_to,
        GraphEdge.relation == changes.get("relation", edge.relation),
        GraphEdge.id != edge.id,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="修改后将产生重复关系")
    _claim_or_conflict(db, revision, expected_version)
    for field, value in changes.items():
        setattr(edge, field, value)
    _replace_teacher_evidence(
        db, revision=revision, actor_id=user.id, edge_id=edge.id, note=teacher_note,
    )
    _audit(
        db, actor_id=user.id, action="graph.edge.update", graph=graph,
        object_id=edge.id,
        metadata={"revision_id": revision.id, "changed_fields": sorted(changes)},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="修改后将产生重复关系")
    return _detail(db, graph, revision)


@router.delete("/teacher/graphs/{graph_id}/edges/{edge_id}", response_model=GraphDetailView)
def delete_graph_edge(
    graph_id: str, edge_id: str, expected_revision_version: int,
    user: TeacherUser, db: DbSession,
):
    graph, revision = _editable_revision(db, user, graph_id)
    edge = db.get(GraphEdge, edge_id)
    if edge is None or edge.revision_id != revision.id:
        raise HTTPException(status_code=404, detail="关系不存在于当前修订")
    _claim_or_conflict(db, revision, expected_revision_version)
    db.delete(edge)
    _audit(
        db, actor_id=user.id, action="graph.edge.delete", graph=graph,
        object_id=edge.id, metadata={"revision_id": revision.id},
    )
    db.commit()
    return _detail(db, graph, revision)


@router.post("/teacher/graphs/{graph_id}/alignment-runs/{run_id}:apply", response_model=GraphDetailView)
def apply_alignment_run(
    graph_id: str, run_id: str, payload: GraphMutationGuard,
    user: TeacherUser, db: DbSession,
):
    graph, revision = _editable_revision(db, user, graph_id)
    run = db.get(AlignmentRun, run_id)
    if run is None or run.course_id != graph.course_id:
        raise HTTPException(status_code=404, detail="知识点对齐任务不存在于当前课程")
    if run.status != "completed":
        raise HTTPException(status_code=409, detail="请先完成全部歧义复核，再写入图谱")
    expected_purpose = "graph_build" if revision.mode == "new" else "graph_update"
    if run.purpose != expected_purpose:
        raise HTTPException(status_code=422, detail="对齐任务用途与当前图谱修订模式不一致")
    mentions = list(db.scalars(
        select(AlignmentMention).where(
            AlignmentMention.run_id == run.id,
            AlignmentMention.status == "matched",
        ).order_by(AlignmentMention.ordinal)
    ).all())
    existing_nodes = {
        node.concept_id: node for node in db.scalars(
            select(GraphNode).where(GraphNode.revision_id == revision.id)
        ).all()
    }
    _claim_or_conflict(db, revision, payload.expected_revision_version)
    added_node_ids: list[str] = []
    evidenced_node_ids: list[str] = []
    for mention in mentions:
        review = db.scalar(select(AlignmentReview).where(AlignmentReview.mention_id == mention.id))
        selected_concept_id = (
            review.selected_concept_id
            if review and review.decision in {"matched", "created"}
            else None
        )
        candidate = None
        if selected_concept_id:
            candidate = db.scalar(select(AlignmentCandidate).where(
                AlignmentCandidate.mention_id == mention.id,
                AlignmentCandidate.concept_id == selected_concept_id,
            ))
        else:
            candidate = db.scalar(select(AlignmentCandidate).where(
                AlignmentCandidate.mention_id == mention.id,
                AlignmentCandidate.recommended.is_(True),
            ))
            selected_concept_id = candidate.concept_id if candidate else None
        if not selected_concept_id:
            continue
        concept = db.get(Concept, selected_concept_id)
        if concept is None or concept.course_id != graph.course_id:
            raise HTTPException(status_code=422, detail="对齐结果包含跨课程知识点")
        node = existing_nodes.get(concept.id)
        if node is None:
            node_count = len(existing_nodes)
            node = GraphNode(
                id=str(uuid4()), revision_id=revision.id, concept_id=concept.id, label=concept.name,
                node_type="core", definition="", key_point="", misconception="",
                origin="alignment_review" if review and review.decision in {"matched", "created"} else "alignment_auto",
                confidence=candidate.final_score if candidate else 1.0,
                position_x=200 + (node_count % 4) * 190,
                position_y=160 + (node_count // 4) * 125,
            )
            db.add(node)
            db.flush()
            existing_nodes[concept.id] = node
            added_node_ids.append(node.id)
        if _ensure_alignment_evidence(
            db, revision=revision, node=node, mention=mention, review=review,
            candidate=candidate, actor_id=user.id,
        ):
            evidenced_node_ids.append(node.id)
        if run.source_asset_id and db.scalar(select(Derivation.id).where(
            Derivation.source_asset_id == run.source_asset_id,
            Derivation.derived_type == "graph_node",
            Derivation.derived_id == node.id,
        )) is None:
            db.add(Derivation(
                id=str(uuid4()), source_asset_id=run.source_asset_id,
                derived_type="graph_node", derived_id=node.id,
                relation="aligned_into", active=True,
            ))
    if added_node_ids or evidenced_node_ids:
        revision.source_type = "material_alignment"
        revision.source_summary = (
            f"知识点对齐任务 {run.id} 已写入 {len(added_node_ids)} 个知识点，"
            f"合并 {len(evidenced_node_ids)} 条来源"
        )
    _audit(
        db, actor_id=user.id, action="graph.alignment.apply", graph=graph,
        object_id=revision.id,
        metadata={
            "alignment_run_id": run.id,
            "added_node_ids": added_node_ids,
            "evidenced_node_ids": evidenced_node_ids,
        },
    )
    db.commit()
    return _detail(db, graph, revision)


@router.post("/teacher/graphs/{graph_id}:validate", response_model=GraphDetailView)
def validate_graph_revision(
    graph_id: str, payload: GraphMutationGuard, user: TeacherUser, db: DbSession,
):
    graph, revision = _editable_revision(db, user, graph_id)
    quality = _validate_and_store(db, revision)
    _claim_or_conflict(
        db, revision, payload.expected_revision_version,
        review_status="passed" if quality.hard_pass else "failed",
        clear_quality=False,
        extra_values={"quality_score": quality.quality_score},
        increment_version=False,
        supersede_semantic=False,
    )
    _audit(db, actor_id=user.id, action="graph.validate", graph=graph, object_id=revision.id, metadata={"hard_pass": quality.hard_pass})
    db.commit()
    return _detail(db, graph, revision)


@router.post("/teacher/graphs/{graph_id}:publish", response_model=GraphDetailView)
def publish_graph_revision(
    graph_id: str, payload: GraphMutationGuard, user: TeacherUser, db: DbSession,
):
    graph, revision = _editable_revision(db, user, graph_id)
    quality = _validate_and_store(db, revision)
    next_review_status = "passed" if quality.hard_pass else "failed"
    published_at = datetime.now(timezone.utc)
    extra_values = {"quality_score": quality.quality_score}
    if quality.hard_pass:
        next_review_status = "teacher_validated"
        extra_values.update({"status": "published", "published_at": published_at})
    _claim_or_conflict(
        db, revision, payload.expected_revision_version,
        review_status=next_review_status, clear_quality=False,
        extra_values=extra_values, increment_version=False, supersede_semantic=False,
    )
    if not quality.hard_pass:
        db.commit()
        raise HTTPException(status_code=422, detail={"message": "图谱未通过发布硬门", "issues": quality.issues_json})
    graph.published_revision_id = revision.id
    graph.working_revision_id = revision.id
    graph.status = "published"
    graph.updated_at = published_at
    _audit(db, actor_id=user.id, action="graph.publish", graph=graph, object_id=revision.id, metadata={"quality_score": quality.quality_score})
    db.commit()
    return _detail(db, graph, revision)


@router.get("/student/courses/{course_id}/graph-resources", response_model=list[GraphListItem])
def student_graphs(course_id: str, user: StudentUser, db: DbSession):
    if CourseRepository(db).get_student_course(user.id, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")
    graphs = db.scalars(select(KnowledgeGraph).where(
        KnowledgeGraph.course_id == course_id,
        KnowledgeGraph.status == "published",
        KnowledgeGraph.published_revision_id.is_not(None),
    ).order_by(KnowledgeGraph.id)).all()
    items = []
    for graph in graphs:
        revision = db.get(GraphRevision, graph.published_revision_id)
        items.append(GraphListItem(
            id=graph.id, course_id=graph.course_id, title=graph.title, status=graph.status,
            working_revision_id=None, published_revision_id=graph.published_revision_id,
            revision_no=revision.revision_no, node_count=db.scalar(select(func.count()).select_from(GraphNode).where(GraphNode.revision_id == revision.id)) or 0,
            edge_count=db.scalar(select(func.count()).select_from(GraphEdge).where(GraphEdge.revision_id == revision.id)) or 0,
            updated_at=graph.updated_at,
        ))
    return items


@router.get("/student/courses/{course_id}/graph-resources/{graph_id}", response_model=GraphDetailView)
def student_graph_detail(course_id: str, graph_id: str, user: StudentUser, db: DbSession):
    if CourseRepository(db).get_student_course(user.id, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")
    graph = db.get(KnowledgeGraph, graph_id)
    if graph is None or graph.course_id != course_id or graph.status != "published" or not graph.published_revision_id:
        raise HTTPException(status_code=404, detail="图谱资源不存在或尚未发布")
    revision = db.get(GraphRevision, graph.published_revision_id)
    _audit(db, actor_id=user.id, action="graph.read", graph=graph, object_id=revision.id)
    db.commit()
    return _detail(db, graph, revision, student_id=user.id)


@router.get("/student/courses/{course_id}/concepts/{concept_id}/card", response_model=GraphNodeView)
def student_concept_card(course_id: str, concept_id: str, user: StudentUser, db: DbSession):
    if CourseRepository(db).get_student_course(user.id, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")
    graph = db.scalar(select(KnowledgeGraph).where(
        KnowledgeGraph.course_id == course_id,
        KnowledgeGraph.status == "published",
        KnowledgeGraph.published_revision_id.is_not(None),
    ).order_by(KnowledgeGraph.updated_at.desc()))
    if graph is None:
        raise HTTPException(status_code=404, detail="当前课程没有已发布图谱")
    node = db.scalar(select(GraphNode).where(
        GraphNode.revision_id == graph.published_revision_id,
        GraphNode.concept_id == concept_id,
    ))
    if node is None:
        raise HTTPException(status_code=404, detail="知识卡片不存在")
    state_row = db.scalar(select(KnowledgeState).where(
        KnowledgeState.student_id == user.id,
        KnowledgeState.course_id == course_id,
        KnowledgeState.concept_id == concept_id,
    ))
    return GraphNodeView(
        id=node.id, concept_id=node.concept_id, label=node.label, node_type=node.node_type,
        definition=node.definition, key_point=node.key_point, misconception=node.misconception,
        origin=node.origin, confidence=node.confidence, position_x=node.position_x,
        position_y=node.position_y, mastery=state_row.mastery if state_row else None,
        mastery_state=state_row.status if state_row else None,
    )
