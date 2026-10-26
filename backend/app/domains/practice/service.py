from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ...models import (
    Attempt,
    AuditEvent,
    BlueprintCell,
    Concept,
    Hint,
    LearningEvent,
    LearningResource,
    ModelRun,
    Question,
    QuestionBlueprint,
    QuestionConcept,
    QuestionGenerationRun,
    QuestionOption,
    QuestionSet,
    QuestionSetRevision,
    Score,
    User,
)
from ...repositories import CourseRepository
from ..model_gateway.profile_catalog import active_policy
from ..model_gateway.schemas import ModelRunView
from ..model_gateway.service import GatewayFailure, stable_hash, stable_json
from ..trajectory.service import ConceptContribution, EventCommand, TrajectoryService
from .blueprint import blueprint_cells
from .grading import grade_fill, grade_objective, grade_subjective_provisional
from .hints import validate_progressive_hints
from .model_generation import TASK_KIND, request_input_hash, run_question_generation
from .quality import validate_revision
from .schemas import (
    AttemptSubmitRequest,
    BlueprintCellView,
    GenerateQuestionSetRequest,
    HintRevealRequest,
    PracticeAttemptResultView,
    PracticeAttemptView,
    PracticeBlueprintView,
    PracticeQuestionView,
    PracticeScoreView,
    QuestionAttemptStateView,
    QuestionConceptView,
    QuestionOptionView,
    QuestionProgressItemView,
    QuestionSetDetailView,
    QuestionSetListView,
    QuestionSetProgressView,
    QuestionSetSummaryView,
    RevealedHintView,
    ReviewScoreRequest,
    RevisionVersionRequest,
    UpdateQuestionRequest,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _failure(status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, **extra},
    )


def _authorize_course(db: Session, actor: User, course_id: str) -> None:
    repository = CourseRepository(db)
    row = (
        repository.get_student_course(actor.id, course_id)
        if actor.role == "student"
        else repository.get_teacher_course(actor.id, course_id)
    )
    if row is None:
        raise _failure(404, "PRACTICE_COURSE_NOT_FOUND", "课程不存在或无权访问")


