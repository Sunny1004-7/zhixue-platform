from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import DEFAULT_FACT_SOURCE, Settings
from app.domains.model_gateway.contracts import ProviderResponse
from app.domains.model_gateway.service import stable_hash
from app.learning_support_models import (
    DecisionPublication,
    PersonalizedResourceJob,
    ResourceExposure,
    TutorConversation,
    TutorMemory,
    TutorMessage,
    TutorTurn,
)
from app.main import create_app
from app.models import (
    Concept,
    LearningEvent,
    ModelProfile,
    ModelProfileRevision,
    PromptTemplate,
    Question,
    QuestionConcept,
    QuestionQualityReport,
    QuestionSet,
    QuestionSetRevision,
    TaskPolicy,
    User,
)
from app.teaching_decision_api import router as decision_router
from app.tutoring_api import router as tutoring_router


COURSE_ID = "machine-learning"


class QueueAdapter:
    def __init__(self, outputs: list[dict]):
        self.outputs = list(outputs)
        self.calls = 0
        self.prompts: list[str] = []

    def invoke(self, request):
        self.calls += 1
        self.prompts.append(request.user_prompt)
        if not self.outputs:
            raise AssertionError("测试适配器没有剩余结构化输出")
        return ProviderResponse(
            content=json.dumps(self.outputs.pop(0), ensure_ascii=False),
            input_tokens=120,
            output_tokens=80,
        )


@pytest.fixture()
def support_client(tmp_path: Path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'support.db').as_posix()}",
        fact_source=DEFAULT_FACT_SOURCE,
        cors_origins=("http://testserver",),
        session_ttl_hours=1,
        asset_root=tmp_path / "assets",
        asset_max_bytes=2 * 1024 * 1024,
    )
    app = create_app(settings)
    app.include_router(tutoring_router)
    app.include_router(decision_router)
    with TestClient(app) as client:
        yield client


