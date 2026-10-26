from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..model_gateway.schemas import ModelRunView


QuestionType = Literal["single", "multiple", "judgment", "fill", "short", "scenario"]
SourceMethod = Literal["history", "recorded", "graph", "alignment"]
DifficultyMode = Literal["personalized", "basic", "standard", "balanced", "challenge"]
QUESTION_TYPES: tuple[str, ...] = ("single", "multiple", "judgment", "fill", "short", "scenario")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class QuestionTypeCounts(StrictModel):
    single: int = Field(default=0, ge=0, le=120)
    multiple: int = Field(default=0, ge=0, le=120)
    judgment: int = Field(default=0, ge=0, le=120)
    fill: int = Field(default=0, ge=0, le=120)
    short: int = Field(default=0, ge=0, le=120)
    scenario: int = Field(default=0, ge=0, le=120)

    @property
    def total(self) -> int:
        return sum(int(getattr(self, item)) for item in QUESTION_TYPES)


class BlueprintConceptRequest(StrictModel):
    concept_id: str = Field(min_length=1, max_length=80)
    counts: QuestionTypeCounts


class CompileBlueprintRequest(StrictModel):
    source_method: SourceMethod
    difficulty_mode: DifficultyMode
    graph_id: str | None = Field(default=None, max_length=80)
    alignment_run_id: str | None = Field(default=None, max_length=36)
    requested_profile_id: str | None = Field(default=None, max_length=80)
    concepts: list[BlueprintConceptRequest] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_source_and_counts(self) -> "CompileBlueprintRequest":
        concept_ids = [item.concept_id for item in self.concepts]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("蓝图中的知识点不能重复")
        if self.source_method == "graph" and not self.graph_id:
            raise ValueError("图谱来源必须指定graph_id")
        if self.source_method != "graph" and self.graph_id is not None:
            raise ValueError("仅图谱来源可以指定graph_id")
        if self.source_method == "alignment" and not self.alignment_run_id:
            raise ValueError("材料对齐来源必须指定alignment_run_id")
        if self.source_method != "alignment" and self.alignment_run_id is not None:
            raise ValueError("仅材料对齐来源可以指定alignment_run_id")
        total = sum(item.counts.total for item in self.concepts)
        if total <= 0:
            raise ValueError("蓝图总题数必须大于0")
        if total > 120:
            raise ValueError("单个题组最多120题")
        return self


class GenerateQuestionSetRequest(StrictModel):
    blueprint_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=240)
    requested_profile_id: str = Field(min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("题组名称不能为空")
        return normalized


class RevisionVersionRequest(StrictModel):
    expected_revision_version: int = Field(ge=1)


class TeacherQuestionOptionInput(StrictModel):
    id: str | None = Field(default=None, min_length=1, max_length=36)
    content: str = Field(min_length=1, max_length=2000)
    is_correct: bool = False


class UpdateQuestionRequest(RevisionVersionRequest):
    prompt: str = Field(min_length=1, max_length=8000)
    options: list[TeacherQuestionOptionInput] = Field(default_factory=list, max_length=12)
    answer_spec: dict[str, Any]
    rubric: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    explanation: str = Field(default="", max_length=8000)
    cognitive_level: Literal["remember", "understand", "apply", "analyze", "evaluate"]
    difficulty_prior: float = Field(ge=0.0, le=1.0)


class HintRevealRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


class AttemptSubmitRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=160)
    answer: dict[str, Any]
    expected_revision_id: str = Field(min_length=1, max_length=36)


class ReviewScoreRequest(StrictModel):
    """Teacher adjudication payload for a low-confidence subjective score."""

    score: float = Field(ge=0.0, le=1.0)
    is_correct: bool | None = None
    feedback: dict[str, Any] = Field(default_factory=dict)
    review_note: str = Field(default="", max_length=2000)


class GeneratedOption(StrictModel):
    content: str = Field(min_length=1, max_length=2000)
    is_correct: bool
    misconception_code: str | None = Field(default=None, max_length=80)


