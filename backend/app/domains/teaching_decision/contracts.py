from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ConceptState = Literal["weak", "mastered", "unseen"]
ResourceType = Literal["graph", "question_set", "video"]
AudienceMode = Literal["class", "concept_directed", "single"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SnapshotRefresh(StrictModel):
    as_of: datetime | None = None


class AttentionComponents(StrictModel):
    accuracy_samples: int | None = None
    practice_count: int
    accuracy: float
    resource_completion: float
    effective_tutoring_count: int
    practice_score: float
    accuracy_score: float
    resource_score: float
    tutoring_score: float


class StudentAttentionView(StrictModel):
    student_id: str
    student_name: str
    initials: str
    rank: int
    score: float
    confidence: float
    components: AttentionComponents
    last_activity_at: datetime | None
    priority: bool


class DecisionSnapshotView(StrictModel):
    snapshot_id: str
    course_id: str
    as_of: datetime
    snapshot_hash: str
    student_count: int
    aggregate: dict
    algorithm_version: str
    priority_students: list[StudentAttentionView]
    created_at: datetime


class StudentListView(StrictModel):
    snapshot_id: str
    snapshot_hash: str
    page: int
    page_size: int
    total: int
    items: list[StudentAttentionView]


class ConceptLearningStateView(StrictModel):
    concept_id: str
    label: str
    state: ConceptState
    mastery: float
    accuracy: float
    evidence_count: int
    confidence: float
    low_evidence: bool
    trend_30d: float
    last_evidence_at: datetime | None


class StudentLearningStateView(StrictModel):
    snapshot_id: str
    course_id: str
    student_id: str
    student_name: str
    rank: int
    score: float
    confidence: float
    components: AttentionComponents
    concepts: list[ConceptLearningStateView]
    weak_concept_ids: list[str]
    privacy_boundary: str


class AudienceDraftCreate(StrictModel):
    resource_type: ResourceType
    resource_id: str = Field(min_length=1, max_length=80)
    resource_version: int | None = Field(default=None, ge=1)
    audience_mode: AudienceMode
    selected_concept_ids: list[str] = Field(default_factory=list, max_length=30)
    selected_states: list[ConceptState] = Field(default_factory=list, max_length=3)
    teacher_selected_student_ids: list[str] = Field(default_factory=list, max_length=500)
    locked_student_id: str | None = Field(default=None, max_length=36)

    @field_validator(
        "selected_concept_ids", "selected_states", "teacher_selected_student_ids"
    )
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("列表值不能重复")
        return value

    @model_validator(mode="after")
    def valid_mode(self) -> "AudienceDraftCreate":
        if self.audience_mode == "class":
            if self.locked_student_id or self.teacher_selected_student_ids:
                raise ValueError("全班发布不能锁定或手动指定学生")
        elif self.audience_mode == "concept_directed":
            if not self.selected_concept_ids or not self.selected_states:
                raise ValueError("定向发布必须选择知识点和学习状态")
            if self.locked_student_id:
                raise ValueError("定向发布不能使用单人锁定字段")
        else:
            if not self.locked_student_id:
                raise ValueError("单人发布必须提供锁定学生")
            if self.teacher_selected_student_ids:
                raise ValueError("单人发布不能覆盖接收者")
        return self


class AudienceCandidateView(StrictModel):
    student_id: str
    student_name: str
    suggested: bool
    selected: bool
    override_action: str | None
    matched_concept_ids: list[str]
    matched_states: list[ConceptState]
    reason_codes: list[str]
    warnings: list[dict]


class AudienceDraftView(StrictModel):
    id: str
    course_id: str
    resource: dict
    audience_mode: AudienceMode
    selected_concept_ids: list[str]
    selected_states: list[ConceptState]
    suggested_student_ids: list[str]
    final_student_ids: list[str]
    candidates: list[AudienceCandidateView]
    status: str
    snapshot_hash: str
    version: int
    expires_at: datetime
    warnings_require_confirmation: bool


class PublicationCreate(StrictModel):
    draft_version: int = Field(ge=1)
    acknowledge_warnings: bool = False


class PublicationView(StrictModel):
    id: str
    draft_id: str
    course_id: str
    resource: dict
    audience_mode: AudienceMode
    recipient_count: int
    status: str
    snapshot_hash: str
    algorithm_version: str
    published_at: datetime
    withdrawn_at: datetime | None


class ResourceInboxItem(StrictModel):
    exposure_id: str
    publication_id: str
    course_id: str
    resource_type: ResourceType
    resource: dict
    personalized: bool
    delivery_status: str
    delivered_at: datetime
    opened_at: datetime | None
    completed_at: datetime | None


class ExposureEventCreate(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    occurred_at: datetime


class PersonalizedJobCreate(StrictModel):
    resource_type: ResourceType
    concept_ids: list[str] = Field(min_length=1, max_length=12)
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    request_payload: dict = Field(default_factory=dict)

    @field_validator("concept_ids")
    @classmethod
    def unique_concepts(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("知识点不能重复")
        return value


class PersonalizedJobView(StrictModel):
    id: str
    student_id: str
    course_id: str
    resource_type: ResourceType
    concept_ids: list[str]
    upstream_job_id: str
    upstream_status: dict
    status: str
    created_at: datetime
    updated_at: datetime
