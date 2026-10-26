from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import delete, func, select, update

from .dependencies import DbSession, StudentUser, TeacherUser
from .domains.knowledge_graph.open_concepts import InvalidConceptName, resolve_open_concept
from .domains.material_alignment.alignment import (
    ALIGNER_VERSION,
    DEFAULT_THRESHOLDS,
    ONTOLOGY_VERSION,
    AlignerConcept,
    extract_document_mentions,
    normalize_concept_text,
    rank_concepts,
    split_manual_mentions,
)
from .domains.material_alignment.parsers import (
    PARSER_VERSION,
    DocumentParseError,
    parse_document,
)
from .domains.material_alignment.security import (
    UploadPolicyError,
    inspect_upload,
    resolve_storage_path,
    validate_upload_metadata,
)
from .models import (
    AlignmentCandidate,
    AlignmentMention,
    AlignmentReview,
    AlignmentRun,
    AuditEvent,
    Concept,
    DeletionJob,
    Derivation,
    DocumentChunk,
    EvidenceSpan,
    GraphEdge,
    GraphExtractionArtifact,
    GraphNode,
    GraphRevision,
    KnowledgeGraph,
    CourseEnrollment,
    ParsedDocument,
    SourceAsset,
)
from .repositories import CourseRepository
from .schemas import (
    AlignmentCandidateView,
    AlignmentMentionView,
    AlignmentReviewDecision,
    AlignmentReviewView,
    AlignmentRunCreate,
    AlignmentRunView,
    AssetCompleteResponse,
    AssetDeletionView,
    AssetPrepareRequest,
    AssetPrepareResponse,
    AssetView,
    EvidenceSpanView,
    ParsedDocumentView,
)


router = APIRouter(prefix="/api/v1")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_teacher_course(db, user, course_id: str) -> None:
    if CourseRepository(db).get_teacher_course(user.id, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")


def _audit(
    db,
    *,
    actor_id: str,
    action: str,
    course_id: str,
    object_type: str,
    object_id: str,
    outcome: str = "success",
    metadata: dict | None = None,
) -> None:
    db.add(AuditEvent(
        id=str(uuid4()), actor_id=actor_id, action=action, object_type=object_type,
        object_id=object_id, course_id=course_id, outcome=outcome,
        metadata_json=metadata or {},
    ))


def _asset_for_teacher(db, user, course_id: str, asset_id: str) -> SourceAsset:
    _ensure_teacher_course(db, user, course_id)
    asset = db.get(SourceAsset, asset_id)
    if asset is None or asset.course_id != course_id or asset.owner_id != user.id:
        raise HTTPException(status_code=404, detail="材料不存在或无权访问")
    return asset


def _ensure_student_course(db, user, course_id: str) -> None:
    enrollment = db.scalar(select(CourseEnrollment.id).where(
        CourseEnrollment.student_id == user.id,
        CourseEnrollment.course_id == course_id,
    ))
    if enrollment is None:
        raise HTTPException(status_code=404, detail="课程不存在或无权访问")


def _asset_for_student(db, user, course_id: str, asset_id: str) -> SourceAsset:
    _ensure_student_course(db, user, course_id)
    asset = db.get(SourceAsset, asset_id)
    if (
        asset is None
        or asset.course_id != course_id
        or asset.owner_id != user.id
        or asset.purpose != "tutor_attachment"
    ):
        raise HTTPException(status_code=404, detail="辅导附件不存在或无权访问")
    return asset


def _asset_view(asset: SourceAsset) -> AssetView:
    return AssetView.model_validate(asset)


def _document_view(db, document: ParsedDocument) -> ParsedDocumentView:
    chunk_count = db.scalar(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document.id)
    ) or 0
    return ParsedDocumentView(
        id=document.id,
        asset_id=document.asset_id,
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        status=document.status,
        title=document.title,
        segment_count=document.segment_count,
        page_count=document.page_count,
        text_length=document.text_length,
        chunk_count=chunk_count,
        warnings=document.warnings_json,
        created_at=document.created_at,
    )


def _stored_path(settings, asset: SourceAsset) -> Path | None:
    if not asset.storage_key:
        return None
    root = settings.asset_root.resolve()
    path = (root / asset.storage_key).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=500, detail="资产存储路径异常")
    return path


def _reject_asset(db, asset: SourceAsset, code: str, reason: str, path: Path | None = None) -> None:
    asset.status = "rejected"
    asset.security_status = "rejected"
    asset.rejection_code = code
    asset.rejection_reason = reason
    if path is not None and path.exists():
        path.unlink()
    asset.storage_key = None
    db.commit()


