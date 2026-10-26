from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domains.teaching_decision.attention import (
    AttentionInput,
    attention_score,
    priority_students,
)
from app.domains.teaching_decision.audience import (
    StudentConceptState,
    classify_state,
    resolve_audience,
)
from app.domains.teaching_decision.snapshots import stable_snapshot_hash


def test_attention_formula_uses_frozen_weights_and_saturation():
    result = attention_score(AttentionInput(
        student_id="s1",
        practice_count=40,
        accuracy=80,
        resource_completion=60,
        effective_tutoring_count=6,
    ))
    assert result.practice_score == 100
    assert result.tutoring_score == 100
    assert result.score == 84.0
    saturated = attention_score(AttentionInput(
        student_id="s2",
        practice_count=400,
        accuracy=120,
        resource_completion=-10,
        effective_tutoring_count=60,
    ))
    assert saturated.score == 75.0


def test_missing_confidence_does_not_reweight_score():
    value = AttentionInput(
        student_id="s1", practice_count=20, accuracy=70,
        resource_completion=50, effective_tutoring_count=3,
        practice_confidence=0.0, accuracy_confidence=0.2,
        resource_confidence=0.0, tutoring_confidence=0.0,
    )
    result = attention_score(value)
    assert result.score == 56.0
    assert result.confidence == 0.06


def test_priority_ties_use_old_activity_then_low_confidence_then_id():
    now = datetime.now(timezone.utc)
    values = [
        attention_score(AttentionInput("b", 20, 50, 50, 3, last_activity_at=now)),
        attention_score(AttentionInput("a", 20, 50, 50, 3, last_activity_at=now - timedelta(days=1))),
        attention_score(AttentionInput("c", 40, 90, 90, 6, last_activity_at=now)),
    ]
    assert [item.student_id for item in priority_students(values, 3)] == ["a", "b", "c"]


def test_three_state_boundaries_are_exact():
    base = dict(student_id="s1", course_id="c1", concept_id="k1", confidence=0.9, effective_evidence=5.0, uncertainty=0.1)
    assert classify_state(StudentConceptState(**{**base, "effective_evidence": 2.0, "uncertainty": 0.577}, mastery=99, evidence_count=0)) == "unseen"
    assert classify_state(StudentConceptState(**base, mastery=49.999, evidence_count=1)) == "weak"
    assert classify_state(StudentConceptState(**base, mastery=50.0, evidence_count=1)) == "mastered"


def test_audience_is_course_scoped_or_match_and_deduplicated():
    states = [
        StudentConceptState("s1", "c1", "k1", 40, 3, 0.8, 5.0, 0.2),
        StudentConceptState("s1", "c1", "k2", 0, 0, 0.0, 0.0, 1.0),
        StudentConceptState("s1", "c2", "k1", 20, 5, 0.9, 7.0, 0.1),
        StudentConceptState("s2", "c1", "k1", 80, 4, 0.9, 6.0, 0.1),
    ]
    matches = resolve_audience(
        states,
        course_id="c1",
        resource_concept_ids=["k1", "k2", "k1"],
        selected_states={"weak", "unseen"},
    )
    assert len(matches) == 1
    assert matches[0].student_id == "s1"
    assert matches[0].matched_concepts == ("k1", "k2")
    assert matches[0].low_evidence is True


def test_snapshot_hash_is_order_independent_but_value_sensitive():
    assert stable_snapshot_hash({"b": 2, "a": [1, 2]}) == stable_snapshot_hash({"a": [1, 2], "b": 2})
    assert stable_snapshot_hash({"a": 1}) != stable_snapshot_hash({"a": 2})
