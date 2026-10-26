from __future__ import annotations

import re
from datetime import datetime, timezone

from .schemas import DiscoveredVideo, VideoCandidate, VideoMetadata, VideoSearchIntent


def _tokens(value: str) -> set[str]:
    latin = re.findall(r"[a-z0-9]+", value.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]", value)
    return set(latin + chinese)


def rank_candidates(
    intent: VideoSearchIntent,
    resolved: list[tuple[DiscoveredVideo, VideoMetadata]],
    *,
    require_verified_source: bool = False,
    use_concept_evidence: bool = True,
    use_source_score: bool = True,
    diversify: bool = False,
    semantic_scores: dict[str, float] | None = None,
    use_semantic_score: bool = True,
) -> list[VideoCandidate]:
    topic_tokens = {item.concept_id: _tokens(item.label) for item in intent.topics}
    candidates: list[VideoCandidate] = []
    for discovered, metadata in resolved:
        if require_verified_source and not (metadata.link_verified and metadata.source_verified):
            continue
        haystack = _tokens(f"{metadata.title} {metadata.description}")
        matched = [
            concept_id for concept_id, tokens in topic_tokens.items()
            if tokens and len(tokens & haystack) / len(tokens) >= 0.5
        ]
        match_score = len(matched) / len(intent.topics)
        present = sum([
            bool(metadata.title), bool(metadata.creator), bool(metadata.description),
            metadata.duration_seconds is not None, bool(metadata.thumbnail_url),
        ])
        completeness = present / 5.0
        trust = {
            "wikimedia-commons": 0.9,
            "internet-archive": 0.85,
            "bilibili": 0.8,
            "youtube": 0.8,
        }.get(discovered.provider, 0.75)
        relevance = 0.6 * match_score if use_concept_evidence else 0.0
        if semantic_scores is not None:
            semantic = max(0.0, min(1.0, semantic_scores.get(discovered.external_id, 0.0)))
            relevance = (0.4 * semantic if use_semantic_score else 0.0) + (0.2 * match_score if use_concept_evidence else 0.0)
        final = round(relevance + 0.25 * completeness + (0.15 * trust if use_source_score else 0.0), 4)
        verified_scope = []
        if metadata.link_verified:
            verified_scope.append("link")
        if metadata.source_verified:
            verified_scope.append("source")
        if metadata.metadata_verified:
            verified_scope.append("metadata")
        candidates.append(VideoCandidate(
            provider=discovered.provider,
            external_id=discovered.external_id,
            canonical_url=discovered.canonical_url,
            title=metadata.title,
            creator=metadata.creator,
            description=metadata.description,
            thumbnail_url=metadata.thumbnail_url,
            duration_seconds=metadata.duration_seconds,
            embed_url=metadata.embed_url,
            license_name=metadata.license_name,
            license_url=metadata.license_url,
            matched_topic_ids=matched,
            match_score=round(match_score, 4),
            completeness_score=round(completeness, 4),
            trust_score=trust,
            clarity_score=None,
            final_score=final,
            evidence_level="E1",
            verified_scope=verified_scope,
            verified_at=datetime.now(timezone.utc),
            uncertainty_reason="缺少授权字幕、章节或教师复核，暂不计算讲解清晰度",
        ))
    ordered = sorted(candidates, key=lambda item: (-item.final_score, item.provider, item.external_id))
    if not diversify:
        return ordered
    selected = []
    def similarity(left, right):
        a = _tokens(f"{left.title} {left.description}")
        b = _tokens(f"{right.title} {right.description}")
        overlap = len(a & b) / max(1, len(a | b))
        return 0.6 * overlap + 0.4 * float(left.provider == right.provider)
    while ordered:
        item = max(ordered, key=lambda x: 0.8 * x.final_score - 0.2 * max((similarity(x,u) for u in selected), default=0.0))
        ordered.remove(item)
        selected.append(item)
    return selected
