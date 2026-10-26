from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.orm import Session

from .domains.practice.hints import HINT_VALIDATOR_VERSION, validate_progressive_hints
from .domains.practice.quality import validate_revision
from .models import (
    Attempt,
    Hint,
    Question,
    QuestionConcept,
    QuestionOption,
    QuestionSet,
    QuestionSetRevision,
    Score,
)


SEED_TIME = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


def _stable_id(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"zhixing:{value}"))


COURSE_SEEDS: dict[str, dict[str, Any]] = {
    "machine-learning": {
        "set_id": "ml-q1",
        "title": "损失函数分层习题组",
        "fill_1": {
            "prompt": "用于衡量模型预测值与真实目标之间差异的函数称为什么？",
            "accepted_texts": ["损失函数", "代价函数"],
        },
        "short": {
            "prompt": "请说明用梯度下降优化线性回归模型时的主要步骤，并说明如何判断迭代可以停止。",
            "reference": "先定义损失函数并初始化参数，计算损失对参数的梯度，按学习率沿负梯度方向更新参数，持续监测损失变化，在收敛或达到停止条件时结束。",
            "keywords": [["损失", "目标"], ["梯度", "参数更新"], ["收敛", "停止条件"]],
        },
        "scenario": {
            "prompt": "某小组训练线性回归模型时把学习率从0.01直接改为10，损失值随后剧烈振荡。请分析原因并给出改进方案。",
            "reference": "学习率过大会使参数更新步长越过较优区域并产生振荡。应降低学习率，观察损失曲线，并通过小范围对比或衰减策略选择稳定取值。",
            "keywords": [["步长", "振荡"], ["降低", "衰减"], ["损失曲线", "对比"]],
        },
        "single_2": {
            "prompt": "比较两个回归模型的泛化能力时，下列哪种做法最合理？",
            "options": [
                ("在独立验证数据上使用相同指标比较", True),
                ("只比较训练集上的最低损失", False),
                ("选择参数数量更多的模型", False),
                ("只查看一次随机样本的预测", False),
            ],
        },
        "fill_2": {
            "prompt": "把原始变量转换为更适合模型学习的输入表示，这一过程通常称为什么？",
            "accepted_texts": ["特征工程", "特征构造"],
        },
    },
    "ai-intro": {
        "set_id": "ai-q1",
        "title": "知识图谱结构习题组",
        "fill_1": {
            "prompt": "依据已知事实与规则推出新结论的过程称为什么？",
            "accepted_texts": ["规则推理", "基于规则的推理"],
        },
        "short": {
            "prompt": "请说明如何把一个问题表示为状态空间，并据此组织求解过程。",
            "reference": "先定义初始状态、可执行动作、状态转移和目标条件，再选择合适的搜索策略展开候选状态，并检查所得路径是否满足目标与约束。",
            "keywords": [["初始状态", "目标条件"], ["动作", "状态转移"], ["搜索", "路径"]],
        },
        "scenario": {
            "prompt": "一个检索智能体始终优先扩展当前看起来最接近目标的节点，却多次陷入局部循环。请分析策略风险并提出改进。",
            "reference": "仅依赖局部启发值可能重复访问状态或错过更优路径。应维护已访问集合，并结合累计代价、深度限制或其他完整性约束改进检索。",
            "keywords": [["局部", "重复"], ["已访问集合", "去重"], ["累计代价", "限制"]],
        },
        "single_2": {
            "prompt": "评估一个规划与决策方案是否可靠时，哪类证据最充分？",
            "options": [
                ("在明确目标和约束下复核行动序列及结果", True),
                ("只确认方案描述足够长", False),
                ("仅依据第一次生成的结论", False),
                ("忽略环境变化继续执行", False),
            ],
        },
        "fill_2": {
            "prompt": "智能体通过规范接口调用检索、计算等外部能力，这种机制通常称为什么？",
            "accepted_texts": ["工具调用", "函数调用"],
        },
    },
    "data-intelligence": {
        "set_id": "di-q1",
        "title": "特征工程实践习题组",
        "fill_1": {
            "prompt": "识别显著偏离常见数据模式的样本或观测，这一过程称为什么？",
            "accepted_texts": ["异常检测", "离群点检测"],
        },
        "short": {
            "prompt": "请说明为城市交通流预测构造特征时，如何避免时间信息泄漏并保证流程可复现。",
            "reference": "先确定预测时点，只使用该时点之前可获得的数据构造特征；按时间划分训练与验证数据，并把清洗和变换步骤固化在可复现流水线中。",
            "keywords": [["预测时点", "历史数据"], ["时间划分", "验证"], ["流水线", "可复现"]],
        },
        "scenario": {
            "prompt": "某小组用当天24小时完整流量的均值预测当天早高峰流量，并获得很高验证分数。请分析问题并提出修正方案。",
            "reference": "特征使用了预测时点之后的数据，造成时间泄漏和虚高结果。应按预测时点截断可用数据，重新构造历史窗口，并采用时间顺序验证。",
            "keywords": [["未来数据", "时间泄漏"], ["预测时点", "截断"], ["历史窗口", "时间验证"]],
        },
        "single_2": {
            "prompt": "检查交通预测数据是否存在时间泄漏时，哪种做法最有效？",
            "options": [
                ("逐项核对每个特征在预测时点是否已经可得", True),
                ("只检查数据表是否存在空值", False),
                ("随机打乱全部日期再验证", False),
                ("仅比较模型参数数量", False),
            ],
        },
        "fill_2": {
            "prompt": "用于提供最低可比较性能、检验复杂方案是否真正改进的简单模型称为什么？",
            "accepted_texts": ["基线模型", "基准模型"],
        },
    },
}


