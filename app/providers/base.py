from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.models import DashboardData


class DashboardProvider(Protocol):
    name: str

    async def fetch(self, range_name: str, start: datetime, end: datetime) -> DashboardData:
        """Fetch and normalize dashboard data for a time range."""
