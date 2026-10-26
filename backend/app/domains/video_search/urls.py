from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlparse, urlunparse


ALLOWED_VIDEO_HOSTS = {
    "bilibili.com",
    "www.bilibili.com",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "v.qq.com",
    "open.163.com",
    "www.icourse163.org",
    "archive.org",
    "www.archive.org",
    "commons.wikimedia.org",
}
TRACKING_PARAMETERS = {
    "from",
    "spm_id_from",
    "vd_source",
    "share_source",
    "share_medium",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}
_BVID = re.compile(r"\b(BV[0-9A-Za-z]{10})\b", re.IGNORECASE)
_YOUTUBE_ID = re.compile(r"^[0-9A-Za-z_-]{6,20}$")


class UnsafeVideoUrl(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalVideoUrl:
    provider: str
    external_id: str
    url: str


@lru_cache(maxsize=256)
def _public_address(host: str) -> bool:
    try:
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    if not records:
        return False
    for record in records:
        address = ipaddress.ip_address(record[4][0])
        if not address.is_global:
            return False
    return True


def validate_https_url(url: str, *, resolve_dns: bool = True) -> str:
    parsed = validate_public_https_url(url, resolve_dns=resolve_dns)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in ALLOWED_VIDEO_HOSTS:
        raise UnsafeVideoUrl("视频来源不在允许的平台范围内")
    return url


def validate_public_https_url(url: str, *, resolve_dns: bool = True):
    if len(url) > 2048:
        raise UnsafeVideoUrl("视频地址过长")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        raise UnsafeVideoUrl("视频地址必须使用HTTPS")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise UnsafeVideoUrl("视频地址不能包含凭证或非标准端口")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise UnsafeVideoUrl("视频地址不能指向内网")
    if resolve_dns and not _public_address(host):
        raise UnsafeVideoUrl("视频来源无法解析为公开网络地址")
    return parsed


def canonicalize_video_url(url: str, *, resolve_dns: bool = True) -> CanonicalVideoUrl:
    validate_https_url(url, resolve_dns=resolve_dns)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    query = dict(parse_qsl(parsed.query, keep_blank_values=False))
    if host in {"bilibili.com", "www.bilibili.com"}:
        match = _BVID.search(parsed.path)
        if not match:
            raise UnsafeVideoUrl("哔哩哔哩地址缺少稳定BV号")
        external_id = match.group(1)
        canonical = f"https://www.bilibili.com/video/{external_id}/"
        return CanonicalVideoUrl("bilibili", external_id, canonical)
    if host == "youtu.be":
        external_id = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "www.youtube.com"}:
        external_id = query.get("v", "")
        if not external_id and parsed.path.startswith("/shorts/"):
            external_id = parsed.path.split("/")[2]
    else:
        external_id = parsed.path.strip("/")
    if host in {"youtu.be", "youtube.com", "www.youtube.com"}:
        if not _YOUTUBE_ID.fullmatch(external_id):
            raise UnsafeVideoUrl("YouTube地址缺少稳定视频ID")
        return CanonicalVideoUrl(
            "youtube", external_id, f"https://www.youtube.com/watch?v={external_id}",
        )
    if host in {"archive.org", "www.archive.org"}:
        parts = [item for item in parsed.path.split("/") if item]
        if len(parts) < 2 or parts[0] not in {"details", "embed"}:
            raise UnsafeVideoUrl("Internet Archive地址缺少稳定资源ID")
        external_id = parts[1]
        if not re.fullmatch(r"[0-9A-Za-z._-]{1,160}", external_id):
            raise UnsafeVideoUrl("Internet Archive资源ID格式无效")
        return CanonicalVideoUrl(
            "internet-archive", external_id, f"https://archive.org/details/{external_id}",
        )
    if host == "commons.wikimedia.org":
        if not parsed.path.startswith("/wiki/File:"):
            raise UnsafeVideoUrl("Wikimedia Commons地址缺少文件页")
        external_id = unquote(parsed.path.removeprefix("/wiki/"))
        if len(external_id) > 240 or any(ord(value) < 32 for value in external_id):
            raise UnsafeVideoUrl("Wikimedia Commons文件标识无效")
        canonical_path = quote(external_id, safe=":()_,-.'")
        return CanonicalVideoUrl(
            "wikimedia-commons", external_id, f"https://commons.wikimedia.org/wiki/{canonical_path}",
        )
    filtered_query = [
        (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key.lower() not in TRACKING_PARAMETERS
    ]
    clean = urlunparse(("https", host, parsed.path or "/", "", urlencode(filtered_query), ""))
    provider = {
        "v.qq.com": "tencent-video",
        "open.163.com": "netease-open-course",
        "www.icourse163.org": "icourse163",
    }[host]
    if not external_id:
        raise UnsafeVideoUrl("视频地址缺少稳定资源路径")
    return CanonicalVideoUrl(provider, external_id[:160], clean)


def validated_redirect(current_url: str, location: str, *, resolve_dns: bool = True) -> str:
    target = urljoin(current_url, location)
    validate_https_url(target, resolve_dns=resolve_dns)
    return target
