from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from .dependencies import CurrentUser, DbSession, StudentUser, TeacherUser
from .domains.model_gateway.service import GatewayFailure
from .domains.practice.blueprint import compile_blueprint
from .domains.practice.schemas import (
    AttemptSubmitRequest,
    CompileBlueprintRequest,
    GenerateQuestionSetRequest,
    HintRevealRequest,
    PracticeAttemptResultView,
    PracticeBlueprintView,
    PracticeScoreView,
    QuestionSetDetailView,
    QuestionSetListView,
    QuestionSetProgressView,
    RevealedHintView,
    ReviewScoreRequest,
    RevisionVersionRequest,
    UpdateQuestionRequest,
)
from .domains.practice.service import (
    attempt_score,
    blueprint_view,
    generate_question_set,
    list_question_sets,
    publish_teacher_question_set,
    question_set_detail,
    question_set_progress,
    reveal_hint,
    review_attempt_score,
    submit_attempt,
    update_teacher_question,
    validate_teacher_question_set,
)


router = APIRouter(prefix="/api/v1")


@router.get(
    "/student/courses/{course_id}/question-sets",
    response_model=QuestionSetListView,
    response_model_exclude_none=True,
)
def student_question_sets(course_id: str, user: StudentUser, db: DbSession):
    return list_question_sets(db, actor=user, course_id=course_id)


@router.get(
    "/teacher/courses/{course_id}/question-sets",
    response_model=QuestionSetListView,
    response_model_exclude_none=True,
)
def teacher_question_sets(course_id: str, user: TeacherUser, db: DbSession):
    return list_question_sets(db, actor=user, course_id=course_id)


@router.get(
    "/question-sets/{set_id}",
    response_model=QuestionSetDetailView,
    response_model_exclude_none=True,
)
def get_question_set(set_id: str, user: CurrentUser, db: DbSession):
    return question_set_detail(db, actor=user, set_id=set_id)


@router.post(
    "/courses/{course_id}/practice-blueprints:compile",
    response_model=PracticeBlueprintView,
    status_code=status.HTTP_201_CREATED,
)
def compile_practice_blueprint(
    course_id: str,
    payload: CompileBlueprintRequest,
    user: CurrentUser,
    db: DbSession,
):
    blueprint = compile_blueprint(db, actor=user, course_id=course_id, payload=payload)
    return blueprint_view(db, blueprint)


@router.post(
    "/courses/{course_id}/question-sets:generate",
    response_model=QuestionSetDetailView,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
def generate_practice_question_set(
    course_id: str,
    payload: GenerateQuestionSetRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
):
    try:
        return generate_question_set(
            db,
            settings=request.app.state.settings,
            adapter_registry=request.app.state.model_adapter_registry,
            actor=user,
            course_id=course_id,
            payload=payload,
        )
    except GatewayFailure as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": exc.code,
                "message": exc.safe_message,
                "model_run_id": exc.run_id,
            },
        ) from exc


@router.patch(
    "/teacher/questions/{question_id}",
    response_model=QuestionSetDetailView,
    response_model_exclude_none=True,
)
def patch_teacher_question(
    question_id: str,
    payload: UpdateQuestionRequest,
    user: TeacherUser,
    db: DbSession,
):
    return update_teacher_question(
        db,
        teacher=user,
        question_id=question_id,
        payload=payload,
    )


@router.post(
    "/teacher/question-sets/{set_id}:validate",
    response_model=QuestionSetDetailView,
    response_model_exclude_none=True,
)
def validate_teacher_set(
    set_id: str,
    payload: RevisionVersionRequest,
    user: TeacherUser,
    db: DbSession,
):
    return validate_teacher_question_set(
        db,
        teacher=user,
        set_id=set_id,
        payload=payload,
    )


@router.post(
    "/teacher/question-sets/{set_id}:publish",
    response_model=QuestionSetDetailView,
    response_model_exclude_none=True,
)
def publish_teacher_set(
    set_id: str,
    payload: RevisionVersionRequest,
    user: TeacherUser,
    db: DbSession,
):
    return publish_teacher_question_set(
        db,
        teacher=user,
        set_id=set_id,
        payload=payload,
    )


@router.post(
    "/student/questions/{question_id}/hints/{level}:reveal",
    response_model=RevealedHintView,
)
def reveal_student_hint(
    question_id: str,
    level: int,
    payload: HintRevealRequest,
    user: StudentUser,
    db: DbSession,
):
    return reveal_hint(
        db,
        student=user,
        question_id=question_id,
        level=level,
        payload=payload,
    )


@router.post(
    "/student/questions/{question_id}/attempts",
    response_model=PracticeAttemptResultView,
)
def submit_student_attempt(
    question_id: str,
    payload: AttemptSubmitRequest,
    user: StudentUser,
    db: DbSession,
):
    return submit_attempt(
        db,
        student=user,
        question_id=question_id,
        payload=payload,
    )


@router.get(
    "/student/question-sets/{set_id}/progress",
    response_model=QuestionSetProgressView,
)
def get_student_question_set_progress(
    set_id: str,
    user: StudentUser,
    db: DbSession,
):
    return question_set_progress(db, student=user, set_id=set_id)


@router.get(
    "/student/attempts/{attempt_id}/score",
    response_model=PracticeScoreView,
)
def get_student_attempt_score(
    attempt_id: str,
    user: StudentUser,
    db: DbSession,
):
    return attempt_score(db, student=user, attempt_id=attempt_id)


@router.post(
    "/teacher/attempts/{attempt_id}:review",
    response_model=PracticeScoreView,
)
@router.post(
    "/teacher/attempts/{attempt_id}/review",
    response_model=PracticeScoreView,
    include_in_schema=False,
)
def review_teacher_attempt(
    attempt_id: str,
    payload: ReviewScoreRequest,
    user: TeacherUser,
    db: DbSession,
):
    return review_attempt_score(
        db,
        teacher=user,
        attempt_id=attempt_id,
        payload=payload,
    )
