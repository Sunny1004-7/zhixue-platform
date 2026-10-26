from __future__ import annotations

from conftest import ingest_trusted_event

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import (
    AlignmentReview,
    Concept,
    GraphEvidenceLink,
    GraphNode,
    GraphRevision,
    KnowledgeGraph,
)


COURSE_ID = "machine-learning"


def _event_payload(key: str, concept_id: str, outcome: float, occurred_at: datetime) -> dict:
    return {
        "idempotency_key": key,
        "event_type": "answer_scored",
        "object_type": "question",
        "object_id": key,
        "concepts": [{"concept_id": concept_id, "weight": 1}],
        "outcome": outcome,
        "difficulty": 0.7,
        "hint_level": 0,
        "attempt_no": 1,
        "upstream_confidence": 1,
        "alignment_confidence": 1,
        "occurred_at": occurred_at.isoformat(),
        "payload": {"grading_mode": "objective_rule"},
    }


def test_clean_sqlite_a2_novel_concept_merge_draft_and_publish_gate(
    client, teacher_headers, student_headers,
):
    aligned = client.post(
        f"/api/v1/teacher/courses/{COURSE_ID}/alignment-runs",
        headers=teacher_headers,
        json={"manual_text": "量子引力；量子引力", "purpose": "graph_build"},
    )
    assert aligned.status_code == 201, aligned.text
    mentions = aligned.json()["mentions"]
    assert len(mentions) == 2
    assert all(item["review"]["status"] == "pending" for item in mentions)

    decided = client.post(
        f"/api/v1/teacher/alignment-reviews/{mentions[0]['review']['id']}:decide",
        headers=teacher_headers,
        json={
            "decision": "created",
            "new_concept_name": "量子引力导论",
            "note": "教师确认为课程扩展概念",
        },
    )
    assert decided.status_code == 200, decided.text
    decision_body = decided.json()
    selected_ids = {
        item["review"]["selected_concept_id"] for item in decision_body["mentions"]
    }
    assert len(selected_ids) == 1
    concept_id = selected_ids.pop()
    assert {item["review"]["decision"] for item in decision_body["mentions"]} == {
        "created", "matched",
    }

    with client.app.state.db.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Concept).where(
            Concept.course_id == COURSE_ID,
            Concept.name == "量子引力导论",
        )) == 1
        reviews = db.scalars(select(AlignmentReview).where(
            AlignmentReview.selected_concept_id == concept_id,
        )).all()
        assert len(reviews) == 2

    graph_response = client.post(
        f"/api/v1/teacher/courses/{COURSE_ID}/graphs",
        headers=teacher_headers,
        json={"title": "A1 A2 清洁库联合验收图谱"},
    )
    assert graph_response.status_code == 201, graph_response.text
    graph = graph_response.json()
    applied = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}/alignment-runs/{decision_body['id']}:apply",
        headers=teacher_headers,
        json={"expected_revision_version": graph["version"]},
    )
    assert applied.status_code == 200, applied.text
    draft = applied.json()
    assert draft["revision_status"] == "draft"
    assert [(node["concept_id"], node["label"]) for node in draft["nodes"]] == [
        (concept_id, "量子引力导论"),
    ]

    hidden = client.get(
        f"/api/v1/student/courses/{COURSE_ID}/graph-resources/{graph['id']}",
        headers=student_headers,
    )
    assert hidden.status_code == 404

    blocked = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}:publish",
        headers=teacher_headers,
        json={"expected_revision_version": draft["version"]},
    )
    assert blocked.status_code == 422, blocked.text
    issue_codes = {item["code"] for item in blocked.json()["detail"]["issues"]}
    assert {"too_few_nodes", "missing_definition"}.issubset(issue_codes)

    novel_node = draft["nodes"][0]
    defined = client.patch(
        f"/api/v1/teacher/graphs/{graph['id']}/nodes/{novel_node['id']}",
        headers=teacher_headers,
        json={
            "expected_revision_version": draft["version"],
            "definition": "研究量子理论与引力相容性的课程扩展概念。",
            "teacher_evidence_note": "教师确认该概念用于课程拓展单元。",
        },
    )
    assert defined.status_code == 200, defined.text
    companion = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}/nodes",
        headers=teacher_headers,
        json={
            "expected_revision_version": defined.json()["version"],
            "label": "广义相对论拓展",
            "node_type": "foundation",
            "definition": "用于连接时空几何与引力描述的拓展知识点。",
            "teacher_evidence_note": "教师确认的课程拓展先备知识。",
            "position_x": 420,
            "position_y": 180,
        },
    )
    assert companion.status_code == 200, companion.text
    published = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}:publish",
        headers=teacher_headers,
        json={"expected_revision_version": companion.json()["version"]},
    )
    assert published.status_code == 200, published.text
    assert published.json()["review_status"] == "teacher_validated"
    assert published.json()["quality"]["hard_pass"] is True

    visible = client.get(
        f"/api/v1/student/courses/{COURSE_ID}/graph-resources/{graph['id']}",
        headers=student_headers,
    )
    assert visible.status_code == 200, visible.text
    assert {node["label"] for node in visible.json()["nodes"]} == {
        "量子引力导论", "广义相对论拓展",
    }


