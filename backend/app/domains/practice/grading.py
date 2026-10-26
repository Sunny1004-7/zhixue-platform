from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GradingResult:
    score: float
    is_correct: bool | None
    confidence: float
    grading_mode: str
    review_status: str
    feedback: dict[str, Any]


def normalize_fill(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.strip("。．.，,；;：:、")


def _numeric(value: str) -> float | None:
    candidate = unicodedata.normalize("NFKC", value).strip().replace(",", "")
    match = re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", candidate)
    if match is None:
        return None
    try:
        number = float(candidate)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def grade_objective(
    *,
    question_type: str,
    answer: dict[str, Any],
    correct_option_ids: set[str],
    valid_option_ids: set[str],
) -> GradingResult:
    raw_selected = answer.get("selected_option_ids")
    if not isinstance(raw_selected, list) or not raw_selected or any(not isinstance(item, str) for item in raw_selected):
        raise ValueError("客观题答案必须包含非空selected_option_ids数组")
    selected = list(dict.fromkeys(raw_selected))
    if len(selected) != len(raw_selected):
        raise ValueError("同一选项不能重复提交")
    if set(selected) - valid_option_ids:
        raise ValueError("答案包含当前题目之外的选项")
    if question_type in {"single", "judgment"} and len(selected) != 1:
        raise ValueError("单选题和判断题必须且只能选择一个选项")
    matched = set(selected) == correct_option_ids
    return GradingResult(
        score=1.0 if matched else 0.0,
        is_correct=matched,
        confidence=1.0,
        grading_mode="objective_exact",
        review_status="graded",
        feedback={
            "summary": "回答正确。" if matched else "本次答案与已审核标准答案不一致。",
            "selected_count": len(selected),
            "expected_count": len(correct_option_ids),
        },
    )


def grade_fill(*, answer: dict[str, Any], answer_spec: dict[str, Any]) -> GradingResult:
    raw_text = answer.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("填空题答案不能为空")
    accepted = answer_spec.get("accepted_texts", [])
    if not isinstance(accepted, list) or not accepted or any(not isinstance(item, str) for item in accepted):
        raise ValueError("填空题缺少可执行的规范答案")
    normalized = normalize_fill(raw_text)
    matched = normalized in {normalize_fill(item) for item in accepted}
    numeric_target = answer_spec.get("numeric_answer")
    if not matched and isinstance(numeric_target, (int, float)):
        submitted = _numeric(raw_text)
        if submitted is not None:
            absolute = float(answer_spec.get("absolute_tolerance") or 0.0)
            relative = float(answer_spec.get("relative_tolerance") or 0.0)
            tolerance = max(absolute, relative * abs(float(numeric_target)))
            matched = abs(submitted - float(numeric_target)) <= tolerance
    return GradingResult(
        score=1.0 if matched else 0.0,
        is_correct=matched,
        confidence=1.0,
        grading_mode="fill_normalized",
        review_status="graded",
        feedback={
            "summary": "答案符合规范化匹配规则。" if matched else "答案未匹配已审核的别名或数值容差。",
            "normalizer_version": "traceq-fill-1.0.0",
        },
    )


def _units(value: str) -> set[str]:
    compact = normalize_fill(value)
    if len(compact) <= 1:
        return {compact} if compact else set()
    return {compact[index:index + 2] for index in range(len(compact) - 1)}


def _coverage(answer: str, criterion: str) -> float:
    expected = _units(criterion)
    if not expected:
        return 0.0
    actual = _units(answer)
    return len(actual & expected) / len(expected)


def grade_subjective_provisional(
    *,
    answer: dict[str, Any],
    answer_spec: dict[str, Any],
    rubric: list[dict[str, Any]],
) -> GradingResult:
    raw_text = answer.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("主观题答案不能为空")
    if not rubric:
        raise ValueError("主观题缺少发布前冻结的评分量规")
    total_weight = 0.0
    weighted_score = 0.0
    criteria_feedback: list[dict[str, Any]] = []
    reference = str(answer_spec.get("reference_answer") or "")
    for index, criterion in enumerate(rubric, start=1):
        weight = criterion.get("weight")
        if not isinstance(weight, (int, float)) or weight <= 0:
            raise ValueError("主观题量规权重必须大于0")
        patterns: list[str] = []
        for key in ("keywords", "accepted_patterns"):
            value = criterion.get(key, [])
            if isinstance(value, list):
                patterns.extend(str(item) for item in value if str(item).strip())
        for key in ("evidence", "criterion"):
            value = criterion.get(key)
            if isinstance(value, str) and value.strip():
                patterns.append(value)
        if not patterns and reference:
            patterns.append(reference)
        satisfaction = max((_coverage(raw_text, item) for item in patterns), default=0.0)
        satisfaction = max(0.0, min(1.0, satisfaction))
        total_weight += float(weight)
        weighted_score += float(weight) * satisfaction
        criteria_feedback.append({
            "index": index,
            "criterion": str(criterion.get("criterion") or f"量规项{index}"),
            "provisional_satisfaction": round(satisfaction, 4),
        })
    if not math.isclose(total_weight, 1.0, abs_tol=1e-6):
        raise ValueError("主观题量规权重之和必须为1")
    provisional = max(0.0, min(1.0, weighted_score / total_weight))
    return GradingResult(
        score=round(provisional, 4),
        is_correct=None,
        confidence=0.3,
        grading_mode="subjective_rubric_provisional",
        review_status="needs_review",
        feedback={
            "summary": "已按冻结量规生成低置信暂定结果；未配置语义评阅器，需教师复核。",
            "criteria": criteria_feedback,
            "semantic_grader_available": False,
            "provisional": True,
        },
    )
