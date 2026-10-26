from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


HINT_VALIDATOR_VERSION = "traceq-hint-1.0.0"
_OPTION_LABEL_PATTERN = re.compile(
    r"(?:答案|正确选项|应选|选择|选)\s*(?:是|为|[:：])?\s*[A-H](?:\b|项|选项)",
    re.IGNORECASE,
)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _units(value: str) -> set[str]:
    compact = normalize_text(value)
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index:index + 2] for index in range(len(compact) - 1)}


def _overlap(left: str, right: str) -> float:
    left_units = _units(left)
    right_units = _units(right)
    if not left_units or not right_units:
        return 0.0
    return len(left_units & right_units) / len(left_units | right_units)


@dataclass(frozen=True)
class HintIssue:
    code: str
    level: int
    message: str


@dataclass(frozen=True)
class HintCheck:
    passed: bool
    leakage_scores: tuple[float, float, float]
    information_gains: tuple[float, float, float]
    issues: tuple[HintIssue, ...]


def validate_progressive_hints(
    hints: list[str],
    *,
    answer_texts: list[str],
    rubric_claims: list[str] | None = None,
) -> HintCheck:
    issues: list[HintIssue] = []
    if len(hints) != 3:
        issues.append(HintIssue("HINT_COUNT_INVALID", 0, "每道题必须恰好包含三级提示"))
    padded = (hints + ["", "", ""])[:3]
    normalized_hints = [normalize_text(item) for item in padded]
    answer_values = [item for item in answer_texts if normalize_text(item)]
    rubric_values = [item for item in (rubric_claims or []) if normalize_text(item)]
    leakage_scores: list[float] = []

    for index, hint in enumerate(padded, start=1):
        compact = normalized_hints[index - 1]
        leakage = 0.0
        if len(compact) < 6:
            issues.append(HintIssue("HINT_TOO_SHORT", index, "提示信息不足，无法形成有效引导"))
        if _OPTION_LABEL_PATTERN.search(unicodedata.normalize("NFKC", hint)):
            leakage = 1.0
            issues.append(HintIssue("HINT_OPTION_LABEL_LEAK", index, "提示直接给出了选项标签"))
        for answer in answer_values:
            normalized_answer = normalize_text(answer)
            lexical = _overlap(hint, answer)
            sequence = SequenceMatcher(None, compact, normalized_answer).ratio()
            leakage = max(leakage, lexical, sequence)
            if len(normalized_answer) >= 3 and normalized_answer in compact:
                leakage = 1.0
                issues.append(HintIssue("HINT_DIRECT_ANSWER_LEAK", index, "提示包含规范答案或正确选项正文"))
                break
            if lexical >= 0.72 or sequence >= 0.82:
                issues.append(HintIssue("HINT_HIGH_ANSWER_OVERLAP", index, "提示与答案的词面重合过高"))
                break
        if rubric_values:
            covered = sum(1 for claim in rubric_values if _overlap(hint, claim) >= 0.65)
            rubric_coverage = covered / len(rubric_values)
            leakage = max(leakage, rubric_coverage)
            if rubric_coverage >= 0.8:
                issues.append(HintIssue("HINT_RUBRIC_COVERAGE_LEAK", index, "提示覆盖了几乎全部主观题评分要点"))
        leakage_scores.append(round(min(1.0, leakage), 4))

    for right in range(1, 3):
        left_hint = normalized_hints[right - 1]
        right_hint = normalized_hints[right]
        similarity = SequenceMatcher(None, left_hint, right_hint).ratio()
        if left_hint == right_hint or similarity >= 0.88:
            issues.append(HintIssue("HINT_LEVEL_DUPLICATE", right + 1, "相邻提示缺少递进差异"))

    information_gains = (0.2, 0.45, 0.68)
    return HintCheck(
        passed=not issues,
        leakage_scores=tuple(leakage_scores),
        information_gains=information_gains,
        issues=tuple(issues),
    )