@router.post(
    "/teacher/courses/{course_id}/assets:prepare-upload",
    response_model=AssetPrepareResponse,
    status_code=status.HTTP_201_CREATED,
)
def prepare_asset_upload(
    course_id: str,
    payload: AssetPrepareRequest,
    request: Request,
    user: TeacherUser,
    db: DbSession,
):
    _ensure_teacher_course(db, user, course_id)
    settings = request.app.state.settings
    try:
        extension = validate_upload_metadata(
            payload.filename,
            payload.declared_mime,
            payload.byte_size,
            settings.asset_max_bytes,
            payload.expected_sha256,
        )
    except UploadPolicyError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    asset = SourceAsset(
        id=str(uuid4()), course_id=course_id, owner_id=user.id, purpose=payload.purpose,
        original_name=payload.filename, extension=extension,
        declared_mime=payload.declared_mime.split(";", 1)[0].strip().lower(),
        expected_size=payload.byte_size,
        expected_sha256=payload.expected_sha256.lower() if payload.expected_sha256 else None,
        status="prepared", security_status="pending",
    )
    db.add(asset)
    _audit(
        db, actor_id=user.id, action="asset.prepare", course_id=course_id,
        object_type="source_asset", object_id=asset.id,
        metadata={"purpose": payload.purpose, "byte_size": payload.byte_size},
    )
    db.commit()
    return AssetPrepareResponse(
        asset=_asset_view(asset),
        upload_url=f"/api/v1/teacher/courses/{course_id}/assets/{asset.id}/content",
        max_bytes=settings.asset_max_bytes,
    )


@router.put("/teacher/courses/{course_id}/assets/{asset_id}/content", response_model=AssetView)
async def upload_asset_content(
    course_id: str,
    asset_id: str,
    request: Request,
    user: TeacherUser,
    db: DbSession,
):
    asset = _asset_for_teacher(db, user, course_id, asset_id)
    if asset.status != "prepared":
        raise HTTPException(status_code=409, detail="当前材料不处于待上传状态")
    settings = request.app.state.settings
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) != asset.expected_size:
        raise HTTPException(status_code=422, detail={"code": "size_mismatch", "message": "请求大小与预申请不一致"})
    quarantine = resolve_storage_path(settings.asset_root, "quarantine", asset.id)
    written = 0
    try:
        with quarantine.open("wb") as stream:
            async for chunk in request.stream():
                written += len(chunk)
                if written > asset.expected_size or written > settings.asset_max_bytes:
                    raise UploadPolicyError("file_too_large", "上传数据超过预申请大小或系统上限")
                stream.write(chunk)
        if written != asset.expected_size:
            raise UploadPolicyError("size_mismatch", "实际上传大小与预申请大小不一致")
    except UploadPolicyError as exc:
        _reject_asset(db, asset, exc.code, exc.message, quarantine)
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    asset.byte_size = written
    asset.storage_key = quarantine.relative_to(settings.asset_root.resolve()).as_posix()
    asset.status = "uploaded"
    asset.uploaded_at = _now()
    _audit(
        db, actor_id=user.id, action="asset.upload", course_id=course_id,
        object_type="source_asset", object_id=asset.id,
        metadata={"byte_size": written},
    )
    db.commit()
    return _asset_view(asset)


@router.post(
    "/teacher/courses/{course_id}/assets/{asset_id}:complete",
    response_model=AssetCompleteResponse,
)
def complete_asset_upload(
    course_id: str,
    asset_id: str,
    request: Request,
    user: TeacherUser,
    db: DbSession,
):
    asset = _asset_for_teacher(db, user, course_id, asset_id)
    existing = db.scalar(select(ParsedDocument).where(ParsedDocument.asset_id == asset.id))
    if asset.status == "parsed" and existing is not None:
        return AssetCompleteResponse(asset=_asset_view(asset), document=_document_view(db, existing))
    if asset.status != "uploaded":
        raise HTTPException(status_code=409, detail="请先完成文件内容上传")
    settings = request.app.state.settings
    quarantine = _stored_path(settings, asset)
    if quarantine is None or not quarantine.exists():
        raise HTTPException(status_code=409, detail="隔离区文件不存在，请重新上传")
    try:
        inspection = inspect_upload(
            quarantine,
            filename=asset.original_name,
            declared_mime=asset.declared_mime,
            expected_size=asset.expected_size,
            max_bytes=settings.asset_max_bytes,
            expected_sha256=asset.expected_sha256,
        )
    except UploadPolicyError as exc:
        _reject_asset(db, asset, exc.code, exc.message, quarantine)
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc

    accepted = resolve_storage_path(settings.asset_root, "accepted", asset.id)
    quarantine.replace(accepted)
    asset.storage_key = accepted.relative_to(settings.asset_root.resolve()).as_posix()
    asset.detected_mime = inspection.detected_mime
    asset.byte_size = inspection.byte_size
    asset.sha256 = inspection.sha256
    asset.security_status = "accepted"
    asset.accepted_at = _now()
    try:
        parsed = parse_document(accepted, asset.extension, asset.original_name)
    except DocumentParseError as exc:
        asset.status = "rejected"
        asset.rejection_code = exc.code
        asset.rejection_reason = exc.message
        accepted.unlink(missing_ok=True)
        asset.storage_key = None
        db.commit()
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc

    document = ParsedDocument(
        id=str(uuid4()), asset_id=asset.id, parser_name=parsed.parser_name,
        parser_version=PARSER_VERSION, status="parsed", title=parsed.title,
        segment_count=len(parsed.segments), page_count=parsed.page_count,
        text_length=sum(len(segment.text) for segment in parsed.segments),
        warnings_json=[*inspection.warnings, *parsed.warnings],
    )
    db.add(document)
    db.flush()
    for chunk in parsed.chunks:
        db.add(DocumentChunk(
            id=str(uuid4()), document_id=document.id, sequence_no=chunk.sequence_no,
            locator_json=chunk.locator, section_title=chunk.section_title, text=chunk.text,
            char_start=chunk.char_start, char_end=chunk.char_end,
            token_estimate=chunk.token_estimate, checksum=chunk.checksum,
        ))
    db.add(Derivation(
        id=str(uuid4()), source_asset_id=asset.id, derived_type="parsed_document",
        derived_id=document.id, relation="parsed_from", active=True,
    ))
    asset.status = "parsed"
    _audit(
        db, actor_id=user.id, action="asset.parse", course_id=course_id,
        object_type="source_asset", object_id=asset.id,
        metadata={
            "parser_version": PARSER_VERSION,
            "chunk_count": len(parsed.chunks),
            "warning_count": len(document.warnings_json),
        },
    )
    db.commit()
    return AssetCompleteResponse(asset=_asset_view(asset), document=_document_view(db, document))


