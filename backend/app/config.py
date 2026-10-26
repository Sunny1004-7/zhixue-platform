from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FACT_SOURCE = BACKEND_ROOT / "config" / "project_facts.yaml"


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    database_url: str = f"sqlite:///{(BACKEND_ROOT / '.data' / 'zhixing.db').as_posix()}"
    fact_source: Path = DEFAULT_FACT_SOURCE
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:4174",
    )
    session_ttl_hours: int = 8
    asset_root: Path = BACKEND_ROOT / ".data" / "assets"
    asset_max_bytes: int = 20 * 1024 * 1024
    model_connect_timeout_seconds: float = 5.0
    model_read_timeout_seconds: float = 45.0
    model_max_attempts: int = 2
    deepseek_thinking_mode: str = "disabled"

    @classmethod
    def from_env(cls) -> "Settings":
        thinking_mode = os.getenv("DEEPSEEK_THINKING_MODE", "disabled").strip().lower()
        if thinking_mode not in {"enabled", "disabled"}:
            raise ValueError("DEEPSEEK_THINKING_MODE must be enabled or disabled")
        origins = tuple(
            item.strip()
            for item in os.getenv(
                "ZHIXING_CORS_ORIGINS",
                "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4174",
            ).split(",")
            if item.strip()
        )
        return cls(
            environment=os.getenv("ZHIXING_ENVIRONMENT", "development"),
            database_url=os.getenv(
                "ZHIXING_DATABASE_URL",
                f"sqlite:///{(BACKEND_ROOT / '.data' / 'zhixing.db').as_posix()}",
            ),
            fact_source=Path(os.getenv("ZHIXING_FACT_SOURCE", str(DEFAULT_FACT_SOURCE))),
            cors_origins=origins,
            session_ttl_hours=int(os.getenv("ZHIXING_SESSION_TTL_HOURS", "8")),
            asset_root=Path(
                os.getenv("ZHIXING_ASSET_ROOT", str(BACKEND_ROOT / ".data" / "assets"))
            ),
            asset_max_bytes=int(os.getenv("ZHIXING_ASSET_MAX_BYTES", str(20 * 1024 * 1024))),
            model_connect_timeout_seconds=float(
                os.getenv("ZHIXING_MODEL_CONNECT_TIMEOUT_SECONDS", "5")
            ),
            model_read_timeout_seconds=float(
                os.getenv("ZHIXING_MODEL_READ_TIMEOUT_SECONDS", "45")
            ),
            model_max_attempts=max(1, min(3, int(os.getenv("ZHIXING_MODEL_MAX_ATTEMPTS", "2")))),
            deepseek_thinking_mode=thinking_mode,
        )
