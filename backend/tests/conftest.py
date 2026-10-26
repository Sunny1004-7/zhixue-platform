from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import DEFAULT_FACT_SOURCE, Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path):
    database_path = tmp_path / "test.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        fact_source=DEFAULT_FACT_SOURCE,
        cors_origins=("http://testserver",),
        session_ttl_hours=1,
        asset_root=tmp_path / "assets",
        asset_max_bytes=2 * 1024 * 1024,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, role: str = "student") -> dict:
    response = client.post("/api/v1/auth/login", json={
        "account": f"{role}@zhixing.edu.cn",
        "password": "zhixing2026",
        "role": role,
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def student_headers(client: TestClient) -> dict[str, str]:
    token = login(client, "student")["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def teacher_headers(client: TestClient) -> dict[str, str]:
    token = login(client, "teacher")["access_token"]
    return {"Authorization": f"Bearer {token}"}


def ingest_trusted_event(client: TestClient, url: str, *, headers: dict, json: dict):
    """Test the server-side event service with a validated payload and user."""
    from dataclasses import asdict
    from fastapi import HTTPException
    from httpx import Response
    from sqlalchemy import select
    from app.domains.trajectory.service import ConceptContribution, EventCommand, TrajectoryService
    from app.models import User
    from app.schemas import LearningEventCreate

    payload = LearningEventCreate.model_validate(json)
    course_id = url.split('/courses/', 1)[1].split('/', 1)[0]
    with client.app.state.db.session_factory() as db:
        user = db.scalar(select(User).where(User.email == 'student@zhixing.edu.cn'))
        command = EventCommand(**{
            **payload.model_dump(exclude={'concepts'}),
            'concepts': [ConceptContribution(c.concept_id, c.weight) for c in payload.concepts],
        })
        try:
            result = TrajectoryService(db).ingest(student=user, course_id=course_id, command=command)
            return Response(200, json=asdict(result))
        except HTTPException as exc:
            return Response(exc.status_code, json={'detail': exc.detail})
