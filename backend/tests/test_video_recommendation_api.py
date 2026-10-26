from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import DEFAULT_FACT_SOURCE, Settings
from app.domains.video_search.provider import VideoDiscoveryError
from app.domains.video_search.schemas import DiscoveredVideo, VideoMetadata, VideoSearchIntent
from app.main import create_app
from app.models import KnowledgeGraph, LearningEvent, ParsedDocument, SourceAsset, User
from app.video_models import VideoLinkCheck


COURSE_ID = "machine-learning"
TOPIC_ID = f"{COURSE_ID}:concept:03"


class ContractVideoProvider:
    provider_id = "internet-archive"

    def __init__(self) -> None:
        self.search_calls = 0
        self.resolve_calls = 0
        self.title = "线性回归公开课程"
        self.fail_search = False
        self.fail_recheck = False
        self.seen_modes: list[str] = []

    def _metadata(self) -> VideoMetadata:
        return VideoMetadata(
            title=self.title,
            creator="公开课程教师",
            description="线性回归课程，包含模型定义与推导。",
            thumbnail_url="https://archive.org/download/demo/cover.jpg",
            duration_seconds=600,
            embed_url="https://archive.org/embed/zhixing-linear-regression-test",
            final_url="https://archive.org/details/zhixing-linear-regression-test",
            content_type="text/html",
            license_name="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            link_verified=True,
            source_verified=True,
            metadata_verified=True,
            collected_at=datetime.now(timezone.utc),
        )

    def search_resolved(
        self,
        intent: VideoSearchIntent,
        *,
        max_candidates: int,
    ) -> list[tuple[DiscoveredVideo, VideoMetadata]]:
        self.search_calls += 1
        assert max_candidates <= 30
        self.seen_modes.append(intent.source_mode)
        if self.fail_search:
            raise VideoDiscoveryError(
                "VIDEO_SEARCH_PROVIDER_UNAVAILABLE", "真实视频检索提供方当前不可用",
            )
        discovered = DiscoveredVideo(
            provider=self.provider_id,
            external_id="zhixing-linear-regression-test",
            canonical_url="https://archive.org/details/zhixing-linear-regression-test",
            title=self.title,
            description="线性回归课程",
        )
        return [(discovered, self._metadata())]

    def resolve(self, candidate: DiscoveredVideo) -> VideoMetadata:
        self.resolve_calls += 1
        if self.fail_recheck:
            raise VideoDiscoveryError("VIDEO_LINK_UNAVAILABLE", "视频页面当前无法访问")
        assert candidate.external_id == "zhixing-linear-regression-test"
        return self._metadata()


@pytest.fixture()
def a4_client(tmp_path: Path):
    database_path = tmp_path / "a4.db"
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
    provider = ContractVideoProvider()
    app.state.video_provider_registry = {provider.provider_id: provider}
    with TestClient(app) as client:
        yield client, app, provider


def _login(client: TestClient, role: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={
        "account": f"{role}@zhixing.edu.cn",
        "password": "zhixing2026",
        "role": role,
    })
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _search(
    client: TestClient,
    teacher_headers: dict[str, str],
    *,
    key: str = "search-1",
) -> tuple[dict, dict]:
    headers = {**teacher_headers, "Idempotency-Key": key}
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/video-search-jobs",
        headers=headers,
        json={
            "source_mode": "records",
            "topic_ids": [TOPIC_ID],
            "teaching_intent": "课后巩固",
            "max_candidates_per_provider": 5,
        },
    )
    assert response.status_code == 201, response.text
    candidates = client.get(
        f"/api/v1/video-search-jobs/{response.json()['id']}/candidates",
        headers=teacher_headers,
    )
    assert candidates.status_code == 200, candidates.text
    assert len(candidates.json()) == 1
    return response.json(), candidates.json()[0]


def _publish(
    client: TestClient,
    teacher_headers: dict[str, str],
    candidate_id: str,
    *,
    key: str = "publish-1",
) -> dict:
    preview = client.post(
        f"/api/v1/video-candidates/{candidate_id}/preview-events",
        headers={**teacher_headers, "Idempotency-Key": f"preview-{key}"},
        json={"action": "embedded_preview"},
    )
    assert preview.status_code == 201, preview.text
    publication = client.post(
        "/api/v1/video-publications",
        headers={**teacher_headers, "Idempotency-Key": key},
        json={"candidate_id": candidate_id, "audience": {"mode": "all"}},
    )
    assert publication.status_code == 201, publication.text
    return publication.json()


