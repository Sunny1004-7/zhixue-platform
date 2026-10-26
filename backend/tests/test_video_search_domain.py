from __future__ import annotations

import pytest
import httpx

from app.domains.video_search.provider import (
    InternetArchiveVideoProvider,
    PeerTubeVideoProvider,
    WikimediaVideoProvider,
    parse_bing_rss,
    parse_video_metadata,
)
from app.domains.video_search.ranking import rank_candidates
from app.domains.video_search.schemas import TopicRef, VideoSearchIntent
from app.domains.video_search.urls import UnsafeVideoUrl, canonicalize_video_url


def test_canonical_urls_remove_tracking_and_keep_stable_ids():
    bilibili = canonicalize_video_url(
        "https://www.bilibili.com/video/BV1xrNGzrEJx/?spm_id_from=333.1",
        resolve_dns=False,
    )
    assert bilibili.provider == "bilibili"
    assert bilibili.external_id == "BV1xrNGzrEJx"
    assert bilibili.url == "https://www.bilibili.com/video/BV1xrNGzrEJx/"
    youtube = canonicalize_video_url(
        "https://youtu.be/dQw4w9WgXcQ?utm_source=test", resolve_dns=False,
    )
    assert youtube.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    archive = canonicalize_video_url(
        "https://archive.org/embed/ucberkeley_webcast_C3HgWsBjvSE", resolve_dns=False,
    )
    assert archive.provider == "internet-archive"
    assert archive.url == "https://archive.org/details/ucberkeley_webcast_C3HgWsBjvSE"


@pytest.mark.parametrize("url", [
    "http://www.bilibili.com/video/BV1xrNGzrEJx/",
    "https://127.0.0.1/video/BV1xrNGzrEJx/",
    "https://user:secret@www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://example.com/watch?v=dQw4w9WgXcQ",
])
def test_unsafe_video_urls_are_rejected(url: str):
    with pytest.raises(UnsafeVideoUrl):
        canonicalize_video_url(url, resolve_dns=False)


def test_rss_parser_filters_non_video_and_deduplicates():
    xml = """<?xml version="1.0"?><rss><channel>
      <item><title>线性回归</title><link>https://www.bilibili.com/video/BV1xrNGzrEJx/</link><description>课程</description></item>
      <item><title>重复</title><link>https://www.bilibili.com/video/BV1xrNGzrEJx/?from=search</link></item>
      <item><title>无关</title><link>https://example.com/video/1</link></item>
    </channel></rss>"""
    result = parse_bing_rss(xml)
    assert len(result) == 1
    assert result[0].external_id == "BV1xrNGzrEJx"


def test_metadata_and_e1_ranking_do_not_invent_clarity():
    html = """
    <html><head>
      <meta property="og:title" content="线性回归与损失函数教学">
      <meta property="og:description" content="从线性回归出发解释损失函数">
      <meta property="og:image" content="https://image.example/cover.jpg">
      <script type="application/ld+json">
      {"@type":"VideoObject","name":"线性回归与损失函数教学","author":{"name":"公开课教师"},"duration":"PT12M30S"}
      </script>
    </head></html>
    """
    metadata = parse_video_metadata(
        html,
        final_url="https://www.bilibili.com/video/BV1xrNGzrEJx/",
        content_type="text/html; charset=utf-8",
    )
    discovered = parse_bing_rss("""<rss><channel><item>
      <title>线性回归</title><link>https://www.bilibili.com/video/BV1xrNGzrEJx/</link>
    </item></channel></rss>""")[0]
    intent = VideoSearchIntent(
        course_id="machine-learning",
        source_mode="recorded",
        topics=[
            TopicRef(concept_id="ml-linear", label="线性回归"),
            TopicRef(concept_id="ml-loss", label="损失函数"),
        ],
    )
    result = rank_candidates(intent, [(discovered, metadata)])
    assert metadata.duration_seconds == 750
    assert result[0].matched_topic_ids == ["ml-linear", "ml-loss"]
    assert result[0].evidence_level == "E1"
    assert result[0].clarity_score is None
    assert "不计算讲解清晰度" in result[0].uncertainty_reason


