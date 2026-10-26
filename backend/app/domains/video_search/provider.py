from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from xml.etree import ElementTree

import httpx

from .schemas import DiscoveredVideo, VideoMetadata, VideoSearchIntent
from .urls import (
    UnsafeVideoUrl,
    canonicalize_video_url,
    validate_https_url,
    validate_public_https_url,
    validated_redirect,
)


class VideoDiscoveryError(RuntimeError):
    def __init__(self, code: str, safe_message: str):
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.json_ld: list[dict] = []
        self._json_buffer: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key and values.get("content"):
                self.meta.setdefault(key, values["content"].strip())
        if tag.lower() == "script" and values.get("type", "").lower() == "application/ld+json":
            self._json_buffer = []

    def handle_data(self, data: str) -> None:
        if self._json_buffer is not None:
            self._json_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or self._json_buffer is None:
            return
        raw = "".join(self._json_buffer).strip()
        self._json_buffer = None
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        items = payload if isinstance(payload, list) else [payload]
        self.json_ld.extend(item for item in items if isinstance(item, dict))


def _plain_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    parser = _MetadataParser()
    parser.feed(value)
    return re.sub(r"\s+", " ", " ".join(parser.meta.values()) or re.sub(r"<[^>]+>", " ", value)).strip()


def _duration_seconds(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return None
    hours, minutes, seconds = (int(item or 0) for item in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def parse_bing_rss(xml_text: str, *, resolve_dns: bool = False) -> list[DiscoveredVideo]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as error:
        raise VideoDiscoveryError("VIDEO_SEARCH_RESPONSE_INVALID", "检索服务返回格式无效") from error
    results: list[DiscoveredVideo] = []
    seen: set[tuple[str, str]] = set()
    for item in root.findall(".//item"):
        link = (item.findtext("link") or "").strip()
        if not link:
            continue
        try:
            canonical = canonicalize_video_url(link, resolve_dns=resolve_dns)
        except UnsafeVideoUrl:
            continue
        identity = (canonical.provider, canonical.external_id)
        if identity in seen:
            continue
        seen.add(identity)
        results.append(DiscoveredVideo(
            provider=canonical.provider,
            external_id=canonical.external_id,
            canonical_url=canonical.url,
            title=(item.findtext("title") or "").strip(),
            description=(item.findtext("description") or "").strip(),
        ))
    return results


def parse_video_metadata(html: str, *, final_url: str, content_type: str | None) -> VideoMetadata:
    parser = _MetadataParser()
    parser.feed(html)
    video_object = next(
        (item for item in parser.json_ld if item.get("@type") in {"VideoObject", "Course"}),
        {},
    )
    creator_value = video_object.get("author") or video_object.get("creator")
    if isinstance(creator_value, dict):
        creator = creator_value.get("name")
    elif isinstance(creator_value, list) and creator_value and isinstance(creator_value[0], dict):
        creator = creator_value[0].get("name")
    elif isinstance(creator_value, str):
        creator = creator_value
    else:
        creator = parser.meta.get("author")
    title = str(
        video_object.get("name") or parser.meta.get("og:title") or parser.meta.get("twitter:title") or ""
    ).strip()
    if not title:
        raise VideoDiscoveryError("VIDEO_METADATA_INCOMPLETE", "视频页面未提供可核验标题")
    description = str(
        video_object.get("description") or parser.meta.get("og:description")
        or parser.meta.get("description") or ""
    ).strip()
    thumbnail = video_object.get("thumbnailUrl") or parser.meta.get("og:image")
    if isinstance(thumbnail, list):
        thumbnail = thumbnail[0] if thumbnail else None
    embed_url = video_object.get("embedUrl") or parser.meta.get("og:video:url")
    return VideoMetadata(
        title=title[:500],
        creator=str(creator).strip()[:240] if creator else None,
        description=description[:4000],
        thumbnail_url=str(thumbnail)[:2048] if thumbnail else None,
        duration_seconds=_duration_seconds(video_object.get("duration")),
        embed_url=str(embed_url)[:2048] if embed_url else None,
        final_url=final_url,
        content_type=content_type,
        link_verified=True,
        collected_at=datetime.now(timezone.utc),
    )


def resolve_public_page(
    client: httpx.Client,
    candidate: DiscoveredVideo,
    *,
    max_redirects: int = 4,
    allow_federated_host: bool = False,
) -> VideoMetadata:
    current = candidate.canonical_url
    for _ in range(max_redirects + 1):
        try:
            if allow_federated_host:
                validate_public_https_url(current)
            else:
                validate_https_url(current)
        except UnsafeVideoUrl as error:
            raise VideoDiscoveryError("VIDEO_LINK_BLOCKED", "视频页面未通过安全校验") from error
        try:
            response = client.get(current)
        except httpx.HTTPError as error:
            raise VideoDiscoveryError("VIDEO_LINK_UNAVAILABLE", "视频页面当前无法访问") from error
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise VideoDiscoveryError("VIDEO_REDIRECT_INVALID", "视频页面返回了无目标重定向")
            try:
                if allow_federated_host:
                    target = str(httpx.URL(current).join(location))
                    validate_public_https_url(target)
                    current = target
                else:
                    current = validated_redirect(current, location)
            except UnsafeVideoUrl as error:
                raise VideoDiscoveryError("VIDEO_REDIRECT_BLOCKED", "视频重定向未通过安全校验") from error
            continue
        if response.status_code >= 400:
            raise VideoDiscoveryError("VIDEO_LINK_UNAVAILABLE", "视频页面当前无法访问")
        content_type = response.headers.get("content-type")
        if content_type and "html" not in content_type.lower():
            raise VideoDiscoveryError("VIDEO_CONTENT_TYPE_INVALID", "视频地址未返回可核验页面")
        if len(response.content) > 2 * 1024 * 1024:
            raise VideoDiscoveryError("VIDEO_PAGE_TOO_LARGE", "视频页面超过核验大小上限")
        return parse_video_metadata(response.text, final_url=str(response.url), content_type=content_type)
    raise VideoDiscoveryError("VIDEO_REDIRECT_LIMIT", "视频页面重定向次数过多")


class InternetArchiveVideoProvider:
    """Search openly indexed moving-image records through archive.org's public API."""

    provider_id = "internet-archive"
    endpoint = "https://archive.org/advancedsearch.php"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(12.0, connect=5.0),
            headers={"User-Agent": "Zhixing-VideoVerifier/1.0"},
            follow_redirects=False,
        )

    @staticmethod
    def _quoted(value: str) -> str:
        cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", value).replace("\\", " ").replace('"', " ")
        return f'"{re.sub(r"\s+", " ", cleaned).strip()[:160]}"'

    def search(self, intent: VideoSearchIntent, *, max_candidates: int = 20) -> list[DiscoveredVideo]:
        if max_candidates < 1 or max_candidates > 100:
            raise ValueError("max_candidates must be between 1 and 100")
        terms = [self._quoted(item.label) for item in intent.topics]
        query = f"({' OR '.join(terms)}) AND mediatype:(movies)"
        try:
            response = self.client.get(self.endpoint, params={
                "q": query,
                "fl[]": ["identifier", "title", "description"],
                "rows": str(max_candidates),
                "page": "1",
                "output": "json",
            })
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
            raise VideoDiscoveryError(
                "VIDEO_SEARCH_PROVIDER_UNAVAILABLE", "Internet Archive视频检索当前不可用",
            ) from error
        docs = payload.get("response", {}).get("docs", []) if isinstance(payload, dict) else []
        if not isinstance(docs, list):
            raise VideoDiscoveryError("VIDEO_SEARCH_RESPONSE_INVALID", "视频检索服务返回格式无效")
        results: list[DiscoveredVideo] = []
        for item in docs:
            if not isinstance(item, dict):
                continue
            identifier = item.get("identifier")
            title = item.get("title")
            if not isinstance(identifier, str) or not isinstance(title, str):
                continue
            try:
                canonical = canonicalize_video_url(
                    f"https://archive.org/details/{identifier}", resolve_dns=False,
                )
            except UnsafeVideoUrl:
                continue
            description = item.get("description", "")
            if isinstance(description, list):
                description = " ".join(str(value) for value in description[:3])
            elif not isinstance(description, str):
                description = ""
            results.append(DiscoveredVideo(
                provider=canonical.provider,
                external_id=canonical.external_id,
                canonical_url=canonical.url,
                title=title.strip()[:500],
                description=description.strip()[:4000],
            ))
        return results

    def resolve(self, candidate: DiscoveredVideo) -> VideoMetadata:
        metadata = resolve_public_page(self.client, candidate)
        return metadata.model_copy(update={
            "embed_url": f"https://archive.org/embed/{candidate.external_id}",
        })


class WikimediaVideoProvider:
    """Search openly licensed videos through the public MediaWiki API."""

    provider_id = "wikimedia-commons"
    endpoint = "https://commons.wikimedia.org/w/api.php"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(12.0, connect=5.0),
            headers={"User-Agent": "Zhixing-VideoVerifier/1.0"},
            follow_redirects=False,
        )

    @staticmethod
    def _metadata(value: dict, key: str) -> str:
        field = value.get(key, {})
        return str(field.get("value", "")) if isinstance(field, dict) else ""

    def _request(self, params: dict[str, str]) -> dict:
        try:
            response = self.client.get(self.endpoint, params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "prop": "info|imageinfo",
                "iiprop": "url|mime|mediatype|extmetadata",
                "iiurlwidth": "640",
                **params,
            })
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
            raise VideoDiscoveryError(
                "VIDEO_SEARCH_PROVIDER_UNAVAILABLE", "Wikimedia Commons视频检索当前不可用",
            ) from error
        if not isinstance(payload, dict):
            raise VideoDiscoveryError("VIDEO_SEARCH_RESPONSE_INVALID", "视频检索服务返回格式无效")
        return payload

    def _page(self, item: object) -> tuple[DiscoveredVideo, VideoMetadata] | None:
        if not isinstance(item, dict):
            return None
        page_id = item.get("pageid")
        title = item.get("title")
        image_info = item.get("imageinfo")
        if not isinstance(page_id, int) or not isinstance(title, str) or not isinstance(image_info, list) or not image_info:
            return None
        info = image_info[0]
        if not isinstance(info, dict) or info.get("mediatype") != "VIDEO":
            return None
        canonical_raw = info.get("descriptionurl")
        if not isinstance(canonical_raw, str):
            return None
        try:
            canonical = canonicalize_video_url(canonical_raw, resolve_dns=False)
        except UnsafeVideoUrl:
            return None
        extra = info.get("extmetadata", {})
        if not isinstance(extra, dict):
            extra = {}
        object_name = self._metadata(extra, "ObjectName") or title.removeprefix("File:")
        description = _plain_text(self._metadata(extra, "ImageDescription"))
        creator = _plain_text(self._metadata(extra, "Artist")) or None
        license_name = _plain_text(self._metadata(extra, "LicenseShortName")) or None
        license_url = self._metadata(extra, "LicenseUrl") or None
        media_url = info.get("url") if isinstance(info.get("url"), str) else None
        thumbnail = info.get("thumburl") if isinstance(info.get("thumburl"), str) else None
        discovered = DiscoveredVideo(
            provider=canonical.provider,
            external_id=str(page_id),
            canonical_url=canonical.url,
            title=object_name[:500],
            description=description[:4000],
        )
        metadata = VideoMetadata(
            title=object_name[:500],
            creator=creator[:240] if creator else None,
            description=description[:4000],
            thumbnail_url=thumbnail,
            duration_seconds=None,
            embed_url=media_url,
            final_url=canonical.url,
            content_type=info.get("mime") if isinstance(info.get("mime"), str) else None,
            license_name=license_name,
            license_url=license_url,
            link_verified=True,
            collected_at=datetime.now(timezone.utc),
        )
        return discovered, metadata

    def resolve(self, candidate: DiscoveredVideo) -> VideoMetadata:
        if not candidate.external_id.isdigit():
            raise VideoDiscoveryError(
                "VIDEO_EXTERNAL_ID_INVALID", "Wikimedia视频标识格式无效",
            )
        payload = self._request({"pageids": candidate.external_id})
        pages = payload.get("query", {}).get("pages", [])
        if not isinstance(pages, list):
            raise VideoDiscoveryError(
                "VIDEO_SEARCH_RESPONSE_INVALID", "视频检索服务返回格式无效",
            )
        resolved = [self._page(item) for item in pages]
        match = next((item for item in resolved if item is not None), None)
        if match is None:
            raise VideoDiscoveryError("VIDEO_LINK_UNAVAILABLE", "视频页面当前无法访问")
        return match[1]

    def search_resolved(
        self,
        intent: VideoSearchIntent,
        *,
        max_candidates: int = 20,
    ) -> list[tuple[DiscoveredVideo, VideoMetadata]]:
        if max_candidates < 1 or max_candidates > 50:
            raise ValueError("max_candidates must be between 1 and 50")
        labels = " ".join(item.label.strip() for item in intent.topics[:5])
        payload = self._request({
            "generator": "search",
            "gsrsearch": f"{labels} filetype:video",
            "gsrnamespace": "6",
            "gsrlimit": str(max_candidates),
        })
        pages = payload.get("query", {}).get("pages", [])
        if not isinstance(pages, list):
            return []
        results = [self._page(item) for item in pages]
        return [item for item in results if item is not None]