class GeneratedRubricItem(StrictModel):
    criterion: str = Field(min_length=1, max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    accepted_patterns: list[str] = Field(default_factory=list, max_length=30)
    weight: float = Field(gt=0.0, le=1.0)


class GeneratedQuestionBase(StrictModel):
    blueprint_cell_id: str = Field(min_length=1, max_length=36)
    question_type: QuestionType
    prompt: str = Field(min_length=2, max_length=8000)
    explanation: str = Field(min_length=1, max_length=8000)
    cognitive_level: Literal["remember", "understand", "apply", "analyze", "evaluate"]
    difficulty_prior: float = Field(ge=0.0, le=1.0)
    hints: list[str] = Field(min_length=3, max_length=3)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("hints")
    @classmethod
    def validate_hints(cls, values: list[str]) -> list[str]:
        normalized = [" ".join(item.split()) for item in values]
        if any(len(item) < 2 for item in normalized):
            raise ValueError("三级提示均不能为空")
        return normalized

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence_ids(cls, values: list[str]) -> list[str]:
        if any(not item.strip() for item in values):
            raise ValueError("evidence_ids不能包含空值")
        if len(values) != len(set(values)):
            raise ValueError("evidence_ids不能重复")
        return values


class GeneratedObjectiveQuestion(GeneratedQuestionBase):
    question_type: Literal["single", "multiple", "judgment"]
    options: list[GeneratedOption] = Field(min_length=2, max_length=12)

    @model_validator(mode="after")
    def validate_objective_shape(self) -> "GeneratedObjectiveQuestion":
        contents = [" ".join(item.content.split()) for item in self.options]
        if len(contents) != len(set(contents)):
            raise ValueError("同一题的选项正文不能重复")
        correct_count = sum(item.is_correct for item in self.options)
        if self.question_type == "single":
            if len(self.options) < 3 or correct_count != 1:
                raise ValueError("单选题至少需要三个选项且必须恰有一个正确选项")
        elif self.question_type == "multiple":
            if len(self.options) < 4 or correct_count < 2 or correct_count >= len(self.options):
                raise ValueError("多选题至少需要四个选项、两个正确项和一个错误项")
        else:
            if len(self.options) != 2 or set(contents) != {"正确", "错误"} or correct_count != 1:
                raise ValueError("判断题必须包含正确、错误两个选项且恰有一个正确项")
        return self


class GeneratedFillQuestion(GeneratedQuestionBase):
    question_type: Literal["fill"]
    accepted_texts: list[str] = Field(min_length=1, max_length=20)
    numeric_answer: float | None = None
    absolute_tolerance: float = Field(default=0.0, ge=0.0)
    relative_tolerance: float = Field(default=0.0, ge=0.0)

    @field_validator("accepted_texts")
    @classmethod
    def validate_accepted_texts(cls, values: list[str]) -> list[str]:
        normalized = [" ".join(item.split()) for item in values]
        if any(not item for item in normalized):
            raise ValueError("可接受答案不能为空")
        if len(normalized) != len(set(normalized)):
            raise ValueError("可接受答案不能重复")
        return normalized


class GeneratedSubjectiveQuestion(GeneratedQuestionBase):
    question_type: Literal["short", "scenario"]
    reference_answer: str = Field(min_length=1, max_length=8000)
    rubric: list[GeneratedRubricItem] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_rubric_weights(self) -> "GeneratedSubjectiveQuestion":
        if not math.isclose(sum(item.weight for item in self.rubric), 1.0, abs_tol=1e-6):
            raise ValueError("主观题量规权重之和必须为1")
        return self


GeneratedQuestion = Annotated[
    GeneratedObjectiveQuestion | GeneratedFillQuestion | GeneratedSubjectiveQuestion,
    Field(discriminator="question_type"),
]


class QuestionGenerationOutput(StrictModel):
    questions: list[GeneratedQuestion] = Field(min_length=1, max_length=120)


class QuestionConceptView(StrictModel):
    concept_id: str
    label: str
    weight: float | None = None


class QuestionOptionView(StrictModel):
    id: str
    position: int
    content: str
    is_correct: bool | None = None


class PracticeScoreView(StrictModel):
    attempt_id: str
    score: float
    is_correct: bool | None
    confidence: float
    grading_mode: str
    review_status: str
    feedback: dict[str, Any]
    graded_at: datetime


class RevealedHintView(StrictModel):
    question_id: str
    level: int
    content: str
    revealed_at: datetime | None = None


class QuestionAttemptStateView(StrictModel):
    attempt_id: str | None
    attempt_no: int
    answer: dict[str, Any] | None
    hint_level: int
    status: str
    submitted_at: datetime | None
    score: PracticeScoreView | None
    revealed_hints: list[RevealedHintView] = Field(default_factory=list)


class PracticeQuestionView(StrictModel):
    id: str
    position: int
    type: QuestionType
    prompt: str
    options: list[QuestionOptionView]
    concepts: list[QuestionConceptView]
    hints_available: int
    attempt_state: QuestionAttemptStateView | None
    answer_spec: dict[str, Any] | None = None
    rubric: list[dict[str, Any]] | None = None
    explanation: str | None = None
    cognitive_level: str | None = None
    difficulty_prior: float | None = None


class QuestionSetSummaryView(StrictModel):
    id: str
    title: str
    status: str
    visibility: str
    revision_id: str
    revision_no: int
    revision_version: int
    total: int
    completed: int
    average_score: float | None
    concepts: list[QuestionConceptView]
    source_kind: str
    model_run: ModelRunView | None = None


class QuestionSetDetailView(QuestionSetSummaryView):
    course_id: str
    quality_status: str
    source_summary: str
    questions: list[PracticeQuestionView]


class QuestionSetListView(StrictModel):
    items: list[QuestionSetSummaryView]


class BlueprintCellView(StrictModel):
    concept_id: str
    concept_label: str
    question_type: QuestionType
    count: int
    difficulty_target: float
    cognitive_level: str
    position: int


class PracticeBlueprintView(StrictModel):
    id: str
    version: int
    total: int
    cells: list[BlueprintCellView]
    source_summary: dict[str, Any]


class PracticeAttemptView(StrictModel):
    id: str
    question_id: str
    question_set_id: str
    revision_id: str
    attempt_no: int
    answer: dict[str, Any]
    hint_level: int
    status: str
    submitted_at: datetime


class PracticeAttemptResultView(StrictModel):
    attempt: PracticeAttemptView
    score: PracticeScoreView | None


class QuestionProgressItemView(StrictModel):
    question_id: str
    position: int
    completed: bool
    hint_level: int
    attempt_id: str | None
    score: float | None
    review_status: str | None


class QuestionSetProgressView(StrictModel):
    question_set_id: str
    revision_id: str
    total: int
    completed: int
    average_score: float | None
    items: list[QuestionProgressItemView]


# Backward-compatible names retained for the deterministic helper modules.
MutationGuard = RevisionVersionRequest
RevealHintRequest = HintRevealRequest
SubmitAttemptRequest = AttemptSubmitRequest
ConceptRef = QuestionConceptView
OptionView = QuestionOptionView
ScoreView = PracticeScoreView
AttemptStateView = QuestionAttemptStateView
QuestionView = PracticeQuestionView
BlueprintView = PracticeBlueprintView
AttemptView = PracticeAttemptView
AttemptResultView = PracticeAttemptResultView
ProgressItemView = QuestionProgressItemView
ProgressView = QuestionSetProgressView
GeneratedQuestionSet = QuestionGenerationOutput
