from datetime import datetime, timezone
from sqlalchemy import delete, select

from app.models import CourseEnrollment, User
from app.resource_metrics import resource_completion


def test_empty_course_membership_returns_an_empty_course_summary(client, student_headers):
    student_id = client.get('/api/v1/me', headers=student_headers).json()['id']
    with client.app.state.db.session_factory() as db:
        db.execute(delete(CourseEnrollment).where(CourseEnrollment.student_id == student_id))
        db.commit()
    assert client.get('/api/v1/courses', headers=student_headers).json() == []
    response = client.get('/api/v1/student/courses/summary', headers=student_headers)
    assert response.status_code == 200
    data = response.json()
    assert data['active_courses'] == data['pending_resources'] == data['resource_completion'] == 0
    assert data['daily_minutes'] == [0] * 7


def test_teacher_class_without_enrolled_students_has_a_finite_zero_snapshot(client, teacher_headers):
    with client.app.state.db.session_factory() as db:
        db.execute(delete(CourseEnrollment).where(CourseEnrollment.course_id == 'machine-learning'))
        db.commit()
    response = client.post('/api/v1/courses/machine-learning/decision-snapshots:refresh', headers=teacher_headers, json={})
    assert response.status_code == 201, response.text
    snapshot = response.json()
    assert snapshot['student_count'] == 0
    assert snapshot['priority_students'] == []
    assert snapshot['aggregate']['average_resource_completion'] == 0
    assert snapshot['aggregate']['average_effective_tutoring_count'] == 0
    overview = client.get('/api/v1/teacher/courses/machine-learning/overview', headers=teacher_headers).json()
    assert overview['student_count'] == overview['priority_student_count'] == 0


def test_resource_completion_uses_current_catalog_instead_of_historic_enrollment_percentage(client, student_headers):
    student_id = client.get('/api/v1/me', headers=student_headers).json()['id']
    with client.app.state.db.session_factory() as db:
        before = resource_completion(db, student_id, 'machine-learning')
        enrollment = db.scalar(select(CourseEnrollment).where(
            CourseEnrollment.student_id == student_id, CourseEnrollment.course_id == 'machine-learning'))
        enrollment.resource_completion = 99
        db.commit()
    overview = client.get('/api/v1/student/courses/machine-learning/overview', headers=student_headers).json()
    courses = client.get('/api/v1/courses', headers=student_headers).json()
    assert before.total > 0
    assert overview['resource_completion']['value'] == before.percent
    assert next(c for c in courses if c['id'] == 'machine-learning')['progress'] == before.percent


def test_catalog_and_directed_inbox_count_the_same_resource_once_and_share_teacher_metrics(
    client, student_headers, teacher_headers,
):
    course = 'machine-learning'
    student_id = client.get('/api/v1/me', headers=student_headers).json()['id']
    graph = client.get(f'/api/v1/student/courses/{course}/graph-resources', headers=student_headers).json()[0]
    with client.app.state.db.session_factory() as db:
        before = resource_completion(db, student_id, course)
    client.post(f'/api/v1/courses/{course}/decision-snapshots:refresh', headers=teacher_headers, json={})
    draft = client.post(f'/api/v1/teacher/courses/{course}/resources/{graph["id"]}/audience-drafts',
        headers=teacher_headers, json={'resource_type': 'graph', 'resource_id': graph['id'],
        'audience_mode': 'single', 'locked_student_id': student_id}).json()
    publication = client.post(f'/api/v1/audience-drafts/{draft["id"]}/publications',
        headers={**teacher_headers, 'Idempotency-Key': 'metrics-publish'},
        json={'draft_version': draft['version'], 'acknowledge_warnings': True})
    assert publication.status_code == 201, publication.text
    inbox = client.get(f'/api/v1/student/courses/{course}/resource-inbox', headers=student_headers).json()
    item = next(x for x in inbox if x['publication_id'] == publication.json()['id'])
    for key in ['metrics-complete-1', 'metrics-complete-2']:
        result = client.post(f'/api/v1/student/resource-inbox/{item["exposure_id"]}:complete',
            headers=student_headers, json={'idempotency_key': key, 'occurred_at':datetime.now(timezone.utc).isoformat()})
        assert result.status_code == 200, result.text
    with client.app.state.db.session_factory() as db:
        after = resource_completion(db, student_id, course)
    assert after.total == before.total
    assert after.completed == before.completed + 1
    overview = client.get(f'/api/v1/student/courses/{course}/overview', headers=student_headers).json()
    client.post(f'/api/v1/courses/{course}/decision-snapshots:refresh', headers=teacher_headers, json={})
    teacher = client.get(f'/api/v1/courses/{course}/students/{student_id}/learning-state', headers=teacher_headers).json()
    assert overview['resource_completion']['value'] == teacher['components']['resource_completion'] == after.percent