@router.post(
    "/student/courses/{course_id}/tutor-attachments:prepare-upload",
    response_model=AssetPrepareResponse,
    status_code=status.HTTP_201_CREATED,
)
def prepare_tutor_attachment(
    course_id: str,
    payload: AssetPrepareRequest,
    request: Request,
    user: StudentUser,
    db: DbSession,
):
    _ensure_student_course(db, user, course_id)
    if payload.purpose != "tutor_attachment":
        raise HTTPException(status_code=422, detail="学生上传端点仅接受辅导附件")
    settings = request.app.state.settings
    try:
        extension = validate_upload_metadata(
            payload.filename,
            payload.declared_mime,
            payload.byte_size,
            settings.asset_max_bytes,
            payload.expected_sha256,
        )
    except UploadPolicyError as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": exc.message}
        ) from exc
    asset = SourceAsset(
        id=str(uuid4()), course_id=course_id, owner_id=user.id,
        purpose="tutor_attachment", original_name=payload.filename,
        extension=extension,
        declared_mime=payload.declared_mime.split(";", 1)[0].strip().lower(),
        expected_size=payload.byte_size,
        expected_sha256=(payload.expected_sha256.lower() if payload.expected_sha256 else None),
        status="prepared", security_status="pending",
    )
    db.add(asset)
    _audit(
        db, actor_id=user.id, action="tutor_attachment.prepare", course_id=course_id,
        object_type="source_asset", object_id=asset.id,
        metadata={"purpose": "tutor_attachment", "byte_size": payload.byte_size},
    )
    db.commit()
    return AssetPrepareResponse(
        asset=_asset_view(asset),
        upload_url=f"/api/v1/student/courses/{course_id}/tutor-attachments/{asset.id}/content",
        max_bytes=settings.asset_max_bytes,
    )


@router.put(
    "/student/courses/{course_id}/tutor-attachments/{asset_id}/content",
    response_model=AssetView,
)
async def upload_tutor_attachment(
    course_id: str,
    asset_id: str,
    request: Request,
    user: StudentUser,
    db: DbSession,
):
    asset = _asset_for_student(db, user, course_id, asset_id)
    if asset.status != "prepared":
        raise HTTPException(status_code=409, detail="当前辅导附件不处于待上传状态")
    settings = request.app.state.settings
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) != asset.expected_size:
        raise HTTPException(
            status_code=422,
            detail={"code": "size_mismatch", "message": "请求大小与预申请不一致"},
        )
    quarantine = resolve_storage_path(settings.asset_root, "quarantine", asset.id)
    written = 0
    try:
        with quarantine.open("wb") as stream:
            async for chunk in request.stream():
                written += len(chunk)
                if written > asset.expected_size or written > settings.asset_max_bytes:
                    raise UploadPolicyError(
                        "file_too_large", "上传数据超过预申请大小或系统上限"
                    )
                stream.write(chunk)
        if written != asset.expected_size:
            raise UploadPolicyError("size_mismatch", "实际上传大小与预申请大小不一致")
    except UploadPolicyError as exc:
        _reject_asset(db, asset, exc.code, exc.message, quarantine)
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": exc.message}
        ) from exc
    asset.byte_size = written
    asset.storage_key = quarantine.relative_to(settings.asset_root.resolve()).as_posix()
    asset.status = "uploaded"
    asset.uploaded_at = _now()
    _audit(
        db, actor_id=user.id, action="tutor_attachment.upload", course_id=course_id,
        object_type="source_asset", object_id=asset.id,
        metadata={"byte_size": written},
    )
    db.commit()
    return _asset_view(asset)


