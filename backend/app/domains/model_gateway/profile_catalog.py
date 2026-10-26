from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import ModelProfile, ModelProfileRevision, TaskPolicy


@dataclass(frozen=True)
class ResolvedProfile:
    profile: ModelProfile
    revision: ModelProfileRevision | None
    available: bool
    unavailable_reason: str | None
    endpoint: str | None
    api_key: str | None
    provider_model_id: str | None


def active_revision(db: Session, profile_id: str) -> ModelProfileRevision | None:
    return db.scalar(
        select(ModelProfileRevision)
        .where(
            ModelProfileRevision.profile_id == profile_id,
            ModelProfileRevision.status == "active",
        )
        .order_by(ModelProfileRevision.revision_no.desc())
    )


def active_policy(db: Session, task_kind: str) -> TaskPolicy | None:
    return db.scalar(
        select(TaskPolicy)
        .where(TaskPolicy.task_kind == task_kind, TaskPolicy.enabled.is_(True))
        .order_by(TaskPolicy.created_at.desc())
    )


def resolve_profile(db: Session, profile: ModelProfile, task_kind: str | None) -> ResolvedProfile:
    revision = active_revision(db, profile.id)
    if not profile.enabled:
        return ResolvedProfile(profile, revision, False, "该模型Profile已停用", None, None, None)
    if task_kind and task_kind not in profile.task_kinds:
        return ResolvedProfile(profile, revision, False, "该Profile不支持当前任务", None, None, None)
    if revision is None:
        return ResolvedProfile(profile, None, False, "缺少已发布的模型配置修订", None, None, None)
    policy = active_policy(db, task_kind) if task_kind else None
    if task_kind and policy is None:
        return ResolvedProfile(profile, revision, False, "当前任务政策尚未发布", None, None, None)
    if policy:
        missing_capabilities = sorted(
            set(policy.required_capabilities_json) - set(revision.capabilities_json)
        )
        if missing_capabilities:
            return ResolvedProfile(
                profile, revision, False,
                f"缺少任务能力：{'、'.join(missing_capabilities)}", None, None, None,
            )
    api_key = os.getenv(revision.credential_ref)
    endpoint = os.getenv(revision.endpoint_ref)
    provider_model_id = os.getenv(revision.model_id_ref)
    missing = [
        label for label, value in (
            ("访问凭证", api_key), ("API地址", endpoint), ("供应商模型ID", provider_model_id)
        ) if not value
    ]
    if missing:
        return ResolvedProfile(
            profile, revision, False, f"运行环境尚未配置{'、'.join(missing)}",
            endpoint, api_key, provider_model_id,
        )
    allowed_regions = {
        item.strip() for item in os.getenv("ZHIXING_MODEL_ALLOWED_DATA_REGIONS", "").split(",")
        if item.strip()
    }
    if revision.data_region not in allowed_regions:
        return ResolvedProfile(
            profile, revision, False, "当前部署尚未授权该模型的数据区域策略",
            endpoint, api_key, provider_model_id,
        )
    allowed_retention = {
        item.strip() for item in os.getenv("ZHIXING_MODEL_ALLOWED_RETENTION_POLICIES", "").split(",")
        if item.strip()
    }
    if revision.retention_policy not in allowed_retention:
        return ResolvedProfile(
            profile, revision, False, "当前部署尚未核验该模型的数据保留策略",
            endpoint, api_key, provider_model_id,
        )
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return ResolvedProfile(
            profile, revision, False, "模型API地址必须是无内嵌凭证的HTTPS地址",
            endpoint, api_key, provider_model_id,
        )
    return ResolvedProfile(profile, revision, True, None, endpoint, api_key, provider_model_id)
