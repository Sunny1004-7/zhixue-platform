from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from app.domains.model_gateway.contracts import ProviderResponse
from app.domains.practice.grading import (
    grade_fill,
    grade_objective,
    grade_subjective_provisional,
)
from app.domains.practice.hints import validate_progressive_hints
from app.domains.practice.schemas import QuestionGenerationOutput
from app.models import (
    AuditEvent,
    EventConcept,
    LearningEvent,
    LearningResource,
    ModelAttempt,
    ModelProfile,
    ModelProfileRevision,
    ModelRun,
    PromptTemplate,
    QuestionGenerationRun,
    Score,
    TaskPolicy,
)


COURSE_ID = "machine-learning"
ALL_TYPES = ("single", "multiple", "judgment", "fill", "short", "scenario")


def _counts(**overrides: int) -> dict[str, int]:
    result = {item: 0 for item in ALL_TYPES}
    result.update(overrides)
    return result


def _compile(
    client,
    headers,
    *,
    source_method: str = "recorded",
    concepts: list[dict] | None = None,
    difficulty_mode: str = "standard",
    graph_id: str | None = None,
    alignment_run_id: str | None = None,
    requested_profile_id: str | None = None,
):
    payload = {
        "source_method": source_method,
        "difficulty_mode": difficulty_mode,
        "concepts": concepts or [{
            "concept_id": f"{COURSE_ID}:concept:01",
            "counts": _counts(single=1),
        }],
    }
    if graph_id is not None:
        payload["graph_id"] = graph_id
    if alignment_run_id is not None:
        payload["alignment_run_id"] = alignment_run_id
    if requested_profile_id is not None:
        payload["requested_profile_id"] = requested_profile_id
    return client.post(
        f"/api/v1/courses/{COURSE_ID}/practice-blueprints:compile",
        headers=headers,
        json=payload,
    )