@router.post(
    "/student/courses/{course_id}/tutor-attachments/{asset_id}:complete",
    response_model=AssetCompleteResponse,
)
def complete_tutor_attachment(
    course_id: str,
    asset_id: str,
    request: Request,
    user: StudentUser,
    db: DbSession,
):
    asset = _asset_for_student(db, user, course_id, asset_id)
    existing = db.scalar(select(ParsedDocument).where(ParsedDocument.asset_id == asset.id))
    if asset.status == "parsed" and existing is not None:
        return AssetCompleteResponse(asset=_asset_view(asset), document=_document_view(db, existing))
    if asset.status != "uploaded":
        raise HTTPException(status_code=409, detail="请先完成辅导附件内容上传")
    settings = request.app.state.settings
    quarantine = _stored_path(settings, asset)
    if quarantine is None or not quarantine.exists():
        raise HTTPException(status_code=409, detail="隔离区文件不存在，请重新上传")
    try:
        inspection = inspect_upload(
            quarantine, filename=asset.original_name,
            declared_mime=asset.declared_mime, expected_size=asset.expected_size,
            max_bytes=settings.asset_max_bytes,
            expected_sha256=asset.expected_sha256,
        )
    except UploadPolicyError as exc:
        _reject_asset(db, asset, exc.code, exc.message, quarantine)
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": exc.message}
        ) from exc

    accepted = resolve_storage_path(settings.asset_root, "accepted", asset.id)
    quarantine.replace(accepted)
    asset.storage_key = accepted.relative_to(settings.asset_root.resolve()).as_posix()
    asset.detected_mime = inspection.detected_mime
    asset.byte_size = inspection.byte_size
    asset.sha256 = inspection.sha256
    asset.security_status = "accepted"
    asset.accepted_at = _now()
    try:
        parsed = parse_document(accepted, asset.extension, asset.original_name)
    except DocumentParseError as exc:
        asset.status = "rejected"
        asset.rejection_code = exc.code
        asset.rejection_reason = exc.message
        accepted.unlink(missing_ok=True)
        asset.storage_key = None
        db.commit()
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": exc.message}
        ) from exc

    document = ParsedDocument(
        id=str(uuid4()), asset_id=asset.id, parser_name=parsed.parser_name,
        parser_version=PARSER_VERSION, status="parsed", title=parsed.title,
        segment_count=len(parsed.segments), page_count=parsed.page_count,
        text_length=sum(len(segment.text) for segment in parsed.segments),
        warnings_json=[*inspection.warnings, *parsed.warnings],
    )
    db.add(document)
    db.flush()
    for chunk in parsed.chunks:
        db.add(DocumentChunk(
            id=str(uuid4()), document_id=document.id,
            sequence_no=chunk.sequence_no, locator_json=chunk.locator,
            section_title=chunk.section_title, text=chunk.text,
            char_start=chunk.char_start, char_end=chunk.char_end,
            token_estimate=chunk.token_estimate, checksum=chunk.checksum,
        ))
    db.add(Derivation(
        id=str(uuid4()), source_asset_id=asset.id,
        derived_type="parsed_document", derived_id=document.id,
        relation="parsed_from", active=True,
    ))
    asset.status = "parsed"
    _audit(
        db, actor_id=user.id, action="tutor_attachment.parse", course_id=course_id,
        object_type="source_asset", object_id=asset.id,
        metadata={
            "parser_version": PARSER_VERSION,
            "chunk_count": len(parsed.chunks),
            "warning_count": len(document.warnings_json),
        },
    )
    db.commit()
    return AssetCompleteResponse(asset=_asset_view(asset), document=_document_view(db, document))


@router.get("/teacher/courses/{course_id}/assets", response_model=list[AssetView])
def list_course_assets(
    course_id: str,
    user: TeacherUser,
    db: DbSession,
    purpose: str | None = None,
):
    _ensure_teacher_course(db, user, course_id)
    query = select(SourceAsset).where(
        SourceAsset.course_id == course_id,
        SourceAsset.owner_id == user.id,
        SourceAsset.status != "deleted",
    )
    if purpose:
        query = query.where(SourceAsset.purpose == purpose)
    assets = db.scalars(query.order_by(SourceAsset.created_at.desc())).all()
    return [_asset_view(asset) for asset in assets]


@router.get("/teacher/courses/{course_id}/assets/{asset_id}", response_model=AssetCompleteResponse)
def get_course_asset(course_id: str, asset_id: str, user: TeacherUser, db: DbSession):
    asset = _asset_for_teacher(db, user, course_id, asset_id)
    document = db.scalar(select(ParsedDocument).where(ParsedDocument.asset_id == asset.id))
    if document is None:
        raise HTTPException(status_code=409, detail="材料尚未完成解析")
    return AssetCompleteResponse(asset=_asset_view(asset), document=_document_view(db, document))


