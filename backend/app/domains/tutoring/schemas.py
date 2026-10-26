from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


TutorStrategy = Literal[
    "adaptive",
    "socratic",
    "visual",
    "micro_practice",
    "web_evidence",
    "analogy",
]
ConcreteStrategy = Literal[
    "socratic",
    "visual",
    "micro_practice",
    "web_evidence",
    "analogy",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategyContext(StrictModel):
    question: str = Field(min_length=1, max_length=8000)
    selected_strategy: TutorStrategy = "adaptive"
    mastery: float | None = Field(default=None, ge=0.0, le=100.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    recent_success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    authorized_attempt_history: bool = False
    authorized_dialogue_history: bool = False


class StrategyStep(StrictModel):
    strategy: ConcreteStrategy
    reason_codes: list[str] = Field(min_length=1, max_length=8)


class StrategyDecision(StrictModel):
    mode: Literal["fixed", "adaptive"]
    candidate_scores: dict[ConcreteStrategy, float]
    plan_steps: list[StrategyStep] = Field(min_length=1, max_length=3)
    policy_version: str = "mosaic-router-1.0.0"

    @model_validator(mode="after")
    def distinct_steps(self) -> "StrategyDecision":
        values = [item.strategy for item in self.plan_steps]
        if len(values) != len(set(values)):
            raise ValueError("组合策略步骤不能重复")
        return self


class VisualNode(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    detail: str = Field(default="", max_length=500)


class VisualEdge(StrictModel):
    source: str
    target: str
    label: str = Field(default="", max_length=80)


class VisualSpec(StrictModel):
    kind: Literal["flow", "concept_map", "comparison", "timeline"]
    title: str = Field(min_length=1, max_length=160)
    alt_text: str = Field(min_length=8, max_length=1000)
    nodes: list[VisualNode] = Field(min_length=2, max_length=30)
    edges: list[VisualEdge] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def valid_references(self) -> "VisualSpec":
        ids = [item.id for item in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("图示节点ID不能重复")
        known = set(ids)
        if any(item.source not in known or item.target not in known for item in self.edges):
            raise ValueError("图示关系引用了不存在的节点")
        return self
