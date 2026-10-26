from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .schemas import VisualSpec


TutorMode = Literal["adaptive", "coach", "visualize", "practice", "research", "explain"]
ConcreteTutorMode = Literal["coach", "visualize", "practice", "research", "explain"]
ExperienceMode = Literal["manual", "automatic"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HistoryPermissions(StrictModel):
    read_answer_history: bool = False
    read_conversation_history: bool = False


class ConversationCreate(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    selected_mode: TutorMode = "adaptive"
    requested_profile_id: str = Field(min_length=1, max_length=80)
    experience_mode: ExperienceMode = "manual"

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class ConversationRename(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    version: int = Field(ge=1)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("对话标题不能为空")
        return cleaned


class TutorTurnCreate(StrictModel):
    client_turn_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    message: str = Field(min_length=1, max_length=8000)
    selected_mode: TutorMode | None = None
    requested_profile_id: str | None = Field(default=None, min_length=1, max_length=80)
    history_permissions: HistoryPermissions = Field(default_factory=HistoryPermissions)
    experience_mode: ExperienceMode | None = None
    attachment_ids: list[str] = Field(default_factory=list, max_length=8)
    concept_ids: list[str] = Field(default_factory=list, max_length=12)
    conversation_version: int = Field(ge=1)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("消息不能为空")
        return cleaned

    @field_validator("attachment_ids", "concept_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("ID不能重复")
        return value


class Citation(StrictModel):
    label: str = Field(min_length=1, max_length=240)
    url: str = Field(min_length=8, max_length=2048)
    claim: str = Field(min_length=1, max_length=1200)


class Checkpoint(StrictModel):
    status: Literal["awaiting_student_response", "understanding_confirmed", "not_required"]
    criterion: str = Field(min_length=1, max_length=500)


class UnderstandingEvidence(StrictModel):
    kind: Literal["none", "student_restatement", "worked_reasoning"] = "none"
    student_quote: str | None = Field(default=None, min_length=1, max_length=1000)
    score: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def complete_evidence(self) -> "UnderstandingEvidence":
        if self.kind == "none":
            if self.student_quote is not None or self.score is not None:
                raise ValueError("无理解证据时不得填写引文或得分")
        elif self.student_quote is None or self.score is None:
            raise ValueError("理解证据必须同时包含学生原话和形成性得分")
        return self


class MemoryProposal(StrictModel):
    memory_kind: Literal["learning_conclusion", "explanation_preference", "unresolved_question"]
    content: str = Field(min_length=2, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_quote: str = Field(min_length=1, max_length=1000)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ExperienceProposal(StrictModel):
    title: str = Field(min_length=2, max_length=180)
    context: str = Field(min_length=2, max_length=1200)
    method: str = Field(min_length=2, max_length=2000)
    evidence_summary: str = Field(min_length=2, max_length=1200)
    evidence_quote: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)


class TutorModelOutput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=12000)
    checkpoint: Checkpoint
    visual: VisualSpec | None = None
    citations: list[Citation] = Field(default_factory=list, max_length=12)
    understanding_evidence: UnderstandingEvidence = Field(default_factory=UnderstandingEvidence)
    memory_candidates: list[MemoryProposal] = Field(default_factory=list, max_length=4)
    experience_candidate: ExperienceProposal | None = None

    @model_validator(mode="after")
    def unique_citations(self) -> "TutorModelOutput":
        urls = [item.url for item in self.citations]
        if len(urls) != len(set(urls)):
            raise ValueError("来源链接不能重复")
        return self


class ExperienceModelOutput(StrictModel):
    decision: Literal["generated", "not_needed"]
    reason_code: str = Field(min_length=1, max_length=80)
    candidate: ExperienceProposal | None = None

    @model_validator(mode="after")
    def candidate_matches_decision(self) -> "ExperienceModelOutput":
        if self.decision == "generated" and self.candidate is None:
            raise ValueError("生成经验时必须返回候选")
        if self.decision == "not_needed" and self.candidate is not None:
            raise ValueError("无需生成时不得返回候选")
        return self


class ExperienceGenerate(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    requested_profile_id: str = Field(min_length=1, max_length=80)
    conversation_version: int = Field(ge=1)


class MemoryResolve(StrictModel):
    action: Literal["confirm", "delete", "supersede"]
    replacement_content: str | None = Field(default=None, min_length=2, max_length=1000)

    @model_validator(mode="after")
    def replacement_only_for_supersede(self) -> "MemoryResolve":
        if self.action == "supersede" and self.replacement_content is None:
            raise ValueError("替换记忆时必须提供新内容")
        if self.action != "supersede" and self.replacement_content is not None:
            raise ValueError("只有替换记忆时可提供新内容")
        return self


class ConversationListItem(StrictModel):
    id: str
    course_id: str
    title: str
    selected_mode: TutorMode
    requested_profile_id: str
    experience_mode: ExperienceMode
    version: int
    preview: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class MessageView(StrictModel):
    id: str
    turn_id: str | None
    ordinal: int
    role: Literal["user", "assistant"]
    title: str | None
    body: str
    strategy: ConcreteTutorMode | None
    checkpoint: dict
    visual: dict | None
    citations: list[dict]
    inline_practice: dict | None
    created_at: datetime


class ConversationView(ConversationListItem):
    messages: list[MessageView]


class TurnView(StrictModel):
    turn_id: str
    conversation_id: str
    conversation_version: int
    duplicate: bool = False
    model_execution: dict
    resolved_concept_ids: list[str]
    strategy_plan: dict
    answer: MessageView
    experience_decision: dict
    quality: dict


class MemoryView(StrictModel):
    id: str
    course_id: str
    memory_kind: str
    content: str
    confidence: float
    status: str
    conflict_group: str | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    source_count: int


class ExperienceView(StrictModel):
    id: str
    course_id: str
    title: str
    context: str
    method: str
    evidence_summary: str
    confidence: float
    generation_mode: str
    status: str
    created_at: datetime
    updated_at: datetime
