from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RelationType = Literal["prerequisite", "contains", "application", "contrast"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedConcept(StrictModel):
    concept_id: str = Field(min_length=3, max_length=80)
    evidence_span_ids: list[str] = Field(min_length=1, max_length=12)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedRelation(StrictModel):
    from_concept_id: str = Field(min_length=3, max_length=80)
    to_concept_id: str = Field(min_length=3, max_length=80)
    relation: RelationType
    evidence_span_ids: list[str] = Field(min_length=1, max_length=12)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=500)


class GraphExtractionOutput(StrictModel):
    concepts: list[ExtractedConcept] = Field(min_length=1, max_length=50)
    relations: list[ExtractedRelation] = Field(default_factory=list, max_length=100)


class GraphExtractionCreate(StrictModel):
    alignment_run_id: str
    requested_profile_id: str
    idempotency_key: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    expected_revision_version: int = Field(ge=1)


class ProposalDecision(StrictModel):
    decision: Literal["accepted", "rejected"]
    expected_artifact_version: int = Field(ge=1)
    note: str = Field(default="", max_length=500)


class GraphExtractionApply(StrictModel):
    expected_artifact_version: int = Field(ge=1)
    expected_revision_version: int = Field(ge=1)


class GraphSemanticReviewCreate(StrictModel):
    requested_profile_id: str
    idempotency_key: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    expected_revision_version: int = Field(ge=1)


class SemanticReviewIssueOutput(StrictModel):
    issue_code: str = Field(min_length=2, max_length=64)
    severity: Literal["info", "warning", "error"]
    target_type: Literal["graph", "node", "edge"]
    target_id: str = Field(min_length=1, max_length=80)
    evidence_span_ids: list[str] = Field(default_factory=list, max_length=12)
    claim: str = Field(min_length=2, max_length=1000)
    suggestion: str = Field(default="", max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)


class GraphSemanticReviewOutput(StrictModel):
    summary: dict[str, Any] = Field(default_factory=dict)
    issues: list[SemanticReviewIssueOutput] = Field(default_factory=list, max_length=80)


class GraphSemanticReviewIssueDecision(StrictModel):
    decision: Literal["confirmed", "ignored"]
    expected_artifact_version: int = Field(ge=1)
    note: str = Field(default="", max_length=500)


class ModelRunView(StrictModel):
    id: str
    task_kind: str
    requested_profile_id: str
    actual_profile_id: str | None
    provider_model_id: str | None
    task_policy_version: str
    prompt_template_version: str | None
    status: str
    fallback_reason: str | None
    error_code: str | None
    safe_error: str | None
    attempt_count: int
    usage: dict
    audit_hash: str | None
    created_at: datetime
    completed_at: datetime | None


class GraphExtractionProposalView(StrictModel):
    id: str
    proposal_kind: Literal["concept", "relation"]
    concept_id: str | None
    concept_label: str | None
    from_concept_id: str | None
    from_label: str | None
    to_concept_id: str | None
    to_label: str | None
    relation: RelationType | None
    evidence_span_ids: list[str]
    confidence: float
    rationale: str
    status: Literal["pending", "accepted", "rejected"]
    review_note: str


class GraphExtractionArtifactView(StrictModel):
    id: str
    course_id: str
    graph_id: str
    revision_id: str
    alignment_run_id: str
    base_revision_version: int
    status: Literal["awaiting_review", "ready_to_apply", "rejected", "applied", "invalidated"]
    version: int
    model_run: ModelRunView
    proposals: list[GraphExtractionProposalView]
    created_at: datetime
    applied_at: datetime | None


class GraphSemanticReviewIssueView(StrictModel):
    id: str
    issue_code: str
    severity: Literal["info", "warning", "error"]
    target_type: Literal["graph", "node", "edge"]
    target_id: str
    target_label: str | None
    evidence_span_ids: list[str]
    claim: str
    suggestion: str
    confidence: float
    status: Literal["pending", "confirmed", "ignored"]
    review_note: str


class GraphSemanticReviewArtifactView(StrictModel):
    id: str
    course_id: str
    graph_id: str
    revision_id: str
    base_revision_version: int
    independence_status: str
    status: Literal["awaiting_review", "reviewed", "changes_required", "passed", "superseded"]
    summary: dict[str, Any]
    version: int
    model_run: ModelRunView
    issues: list[GraphSemanticReviewIssueView]
    created_at: datetime
    completed_at: datetime | None
