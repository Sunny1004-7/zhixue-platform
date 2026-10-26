from __future__ import annotations

from .schemas import ConcreteStrategy, StrategyContext, StrategyDecision, StrategyStep


STRATEGIES: tuple[ConcreteStrategy, ...] = (
    "socratic", "visual", "micro_practice", "web_evidence", "analogy",
)
KEYWORDS: dict[ConcreteStrategy, tuple[str, ...]] = {
    "socratic": ("为什么", "推导", "步骤", "思路", "证明", "怎么想"),
    "visual": ("图", "流程", "关系", "结构", "变化", "可视化"),
    "micro_practice": ("练习", "出题", "检验", "测试", "巩固", "做题"),
    "web_evidence": ("最新", "来源", "依据", "政策", "争议", "联网", "文献"),
    "analogy": ("类比", "举例", "直观", "通俗", "像什么", "不理解"),
}


def _round(score: float) -> float:
    return round(max(0.0, min(score, 1.0)), 4)


def route_strategy(context: StrategyContext) -> StrategyDecision:
    scores: dict[ConcreteStrategy, float] = {item: 0.2 for item in STRATEGIES}
    reasons: dict[ConcreteStrategy, list[str]] = {item: [] for item in STRATEGIES}
    normalized = context.question.lower()
    for strategy, words in KEYWORDS.items():
        hits = sum(1 for word in words if word in normalized)
        if hits:
            scores[strategy] += min(0.5, 0.18 * hits)
            reasons[strategy].append("QUESTION_SIGNAL")
    if context.mastery is not None:
        if context.mastery < 50:
            scores["analogy"] += 0.18
            scores["socratic"] += 0.12
            reasons["analogy"].append("LOW_MASTERY")
            reasons["socratic"].append("LOW_MASTERY")
        elif context.mastery >= 75:
            scores["micro_practice"] += 0.16
            reasons["micro_practice"].append("TRANSFER_READY")
    else:
        reasons["socratic"].append("NO_MASTERY_EVIDENCE")
    if context.confidence is not None and context.confidence < 0.45:
        scores["socratic"] += 0.12
        reasons["socratic"].append("STATE_UNCERTAIN")
    if context.recent_success_rate is not None and context.recent_success_rate < 0.5:
        scores["visual"] += 0.1
        scores["analogy"] += 0.1
        reasons["visual"].append("RECENT_DIFFICULTY")
        reasons["analogy"].append("RECENT_DIFFICULTY")
    scores = {key: _round(value) for key, value in scores.items()}
    if context.selected_strategy != "adaptive":
        strategy = context.selected_strategy
        fixed_reasons = reasons[strategy] or ["STUDENT_SELECTED"]
        if "STUDENT_SELECTED" not in fixed_reasons:
            fixed_reasons.insert(0, "STUDENT_SELECTED")
        return StrategyDecision(
            mode="fixed",
            candidate_scores=scores,
            plan_steps=[StrategyStep(strategy=strategy, reason_codes=fixed_reasons)],
        )
    ordered = sorted(STRATEGIES, key=lambda item: (-scores[item], STRATEGIES.index(item)))
    primary = ordered[0]
    plan = [StrategyStep(
        strategy=primary,
        reason_codes=reasons[primary] or ["DEFAULT_PEDAGOGICAL_FIT"],
    )]
    if scores[ordered[1]] >= 0.45 and scores[ordered[1]] >= scores[primary] - 0.2:
        plan.append(StrategyStep(
            strategy=ordered[1],
            reason_codes=reasons[ordered[1]] or ["COMPLEMENTARY_FIT"],
        ))
    if (
        primary != "micro_practice"
        and context.mastery is not None
        and context.mastery >= 60
        and len(plan) < 3
    ):
        plan.append(StrategyStep(
            strategy="micro_practice",
            reason_codes=["UNDERSTANDING_CHECK"],
        ))
    return StrategyDecision(mode="adaptive", candidate_scores=scores, plan_steps=plan)
