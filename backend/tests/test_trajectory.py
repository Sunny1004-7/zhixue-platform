from __future__ import annotations

from conftest import ingest_trusted_event

from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.domains.trajectory.evidence import score_event
from app.domains.trajectory.graph_constraint import PublishedGraphConstraint
from app.domains.trajectory.temporal_residual import EvidenceTemporalResidual
from app.domains.trajectory.numerics import OnlineUpdateConfig, mix_probabilities, smooth_probability
from app.domains.trajectory.ports import TemporalPrediction
from app.domains.trajectory.service import TrajectoryService
from app.models import Concept, KnowledgeState, MasteryEvidence, User
from sqlalchemy import inspect, select


COURSE_ID = "machine-learning"
LOSS_CONCEPT = "machine-learning:concept:04"


def event_payload(
    key: str,
    *,
    outcome: float = 1.0,
    concept_id: str = LOSS_CONCEPT,
    occurred_at: datetime | None = None,
    correction_of_event_id: str | None = None,
    alignment_confidence: float = 1.0,
):
    return {
        "idempotency_key": key,
        "event_type": "answer_scored",
        "object_type": "question",
        "object_id": "question-eglt-01",
        "concepts": [{"concept_id": concept_id, "weight": 1}],
        "outcome": outcome,
        "difficulty": 0.7,
        "hint_level": 0,
        "attempt_no": 1,
        "upstream_confidence": 1,
        "alignment_confidence": alignment_confidence,
        "occurred_at": (occurred_at or datetime.now(timezone.utc)).isoformat(),
        "correction_of_event_id": correction_of_event_id,
        "payload": {"grading_mode": "objective_rule"},
    }


def state(client, headers, concept_id=LOSS_CONCEPT):
    response = client.get(f"/api/v1/student/courses/{COURSE_ID}/mastery", headers=headers)
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["concept_id"] == concept_id)


def test_answer_event_updates_state_once_and_is_idempotent(client, student_headers):
    before = state(client, student_headers)
    payload = event_payload("attempt-eglt-0001")
    first = ingest_trusted_event(client, f"/api/v1/student/courses/{COURSE_ID}/events", headers=student_headers, json=payload)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["duplicate"] is False
    assert result["processing_status"] == "accepted"
    assert result["evidence_reliability"] == 1
    assert len(result["changes"]) == 1
    # The final state also reflects confirmed prerequisites, so its direction
    # need not match the answer outcome alone.
    assert result["changes"][0]["mastery"] * 100 != pytest.approx(before["mastery"])

    after_first = state(client, student_headers)
    assert after_first["evidence_count"] == before["evidence_count"] + 1
    second = ingest_trusted_event(client, f"/api/v1/student/courses/{COURSE_ID}/events", headers=student_headers, json=payload)
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    after_second = state(client, student_headers)
    assert after_second["mastery"] == after_first["mastery"]
    assert after_second["evidence_count"] == after_first["evidence_count"]


def test_cross_course_concept_cannot_update_current_course(client, student_headers):
    response = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=event_payload("attempt-eglt-cross", concept_id="ai-intro:concept:01"),
    )
    assert response.status_code == 422
    assert "不属于当前课程" in response.json()["detail"]


def test_low_alignment_event_is_saved_but_does_not_change_mastery(client, student_headers):
    before = state(client, student_headers)
    response = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=event_payload("attempt-eglt-review", alignment_confidence=0.4),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "awaiting_alignment_review"
    assert payload["changes"] == []
    assert state(client, student_headers)["mastery"] == before["mastery"]