def _configure_gpt(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("OPENAI_API_BASE", "https://model.test.invalid/v1")
    monkeypatch.setenv("OPENAI_MODEL_ID", "provider/test-practice-model")
    monkeypatch.setenv("ZHIXING_MODEL_ALLOWED_DATA_REGIONS", "deployment_configured")
    monkeypatch.setenv("ZHIXING_MODEL_ALLOWED_RETENTION_POLICIES", "provider_account_policy")


class PracticeGenerationAdapter:
    def __init__(self):
        self.calls = 0

    def invoke(self, request):
        self.calls += 1
        marker = "已审核的蓝图、知识点、证据和学习状态如下（JSON）：\n"
        suffix = "\n请按蓝图精确生成题组。"
        start = request.user_prompt.index(marker) + len(marker)
        end = request.user_prompt.index(suffix, start)
        context = json.loads(request.user_prompt[start:end])
        names = {item["concept_id"]: item["name"] for item in context["concepts"]}
        questions = []
        ordinal = 0
        for cell in context["cells"]:
            for _ in range(cell["count"]):
                ordinal += 1
                question_type = cell["question_type"]
                base = {
                    "blueprint_cell_id": cell["blueprint_cell_id"],
                    "question_type": question_type,
                    "prompt": _generated_prompt(question_type, names[cell["concept_id"]], ordinal),
                    "explanation": "本题依据审核蓝图生成，发布前仍需教师确认。",
                    "cognitive_level": cell["cognitive_level"],
                    "difficulty_prior": cell["difficulty_target"],
                    "hints": [
                        "先辨认题目要求比较的对象与范围。",
                        "逐项检查每个候选是否满足给定前提。",
                        "综合核对过程完整性与结论一致性。",
                    ],
                    "evidence_ids": [],
                }
                if question_type == "single":
                    base["options"] = [
                        {"content": "采用独立样例完成迁移检验", "is_correct": True},
                        {"content": "只记忆讲义中的最终句子", "is_correct": False, "misconception_code": "rote"},
                        {"content": "跳过条件直接选择最长表述", "is_correct": False, "misconception_code": "surface"},
                    ]
                elif question_type == "multiple":
                    base["options"] = [
                        {"content": "记录中间推导", "is_correct": True},
                        {"content": "检查输入范围", "is_correct": True},
                        {"content": "忽略冲突证据", "is_correct": False, "misconception_code": "ignore"},
                        {"content": "只保留最终数字", "is_correct": False, "misconception_code": "result-only"},
                    ]
                elif question_type == "judgment":
                    base["options"] = [
                        {"content": "正确", "is_correct": False, "misconception_code": "absolute"},
                        {"content": "错误", "is_correct": True},
                    ]
                elif question_type == "fill":
                    base.update({
                        "accepted_texts": [f"受控术语{ordinal}"],
                        "numeric_answer": None,
                        "absolute_tolerance": 0.0,
                        "relative_tolerance": 0.0,
                    })
                else:
                    base.update({
                        "reference_answer": (
                            f"先界定{names[cell['concept_id']]}的条件，"
                            "再说明处理过程并复核结论。"
                        ),
                        "rubric": [
                            {"criterion": "识别主要问题", "keywords": ["问题", "条件"], "weight": 0.3},
                            {"criterion": "提出处理步骤", "keywords": ["步骤", "过程"], "weight": 0.4},
                            {"criterion": "说明复核方法", "keywords": ["复核", "验证"], "weight": 0.3},
                        ],
                    })
                questions.append(base)
        return ProviderResponse(
            content=json.dumps({"questions": questions}, ensure_ascii=False),
            input_tokens=640,
            output_tokens=420,
        )


def _generated_prompt(question_type: str, concept: str, ordinal: int) -> str:
    templates = {
        "single": "学习{concept}时，哪项证据最能说明已经理解？（题{ordinal}）",
        "multiple": "围绕{concept}解决问题时，哪些过程需要保留？（题{ordinal}）",
        "judgment": "判断：学习{concept}只需记住一个结论，不必检查条件。（题{ordinal}）",
        "fill": "根据课程给出的定义填写对应规范名称。（题{ordinal}）",
        "short": "简要说明如何分析{concept}问题并核对结果。（题{ordinal}）",
        "scenario": "某方案在应用{concept}时遗漏前提，请分析影响并提出修正。（题{ordinal}）",
    }
    return templates[question_type].format(concept=concept, ordinal=ordinal)


def test_six_type_schema_hint_gate_and_grading_boundaries():
    payload = {"questions": []}
    common = {
        "explanation": "教师发布前需审核答案、提示与量规。",
        "cognitive_level": "understand",
        "difficulty_prior": 0.5,
        "hints": [
            "先确定题目要求识别的对象。",
            "再比较每种处理方式的适用前提。",
            "最后核对推理过程是否完整一致。",
        ],
        "evidence_ids": [],
    }
    for index, question_type in enumerate(ALL_TYPES, start=1):
        question = {
            **common,
            "blueprint_cell_id": f"cell-{index}",
            "question_type": question_type,
            "prompt": f"第{index}道{question_type}结构校验题。",
        }
        if question_type == "single":
            question["options"] = [
                {"content": "独立完成迁移任务", "is_correct": True},
                {"content": "仅抄录结论", "is_correct": False},
                {"content": "忽略适用条件", "is_correct": False},
            ]
        elif question_type == "multiple":
            question["options"] = [
                {"content": "核对输入", "is_correct": True},
                {"content": "保留步骤", "is_correct": True},
                {"content": "删除反例", "is_correct": False},
                {"content": "只看结果", "is_correct": False},
            ]
        elif question_type == "judgment":
            question["options"] = [
                {"content": "正确", "is_correct": False},
                {"content": "错误", "is_correct": True},
            ]
        elif question_type == "fill":
            question.update({
                "accepted_texts": ["梯度下降", "最速下降法"],
                "numeric_answer": None,
                "absolute_tolerance": 0.0,
                "relative_tolerance": 0.0,
            })
        else:
            question.update({
                "reference_answer": "明确问题边界，给出处理步骤，并说明验证依据。",
                "rubric": [
                    {"criterion": "问题边界", "keywords": ["边界"], "weight": 0.3},
                    {"criterion": "处理过程", "keywords": ["步骤"], "weight": 0.4},
                    {"criterion": "验证依据", "keywords": ["验证"], "weight": 0.3},
                ],
            })
        payload["questions"].append(question)
    output = QuestionGenerationOutput.model_validate(payload)
    assert [item.question_type for item in output.questions] == list(ALL_TYPES)

    invalid = json.loads(json.dumps(payload, ensure_ascii=False))
    invalid["questions"][1]["options"][1]["is_correct"] = False
    with pytest.raises(ValidationError):
        QuestionGenerationOutput.model_validate(invalid)

    leaked = validate_progressive_hints(
        ["先思考定义和条件。", "答案是A选项。", "最后复核过程。"],
        answer_texts=["梯度下降"],
    )
    assert leaked.passed is False
    assert "HINT_OPTION_LABEL_LEAK" in {item.code for item in leaked.issues}

    exact = grade_objective(
        question_type="multiple",
        answer={"selected_option_ids": ["a", "c"]},
        correct_option_ids={"a", "c"},
        valid_option_ids={"a", "b", "c"},
    )
    assert exact.score == 1.0 and exact.is_correct is True
    not_partial = grade_objective(
        question_type="multiple",
        answer={"selected_option_ids": ["a"]},
        correct_option_ids={"a", "c"},
        valid_option_ids={"a", "b", "c"},
    )
    assert not_partial.score == 0.0 and not_partial.is_correct is False
    normalized = grade_fill(
        answer={"text": " 10.05 "},
        answer_spec={
            "accepted_texts": ["十"],
            "numeric_answer": 10.0,
            "absolute_tolerance": 0.1,
        },
    )
    assert normalized.score == 1.0
    provisional = grade_subjective_provisional(
        answer={"text": "先说明问题边界，再检查过程。"},
        answer_spec={"reference_answer": "说明边界、过程和验证。"},
        rubric=[
            {"criterion": "问题边界", "keywords": ["边界"], "weight": 0.5},
            {"criterion": "验证过程", "keywords": ["检查"], "weight": 0.5},
        ],
    )
    assert provisional.review_status == "needs_review"
    assert provisional.confidence == 0.3
    assert provisional.is_correct is None


def test_seed_sets_are_real_published_resources_and_hide_answers(
    client, student_headers, teacher_headers
):
    student_list = client.get(
        f"/api/v1/student/courses/{COURSE_ID}/question-sets",
        headers=student_headers,
    )
    assert student_list.status_code == 200, student_list.text
    seeded = next(item for item in student_list.json()["items"] if item["id"] == "ml-q1")
    assert seeded["status"] == "published"
    assert seeded["source_kind"] == "curated_seed"
    assert seeded["total"] == 8
    assert seeded["completed"] == 3
    assert seeded["average_score"] == pytest.approx(2 / 3, abs=1e-4)

    student_detail = client.get("/api/v1/question-sets/ml-q1", headers=student_headers)
    assert student_detail.status_code == 200, student_detail.text
    body = student_detail.json()
    assert {item["type"] for item in body["questions"]} == set(ALL_TYPES)
    assert all("answer_spec" not in item for item in body["questions"])
    assert all("rubric" not in item for item in body["questions"])
    assert all(
        "is_correct" not in option
        for question in body["questions"]
        for option in question["options"]
    )
    assert "attempt_state" not in body["questions"][3]

    teacher_detail = client.get("/api/v1/question-sets/ml-q1", headers=teacher_headers)
    assert teacher_detail.status_code == 200
    teacher_body = teacher_detail.json()
    assert teacher_body["questions"][0]["answer_spec"]["kind"] == "option_set"
    assert any(option["is_correct"] for option in teacher_body["questions"][0]["options"])
    assert teacher_body["questions"][4]["rubric"]

    forbidden = client.get(
        f"/api/v1/teacher/courses/{COURSE_ID}/question-sets",
        headers=student_headers,
    )
    assert forbidden.status_code == 403


def test_four_blueprint_sources_and_exact_cell_counts(
    client, student_headers, teacher_headers
):
    recorded = _compile(
        client,
        teacher_headers,
        concepts=[
            {"concept_id": f"{COURSE_ID}:concept:01", "counts": _counts(single=2, fill=1)},
            {"concept_id": f"{COURSE_ID}:concept:02", "counts": _counts(multiple=1)},
        ],
    )
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["total"] == 4
    assert {
        (item["concept_id"], item["question_type"]): item["count"]
        for item in recorded.json()["cells"]
    } == {
        (f"{COURSE_ID}:concept:01", "single"): 2,
        (f"{COURSE_ID}:concept:01", "fill"): 1,
        (f"{COURSE_ID}:concept:02", "multiple"): 1,
    }

    history = _compile(
        client,
        student_headers,
        source_method="history",
        difficulty_mode="personalized",
        concepts=[{
            "concept_id": f"{COURSE_ID}:concept:04",
            "counts": _counts(single=1),
        }],
    )
    assert history.status_code == 201, history.text
    assert history.json()["source_summary"]["personalization_applied"] is True
    assert 0.2 <= history.json()["cells"][0]["difficulty_target"] <= 0.8

    graph_list = client.get(
        f"/api/v1/student/courses/{COURSE_ID}/graph-resources",
        headers=student_headers,
    ).json()
    graph_id = next(item["id"] for item in graph_list if item["id"] == "ml-g1")
    graph_detail = client.get(
        f"/api/v1/student/courses/{COURSE_ID}/graph-resources/{graph_id}",
        headers=student_headers,
    ).json()
    graph_concept = graph_detail["nodes"][0]["concept_id"]
    graph = _compile(
        client,
        student_headers,
        source_method="graph",
        graph_id=graph_id,
        concepts=[{"concept_id": graph_concept, "counts": _counts(judgment=1)}],
    )
    assert graph.status_code == 201, graph.text
    assert graph.json()["source_summary"]["graph_node_count"] == len(graph_detail["nodes"])
    assert graph.json()["source_summary"]["selected_concept_count"] == 1

    aligned = client.post(
        f"/api/v1/teacher/courses/{COURSE_ID}/alignment-runs",
        headers=teacher_headers,
        json={"manual_text": "线性回归；损失函数", "purpose": "question_generation"},
    )
    assert aligned.status_code == 201, aligned.text
    assert aligned.json()["status"] == "completed"
    alignment = _compile(
        client,
        teacher_headers,
        source_method="alignment",
        alignment_run_id=aligned.json()["id"],
        concepts=[{
            "concept_id": f"{COURSE_ID}:concept:03",
            "counts": _counts(scenario=1),
        }],
    )
    assert alignment.status_code == 201, alignment.text
    assert alignment.json()["source_summary"]["alignment_run_id"] == aligned.json()["id"]

    teacher_personalization = _compile(
        client,
        teacher_headers,
        source_method="history",
        difficulty_mode="personalized",
    )
    assert teacher_personalization.status_code == 422
    cross_course = _compile(
        client,
        student_headers,
        concepts=[{
            "concept_id": "ai-intro:concept:01",
            "counts": _counts(single=1),
        }],
    )
    assert cross_course.status_code == 422


def test_hint_sequence_attempt_idempotency_retry_and_event_recovery(client, student_headers):
    detail = client.get("/api/v1/question-sets/ml-q1", headers=student_headers).json()
    question = next(item for item in detail["questions"] if item["position"] == 4)

    skipped = client.post(
        f"/api/v1/student/questions/{question['id']}/hints/2:reveal",
        headers=student_headers,
        json={"idempotency_key": "hint-sequence-0002"},
    )
    assert skipped.status_code == 409
    first_hint = client.post(
        f"/api/v1/student/questions/{question['id']}/hints/1:reveal",
        headers=student_headers,
        json={"idempotency_key": "hint-sequence-0001"},
    )
    assert first_hint.status_code == 200, first_hint.text
    repeated_hint = client.post(
        f"/api/v1/student/questions/{question['id']}/hints/1:reveal",
        headers=student_headers,
        json={"idempotency_key": "hint-sequence-0001"},
    )
    assert repeated_hint.json() == first_hint.json()
    reused_hint_key = client.post(
        f"/api/v1/student/questions/{question['id']}/hints/2:reveal",
        headers=student_headers,
        json={"idempotency_key": "hint-sequence-0001"},
    )
    assert reused_hint_key.status_code == 409

    first_payload = {
        "idempotency_key": "attempt-fill-0001",
        "answer": {"text": " 损失函数。 "},
        "expected_revision_id": detail["revision_id"],
    }
    first = client.post(
        f"/api/v1/student/questions/{question['id']}/attempts",
        headers=student_headers,
        json=first_payload,
    )
    assert first.status_code == 200, first.text
    assert first.json()["attempt"]["attempt_no"] == 1
    assert first.json()["attempt"]["hint_level"] == 1
    assert first.json()["score"]["score"] == 1.0
    assert client.post(
        f"/api/v1/student/questions/{question['id']}/attempts",
        headers=student_headers,
        json=first_payload,
    ).json()["attempt"]["id"] == first.json()["attempt"]["id"]
    conflict = client.post(
        f"/api/v1/student/questions/{question['id']}/attempts",
        headers=student_headers,
        json={**first_payload, "answer": {"text": "其他答案"}},
    )
    assert conflict.status_code == 409

    second_payload = {
        **first_payload,
        "idempotency_key": "attempt-fill-0002",
        "answer": {"text": "其他答案"},
    }
    second = client.post(
        f"/api/v1/student/questions/{question['id']}/attempts",
        headers=student_headers,
        json=second_payload,
    )
    assert second.status_code == 200, second.text
    assert second.json()["attempt"]["attempt_no"] == 2
    assert second.json()["score"]["score"] == 0.0
    score = client.get(
        f"/api/v1/student/attempts/{second.json()['attempt']['id']}/score",
        headers=student_headers,
    )
    assert score.status_code == 200
    assert score.json()["attempt_id"] == second.json()["attempt"]["id"]

    with client.app.state.db.session_factory() as db:
        second_events = list(db.scalars(select(LearningEvent).where(
            LearningEvent.object_id.in_([
                second.json()["attempt"]["id"],
                second.json()["score"]["attempt_id"],
            ])
        )).all())
        event_types = {item.event_type for item in second_events}
        assert {"answer_submitted", "question_retried"}.issubset(event_types)
        scored = db.scalar(select(LearningEvent).where(
            LearningEvent.idempotency_key == f"a3:answer-scored:{second.json()['attempt']['id']}"
        ))
        assert scored is not None and scored.event_type == "answer_scored"
        submitted = db.scalar(select(LearningEvent).where(
            LearningEvent.idempotency_key == f"a3:answer-submitted:{second.json()['attempt']['id']}"
        ))
        db.execute(delete(EventConcept).where(EventConcept.event_id == submitted.id))
        db.delete(submitted)
        db.commit()

    recovered = client.post(
        f"/api/v1/student/questions/{question['id']}/attempts",
        headers=student_headers,
        json=second_payload,
    )
    assert recovered.status_code == 200
    with client.app.state.db.session_factory() as db:
        repaired_count = db.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.idempotency_key == f"a3:answer-submitted:{second.json()['attempt']['id']}"
        ))
        assert repaired_count == 1
        assert db.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.event_type == "hint_viewed",
            LearningEvent.object_id == question["id"],
        )) == 1

    progress = client.get(
        "/api/v1/student/question-sets/ml-q1/progress",
        headers=student_headers,
    ).json()
    assert progress["completed"] == 4
    q4 = next(item for item in progress["items"] if item["position"] == 4)
    assert q4["attempt_id"] == second.json()["attempt"]["id"]
    assert q4["hint_level"] == 1


