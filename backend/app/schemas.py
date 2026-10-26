from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Role = Literal["student", "teacher"]


class UserView(BaseModel):
    id: str
    email: str
    role: Role
    name: str
    initials: str
    profile_title: str

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    account: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=6, max_length=256)
    role: Role


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserView


class CourseListItem(BaseModel):
    id: str
    code: str
    title: str
    short_title: str
    term: str
    accent: str
    teacher: str
    mastery: float | None = None
    progress: float | None = None
    weekly_minutes: int | None = None
    streak_days: int | None = None
    goal: str | None = None
    focus: str | None = None


class CrossCourseSummary(BaseModel):
    active_courses: int
    weekly_minutes: int
    pending_resources: int
    overall_mastery: float
    mastery_delta: float
    strong_topics: list[str]
    weak_topics: list[str]
    daily_minutes: list[int]
    daily_average: int
    peak_day: str
    streak_days: int
    resource_completion: float
    preferred_pattern: str


class TrendMetric(BaseModel):
    value: float
    delta: str
    trend: list[int]


class KnowledgeStateView(BaseModel):
    concept_id: str
    label: str
    mastery: float
    correct_rate: float
    evidence_count: int
    confidence: float
    state: Literal["weak", "mastered", "unseen"]
    uncertainty: float = 0.0
    effective_evidence: float = 0.0
    trend_30d: float = 0.0
    last_evidence_at: datetime | None = None
    top_evidence: list[str] = Field(default_factory=list)
    model_version: str = "eglt-0.1.0"


class ResourceView(BaseModel):
    id: str
    resource_type: Literal["knowledge_graph", "question_set", "learning_video"]
    title: str
    detail: str
    progress_completed: int | None
    progress_total: int | None
    accuracy: float | None


class ActivityView(BaseModel):
    id: str
    title: str
    detail: str
    activity_type: Literal["result", "learn", "practice"]
    occurred_at: datetime


class StudentCourseOverview(BaseModel):
    course: CourseListItem
    focus_summary: str
    mastery: TrendMetric
    resource_completion: TrendMetric
    recent_accuracy: TrendMetric
    streak: TrendMetric
    weekly_activity: list[int]
    daily_average: int
    efficient_sessions: int
    knowledge_states: list[KnowledgeStateView]
    recent_resources: list[ResourceView]
    recent_activities: list[ActivityView]


class TeacherCourseOverview(BaseModel):
    course: CourseListItem
    class_name: str
    student_count: int
    average_mastery: float
    average_accuracy: float
    resource_completion: float
    priority_student_count: int


class ModelProfileView(BaseModel):
    id: str
    display_name: str
    task_kinds: list[str]
    config_revision: str
    capabilities: list[str] = Field(default_factory=list)
    available: bool = False
    unavailable_reason: str | None = None


class ModelRunContract(BaseModel):
    model_run_id: str
    task_kind: str
    requested_profile_id: str
    actual_profile_id: str | None
    provider_model_id: str | None
    task_policy_version: str
    fallback_reason: str | None
    status: Literal["queued", "running", "validated", "rejected", "failed"]


class EventConceptInput(BaseModel):
    concept_id: str = Field(min_length=3, max_length=80)
    weight: float = Field(gt=0, le=1)


class LearningEventCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)
    event_type: Literal[
        "resource_opened", "graph_node_viewed", "knowledge_card_opened",
        "video_started", "video_progressed", "video_completed",
        "question_generated", "hint_viewed", "answer_submitted", "answer_scored",
        "question_set_completed", "question_retried",
        "conversation_started", "tutor_message_received", "inline_practice_scored",
        "experience_confirmed", "resource_completed",
    ]
    object_type: str = Field(min_length=1, max_length=80)
    object_id: str = Field(min_length=1, max_length=120)
    concepts: list[EventConceptInput] = Field(min_length=1, max_length=10)
    outcome: float | None = Field(default=None, ge=0, le=1)
    difficulty: float | None = Field(default=None, ge=0, le=1)
    hint_level: int | None = Field(default=None, ge=0, le=3)
    attempt_no: int | None = Field(default=None, ge=1, le=100)
    completion: float | None = Field(default=None, ge=0, le=1)
    strategy: str | None = Field(default=None, max_length=40)
    upstream_confidence: float = Field(default=1, ge=0, le=1)
    alignment_confidence: float = Field(default=1, ge=0, le=1)
    occurred_at: datetime
    correction_of_event_id: str | None = None
    payload: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event_semantics(self):
        if self.event_type == "answer_scored" and self.outcome is None:
            raise ValueError("answer_scored必须包含outcome")
        if len({item.concept_id for item in self.concepts}) != len(self.concepts):
            raise ValueError("concepts不能包含重复知识点")
        return self