def _concept_descriptors(db, course_id: str) -> list[AlignerConcept]:
    concepts = list(db.scalars(
        select(Concept).where(Concept.course_id == course_id).order_by(Concept.sort_order, Concept.id)
    ).all())
    published_revision_ids = list(db.scalars(
        select(KnowledgeGraph.published_revision_id).where(
            KnowledgeGraph.course_id == course_id,
            KnowledgeGraph.published_revision_id.is_not(None),
        )
    ).all())
    nodes = list(db.scalars(
        select(GraphNode).where(GraphNode.revision_id.in_(published_revision_ids))
    ).all()) if published_revision_ids else []
    node_by_id = {node.id: node for node in nodes}
    context_by_concept: dict[str, list[str]] = {}
    aliases_by_concept: dict[str, set[str]] = {}
    neighbors_by_concept: dict[str, set[str]] = {}
    for node in nodes:
        aliases_by_concept.setdefault(node.concept_id, set()).add(node.label)
        terms = [part.strip() for part in (node.definition + "；" + node.key_point).replace("。", "；").split("；")]
        context_by_concept.setdefault(node.concept_id, []).extend(part for part in terms if 1 < len(part) <= 30)
    if published_revision_ids:
        for edge in db.scalars(select(GraphEdge).where(GraphEdge.revision_id.in_(published_revision_ids))).all():
            left = node_by_id.get(edge.from_node_id)
            right = node_by_id.get(edge.to_node_id)
            if left and right:
                neighbors_by_concept.setdefault(left.concept_id, set()).add(right.label)
                neighbors_by_concept.setdefault(right.concept_id, set()).add(left.label)
    return [AlignerConcept(
        id=concept.id,
        name=concept.name,
        aliases=tuple(sorted(alias for alias in aliases_by_concept.get(concept.id, set()) if alias != concept.name)),
        context_terms=tuple(context_by_concept.get(concept.id, [])[:12]),
        neighbor_names=tuple(sorted(neighbors_by_concept.get(concept.id, set()))),
    ) for concept in concepts]


def _alignment_view(db, run: AlignmentRun, include_mentions: bool = True) -> AlignmentRunView:
    mention_views: list[AlignmentMentionView] = []
    if include_mentions:
        mentions = list(db.scalars(
            select(AlignmentMention).where(AlignmentMention.run_id == run.id).order_by(AlignmentMention.ordinal)
        ).all())
        concept_names = dict(db.execute(select(Concept.id, Concept.name).where(Concept.course_id == run.course_id)).all())
        for mention in mentions:
            candidates = list(db.scalars(
                select(AlignmentCandidate).where(AlignmentCandidate.mention_id == mention.id)
                .order_by(AlignmentCandidate.rank)
            ).all())
            review = db.scalar(select(AlignmentReview).where(AlignmentReview.mention_id == mention.id))
            candidate_views = [AlignmentCandidateView(
                concept_id=item.concept_id,
                concept_name=concept_names.get(item.concept_id, "已删除知识点"),
                rank=item.rank,
                lexical_score=item.lexical_score,
                context_score=item.context_score,
                graph_score=item.graph_score,
                final_score=item.final_score,
                recommended=item.recommended,
            ) for item in candidates]
            candidate_ids = {item.concept_id for item in candidates}
            if review and review.selected_concept_id and review.selected_concept_id not in candidate_ids:
                candidate_views.append(AlignmentCandidateView(
                    concept_id=review.selected_concept_id,
                    concept_name=concept_names.get(review.selected_concept_id, "已删除知识点"),
                    rank=0,
                    lexical_score=1.0,
                    context_score=1.0,
                    graph_score=1.0,
                    final_score=1.0,
                    recommended=True,
                ))
            mention_views.append(AlignmentMentionView(
                id=mention.id, ordinal=mention.ordinal, raw_text=mention.raw_text,
                normalized_text=mention.normalized_text, context=mention.context,
                status=mention.status, evidence_span_id=mention.evidence_span_id,
                candidates=candidate_views,
                review=AlignmentReviewView(
                    id=review.id, status=review.status, decision=review.decision,
                    selected_concept_id=review.selected_concept_id, note=review.note,
                    decided_at=review.decided_at,
                ) if review else None,
            ))
    return AlignmentRunView(
        id=run.id, course_id=run.course_id, source_type=run.source_type,
        source_asset_id=run.source_asset_id, purpose=run.purpose, mode=run.mode,
        status=run.status, parser_version=run.parser_version,
        ontology_version=run.ontology_version, aligner_version=run.aligner_version,
        thresholds=run.thresholds_json, summary=run.summary_json,
        created_at=run.created_at, completed_at=run.completed_at,
        mentions=mention_views,
    )


def _run_for_teacher(db, user, run_id: str) -> AlignmentRun:
    run = db.get(AlignmentRun, run_id)
    if run is None or CourseRepository(db).get_teacher_course(user.id, run.course_id) is None:
        raise HTTPException(status_code=404, detail="对齐任务不存在或无权访问")
    return run