def _base_questions(course_id: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    concept = lambda index: f"{course_id}:concept:{index:02d}"
    return [
        {
            "type": "single",
            "concept_id": concept(1),
            "prompt": f"关于“{_concept_label(course_id, 1)}”的学习，下列哪种做法最能形成可复核的掌握证据？",
            "options": [
                ("在新问题中独立完成关键步骤并说明依据", True),
                ("只抄录教材中的最终结论", False),
                ("仅记住相关术语的名称", False),
                ("跳过适用条件直接套用结果", False),
            ],
            "hints": [
                "先区分记忆行为与能够迁移的学习证据。",
                "关注是否需要学习者亲自完成推理过程。",
                "比较各做法能否呈现完整的思考链条。",
            ],
        },
        {
            "type": "multiple",
            "concept_id": concept(2),
            "prompt": f"分析“{_concept_label(course_id, 2)}”相关方案时，哪些做法有助于减少推理或操作错误？",
            "options": [
                ("先确认输入、符号和适用条件", True),
                ("保留关键中间步骤并检查结果", True),
                ("忽略前提，只比较最终数字", False),
                ("遇到冲突时删除不利证据", False),
            ],
            "hints": [
                "从过程是否可以复查的角度筛选。",
                "同时考虑开始前和完成后的检查动作。",
                "选择能够暴露条件遗漏或计算偏差的做法。",
            ],
        },
        {
            "type": "judgment",
            "concept_id": concept(3),
            "prompt": f"处理“{_concept_label(course_id, 3)}”相关问题时，只要最终答案看起来合理，就可以省略条件检查与过程核验。",
            "options": [("正确", False), ("错误", True)],
            "hints": [
                "判断命题是否在所有相关情形下都成立。",
                "想一想结论看似合理时是否仍可能遗漏前提。",
                "分别检查适用范围、处理过程和结果一致性。",
            ],
        },
        {
            "type": "fill",
            "concept_id": concept(4),
            "prompt": config["fill_1"]["prompt"],
            "accepted_texts": config["fill_1"]["accepted_texts"],
            "hints": [
                "回想课程目录中与这一定义对应的术语。",
                "关注题干描述的对象、作用和处理目标。",
                "将定义拆成输入、操作和结果三部分再定位概念。",
            ],
        },
        {
            "type": "short",
            "concept_id": concept(5),
            "prompt": config["short"]["prompt"],
            "reference_answer": config["short"]["reference"],
            "rubric": _rubric(config["short"]["keywords"]),
            "hints": [
                "先说明任务要解决的核心问题与边界。",
                "按先后关系拆出三到四个关键环节。",
                "最后补充如何判断方案是否达到预期。",
            ],
        },
        {
            "type": "scenario",
            "concept_id": concept(6),
            "prompt": config["scenario"]["prompt"],
            "reference_answer": config["scenario"]["reference"],
            "rubric": _rubric(config["scenario"]["keywords"]),
            "hints": [
                "先找出案例中发生变化的关键设置。",
                "再解释这一变化如何影响后续过程。",
                "给出的处理办法还应包含可观察的检查方式。",
            ],
        },
        {
            "type": "single",
            "concept_id": concept(7),
            "prompt": config["single_2"]["prompt"],
            "options": config["single_2"]["options"],
            "hints": [
                "先明确题目要求判断的是可靠性而非表面复杂度。",
                "关注证据是否来自独立且可重复的检查过程。",
                "优先选择同时控制条件并核对结果的方案。",
            ],
        },
        {
            "type": "fill",
            "concept_id": concept(8),
            "prompt": config["fill_2"]["prompt"],
            "accepted_texts": config["fill_2"]["accepted_texts"],
            "hints": [
                "从课程中描述这类机制或过程的术语入手。",
                "辨认它连接的对象以及完成的主要作用。",
                "结合所在章节标题缩小到一个规范概念。",
            ],
        },
    ]


CONCEPT_LABELS = {
    "machine-learning": ["矩阵运算", "矩阵求导", "线性回归"],
    "ai-intro": ["智能体基础", "知识表示", "知识图谱"],
    "data-intelligence": ["数据理解", "数据清洗", "缺失值处理"],
}


def _concept_label(course_id: str, index: int) -> str:
    return CONCEPT_LABELS[course_id][index - 1]


def _rubric(keywords: list[list[str]]) -> list[dict[str, Any]]:
    labels = ["界定问题与关键原因", "给出有序处理过程", "说明检查或验证依据"]
    weights = [0.3, 0.4, 0.3]
    return [
        {"criterion": labels[index], "keywords": values, "weight": weights[index]}
        for index, values in enumerate(keywords)
    ]


def _answer_texts(item: dict[str, Any]) -> tuple[list[str], list[str]]:
    if item["type"] in {"single", "multiple", "judgment"}:
        return ([content for content, correct in item["options"] if correct], [])
    if item["type"] == "fill":
        return (list(item["accepted_texts"]), [])
    return (
        [item["reference_answer"]],
        [rubric_item["criterion"] for rubric_item in item["rubric"]],
    )


def _seed_question(
    session: Session,
    *,
    set_id: str,
    revision: QuestionSetRevision,
    position: int,
    item: dict[str, Any],
) -> Question:
    question_id = _stable_id(f"practice:{set_id}:question:{position}")
    answer_spec: dict[str, Any]
    if item["type"] in {"single", "multiple", "judgment"}:
        correct_ids = [
            _stable_id(f"practice:{set_id}:question:{position}:option:{option_position}")
            for option_position, (_, is_correct) in enumerate(item["options"], start=1)
            if is_correct
        ]
        answer_spec = {"kind": "option_set", "selected_option_ids": correct_ids}
    elif item["type"] == "fill":
        answer_spec = {
            "kind": "normalized_text",
            "accepted_texts": list(item["accepted_texts"]),
            "numeric_answer": None,
            "absolute_tolerance": 0.0,
            "relative_tolerance": 0.0,
        }
    else:
        answer_spec = {"kind": "rubric", "reference_answer": item["reference_answer"]}

    question = Question(
        id=question_id,
        revision_id=revision.id,
        position=position,
        question_type=item["type"],
        prompt=item["prompt"],
        answer_spec_json=answer_spec,
        rubric_json=item.get("rubric", []),
        explanation=_explanation(item),
        cognitive_level=_cognitive_level(item["type"]),
        difficulty_prior=min(0.8, 0.28 + position * 0.06),
        difficulty_calibrated=None,
        source_evidence_ids=[],
        created_at=SEED_TIME,
    )
    session.add(question)
    session.flush()

    if item["type"] in {"single", "multiple", "judgment"}:
        for option_position, (content, is_correct) in enumerate(item["options"], start=1):
            session.add(QuestionOption(
                id=_stable_id(f"practice:{set_id}:question:{position}:option:{option_position}"),
                question_id=question.id,
                position=option_position,
                content=content,
                is_correct=is_correct,
                misconception_code=None if is_correct else f"seed-distractor-{option_position}",
            ))
    session.add(QuestionConcept(
        id=_stable_id(f"practice:{set_id}:question:{position}:concept"),
        question_id=question.id,
        concept_id=item["concept_id"],
        weight=1.0,
        evidence_ids=[],
    ))
    answer_texts, rubric_claims = _answer_texts(item)
    hint_check = validate_progressive_hints(
        list(item["hints"]),
        answer_texts=answer_texts,
        rubric_claims=rubric_claims,
    )
    if not hint_check.passed:
        codes = ", ".join(issue.code for issue in hint_check.issues)
        raise RuntimeError(f"种子题提示未通过防泄漏校验：{set_id} 第{position}题 {codes}")
    for level, content in enumerate(item["hints"], start=1):
        session.add(Hint(
            id=_stable_id(f"practice:{set_id}:question:{position}:hint:{level}"),
            question_id=question.id,
            level=level,
            content=content,
            leakage_score=hint_check.leakage_scores[level - 1],
            information_gain=hint_check.information_gains[level - 1],
            validation_status="passed",
            validator_version=HINT_VALIDATOR_VERSION,
        ))
    return question


def _explanation(item: dict[str, Any]) -> str:
    if item["type"] in {"single", "multiple", "judgment"}:
        correct = "、".join(content for content, is_correct in item["options"] if is_correct)
        return f"教师审核答案为：{correct}。判分采用选项集合精确匹配。"
    if item["type"] == "fill":
        return "教师已审核可接受表达；判分时执行Unicode规范化、大小写折叠与空白归一。"
    return "该题按发布前冻结的三项量规形成暂定结果，并保留教师复核入口。"


def _cognitive_level(question_type: str) -> str:
    return {
        "single": "understand",
        "multiple": "analyze",
        "judgment": "understand",
        "fill": "remember",
        "short": "apply",
        "scenario": "analyze",
    }[question_type]


def _seed_demo_attempts(
    session: Session,
    *,
    course_id: str,
    set_id: str,
    revision_id: str,
    student_id: str,
    questions: list[Question],
) -> None:
    plans: list[tuple[int, float, str]]
    if course_id == "machine-learning":
        plans = [(1, 1.0, "graded"), (2, 1.0, "graded"), (3, 0.0, "graded")]
    elif course_id == "ai-intro":
        plans = [(1, 1.0, "graded"), (5, 0.68, "reviewed")]
    else:
        plans = [(1, 1.0, "graded"), (5, 0.24, "reviewed")]

    for sequence, (position, value, review_status) in enumerate(plans, start=1):
        question = questions[position - 1]
        attempt_id = _stable_id(f"practice:{set_id}:demo-attempt:{sequence}")
        if session.get(Attempt, attempt_id) is not None:
            continue
        if question.question_type in {"single", "multiple", "judgment"}:
            selected = list(question.answer_spec_json["selected_option_ids"])
            if value == 0.0:
                selected = [
                    _stable_id(f"practice:{set_id}:question:{position}:option:1")
                ]
            answer = {"selected_option_ids": selected}
        else:
            answer = {"text": "先明确条件，再按步骤处理，并通过独立检查确认结果。"}
        attempt = Attempt(
            id=attempt_id,
            student_id=student_id,
            course_id=course_id,
            question_set_id=set_id,
            revision_id=revision_id,
            question_id=question.id,
            attempt_no=1,
            idempotency_key=f"curated-seed:{set_id}:{sequence}",
            answer_json=answer,
            hint_level=0,
            status="graded" if review_status == "graded" else "reviewed",
            submitted_at=SEED_TIME,
        )
        session.add(attempt)
        session.flush()
        session.add(Score(
            id=_stable_id(f"practice:{set_id}:demo-score:{sequence}"),
            attempt_id=attempt.id,
            score=value,
            is_correct=(value == 1.0) if question.question_type in {"single", "multiple", "judgment"} else None,
            confidence=1.0 if review_status == "graded" else 0.95,
            grading_mode="curated_seed_rule" if review_status == "graded" else "teacher_reviewed_seed",
            review_status=review_status,
            feedback_json={
                "summary": "课程演示种子作答，供功能状态展示；不是科学实验数据。",
                "source_kind": "curated_seed",
            },
            grader_model_run_id=None,
            graded_at=SEED_TIME,
            reviewed_by=None,
            reviewed_at=SEED_TIME if review_status == "reviewed" else None,
        ))


def seed_practice_sets(session: Session, teacher_id: str, student_id: str) -> None:
    for course_id, config in COURSE_SEEDS.items():
        set_id = config["set_id"]
        if session.get(QuestionSet, set_id) is not None:
            continue
        revision_id = _stable_id(f"practice:{set_id}:revision:1")
        question_set = QuestionSet(
            id=set_id,
            course_id=course_id,
            created_by=teacher_id,
            owner_student_id=None,
            title=config["title"],
            status="published",
            visibility="course",
            working_revision_id=revision_id,
            published_revision_id=revision_id,
            created_at=SEED_TIME,
            updated_at=SEED_TIME,
        )
        revision = QuestionSetRevision(
            id=revision_id,
            question_set_id=set_id,
            parent_revision_id=None,
            blueprint_id=None,
            revision_no=1,
            status="published",
            quality_status="pending",
            source_kind="curated_seed",
            source_summary="课程演示用教师审核种子题；非模型固定响应，不作为科学实验数据。",
            created_by=teacher_id,
            version=1,
            created_at=SEED_TIME,
            published_at=SEED_TIME,
        )
        session.add_all([question_set, revision])
        session.flush()
        questions = [
            _seed_question(
                session,
                set_id=set_id,
                revision=revision,
                position=position,
                item=item,
            )
            for position, item in enumerate(_base_questions(course_id, config), start=1)
        ]
        session.flush()
        gate = validate_revision(session, revision)
        if not gate.hard_pass:
            codes = ", ".join(str(issue.get("code")) for issue in gate.issues)
            raise RuntimeError(f"种子题组未通过TraceQ质量门：{set_id} {codes}")
        revision.quality_status = "passed"
        _seed_demo_attempts(
            session,
            course_id=course_id,
            set_id=set_id,
            revision_id=revision.id,
            student_id=student_id,
            questions=questions,
        )
        session.flush()