def test_idle_video_progress_is_observed_only(client, student_headers):
    before = state(client, student_headers)
    payload = {
        "idempotency_key": "video-eglt-idle-01",
        "event_type": "video_progressed",
        "object_type": "learning_video",
        "object_id": "ml-v1",
        "concepts": [{"concept_id": LOSS_CONCEPT, "weight": 1}],
        "completion": 0.9,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"active_seconds": 8, "duration_seconds": 1200, "foreground_ratio": 0.3},
    }
    response = ingest_trusted_event(client, f"/api/v1/student/courses/{COURSE_ID}/events", headers=student_headers, json=payload)
    assert response.status_code == 200
    assert response.json()["processing_status"] == "observed_only"
    assert response.json()["evidence_reliability"] == 0
    assert state(client, student_headers)["mastery"] == before["mastery"]


def test_visible_knowledge_card_dwell_updates_a1_state(client, student_headers):
    before = state(client, student_headers)
    graph = client.get(f'/api/v1/student/courses/{COURSE_ID}/graph-resources/ml-g1', headers=student_headers).json()
    node = next(n for n in graph['nodes'] if n['concept_id'] == LOSS_CONCEPT)
    response = client.post(
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json={
            "idempotency_key": "knowledge-card-eglt-01",
            "event_type": "knowledge_card_opened",
            "object_type": "knowledge_graph_node",
            "object_id": node["id"],
            "concepts": [{"concept_id": LOSS_CONCEPT, "weight": 1}],
            "completion": 0.5,
            "upstream_confidence": 1,
            "alignment_confidence": 1,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "dwell_seconds": 60,
                "foreground_ratio": 0.9,
                "graph_id": "ml-g1",
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["processing_status"] == "accepted"
    assert response.json()["evidence_reliability"] > 0
    assert state(client, student_headers)["evidence_count"] == before["evidence_count"] + 1


def test_correction_replays_from_baseline_without_double_counting(client, student_headers):
    before = state(client, student_headers)
    wrong = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=event_payload("attempt-eglt-wrong", outcome=0),
    ).json()
    after_wrong = state(client, student_headers)
    assert after_wrong["mastery"] < before["mastery"]

    corrected = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=event_payload(
            "attempt-eglt-correction", outcome=1,
            correction_of_event_id=wrong["event_id"],
        ),
    )
    assert corrected.status_code == 200, corrected.text
    after_correction = state(client, student_headers)
    assert after_correction["mastery"] > after_wrong["mastery"]
    assert after_correction["evidence_count"] == after_wrong["evidence_count"]
    assert wrong["event_id"] not in after_correction["top_evidence"]
    assert corrected.json()["event_id"] in after_correction["top_evidence"]


def test_out_of_order_event_triggers_replay_and_retains_both_evidence(client, student_headers):
    now = datetime.now(timezone.utc)
    later = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=event_payload("attempt-eglt-later", outcome=0, occurred_at=now),
    )
    older = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=event_payload("attempt-eglt-older", outcome=1, occurred_at=now - timedelta(days=1)),
    )
    assert later.status_code == 200 and older.status_code == 200
    current = state(client, student_headers)
    assert {later.json()["event_id"], older.json()["event_id"]}.issubset(set(current["top_evidence"]))


def test_temporal_residual_is_active_after_two_auditable_events(client, student_headers):
    now = datetime.now(timezone.utc)
    first = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=event_payload("temporal-active-1", outcome=0, occurred_at=now - timedelta(days=1)),
    )
    second = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=event_payload("temporal-active-2", outcome=1, occurred_at=now),
    )
    assert first.status_code == 200 and second.status_code == 200
    assert_complete_model_version_saved(client, second.json())


def assert_complete_model_version_saved(client, result):
    expected = "eglt-0.4.0+temporal-evidence-1.0+a2-graph"
    assert result["changes"][0]["model_version"] == expected
    with client.app.state.db.session_factory() as db:
        evidence = db.scalar(select(MasteryEvidence).where(
            MasteryEvidence.event_id == result["event_id"],
            MasteryEvidence.concept_id == LOSS_CONCEPT,
        ))
        assert evidence is not None
        knowledge = db.get(KnowledgeState, evidence.state_id)
        assert knowledge is not None
        assert knowledge.model_version == evidence.model_version == expected
    schema = inspect(client.app.state.db.engine)
    for table_name in ("knowledge_states", "mastery_evidence"):
        column = next(c for c in schema.get_columns(table_name) if c["name"] == "model_version")
        assert column["type"].length >= len(expected)