@router.post(
    "/teacher/courses/{course_id}/alignment-runs",
    response_model=AlignmentRunView,
    status_code=status.HTTP_201_CREATED,
)
def create_alignment_run(
    course_id: str,
    payload: AlignmentRunCreate,
    user: TeacherUser,
    db: DbSession,
):
    _ensure_teacher_course(db, user, course_id)
    concepts = _concept_descriptors(db, course_id)
    if not concepts:
        raise HTTPException(status_code=409, detail="当前课程尚未建立规范知识点词表")
    source_type = "asset" if payload.source_asset_id else "manual"
    asset: SourceAsset | None = None
    document: ParsedDocument | None = None
    raw_mentions: list[tuple[str, str, str | None, int | None, int | None, dict | None]] = []
    parser_version = None
    if payload.source_asset_id:
        asset = _asset_for_teacher(db, user, course_id, payload.source_asset_id)
        if asset.status != "parsed":
            raise HTTPException(status_code=409, detail="材料尚未完成安全解析")
        if asset.purpose != payload.purpose:
            raise HTTPException(status_code=422, detail="材料用途与当前对齐任务不一致")
        document = db.scalar(select(ParsedDocument).where(ParsedDocument.asset_id == asset.id))
        if document is None or document.status != "parsed":
            raise HTTPException(status_code=409, detail="解析文档不可用")
        chunks = list(db.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.sequence_no)
        ).all())
        extracted = extract_document_mentions(
            ((chunk.id, chunk.text, chunk.locator_json) for chunk in chunks), concepts
        )
        raw_mentions = [
            (item.raw_text, item.context, item.chunk_id, item.start_char, item.end_char, item.locator)
            for item in extracted
        ]
        parser_version = document.parser_version
    else:
        mentions = split_manual_mentions(payload.manual_text or "")
        if not mentions:
            raise HTTPException(status_code=422, detail="请至少输入一个知识点")
        if len(mentions) > 50:
            raise HTTPException(status_code=422, detail="单次最多对齐50个知识点")
        raw_mentions = [(item, payload.manual_text or "", None, None, None, None) for item in mentions]

    run = AlignmentRun(
        id=str(uuid4()), course_id=course_id, actor_id=user.id, source_type=source_type,
        source_asset_id=asset.id if asset else None,
        raw_input=payload.manual_text.strip() if payload.manual_text else None,
        purpose=payload.purpose, mode="concept_alignment", status="running",
        parser_version=parser_version, ontology_version=ONTOLOGY_VERSION,
        aligner_version=ALIGNER_VERSION, thresholds_json=DEFAULT_THRESHOLDS,
        summary_json={},
    )
    db.add(run)
    db.flush()
    counts = {"matched": 0, "ambiguous": 0, "abstained": 0}
    for ordinal, (raw_text, context, chunk_id, start_char, end_char, locator) in enumerate(raw_mentions, start=1):
        decision = rank_concepts(raw_text, context, concepts)
        evidence_id = None
        if chunk_id is not None and start_char is not None and end_char is not None:
            quote = db.get(DocumentChunk, chunk_id).text[start_char:end_char]
            evidence = EvidenceSpan(
                id=str(uuid4()), chunk_id=chunk_id, start_char=start_char, end_char=end_char,
                quote=quote, locator_json=locator or {},
                checksum=sha256(quote.encode("utf-8")).hexdigest(),
            )
            db.add(evidence)
            db.flush()
            evidence_id = evidence.id
        mention = AlignmentMention(
            id=str(uuid4()), run_id=run.id, ordinal=ordinal, raw_text=raw_text[:500],
            normalized_text=normalize_concept_text(raw_text)[:500], context=context,
            evidence_span_id=evidence_id, status=decision.status,
        )
        db.add(mention)
        db.flush()
        for rank, candidate in enumerate(decision.candidates, start=1):
            db.add(AlignmentCandidate(
                id=str(uuid4()), mention_id=mention.id, concept_id=candidate.concept_id,
                rank=rank, lexical_score=candidate.lexical_score,
                context_score=candidate.context_score, graph_score=candidate.graph_score,
                final_score=candidate.final_score,
                recommended=candidate.concept_id == decision.recommended_concept_id,
            ))
        if decision.status in {"ambiguous", "abstained"}:
            db.add(AlignmentReview(id=str(uuid4()), mention_id=mention.id, status="pending"))
        counts[decision.status] += 1

    run.status = "needs_review" if counts["ambiguous"] + counts["abstained"] else "completed"
    run.completed_at = _now()
    run.summary_json = {"mention_count": len(raw_mentions), **counts, "pending_review": counts["ambiguous"] + counts["abstained"]}
    if asset:
        db.add(Derivation(
            id=str(uuid4()), source_asset_id=asset.id, derived_type="alignment_run",
            derived_id=run.id, relation="aligned_from", active=True,
        ))
    _audit(
        db, actor_id=user.id, action="alignment.run", course_id=course_id,
        object_type="alignment_run", object_id=run.id,
        metadata={"source_type": source_type, **run.summary_json},
    )
    db.commit()
    return _alignment_view(db, run)