def test_clean_sqlite_a1_temporal_residual_and_a2_downstream_replay(
    client, student_headers,
):
    mastery = client.get(
        f"/api/v1/student/courses/{COURSE_ID}/mastery",
        headers=student_headers,
    )
    assert mastery.status_code == 200, mastery.text
    concept_ids = {item["label"]: item["concept_id"] for item in mastery.json()}
    prerequisite_id = concept_ids["损失函数"]
    target_id = concept_ids["梯度下降"]
    now = datetime.now(timezone.utc)

    first = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=_event_payload("a1a2-target-event-1", target_id, 1, now - timedelta(minutes=2)),
    )
    assert first.status_code == 200, first.text
    second = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=_event_payload("a1a2-target-event-2", target_id, 1, now - timedelta(minutes=1)),
    )
    assert second.status_code == 200, second.text
    target_change = next(item for item in second.json()["changes"] if item["concept_id"] == target_id)
    assert "temporal-evidence-1.0" in target_change["model_version"]

    prerequisite_payload = _event_payload(
        "a1a2-prerequisite-event", prerequisite_id, 0, now,
    )
    propagated = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=prerequisite_payload,
    )
    assert propagated.status_code == 200, propagated.text
    changes = {item["concept_id"]: item for item in propagated.json()["changes"]}
    assert prerequisite_id in changes
    assert target_id in changes
    assert "temporal-evidence-1.0" in changes[target_id]["model_version"]
    assert "+a2-graph" in changes[target_id]["model_version"]

    duplicate = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=prerequisite_payload,
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["duplicate"] is True


def test_clean_sqlite_enforces_graph_delete_cascades(client, teacher_headers):
    graph_response = client.post(
        f"/api/v1/teacher/courses/{COURSE_ID}/graphs",
        headers=teacher_headers,
        json={"title": "SQLite 外键级联验收图谱"},
    )
    assert graph_response.status_code == 201, graph_response.text
    graph = graph_response.json()
    created = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}/nodes",
        headers=teacher_headers,
        json={
            "expected_revision_version": graph["version"],
            "label": "级联删除知识点",
            "definition": "只用于验证清洁 SQLite 的真实外键级联。",
            "teacher_evidence_note": "数据库级联验收证据。",
        },
    )
    assert created.status_code == 200, created.text
    revision_id = created.json()["revision_id"]
    node_id = created.json()["nodes"][0]["id"]
    with client.app.state.db.session_factory() as db:
        evidence_id = db.scalar(select(GraphEvidenceLink.id).where(
            GraphEvidenceLink.node_id == node_id,
        ))
        assert evidence_id is not None

    deleted = client.delete(
        f"/api/v1/teacher/graphs/{graph['id']}"
        f"?expected_revision_version={created.json()['version']}",
        headers=teacher_headers,
    )
    assert deleted.status_code == 204, deleted.text
    with client.app.state.db.session_factory() as db:
        assert db.get(KnowledgeGraph, graph["id"]) is None
        assert db.get(GraphRevision, revision_id) is None
        assert db.get(GraphNode, node_id) is None
        assert db.get(GraphEvidenceLink, evidence_id) is None


def test_novel_concept_name_requires_normalized_content(client, teacher_headers):
    aligned = client.post(
        f"/api/v1/teacher/courses/{COURSE_ID}/alignment-runs",
        headers=teacher_headers,
        json={"manual_text": "未知概念", "purpose": "graph_build"},
    )
    assert aligned.status_code == 201, aligned.text
    review_id = aligned.json()["mentions"][0]["review"]["id"]
    rejected = client.post(
        f"/api/v1/teacher/alignment-reviews/{review_id}:decide",
        headers=teacher_headers,
        json={"decision": "created", "new_concept_name": "--"},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"] == "概念名称规范化后不能为空"
