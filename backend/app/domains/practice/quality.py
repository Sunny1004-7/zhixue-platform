from __future__ import annotations

import math
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    BlueprintCell,
    Hint,
    Question,
    QuestionConcept,
    QuestionOption,
    QuestionQualityReport,
    QuestionSetRevision,
)
from .hints import HINT_VALIDATOR_VERSION, validate_progressive_hints
from .schemas import (
    GeneratedFillQuestion,
    GeneratedObjectiveQuestion,
    GeneratedQuestion,
    GeneratedSubjectiveQuestion,
    QuestionGenerationOutput,
)


QUALITY_VALIDATOR_VERSION = "traceq-quality-1.0.0"


@dataclass(frozen=True)
class GateResult:
    hard_pass: bool
    issues: tuple[dict[str, Any], ...]
    metrics: dict[str, Any]


def _compact(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


def _rubric_issues(rubric: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rubric:
        return [_issue("RUBRIC_REQUIRED", "简答题和情境分析题必须配置评分量规")]
    weights: list[float] = []
    issues: list[dict[str, Any]] = []
    for index, criterion in enumerate(rubric, start=1):
        label = criterion.get("criterion")
        weight = criterion.get("weight")
        if not isinstance(label, str) or not label.strip():
            issues.append(_issue("RUBRIC_CRITERION_EMPTY", "量规项描述不能为空", criterion=index))
        if not isinstance(weight, (int, float)) or weight <= 0:
            issues.append(_issue("RUBRIC_WEIGHT_INVALID", "量规权重必须大于0", criterion=index))
        else:
            weights.append(float(weight))
    if weights and not math.isclose(sum(weights), 1.0, abs_tol=1e-6):
        issues.append(_issue("RUBRIC_WEIGHT_SUM_INVALID", "量规权重之和必须为1"))
    return issues


def _question_schema_issues(
    *,
    question_type: str,
    prompt: str,
    options: list[dict[str, Any]],
    answer_spec: dict[str, Any],
    rubric: list[dict[str, Any]],
    hints: list[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if len(_compact(prompt)) < 2:
        issues.append(_issue("QUESTION_PROMPT_EMPTY", "题干不能为空"))
    option_contents = [_compact(str(item.get("content") or "")) for item in options]
    if any(not item for item in option_contents):
        issues.append(_issue("QUESTION_OPTION_EMPTY", "选项正文不能为空"))
    if len(option_contents) != len(set(option_contents)):
        issues.append(_issue("QUESTION_OPTION_DUPLICATE", "同一题的选项不能重复"))
    correct_options = [item for item in options if item.get("is_correct") is True]

    if question_type == "single":
        if len(options) < 3:
            issues.append(_issue("SINGLE_OPTION_COUNT_INVALID", "单选题至少需要3个选项"))
        if len(correct_options) != 1:
            issues.append(_issue("SINGLE_ANSWER_COUNT_INVALID", "单选题必须恰好有一个正确选项"))
    elif question_type == "multiple":
        if len(options) < 4:
            issues.append(_issue("MULTIPLE_OPTION_COUNT_INVALID", "多选题至少需要4个选项"))
        if len(correct_options) < 2 or len(correct_options) >= len(options):
            issues.append(_issue("MULTIPLE_ANSWER_COUNT_INVALID", "多选题至少有两个正确项且至少有一个错误项"))
    elif question_type == "judgment":
        if len(options) != 2 or {_compact(item.get("content", "")) for item in options} != {"正确", "错误"}:
            issues.append(_issue("JUDGMENT_OPTION_SCHEMA_INVALID", "判断题必须提供“正确”和“错误”两个可选项"))
        if len(correct_options) != 1:
            issues.append(_issue("JUDGMENT_ANSWER_COUNT_INVALID", "判断题必须恰好有一个正确选项"))
    elif question_type == "fill":
        if options:
            issues.append(_issue("FILL_OPTIONS_NOT_ALLOWED", "填空题不能包含选择题选项"))
        accepted = answer_spec.get("accepted_texts")
        if not isinstance(accepted, list) or not accepted or any(not isinstance(item, str) or not item.strip() for item in accepted):
            issues.append(_issue("FILL_ANSWER_SPEC_INVALID", "填空题必须包含非空可接受答案"))
    elif question_type in {"short", "scenario"}:
        if options:
            issues.append(_issue("SUBJECTIVE_OPTIONS_NOT_ALLOWED", "主观题不能包含选择题选项"))
        if not isinstance(answer_spec.get("reference_answer"), str) or not answer_spec["reference_answer"].strip():
            issues.append(_issue("REFERENCE_ANSWER_REQUIRED", "主观题必须包含参考答案"))
        issues.extend(_rubric_issues(rubric))
    else:
        issues.append(_issue("QUESTION_TYPE_UNSUPPORTED", "题型不在TraceQ受控枚举中"))

    if question_type in {"single", "multiple", "judgment"}:
        selected_ids = answer_spec.get("selected_option_ids")
        option_ids = {str(item.get("id")) for item in options if item.get("id") is not None}
        expected_ids = {str(item.get("id")) for item in correct_options if item.get("id") is not None}
        if option_ids and (
            not isinstance(selected_ids, list)
            or set(str(item) for item in selected_ids) != expected_ids
        ):
            issues.append(_issue("OBJECTIVE_ANSWER_SPEC_MISMATCH", "答案契约与选项正确标记不一致"))

    answer_texts = [str(item.get("content") or "") for item in correct_options]
    if question_type == "fill":
        answer_texts.extend(str(item) for item in answer_spec.get("accepted_texts", []))
    if question_type in {"short", "scenario"}:
        answer_texts.append(str(answer_spec.get("reference_answer") or ""))
    hint_check = validate_progressive_hints(
        hints,
        answer_texts=answer_texts,
        rubric_claims=[str(item.get("criterion") or "") for item in rubric],
    )
    issues.extend(_issue(item.code, item.message, level=item.level) for item in hint_check.issues)
    return issues


def _generated_parts(question: GeneratedQuestion) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if isinstance(question, GeneratedObjectiveQuestion):
        return ([item.model_dump() for item in question.options], {}, [])
    if isinstance(question, GeneratedFillQuestion):
        return ([], {
            "accepted_texts": question.accepted_texts,
            "numeric_answer": question.numeric_answer,
            "absolute_tolerance": question.absolute_tolerance,
            "relative_tolerance": question.relative_tolerance,
        }, [])
    assert isinstance(question, GeneratedSubjectiveQuestion)
    return ([], {"reference_answer": question.reference_answer}, [item.model_dump() for item in question.rubric])


def validate_generation_output(
    output: QuestionGenerationOutput,
    *,
    cells: list[BlueprintCell],
    allowed_evidence_by_concept: dict[str, set[str]],
) -> GateResult:
    issues: list[dict[str, Any]] = []
    cell_by_id = {item.id: item for item in cells}
    actual_counts = Counter(item.blueprint_cell_id for item in output.questions)
    for cell in cells:
        if actual_counts[cell.id] != cell.count:
            issues.append(_issue(
                "BLUEPRINT_CELL_COUNT_MISMATCH",
                "生成结果未精确满足蓝图单元题量",
                blueprint_cell_id=cell.id,
                expected=cell.count,
                actual=actual_counts[cell.id],
            ))
    for unknown in set(actual_counts) - set(cell_by_id):
        issues.append(_issue("BLUEPRINT_CELL_OUT_OF_SCOPE", "生成结果引用了蓝图外单元", blueprint_cell_id=unknown))

    prompt_values: list[tuple[int, str]] = []
    for index, question in enumerate(output.questions, start=1):
        cell = cell_by_id.get(question.blueprint_cell_id)
        if cell is None:
            continue
        if question.question_type != cell.question_type:
            issues.append(_issue(
                "BLUEPRINT_TYPE_MISMATCH",
                "生成题型与蓝图单元不一致",
                question=index,
                expected=cell.question_type,
                actual=question.question_type,
            ))
        if abs(question.difficulty_prior - cell.difficulty_target) > 0.35:
            issues.append(_issue(
                "DIFFICULTY_TARGET_MISMATCH",
                "生成难度明显偏离蓝图目标",
                question=index,
                target=cell.difficulty_target,
                actual=question.difficulty_prior,
            ))
        allowed_evidence = allowed_evidence_by_concept.get(cell.concept_id, set())
        if set(question.evidence_ids) - allowed_evidence:
            issues.append(_issue(
                "QUESTION_EVIDENCE_OUT_OF_SCOPE",
                "题目引用了当前知识来源之外的证据",
                question=index,
            ))
        options, answer_spec, rubric = _generated_parts(question)
        issues.extend(
            {**item, "question": index}
            for item in _question_schema_issues(
                question_type=question.question_type,
                prompt=question.prompt,
                options=options,
                answer_spec=answer_spec,
                rubric=rubric,
                hints=question.hints,
            )
        )
        prompt_values.append((index, _compact(question.prompt)))

    for left_index, (left_position, left_prompt) in enumerate(prompt_values):
        for right_position, right_prompt in prompt_values[left_index + 1:]:
            if left_prompt == right_prompt or SequenceMatcher(None, left_prompt, right_prompt).ratio() >= 0.94:
                issues.append(_issue(
                    "QUESTION_NEAR_DUPLICATE",
                    "同一题组中存在相同或近重复题干",
                    questions=[left_position, right_position],
                ))
    return GateResult(
        hard_pass=not issues,
        issues=tuple(issues),
        metrics={
            "expected_total": sum(item.count for item in cells),
            "actual_total": len(output.questions),
            "cell_count": len(cells),
            "issue_count": len(issues),
            "exact_blueprint_match": not any(item["code"].startswith("BLUEPRINT_") for item in issues),
        },
    )


def validate_revision(db: Session, revision: QuestionSetRevision) -> GateResult:
    questions = list(db.scalars(select(Question).where(
        Question.revision_id == revision.id
    ).order_by(Question.position)).all())
    issues: list[dict[str, Any]] = []
    actual_distribution: Counter[tuple[str, str]] = Counter()
    prompt_values: list[tuple[int, str]] = []
    question_issue_count = 0

    for question in questions:
        options_orm = list(db.scalars(select(QuestionOption).where(
            QuestionOption.question_id == question.id
        ).order_by(QuestionOption.position)).all())
        concepts = list(db.scalars(select(QuestionConcept).where(
            QuestionConcept.question_id == question.id
        ).order_by(QuestionConcept.id)).all())
        hints = list(db.scalars(select(Hint).where(
            Hint.question_id == question.id
        ).order_by(Hint.level)).all())
        options = [{
            "id": item.id,
            "content": item.content,
            "is_correct": item.is_correct,
        } for item in options_orm]
        local = _question_schema_issues(
            question_type=question.question_type,
            prompt=question.prompt,
            options=options,
            answer_spec=question.answer_spec_json or {},
            rubric=question.rubric_json or [],
            hints=[item.content for item in hints],
        )
        if not concepts:
            local.append(_issue("QUESTION_CONCEPT_REQUIRED", "每道题必须关联至少一个课程知识点"))
        elif not math.isclose(sum(item.weight for item in concepts), 1.0, abs_tol=1e-6):
            local.append(_issue("QUESTION_CONCEPT_WEIGHT_INVALID", "题目知识点权重之和必须为1"))
        for concept in concepts:
            actual_distribution[(concept.concept_id, question.question_type)] += 1
        issues.extend({**item, "question_id": question.id, "position": question.position} for item in local)
        question_issue_count += len(local)
        prompt_values.append((question.position, _compact(question.prompt)))
        db.add(QuestionQualityReport(
            id=str(uuid4()),
            revision_id=revision.id,
            question_id=question.id,
            hard_pass=not local,
            hard_gates_json={"schema": not local, "hint_validator": HINT_VALIDATOR_VERSION},
            dimension_scores_json={"deterministic_quality": 1.0 if not local else 0.0},
            issues_json=local,
            validator_version=QUALITY_VALIDATOR_VERSION,
        ))

    if not questions:
        issues.append(_issue("QUESTION_SET_EMPTY", "题组至少需要一道题"))
    for left_index, (left_position, left_prompt) in enumerate(prompt_values):
        for right_position, right_prompt in prompt_values[left_index + 1:]:
            if left_prompt == right_prompt or SequenceMatcher(None, left_prompt, right_prompt).ratio() >= 0.94:
                issues.append(_issue(
                    "QUESTION_NEAR_DUPLICATE",
                    "同一题组中存在相同或近重复题干",
                    positions=[left_position, right_position],
                ))

    if revision.blueprint_id:
        cells = list(db.scalars(select(BlueprintCell).where(
            BlueprintCell.blueprint_id == revision.blueprint_id
        )).all())
        expected = Counter({(cell.concept_id, cell.question_type): cell.count for cell in cells})
        if expected != actual_distribution:
            issues.append(_issue(
                "QUESTION_SET_BLUEPRINT_MISMATCH",
                "题组实际知识点、题型或题量与蓝图不一致",
                expected={f"{key[0]}::{key[1]}": value for key, value in expected.items()},
                actual={f"{key[0]}::{key[1]}": value for key, value in actual_distribution.items()},
            ))

    result = GateResult(
        hard_pass=not issues,
        issues=tuple(issues),
        metrics={
            "question_count": len(questions),
            "question_issue_count": question_issue_count,
            "set_issue_count": len(issues) - question_issue_count,
            "blueprint_exact": not any(item["code"] == "QUESTION_SET_BLUEPRINT_MISMATCH" for item in issues),
        },
    )
    db.add(QuestionQualityReport(
        id=str(uuid4()),
        revision_id=revision.id,
        question_id=None,
        hard_pass=result.hard_pass,
        hard_gates_json={
            "schema": question_issue_count == 0,
            "blueprint": result.metrics["blueprint_exact"],
            "duplicates": not any(item["code"] == "QUESTION_NEAR_DUPLICATE" for item in issues),
        },
        dimension_scores_json={
            "deterministic_quality": 1.0 if result.hard_pass else 0.0,
            "question_count": len(questions),
        },
        issues_json=list(result.issues),
        validator_version=QUALITY_VALIDATOR_VERSION,
    ))
    return result