def test_completing_seed_set_emits_all_a1_events_and_updates_resource(client, student_headers):
    detail = client.get("/api/v1/question-sets/ml-q1", headers=student_headers).json()
    by_position = {item["position"]: item for item in detail["questions"]}
    answers = {
        4: {"text": "损失函数"},
        5: {"text": "先定义目标，计算梯度并更新参数，最后检查收敛条件。"},
        6: {"text": "步长过大会造成振荡，应降低取值并观察损失曲线。"},
        7: {"selected_option_ids": [by_position[7]["options"][0]["id"]]},
        8: {"text": "特征工程"},
    }
    client.post(
        f"/api/v1/student/questions/{by_position[4]['id']}/hints/1:reveal",
        headers=student_headers,
        json={"idempotency_key": "complete-hint-0001"},
    )
    for position, answer in answers.items():
        response = client.post(
            f"/api/v1/student/questions/{by_position[position]['id']}/attempts",
            headers=student_headers,
            json={
                "idempotency_key": f"complete-attempt-{position:04d}",
                "answer": answer,
                "expected_revision_id": detail["revision_id"],
            },
        )
        assert response.status_code == 200, response.text

    progress = client.get(
        "/api/v1/student/question-sets/ml-q1/progress",
        headers=student_headers,
    ).json()
    assert progress["completed"] == progress["total"] == 8
    with client.app.state.db.session_factory() as db:
        event_types = set(db.scalars(select(LearningEvent.event_type).where(
            LearningEvent.course_id == COURSE_ID
        )).all())
        assert {
            "hint_viewed", "answer_submitted", "answer_scored", "question_set_completed",
        }.issubset(event_types)
        assert db.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.event_type == "question_set_completed",
            LearningEvent.object_id == "ml-q1",
        )) == 1
        resource = db.get(LearningResource, "ml-q1")
        assert resource.progress_completed == 8
        assert resource.progress_total == 8


