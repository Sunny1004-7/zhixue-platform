from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


def clip(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class EvidenceScore:
    success: float
    reliability: float
    processing_status: str
    reason: str


def score_event(
    *,
    event_type: str,
    outcome: float | None,
    difficulty: float | None,
    hint_level: int | None,
    attempt_no: int | None,
    completion: float | None,
    upstream_confidence: float,
    alignment_confidence: float,
    payload: dict[str, Any],
) -> EvidenceScore:
    """实现A1公式(1)及非作答事件的可靠度硬上限。"""
    upstream = clip(upstream_confidence)
    alignment = clip(alignment_confidence)
    if alignment < 0.55:
        return EvidenceScore(0.5, 0.0, "awaiting_alignment_review", "知识点对齐置信度不足")

    if event_type == "answer_scored":
        if outcome is None:
            return EvidenceScore(0.5, 0.0, "rejected", "作答评分事件缺少得分比例")
        normalized_hint = clip((hint_level or 0) / 3.0)
        attempts = max(1, attempt_no or 1)
        success = clip(
            outcome
            + 0.18 * ((difficulty if difficulty is not None else 0.5) - 0.5)
            - 0.12 * normalized_hint
            - 0.05 * math.log(attempts)
        )
        grading_cap = 0.85 if payload.get("grading_mode") == "subjective_ai" else 1.0
        reliability = clip(grading_cap * upstream * alignment)
        if payload.get("anomaly_detected"):
            reliability *= 0.2
        return EvidenceScore(success, reliability, "accepted", "作答证据")

    if event_type in {"video_progressed", "video_completed"}:
        active_seconds = float(payload.get("active_seconds", 0))
        duration_seconds = max(float(payload.get("duration_seconds", 1)), 1.0)
        foreground_ratio = clip(float(payload.get("foreground_ratio", 0)))
        if active_seconds < 20 or foreground_ratio < 0.55:
            return EvidenceScore(clip(completion or 0), 0.0, "observed_only", "有效观看证据不足")
        active_ratio = clip(active_seconds / duration_seconds)
        success = clip(0.65 * (completion if completion is not None else active_ratio) + 0.35 * active_ratio)
        reliability = 0.35 * upstream * alignment * foreground_ratio
        return EvidenceScore(success, reliability, "accepted", "有效视频学习证据")

    if event_type in {"knowledge_card_opened", "graph_node_viewed"}:
        dwell_seconds = float(payload.get("dwell_seconds", 0))
        foreground_ratio = clip(float(payload.get("foreground_ratio", 0)))
        if dwell_seconds < 15 or foreground_ratio < 0.55:
            return EvidenceScore(clip(completion or 0), 0.0, "observed_only", "知识卡有效停留不足")
        dwell_score = clip(dwell_seconds / 120.0)
        success = clip(0.55 * (completion if completion is not None else dwell_score) + 0.45 * dwell_score)
        return EvidenceScore(success, 0.25 * upstream * alignment * foreground_ratio, "accepted", "图谱学习弱证据")

    if event_type in {"tutor_message_received", "inline_practice_scored"}:
        effective_turns = int(payload.get("effective_turns", 0))
        check_score = payload.get("understanding_check_score", outcome)
        if effective_turns < 2 or check_score is None:
            return EvidenceScore(0.5, 0.0, "observed_only", "缺少后续理解确认")
        success = clip(float(check_score))
        return EvidenceScore(success, 0.45 * upstream * alignment, "accepted", "有效辅导证据")

    if event_type == "resource_completed":
        success = clip(completion if completion is not None else 1.0)
        return EvidenceScore(success, 0.30 * upstream * alignment, "accepted", "资源完成弱证据")

    return EvidenceScore(0.5, 0.0, "observed_only", "行为被记录但不直接更新掌握度")


def decay_beta(
    alpha: float,
    beta: float,
    delta_days: float,
    *,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
    forgetting_rate: float = 0.003,
) -> tuple[float, float]:
    factor = math.exp(-forgetting_rate * max(0.0, delta_days))
    return (
        prior_alpha + (alpha - prior_alpha) * factor,
        prior_beta + (beta - prior_beta) * factor,
    )


def beta_statistics(alpha: float, beta: float) -> tuple[float, float]:
    total = max(alpha + beta, 1e-9)
    mean = alpha / total
    variance = alpha * beta / (total * total * (total + 1.0))
    return mean, variance


def combined_uncertainty(variance: float, alignment_confidence: float) -> float:
    return clip(2.0 * math.sqrt(max(variance, 0.0)) + 0.15 * (1.0 - clip(alignment_confidence)))


def classify_state(mastery: float, effective_evidence: float, uncertainty: float) -> str:
    if effective_evidence < 2.5 or uncertainty > 0.45:
        return "unseen"
    return "weak" if mastery < 0.5 else "mastered"
