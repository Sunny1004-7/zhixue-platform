from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.domains.teaching_decision.audience import StudentConceptState, classify_state, resolve_audience
from app.domains.teaching_decision.publication import _state_rows
from app.domains.trajectory.evidence import classify_state as trajectory_classify_state
from app.models import KnowledgeState, LearningEvent, User


COURSE = "machine-learning"


def graph_card(client, headers):
    graph = client.get(f"/api/v1/student/courses/{COURSE}/graph-resources/ml-g1", headers=headers).json()
    return graph, graph["nodes"][0]


def observation(graph, node, key="browser-card-boundary"):
    return {
        "idempotency_key": key, "event_type": "knowledge_card_opened",
        "object_type": "knowledge_graph_node", "object_id": node["id"],
        "concepts": [{"concept_id": node["concept_id"], "weight": 1}],
        "completion": 1, "upstream_confidence": 0, "alignment_confidence": 0,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"graph_id": graph["id"], "dwell_seconds": 60, "foreground_ratio": .9},
    }


@pytest.mark.parametrize("event_type", [
    "answer_scored", "inline_practice_scored", "tutor_message_received",
    "video_completed", "experience_confirmed",
])
def test_browser_cannot_impersonate_grading_or_other_result_services(client, student_headers, event_type):
    graph, node = graph_card(client, student_headers)
    payload = observation(graph, node)
    payload.update(event_type=event_type, outcome=1, upstream_confidence=1, alignment_confidence=1)
    payload["object_id"] = "unverified-result-reference"
    payload["payload"]["grading_mode"] = "objective_rule"
    with client.app.state.db.session_factory() as db:
        count = db.scalar(select(func.count()).select_from(LearningEvent))
    before = client.get(f"/api/v1/student/courses/{COURSE}/mastery", headers=student_headers).json()
    response = client.post(f"/api/v1/student/courses/{COURSE}/events", headers=student_headers, json=payload)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVER_RESULT_REQUIRED"
    assert client.get(f"/api/v1/student/courses/{COURSE}/mastery", headers=student_headers).json() == before
    with client.app.state.db.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == count


def test_published_card_is_resolved_on_server_and_duplicate_is_not_counted_twice(client, student_headers):
    graph, node = graph_card(client, student_headers)
    payload = observation(graph, node)
    payload["payload"]["grading_mode"] = "objective_rule"
    response = client.post(f"/api/v1/student/courses/{COURSE}/events", headers=student_headers, json=payload)
    assert response.status_code == 200, response.text
    assert 0 < response.json()["evidence_reliability"] <= .25
    again = client.post(f"/api/v1/student/courses/{COURSE}/events", headers=student_headers, json=payload)
    assert again.status_code == 200 and again.json()["duplicate"] is True
    with client.app.state.db.session_factory() as db:
        event = db.get(LearningEvent, response.json()["event_id"])
        assert event.outcome is None
        assert event.upstream_confidence == node["confidence"]
        assert event.alignment_confidence == node["confidence"]
        assert event.completion == .5  # Derived from dwell; supplied completion=1 is ignored.
        assert "grading_mode" not in event.payload
        assert event.payload["revision_id"] == graph["revision_id"]


@pytest.mark.parametrize("mutation,expected", [
    ("missing_node", 422), ("different_concept", 422), ("different_course", 404),
    ("malformed_graph", 422), ("grade_on_card", 422), ("correction_on_card", 422),
    ("invalid_dwell", 422),
])
def test_browser_observation_rejects_unverified_references_and_scores(client, student_headers, mutation, expected):
    graph, node = graph_card(client, student_headers)
    payload = observation(graph, node)
    if mutation == "missing_node": payload["object_id"] = "missing-node"
    if mutation == "different_concept": payload["concepts"][0]["concept_id"] = "ai-intro:concept:01"
    if mutation == "different_course": payload["payload"]["graph_id"] = "ai-g1"
    if mutation == "malformed_graph": payload["payload"]["graph_id"] = ["ml-g1"]
    if mutation == "grade_on_card": payload["outcome"] = 1
    if mutation == "correction_on_card": payload["correction_of_event_id"] = "forged-correction"
    if mutation == "invalid_dwell": payload["payload"]["dwell_seconds"] = "NaN"
    response = client.post(f"/api/v1/student/courses/{COURSE}/events", headers=student_headers, json=payload)
    assert response.status_code == expected, response.text


