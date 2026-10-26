from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ProviderRequest:
    endpoint: str
    api_key: str
    model_id: str
    system_prompt: str
    user_prompt: str
    connect_timeout_seconds: float
    timeout_seconds: float
    temperature: float = 0.1
    max_output_tokens: int = 3000


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class ProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        retryable: bool,
        retry_after_seconds: float | None = None,
    ):
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class ModelAdapter(Protocol):
    def invoke(self, request: ProviderRequest) -> ProviderResponse: ...