@router.get("/teacher/alignment-runs/{run_id}", response_model=AlignmentRunView)
def get_alignment_run(run_id: str, user: TeacherUser, db: DbSession):
    return _alignment_view(db, _run_for_teacher(db, user, run_id))


@router.get("/teacher/alignment-runs/{run_id}/concepts", response_model=list[AlignmentMentionView])
def get_alignment_concepts(run_id: str, user: TeacherUser, db: DbSession):
    return _alignment_view(db, _run_for_teacher(db, user, run_id)).mentions


def _refresh_run_summary(db, run: AlignmentRun) -> None:
    mentions = list(db.scalars(select(AlignmentMention).where(AlignmentMention.run_id == run.id)).all())
    counts = {"matched": 0, "ambiguous": 0, "abstained": 0}
    pending = 0
    for mention in mentions:
        counts[mention.status] += 1
        review = db.scalar(select(AlignmentReview).where(AlignmentReview.mention_id == mention.id))
        if review and review.status == "pending":
            pending += 1
    run.summary_json = {"mention_count": len(mentions), **counts, "pending_review": pending}
    run.status = "needs_review" if pending else "completed"


@router.post("/teacher/alignment-reviews/{review_id}:decide", response_model=AlignmentRunView)
def decide_alignment_review(
    review_id: str,
    payload: AlignmentReviewDecision,
    user: TeacherUser,
    db: DbSession,
):
    review = db.get(AlignmentReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="复核项不存在")
    mention = db.get(AlignmentMention, review.mention_id)
    run = _run_for_teacher(db, user, mention.run_id)
    if run.status == "invalidated":
        raise HTTPException(status_code=409, detail="来源材料已删除，对齐结果不可继续使用")
    if review.status == "decided":
        raise HTTPException(status_code=409, detail="该复核项已经完成")
    selected_concept_id = payload.selected_concept_id
    effective_decision = payload.decision
    concept_created = False
    merged_review_ids: list[str] = []
    if payload.decision == "created":
        try:
            resolution = resolve_open_concept(
                db,
                course_id=run.course_id,
                name=payload.new_concept_name or "",
            )
        except InvalidConceptName as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        concept = resolution.concept
        concept_created = resolution.created
        effective_decision = "created" if concept_created else "matched"
        selected_concept_id = concept.id

        duplicate_rows = db.execute(
            select(AlignmentReview, AlignmentMention)
            .join(AlignmentMention, AlignmentMention.id == AlignmentReview.mention_id)
            .where(
                AlignmentMention.run_id == run.id,
                AlignmentMention.normalized_text.in_({
                    mention.normalized_text, concept.normalized_name,
                }),
                AlignmentMention.id != mention.id,
                AlignmentReview.status == "pending",
            )
        ).all()
        for duplicate_review, duplicate_mention in duplicate_rows:
            duplicate_review.status = "decided"
            duplicate_review.decision = "matched"
            duplicate_review.selected_concept_id = concept.id
            duplicate_review.reviewer_id = user.id
            duplicate_review.note = "与教师确认的新概念按规范化名称精确归并"
            duplicate_review.decided_at = _now()
            duplicate_mention.status = "matched"
            merged_review_ids.append(duplicate_review.id)
    if payload.selected_concept_id:
        concept = db.get(Concept, payload.selected_concept_id)
        if concept is None or concept.course_id != run.course_id:
            raise HTTPException(status_code=422, detail="所选知识点不属于当前课程")
    review.status = "decided"
    review.decision = effective_decision
    review.selected_concept_id = selected_concept_id
    review.reviewer_id = user.id
    review.note = payload.note.strip()
    review.decided_at = _now()
    mention.status = "matched" if effective_decision in {"matched", "created"} else "abstained"
    _refresh_run_summary(db, run)
    _audit(
        db, actor_id=user.id, action="alignment.review", course_id=run.course_id,
        object_type="alignment_review", object_id=review.id,
        metadata={
            "requested_decision": payload.decision,
            "decision": effective_decision,
            "selected_concept_id": selected_concept_id,
            "concept_created": concept_created,
            "merged_review_ids": merged_review_ids,
        },
    )
    db.commit()
    return _alignment_view(db, run)


@router.get("/teacher/evidence-spans/{span_id}", response_model=EvidenceSpanView)
def get_evidence_span(span_id: str, user: TeacherUser, db: DbSession):
    span = db.get(EvidenceSpan, span_id)
    if span is None:
        raise HTTPException(status_code=404, detail="证据片段不存在")
    chunk = db.get(DocumentChunk, span.chunk_id)
    document = db.get(ParsedDocument, chunk.document_id)
    asset = db.get(SourceAsset, document.asset_id)
    _ensure_teacher_course(db, user, asset.course_id)
    if asset.status == "deleted" or document.status == "invalidated":
        raise HTTPException(status_code=410, detail="证据来源已删除")
    return EvidenceSpanView(
        id=span.id, chunk_id=span.chunk_id, start_char=span.start_char,
        end_char=span.end_char, quote=span.quote, locator=span.locator_json,
        checksum=span.checksum, chunk_text=chunk.text,
    )


