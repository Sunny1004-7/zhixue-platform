from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable

from ..knowledge_graph.names import normalize_concept_name


ALIGNER_VERSION = "x1-lexical-graph-aligner-0.1.0"
ONTOLOGY_VERSION = "course-concepts-0.1.0"
DEFAULT_THRESHOLDS = {
    "auto_match": 0.82,
    "ambiguity_floor": 0.40,
    "minimum_margin": 0.08,
    "candidate_limit": 5,
}


@dataclass(frozen=True)
class AlignerConcept:
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    context_terms: tuple[str, ...] = ()
    neighbor_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class RankedCandidate:
    concept_id: str
    concept_name: str
    lexical_score: float
    context_score: float
    graph_score: float
    final_score: float


@dataclass(frozen=True)
class AlignmentDecision:
    status: str
    candidates: list[RankedCandidate]
    recommended_concept_id: str | None


@dataclass(frozen=True)
class ExtractedMention:
    raw_text: str
    chunk_id: str
    start_char: int
    end_char: int
    context: str
    locator: dict


def normalize_concept_text(text: str) -> str:
    return normalize_concept_name(text)


def split_manual_mentions(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;；]+", text) if part.strip()]


def _bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[index:index + 2] for index in range(len(text) - 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _lexical_score(mention: str, names: Iterable[str]) -> float:
    normalized_mention = normalize_concept_text(mention)
    if not normalized_mention:
        return 0.0
    best = 0.0
    for name in names:
        normalized_name = normalize_concept_text(name)
        if not normalized_name:
            continue
        if normalized_mention == normalized_name:
            return 1.0
        ratio = SequenceMatcher(None, normalized_mention, normalized_name).ratio()
        jaccard = _jaccard(_bigrams(normalized_mention), _bigrams(normalized_name))
        containment = min(len(normalized_mention), len(normalized_name)) / max(
            len(normalized_mention), len(normalized_name)
        ) if normalized_name in normalized_mention or normalized_mention in normalized_name else 0.0
        best = max(best, 0.50 * ratio + 0.35 * jaccard + 0.15 * containment)
    return min(1.0, best)


def _context_score(context: str, concept: AlignerConcept) -> float:
    normalized_context = normalize_concept_text(context)
    if normalize_concept_text(concept.name) in normalized_context:
        return 1.0
    terms = [normalize_concept_text(term) for term in concept.context_terms if normalize_concept_text(term)]
    if not terms:
        return 0.0
    matched = sum(1 for term in terms if term in normalized_context)
    return min(1.0, matched / min(4, len(terms)))


def _graph_score(context: str, concept: AlignerConcept) -> float:
    normalized_context = normalize_concept_text(context)
    neighbors = [normalize_concept_text(name) for name in concept.neighbor_names]
    neighbors = [name for name in neighbors if name]
    if not neighbors:
        return 0.0
    matched = sum(1 for name in neighbors if name in normalized_context)
    return min(1.0, matched / min(3, len(neighbors)))


def rank_concepts(
    mention: str,
    context: str,
    concepts: list[AlignerConcept],
    thresholds: dict[str, float] | None = None,
) -> AlignmentDecision:
    policy = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    scored: list[RankedCandidate] = []
    for concept in concepts:
        lexical = _lexical_score(mention, (concept.name, *concept.aliases))
        context_score = _context_score(context, concept)
        graph_score = _graph_score(context, concept)
        final_score = lexical * 0.72 + context_score * 0.18 + graph_score * 0.10
        if normalize_concept_text(mention) in {
            normalize_concept_text(concept.name),
            *(normalize_concept_text(alias) for alias in concept.aliases),
        }:
            final_score = 1.0
        scored.append(RankedCandidate(
            concept_id=concept.id,
            concept_name=concept.name,
            lexical_score=round(lexical, 6),
            context_score=round(context_score, 6),
            graph_score=round(graph_score, 6),
            final_score=round(min(1.0, final_score), 6),
        ))
    scored.sort(key=lambda item: (-item.final_score, item.concept_name, item.concept_id))
    limit = int(policy["candidate_limit"])
    candidates = scored[:limit]
    if not candidates:
        return AlignmentDecision("abstained", [], None)
    top = candidates[0]
    second_score = candidates[1].final_score if len(candidates) > 1 else 0.0
    margin = top.final_score - second_score
    if top.final_score >= policy["auto_match"] and (
        margin >= policy["minimum_margin"] or top.final_score >= 0.95
    ):
        return AlignmentDecision("matched", candidates, top.concept_id)
    if top.final_score >= policy["ambiguity_floor"]:
        return AlignmentDecision("ambiguous", candidates, None)
    return AlignmentDecision("abstained", candidates, None)


def extract_document_mentions(
    chunks: Iterable[tuple[str, str, dict]], concepts: list[AlignerConcept]
) -> list[ExtractedMention]:
    """按文档顺序召回当前课程词表中的首次显式出现，并保留原文证据。"""
    seen: set[str] = set()
    extracted: list[ExtractedMention] = []
    concepts_by_length = sorted(concepts, key=lambda item: (-len(item.name), item.name))
    for chunk_id, text, locator in chunks:
        matches: list[tuple[int, int, AlignerConcept, str]] = []
        for concept in concepts_by_length:
            for surface in (concept.name, *concept.aliases):
                if not surface:
                    continue
                match = re.search(re.escape(surface), text, flags=re.IGNORECASE)
                if match:
                    matches.append((match.start(), match.end(), concept, match.group(0)))
                    break
        for start, end, concept, raw_text in sorted(matches, key=lambda item: (item[0], -item[1])):
            normalized = normalize_concept_text(concept.name)
            if normalized in seen:
                continue
            seen.add(normalized)
            context_start = max(0, start - 100)
            context_end = min(len(text), end + 100)
            extracted.append(ExtractedMention(
                raw_text=raw_text,
                chunk_id=chunk_id,
                start_char=start,
                end_char=end,
                context=text[context_start:context_end],
                locator=locator,
            ))
    return extracted