def test_model_unavailable_is_explicit_and_audited(
    client, teacher_headers, monkeypatch
):
    for key in (
        "OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_MODEL_ID",
        "ZHIXING_MODEL_ALLOWED_DATA_REGIONS", "ZHIXING_MODEL_ALLOWED_RETENTION_POLICIES",
    ):
        monkeypatch.delenv(key, raising=False)
    profiles = client.get(
        "/api/v1/model-profiles?task_kind=a3.question_generation",
        headers=teacher_headers,
    )
    assert profiles.status_code == 200
    gpt = next(item for item in profiles.json() if item["id"] == "gpt-5")
    assert gpt["available"] is False
    assert "question_generation" in gpt["capabilities"]

    blueprint = _compile(
        client,
        teacher_headers,
        requested_profile_id="gpt-5",
    )
    assert blueprint.status_code == 201
    generated = client.post(
        f"/api/v1/courses/{COURSE_ID}/question-sets:generate",
        headers=teacher_headers,
        json={
            "blueprint_id": blueprint.json()["id"],
            "title": "模型不可用边界测试",
            "requested_profile_id": "gpt-5",
            "idempotency_key": "practice-unavailable-0001",
        },
    )
    assert generated.status_code == 503, generated.text
    assert generated.json()["detail"]["code"] == "MODEL_PROFILE_NOT_FEASIBLE"
    with client.app.state.db.session_factory() as db:
        run = db.scalar(select(ModelRun).where(
            ModelRun.idempotency_key == "practice-unavailable-0001"
        ))
        assert run is not None
        assert run.status == "failed"
        assert run.safe_error
        assert db.scalar(select(QuestionGenerationRun).where(
            QuestionGenerationRun.model_run_id == run.id
        )).status == "failed"


