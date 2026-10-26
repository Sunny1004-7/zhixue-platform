from __future__ import annotations

import json

import httpx

from ..contracts import ProviderError, ProviderRequest, ProviderResponse


def _normalize_json_object(content: str) -> str:
    """Unwrap one fenced JSON object while keeping ambiguous output rejectable."""
    stripped = content.strip()
    lines = stripped.splitlines()
    fence_lines = [index for index, line in enumerate(lines) if line.strip().startswith("```")]
    if len(fence_lines) != 2:
        return content
    opening, closing = fence_lines
    if (
        closing <= opening + 1
        or lines[opening].strip().casefold() not in {"```", "```json"}
        or lines[closing].strip() != "```"
    ):
        return content
    outside = "\n".join((*lines[:opening], *lines[closing + 1 :])).strip()
    if "```" in outside or "{" in outside or "}" in outside:
        return content
    candidate = "\n".join(lines[opening + 1 : closing]).strip()
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return content
    if isinstance(parsed, dict):
        return candidate
    return content


class OpenAICompatibleAdapter:
    """调用OpenAI兼容chat/completions端口，不保存或记录密钥与完整Prompt。"""

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        url = f"{request.endpoint.rstrip('/')}/chat/completions"
        timeout = httpx.Timeout(
            connect=request.connect_timeout_seconds,
            read=request.timeout_seconds,
            write=min(15.0, request.timeout_seconds),
            pool=min(10.0, request.timeout_seconds),
        )
        body = {
            "model": request.model_id,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        if request.provider_kind == "deepseek":
            if request.thinking_mode not in {"enabled", "disabled"}:
                raise ProviderError("MODEL_PROVIDER_CONFIGURATION_INVALID", "模型参数配置无效，请联系课程教师", retryable=False)
            body["thinking"] = {"type": request.thinking_mode}
            if request.thinking_mode == "enabled":
                body.pop("temperature")
        try:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {request.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("MODEL_PROVIDER_TIMEOUT", "模型服务响应超时", retryable=True) from exc
        except httpx.NetworkError as exc:
            raise ProviderError("MODEL_PROVIDER_NETWORK", "模型服务网络连接失败", retryable=True) from exc
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            try:
                retry_after_seconds = float(retry_after) if retry_after else None
            except ValueError:
                retry_after_seconds = None
            raise ProviderError(
                "MODEL_PROVIDER_RATE_LIMITED", "模型服务当前请求繁忙",
                retryable=True, retry_after_seconds=retry_after_seconds,
            )
        if response.status_code >= 500:
            raise ProviderError("MODEL_PROVIDER_5XX", "模型服务暂时不可用", retryable=True)
        if response.status_code >= 400:
            raise ProviderError("MODEL_PROVIDER_REJECTED", "模型服务拒绝了当前请求", retryable=False)
        try:
            payload = response.json()
            choice = payload["choices"][0]
            message = choice["message"]
            content = message.get("content")
            usage = payload.get("usage") or {}
            if not isinstance(message, dict) or not isinstance(usage, dict):
                raise TypeError("Invalid message or usage object")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderError(
                "MODEL_PROVIDER_PROTOCOL_INVALID", "模型服务返回格式无法识别", retryable=False
            ) from exc
        metadata = {
            "response_model": payload.get("model") if isinstance(payload.get("model"), str) else None,
            "response_id": payload.get("id") if isinstance(payload.get("id"), str) else None,
            "finish_reason": choice.get("finish_reason"),
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }
        if message.get("refusal") or choice.get("finish_reason") == "content_filter":
            raise ProviderError("MODEL_PROVIDER_REJECTED", "模型服务未接受当前教学请求，请调整内容后重试", retryable=False, metadata=metadata)
        if choice.get("finish_reason") == "length":
            raise ProviderError("MODEL_PROVIDER_TRUNCATED", "模型输出未完整返回，请缩小本次任务范围后重试", retryable=False, metadata=metadata)
        if not isinstance(content, str):
            raise ProviderError(
                "MODEL_PROVIDER_PROTOCOL_INVALID", "模型服务未返回文本结果", retryable=False, metadata=metadata
            )
        if not content.strip():
            raise ProviderError("MODEL_PROVIDER_EMPTY", "模型服务返回空内容，请稍后重试", retryable=True, metadata=metadata)
        if len(content.encode("utf-8")) > 256 * 1024:
            raise ProviderError(
                "MODEL_PROVIDER_RESPONSE_TOO_LARGE",
                "模型服务返回内容超过当前任务上限",
                retryable=False,
                metadata=metadata,
            )
        return ProviderResponse(
            content=_normalize_json_object(content),
            provider_request_id=(
                response.headers.get("x-request-id")
                or response.headers.get("x-oneapi-request-id")
            ),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            metadata={key: value for key, value in metadata.items() if isinstance(value, str)},
        )