class StateChangeView(BaseModel):
    concept_id: str
    mastery: float
    uncertainty: float
    effective_evidence: float
    status: Literal["weak", "mastered", "unseen"]
    delta: float
    model_version: str


class TrajectoryUpdateResponse(BaseModel):
    event_id: str
    duplicate: bool
    processing_status: Literal["accepted", "observed_only", "awaiting_alignment_review", "rejected"]
    evidence_success: float | None
    evidence_reliability: float | None
    evidence_reason: str
    changes: list[StateChangeView]


GraphNodeType = Literal["foundation", "core", "application"]
GraphRelation = Literal["prerequisite", "contains", "application", "contrast"]


class GraphNodeView(BaseModel):
    id: str
    concept_id: str
    label: str
    node_type: GraphNodeType
    definition: str
    key_point: str
    misconception: str
    origin: str
    confidence: float
    position_x: float
    position_y: float
    evidence_count: int = 0
    mastery: float | None = None
    mastery_state: Literal["weak", "mastered", "unseen"] | None = None


class GraphEdgeView(BaseModel):
    id: str
    from_node_id: str
    to_node_id: str
    relation: GraphRelation
    origin: str
    confidence: float
    evidence_count: int = 0


class GraphQualityView(BaseModel):
    hard_pass: bool
    quality_score: float
    metrics: dict
    issues: list[dict]
    validator_version: str
    created_at: datetime


class GraphListItem(BaseModel):
    id: str
    course_id: str
    title: str
    status: Literal["draft", "published"]
    working_revision_id: str | None
    published_revision_id: str | None
    revision_no: int | None
    node_count: int
    edge_count: int
    updated_at: datetime


class GraphDetailView(BaseModel):
    id: str
    course_id: str
    title: str
    status: Literal["draft", "published"]
    revision_id: str
    revision_no: int
    revision_status: Literal["draft", "published"]
    review_status: Literal["pending", "passed", "failed", "teacher_validated"]
    mode: Literal["new", "update", "curated_seed"]
    source_type: str
    source_summary: str
    version: int
    nodes: list[GraphNodeView]
    edges: list[GraphEdgeView]
    quality: GraphQualityView | None


class GraphCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    source_summary: str = Field(default="", max_length=1000)


class GraphRenameRequest(BaseModel):
    title: str = Field(min_length=2, max_length=180)


class GraphMutationGuard(BaseModel):
    expected_revision_version: int = Field(ge=1)


class GraphNodeCreate(BaseModel):
    expected_revision_version: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=120)
    node_type: GraphNodeType = "core"
    definition: str = Field(default="", max_length=3000)
    key_point: str = Field(default="", max_length=2000)
    misconception: str = Field(default="", max_length=2000)
    position_x: float = Field(default=0, ge=0, le=2000)
    position_y: float = Field(default=0, ge=0, le=1200)
    teacher_evidence_note: str = Field(default="", max_length=1000)


class GraphNodeUpdate(BaseModel):
    expected_revision_version: int = Field(ge=1)
    label: str | None = Field(default=None, min_length=1, max_length=120)
    node_type: GraphNodeType | None = None
    definition: str | None = Field(default=None, max_length=3000)
    key_point: str | None = Field(default=None, max_length=2000)
    misconception: str | None = Field(default=None, max_length=2000)
    position_x: float | None = Field(default=None, ge=0, le=2000)
    position_y: float | None = Field(default=None, ge=0, le=1200)
    teacher_evidence_note: str | None = Field(default=None, max_length=1000)


class GraphEdgeCreate(BaseModel):
    expected_revision_version: int = Field(ge=1)
    from_node_id: str
    to_node_id: str
    relation: GraphRelation
    teacher_evidence_note: str = Field(default="", max_length=1000)


class GraphEdgeUpdate(BaseModel):
    expected_revision_version: int = Field(ge=1)
    from_node_id: str | None = None
    to_node_id: str | None = None
    relation: GraphRelation | None = None
    teacher_evidence_note: str | None = Field(default=None, max_length=1000)


class GraphEvidenceSourceView(BaseModel):
    id: str
    target_type: Literal["node", "edge"]
    target_id: str
    source_kind: Literal["material_span", "teacher_statement", "curated_seed"]
    evidence_span_id: str | None
    source_name: str | None
    quote: str | None
    locator: dict | None
    assertion_note: str
    confidence: float
    source_model_run_id: str | None
    created_at: datetime