def test_model_version_migration_preserves_existing_data_and_safe_rollback(tmp_path, monkeypatch):
    from app.config import DEFAULT_FACT_SOURCE, Settings
    from app.main import create_app

    monkeypatch.delenv("ZHIXING_DATABASE_URL", raising=False)
    backend_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "fresh-install" / "version-upgrade.db"
    assert not database_path.parent.exists()
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(config, "0011_open_concept_registry")
    assert database_path.is_file()

    def snapshot():
        with sqlite3.connect(database_path) as connection:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY name"
            ).fetchall()
            return {
                name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                for (name,) in tables
            }

    def assert_capacity(expected):
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            for table_name in ("knowledge_states", "mastery_evidence"):
                columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
                version = next(column for column in columns if column[1] == "model_version")
                assert version[2] == f"VARCHAR({expected})"

    settings = Settings(
        environment="test", database_url=f"sqlite:///{database_path.as_posix()}",
        fact_source=DEFAULT_FACT_SOURCE, asset_root=tmp_path / "assets",
    )
    with TestClient(create_app(settings)) as migrated_client:
        login = migrated_client.post("/api/v1/auth/login", json={
            "account": "student@zhixing.edu.cn", "password": "zhixing2026", "role": "student",
        })
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        now = datetime.now(timezone.utc)
        first = ingest_trusted_event(migrated_client,
            f"/api/v1/student/courses/{COURSE_ID}/events", headers=headers,
            json=event_payload("migration-old-event", outcome=0, occurred_at=now - timedelta(days=1)),
        )
        assert first.status_code == 200, first.text
        before = snapshot()
        assert before["knowledge_states"] and before["mastery_evidence"]
        assert_capacity(40)
        command.upgrade(config, "head")
        assert_capacity(128)
        assert snapshot() == before

        # Short legacy identifiers can still be rolled back without losing data.
        command.downgrade(config, "0011_open_concept_registry")
        assert_capacity(40)
        assert snapshot() == before
        command.upgrade(config, "head")

        second = ingest_trusted_event(migrated_client,
            f"/api/v1/student/courses/{COURSE_ID}/events", headers=headers,
            json=event_payload("migration-new-event", outcome=1, occurred_at=now),
        )
        assert second.status_code == 200, second.text
        assert_complete_model_version_saved(migrated_client, second.json())
        after = snapshot()
        with pytest.raises(RuntimeError, match="existing model versions exceed"):
            command.downgrade(config, "0011_open_concept_registry")
        assert_capacity(128)
        assert snapshot() == after
        command.check(config)