def test_internet_archive_provider_parses_real_contract_shape_without_static_catalog():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "archive.org"
        assert "mediatype" in request.url.params["q"]
        return httpx.Response(200, json={
            "response": {
                "numFound": 1,
                "docs": [{
                    "identifier": "ucberkeley_webcast_C3HgWsBjvSE",
                    "title": "Least squares, Linear regression",
                    "description": "Mathematics lecture",
                }],
            },
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = InternetArchiveVideoProvider(client)
    intent = VideoSearchIntent(
        course_id="machine-learning",
        source_mode="manual",
        topics=[TopicRef(concept_id="ml-linear", label="linear regression")],
    )
    result = provider.search(intent, max_candidates=5)
    assert len(result) == 1
    assert result[0].canonical_url.endswith("ucberkeley_webcast_C3HgWsBjvSE")


def test_wikimedia_provider_keeps_license_and_official_media_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "commons.wikimedia.org"
        return httpx.Response(200, json={
            "query": {"pages": [{
                "pageid": 18011264,
                "title": "File:Linear Regression.ogv",
                "imageinfo": [{
                    "url": "https://upload.wikimedia.org/video.ogv",
                    "thumburl": "https://upload.wikimedia.org/thumb.jpg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Linear_Regression.ogv",
                    "mime": "application/ogg",
                    "mediatype": "VIDEO",
                    "extmetadata": {
                        "ObjectName": {"value": "Linear Regression Lecture"},
                        "ImageDescription": {"value": "<p>Least squares lesson</p>"},
                        "Artist": {"value": "Course Author"},
                        "LicenseShortName": {"value": "CC BY 3.0"},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/3.0"},
                    },
                }],
            }]},
        })

    provider = WikimediaVideoProvider(httpx.Client(transport=httpx.MockTransport(handler)))
    intent = VideoSearchIntent(
        course_id="machine-learning",
        source_mode="manual",
        topics=[TopicRef(concept_id="ml-linear", label="linear regression")],
    )
    result = provider.search_resolved(intent, max_candidates=5)
    assert len(result) == 1
    discovered, metadata = result[0]
    assert discovered.provider == "wikimedia-commons"
    assert metadata.license_name == "CC BY 3.0"
    assert metadata.embed_url.endswith("video.ogv")


def test_peertube_provider_keeps_federated_source_and_marks_link_unverified(monkeypatch):
    monkeypatch.setattr(
        "app.domains.video_search.urls.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "sepiasearch.org"
        return httpx.Response(200, json={
            "total": 1,
            "data": [{
                "uuid": "90769b3c-6077-4daa-a7c3-e4da3a2f8162",
                "privacy": {"id": 1, "label": "Public"},
                "nsfw": False,
                "name": "Linear regression lesson",
                "description": "An education video about linear regression",
                "duration": 60,
                "url": "https://video.example.org/videos/watch/90769b3c-6077-4daa-a7c3-e4da3a2f8162",
                "embedUrl": "https://video.example.org/videos/embed/short-id",
                "thumbnailUrl": "https://video.example.org/lazy-static/thumbnails/cover.jpg",
                "account": {"displayName": "Course Author"},
                "licence": {"label": "CC BY"},
            }],
        })

    provider = PeerTubeVideoProvider(httpx.Client(transport=httpx.MockTransport(handler)))
    intent = VideoSearchIntent(
        course_id="machine-learning",
        source_mode="manual",
        topics=[TopicRef(concept_id="ml-linear", label="linear regression")],
    )
    resolved = provider.search_resolved(intent, max_candidates=5)
    assert len(resolved) == 1
    ranked = rank_candidates(intent, resolved)
    assert ranked[0].provider == "peertube"
    assert ranked[0].duration_seconds == 60
    assert "metadata" in ranked[0].verified_scope
    assert "link" not in ranked[0].verified_scope
