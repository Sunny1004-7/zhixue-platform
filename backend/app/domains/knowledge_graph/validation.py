from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


ALLOWED_NODE_TYPES = {"foundation", "core", "application"}
ALLOWED_RELATIONS = {"prerequisite", "contains", "application", "contrast"}
AUDITED_ORIGINS = {"curated_seed", "teacher", "model_extraction_review"}


@dataclass(frozen=True)
class GraphIssue:
    code: str
    message: str
    target_id: str | None = None
    severity: str = "error"


@dataclass(frozen=True)
class GraphValidationResult:
    hard_pass: bool
    quality_score: float
    metrics: dict[str, float | int]
    issues: list[GraphIssue]


def _has_prerequisite_cycle(node_ids: set[str], edges: Iterable) -> bool:
    adjacency = {node_id: [] for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        if edge.relation != "prerequisite":
            continue
        adjacency[edge.from_node_id].append(edge.to_node_id)
        indegree[edge.to_node_id] += 1
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for target in adjacency[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return visited != len(node_ids)


def validate_graph(
    nodes: list,
    edges: list,
    *,
    evidenced_node_ids: set[str] | None = None,
    evidenced_edge_ids: set[str] | None = None,
) -> GraphValidationResult:
    issues: list[GraphIssue] = []
    evidenced_node_ids = evidenced_node_ids or set()
    evidenced_edge_ids = evidenced_edge_ids or set()
    node_ids = {node.id for node in nodes}
    labels = [node.label.strip().casefold() for node in nodes]
    if len(nodes) < 2:
        issues.append(GraphIssue("too_few_nodes", "图谱至少需要2个知识点"))
    if len(labels) != len(set(labels)):
        issues.append(GraphIssue("duplicate_label", "同一修订中知识点名称不可重复"))
    for node in nodes:
        if not node.label.strip():
            issues.append(GraphIssue("empty_label", "知识点名称不能为空", node.id))
        if node.node_type not in ALLOWED_NODE_TYPES:
            issues.append(GraphIssue("invalid_node_type", "知识点类型不在允许范围", node.id))
        if not node.definition.strip():
            issues.append(GraphIssue(
                "missing_definition", "知识点缺少定义", node.id,
                "warning" if node.origin == "curated_seed" else "error",
            ))
        if node.id not in evidenced_node_ids and node.origin not in AUDITED_ORIGINS:
            issues.append(GraphIssue(
                "missing_provenance", "知识点缺少材料证据或可查证的教师确认来源",
                node.id,
            ))
    seen_edges: set[tuple[str, str, str]] = set()
    for edge in edges:
        if edge.from_node_id not in node_ids or edge.to_node_id not in node_ids:
            issues.append(GraphIssue("dangling_edge", "关系端点不属于当前修订", edge.id))
        if edge.from_node_id == edge.to_node_id:
            issues.append(GraphIssue("self_loop", "关系不能连接知识点自身", edge.id))
        if edge.relation not in ALLOWED_RELATIONS:
            issues.append(GraphIssue("invalid_relation", "关系类型不在允许范围", edge.id))
        signature = (edge.from_node_id, edge.to_node_id, edge.relation)
        if signature in seen_edges:
            issues.append(GraphIssue("duplicate_edge", "存在重复语义关系", edge.id))
        seen_edges.add(signature)
        if edge.id not in evidenced_edge_ids and edge.origin not in AUDITED_ORIGINS:
            issues.append(GraphIssue(
                "missing_provenance", "关系缺少材料证据或可查证的教师确认来源",
                edge.id,
            ))
    if node_ids and all(edge.from_node_id in node_ids and edge.to_node_id in node_ids for edge in edges):
        if _has_prerequisite_cycle(node_ids, edges):
            issues.append(GraphIssue("prerequisite_cycle", "先修关系存在环路，禁止发布"))
    hard_errors = [issue for issue in issues if issue.severity == "error"]
    definition_coverage = sum(bool(node.definition.strip()) for node in nodes) / max(1, len(nodes))
    structural_score = max(0.0, 1.0 - 0.2 * len(hard_errors))
    provenance_total = len(nodes) + len(edges)
    provenance_covered = sum(
        node.id in evidenced_node_ids or node.origin in AUDITED_ORIGINS for node in nodes
    ) + sum(
        edge.id in evidenced_edge_ids or edge.origin in AUDITED_ORIGINS for edge in edges
    )
    provenance_coverage = provenance_covered / max(1, provenance_total)
    quality_score = round(
        100 * (0.55 * structural_score + 0.25 * definition_coverage + 0.20 * provenance_coverage),
        2,
    )
    return GraphValidationResult(
        hard_pass=not hard_errors,
        quality_score=quality_score,
        metrics={
            "node_count": len(nodes),
            "edge_count": len(edges),
            "definition_coverage": round(definition_coverage, 4),
            "provenance_coverage": round(provenance_coverage, 4),
            "hard_error_count": len(hard_errors),
            "warning_count": len(issues) - len(hard_errors),
        },
        issues=issues,
    )