def test_model_version_migration_generates_postgresql_column_expansion(monkeypatch):
    monkeypatch.delenv("ZHIXING_DATABASE_URL", raising=False)
    backend_root = Path(__file__).resolve().parents[1]
    output = StringIO()
    config = Config(str(backend_root / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql+psycopg://localhost/zhixing_migration_test")
    command.upgrade(config, "0011_open_concept_registry:0012_expand_model_version", sql=True)
    sql = output.getvalue()
    for table_name in ("knowledge_states", "mastery_evidence"):
        assert f"ALTER TABLE {table_name} ALTER COLUMN model_version TYPE VARCHAR(128);" in sql


def test_temporal_residual_uses_as_of_cutoff_without_future_leakage(client, student_headers):
    now = datetime.now(timezone.utc)
    for key, outcome, days_ago in [
        ("temporal-cutoff-1", 0.0, 3),
        ("temporal-cutoff-2", 0.0, 2),
        ("temporal-cutoff-3", 1.0, 0),
    ]:
        response = ingest_trusted_event(client,
            f"/api/v1/student/courses/{COURSE_ID}/events",
            headers=student_headers,
            json=event_payload(key, outcome=outcome, occurred_at=now - timedelta(days=days_ago)),
        )
        assert response.status_code == 200, response.text

    with client.app.state.db.session_factory() as db:
        student = db.scalar(select(User).where(User.email == "student@zhixing.edu.cn"))
        assert student is not None
        residual = EvidenceTemporalResidual(db)
        past = residual.predict(
            student_id=student.id,
            course_id=COURSE_ID,
            concept_id=LOSS_CONCEPT,
            as_of=now - timedelta(days=1),
        )
        current = residual.predict(
            student_id=student.id,
            course_id=COURSE_ID,
            concept_id=LOSS_CONCEPT,
            as_of=now,
        )
        assert past is not None and current is not None
        assert current.probability > past.probability
        assert 0 < current.gate <= 0.18


def test_progressive_hints_reduce_independent_success_evidence():
    base = dict(
        event_type="answer_scored", outcome=1.0, difficulty=0.5, attempt_no=1,
        completion=None, upstream_confidence=1.0, alignment_confidence=1.0,
        payload={"grading_mode": "objective_rule"},
    )
    no_hint = score_event(hint_level=0, **base)
    third_hint = score_event(hint_level=3, **base)
    assert no_hint.success > third_hint.success
    assert no_hint.reliability == third_hint.reliability == 1


def test_published_a2_prerequisites_constrain_a1_mastery(client):
    with client.app.state.db.session_factory() as db:
        student = db.scalar(select(User).where(User.email == "student@zhixing.edu.cn"))
        prerequisite = db.scalar(select(Concept).where(
            Concept.course_id == COURSE_ID,
            Concept.name == "损失函数",
        ))
        target = db.scalar(select(Concept).where(
            Concept.course_id == COURSE_ID,
            Concept.name == "梯度下降",
        ))
        assert student is not None and prerequisite is not None and target is not None
        prerequisite_state = db.scalar(select(KnowledgeState).where(
            KnowledgeState.student_id == student.id,
            KnowledgeState.course_id == COURSE_ID,
            KnowledgeState.concept_id == prerequisite.id,
        ))
        assert prerequisite_state is not None
        prerequisite_state.mastery = 20.0
        prerequisite_state.status = "weak"
        prerequisite_state.effective_evidence = 8.0
        db.flush()

        constrained, applied = PublishedGraphConstraint(db).constrain(
            student_id=student.id,
            course_id=COURSE_ID,
            concept_id=target.id,
            probability=0.9,
        )
        assert applied is True
        assert 0.0 < constrained < 0.9

        prerequisite_state.status = "unseen"
        db.flush()
        unchanged, applied_without_evidence = PublishedGraphConstraint(db).constrain(
            student_id=student.id,
            course_id=COURSE_ID,
            concept_id=target.id,
            probability=0.9,
        )
        assert applied_without_evidence is False
        assert unchanged == 0.9


def test_prerequisite_update_replays_existing_downstream_state(client, student_headers):
    with client.app.state.db.session_factory() as db:
        prerequisite = db.scalar(select(Concept).where(
            Concept.course_id == COURSE_ID,
            Concept.name == "损失函数",
        ))
        target = db.scalar(select(Concept).where(
            Concept.course_id == COURSE_ID,
            Concept.name == "梯度下降",
        ))
        assert prerequisite is not None and target is not None
        prerequisite_id = prerequisite.id
        target_id = target.id

    target_response = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=event_payload(
            "graph-propagation-target",
            outcome=1.0,
            concept_id=target_id,
            occurred_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        ),
    )
    assert target_response.status_code == 200, target_response.text

    prerequisite_response = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events",
        headers=student_headers,
        json=event_payload(
            "graph-propagation-prerequisite",
            outcome=0.0,
            concept_id=prerequisite_id,
        ),
    )
    assert prerequisite_response.status_code == 200, prerequisite_response.text
    changes = {item["concept_id"]: item for item in prerequisite_response.json()["changes"]}
    assert prerequisite_id in changes
    assert target_id in changes
    assert "+a2-graph" in changes[target_id]["model_version"]