def test_search_is_role_scoped_strict_and_idempotent(a4_client):
    client, _, provider = a4_client
    teacher = _login(client, "teacher")
    student = _login(client, "student")
    payload = {
        "source_mode": "records",
        "topic_ids": [TOPIC_ID],
        "teaching_intent": "课后巩固",
    }
    forbidden = client.post(
        f"/api/v1/courses/{COURSE_ID}/video-search-jobs",
        headers={**student, "Idempotency-Key": "student-search"},
        json=payload,
    )
    assert forbidden.status_code == 403
    missing_key = client.post(
        f"/api/v1/courses/{COURSE_ID}/video-search-jobs",
        headers=teacher,
        json=payload,
    )
    assert missing_key.status_code == 422

    job, candidate = _search(client, teacher)
    assert job["status"] == "completed"
    assert job["actual_profile_id"] is None
    assert candidate["scores"]["clarity"] is None
    assert candidate["evidence_level"] == "E1"
    assert set(candidate["verified_scope"]) >= {"link", "source", "metadata"}
    assert provider.search_calls == 1

    repeated, repeated_candidate = _search(client, teacher)
    assert repeated["id"] == job["id"]
    assert repeated_candidate["id"] == candidate["id"]
    assert provider.search_calls == 1
    conflict = client.post(
        f"/api/v1/courses/{COURSE_ID}/video-search-jobs",
        headers={**teacher, "Idempotency-Key": "search-1"},
        json={**payload, "topic_ids": [f"{COURSE_ID}:concept:02"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "VIDEO_SEARCH_IDEMPOTENCY_CONFLICT"

    filtered = client.get(
        f"/api/v1/video-search-jobs/{job['id']}/candidates?min_duration=601",
        headers=teacher,
    )
    assert filtered.status_code == 200
    assert filtered.json() == []


def test_all_provider_failures_are_explicit_and_never_return_catalog(a4_client):
    client, _, provider = a4_client
    teacher = _login(client, "teacher")
    provider.fail_search = True
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/video-search-jobs",
        headers={**teacher, "Idempotency-Key": "unavailable-search"},
        json={"source_mode": "records", "topic_ids": [TOPIC_ID]},
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "VIDEO_ALL_PROVIDERS_UNAVAILABLE"
    job = client.get(f"/api/v1/video-search-jobs/{detail['job_id']}", headers=teacher)
    assert job.status_code == 200
    assert job.json()["status"] == "failed"
    candidates = client.get(
        f"/api/v1/video-search-jobs/{detail['job_id']}/candidates",
        headers=teacher,
    )
    assert candidates.status_code == 200
    assert candidates.json() == []


def test_all_four_source_modes_use_one_validated_real_provider_contract(a4_client):
    client, app, provider = a4_client
    teacher = _login(client, "teacher")
    with app.state.db.session_factory() as session:
        graph = session.scalar(select(KnowledgeGraph).where(
            KnowledgeGraph.course_id == COURSE_ID,
            KnowledgeGraph.published_revision_id.is_not(None),
        ))
        teacher_row = session.scalar(select(User).where(User.email == "teacher@zhixing.edu.cn"))
        assert graph is not None and teacher_row is not None
        asset_id = str(uuid4())
        session.add(SourceAsset(
            id=asset_id, course_id=COURSE_ID, owner_id=teacher_row.id,
            purpose="video_search", original_name="linear.txt", extension="txt",
            declared_mime="text/plain", detected_mime="text/plain",
            expected_size=20, byte_size=20, expected_sha256=None,
            sha256="1" * 64, storage_key="test/linear.txt",
            status="accepted", security_status="accepted",
            accepted_at=datetime.now(timezone.utc),
        ))
        session.flush()
        session.add(ParsedDocument(
            id=str(uuid4()), asset_id=asset_id, parser_name="plain_text",
            parser_version="test-contract", status="parsed", title="线性回归",
            segment_count=1, page_count=1, text_length=20, warnings_json=[],
        ))
        session.commit()
        graph_revision_id = graph.published_revision_id

    sources = client.get(
        f"/api/v1/teacher/courses/{COURSE_ID}/video-search-sources",
        headers=teacher,
    )
    assert sources.status_code == 200, sources.text
    assert len(sources.json()["recorded_topics"]) == 10
    graph_option = next(
        item for item in sources.json()["graphs"]
        if item["published_revision_id"] == graph_revision_id
    )
    assert TOPIC_ID in {item["concept_id"] for item in graph_option["topics"]}
    assert sources.json()["parsed_assets"][0]["asset_id"] == asset_id

    cases = [
        ("graph", {"graph_revision_id": graph_revision_id}),
        ("files", {"asset_ids": [asset_id]}),
        ("manual", {"raw_text": "线性回归；课后推导"}),
    ]
    for index, (mode, extra) in enumerate(cases):
        response = client.post(
            f"/api/v1/courses/{COURSE_ID}/video-search-jobs",
            headers={**teacher, "Idempotency-Key": f"source-{index}"},
            json={"source_mode": mode, "topic_ids": [TOPIC_ID], **extra},
        )
        assert response.status_code == 201, response.text
    assert provider.seen_modes == ["graph", "files", "manual"]

    unavailable_model = client.post(
        f"/api/v1/courses/{COURSE_ID}/video-search-jobs",
        headers={**teacher, "Idempotency-Key": "model-required"},
        json={
            "source_mode": "records", "topic_ids": [TOPIC_ID],
            "requested_profile_id": "gpt-5", "allow_deterministic_degrade": False,
        },
    )
    assert unavailable_model.status_code == 503
    assert unavailable_model.json()["detail"]["code"] == "VIDEO_QUERY_PLANNER_UNAVAILABLE"

    degraded = client.post(
        f"/api/v1/courses/{COURSE_ID}/video-search-jobs",
        headers={**teacher, "Idempotency-Key": "model-degraded"},
        json={
            "source_mode": "records", "topic_ids": [TOPIC_ID],
            "requested_profile_id": "gpt-5", "allow_deterministic_degrade": True,
        },
    )
    assert degraded.status_code == 201
    assert degraded.json()["actual_profile_id"] is None
    assert degraded.json()["warnings"][0]["code"] == "DETERMINISTIC_QUERY_PLAN"


def test_e1_requires_preview_and_publication_is_single_video_idempotent(a4_client):
    client, _, provider = a4_client
    teacher = _login(client, "teacher")
    student = _login(client, "student")
    _, candidate = _search(client, teacher)

    blocked = client.post(
        "/api/v1/video-publications",
        headers={**teacher, "Idempotency-Key": "publish-without-preview"},
        json={"candidate_id": candidate["id"], "audience": {"mode": "all"}},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "VIDEO_PREVIEW_REQUIRED"
    assert provider.resolve_calls == 1

    publication = _publish(client, teacher, candidate["id"])
    assert publication["recipient_count"] == 48
    assert publication["resource"]["canonical_url"].startswith("https://archive.org/details/")
    assert publication["resource"]["matched_topic_ids"] == [TOPIC_ID]
    repeated = client.post(
        "/api/v1/video-publications",
        headers={**teacher, "Idempotency-Key": "publish-1"},
        json={"candidate_id": candidate["id"], "audience": {"mode": "all"}},
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == publication["id"]
    assert repeated.json()["duplicate"] is True

    array_contract = client.post(
        "/api/v1/video-publications",
        headers={**teacher, "Idempotency-Key": "bad-array"},
        json={"candidate_ids": [candidate["id"]], "audience": {"mode": "all"}},
    )
    assert array_contract.status_code == 422
    resources = client.get(
        f"/api/v1/courses/{COURSE_ID}/resources?type=video",
        headers=student,
    )
    assert resources.status_code == 200
    assert [item["id"] for item in resources.json()] == [publication["id"]]
    teacher_cannot_open_student_resource = client.get(
        f"/api/v1/video-publications/{publication['id']}", headers=teacher,
    )
    assert teacher_cannot_open_student_resource.status_code == 403


def test_targeted_audience_uses_only_candidate_topics(a4_client):
    client, _, _ = a4_client
    teacher = _login(client, "teacher")
    _, candidate = _search(client, teacher, key="target-search")
    preview = client.post(
        f"/api/v1/video-candidates/{candidate['id']}/preview-events",
        headers={**teacher, "Idempotency-Key": "target-preview"},
        json={"action": "original_page_opened"},
    )
    assert preview.status_code == 201
    outside = client.post(
        "/api/v1/video-publications",
        headers={**teacher, "Idempotency-Key": "target-outside"},
        json={
            "candidate_id": candidate["id"],
            "audience": {
                "mode": "states",
                "topic_ids": [f"{COURSE_ID}:concept:02"],
                "states": ["weak", "mastered", "unseen"],
            },
        },
    )
    assert outside.status_code == 422
    assert outside.json()["detail"]["code"] == "VIDEO_AUDIENCE_TOPIC_OUT_OF_SCOPE"
    targeted = client.post(
        "/api/v1/video-publications",
        headers={**teacher, "Idempotency-Key": "target-valid"},
        json={
            "candidate_id": candidate["id"],
            "audience": {
                "mode": "states",
                "topic_ids": [TOPIC_ID],
                "states": ["weak", "mastered", "unseen"],
            },
        },
    )
    assert targeted.status_code == 201, targeted.text
    assert targeted.json()["recipient_count"] == 48


def test_player_events_preserve_evidence_boundary_and_repair_idempotently(a4_client):
    client, app, _ = a4_client
    teacher = _login(client, "teacher")
    student = _login(client, "student")
    _, candidate = _search(client, teacher, key="event-search")
    publication = _publish(client, teacher, candidate["id"], key="event-publish")
    publication_id = publication["id"]
    now = datetime.now(timezone.utc).isoformat()

    opened = client.post(
        f"/api/v1/video-publications/{publication_id}/events",
        headers={**student, "Idempotency-Key": "opened-1"},
        json={
            "event_type": "opened",
            "occurred_at": now,
            "player_signal": "page_only",
        },
    )
    assert opened.status_code == 201, opened.text
    assert opened.json()["trajectory_processing_status"] == "observed_only"
    assert opened.json()["progress"]["active_seconds"] == 0
    assert opened.json()["progress"]["evidence_scope"] == "resource_interaction_only"
    fake_watch = client.post(
        f"/api/v1/video-publications/{publication_id}/events",
        headers={**student, "Idempotency-Key": "fake-watch"},
        json={
            "event_type": "playback", "occurred_at": now,
            "player_signal": "page_only", "position_seconds": 540,
            "active_seconds_delta": 60, "foreground_ratio": 1,
        },
    )
    assert fake_watch.status_code == 422

    completed_payload = {
        "event_type": "completed",
        "occurred_at": now,
        "player_signal": "official_sdk",
        "position_seconds": 540,
        "active_seconds_delta": 30,
        "foreground_ratio": 0.9,
    }
    completed = client.post(
        f"/api/v1/video-publications/{publication_id}/events",
        headers={**student, "Idempotency-Key": "complete-1"},
        json=completed_payload,
    )
    assert completed.status_code == 201, completed.text
    assert completed.json()["trajectory_processing_status"] == "accepted"
    assert completed.json()["progress"]["completed"] is True
    assert completed.json()["progress"]["evidence_scope"] == "verified_playback"
    repeated = client.post(
        f"/api/v1/video-publications/{publication_id}/events",
        headers={**student, "Idempotency-Key": "complete-1"},
        json=completed_payload,
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["duplicate"] is True
    assert repeated.json()["progress"]["active_seconds"] == 30
    conflict = client.post(
        f"/api/v1/video-publications/{publication_id}/events",
        headers={**student, "Idempotency-Key": "complete-1"},
        json={**completed_payload, "position_seconds": 500},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "VIDEO_EVENT_IDEMPOTENCY_CONFLICT"
    with app.state.db.session_factory() as session:
        count = session.scalar(select(func.count()).select_from(LearningEvent).where(
            LearningEvent.object_id == publication_id,
            LearningEvent.event_type == "video_completed",
        ))
    assert count == 1


def test_recheck_detects_metadata_change_and_network_failure(a4_client):
    client, app, provider = a4_client
    teacher = _login(client, "teacher")
    _, candidate = _search(client, teacher, key="change-search")
    provider.title = "已变化的课程标题"
    changed = client.post(
        f"/api/v1/video-candidates/{candidate['id']}/recheck",
        headers={**teacher, "Idempotency-Key": "changed-check"},
    )
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "VIDEO_METADATA_CHANGED"
    with app.state.db.session_factory() as session:
        persisted = session.scalar(select(VideoLinkCheck).where(
            VideoLinkCheck.candidate_id == candidate["id"],
            VideoLinkCheck.idempotency_key == "changed-check",
        ))
        assert persisted is not None
        assert persisted.status == "metadata_changed"

    _, other = _search(client, teacher, key="failure-search")
    provider.fail_recheck = True
    failed = client.post(
        f"/api/v1/video-candidates/{other['id']}/recheck",
        headers={**teacher, "Idempotency-Key": "failed-check"},
    )
    assert failed.status_code == 503
    assert failed.json()["detail"] == {
        "code": "VIDEO_LINK_UNAVAILABLE",
        "message": "视频页面当前无法访问",
    }