def test_opening_a_graph_node_does_not_count_as_effective_learning(client, student_headers):
    graph, node = graph_card(client, student_headers)
    payload = observation(graph, node)
    payload["event_type"] = "graph_node_viewed"
    payload["payload"]["dwell_seconds"] = 999999
    response = client.post(f"/api/v1/student/courses/{COURSE}/events", headers=student_headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["processing_status"] == "observed_only"
    assert response.json()["changes"] == []


@pytest.mark.parametrize("mastery,evidence,uncertainty", [
    (49, 2.499, .1), (80, 10, .4501), (49, 2.5, .45), (50, 2.5, .45),
])
def test_audience_classification_uses_trajectory_evidence_boundaries(mastery, evidence, uncertainty):
    state = StudentConceptState("s", "c", "k", mastery, 1, 1-uncertainty, evidence, uncertainty)
    assert classify_state(state) == trajectory_classify_state(mastery/100, evidence, uncertainty)


@pytest.mark.parametrize("mastery,evidence,uncertainty,expected", [
    (49, 2.499, .1, "unseen"), (49, 5, .3, "weak"), (50, 5, .3, "mastered"),
])
def test_cached_category_cannot_override_shared_state_rules(
    client, student_headers, teacher_headers, mastery, evidence, uncertainty, expected,
):
    graph, node = graph_card(client, student_headers)
    with client.app.state.db.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "student@zhixing.edu.cn"))
        user_id = user.id
        state = db.scalar(select(KnowledgeState).where(
            KnowledgeState.student_id == user_id, KnowledgeState.concept_id == node["concept_id"],
        ))
        state.mastery = mastery
        state.effective_evidence = evidence
        state.uncertainty = uncertainty
        state.evidence_count = 4 if expected == "unseen" else 0
        state.confidence = 1 - uncertainty
        state.status = "mastered" if expected != "mastered" else "unseen"
        db.commit()
    student = next(s for s in client.get(f"/api/v1/student/courses/{COURSE}/mastery", headers=student_headers).json()
                   if s["concept_id"] == node["concept_id"])
    graph_after, _ = graph_card(client, student_headers)
    graph_node = next(n for n in graph_after["nodes"] if n["id"] == node["id"])
    refresh = client.post(f"/api/v1/courses/{COURSE}/decision-snapshots:refresh", headers=teacher_headers, json={})
    assert refresh.status_code == 201, refresh.text
    teacher = client.get(f"/api/v1/courses/{COURSE}/students/{user_id}/learning-state", headers=teacher_headers)
    assert teacher.status_code == 200, teacher.text
    teacher_state = next(s for s in teacher.json()["concepts"] if s["concept_id"] == node["concept_id"])
    audience = client.post(
        f"/api/v1/teacher/courses/{COURSE}/resources/{graph['id']}/audience-drafts",
        headers=teacher_headers, json={"resource_type": "graph", "resource_id": graph["id"],
                                     "audience_mode": "class", "selected_concept_ids": [node["concept_id"]]},
    )
    assert audience.status_code == 201, audience.text
    candidate = next(s for s in audience.json()["candidates"] if s["student_id"] == user_id)
    assert candidate["matched_states"] == [expected]
    assert "LOW_EVIDENCE" in candidate["reason_codes"]
    with client.app.state.db.session_factory() as db:
        rows = _state_rows(db, course_id=COURSE, student_ids=[user_id], concept_ids=[node["concept_id"]])
        assert classify_state(rows[0]) == expected
    assert student["state"] == graph_node["mastery_state"] == teacher_state["state"] == expected


def test_cold_start_state_matches_student_teacher_and_resource_audience(client, student_headers, teacher_headers):
    graph, node = graph_card(client, student_headers)
    with client.app.state.db.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "student@zhixing.edu.cn"))
        user_id = user.id
        state = db.scalar(select(KnowledgeState).where(
            KnowledgeState.student_id == user_id, KnowledgeState.concept_id == node["concept_id"],
        ))
        state.alpha = state.beta = state.baseline_alpha = state.baseline_beta = 1
        state.mastery = 50
        state.evidence_count = 0
        state.effective_evidence = 2
        state.uncertainty = .577
        state.status = "unseen"
        state.last_evidence_at = None
        db.commit()
    response = client.post(f"/api/v1/student/courses/{COURSE}/events", headers=student_headers,
                           json=observation(graph, node))
    assert response.status_code == 200, response.text
    student = next(s for s in client.get(f"/api/v1/student/courses/{COURSE}/mastery", headers=student_headers).json()
                   if s["concept_id"] == node["concept_id"])
    refresh = client.post(f"/api/v1/courses/{COURSE}/decision-snapshots:refresh", headers=teacher_headers, json={})
    assert refresh.status_code == 201, refresh.text
    teacher_response = client.get(f"/api/v1/courses/{COURSE}/students/{user_id}/learning-state", headers=teacher_headers)
    assert teacher_response.status_code == 200, teacher_response.text
    teacher = next(s for s in teacher_response.json()["concepts"] if s["concept_id"] == node["concept_id"])
    assert student["effective_evidence"] < 2.5 and student["uncertainty"] > .45
    assert student["state"] == teacher["state"] == "unseen"
    assert teacher["low_evidence"] is True
    graph_after, _ = graph_card(client, student_headers)
    graph_node = next(n for n in graph_after["nodes"] if n["id"] == node["id"])
    assert graph_node["mastery_state"] == student["state"]
    with client.app.state.db.session_factory() as db:
        rows = _state_rows(db, course_id=COURSE, student_ids=[user_id], concept_ids=[node["concept_id"]])
        assert resolve_audience(rows, course_id=COURSE, resource_concept_ids=[node["concept_id"]], selected_states={"weak"}) == []
        matched = resolve_audience(rows, course_id=COURSE, resource_concept_ids=[node["concept_id"]], selected_states={"unseen"})
        assert matched[0].student_id == user_id and matched[0].matched_states == ("unseen",)