def test_online_smoothing_is_cautious_with_sparse_evidence_and_caps_large_updates():
    assert smooth_probability(0.2, 0.8, 0.0) == pytest.approx(0.2)
    assert smooth_probability(0.2, 0.8, 1.0) == pytest.approx(0.2 + 0.6 / 11)
    assert smooth_probability(0.2, 0.8, 100.0) == pytest.approx(0.41)
    assert smooth_probability(0.8, 0.2, 100.0) == pytest.approx(0.59)


@pytest.mark.parametrize("parameters", [
    {"eta_max": -0.1}, {"eta_max": 1.1}, {"eta_max": float("nan")},
    {"kappa": 0.0}, {"kappa": float("inf")},
])
def test_online_smoothing_rejects_invalid_course_parameters(parameters):
    with pytest.raises(ValueError):
        OnlineUpdateConfig(**parameters)


@pytest.mark.parametrize("config", [OnlineUpdateConfig(), OnlineUpdateConfig(eta_max=0.6, kappa=1.0)])
def test_online_update_smooths_before_temporal_and_graph_corrections(client, config):
    class FixedTemporal:
        def predict(self, **kwargs):
            return TemporalPrediction(probability=0.9, gate=0.18, model_version="test-temporal")

    class RecordingGraph:
        def constrain(self, *, probability, **kwargs):
            self.input_probability = probability
            return probability * 0.95, True

    with client.app.state.db.session_factory() as db:
        student = db.scalar(select(User).where(User.email == "student@zhixing.edu.cn"))
        knowledge = db.scalar(select(KnowledgeState).where(
            KnowledgeState.student_id == student.id,
            KnowledgeState.concept_id == LOSS_CONCEPT,
        ))
        knowledge.mastery = 20.0
        knowledge.alpha = 2.0
        knowledge.beta = 2.0
        knowledge.last_evidence_at = None
        graph = RecordingGraph()
        service = TrajectoryService(
            db, temporal=FixedTemporal(), graph=graph,
            course_online_updates={COURSE_ID: config},
        )
        event = SimpleNamespace(
            id="test-smoothing-event", occurred_at=datetime.now(timezone.utc),
            evidence_success=0.8, evidence_reliability=0.6, alignment_confidence=1.0,
        )
        result = service._apply_event(knowledge, event, weight=1.0)
        posterior = 2.48 / 4.6
        eta = min(config.eta_max, 4.6 / (4.6 + config.kappa))
        smoothed = (1 - eta) * 0.2 + eta * posterior
        temporal_result = mix_probabilities(smoothed, 0.9, 0.18)
        assert graph.input_probability == pytest.approx(temporal_result)
        assert result.mastery == pytest.approx(temporal_result * 0.95)
        assert knowledge.mastery == pytest.approx(result.mastery * 100)
        assert result.delta == pytest.approx(result.mastery - 0.2)


def test_online_smoothing_parameters_are_saved_with_event_version(client, student_headers):
    response = ingest_trusted_event(client,
        f"/api/v1/student/courses/{COURSE_ID}/events", headers=student_headers,
        json=event_payload("smoothing-version-01"),
    )
    assert response.status_code == 200, response.text
    from app.models import AuditEvent
    with client.app.state.db.session_factory() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.object_id == response.json()["event_id"]))
        assert audit.metadata_json["model_version"] == "eglt-0.4.0"
        assert audit.metadata_json["online_update"] == {
            "eta_max": 0.35, "kappa": 10.0, "effective_evidence_definition": "alpha+beta",
        }
