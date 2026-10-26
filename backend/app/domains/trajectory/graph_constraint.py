from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from ...models import GraphEdge, GraphNode, GraphRevision, KnowledgeGraph, KnowledgeState
from .numerics import constrain_probability


class PublishedGraphConstraint:
    """Apply reviewed prerequisite edges from A2 to A1 mastery updates."""

    def __init__(self, db: Session, *, dependency_strength: float = 0.05):
        self.db = db
        self.dependency_strength = max(0.0, min(0.5, dependency_strength))

    def constrain(
        self,
        *,
        student_id: str,
        course_id: str,
        concept_id: str,
        probability: float,
    ) -> tuple[float, bool]:
        source_node = aliased(GraphNode)
        target_node = aliased(GraphNode)
        rows = self.db.execute(
            select(source_node.concept_id, GraphEdge.confidence)
            .select_from(GraphEdge)
            .join(source_node, source_node.id == GraphEdge.from_node_id)
            .join(target_node, target_node.id == GraphEdge.to_node_id)
            .join(GraphRevision, GraphRevision.id == GraphEdge.revision_id)
            .join(
                KnowledgeGraph,
                KnowledgeGraph.published_revision_id == GraphRevision.id,
            )
            .where(
                KnowledgeGraph.course_id == course_id,
                KnowledgeGraph.status == "published",
                GraphRevision.status == "published",
                GraphRevision.review_status == "teacher_validated",
                GraphEdge.relation == "prerequisite",
                target_node.concept_id == concept_id,
            )
        ).all()
        if not rows:
            return probability, False

        # A concept can appear in several published graphs. Keep the strongest
        # reviewed edge once so duplicated teaching views do not over-penalize it.
        prerequisite_weights: dict[str, float] = {}
        for prerequisite_id, confidence in rows:
            weight = max(0.0, min(1.0, float(confidence)))
            prerequisite_weights[prerequisite_id] = max(
                prerequisite_weights.get(prerequisite_id, 0.0), weight
            )

        states = self.db.scalars(
            select(KnowledgeState).where(
                KnowledgeState.student_id == student_id,
                KnowledgeState.course_id == course_id,
                KnowledgeState.concept_id.in_(prerequisite_weights),
                KnowledgeState.status != "unseen",
                KnowledgeState.effective_evidence >= 2.5,
            )
        ).all()
        if not states:
            return probability, False

        constrained = constrain_probability(probability, [
            (state.mastery / 100.0, prerequisite_weights[state.concept_id]) for state in states
        ], self.dependency_strength)
        return constrained, True

    def dependent_concepts(self, *, course_id: str, prerequisite_ids: set[str]) -> list[str]:
        if not prerequisite_ids:
            return []
        source_node = aliased(GraphNode)
        target_node = aliased(GraphNode)
        rows = self.db.execute(
            select(source_node.concept_id, target_node.concept_id)
            .select_from(GraphEdge)
            .join(source_node, source_node.id == GraphEdge.from_node_id)
            .join(target_node, target_node.id == GraphEdge.to_node_id)
            .join(GraphRevision, GraphRevision.id == GraphEdge.revision_id)
            .join(KnowledgeGraph, KnowledgeGraph.published_revision_id == GraphRevision.id)
            .where(
                KnowledgeGraph.course_id == course_id,
                KnowledgeGraph.status == "published",
                GraphRevision.status == "published",
                GraphRevision.review_status == "teacher_validated",
                GraphEdge.relation == "prerequisite",
            )
        ).all()
        adjacency: dict[str, set[str]] = {}
        for source_id, target_id in rows:
            if source_id != target_id:
                adjacency.setdefault(source_id, set()).add(target_id)

        queue = sorted(prerequisite_ids)
        visited = set(prerequisite_ids)
        ordered: list[str] = []
        while queue:
            source_id = queue.pop(0)
            for target_id in sorted(adjacency.get(source_id, set())):
                if target_id in visited:
                    continue
                visited.add(target_id)
                ordered.append(target_id)
                queue.append(target_id)
        return ordered