def test_seed_configures_a3_and_a5_structured_model_tasks(client):
    expected = {
        "a3.question_generation": "question_generation",
        "a5.tutor_reply": "tutoring",
        "a5.experience_generation": "tutoring",
    }
    with client.app.state.db.session_factory() as db:
        profile = db.get(ModelProfile, "gpt-5")
        revision = db.get(ModelProfileRevision, "gpt-5:rev:1")
        assert set(expected).issubset(set(profile.task_kinds))
        assert set(expected.values()).issubset(set(revision.capabilities_json))
        for task_kind, capability in expected.items():
            policy = db.scalar(select(TaskPolicy).where(
                TaskPolicy.task_kind == task_kind,
                TaskPolicy.enabled.is_(True),
            ))
            prompt = db.scalar(select(PromptTemplate).where(
                PromptTemplate.task_kind == task_kind,
                PromptTemplate.active.is_(True),
            ))
            assert policy is not None
            assert capability in policy.required_capabilities_json
            assert prompt is not None
            assert "{context_json}" in prompt.user_template
            assert "{schema_json}" in prompt.user_template or task_kind == "a3.question_generation"


def test_model_gateway_generation_teacher_review_publish_and_idempotency(
    client, teacher_headers, student_headers, monkeypatch
):
    _configure_gpt(monkeypatch)
    adapter = PracticeGenerationAdapter()
    client.app.state.model_adapter_registry["openai"] = adapter
    concepts = [
        {
            "concept_id": f"{COURSE_ID}:concept:{index:02d}",
            "counts": _counts(**{question_type: 1}),
        }
        for index, question_type in enumerate(ALL_TYPES, start=1)
    ]
    blueprint = _compile(
        client,
        teacher_headers,
        concepts=concepts,
        difficulty_mode="balanced",
        requested_profile_id="gpt-5",
    )
    assert blueprint.status_code == 201, blueprint.text
    payload = {
        "blueprint_id": blueprint.json()["id"],
        "title": "六题型模型生成审核组",
        "requested_profile_id": "gpt-5",
        "idempotency_key": "practice-generate-0001",
    }
    generated = client.post(
        f"/api/v1/courses/{COURSE_ID}/question-sets:generate",
        headers=teacher_headers,
        json=payload,
    )
    assert generated.status_code == 201, generated.text
    body = generated.json()
    assert body["status"] == "draft"
    assert body["quality_status"] == "passed"
    assert body["total"] == 6
    assert {item["type"] for item in body["questions"]} == set(ALL_TYPES)
    assert body["model_run"]["status"] == "validated"
    assert adapter.calls == 1

    repeated = client.post(
        f"/api/v1/courses/{COURSE_ID}/question-sets:generate",
        headers=teacher_headers,
        json=payload,
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == body["id"]
    assert adapter.calls == 1
    conflicting = client.post(
        f"/api/v1/courses/{COURSE_ID}/question-sets:generate",
        headers=teacher_headers,
        json={**payload, "title": "改变后的标题"},
    )
    assert conflicting.status_code == 409

    question = next(item for item in body["questions"] if item["type"] == "single")
    edit_options = [
        {
            "id": option["id"],
            "content": option["content"],
            "is_correct": option["is_correct"],
        }
        for option in question["options"]
    ]
    updated = client.patch(
        f"/api/v1/teacher/questions/{question['id']}",
        headers=teacher_headers,
        json={
            "expected_revision_version": body["revision_version"],
            "prompt": question["prompt"] + "（教师已复核题干）",
            "options": edit_options,
            "answer_spec": question["answer_spec"],
            "rubric": question["rubric"],
            "explanation": question["explanation"],
            "cognitive_level": question["cognitive_level"],
            "difficulty_prior": question["difficulty_prior"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision_version"] == body["revision_version"] + 1
    stale = client.patch(
        f"/api/v1/teacher/questions/{question['id']}",
        headers=teacher_headers,
        json={
            "expected_revision_version": body["revision_version"],
            "prompt": question["prompt"],
            "options": edit_options,
            "answer_spec": question["answer_spec"],
            "rubric": question["rubric"],
            "explanation": question["explanation"],
            "cognitive_level": question["cognitive_level"],
            "difficulty_prior": question["difficulty_prior"],
        },
    )
    assert stale.status_code == 409

    validated = client.post(
        f"/api/v1/teacher/question-sets/{body['id']}:validate",
        headers=teacher_headers,
        json={"expected_revision_version": updated.json()["revision_version"]},
    )
    assert validated.status_code == 200, validated.text
    assert validated.json()["status"] == "validated"
    published = client.post(
        f"/api/v1/teacher/question-sets/{body['id']}:publish",
        headers=teacher_headers,
        json={"expected_revision_version": validated.json()["revision_version"]},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    immutable = client.patch(
        f"/api/v1/teacher/questions/{question['id']}",
        headers=teacher_headers,
        json={
            "expected_revision_version": published.json()["revision_version"],
            "prompt": question["prompt"],
            "options": edit_options,
            "answer_spec": question["answer_spec"],
            "rubric": question["rubric"],
            "explanation": question["explanation"],
            "cognitive_level": question["cognitive_level"],
            "difficulty_prior": question["difficulty_prior"],
        },
    )
    assert immutable.status_code == 409

    student_detail = client.get(
        f"/api/v1/question-sets/{body['id']}",
        headers=student_headers,
    )
    assert student_detail.status_code == 200
    assert all("answer_spec" not in item for item in student_detail.json()["questions"])
    assert all(
        "is_correct" not in option
        for item in student_detail.json()["questions"]
        for option in item["options"]
    )
    with client.app.state.db.session_factory() as db:
        run = db.scalar(select(ModelRun).where(ModelRun.idempotency_key == payload["idempotency_key"]))
        assert run.status == "validated"
        assert run.output_hash and run.audit_hash and run.prompt_hash
        assert run.usage_json["input_tokens"] == 640
        assert run.usage_json["output_tokens"] == 420
        assert run.usage_json["profile_revision_id"] == "gpt-5:rev:1"
        assert db.scalar(select(func.count()).select_from(ModelAttempt).where(
            ModelAttempt.run_id == run.id
        )) == 1
        generation = db.scalar(select(QuestionGenerationRun).where(
            QuestionGenerationRun.model_run_id == run.id
        ))
        assert generation.status == "completed"
        assert generation.accepted_count == 6


def test_teacher_reviews_low_confidence_subjective_score_and_replays_trajectory(
    client, student_headers, teacher_headers
):
    detail = client.get("/api/v1/question-sets/ml-q1", headers=student_headers).json()
    question = next(item for item in detail["questions"] if item["position"] == 5)
    submitted = client.post(
        f"/api/v1/student/questions/{question['id']}/attempts",
        headers=student_headers,
        json={
            "idempotency_key": "subjective-review-attempt-0001",
            "expected_revision_id": detail["revision_id"],
            "answer": {"text": "先定义目标，计算梯度并更新参数，最后检查收敛条件。"},
        },
    )
    assert submitted.status_code == 200, submitted.text
    attempt = submitted.json()["attempt"]
    assert submitted.json()["score"]["review_status"] == "needs_review"
    forbidden = client.post(
        f"/api/v1/teacher/attempts/{attempt['id']}:review",
        headers=student_headers,
        json={"score": 0.85, "is_correct": None},
    )
    assert forbidden.status_code == 403

    reviewed = client.post(
        f"/api/v1/teacher/attempts/{attempt['id']}:review",
        headers=teacher_headers,
        json={
            "score": 0.85,
            "is_correct": None,
            "feedback": {"summary": "覆盖主要步骤"},
            "review_note": "教师复核：步骤完整，保留少量表达扣分。",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["attempt_id"] == attempt["id"]
    assert body["score"] == pytest.approx(0.85)
    assert body["confidence"] == 1.0
    assert body["grading_mode"] == "teacher_review"
    assert body["review_status"] == "reviewed"

    repeated = client.post(
        f"/api/v1/teacher/attempts/{attempt['id']}/review",
        headers=teacher_headers,
        json={
            "score": 0.85,
            "is_correct": None,
            "feedback": {"summary": "覆盖主要步骤"},
            "review_note": "教师复核：步骤完整，保留少量表达扣分。",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json() == body

    changed = client.post(
        f"/api/v1/teacher/attempts/{attempt['id']}:review",
        headers=teacher_headers,
        json={
            "score": 0.95,
            "is_correct": None,
            "feedback": {"summary": "覆盖主要步骤"},
            "review_note": "重新改分",
        },
    )
    assert changed.status_code == 409

    with client.app.state.db.session_factory() as db:
        reviewed_event = db.scalar(select(LearningEvent).where(
            LearningEvent.idempotency_key == f"a3:answer-reviewed:{attempt['id']}"
        ))
        original_event = db.scalar(select(LearningEvent).where(
            LearningEvent.idempotency_key == f"a3:answer-scored:{attempt['id']}"
        ))
        score = db.scalar(select(Score).where(Score.attempt_id == attempt["id"]))
        assert reviewed_event is not None
        assert reviewed_event.correction_of_event_id == original_event.id
        audit = db.scalar(select(AuditEvent).where(
            AuditEvent.action == "practice.attempt.reviewed",
            AuditEvent.object_id == score.id,
        ))
        assert audit is not None