class GraphEvidenceBundleView(BaseModel):
    graph_id: str
    revision_id: str
    revision_version: int
    target_type: Literal["node", "edge"]
    target_id: str
    links: list[GraphEvidenceSourceView]


AssetPurpose = Literal[
    "graph_build", "graph_update", "question_generation", "video_search", "tutor_attachment"
]


class AssetPrepareRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(gt=0)
    declared_mime: str = Field(min_length=3, max_length=120)
    purpose: AssetPurpose
    expected_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class AssetView(BaseModel):
    id: str
    course_id: str
    purpose: AssetPurpose
    original_name: str
    extension: str
    declared_mime: str
    detected_mime: str | None
    expected_size: int
    byte_size: int | None
    sha256: str | None
    status: Literal["prepared", "uploaded", "parsed", "rejected", "deleted"]
    security_status: Literal["pending", "accepted", "rejected", "deleted"]
    rejection_code: str | None
    rejection_reason: str | None
    created_at: datetime
    uploaded_at: datetime | None
    accepted_at: datetime | None
    deleted_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class AssetPrepareResponse(BaseModel):
    asset: AssetView
    upload_url: str
    upload_method: Literal["PUT"] = "PUT"
    max_bytes: int


class ParsedDocumentView(BaseModel):
    id: str
    asset_id: str
    parser_name: str
    parser_version: str
    status: Literal["parsed", "invalidated"]
    title: str
    segment_count: int
    page_count: int
    text_length: int
    chunk_count: int
    warnings: list[dict]
    created_at: datetime


class AssetCompleteResponse(BaseModel):
    asset: AssetView
    document: ParsedDocumentView


class AlignmentRunCreate(BaseModel):
    source_asset_id: str | None = None
    manual_text: str | None = Field(default=None, max_length=12000)
    purpose: AssetPurpose

    @model_validator(mode="after")
    def exactly_one_source(self):
        if (self.source_asset_id is None) == (not self.manual_text or not self.manual_text.strip()):
            raise ValueError("source_asset_id与manual_text必须且只能提供一项")
        return self


class AlignmentCandidateView(BaseModel):
    concept_id: str
    concept_name: str
    rank: int
    lexical_score: float
    context_score: float
    graph_score: float
    final_score: float
    recommended: bool


class AlignmentReviewView(BaseModel):
    id: str
    status: Literal["pending", "decided"]
    decision: Literal["matched", "created", "abstained"] | None
    selected_concept_id: str | None
    note: str
    decided_at: datetime | None


class AlignmentMentionView(BaseModel):
    id: str
    ordinal: int
    raw_text: str
    normalized_text: str
    context: str
    status: Literal["matched", "ambiguous", "abstained"]
    evidence_span_id: str | None
    candidates: list[AlignmentCandidateView]
    review: AlignmentReviewView | None


class AlignmentRunView(BaseModel):
    id: str
    course_id: str
    source_type: Literal["asset", "manual"]
    source_asset_id: str | None
    purpose: AssetPurpose
    mode: Literal["concept_alignment"]
    status: Literal["completed", "needs_review", "invalidated", "failed"]
    parser_version: str | None
    ontology_version: str
    aligner_version: str
    thresholds: dict
    summary: dict
    created_at: datetime
    completed_at: datetime | None
    mentions: list[AlignmentMentionView] = Field(default_factory=list)


class AlignmentReviewDecision(BaseModel):
    decision: Literal["matched", "created", "abstained"]
    selected_concept_id: str | None = None
    new_concept_name: str | None = Field(default=None, min_length=2, max_length=120)
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.decision == "matched" and not self.selected_concept_id:
            raise ValueError("确认匹配时必须选择知识点")
        if self.decision == "created" and not (self.new_concept_name or "").strip():
            raise ValueError("创建新概念时必须填写规范名称")
        if self.decision != "matched" and self.selected_concept_id is not None:
            raise ValueError("仅确认匹配时可以指定现有知识点")
        if self.decision != "created" and self.new_concept_name is not None:
            raise ValueError("仅创建新概念时可以填写新名称")
        return self


class EvidenceSpanView(BaseModel):
    id: str
    chunk_id: str
    start_char: int
    end_char: int
    quote: str
    locator: dict
    checksum: str
    chunk_text: str


class AssetDeletionView(BaseModel):
    job_id: str
    asset_id: str
    status: Literal["completed", "failed"]
    invalidated_derivations: int
    storage_removed: bool
