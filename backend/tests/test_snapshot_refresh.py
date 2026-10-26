from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

from sqlalchemy import func, select
from app.learning_support_models import AttentionScoreSnapshot, DecisionSnapshot


def test_concurrent_snapshot_refresh_reuses_identical_input(client, teacher_headers):
    when = datetime.now(timezone.utc).isoformat()
    barrier = Barrier(3)
    def refresh(_):
        barrier.wait(timeout=10)
        return client.post('/api/v1/courses/machine-learning/decision-snapshots:refresh',
                           headers=teacher_headers, json={'as_of': when})
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(refresh, range(3)))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    snapshots = [r.json() for r in responses]
    assert len({s['snapshot_id'] for s in snapshots}) == 1
    with client.app.state.db.session_factory() as db:
        saved = db.scalar(select(DecisionSnapshot).where(DecisionSnapshot.id == snapshots[0]['snapshot_id']))
        assert db.scalar(select(func.count()).select_from(DecisionSnapshot).where(
            DecisionSnapshot.snapshot_hash == saved.snapshot_hash)) == 1
        assert db.scalar(select(func.count()).select_from(AttentionScoreSnapshot).where(
            AttentionScoreSnapshot.snapshot_id == saved.id)) == saved.student_count