def _model_run_view(run: ModelRun | None) -> ModelRunView | None:
    if run is None:
        return None
    return ModelRunView(
        id=run.id,
        task_kind=run.task_kind,
        requested_profile_id=run.requested_profile_id,
        actual_profile_id=run.actual_profile_id,
        provider_model_id=run.provider_model_id,
        task_policy_version=run.task_policy_version,
        prompt_template_version=run.prompt_template_version,
        status=run.status,
        fallback_reason=run.fallback_reason,
        error_code=run.error_code,
        safe_error=run.safe_error,
        attempt_count=run.attempt_count,
        usage=run.usage_json or {},
        audit_hash=run.audit_hash,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


def blueprint_view(db: Session, blueprint: QuestionBlueprint) -> PracticeBlueprintView:
    cells = blueprint_cells(db, blueprint.id)
    concept_ids = list(dict.fromkeys(item.concept_id for item in cells))
    names = {
        item.id: item.name for item in db.scalars(select(Concept).where(
            Concept.id.in_(concept_ids)
        )).all()
    } if concept_ids else {}
    return PracticeBlueprintView(
        id=blueprint.id,
        version=blueprint.version,
        total=blueprint.total,
        cells=[BlueprintCellView(
            concept_id=item.concept_id,
            concept_label=names.get(item.concept_id, item.concept_id),
            question_type=item.question_type,
            count=item.count,
            difficulty_target=item.difficulty_target,
            cognitive_level=item.cognitive_level,
            position=item.position,
        ) for item in cells],
        source_summary=blueprint.source_summary_json or {},
    )


def _revision_for_actor(db: Session, question_set: QuestionSet, actor: User) -> QuestionSetRevision:
    if actor.role == "student":
        if question_set.owner_student_id == actor.id and question_set.status != "published":
            revision_id = question_set.working_revision_id
        else:
            revision_id = question_set.published_revision_id
    else:
        revision_id = question_set.working_revision_id or question_set.published_revision_id
    revision = db.get(QuestionSetRevision, revision_id) if revision_id else None
    if revision is None:
        raise _failure(404, "QUESTION_SET_REVISION_NOT_FOUND", "题组当前修订不存在")
    return revision


def _question_set_access(db: Session, actor: User, set_id: str) -> tuple[QuestionSet, QuestionSetRevision]:
    question_set = db.get(QuestionSet, set_id)
    if question_set is None:
        raise _failure(404, "QUESTION_SET_NOT_FOUND", "题组不存在或无权访问")
    _authorize_course(db, actor, question_set.course_id)
    if actor.role == "student":
        private_owner = question_set.owner_student_id == actor.id
        published_course = question_set.status == "published" and question_set.visibility == "course"
        if not private_owner and not published_course:
            raise _failure(404, "QUESTION_SET_NOT_FOUND", "题组不存在或无权访问")
    elif question_set.owner_student_id is not None:
        raise _failure(404, "QUESTION_SET_NOT_FOUND", "学生私有题组不向教师公开")
    return question_set, _revision_for_actor(db, question_set, actor)


def _question_access(db: Session, actor: User, question_id: str) -> tuple[Question, QuestionSetRevision, QuestionSet]:
    question = db.get(Question, question_id)
    if question is None:
        raise _failure(404, "QUESTION_NOT_FOUND", "题目不存在或无权访问")
    revision = db.get(QuestionSetRevision, question.revision_id)
    question_set = db.get(QuestionSet, revision.question_set_id) if revision else None
    if revision is None or question_set is None:
        raise _failure(404, "QUESTION_NOT_FOUND", "题目不存在或无权访问")
    accessible_set, current_revision = _question_set_access(db, actor, question_set.id)
    if current_revision.id != revision.id:
        raise _failure(409, "QUESTION_REVISION_STALE", "题目不属于题组当前可见修订")
    return question, revision, accessible_set


def _generation_model_run(db: Session, revision: QuestionSetRevision) -> ModelRun | None:
    if not revision.blueprint_id:
        return None
    generation = db.scalar(select(QuestionGenerationRun).where(
        QuestionGenerationRun.blueprint_id == revision.blueprint_id,
        QuestionGenerationRun.model_run_id.is_not(None),
    ).order_by(QuestionGenerationRun.created_at.desc()))
    return db.get(ModelRun, generation.model_run_id) if generation and generation.model_run_id else None


def _latest_attempts(
    db: Session,
    *,
    student_id: str,
    revision_id: str,
) -> dict[str, Attempt]:
    attempts = list(db.scalars(select(Attempt).where(
        Attempt.student_id == student_id,
        Attempt.revision_id == revision_id,
    ).order_by(Attempt.question_id, Attempt.attempt_no.desc())).all())
    result: dict[str, Attempt] = {}
    for attempt in attempts:
        result.setdefault(attempt.question_id, attempt)
    return result


def _hint_events(
    db: Session,
    *,
    student_id: str,
    course_id: str,
    question_ids: list[str],
) -> dict[str, dict[int, LearningEvent]]:
    result: dict[str, dict[int, LearningEvent]] = defaultdict(dict)
    if not question_ids:
        return result
    events = list(db.scalars(select(LearningEvent).where(
        LearningEvent.student_id == student_id,
        LearningEvent.course_id == course_id,
        LearningEvent.event_type == "hint_viewed",
        LearningEvent.object_type == "question",
        LearningEvent.object_id.in_(question_ids),
    ).order_by(LearningEvent.occurred_at, LearningEvent.id)).all())
    for event in events:
        level = event.hint_level or int((event.payload or {}).get("level") or 0)
        if 1 <= level <= 3:
            result[event.object_id].setdefault(level, event)
    return result


def _score_view(score: Score | None) -> PracticeScoreView | None:
    if score is None:
        return None
    graded_at = score.graded_at
    if graded_at.tzinfo is None:
        graded_at = graded_at.replace(tzinfo=timezone.utc)
    return PracticeScoreView(
        attempt_id=score.attempt_id,
        score=score.score,
        is_correct=score.is_correct,
        confidence=score.confidence,
        grading_mode=score.grading_mode,
        review_status=score.review_status,
        feedback=score.feedback_json or {},
        graded_at=graded_at,
    )


def _progress_data(
    db: Session,
    *,
    student_id: str,
    question_set: QuestionSet,
    revision: QuestionSetRevision,
) -> QuestionSetProgressView:
    questions = list(db.scalars(select(Question).where(
        Question.revision_id == revision.id
    ).order_by(Question.position)).all())
    attempts = _latest_attempts(db, student_id=student_id, revision_id=revision.id)
    hint_events = _hint_events(
        db,
        student_id=student_id,
        course_id=question_set.course_id,
        question_ids=[item.id for item in questions],
    )
    scores = {
        item.attempt_id: item for item in db.scalars(select(Score).where(
            Score.attempt_id.in_([attempt.id for attempt in attempts.values()])
        )).all()
    } if attempts else {}
    items: list[QuestionProgressItemView] = []
    graded_scores: list[float] = []
    for question in questions:
        attempt = attempts.get(question.id)
        score = scores.get(attempt.id) if attempt else None
        if score is not None and score.review_status in {"graded", "reviewed"}:
            graded_scores.append(score.score)
        items.append(QuestionProgressItemView(
            question_id=question.id,
            position=question.position,
            completed=attempt is not None,
            hint_level=max(hint_events.get(question.id, {0: None})),
            attempt_id=attempt.id if attempt else None,
            score=score.score if score and score.review_status in {"graded", "reviewed"} else None,
            review_status=score.review_status if score else None,
        ))
    return QuestionSetProgressView(
        question_set_id=question_set.id,
        revision_id=revision.id,
        total=len(questions),
        completed=sum(1 for item in items if item.completed),
        average_score=round(sum(graded_scores) / len(graded_scores), 4) if graded_scores else None,
        items=items,
    )


def question_set_progress(
    db: Session,
    *,
    student: User,
    set_id: str,
) -> QuestionSetProgressView:
    question_set, revision = _question_set_access(db, student, set_id)
    return _progress_data(
        db,
        student_id=student.id,
        question_set=question_set,
        revision=revision,
    )


def _set_view(
    db: Session,
    *,
    actor: User,
    question_set: QuestionSet,
    include_questions: bool,
) -> QuestionSetSummaryView | QuestionSetDetailView:
    revision = _revision_for_actor(db, question_set, actor)
    questions = list(db.scalars(select(Question).where(
        Question.revision_id == revision.id
    ).order_by(Question.position)).all())
    question_ids = [item.id for item in questions]
    concept_rows = list(db.execute(
        select(QuestionConcept, Concept)
        .join(Concept, Concept.id == QuestionConcept.concept_id)
        .where(QuestionConcept.question_id.in_(question_ids))
        .order_by(Concept.sort_order, Concept.id)
    ).all()) if question_ids else []
    concept_views: list[QuestionConceptView] = []
    seen_concepts: set[str] = set()
    for mapping, concept in concept_rows:
        if concept.id in seen_concepts:
            continue
        seen_concepts.add(concept.id)
        concept_views.append(QuestionConceptView(
            concept_id=concept.id,
            label=concept.name,
            weight=None,
        ))

    progress = None
    attempts: dict[str, Attempt] = {}
    hint_events: dict[str, dict[int, LearningEvent]] = defaultdict(dict)
    scores: dict[str, Score] = {}
    if actor.role == "student":
        progress = _progress_data(
            db,
            student_id=actor.id,
            question_set=question_set,
            revision=revision,
        )
        attempts = _latest_attempts(db, student_id=actor.id, revision_id=revision.id)
        hint_events = _hint_events(
            db,
            student_id=actor.id,
            course_id=question_set.course_id,
            question_ids=question_ids,
        )
        if attempts:
            scores = {
                item.attempt_id: item for item in db.scalars(select(Score).where(
                    Score.attempt_id.in_([attempt.id for attempt in attempts.values()])
                )).all()
            }

    summary_fields = dict(
        id=question_set.id,
        title=question_set.title,
        status=question_set.status,
        visibility=question_set.visibility,
        revision_id=revision.id,
        revision_no=revision.revision_no,
        revision_version=revision.version,
        total=len(questions),
        completed=progress.completed if progress else 0,
        average_score=progress.average_score if progress else None,
        concepts=concept_views,
        source_kind=revision.source_kind,
        model_run=_model_run_view(_generation_model_run(db, revision)),
    )
    if not include_questions:
        return QuestionSetSummaryView(**summary_fields)

    concepts_by_question: dict[str, list[QuestionConceptView]] = defaultdict(list)
    for mapping, concept in concept_rows:
        concepts_by_question[mapping.question_id].append(QuestionConceptView(
            concept_id=concept.id,
            label=concept.name,
            weight=mapping.weight,
        ))
    options_by_question: dict[str, list[QuestionOption]] = defaultdict(list)
    if question_ids:
        for option in db.scalars(select(QuestionOption).where(
            QuestionOption.question_id.in_(question_ids)
        ).order_by(QuestionOption.question_id, QuestionOption.position)).all():
            options_by_question[option.question_id].append(option)
    hints_by_question: dict[str, dict[int, Hint]] = defaultdict(dict)
    if question_ids:
        for hint in db.scalars(select(Hint).where(
            Hint.question_id.in_(question_ids),
            Hint.validation_status == "passed",
        ).order_by(Hint.question_id, Hint.level)).all():
            hints_by_question[hint.question_id][hint.level] = hint

    question_views: list[PracticeQuestionView] = []
    for question in questions:
        attempt = attempts.get(question.id)
        score = scores.get(attempt.id) if attempt else None
        revealed: list[RevealedHintView] = []
        for level, event in sorted(hint_events.get(question.id, {}).items()):
            hint = hints_by_question.get(question.id, {}).get(level)
            if hint is not None:
                revealed.append(RevealedHintView(
                    question_id=question.id,
                    level=level,
                    content=hint.content,
                    revealed_at=event.occurred_at,
                ))
        attempt_state = None
        if attempt is not None or revealed:
            attempt_state = QuestionAttemptStateView(
                attempt_id=attempt.id if attempt else None,
                attempt_no=attempt.attempt_no if attempt else 0,
                answer=attempt.answer_json if attempt else None,
                hint_level=max((item.level for item in revealed), default=attempt.hint_level if attempt else 0),
                status=attempt.status if attempt else "in_progress",
                submitted_at=attempt.submitted_at if attempt else None,
                score=_score_view(score),
                revealed_hints=revealed,
            )
        teacher_view = actor.role == "teacher"
        explanation = None
        if teacher_view or (score is not None and score.review_status != "needs_review"):
            explanation = question.explanation
        question_views.append(PracticeQuestionView(
            id=question.id,
            position=question.position,
            type=question.question_type,
            prompt=question.prompt,
            options=[QuestionOptionView(
                id=option.id,
                position=option.position,
                content=option.content,
                is_correct=option.is_correct if teacher_view else None,
            ) for option in options_by_question.get(question.id, [])],
            concepts=concepts_by_question.get(question.id, []),
            hints_available=len(hints_by_question.get(question.id, {})),
            attempt_state=attempt_state,
            answer_spec=question.answer_spec_json if teacher_view else None,
            rubric=question.rubric_json if teacher_view else None,
            explanation=explanation,
            cognitive_level=question.cognitive_level if teacher_view else None,
            difficulty_prior=question.difficulty_prior if teacher_view else None,
        ))
    return QuestionSetDetailView(
        **summary_fields,
        course_id=question_set.course_id,
        quality_status=revision.quality_status,
        source_summary=revision.source_summary,
        questions=question_views,
    )


def list_question_sets(
    db: Session,
    *,
    actor: User,
    course_id: str,
) -> QuestionSetListView:
    _authorize_course(db, actor, course_id)
    query = select(QuestionSet).where(QuestionSet.course_id == course_id)
    if actor.role == "student":
        query = query.where(or_(
            QuestionSet.owner_student_id == actor.id,
            (QuestionSet.owner_student_id.is_(None))
            & (QuestionSet.status == "published")
            & (QuestionSet.visibility == "course"),
        ))
    else:
        query = query.where(QuestionSet.owner_student_id.is_(None))
    sets = list(db.scalars(query.order_by(QuestionSet.updated_at.desc(), QuestionSet.id)).all())
    return QuestionSetListView(items=[
        _set_view(db, actor=actor, question_set=item, include_questions=False)
        for item in sets
    ])


def question_set_detail(
    db: Session,
    *,
    actor: User,
    set_id: str,
) -> QuestionSetDetailView:
    question_set, _ = _question_set_access(db, actor, set_id)
    return _set_view(db, actor=actor, question_set=question_set, include_questions=True)


def _persist_generated_question(
    db: Session,
    *,
    revision: QuestionSetRevision,
    cell: BlueprintCell,
    candidate: Any,
    position: int,
) -> None:
    question = Question(
        id=str(uuid4()),
        revision_id=revision.id,
        position=position,
        question_type=candidate.question_type,
        prompt=candidate.prompt.strip(),
        answer_spec_json={},
        rubric_json=[],
        explanation=candidate.explanation.strip(),
        cognitive_level=candidate.cognitive_level,
        difficulty_prior=candidate.difficulty_prior,
        difficulty_calibrated=None,
        source_evidence_ids=list(candidate.evidence_ids),
    )
    db.add(question)
    db.flush()
    if candidate.question_type in {"single", "multiple", "judgment"}:
        correct_ids: list[str] = []
        for option_position, generated in enumerate(candidate.options, start=1):
            option = QuestionOption(
                id=str(uuid4()),
                question_id=question.id,
                position=option_position,
                content=generated.content.strip(),
                is_correct=generated.is_correct,
                misconception_code=generated.misconception_code,
            )
            db.add(option)
            if option.is_correct:
                correct_ids.append(option.id)
        question.answer_spec_json = {
            "kind": "option_set",
            "selected_option_ids": correct_ids,
        }
    elif candidate.question_type == "fill":
        question.answer_spec_json = {
            "kind": "normalized_text",
            "accepted_texts": list(candidate.accepted_texts),
            "numeric_answer": candidate.numeric_answer,
            "absolute_tolerance": candidate.absolute_tolerance,
            "relative_tolerance": candidate.relative_tolerance,
        }
    else:
        question.answer_spec_json = {
            "kind": "rubric",
            "reference_answer": candidate.reference_answer,
        }
        question.rubric_json = [item.model_dump() for item in candidate.rubric]
    db.add(QuestionConcept(
        id=str(uuid4()),
        question_id=question.id,
        concept_id=cell.concept_id,
        weight=1.0,
        evidence_ids=list(candidate.evidence_ids),
    ))
    answer_texts: list[str]
    rubric_claims: list[str] = []
    if candidate.question_type in {"single", "multiple", "judgment"}:
        answer_texts = [item.content for item in candidate.options if item.is_correct]
    elif candidate.question_type == "fill":
        answer_texts = list(candidate.accepted_texts)
    else:
        answer_texts = [candidate.reference_answer]
        rubric_claims = [item.criterion for item in candidate.rubric]
    hint_check = validate_progressive_hints(
        list(candidate.hints),
        answer_texts=answer_texts,
        rubric_claims=rubric_claims,
    )
    for level, content in enumerate(candidate.hints, start=1):
        db.add(Hint(
            id=str(uuid4()),
            question_id=question.id,
            level=level,
            content=content.strip(),
            leakage_score=hint_check.leakage_scores[level - 1],
            information_gain=hint_check.information_gains[level - 1],
            validation_status="passed" if hint_check.passed else "failed",
        ))


def _existing_generated_set(
    db: Session,
    *,
    actor: User,
    blueprint: QuestionBlueprint,
    cells: list[BlueprintCell],
    payload: GenerateQuestionSetRequest,
) -> QuestionSetDetailView | None:
    revision = db.scalar(select(QuestionSetRevision).where(
        QuestionSetRevision.blueprint_id == blueprint.id
    ).order_by(QuestionSetRevision.created_at.desc()))
    if revision is None:
        return None
    question_set = db.get(QuestionSet, revision.question_set_id)
    prior = db.scalar(select(ModelRun).where(
        ModelRun.actor_id == actor.id,
        ModelRun.course_id == blueprint.course_id,
        ModelRun.task_kind == TASK_KIND,
        ModelRun.idempotency_key == payload.idempotency_key,
    ))
    if prior is None:
        raise _failure(409, "BLUEPRINT_ALREADY_CONSUMED", "该蓝图已经生成题组，不能重复消费")
    policy = active_policy(db, TASK_KIND)
    from ...models import PromptTemplate
    prompt = db.scalar(select(PromptTemplate).where(
        PromptTemplate.task_kind == TASK_KIND,
        PromptTemplate.active.is_(True),
    ).order_by(PromptTemplate.created_at.desc()))
    if policy is None or prompt is None:
        raise _failure(503, "MODEL_TASK_CONFIGURATION_MISSING", "习题生成任务配置当前不可用")
    expected_hash = request_input_hash(
        blueprint=blueprint,
        cells=cells,
        title=payload.title.strip(),
        requested_profile_id=payload.requested_profile_id,
        policy_version=policy.version,
        prompt_version=prompt.version,
    )
    if prior.input_hash != expected_hash:
        raise _failure(
            409,
            "MODEL_REQUEST_IDEMPOTENCY_CONFLICT",
            "同一幂等键已用于不同的习题生成输入",
            model_run_id=prior.id,
        )
    return _set_view(db, actor=actor, question_set=question_set, include_questions=True)


def generate_question_set(
    db: Session,
    *,
    settings: Any,
    adapter_registry: dict[str, Any],
    actor: User,
    course_id: str,
    payload: GenerateQuestionSetRequest,
) -> QuestionSetDetailView:
    _authorize_course(db, actor, course_id)
    blueprint = db.get(QuestionBlueprint, payload.blueprint_id)
    if blueprint is None or blueprint.course_id != course_id or blueprint.created_by != actor.id:
        raise _failure(404, "PRACTICE_BLUEPRINT_NOT_FOUND", "习题蓝图不存在或无权使用")
    if blueprint.requested_profile_id and blueprint.requested_profile_id != payload.requested_profile_id:
        raise _failure(409, "BLUEPRINT_PROFILE_CONFLICT", "生成模型与蓝图编译时明选Profile不一致")
    cells = blueprint_cells(db, blueprint.id)
    existing = _existing_generated_set(
        db,
        actor=actor,
        blueprint=blueprint,
        cells=cells,
        payload=payload,
    )
    if existing is not None:
        return existing
    if blueprint.status != "compiled":
        raise _failure(409, "BLUEPRINT_NOT_GENERATABLE", "该蓝图当前不能提交生成")
    output, model_run, generation_run = run_question_generation(
        db,
        settings=settings,
        adapter_registry=adapter_registry,
        actor_id=actor.id,
        blueprint=blueprint,
        cells=cells,
        title=payload.title.strip(),
        requested_profile_id=payload.requested_profile_id,
        idempotency_key=payload.idempotency_key,
    )
    question_set = QuestionSet(
        id=str(uuid4()),
        course_id=course_id,
        created_by=actor.id,
        owner_student_id=actor.id if actor.role == "student" else None,
        title=payload.title.strip(),
        status="validated" if actor.role == "student" else "draft",
        visibility="private" if actor.role == "student" else "course",
    )
    db.add(question_set)
    db.flush()
    revision = QuestionSetRevision(
        id=str(uuid4()),
        question_set_id=question_set.id,
        parent_revision_id=None,
        blueprint_id=blueprint.id,
        revision_no=1,
        status="validated" if actor.role == "student" else "draft",
        quality_status="passed",
        source_kind="model",
        source_summary=stable_json({
            "blueprint": blueprint.source_summary_json,
            "model_run_id": model_run.id,
            "generation_run_id": generation_run.id,
        }),
        created_by=actor.id,
        version=1,
    )
    db.add(revision)
    db.flush()
    question_set.working_revision_id = revision.id
    by_cell: dict[str, list[Any]] = defaultdict(list)
    for candidate in output.questions:
        by_cell[candidate.blueprint_cell_id].append(candidate)
    position = 0
    for cell in cells:
        for candidate in by_cell[cell.id]:
            position += 1
            _persist_generated_question(
                db,
                revision=revision,
                cell=cell,
                candidate=candidate,
                position=position,
            )
    db.flush()
    gate = validate_revision(db, revision)
    if not gate.hard_pass:
        revision.quality_status = "failed"
        question_set.status = "draft"
        generation_run.status = "rejected"
        generation_run.rejected_count = len(output.questions)
        generation_run.safe_error = "持久化后题组未通过TraceQ质量门"
        generation_run.completed_at = _now()
        db.commit()
        raise _failure(
            422,
            "QUESTION_SET_HARD_GATE_FAILED",
            "题组未通过发布前确定性质量门",
            issues=list(gate.issues),
        )
    blueprint.status = "generated"
    generation_run.status = "completed"
    generation_run.completed_at = _now()
    question_set.updated_at = _now()
    db.add(AuditEvent(
        id=str(uuid4()),
        actor_id=actor.id,
        action="practice.question_set.generated",
        object_type="question_set",
        object_id=question_set.id,
        course_id=course_id,
        outcome="success",
        metadata_json={
            "blueprint_id": blueprint.id,
            "revision_id": revision.id,
            "model_run_id": model_run.id,
            "question_count": position,
            "source_kind": "model",
        },
    ))
    db.commit()
    if actor.role == "student":
        concept_ids = list(dict.fromkeys(item.concept_id for item in cells))
        _emit_event(
            db,
            student=actor,
            course_id=course_id,
            idempotency_key=f"a3:question-generated:{question_set.id}:{revision.id}",
            event_type="question_generated",
            object_type="question_set",
            object_id=question_set.id,
            concept_ids=concept_ids,
            difficulty=sum(item.difficulty_target * item.count for item in cells) / blueprint.total,
            payload={
                "blueprint_id": blueprint.id,
                "question_count": position,
                "model_run_id": model_run.id,
            },
        )
    return _set_view(db, actor=actor, question_set=question_set, include_questions=True)


def update_teacher_question(
    db: Session,
    *,
    teacher: User,
    question_id: str,
    payload: UpdateQuestionRequest,
) -> QuestionSetDetailView:
    question, revision, question_set = _question_access(db, teacher, question_id)
    if revision.status == "published" or question_set.status == "published":
        raise _failure(409, "PUBLISHED_QUESTION_IMMUTABLE", "已发布题组修订只读，请派生新修订后再编辑")
    if revision.version != payload.expected_revision_version:
        raise _failure(
            409,
            "QUESTION_REVISION_CONFLICT",
            "题组修订已被其他操作更新，请刷新后重试",
            expected_version=payload.expected_revision_version,
            actual_version=revision.version,
        )
    question.prompt = payload.prompt.strip()
    question.explanation = payload.explanation.strip()
    question.cognitive_level = payload.cognitive_level
    question.difficulty_prior = payload.difficulty_prior
    question.rubric_json = [dict(item) for item in payload.rubric]
    objective = question.question_type in {"single", "multiple", "judgment"}
    existing_options = {
        item.id: item for item in db.scalars(select(QuestionOption).where(
            QuestionOption.question_id == question.id
        )).all()
    }
    provided_ids = {item.id for item in payload.options if item.id}
    if provided_ids - set(existing_options):
        raise _failure(422, "QUESTION_OPTION_OUT_OF_SCOPE", "编辑请求包含当前题目之外的选项")
    correct_ids: list[str] = []
    if objective:
        for option in existing_options.values():
            if option.id not in provided_ids:
                db.delete(option)
        for position, submitted in enumerate(payload.options, start=1):
            option = existing_options.get(submitted.id) if submitted.id else None
            if option is None:
                option = QuestionOption(
                    id=str(uuid4()),
                    question_id=question.id,
                    position=position,
                    content=submitted.content.strip(),
                    is_correct=submitted.is_correct,
                )
                db.add(option)
            else:
                option.position = position
                option.content = submitted.content.strip()
                option.is_correct = submitted.is_correct
            if option.is_correct:
                correct_ids.append(option.id)
        question.answer_spec_json = {
            **payload.answer_spec,
            "kind": "option_set",
            "selected_option_ids": correct_ids,
        }
    else:
        if existing_options:
            db.execute(delete(QuestionOption).where(QuestionOption.question_id == question.id))
        question.answer_spec_json = dict(payload.answer_spec)
    revision.version += 1
    revision.status = "draft"
    revision.quality_status = "pending"
    question_set.status = "draft"
    question_set.updated_at = _now()
    db.flush()
    gate = validate_revision(db, revision)
    db.add(AuditEvent(
        id=str(uuid4()),
        actor_id=teacher.id,
        action="practice.question.updated",
        object_type="question",
        object_id=question.id,
        course_id=question_set.course_id,
        outcome="success",
        metadata_json={
            "revision_id": revision.id,
            "revision_version": revision.version,
            "deterministic_gate_passed": gate.hard_pass,
        },
    ))
    db.commit()
    return _set_view(db, actor=teacher, question_set=question_set, include_questions=True)


def validate_teacher_question_set(
    db: Session,
    *,
    teacher: User,
    set_id: str,
    payload: RevisionVersionRequest,
) -> QuestionSetDetailView:
    question_set, revision = _question_set_access(db, teacher, set_id)
    if revision.status == "published" or question_set.status == "published":
        return _set_view(db, actor=teacher, question_set=question_set, include_questions=True)
    if revision.version != payload.expected_revision_version:
        raise _failure(409, "QUESTION_REVISION_CONFLICT", "题组修订已变化，请刷新后重试")
    gate = validate_revision(db, revision)
    revision.version += 1
    revision.quality_status = "passed" if gate.hard_pass else "failed"
    revision.status = "validated" if gate.hard_pass else "draft"
    question_set.status = revision.status
    question_set.updated_at = _now()
    db.add(AuditEvent(
        id=str(uuid4()),
        actor_id=teacher.id,
        action="practice.question_set.validated",
        object_type="question_set_revision",
        object_id=revision.id,
        course_id=question_set.course_id,
        outcome="success" if gate.hard_pass else "rejected",
        metadata_json={
            "revision_version": revision.version,
            "hard_pass": gate.hard_pass,
            "issue_count": len(gate.issues),
        },
    ))
    db.commit()
    return _set_view(db, actor=teacher, question_set=question_set, include_questions=True)


def publish_teacher_question_set(
    db: Session,
    *,
    teacher: User,
    set_id: str,
    payload: RevisionVersionRequest,
) -> QuestionSetDetailView:
    question_set, revision = _question_set_access(db, teacher, set_id)
    if revision.status == "published" and question_set.status == "published":
        return _set_view(db, actor=teacher, question_set=question_set, include_questions=True)
    if revision.version != payload.expected_revision_version:
        raise _failure(409, "QUESTION_REVISION_CONFLICT", "题组修订已变化，请刷新后重试")
    gate = validate_revision(db, revision)
    if not gate.hard_pass:
        revision.quality_status = "failed"
        db.commit()
        raise _failure(
            422,
            "QUESTION_SET_HARD_GATE_FAILED",
            "题组未通过发布前质量硬门",
            issues=list(gate.issues),
        )
    revision.version += 1
    revision.status = "published"
    revision.quality_status = "passed"
    revision.published_at = _now()
    question_set.status = "published"
    question_set.visibility = "course"
    question_set.published_revision_id = revision.id
    question_set.updated_at = _now()
    db.add(AuditEvent(
        id=str(uuid4()),
        actor_id=teacher.id,
        action="practice.question_set.published",
        object_type="question_set_revision",
        object_id=revision.id,
        course_id=question_set.course_id,
        outcome="success",
        metadata_json={
            "revision_version": revision.version,
            "question_count": db.scalar(select(func.count()).select_from(Question).where(
                Question.revision_id == revision.id
            )) or 0,
            "audience": "course",
        },
    ))
    db.commit()
    return _set_view(db, actor=teacher, question_set=question_set, include_questions=True)


def _question_concept_ids(db: Session, question_id: str) -> list[str]:
    return list(db.scalars(select(QuestionConcept.concept_id).where(
        QuestionConcept.question_id == question_id
    ).order_by(QuestionConcept.id)).all())


def _emit_event(
    db: Session,
    *,
    student: User,
    course_id: str,
    idempotency_key: str,
    event_type: str,
    object_type: str,
    object_id: str,
    concept_ids: list[str],
    payload: dict[str, Any],
    outcome: float | None = None,
    difficulty: float | None = None,
    hint_level: int | None = None,
    attempt_no: int | None = None,
    completion: float | None = None,
    upstream_confidence: float = 1.0,
    correction_of_event_id: str | None = None,
) -> None:
    unique_concepts = list(dict.fromkeys(concept_ids))
    if not unique_concepts:
        return
    weight = 1.0 / len(unique_concepts)
    TrajectoryService(db).ingest(
        student=student,
        course_id=course_id,
        command=EventCommand(
            idempotency_key=idempotency_key,
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            concepts=[ConceptContribution(item, weight) for item in unique_concepts],
            outcome=outcome,
            difficulty=difficulty,
            hint_level=hint_level,
            attempt_no=attempt_no,
            completion=completion,
            strategy=None,
            upstream_confidence=upstream_confidence,
            alignment_confidence=1.0,
            occurred_at=_now(),
            correction_of_event_id=correction_of_event_id,
            payload=payload,
        ),
    )


def reveal_hint(
    db: Session,
    *,
    student: User,
    question_id: str,
    level: int,
    payload: HintRevealRequest,
) -> RevealedHintView:
    if level < 1 or level > 3:
        raise _failure(404, "HINT_LEVEL_NOT_FOUND", "提示级别不存在")
    question, _, question_set = _question_access(db, student, question_id)
    hint = db.scalar(select(Hint).where(
        Hint.question_id == question.id,
        Hint.level == level,
        Hint.validation_status == "passed",
    ))
    if hint is None:
        raise _failure(404, "HINT_NOT_FOUND", "该级提示不存在或未通过防泄漏校验")
    existing_key = db.scalar(select(LearningEvent).where(
        LearningEvent.student_id == student.id,
        LearningEvent.course_id == question_set.course_id,
        LearningEvent.idempotency_key == payload.idempotency_key,
    ))
    if existing_key is not None:
        if (
            existing_key.event_type != "hint_viewed"
            or existing_key.object_id != question.id
            or existing_key.hint_level != level
        ):
            raise _failure(409, "HINT_IDEMPOTENCY_CONFLICT", "同一幂等键已用于不同的提示操作")
        return RevealedHintView(
            question_id=question.id,
            level=level,
            content=hint.content,
            revealed_at=existing_key.occurred_at,
        )
    viewed = _hint_events(
        db,
        student_id=student.id,
        course_id=question_set.course_id,
        question_ids=[question.id],
    ).get(question.id, {})
    if level in viewed:
        return RevealedHintView(
            question_id=question.id,
            level=level,
            content=hint.content,
            revealed_at=viewed[level].occurred_at,
        )
    expected_level = max(viewed, default=0) + 1
    if level != expected_level:
        raise _failure(
            409,
            "HINT_LEVEL_SEQUENCE_INVALID",
            "必须按顺序逐级查看提示",
            expected_level=expected_level,
        )
    _emit_event(
        db,
        student=student,
        course_id=question_set.course_id,
        idempotency_key=payload.idempotency_key,
        event_type="hint_viewed",
        object_type="question",
        object_id=question.id,
        concept_ids=_question_concept_ids(db, question.id),
        hint_level=level,
        payload={"level": level, "validator_version": hint.validator_version},
    )
    event = db.scalar(select(LearningEvent).where(
        LearningEvent.student_id == student.id,
        LearningEvent.course_id == question_set.course_id,
        LearningEvent.idempotency_key == payload.idempotency_key,
    ))
    return RevealedHintView(
        question_id=question.id,
        level=level,
        content=hint.content,
        revealed_at=event.occurred_at if event else _now(),
    )


def _attempt_result(db: Session, attempt: Attempt) -> PracticeAttemptResultView:
    score = db.scalar(select(Score).where(Score.attempt_id == attempt.id))
    return PracticeAttemptResultView(
        attempt=PracticeAttemptView(
            id=attempt.id,
            question_id=attempt.question_id,
            question_set_id=attempt.question_set_id,
            revision_id=attempt.revision_id,
            attempt_no=attempt.attempt_no,
            answer=attempt.answer_json,
            hint_level=attempt.hint_level,
            status=attempt.status,
            submitted_at=attempt.submitted_at,
        ),
        score=_score_view(score),
    )


def _grade_question(db: Session, question: Question, answer: dict[str, Any]):
    options = list(db.scalars(select(QuestionOption).where(
        QuestionOption.question_id == question.id
    ).order_by(QuestionOption.position)).all())
    if question.question_type in {"single", "multiple", "judgment"}:
        return grade_objective(
            question_type=question.question_type,
            answer=answer,
            correct_option_ids={item.id for item in options if item.is_correct},
            valid_option_ids={item.id for item in options},
        )
    if question.question_type == "fill":
        return grade_fill(answer=answer, answer_spec=question.answer_spec_json or {})
    return grade_subjective_provisional(
        answer=answer,
        answer_spec=question.answer_spec_json or {},
        rubric=question.rubric_json or [],
    )


def _sync_resource_projection(
    db: Session,
    *,
    question_set: QuestionSet,
    progress: QuestionSetProgressView,
) -> None:
    resource = db.get(LearningResource, question_set.id)
    if resource is None or resource.resource_type != "question_set":
        return
    resource.progress_completed = progress.completed
    resource.progress_total = progress.total
    resource.accuracy = (
        round(progress.average_score * 100.0, 2)
        if progress.average_score is not None
        else None
    )
    accuracy_text = f" · 当前正确率 {round(resource.accuracy)}%" if resource.accuracy is not None else ""
    resource.detail = f"已完成 {progress.completed} / {progress.total} 题{accuracy_text}"
    db.commit()


def _ensure_attempt_side_effects(
    db: Session,
    *,
    student: User,
    question: Question,
    revision: QuestionSetRevision,
    question_set: QuestionSet,
    attempt: Attempt,
    score: Score,
) -> None:
    concept_ids = _question_concept_ids(db, question.id)
    answer_hash = sha256(stable_json(attempt.answer_json).encode("utf-8")).hexdigest()
    _emit_event(
        db,
        student=student,
        course_id=question_set.course_id,
        idempotency_key=f"a3:answer-submitted:{attempt.id}",
        event_type="answer_submitted",
        object_type="attempt",
        object_id=attempt.id,
        concept_ids=concept_ids,
        difficulty=question.difficulty_prior,
        hint_level=attempt.hint_level,
        attempt_no=attempt.attempt_no,
        payload={
            "question_id": question.id,
            "revision_id": revision.id,
            "answer_hash": answer_hash,
        },
    )
    if attempt.attempt_no > 1:
        _emit_event(
            db,
            student=student,
            course_id=question_set.course_id,
            idempotency_key=f"a3:question-retried:{attempt.id}",
            event_type="question_retried",
            object_type="attempt",
            object_id=attempt.id,
            concept_ids=concept_ids,
            difficulty=question.difficulty_prior,
            hint_level=attempt.hint_level,
            attempt_no=attempt.attempt_no,
            payload={
                "question_id": question.id,
                "revision_id": revision.id,
                "previous_attempt_count": attempt.attempt_no - 1,
            },
        )
    _emit_event(
        db,
        student=student,
        course_id=question_set.course_id,
        idempotency_key=f"a3:answer-scored:{attempt.id}",
        event_type="answer_scored",
        object_type="score",
        object_id=score.id,
        concept_ids=concept_ids,
        outcome=score.score,
        difficulty=question.difficulty_prior,
        hint_level=attempt.hint_level,
        attempt_no=attempt.attempt_no,
        upstream_confidence=score.confidence,
        payload={
            "question_id": question.id,
            "attempt_id": attempt.id,
            "grading_mode": score.grading_mode,
            "review_status": score.review_status,
        },
    )
    progress = _progress_data(
        db,
        student_id=student.id,
        question_set=question_set,
        revision=revision,
    )
    _sync_resource_projection(db, question_set=question_set, progress=progress)
    if progress.total > 0 and progress.completed == progress.total:
        all_concepts = list(db.scalars(
            select(QuestionConcept.concept_id)
            .join(Question, Question.id == QuestionConcept.question_id)
            .where(Question.revision_id == revision.id)
        ).all())
        _emit_event(
            db,
            student=student,
            course_id=question_set.course_id,
            idempotency_key=f"a3:question-set-completed:{question_set.id}:{revision.id}",
            event_type="question_set_completed",
            object_type="question_set",
            object_id=question_set.id,
            concept_ids=all_concepts,
            completion=1.0,
            payload={
                "revision_id": revision.id,
                "completed": progress.completed,
                "total": progress.total,
                "aggregate_score": progress.average_score,
            },
        )


def submit_attempt(
    db: Session,
    *,
    student: User,
    question_id: str,
    payload: AttemptSubmitRequest,
) -> PracticeAttemptResultView:
    question, revision, question_set = _question_access(db, student, question_id)
    if payload.expected_revision_id != revision.id:
        raise _failure(
            409,
            "QUESTION_REVISION_CONFLICT",
            "题组修订已变化，请重新打开后作答",
            expected_revision_id=payload.expected_revision_id,
            actual_revision_id=revision.id,
        )
    existing = db.scalar(select(Attempt).where(
        Attempt.student_id == student.id,
        Attempt.question_id == question.id,
        Attempt.idempotency_key == payload.idempotency_key,
    ))
    if existing is not None:
        if existing.revision_id != revision.id or stable_json(existing.answer_json) != stable_json(payload.answer):
            raise _failure(409, "ATTEMPT_IDEMPOTENCY_CONFLICT", "同一幂等键已用于不同的作答内容")
        existing_score = db.scalar(select(Score).where(Score.attempt_id == existing.id))
        if existing_score is None:
            raise _failure(503, "ATTEMPT_SCORE_RECOVERY_REQUIRED", "作答已保存但评分记录缺失，请联系管理员恢复")
        _ensure_attempt_side_effects(
            db,
            student=student,
            question=question,
            revision=revision,
            question_set=question_set,
            attempt=existing,
            score=existing_score,
        )
        return _attempt_result(db, existing)
    try:
        grading = _grade_question(db, question, payload.answer)
    except ValueError as error:
        raise _failure(422, "ATTEMPT_ANSWER_INVALID", str(error)) from error
    viewed = _hint_events(
        db,
        student_id=student.id,
        course_id=question_set.course_id,
        question_ids=[question.id],
    ).get(question.id, {})
    latest_number = db.scalar(select(func.max(Attempt.attempt_no)).where(
        Attempt.student_id == student.id,
        Attempt.question_id == question.id,
    )) or 0
    attempt = Attempt(
        id=str(uuid4()),
        student_id=student.id,
        course_id=question_set.course_id,
        question_set_id=question_set.id,
        revision_id=revision.id,
        question_id=question.id,
        attempt_no=int(latest_number) + 1,
        idempotency_key=payload.idempotency_key,
        answer_json=payload.answer,
        hint_level=max(viewed, default=0),
        status="graded" if grading.review_status == "graded" else "needs_review",
    )
    db.add(attempt)
    db.flush()
    score = Score(
        id=str(uuid4()),
        attempt_id=attempt.id,
        score=grading.score,
        is_correct=grading.is_correct,
        confidence=grading.confidence,
        grading_mode=grading.grading_mode,
        review_status=grading.review_status,
        feedback_json=grading.feedback,
        grader_model_run_id=None,
    )
    db.add(score)
    db.add(AuditEvent(
        id=str(uuid4()),
        actor_id=student.id,
        action="practice.attempt.submitted",
        object_type="attempt",
        object_id=attempt.id,
        course_id=question_set.course_id,
        outcome="success",
        metadata_json={
            "question_id": question.id,
            "revision_id": revision.id,
            "attempt_no": attempt.attempt_no,
            "grading_mode": grading.grading_mode,
            "review_status": grading.review_status,
        },
    ))
    db.commit()
    _ensure_attempt_side_effects(
        db,
        student=student,
        question=question,
        revision=revision,
        question_set=question_set,
        attempt=attempt,
        score=score,
    )
    return _attempt_result(db, attempt)


def attempt_score(
    db: Session,
    *,
    student: User,
    attempt_id: str,
) -> PracticeScoreView:
    attempt = db.get(Attempt, attempt_id)
    if attempt is None or attempt.student_id != student.id:
        raise _failure(404, "ATTEMPT_NOT_FOUND", "作答不存在或无权访问")
    _authorize_course(db, student, attempt.course_id)
    score = db.scalar(select(Score).where(Score.attempt_id == attempt.id))
    if score is None:
        raise _failure(404, "SCORE_NOT_FOUND", "该作答尚未产生评分")
    return _score_view(score)


def review_attempt_score(
    db: Session,
    *,
    teacher: User,
    attempt_id: str,
    payload: ReviewScoreRequest,
) -> PracticeScoreView:
    """Finalize a low-confidence subjective score with teacher adjudication."""
    attempt = db.get(Attempt, attempt_id)
    if attempt is None:
        raise _failure(404, "ATTEMPT_NOT_FOUND", "浣滅瓟涓嶅瓨鍦ㄦ垨鏃犳潈璁块棶")
    if CourseRepository(db).get_teacher_course(teacher.id, attempt.course_id) is None:
        raise _failure(404, "ATTEMPT_NOT_FOUND", "浣滅瓟涓嶅瓨鍦ㄦ垨鏃犳潈璁块棶")
    question_set = db.get(QuestionSet, attempt.question_set_id)
    question = db.get(Question, attempt.question_id)
    score = db.scalar(select(Score).where(Score.attempt_id == attempt.id))
    if question_set is None or question is None or score is None:
        raise _failure(404, "SCORE_NOT_FOUND", "璇ヤ綔绛斿皻鏈骇鐢熻瘎鍒?")
    # Student-owned private sets must never become teacher-visible through a
    # guessed attempt id, even when the student is enrolled in the same course.
    if question_set.owner_student_id is not None or question_set.course_id != attempt.course_id:
        raise _failure(404, "ATTEMPT_NOT_FOUND", "浣滅瓟涓嶅瓨鍦ㄦ垨鏃犳潈璁块棶")
    if score.review_status == "reviewed":
        existing_feedback = score.feedback_json or {}
        if (
            score.score == payload.score
            and score.is_correct == payload.is_correct
            and existing_feedback.get("teacher_review", {}) == payload.feedback
            and existing_feedback.get("teacher_review_note", "") == payload.review_note
        ):
            return _score_view(score)
        raise _failure(409, "SCORE_ALREADY_REVIEWED", "璇勫垎宸插畬鎴愭暀甯堝鏍革紝涓嶈兘閲嶅瑕嗙洊")
    if score.review_status != "needs_review":
        raise _failure(409, "SCORE_REVIEW_NOT_REQUIRED", "璇ヤ綔绛斾笉闇€瑕佹暀甯堝鏍革紒")

    feedback = dict(payload.feedback)
    feedback["teacher_review"] = dict(payload.feedback)
    if payload.review_note:
        feedback["teacher_review_note"] = payload.review_note
    score.score = payload.score
    score.is_correct = payload.is_correct
    score.confidence = 1.0
    score.grading_mode = "teacher_review"
    score.review_status = "reviewed"
    score.feedback_json = feedback
    score.reviewed_by = teacher.id
    score.reviewed_at = _now()
    score.graded_at = _now()
    attempt.status = "graded"
    db.add(AuditEvent(
        id=str(uuid4()),
        actor_id=teacher.id,
        action="practice.attempt.reviewed",
        object_type="score",
        object_id=score.id,
        course_id=attempt.course_id,
        outcome="success",
        metadata_json={
            "attempt_id": attempt.id,
            "question_id": attempt.question_id,
            "review_status": "reviewed",
            "review_note_present": bool(payload.review_note),
        },
    ))
    db.commit()

    # Replace the provisional trajectory contribution with the adjudicated one.
    student = db.get(User, attempt.student_id)
    original_event = db.scalar(select(LearningEvent).where(
        LearningEvent.student_id == attempt.student_id,
        LearningEvent.course_id == attempt.course_id,
        LearningEvent.idempotency_key == f"a3:answer-scored:{attempt.id}",
    ))
    if student is not None:
        _emit_event(
            db,
            student=student,
            course_id=attempt.course_id,
            idempotency_key=f"a3:answer-reviewed:{attempt.id}",
            event_type="answer_scored",
            object_type="score",
            object_id=score.id,
            concept_ids=_question_concept_ids(db, question.id),
            outcome=score.score,
            difficulty=question.difficulty_prior,
            hint_level=attempt.hint_level,
            attempt_no=attempt.attempt_no,
            upstream_confidence=1.0,
            correction_of_event_id=original_event.id if original_event is not None else None,
            payload={
                "question_id": question.id,
                "attempt_id": attempt.id,
                "grading_mode": "teacher_review",
                "review_status": "reviewed",
            },
        )
        revision = db.get(QuestionSetRevision, attempt.revision_id)
        if revision is not None:
            progress = _progress_data(
                db,
                student_id=student.id,
                question_set=question_set,
                revision=revision,
            )
            _sync_resource_projection(db, question_set=question_set, progress=progress)
    return _score_view(score)