@router.delete("/teacher/courses/{course_id}/assets/{asset_id}", response_model=AssetDeletionView)
def delete_course_asset(
    course_id: str,
    asset_id: str,
    request: Request,
    user: TeacherUser,
    db: DbSession,
):
    asset = _asset_for_teacher(db, user, course_id, asset_id)
    if asset.status == "deleted":
        latest = db.scalar(select(DeletionJob).where(
            DeletionJob.source_asset_id == asset.id
        ).order_by(DeletionJob.requested_at.desc()))
        if latest:
            return AssetDeletionView(
                job_id=latest.id, asset_id=asset.id, status=latest.status,
                invalidated_derivations=latest.invalidated_derivations,
                storage_removed=latest.storage_removed,
            )
    job = DeletionJob(id=str(uuid4()), source_asset_id=asset.id, requested_by=user.id, status="running")
    db.add(job)
    storage_removed = False
    try:
        stored = _stored_path(request.app.state.settings, asset)
        if stored is not None and stored.exists():
            stored.unlink()
            storage_removed = True
        removed_draft_nodes: list[str] = []
        removed_draft_edges: list[str] = []
        retained_published_nodes: list[str] = []
        retained_published_edges: list[str] = []
        touched_revisions: set[str] = set()
        edge_derivations = list(db.scalars(select(Derivation).where(
            Derivation.source_asset_id == asset.id,
            Derivation.derived_type == "graph_edge",
            Derivation.active.is_(True),
        )).all())
        for derivation in edge_derivations:
            edge = db.get(GraphEdge, derivation.derived_id)
            if edge is None:
                continue
            revision = db.get(GraphRevision, edge.revision_id)
            if revision is not None and revision.status == "draft":
                db.delete(edge)
                removed_draft_edges.append(edge.id)
                touched_revisions.add(revision.id)
            else:
                retained_published_edges.append(edge.id)
        node_derivations = list(db.scalars(select(Derivation).where(
            Derivation.source_asset_id == asset.id,
            Derivation.derived_type == "graph_node",
            Derivation.active.is_(True),
        )).all())
        for derivation in node_derivations:
            node = db.get(GraphNode, derivation.derived_id)
            if node is None:
                continue
            revision = db.get(GraphRevision, node.revision_id)
            if revision is not None and revision.status == "draft":
                db.execute(delete(GraphEdge).where(
                    (GraphEdge.from_node_id == node.id) | (GraphEdge.to_node_id == node.id)
                ))
                db.delete(node)
                removed_draft_nodes.append(node.id)
                touched_revisions.add(revision.id)
            else:
                retained_published_nodes.append(node.id)
        for revision_id in touched_revisions:
            revision = db.get(GraphRevision, revision_id)
            revision.review_status = "pending"
            revision.quality_score = None
            revision.version += 1
        invalidated = db.execute(update(Derivation).where(
            Derivation.source_asset_id == asset.id,
            Derivation.active.is_(True),
        ).values(active=False)).rowcount or 0
        db.execute(update(ParsedDocument).where(
            ParsedDocument.asset_id == asset.id
        ).values(status="invalidated"))
        db.execute(update(AlignmentRun).where(
            AlignmentRun.source_asset_id == asset.id
        ).values(status="invalidated"))
        alignment_ids = select(AlignmentRun.id).where(AlignmentRun.source_asset_id == asset.id)
        db.execute(update(GraphExtractionArtifact).where(
            GraphExtractionArtifact.alignment_run_id.in_(alignment_ids),
            GraphExtractionArtifact.status != "invalidated",
        ).values(status="invalidated", version=GraphExtractionArtifact.version + 1))
        asset.status = "deleted"
        asset.security_status = "deleted"
        asset.deleted_at = _now()
        asset.storage_key = None
        job.status = "completed"
        job.invalidated_derivations = invalidated
        job.storage_removed = storage_removed
        job.completed_at = _now()
        _audit(
            db, actor_id=user.id, action="asset.delete", course_id=course_id,
            object_type="source_asset", object_id=asset.id,
            metadata={
                "invalidated_derivations": invalidated,
                "storage_removed": storage_removed,
                "removed_draft_graph_nodes": removed_draft_nodes,
                "retained_published_graph_nodes": retained_published_nodes,
                "removed_draft_graph_edges": removed_draft_edges,
                "retained_published_graph_edges": retained_published_edges,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        failed = DeletionJob(
            id=str(uuid4()), source_asset_id=asset.id, requested_by=user.id,
            status="failed", error_message=str(exc)[:500], completed_at=_now(),
        )
        db.add(failed)
        db.commit()
        return AssetDeletionView(
            job_id=failed.id, asset_id=asset.id, status="failed",
            invalidated_derivations=0, storage_removed=storage_removed,
        )
    return AssetDeletionView(
        job_id=job.id, asset_id=asset.id, status="completed",
        invalidated_derivations=job.invalidated_derivations,
        storage_removed=job.storage_removed,
    )
