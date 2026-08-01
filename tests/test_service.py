import pytest

from app.config import Settings
from app.service import DashboardService, range_delta


def config() -> Settings:
    return Settings(
        dashboard_title="Test",
        refresh_seconds=60,
        default_range="7d",
        allowed_ranges=("24h", "7d"),
        frame_ancestors="'self'",
        request_timeout_seconds=20,
        langfuse_enabled=True,
        langfuse_host="http://example.test",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        langfuse_max_observations=1000,
    )


def test_range_delta():
    assert range_delta("24h").total_seconds() == 86400
    assert range_delta("7d").days == 7
    with pytest.raises(ValueError):
        range_delta("all")


@pytest.mark.asyncio
async def test_rejects_unknown_range():
    service = DashboardService(config(), {})
    with pytest.raises(ValueError, match="Range must be one of"):
        await service.fetch("30d")


@pytest.mark.asyncio
async def test_rejects_unknown_source():
    service = DashboardService(config(), {})
    with pytest.raises(ValueError, match="Unknown or disabled source"):
        await service.fetch("7d", "grafana")
