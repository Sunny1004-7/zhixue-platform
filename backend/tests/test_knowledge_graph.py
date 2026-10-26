from __future__ import annotations

from types import SimpleNamespace

from app.domains.knowledge_graph.validation import validate_graph


COURSE_ID = "machine-learning"


def create_graph(client, teacher_headers, title="线性回归知识图谱·测试"):
    response = client.post(
        f"/api/v1/teacher/courses/{COURSE_ID}/graphs",
        headers=teacher_headers,
        json={"title": title, "source_summary": "教师手动建立的审核工作区"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_node(client, teacher_headers, graph_id, label, x):
    version = client.get(
        f"/api/v1/teacher/graphs/{graph_id}", headers=teacher_headers
    ).json()["version"]
    response = client.post(
        f"/api/v1/teacher/graphs/{graph_id}/nodes",
        headers=teacher_headers,
        json={
            "expected_revision_version": version,
            "label": label,
            "node_type": "foundation" if label == "矩阵运算" else "core",
            "definition": f"{label}的可审核定义。",
            "key_point": f"{label}的学习要点。",
            "misconception": f"{label}的常见误区。",
            "position_x": x,
            "position_y": 180,
        },
    )
    assert response.status_code == 200, response.text
    return next(node for node in response.json()["nodes"] if node["label"] == label)


def build_valid_graph(client, teacher_headers, title="线性回归知识图谱·测试"):
    graph = create_graph(client, teacher_headers, title)
    matrix = add_node(client, teacher_headers, graph["id"], "矩阵运算", 120)
    linear = add_node(client, teacher_headers, graph["id"], "线性回归", 360)
    response = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}/edges",
        headers=teacher_headers,
        json={
            "expected_revision_version": client.get(
                f"/api/v1/teacher/graphs/{graph['id']}", headers=teacher_headers
            ).json()["version"],
            "from_node_id": matrix["id"], "to_node_id": linear["id"],
            "relation": "prerequisite",
        },
    )
    assert response.status_code == 200, response.text
    return response.json(), matrix, linear


def test_teacher_can_edit_validate_publish_and_student_reads_mastery(client, teacher_headers, student_headers):
    graph, _, _ = build_valid_graph(client, teacher_headers)
    validated = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}:validate", headers=teacher_headers,
        json={"expected_revision_version": graph["version"]},
    )
    assert validated.status_code == 200, validated.text
    assert validated.json()["quality"]["hard_pass"] is True
    assert validated.json()["quality"]["metrics"]["node_count"] == 2

    published = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}:publish", headers=teacher_headers,
        json={"expected_revision_version": validated.json()["version"]},
    )
    assert published.status_code == 200, published.text
    assert published.json()["revision_status"] == "published"
    assert published.json()["review_status"] == "teacher_validated"

    listing = client.get(f"/api/v1/student/courses/{COURSE_ID}/graph-resources", headers=student_headers)
    assert listing.status_code == 200
    listed_ids = [item["id"] for item in listing.json()]
    assert graph["id"] in listed_ids
    assert {"ml-g1", "ml-g2"}.issubset(set(listed_ids))
    detail = client.get(
        f"/api/v1/student/courses/{COURSE_ID}/graph-resources/{graph['id']}",
        headers=student_headers,
    )
    assert detail.status_code == 200, detail.text
    by_label = {node["label"]: node for node in detail.json()["nodes"]}
    assert by_label["矩阵运算"]["mastery"] == 87
    assert by_label["线性回归"]["mastery_state"] == "mastered"


def test_prerequisite_cycle_blocks_publish(client, teacher_headers):
    graph, matrix, linear = build_valid_graph(client, teacher_headers, "先修环路测试图谱")
    response = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}/edges",
        headers=teacher_headers,
        json={
            "expected_revision_version": graph["version"],
            "from_node_id": linear["id"], "to_node_id": matrix["id"],
            "relation": "prerequisite",
        },
    )
    assert response.status_code == 200
    validated = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}:validate", headers=teacher_headers,
        json={"expected_revision_version": response.json()["version"]},
    )
    assert validated.status_code == 200
    assert validated.json()["quality"]["hard_pass"] is False
    assert "prerequisite_cycle" in {item["code"] for item in validated.json()["quality"]["issues"]}
    blocked = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}:publish", headers=teacher_headers,
        json={"expected_revision_version": validated.json()["version"]},
    )
    assert blocked.status_code == 422


