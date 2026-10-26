from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TopicRef(StrictModel):
    concept_id: str = Field(min_length=3, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    weight: float = Field(default=1.0, gt=0.0, le=1.0)


class VideoSearchIntent(StrictModel):
    course_id: str = Field(min_length=2, max_length=64)
    source_mode: Literal["graph", "records", "files", "manual"]
    topics: list[TopicRef] = Field(min_length=1, max_length=30)
    teaching_intent: str = Field(default="", max_length=500)
    language: str = Field(default="zh-CN", max_length=16)
    requested_profile_id: str | None = Field(default=None, max_length=80)

    @field_validator("source_mode", mode="before")
    @classmethod
    def normalize_legacy_source_mode(cls, value: object) -> object:
        # 兼容早期领域测试及已保存草稿；对外API只公开规范枚举。
        return {"recorded": "records", "asset": "files"}.get(value, value)

    @model_validator(mode="after")
    def unique_topics(self) -> "VideoSearchIntent":
        ids = [item.concept_id for item in self.topics]
        if len(ids) != len(set(ids)):
            raise ValueError("知识点不能重复")
        return self


class DiscoveredVideo(StrictModel):
    provider: str
    external_id: str
    canonical_url: str
    title: str = ""
    description: str = ""


class VideoMetadata(StrictModel):
    title: str
    creator: str | None = None
    description: str = ""
    thumbnail_url: str | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    embed_url: str | None = None
    final_url: str
    content_type: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    link_verified: bool = False
    source_verified: bool = True
    metadata_verified: bool = True
    collected_at: datetime


class VideoCandidate(StrictModel):
    provider: str
    external_id: str
    canonical_url: str
    title: str
    creator: str | None = None
    description: str = ""
    thumbnail_url: str | None = None
    duration_seconds: int | None = None
    embed_url: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    matched_topic_ids: list[str] = Field(default_factory=list)
    match_score: float = Field(ge=0.0, le=1.0)
    completeness_score: float = Field(ge=0.0, le=1.0)
    trust_score: float = Field(ge=0.0, le=1.0)
    clarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    final_score: float = Field(ge=0.0, le=1.0)
    evidence_level: Literal["E0", "E1", "E2", "E3"]
    verified_scope: list[Literal["link", "source", "metadata", "content_evidence"]]
    verified_at: datetime
    uncertainty_reason: str | None = None
