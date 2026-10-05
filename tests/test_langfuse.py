from datetime import datetime, timezone

import httpx
import pytest

from app.config import Settings
from app.providers.langfuse import LangfuseProvider, _complete_trend, _parse_timestamp


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


def test_complete_trend_fills_empty_hours():
    start = datetime(2026, 8, 1, 0, 30, tzinfo=timezone.utc)
    end = datetime(2026, 8, 1, 3, 15, tzinfo=timezone.utc)
    points = _complete_trend(
        [
            {"time_dimension": "2026-08-01T02:00:00Z", "providedModelName": "model-a", "count_count": 1, "sum_totalTokens": 20},
            {"time_dimension": "2026-08-01T02:00:00Z", "providedModelName": "model-b", "count_count": 1, "sum_totalTokens": 10},
        ],
        start,
        end,
    )
    assert len(points) == 4
    assert [point.total_tokens for point in points] == [0, 0, 30, 0]
    assert points[2].model_tokens == {"model-a": 20, "model-b": 10}


@pytest.mark.asyncio
async def test_provider_normalizes_metrics_and_users():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/metrics"):
            query = request.url.params["query"]
            if "timeDimension" in query:
                return httpx.Response(200, json={"data": [{"time_dimension": "2026-08-01", "providedModelName": "model-a", "count_count": 2, "sum_totalCost": 0.2, "sum_totalTokens": 30}]})
            if "providedModelName" in query:
                return httpx.Response(200, json={"data": [{"providedModelName": "model-a", "count_count": 2, "sum_totalCost": 0.2, "sum_totalTokens": 30, "avg_latency": 1200}]})
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
    assert data.trend[0].model_tokens == {"model-a": 30}
    assert data.users[0].user_id == "a@example.com"
    assert data.users[0].requests == 1
    assert sum(user.requests for user in data.users) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('cap,total', [(1050, 1200), (1050, 1050), (1000, 1000), (1050, 1030)])
async def test_trace_pagination_preserves_offsets_and_reports_truncation(cap, total):
    from dataclasses import replace
    from math import ceil

    limits = []

    def handler(request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params['limit'])
        page = int(request.url.params['page'])
        limits.append(limit)
        offset = (page - 1) * limit
        return httpx.Response(200, json={
            'data': [{'id': f't{index}'} for index in range(offset, min(offset + limit, total))],
            'meta': {'totalItems': total, 'totalPages': ceil(total / limit)},
        })

    provider = LangfuseProvider(replace(config(), langfuse_max_observations=cap),
                                transport=httpx.MockTransport(handler))
    async with provider._client() as client:
        records, count, partial = await provider._traces(
            client, datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    assert [row['id'] for row in records] == [f't{i}' for i in range(min(cap, total))]
    assert count == total
    assert partial is (total > cap)
    assert set(limits) == {100}


@pytest.mark.parametrize("value", ["2026-08-01", "2026-08-01T00:00:00", "2026-08-01T00:00:00Z"])
def test_metrics_timestamps_without_offset_are_utc(value):
    assert _parse_timestamp(value) == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert _parse_timestamp(value).tzinfo is timezone.utc


def test_metrics_timestamp_preserves_explicit_offset():
    assert _parse_timestamp("2026-08-01T09:00:00+09:00") == datetime(2026, 8, 1, tzinfo=timezone.utc)
