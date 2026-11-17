"""Idempotent model catalog upgrades shared by new and existing databases."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import ModelProfile, ModelProfileRevision, TaskPolicy


CATALOG_VERSION = "deepseek-catalog-2026-11-17"
PROFILE_SPECS = (
    ("deepseek-flash", "DeepSeek Flash", "DEEPSEEK_FLASH_MODEL_ID"),
    ("deepseek-pro", "DeepSeek Pro", "DEEPSEEK_PRO_MODEL_ID"),
)
TASK_KINDS = [
    "knowledge_graph", "a2.graph_extract", "a2.graph_semantic_review",
    "question_generation", "a3.question_generation", "a5.tutor_reply",
    "a5.experience_generation", "video_retrieval", "tutoring",
]
CAPABILITIES = [
    "chat", "structured_json", "chinese", "graph_extract",
    "graph_semantic_review", "question_generation", "tutoring",
]


def seed_model_catalog(session: Session) -> None:
    supported_ids = {spec[0] for spec in PROFILE_SPECS}
    for profile in session.scalars(select(ModelProfile)):
        if profile.id not in supported_ids:
            profile.enabled = False
    for profile_id, name, model_ref in PROFILE_SPECS:
        profile = session.get(ModelProfile, profile_id)
        if profile is None:
            profile = ModelProfile(id=profile_id, display_name=name, enabled=True,
                                   task_kinds=TASK_KINDS, config_revision=CATALOG_VERSION)
            session.add(profile)
            session.flush()
        profile.display_name = name
        profile.enabled = True
        profile.task_kinds = TASK_KINDS
        profile.config_revision = CATALOG_VERSION
        revisions = list(session.scalars(select(ModelProfileRevision).where(
            ModelProfileRevision.profile_id == profile_id)))
        current = next((revision for revision in revisions
                        if revision.model_id_ref == model_ref and revision.status == "active"), None)
        if current is None:
            revision_no = max((revision.revision_no for revision in revisions), default=0) + 1
            for revision in revisions:
                if revision.status == "active":
                    revision.status = "retired"
            session.add(ModelProfileRevision(
                id=f"{profile_id}:rev:{revision_no}", profile_id=profile_id,
                revision_no=revision_no, provider_kind="deepseek",
                credential_ref="DEEPSEEK_API_KEY", endpoint_ref="DEEPSEEK_API_BASE",
                model_id_ref=model_ref, capabilities_json=CAPABILITIES,
                data_region="deployment_configured", retention_policy="provider_account_policy",
                status="active",
            ))
    # Preserve task schemas and selection rules, with enough time for either model.
    for policy in session.scalars(select(TaskPolicy).where(TaskPolicy.enabled.is_(True))):
        if policy.timeout_seconds <= 60:
            policy.timeout_seconds = 180
    session.flush()