def test_published_revision_is_immutable_and_update_revision_clones(client, teacher_headers):
    graph, _, _ = build_valid_graph(client, teacher_headers, "不可变修订测试图谱")
    published = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}:publish", headers=teacher_headers,
        json={"expected_revision_version": graph["version"]},
    )
    assert published.status_code == 200
    denied = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}/nodes",
        headers=teacher_headers,
        json={
            "expected_revision_version": published.json()["version"],
            "label": "损失函数", "definition": "测试",
        },
    )
    assert denied.status_code == 409
    update = client.post(f"/api/v1/teacher/graphs/{graph['id']}/revisions", headers=teacher_headers)
    assert update.status_code == 201, update.text
    assert update.json()["revision_no"] == 2
    assert update.json()["revision_status"] == "draft"
    assert len(update.json()["nodes"]) == 2
    assert len(update.json()["edges"]) == 1


def test_student_cannot_call_teacher_graph_workspace(client, student_headers):
    response = client.post(
        f"/api/v1/teacher/courses/{COURSE_ID}/graphs",
        headers=student_headers,
        json={"title": "越权图谱"},
    )
    assert response.status_code == 403


def test_editor_uses_optimistic_version_and_exposes_teacher_evidence(
    client, teacher_headers
):
    graph = create_graph(client, teacher_headers, "并发与证据编辑测试图谱")
    created = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}/nodes",
        headers=teacher_headers,
        json={
            "expected_revision_version": graph["version"],
            "label": "偏差与方差",
            "node_type": "core",
            "definition": "用于分析模型泛化误差的两个互补来源。",
            "key_point": "区分欠拟合与过拟合。",
            "misconception": "偏差与方差不能简单同时降为零。",
            "position_x": 240,
            "position_y": 180,
            "teacher_evidence_note": "依据本课程第4讲教学目标，由教师补充确认。",
        },
    )
    assert created.status_code == 200, created.text
    current = created.json()
    node = current["nodes"][0]
    assert current["version"] == graph["version"] + 1
    assert node["evidence_count"] == 1

    evidence = client.get(
        f"/api/v1/teacher/graphs/{graph['id']}/evidence/node/{node['id']}",
        headers=teacher_headers,
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["links"][0]["source_kind"] == "teacher_statement"
    assert "第4讲" in evidence.json()["links"][0]["assertion_note"]

    stale = client.patch(
        f"/api/v1/teacher/graphs/{graph['id']}/nodes/{node['id']}",
        headers=teacher_headers,
        json={
            "expected_revision_version": graph["version"],
            "definition": "过期页面试图覆盖的新定义",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "GRAPH_REVISION_CONFLICT"
    unchanged = client.get(
        f"/api/v1/teacher/graphs/{graph['id']}", headers=teacher_headers
    ).json()
    assert unchanged["nodes"][0]["definition"] == node["definition"]

    updated = client.patch(
        f"/api/v1/teacher/graphs/{graph['id']}/nodes/{node['id']}",
        headers=teacher_headers,
        json={
            "expected_revision_version": current["version"],
            "definition": "描述模型误差分解中的系统偏差与采样方差。",
            "teacher_evidence_note": "依据本课程第4讲误差分解例题，由教师复核。",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == current["version"] + 1
    evidence_after = client.get(
        f"/api/v1/teacher/graphs/{graph['id']}/evidence/node/{node['id']}",
        headers=teacher_headers,
    ).json()
    assert len(evidence_after["links"]) == 1
    assert "误差分解例题" in evidence_after["links"][0]["assertion_note"]


def test_teacher_graph_lifecycle_rename_discard_and_safe_delete(client, teacher_headers):
    graph, _, _ = build_valid_graph(client, teacher_headers, "Lifecycle graph")
    renamed = client.patch(
        f"/api/v1/teacher/graphs/{graph['id']}",
        headers=teacher_headers,
        json={"title": "Lifecycle graph renamed"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Lifecycle graph renamed"

    stale_delete = client.delete(
        f"/api/v1/teacher/graphs/{graph['id']}?expected_revision_version=1",
        headers=teacher_headers,
    )
    assert stale_delete.status_code == 409
    assert stale_delete.json()["detail"]["code"] == "GRAPH_REVISION_CONFLICT"

    published = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}:publish",
        headers=teacher_headers,
        json={"expected_revision_version": renamed.json()["version"]},
    )
    assert published.status_code == 200, published.text
    published_revision_id = published.json()["revision_id"]

    update = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}/revisions", headers=teacher_headers,
    )
    assert update.status_code == 201, update.text
    discarded_revision_id = update.json()["revision_id"]
    discarded = client.delete(
        f"/api/v1/teacher/graphs/{graph['id']}/draft"
        f"?expected_revision_version={update.json()['version']}",
        headers=teacher_headers,
    )
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["revision_id"] == published_revision_id
    assert discarded.json()["revision_id"] != discarded_revision_id
    assert discarded.json()["revision_status"] == "published"

    protected = client.delete(
        f"/api/v1/teacher/graphs/{graph['id']}"
        f"?expected_revision_version={discarded.json()['version']}",
        headers=teacher_headers,
    )
    assert protected.status_code == 409

    draft = create_graph(client, teacher_headers, "Disposable draft graph")
    deleted = client.delete(
        f"/api/v1/teacher/graphs/{draft['id']}"
        f"?expected_revision_version={draft['version']}",
        headers=teacher_headers,
    )
    assert deleted.status_code == 204, deleted.text
    assert client.get(
        f"/api/v1/teacher/graphs/{draft['id']}", headers=teacher_headers,
    ).status_code == 404


def test_publish_validation_requires_definition_and_auditable_provenance():
    teacher_node = SimpleNamespace(
        id="teacher-node", label="Teacher node", node_type="core", definition="",
        origin="teacher",
    )
    external_node = SimpleNamespace(
        id="external-node", label="External node", node_type="core",
        definition="Defined", origin="student_state",
    )
    result = validate_graph([teacher_node, external_node], [])
    errors = {(issue.code, issue.target_id) for issue in result.issues if issue.severity == "error"}
    assert ("missing_definition", teacher_node.id) in errors
    assert ("missing_provenance", external_node.id) in errors
    assert result.hard_pass is False

    curated_nodes = [
        SimpleNamespace(
            id=f"seed-{index}", label=f"Seed {index}", node_type="core",
            definition="", origin="curated_seed",
        )
        for index in range(2)
    ]
    curated_result = validate_graph(curated_nodes, [])
    assert curated_result.hard_pass is True
    assert all(issue.severity == "warning" for issue in curated_result.issues)


def test_publish_blocks_non_seed_node_without_definition(client, teacher_headers):
    graph = create_graph(client, teacher_headers, "Definition gate graph")
    first = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}/nodes",
        headers=teacher_headers,
        json={
            "expected_revision_version": graph["version"],
            "label": "Undefined concept",
            "definition": "",
        },
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}/nodes",
        headers=teacher_headers,
        json={
            "expected_revision_version": first.json()["version"],
            "label": "Defined concept",
            "definition": "A complete teacher-authored definition.",
        },
    )
    assert second.status_code == 200, second.text
    published = client.post(
        f"/api/v1/teacher/graphs/{graph['id']}:publish",
        headers=teacher_headers,
        json={"expected_revision_version": second.json()["version"]},
    )
    assert published.status_code == 422, published.text
    assert "missing_definition" in {
        issue["code"] for issue in published.json()["detail"]["issues"]
    }
