from __future__ import annotations

from conftest import login


def test_health_is_public(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_login_rejects_role_mismatch(client):
    response = client.post("/api/v1/auth/login", json={
        "account": "student@zhixing.edu.cn",
        "password": "zhixing2026",
        "role": "teacher",
    })
    assert response.status_code == 403


def test_student_course_list_and_summary_are_consistent(client, student_headers):
    courses_response = client.get("/api/v1/courses", headers=student_headers)
    assert courses_response.status_code == 200
    courses = courses_response.json()
    assert [(item["id"], item["code"]) for item in courses] == [
        ("machine-learning", "ML-2026"),
        ("ai-intro", "AI-2026"),
        ("data-intelligence", "DI-2026"),
    ]
    summary = client.get("/api/v1/student/courses/summary", headers=student_headers).json()
    assert summary["active_courses"] == 3
    assert summary["weekly_minutes"] == sum(item["weekly_minutes"] for item in courses)
    assert summary["overall_mastery"] == 72
    assert summary["pending_resources"] > 0
    assert summary["mastery_delta"] != 4
    assert "18%" not in summary["preferred_pattern"]
    assert summary["preferred_pattern"] == "尚无足够行为证据，暂不生成学习偏好结论"


def test_overview_has_ten_topics_and_eight_question_progress(client, student_headers):
    response = client.get("/api/v1/student/courses/machine-learning/overview", headers=student_headers)
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["knowledge_states"]) == 10
    assert [item["label"] for item in payload["knowledge_states"]][-1] == "正则化"
    question_set = next(item for item in payload["recent_resources"] if item["resource_type"] == "question_set")
    assert question_set["progress_completed"] == 3
    assert question_set["progress_total"] == 8
    assert "3 / 8" in question_set["detail"]


def test_role_and_course_access_are_isolated(client, student_headers, teacher_headers):
    denied_teacher = client.get("/api/v1/teacher/courses/machine-learning/overview", headers=student_headers)
    denied_student = client.get("/api/v1/student/courses/machine-learning/overview", headers=teacher_headers)
    assert denied_teacher.status_code == 403
    assert denied_student.status_code == 403
    teacher_ok = client.get("/api/v1/teacher/courses/machine-learning/overview", headers=teacher_headers)
    assert teacher_ok.status_code == 200
    assert teacher_ok.json()["student_count"] == 48
    assert teacher_ok.json()["priority_student_count"] == 3
    assert teacher_ok.json()["class_name"].startswith("ML-2026")


def test_logout_revokes_server_session(client):
    token = login(client)["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/me", headers=headers).status_code == 401
