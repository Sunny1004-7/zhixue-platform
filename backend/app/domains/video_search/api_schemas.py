from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VideoSearchJobCreate(StrictModel):
    source_mode: Literal["graph", "records", "files", "manual"]
    topic_ids: list[str] = Field(min_length=1, max_length=30)
    graph_revision_id: str | None = Field(default=None, max_length=80)
    asset_ids: list[str] = Field(default_factory=list, max_length=10)
    raw_text: str | None = Field(default=None, max_length=500)
    teaching_intent: str = Field(default="", max_length=500)
    language: str = Field(default="zh-CN", pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?$")
    requested_profile_id: str | None = Field(default=None, max_length=80)
    allow_deterministic_degrade: bool = True
    max_candidates_per_provider: int = Field(default=12, ge=1, le=30)

    @model_validator(mode="after")
    def validate_source(self) -> "VideoSearchJobCreate":
        if len(set(self.topic_ids)) != len(self.topic_ids):
            raise ValueError("知识点不能重复")
        if self.source_mode == "graph" and not self.graph_revision_id:
            raise ValueError("图谱检索必须提供已发布修订")
        if self.source_mode == "files" and not self.asset_ids:
            raise ValueError("文件检索必须提供已解析教学文件")
        if self.source_mode == "manual" and not (self.raw_text or "").strip():
            raise ValueError("手动检索必须提供知识点说明")
        if self.source_mode != "graph" and self.graph_revision_id is not None:
            raise ValueError("当前来源不能携带图谱修订")
        if self.source_mode != "files" and self.asset_ids:
            raise ValueError("当前来源不能携带教学文件")
        if self.source_mode != "manual" and self.raw_text is not None:
            raise ValueError("当前来源不能携带手动输入")
        return self


class ProviderStatusView(StrictModel):
    provider: str
    status: Literal["completed", "partial", "unavailable"]
    discovered_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    error_code: str | None = None
    safe_message: str | None = None


class VideoSourceTopicView(StrictModel):
    concept_id: str
    label: str
    correct_rate: float | None = None
    evidence_count: int = 0


class VideoSourceGraphView(StrictModel):
    graph_id: str
    title: str
    published_revision_id: str
    topics: list[VideoSourceTopicView]


class VideoSourceAssetView(StrictModel):
    asset_id: str
    original_name: str
    parsed_title: str
    accepted_at: datetime | None


class VideoSearchSourcesView(StrictModel):
    course_id: str
    recorded_topics: list[VideoSourceTopicView]
    graphs: list[VideoSourceGraphView]
    parsed_assets: list[VideoSourceAssetView]


class VideoSearchJobView(StrictModel):
    id: str
    course_id: str
    source_mode: str
    requested_profile_id: str | None
    actual_profile_id: str | None
    deterministic_degrade: bool
    status: Literal["created", "retrieving", "completed", "partial", "failed"]
    provider_statuses: list[ProviderStatusView]
    warnings: list[dict[str, Any]]
    candidate_count: int
    safe_error_code: str | None
    safe_error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class VideoScoresView(StrictModel):
    match: float = Field(ge=0.0, le=1.0)
    completeness: float = Field(ge=0.0, le=1.0)
    trust: float = Field(ge=0.0, le=1.0)
    clarity: float | None = Field(default=None, ge=0.0, le=1.0)
    final: float = Field(ge=0.0, le=1.0)


class VideoCandidateView(StrictModel):
    id: str
    job_id: str
    provider: str
    external_id: str
    canonical_url: str
    embed_url: str | None
    title: str
    creator: str | None
    description: str
    thumbnail_url: str | None
    duration_seconds: int | None
    content_type: str | None
    content_kind: str
    license_name: str | None
    license_url: str | None
    scores: VideoScoresView
    matched_topic_ids: list[str]
    evidence_level: Literal["E0", "E1", "E2", "E3"]
    verified_scope: list[str]
    uncertainty_reason: str | None
    verification_status: str
    lifecycle_status: str
    rank: int
    verified_at: datetime
    verification_expires_at: datetime | None
    preview_required: bool
    previewed: bool


class PreviewEventCreate(StrictModel):
    action: Literal["embedded_preview", "original_page_opened"]


class PreviewEventView(StrictModel):
    id: str
    candidate_id: str
    action: str
    created_at: datetime
    duplicate: bool = False


class LinkCheckView(StrictModel):
    id: str
    candidate_id: str
    status: str
    safe_error_code: str | None
    final_url: str | None
    checked_at: datetime


class PublicationAudience(StrictModel):
    mode: Literal["all", "states"] = "all"
    topic_ids: list[str] = Field(default_factory=list, max_length=30)
    states: list[Literal["weak", "mastered", "unseen"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_targeting(self) -> "PublicationAudience":
        if self.mode == "states" and (not self.topic_ids or not self.states):
            raise ValueError("定向发布必须选择实际知识点和学生状态")
        if self.mode == "all" and (self.topic_ids or self.states):
            raise ValueError("全班发布不能携带定向条件")
        if len(set(self.topic_ids)) != len(self.topic_ids):
            raise ValueError("定向知识点不能重复")
        if len(set(self.states)) != len(self.states):
            raise ValueError("学生状态不能重复")
        return self


class VideoPublicationCreate(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=80)
    audience: PublicationAudience = Field(default_factory=PublicationAudience)
    intervention_plan_id: str | None = Field(default=None, max_length=80)


class VideoPublicationView(StrictModel):
    id: str
    course_id: str
    candidate_id: str
    status: str
    resource: dict[str, Any]
    audience: dict[str, Any]
    recipient_count: int
    created_at: datetime
    duplicate: bool = False


class VideoPlayerEventCreate(StrictModel):
    event_type: Literal[
        "opened", "playback", "heartbeat", "chapter_opened", "completed", "feedback"
    ]
    occurred_at: datetime
    player_signal: Literal["official_sdk", "heartbeat", "chapter", "page_only"]
    position_seconds: float | None = Field(default=None, ge=0.0, le=86400.0)
    active_seconds_delta: float = Field(default=0.0, ge=0.0, le=120.0)
    foreground_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    chapter_id: str | None = Field(default=None, max_length=80)
    feedback: Literal["helpful", "not_helpful"] | None = None

    @model_validator(mode="after")
    def validate_event(self) -> "VideoPlayerEventCreate":
        if self.event_type in {"playback", "heartbeat", "completed"} and self.position_seconds is None:
            raise ValueError("播放器进度事件必须提供播放位置")
        if self.event_type == "chapter_opened" and not self.chapter_id:
            raise ValueError("章节事件必须提供章节标识")
        if self.event_type == "feedback" and self.feedback is None:
            raise ValueError("反馈事件必须提供反馈结果")
        if self.player_signal == "page_only" and self.active_seconds_delta > 0:
            raise ValueError("页面停留不能上报真实观看时长")
        return self


class VideoProgressView(StrictModel):
    publication_id: str
    active_seconds: float
    max_position_seconds: float | None
    progress_ratio: float
    foreground_ratio: float
    reliability: float
    completed: bool
    evidence_scope: Literal["verified_playback", "resource_interaction_only"]
    last_event_at: datetime | None


class VideoEventResult(StrictModel):
    event_id: str
    duplicate: bool
    trajectory_event_id: str | None
    trajectory_processing_status: str
    progress: VideoProgressView
