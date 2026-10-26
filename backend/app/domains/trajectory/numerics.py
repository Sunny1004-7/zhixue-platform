"""Numerical trajectory operators shared by online updates and offline evaluation."""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class OnlineUpdateConfig:
    eta_max: float = 0.35
    kappa: float = 10.0

    def __post_init__(self):
        if not math.isfinite(self.eta_max) or not 0.0 <= self.eta_max <= 1.0:
            raise ValueError("eta_max must be finite and between 0 and 1")
        if not math.isfinite(self.kappa) or self.kappa <= 0.0:
            raise ValueError("kappa must be finite and positive")


def smooth_probability(previous: float, posterior: float, effective_evidence: float,
                       *, eta_max: float = 0.35, kappa: float = 10.0) -> float:
    """Apply equation (2.11) before temporal fusion and graph correction."""
    config = OnlineUpdateConfig(eta_max=eta_max, kappa=kappa)
    if not all(math.isfinite(value) for value in (previous, posterior, effective_evidence)):
        raise ValueError("online update inputs must be finite")
    if not 0.0 <= previous <= 1.0 or not 0.0 <= posterior <= 1.0:
        raise ValueError("mastery probabilities must be between 0 and 1")
    if effective_evidence < 0.0:
        raise ValueError("effective evidence must be non-negative")
    eta = min(config.eta_max, effective_evidence / (effective_evidence + config.kappa))
    return (1.0 - eta) * previous + eta * posterior

def temporal_statistics(history: list[dict], as_of: datetime, *, max_events=20,
                        half_life_days=30.0, max_gate=0.18):
    active = sorted([e for e in history if e["occurred_at"] <= as_of],
                    key=lambda e:e["occurred_at"], reverse=True)[:max_events]
    if len(active) < 2:
        return None
    weighted, total = 1.0, 2.0
    recent, recent_w, earlier, earlier_w = 0.0, 0.0, 0.0, 0.0
    for i,event in enumerate(active):
        age = max(0.0, (as_of-event["occurred_at"]).total_seconds()/86400.0)
        weight = event["reliability"] * event.get("weight",1.0) * math.exp(-math.log(2)*age/half_life_days) * 0.9**i
        success = max(0.0,min(1.0,event["success"]))
        weighted += weight*success
        total += weight
        if i < min(3,len(active)):
            recent += weight*success; recent_w += weight
        else:
            earlier += weight*success; earlier_w += weight
    probability = weighted/total
    if recent_w > 0 and earlier_w > 0:
        probability += 0.12*(recent/recent_w-earlier/earlier_w)
    probability = max(0.02,min(0.98,probability))
    gate = min(max_gate,0.04+0.05*math.log1p(max(0.0,total-2.0)))
    return probability,gate

def mix_probabilities(bayes: float, temporal: float, gate: float) -> float:
    eps=1e-6
    b=max(eps,min(1-eps,bayes)); t=max(eps,min(1-eps,temporal))
    g=max(0.0,min(0.45,gate))
    value=(1-g)*math.log(b/(1-b))+g*math.log(t/(1-t))
    return 1.0/(1.0+math.exp(-value))

def constrain_probability(probability: float, prerequisites: list[tuple[float,float]],
                          dependency_strength: float=0.05) -> float:
    support=1.0
    for mastery,confidence in prerequisites:
        support *= 1.0-max(0.0,min(1.0,confidence))*(1.0-max(0.0,min(1.0,mastery)))
    local=max(0.0,min(1.0,probability))
    strength=max(0.0,min(0.5,dependency_strength))
    return local*((1.0-strength)+strength*support)
