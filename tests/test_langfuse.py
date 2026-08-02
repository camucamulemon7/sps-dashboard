from datetime import datetime, timezone

import httpx
import pytest

from app.config import Settings
from app.providers.langfuse import LangfuseProvider


def config() -> Settings:
    return Settings(
        dashboard_title="Test",
        refresh_seconds=60,
        default_range="7d",
        allowed_ranges=("7d",),
        frame_ancestors="'self'",
        request_timeout_seconds=20,
        langfuse_enabled=True,
        langfuse_host="http://langfuse.test",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",
        langfuse_max_observations=1000,
    )


@pytest.mark.asyncio
async def test_provider_normalizes_metrics_and_users():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/metrics"):
            query = request.url.params["query"]
            if "providedModelName" in query:
                return httpx.Response(200, json={"data": [{"providedModelName": "model-a", "count_count": 2, "sum_totalCost": 0.2, "sum_totalTokens": 30, "avg_latency": 1200}]})
            if "timeDimension" in query:
                return httpx.Response(200, json={"data": [{"time_dimension": "2026-08-01", "count_count": 2, "sum_totalCost": 0.2, "sum_totalTokens": 30}]})
            return httpx.Response(200, json={"data": [{"count_count": 4, "sum_totalCost": 0.2, "sum_inputTokens": 20, "sum_outputTokens": 10, "sum_totalTokens": 30, "avg_latency": 1200, "p95_latency": 1800}]})
        if request.url.path.endswith("/traces"):
            return httpx.Response(200, json={"data": [
                {"id": "t1", "userId": "a@example.com"},
                {"id": "t2", "userId": "b@example.com"},
            ], "meta": {"page": 1, "limit": 100, "totalItems": 2, "totalPages": 1}})
        return httpx.Response(200, json={"data": [
            {"id": "1", "traceId": "t1", "userId": "a@example.com", "type": "GENERATION", "level": "DEFAULT", "totalCost": 0.2, "inputUsage": 20, "outputUsage": 10, "totalUsage": 30},
            {"id": "2", "traceId": "t1", "userId": "a@example.com", "type": "SPAN", "level": "ERROR", "totalCost": 9, "inputUsage": 900, "outputUsage": 900, "totalUsage": 1800},
        ], "meta": {"cursor": None}})

    provider = LangfuseProvider(config(), transport=httpx.MockTransport(handler))
    data = await provider.fetch(
        "7d",
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    assert data.summary.requests == 2
    assert data.summary.total_tokens == 30
    assert data.summary.error_rate == 0.5
    assert data.models[0].name == "model-a"
    assert data.users[0].user_id == "a@example.com"
    assert data.users[0].requests == 1
    assert sum(user.requests for user in data.users) == 2
