from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domains.tutoring.memory import MemoryCandidate, recall_memories
from app.domains.tutoring.router import route_strategy
from app.domains.tutoring.schemas import StrategyContext, VisualEdge, VisualNode, VisualSpec


def test_fixed_strategy_is_never_silently_switched():
    decision = route_strategy(StrategyContext(
        question="请联网找最新来源，再给我做一道题",
        selected_strategy="visual",
        mastery=80,
    ))
    assert decision.mode == "fixed"
    assert [item.strategy for item in decision.plan_steps] == ["visual"]
    assert "STUDENT_SELECTED" in decision.plan_steps[0].reason_codes


def test_adaptive_strategy_uses_problem_and_state_without_history_claims():
    decision = route_strategy(StrategyContext(
        question="我不理解损失函数，能用通俗类比解释吗？",
        selected_strategy="adaptive",
        mastery=38,
        confidence=0.8,
    ))
    assert decision.mode == "adaptive"
    assert decision.plan_steps[0].strategy == "analogy"
    assert len(decision.plan_steps) <= 3


def test_visual_spec_rejects_dangling_edges():
    try:
        VisualSpec(
            kind="flow",
            title="梯度下降流程",
            alt_text="从计算梯度到更新参数的有向流程图",
            nodes=[VisualNode(id="a", label="计算梯度"), VisualNode(id="b", label="更新参数")],
            edges=[VisualEdge(source="a", target="missing")],
        )
    except ValueError as error:
        assert "不存在的节点" in str(error)
    else:
        raise AssertionError("dangling visual edge should fail validation")


def test_memory_recall_requires_authorization_and_course_scope():
    now = datetime.now(timezone.utc)
    memories = [
        MemoryCandidate("m1", "s1", "c1", "学生容易混淆损失函数与评价指标", 0.9, "confirmed", now),
        MemoryCandidate("m2", "s1", "c2", "另一门课程的损失函数", 0.95, "active", now),
        MemoryCandidate("m3", "s2", "c1", "其他学生的损失函数", 0.95, "active", now),
    ]
    assert recall_memories(
        memories, student_id="s1", course_id="c1", query="损失函数", authorized=False,
    ) == []
    recalled = recall_memories(
        memories, student_id="s1", course_id="c1", query="损失函数", authorized=True,
    )
    assert [item.memory.id for item in recalled] == ["m1"]


def test_memory_recall_filters_expired_deleted_and_conflicts():
    now = datetime.now(timezone.utc)
    memories = [
        MemoryCandidate("new", "s1", "c1", "偏好图示解释", 0.9, "confirmed", now, conflict_group="preference"),
        MemoryCandidate("old", "s1", "c1", "偏好文字解释", 0.8, "active", now - timedelta(days=30), conflict_group="preference"),
        MemoryCandidate("expired", "s1", "c1", "旧知识", 0.9, "active", now - timedelta(days=100), expires_at=now),
        MemoryCandidate("deleted", "s1", "c1", "已删除", 0.9, "active", now, deleted_at=now),
    ]
    recalled = recall_memories(
        memories, student_id="s1", course_id="c1", query="偏好解释", authorized=True, now=now,
    )
    assert [item.memory.id for item in recalled] == ["new"]
