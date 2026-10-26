from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def _normalized(value: Any) -> str:
    return "".join(re.findall(r"[a-z0-9\u4e00-\u9fff]+", str(value).lower()))


@dataclass(frozen=True)
class GradeResult:
    score: float
    is_correct: bool | None
    confidence: float
    grading_mode: str
    review_status: str
    feedback: dict[str, Any]


def grade_answer(
    *,
    question_type: str,
    answer: dict[str, Any],
    answer_spec: dict[str, Any],
    rubric: list[dict[str, Any]],
) -> GradeResult:
    if question_type in {"single", "judgment"}:
        expected = set(answer_spec.get("selected_option_ids") or [])
        selected = set(answer.get("selected_option_ids") or [])
        correct = len(selected) == 1 and selected == expected
        return GradeResult(
            score=1.0 if correct else 0.0,
            is_correct=correct,
            confidence=1.0,
            grading_mode="objective_rule",
            review_status="graded",
            feedback={"summary": "作答正确" if correct else "作答未命中正确选项"},
        )
    if question_type == "multiple":
        expected = set(answer_spec.get("selected_option_ids") or [])
        selected = set(answer.get("selected_option_ids") or [])
        correct_hits = len(expected & selected)
        false_hits = len(selected - expected)
        score = max(0.0, (correct_hits - false_hits) / max(1, len(expected)))
        exact = selected == expected
        return GradeResult(
            score=round(score, 4),
            is_correct=exact,
            confidence=1.0,
            grading_mode="objective_rule",
            review_status="graded",
            feedback={"summary": "所有正确选项均已选中" if exact else "按命中与误选情况给予部分分"},
        )
    if question_type == "fill":
        submitted = _normalized(answer.get("text", ""))
        accepted = {_normalized(item) for item in answer_spec.get("accepted_texts") or []}
        correct = bool(submitted and submitted in accepted)
        return GradeResult(
            score=1.0 if correct else 0.0,
            is_correct=correct,
            confidence=0.98,
            grading_mode="normalized_text_rule",
            review_status="graded",
            feedback={"summary": "填空答案已命中可接受表达" if correct else "当前表达未命中可接受答案"},
        )

    submitted_text = str(answer.get("text", "")).strip()
    submitted_normalized = _normalized(submitted_text)
    weighted = 0.0
    total_weight = 0.0
    matched: list[str] = []
    missing: list[str] = []
    for item in rubric:
        weight = max(0.0, float(item.get("weight", 0.0)))
        criterion = str(item.get("criterion", ""))
        keywords = [_normalized(value) for value in item.get("keywords") or [] if _normalized(value)]
        hit = bool(keywords) and any(keyword in submitted_normalized for keyword in keywords)
        if not keywords:
            criterion_tokens = [_normalized(value) for value in re.split(r"[,;，；、\s]+", criterion) if _normalized(value)]
            hit = any(token in submitted_normalized for token in criterion_tokens)
        weighted += weight * (1.0 if hit else 0.0)
        total_weight += weight
        (matched if hit else missing).append(criterion)
    score = weighted / total_weight if total_weight > 0 else 0.0
    return GradeResult(
        score=round(max(0.0, min(score, 1.0)), 4),
        is_correct=None,
        confidence=0.35,
        grading_mode="subjective_formative_rule",
        review_status="needs_review",
        feedback={
            "summary": "按量规关键证据生成低置信形成性分数，需教师复核",
            "matched_criteria": matched,
            "missing_criteria": missing,
        },
    )