class PeerTubeVideoProvider:
    """Search federated public PeerTube instances through Sepia Search."""

    provider_id = "peertube"
    endpoint = "https://sepiasearch.org/api/v1/search/videos"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(12.0, connect=5.0),
            headers={"User-Agent": "Zhixing-VideoVerifier/1.0"},
            follow_redirects=False,
        )

    @staticmethod
    def _safe_media_url(url: object, *, expected_path: str) -> str | None:
        if not isinstance(url, str):
            return None
        try:
            parsed = validate_public_https_url(url)
        except UnsafeVideoUrl:
            return None
        if expected_path not in parsed.path:
            return None
        return url

    def search_resolved(
        self,
        intent: VideoSearchIntent,
        *,
        max_candidates: int = 20,
    ) -> list[tuple[DiscoveredVideo, VideoMetadata]]:
        if max_candidates < 1 or max_candidates > 50:
            raise ValueError("max_candidates must be between 1 and 50")
        query = " ".join(item.label.strip() for item in intent.topics[:8])
        try:
            response = self.client.get(self.endpoint, params={
                "search": query,
                "count": str(max_candidates),
                "start": "0",
                "nsfw": "false",
            })
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
            raise VideoDiscoveryError(
                "VIDEO_SEARCH_PROVIDER_UNAVAILABLE", "PeerTube视频检索当前不可用",
            ) from error
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            raise VideoDiscoveryError("VIDEO_SEARCH_RESPONSE_INVALID", "视频检索服务返回格式无效")
        results: list[tuple[DiscoveredVideo, VideoMetadata]] = []
        for item in rows:
            if not isinstance(item, dict) or item.get("privacy", {}).get("id") != 1:
                continue
            if item.get("nsfw") is True:
                continue
            uuid = item.get("uuid")
            title = item.get("name")
            if not isinstance(uuid, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", uuid):
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            canonical = self._safe_media_url(item.get("url"), expected_path="/videos/watch/")
            if canonical is None:
                continue
            embed = self._safe_media_url(item.get("embedUrl"), expected_path="/videos/embed/")
            thumbnail = self._safe_media_url(item.get("thumbnailUrl"), expected_path="/lazy-static/")
            description = item.get("description")
            if not isinstance(description, str):
                description = item.get("truncatedDescription") if isinstance(item.get("truncatedDescription"), str) else ""
            account = item.get("account", {})
            creator = account.get("displayName") if isinstance(account, dict) else None
            licence = item.get("licence", {})
            license_name = licence.get("label") if isinstance(licence, dict) else None
            duration = item.get("duration")
            duration = duration if isinstance(duration, int) and duration >= 0 else None
            discovered = DiscoveredVideo(
                provider="peertube",
                external_id=uuid,
                canonical_url=canonical,
                title=title.strip()[:500],
                description=description.strip()[:4000],
            )
            metadata = VideoMetadata(
                title=title.strip()[:500],
                creator=str(creator).strip()[:240] if creator else None,
                description=description.strip()[:4000],
                thumbnail_url=thumbnail,
                duration_seconds=duration,
                embed_url=embed,
                final_url=canonical,
                content_type=None,
                license_name=str(license_name)[:120] if license_name else None,
                license_url=None,
                link_verified=False,
                source_verified=True,
                metadata_verified=True,
                collected_at=datetime.now(timezone.utc),
            )
            results.append((discovered, metadata))
        return results

    def resolve(self, candidate: DiscoveredVideo) -> VideoMetadata:
        return resolve_public_page(
            self.client, candidate, allow_federated_host=True,
        )