def login(client: TestClient, role: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={
        "account": f"{role}@zhixing.edu.cn",
        "password": "zhixing2026",
        "role": role,
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def configure_tutoring(monkeypatch, client: TestClient, adapter: QueueAdapter) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("OPENAI_API_BASE", "https://model.test.invalid/v1")
    monkeypatch.setenv("OPENAI_MODEL_ID", "provider/test-model")
    monkeypatch.setenv("ZHIXING_MODEL_ALLOWED_DATA_REGIONS", "deployment_configured")
    monkeypatch.setenv("ZHIXING_MODEL_ALLOWED_RETENTION_POLICIES", "provider_account_policy")
    client.app.state.model_adapter_registry = {"openai": adapter}
    with client.app.state.db.session_factory() as db:
        profile = db.get(ModelProfile, "gpt-5")
        profile.task_kinds = sorted(set(profile.task_kinds) | {
            "a5.tutor_reply", "a5.experience_generation",
        })
        revision = db.get(ModelProfileRevision, "gpt-5:rev:1")
        revision.capabilities_json = sorted(set(revision.capabilities_json) | {
            "tutoring", "structured_json", "chinese",
        })
        for task_kind, schema_version in (
            ("a5.tutor_reply", "a5.tutor-output-1.0.0"),
            ("a5.experience_generation", "a5.experience-output-1.0.0"),
        ):
            if db.scalar(select(TaskPolicy).where(TaskPolicy.task_kind == task_kind)) is None:
                db.add(TaskPolicy(
                    id=f"test:{task_kind}:policy", task_kind=task_kind,
                    version="1.0.0",
                    required_capabilities_json=["tutoring", "structured_json", "chinese"],
                    selection_mode="required", max_attempts=1, timeout_seconds=10,
                    output_schema_version=schema_version, enabled=True,
                ))
            if db.scalar(select(PromptTemplate).where(PromptTemplate.task_kind == task_kind)) is None:
                system = "只使用授权上下文，严格输出给定JSON Schema，不得输出Markdown。"
                user = "课程：{course_id}\n授权上下文：{context_json}\nJSON Schema：{schema_json}"
                db.add(PromptTemplate(
                    id=f"test:{task_kind}:prompt", task_kind=task_kind,
                    version="1.0.0", system_template=system,
                    user_template=user,
                    template_hash=sha256((system + user).encode()).hexdigest(),
                    active=True,
                ))
        db.commit()


def tutor_output(
    *,
    title: str = "先区分使用阶段",
    body: str = "训练时关注优化信号，评估时关注解释口径。",
    memory_quote: str | None = None,
    understanding_quote: str | None = None,
    visual: dict | None = None,
) -> dict:
    return {
        "title": title,
        "body": body,
        "checkpoint": {
            "status": "understanding_confirmed" if understanding_quote else "awaiting_student_response",
            "criterion": "能按训练与评估阶段说明指标用途",
        },
        "visual": visual,
        "citations": [],
        "understanding_evidence": {
            "kind": "student_restatement" if understanding_quote else "none",
            "student_quote": understanding_quote,
            "score": 0.9 if understanding_quote else None,
        },
        "memory_candidates": ([{
            "memory_kind": "explanation_preference",
            "content": "学生偏好先看流程，再核对公式。",
            "confidence": 0.75,
            "evidence_quote": memory_quote,
            "expires_in_days": 180,
        }] if memory_quote else []),
        "experience_candidate": None,
    }


def create_conversation(client: TestClient, headers: dict[str, str], mode: str = "adaptive") -> dict:
    response = client.post(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/conversations",
        headers=headers,
        json={
            "selected_mode": mode,
            "requested_profile_id": "gpt-5",
            "experience_mode": "manual",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_tutor_missing_model_credentials_is_explicit_and_non_mutating(support_client):
    student_headers = login(support_client, "student")
    conversation = create_conversation(support_client, student_headers)
    response = support_client.post(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/conversations/{conversation['id']}/turns",
        headers=student_headers,
        json={
            "client_turn_id": "missing-model-1",
            "message": "请解释损失函数。",
            "history_permissions": {
                "read_answer_history": False,
                "read_conversation_history": False,
            },
            "conversation_version": 1,
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] in {
        "MODEL_TASK_NOT_CONFIGURED", "MODEL_PROFILE_NOT_FEASIBLE",
    }
    loaded = support_client.get(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/conversations/{conversation['id']}",
        headers=student_headers,
    )
    assert loaded.status_code == 200
    assert loaded.json()["version"] == 1
    assert loaded.json()["messages"] == []


def test_tutor_turn_idempotency_permissions_memory_and_a1_feedback(
    support_client, monkeypatch,
):
    student_headers = login(support_client, "student")
    teacher_headers = login(support_client, "teacher")
    message = "我更喜欢先看步骤解释。"
    adapter = QueueAdapter([tutor_output(memory_quote=message)])
    configure_tutoring(monkeypatch, support_client, adapter)
    conversation = create_conversation(support_client, student_headers)
    request_body = {
        "client_turn_id": "turn-privacy-1",
        "message": message,
        "history_permissions": {
            "read_answer_history": False,
            "read_conversation_history": False,
        },
        "conversation_version": 1,
    }
    response = support_client.post(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/conversations/{conversation['id']}/turns",
        headers=student_headers, json=request_body,
    )
    assert response.status_code == 200, response.text
    assert response.json()["conversation_version"] == 2
    assert response.json()["quality"]["permission_snapshot"] == {
        "read_answer_history": False,
        "read_conversation_history": False,
    }
    duplicate = support_client.post(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/conversations/{conversation['id']}/turns",
        headers=student_headers, json=request_body,
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["turn_id"] == response.json()["turn_id"]
    assert adapter.calls == 1
    assert '"read_answer_history":false' in adapter.prompts[0]
    assert '"authorized_answer_summary":[]' in adapter.prompts[0]
    memories = support_client.get(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/memories",
        headers=student_headers,
    )
    assert memories.status_code == 200
    assert len(memories.json()) == 1
    forbidden = support_client.get(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/conversations/{conversation['id']}",
        headers=teacher_headers,
    )
    assert forbidden.status_code == 403
    with support_client.app.state.db.session_factory() as db:
        turn = db.get(TutorTurn, response.json()["turn_id"])
        event = db.get(LearningEvent, turn.trajectory_event_id)
        assert event.event_type == "tutor_message_received"
        assert event.processing_status == "observed_only"
        assert event.payload["effective_turns"] == 1

    deleted = support_client.delete(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/conversations/{conversation['id']}",
        headers=student_headers,
    )
    assert deleted.status_code == 204
    with support_client.app.state.db.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(TutorMessage)) == 0
        memory = db.scalar(select(TutorMemory))
        assert memory.status == "deleted"
        assert memory.deleted_at is not None


def test_tutor_visual_hard_gate_and_manual_experience(support_client, monkeypatch):
    student_headers = login(support_client, "student")
    first_message = "我会先看单位，再判断指标用途。"
    second_message = "我现在会先看单位再选指标。"
    experience = {
        "decision": "generated",
        "reason_code": "REPEATED_SUCCESSFUL_METHOD",
        "candidate": {
            "title": "先看单位再选指标",
            "context": "区分训练目标与业务评价指标时",
            "method": "先核对使用阶段，再检查结果单位与风险偏好。",
            "evidence_summary": "学生连续两轮能够按单位和阶段说明选择。",
            "evidence_quote": second_message,
            "confidence": 0.82,
        },
    }
    adapter = QueueAdapter([
        tutor_output(),
        tutor_output(understanding_quote=second_message),
        experience,
        tutor_output(),
    ])
    configure_tutoring(monkeypatch, support_client, adapter)
    conversation = create_conversation(support_client, student_headers)
    first = support_client.post(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/conversations/{conversation['id']}/turns",
        headers=student_headers,
        json={
            "client_turn_id": "experience-turn-1", "message": first_message,
            "history_permissions": {}, "conversation_version": 1,
        },
    )
    assert first.status_code == 200, first.text
    second = support_client.post(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/conversations/{conversation['id']}/turns",
        headers=student_headers,
        json={
            "client_turn_id": "experience-turn-2", "message": second_message,
            "history_permissions": {}, "conversation_version": 2,
        },
    )
    assert second.status_code == 200, second.text
    with support_client.app.state.db.session_factory() as db:
        turn = db.get(TutorTurn, second.json()["turn_id"])
        event = db.get(LearningEvent, turn.trajectory_event_id)
        assert event.processing_status == "accepted"
        assert event.evidence_reliability > 0
    generated = support_client.post(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/conversations/{conversation['id']}/experiences:generate",
        headers=student_headers,
        json={
            "idempotency_key": "manual-experience-1",
            "requested_profile_id": "gpt-5",
            "conversation_version": 3,
        },
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["decision"] == "generated"
    assert generated.json()["experience"]["evidence_summary"]

    visual_conversation = create_conversation(support_client, student_headers, mode="visualize")
    rejected = support_client.post(
        f"/api/v1/student/courses/{COURSE_ID}/tutor/conversations/{visual_conversation['id']}/turns",
        headers=student_headers,
        json={
            "client_turn_id": "visual-missing-1",
            "message": "请画图解释梯度下降。",
            "history_permissions": {}, "conversation_version": 1,
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "MODEL_OUTPUT_HARD_GATE_FAILED"


def seed_published_question_set(client: TestClient) -> tuple[str, str]:
    with client.app.state.db.session_factory() as db:
        teacher = db.scalar(select(User).where(User.email == "teacher@zhixing.edu.cn"))
        concept = db.scalar(select(Concept).where(
            Concept.course_id == COURSE_ID
        ).order_by(Concept.sort_order))
        set_id = str(uuid4())
        revision_id = str(uuid4())
        question_id = str(uuid4())
        db.add(QuestionSet(
            id=set_id, course_id=COURSE_ID, created_by=teacher.id,
            title="发布集成测试题组", status="published", visibility="course",
        ))
        db.flush()
        db.add(QuestionSetRevision(
            id=revision_id, question_set_id=set_id, revision_no=1,
            status="published", quality_status="passed", source_kind="teacher",
            source_summary="教师审核的集成测试资源", created_by=teacher.id,
            version=1, published_at=datetime.now(timezone.utc),
        ))
        db.flush()
        question_set = db.get(QuestionSet, set_id)
        question_set.working_revision_id = revision_id
        question_set.published_revision_id = revision_id
        db.add(Question(
            id=question_id, revision_id=revision_id, position=1,
            question_type="short", prompt="说明损失函数的作用。",
            answer_spec_json={"keywords": ["优化"]}, rubric_json=[],
            explanation="用于形成优化信号。", cognitive_level="understand",
            difficulty_prior=0.5, source_evidence_ids=[],
        ))
        db.flush()
        db.add(QuestionConcept(
            id=str(uuid4()), question_id=question_id,
            concept_id=concept.id, weight=1.0, evidence_ids=[],
        ))
        db.add(QuestionQualityReport(
            id=str(uuid4()), revision_id=revision_id, question_id=None,
            hard_pass=True, hard_gates_json={"answer_consistency": True},
            dimension_scores_json={}, issues_json=[],
            validator_version="test-quality-1.0.0",
        ))
        db.commit()
        return set_id, concept.id


def test_decision_snapshot_directed_publication_inbox_and_privacy(support_client):
    teacher_headers = login(support_client, "teacher")
    student_headers = login(support_client, "student")
    refreshed = support_client.post(
        f"/api/v1/courses/{COURSE_ID}/decision-snapshots:refresh",
        headers=teacher_headers, json={},
    )
    assert refreshed.status_code == 201, refreshed.text
    assert refreshed.json()["student_count"] >= 48
    assert len(refreshed.json()["priority_students"]) == 3
    listed = support_client.get(
        f"/api/v1/courses/{COURSE_ID}/students?sort=score_asc&page_size=100",
        headers=teacher_headers,
    )
    assert listed.status_code == 200, listed.text
    scores = [item["score"] for item in listed.json()["items"]]
    assert scores == sorted(scores)
    student_id = next(
        item["student_id"] for item in listed.json()["items"]
        if item["student_name"] == "林知夏"
    )
    detail = support_client.get(
        f"/api/v1/courses/{COURSE_ID}/students/{student_id}/learning-state",
        headers=teacher_headers,
    )
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["concepts"]) == 10
    serialized_detail = json.dumps(detail.json(), ensure_ascii=False).lower()
    assert "conversation" not in serialized_detail
    assert '"body"' not in serialized_detail
    assert "辅导对话" in detail.json()["privacy_boundary"]
    forbidden = support_client.post(
        f"/api/v1/courses/{COURSE_ID}/decision-snapshots:refresh",
        headers=student_headers, json={},
    )
    assert forbidden.status_code == 403

    question_set_id, concept_id = seed_published_question_set(support_client)
    preview = support_client.post(
        f"/api/v1/teacher/courses/{COURSE_ID}/resources/{question_set_id}/audience-drafts",
        headers=teacher_headers,
        json={
            "resource_type": "question_set",
            "resource_id": question_set_id,
            "resource_version": 1,
            "audience_mode": "concept_directed",
            "selected_concept_ids": [concept_id],
            "selected_states": ["weak", "mastered", "unseen"],
        },
    )
    assert preview.status_code == 201, preview.text
    assert preview.json()["final_student_ids"]
    assert preview.json()["resource"]["concept_ids"] == [concept_id]
    publication = support_client.post(
        f"/api/v1/audience-drafts/{preview.json()['id']}/publications",
        headers={**teacher_headers, "Idempotency-Key": "publish-directed-1"},
        json={"draft_version": 1, "acknowledge_warnings": False},
    )
    assert publication.status_code == 201, publication.text
    assert publication.json()["recipient_count"] == len(preview.json()["final_student_ids"])
    duplicate = support_client.post(
        f"/api/v1/audience-drafts/{preview.json()['id']}/publications",
        headers={**teacher_headers, "Idempotency-Key": "publish-directed-1"},
        json={"draft_version": 1, "acknowledge_warnings": False},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == publication.json()["id"]
    inbox = support_client.get(
        f"/api/v1/student/courses/{COURSE_ID}/resource-inbox",
        headers=student_headers,
    )
    assert inbox.status_code == 200, inbox.text
    item = next(entry for entry in inbox.json() if entry["publication_id"] == publication.json()["id"])
    assert item["personalized"] is True
    now = datetime.now(timezone.utc).isoformat()
    opened = support_client.post(
        f"/api/v1/student/resource-inbox/{item['exposure_id']}:open",
        headers=student_headers,
        json={"idempotency_key": "open-1", "occurred_at": now},
    )
    assert opened.status_code == 200, opened.text
    completed = support_client.post(
        f"/api/v1/student/resource-inbox/{item['exposure_id']}:complete",
        headers=student_headers,
        json={"idempotency_key": "complete-1", "occurred_at": now},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["delivery_status"] == "completed"
    repeated = support_client.post(
        f"/api/v1/student/resource-inbox/{item['exposure_id']}:complete",
        headers=student_headers,
        json={"idempotency_key": "complete-1", "occurred_at": now},
    )
    assert repeated.status_code == 200
    with support_client.app.state.db.session_factory() as db:
        exposure = db.get(ResourceExposure, item["exposure_id"])
        assert exposure.open_event_id is not None
        assert exposure.completion_event_id is not None
        event = db.get(LearningEvent, exposure.completion_event_id)
        assert event.event_type == "resource_completed"
        assert event.processing_status == "accepted"
        assert db.scalar(select(func.count()).select_from(DecisionPublication)) == 1


def test_decision_overview_initializes_snapshot_on_first_read(support_client):
    teacher_headers = login(support_client, "teacher")
    first = support_client.get(
        f"/api/v1/courses/{COURSE_ID}/teacher/overview",
        headers=teacher_headers,
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["course_id"] == COURSE_ID
    assert payload["student_count"] >= 48
    second = support_client.get(
        f"/api/v1/courses/{COURSE_ID}/teacher/overview",
        headers=teacher_headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["snapshot_id"] == payload["snapshot_id"]


def test_personalized_job_requires_real_handler_and_is_idempotent(support_client):
    teacher_headers = login(support_client, "teacher")
    refreshed = support_client.post(
        f"/api/v1/courses/{COURSE_ID}/decision-snapshots:refresh",
        headers=teacher_headers, json={},
    )
    assert refreshed.status_code == 201
    with support_client.app.state.db.session_factory() as db:
        student = db.scalar(select(User).where(User.email == "student@zhixing.edu.cn"))
        concept = db.scalar(select(Concept).where(
            Concept.course_id == COURSE_ID
        ).order_by(Concept.sort_order))
        student_id = student.id
        concept_id = concept.id
    payload = {
        "resource_type": "video",
        "concept_ids": [concept_id],
        "idempotency_key": "personal-video-1",
        "request_payload": {"teaching_intent": "错误辨析"},
    }
    unavailable = support_client.post(
        f"/api/v1/courses/{COURSE_ID}/students/{student_id}/personalized-resource-jobs",
        headers=teacher_headers, json=payload,
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "UPSTREAM_RESOURCE_HANDLER_UNAVAILABLE"
    with support_client.app.state.db.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PersonalizedResourceJob)) == 0

    calls = []

    def real_test_handler(**kwargs):
        calls.append(kwargs)
        return {"job_id": "upstream-video-job-1", "status": "queued"}

    support_client.app.state.personalized_resource_handlers = {"video": real_test_handler}
    created = support_client.post(
        f"/api/v1/courses/{COURSE_ID}/students/{student_id}/personalized-resource-jobs",
        headers=teacher_headers, json=payload,
    )
    assert created.status_code == 201, created.text
    duplicate = support_client.post(
        f"/api/v1/courses/{COURSE_ID}/students/{student_id}/personalized-resource-jobs",
        headers=teacher_headers, json=payload,
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == created.json()["id"]
    assert len(calls) == 1
