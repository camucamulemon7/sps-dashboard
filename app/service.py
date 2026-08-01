from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.models import DashboardData
from app.providers.base import DashboardProvider


RANGE_PATTERN = re.compile(r"^(\d+)([hd])$")


def range_delta(value: str) -> timedelta:
    match = RANGE_PATTERN.match(value)
    if not match:
        raise ValueError(f"Unsupported range: {value}")
    amount = int(match.group(1))
    return timedelta(hours=amount) if match.group(2) == "h" else timedelta(days=amount)


class DashboardService:
    def __init__(self, config: Settings, providers: dict[str, DashboardProvider]):
        self.config = config
        self.providers = providers

    async def fetch(self, range_name: str, source: str = "langfuse") -> DashboardData:
        if range_name not in self.config.allowed_ranges:
            raise ValueError(f"Range must be one of: {', '.join(self.config.allowed_ranges)}")
        provider = self.providers.get(source)
        if provider is None:
            raise ValueError(f"Unknown or disabled source: {source}")
        end = datetime.now(timezone.utc)
        start = end - range_delta(range_name)
        return await provider.fetch(range_name, start, end)
