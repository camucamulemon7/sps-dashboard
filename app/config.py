from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        parsed = default
    return min(max(parsed, minimum), maximum)


@dataclass(frozen=True)
class Settings:
    dashboard_title: str
    refresh_seconds: int
    default_range: str
    allowed_ranges: tuple[str, ...]
    frame_ancestors: str
    request_timeout_seconds: int
    langfuse_enabled: bool
    langfuse_host: str
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_max_observations: int

    @classmethod
    def from_env(cls) -> "Settings":
        allowed = tuple(
            item.strip()
            for item in os.getenv("DASHBOARD_ALLOWED_RANGES", "24h,7d,30d").split(",")
            if item.strip()
        )
        default_range = os.getenv("DASHBOARD_DEFAULT_RANGE", "7d")
        if default_range not in allowed:
            default_range = allowed[0] if allowed else "7d"
        return cls(
            dashboard_title=os.getenv("DASHBOARD_TITLE", "LLM Usage Dashboard"),
            refresh_seconds=_as_int(os.getenv("DASHBOARD_REFRESH_SECONDS"), 60, 15, 3600),
            default_range=default_range,
            allowed_ranges=allowed or ("7d",),
            frame_ancestors=os.getenv("FRAME_ANCESTORS", "'self'"),
            request_timeout_seconds=_as_int(os.getenv("REQUEST_TIMEOUT_SECONDS"), 20, 3, 120),
            langfuse_enabled=_as_bool(os.getenv("LANGFUSE_ENABLED"), True),
            langfuse_host=os.getenv("LANGFUSE_HOST", "http://host.docker.internal:3000").rstrip("/"),
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            langfuse_max_observations=_as_int(
                os.getenv("LANGFUSE_MAX_OBSERVATIONS"), 10_000, 1_000, 100_000
            ),
        )


settings = Settings.from_env()
