from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Concept, GraphEdge, GraphNode, GraphQualityReport, GraphRevision, KnowledgeGraph, LearningResource


GRAPH_SEEDS = {
    "machine-learning": [
        ("ml-g1", "线性回归知识图谱", [
            "矩阵运算", "矩阵求导", "线性回归", "损失函数", "梯度下降", "模型评价",
            "房价预测", "特征工程", "模型假设", "学习率", "正则化",
        ]),
        ("ml-g2", "梯度下降优化专题图谱", [
            "目标函数", "偏导数", "梯度向量", "学习率", "批量梯度", "随机梯度",
            "小批量训练", "链式法则", "收敛判据", "鞍点识别", "自适应优化",
        ]),
    ],
    "ai-intro": [
        ("ai-g1", "知识表示与规则推理图谱", [
            "命题逻辑", "实体与关系", "知识表示", "知识图谱", "规则推理", "智能体决策",
            "校园问答", "状态空间", "启发式搜索", "任务规划", "可解释推理",
        ]),
        ("ai-g2", "智能体规划与决策专题图谱", [
            "问题状态", "行动模型", "状态空间", "启发函数", "搜索策略", "任务规划",
            "智能体决策", "目标条件", "规划约束", "路径规划", "计划评估",
        ]),
    ],
    "data-intelligence": [
        ("di-g1", "交通流特征工程知识图谱", [
            "时间序列", "数据质量", "特征工程", "时间窗口", "数据泄漏", "流量预测",
            "信号配时", "传感器数据", "特征缩放", "时序切分", "在线监测",
        ]),
        ("di-g2", "时序数据质量专题图谱", [
            "传感器采样", "时间戳对齐", "质量诊断", "缺失模式", "异常检测", "缺失填补",
            "流量预测", "设备元数据", "时序切分", "数据泄漏", "在线监测",
        ]),
    ],
}

EDGE_PATTERN = [
    (0, 2, "prerequisite"), (1, 2, "prerequisite"), (7, 2, "prerequisite"),
    (2, 3, "contains"), (3, 4, "prerequisite"), (3, 5, "contrast"),
    (4, 6, "application"), (5, 6, "application"), (7, 8, "contains"),
    (8, 3, "prerequisite"), (9, 4, "contains"), (3, 10, "contrast"),
    (10, 6, "application"), (8, 5, "prerequisite"),
]

NODE_POSITIONS = [
    (115, 245), (260, 105), (365, 250), (535, 120), (570, 330), (735, 210),
    (820, 380), (105, 410), (350, 410), (690, 70), (845, 85),
]


def _node_type(index: int) -> str:
    if index in {0, 1, 7}:
        return "foundation"
    if index in {6, 10}:
        return "application"
    return "core"


def seed_knowledge_graphs(session: Session, teacher_id: str) -> None:
    for course_id, graph_specs in GRAPH_SEEDS.items():
        for graph_id, title, labels in graph_specs:
            existing_graph = session.get(KnowledgeGraph, graph_id)
            if existing_graph is not None:
                revision = session.get(GraphRevision, existing_graph.published_revision_id) if existing_graph.published_revision_id else None
                if revision and revision.source_type == "curated_seed":
                    for index, label in enumerate(labels):
                        node = session.scalar(select(GraphNode).where(GraphNode.revision_id == revision.id, GraphNode.label == label))
                        if node:
                            node.position_x, node.position_y = NODE_POSITIONS[index]
                continue
            graph = KnowledgeGraph(
                id=graph_id, course_id=course_id, title=title, owner_id=teacher_id,
                status="published", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            )
            revision_id = str(uuid5(NAMESPACE_URL, f"zhixing:graph-revision:{graph_id}:1"))
            revision = GraphRevision(
                id=revision_id, graph_id=graph_id, revision_no=1, mode="curated_seed",
                status="published", review_status="teacher_validated", quality_score=100.0,
                source_type="curated_seed", source_summary="课程教学资源基线，经结构硬门与教师确认后发布。",
                created_by=teacher_id, published_at=datetime.now(timezone.utc),
            )
            session.add(graph)
            session.flush()
            session.add(revision)
            session.flush()
            graph.working_revision_id = revision_id
            graph.published_revision_id = revision_id
            session.flush()
            node_ids: list[str] = []
            for index, label in enumerate(labels):
                concept = session.scalar(select(Concept).where(Concept.course_id == course_id, Concept.name == label))
                if concept is None:
                    sort_order = (session.scalar(select(func.max(Concept.sort_order)).where(Concept.course_id == course_id)) or 0) + 1
                    concept = Concept(
                        id=f"{course_id}:concept:graph:{uuid5(NAMESPACE_URL, f'zhixing:{course_id}:{label}').hex[:12]}",
                        course_id=course_id, name=label, sort_order=sort_order,
                    )
                    session.add(concept)
                    session.flush()
                node_id = str(uuid5(NAMESPACE_URL, f"zhixing:graph-node:{graph_id}:{index}"))
                node_ids.append(node_id)
                session.add(GraphNode(
                    id=node_id, revision_id=revision_id, concept_id=concept.id, label=label,
                    node_type=_node_type(index),
                    definition=f"{label}是“{title}”中的关键知识点，用于建立相关概念、方法与应用之间的可解释联系。",
                    key_point=f"理解{label}的定义、适用条件以及它与相邻知识点之间的关系。",
                    misconception=f"避免只记忆{label}的结论而忽略其成立条件和使用边界。",
                    origin="curated_seed", confidence=1.0,
                    position_x=NODE_POSITIONS[index][0], position_y=NODE_POSITIONS[index][1],
                ))
            session.flush()
            for index, (source, target, relation) in enumerate(EDGE_PATTERN):
                session.add(GraphEdge(
                    id=str(uuid5(NAMESPACE_URL, f"zhixing:graph-edge:{graph_id}:{index}")),
                    revision_id=revision_id, from_node_id=node_ids[source], to_node_id=node_ids[target],
                    relation=relation, origin="curated_seed", confidence=1.0,
                ))
            session.add(GraphQualityReport(
                id=str(uuid5(NAMESPACE_URL, f"zhixing:graph-quality:{graph_id}:1")),
                revision_id=revision_id, hard_pass=True, quality_score=100.0,
                metrics_json={"node_count": 11, "edge_count": 14, "definition_coverage": 1.0, "hard_error_count": 0, "warning_count": 0},
                issues_json=[], validator_version="a2-structural-gates-0.1.0",
            ))
            secondary_resource_id = graph_id
            if session.get(LearningResource, secondary_resource_id) is None:
                session.add(LearningResource(
                    id=secondary_resource_id, course_id=course_id, resource_type="knowledge_graph",
                    title=title, detail="11个节点 · 14条关系", progress_completed=None,
                    progress_total=None, accuracy=None, sort_order=10 + len(graph_specs), published=True,
                ))
