from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import Settings
from app.models import (
    DashboardData,
    ModelMetric,
    SourceStatus,
    Summary,
    TrendPoint,
    UserMetric,
)

GENERATION_LIKE_TYPES = (
    "GENERATION",
    "AGENT",
    "TOOL",
    "CHAIN",
    "RETRIEVER",
    "EVALUATOR",
    "EMBEDDING",
    "GUARDRAIL",
)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _trend_granularity(start: datetime, end: datetime) -> str:
    return "hour" if (end - start).total_seconds() <= 48 * 3600 else "day"


def _floor_timestamp(value: datetime, granularity: str) -> datetime:
    value = value.astimezone(timezone.utc)
    if granularity == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _complete_trend(
    rows: list[dict[str, Any]], start: datetime, end: datetime
) -> list[TrendPoint]:
    granularity = _trend_granularity(start, end)
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    indexed: dict[datetime, dict[str, Any]] = {}
    for row in rows:
        timestamp = _parse_timestamp(row.get("time_dimension"))
        if timestamp is not None:
            indexed[_floor_timestamp(timestamp, granularity)] = row

    points: list[TrendPoint] = []
    current = _floor_timestamp(start, granularity)
    last = _floor_timestamp(end, granularity)
    while current <= last:
        row = indexed.get(current, {})
        points.append(
            TrendPoint(
                timestamp=_iso(current),
                observations=int(_number(row.get("count_count"))),
                total_cost=_number(row.get("sum_totalCost")),
                total_tokens=int(_number(row.get("sum_totalTokens"))),
            )
        )
        current += step
    return points


class LangfuseProvider:
    name = "langfuse"

    def __init__(self, config: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.config.langfuse_host,
            auth=(self.config.langfuse_public_key, self.config.langfuse_secret_key),
            timeout=self.config.request_timeout_seconds,
            transport=self.transport,
            headers={"Accept": "application/json", "User-Agent": "sps-dashboard/1.0"},
        )

    async def _metrics(self, client: httpx.AsyncClient, query: dict[str, Any]) -> list[dict[str, Any]]:
        response = await client.get(
            "/api/public/v2/metrics",
            params={"query": json.dumps(query, separators=(",", ":"))},
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", [])

    async def _observations(
        self, client: httpx.AsyncClient, start: datetime, end: datetime
    ) -> tuple[list[dict[str, Any]], bool]:
        records: list[dict[str, Any]] = []
        cursor: str | None = None
        partial = False
        while True:
            remaining = self.config.langfuse_max_observations - len(records)
            if remaining <= 0:
                partial = True
                break
            params: dict[str, Any] = {
                "fields": "basic,usage,model,metrics",
                "limit": min(1000, remaining),
                "fromStartTime": _iso(start),
                "toStartTime": _iso(end),
            }
            if cursor:
                params["cursor"] = cursor
            response = await client.get("/api/public/v2/observations", params=params)
            response.raise_for_status()
            payload = response.json()
            records.extend(payload.get("data", []))
            cursor = (payload.get("meta") or {}).get("cursor")
            if not cursor:
                break
        return records, partial

    async def _traces(
        self, client: httpx.AsyncClient, start: datetime, end: datetime
    ) -> tuple[list[dict[str, Any]], int, bool]:
        records: list[dict[str, Any]] = []
        page = 1
        total_items = 0
        partial = False
        while True:
            remaining = self.config.langfuse_max_observations - len(records)
            if remaining <= 0:
                partial = True
                break
            response = await client.get(
                "/api/public/traces",
                params={
                    "fields": "core,metrics",
                    "limit": min(100, remaining),
                    "page": page,
                    "fromTimestamp": _iso(start),
                    "toTimestamp": _iso(end),
                },
            )
            response.raise_for_status()
            payload = response.json()
            records.extend(payload.get("data", []))
            meta = payload.get("meta") or {}
            total_items = int(_number(meta.get("totalItems")))
            total_pages = int(_number(meta.get("totalPages")))
            if page >= total_pages:
                break
            page += 1
        return records, total_items, partial

    @staticmethod
    def _base_query(start: datetime, end: datetime) -> dict[str, Any]:
        return {
            "view": "observations",
            "filters": [
                {
                    "column": "type",
                    "operator": "any of",
                    "value": list(GENERATION_LIKE_TYPES),
                    "type": "stringOptions",
                }
            ],
            "fromTimestamp": _iso(start),
            "toTimestamp": _iso(end),
            "config": {"row_limit": 1000},
        }

    @classmethod
    def _summary_query(cls, start: datetime, end: datetime) -> dict[str, Any]:
        query = cls._base_query(start, end)
        query.update(
            {
                "dimensions": [],
                "metrics": [
                    {"measure": "count", "aggregation": "count"},
                    {"measure": "totalCost", "aggregation": "sum"},
                    {"measure": "inputTokens", "aggregation": "sum"},
                    {"measure": "outputTokens", "aggregation": "sum"},
                    {"measure": "totalTokens", "aggregation": "sum"},
                    {"measure": "latency", "aggregation": "avg"},
                    {"measure": "latency", "aggregation": "p95"},
                ],
            }
        )
        return query

    @classmethod
    def _trend_query(cls, start: datetime, end: datetime) -> dict[str, Any]:
        query = cls._base_query(start, end)
        granularity = _trend_granularity(start, end)
        query.update(
            {
                "dimensions": [],
                "metrics": [
                    {"measure": "count", "aggregation": "count"},
                    {"measure": "totalCost", "aggregation": "sum"},
                    {"measure": "totalTokens", "aggregation": "sum"},
                ],
                "timeDimension": {"granularity": granularity},
                "orderBy": [{"field": "time_dimension", "direction": "asc"}],
            }
        )
        return query

    @classmethod
    def _models_query(cls, start: datetime, end: datetime) -> dict[str, Any]:
        query = cls._base_query(start, end)
        query["config"] = {"row_limit": 100}
        query.update(
            {
                "dimensions": [{"field": "providedModelName"}],
                "metrics": [
                    {"measure": "count", "aggregation": "count"},
                    {"measure": "totalCost", "aggregation": "sum"},
                    {"measure": "totalTokens", "aggregation": "sum"},
                    {"measure": "latency", "aggregation": "avg"},
                ],
                "orderBy": [{"field": "count_count", "direction": "desc"}],
            }
        )
        return query

    @staticmethod
    def _users(
        records: list[dict[str, Any]], traces: list[dict[str, Any]]
    ) -> tuple[list[UserMetric], int]:
        users: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "traces": set(),
                "error_traces": set(),
                "total_cost": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }
        )
        trace_users: dict[str, str] = {}
        error_traces: set[str] = set()
        for trace in traces:
            trace_id = str(trace.get("id") or "")
            user_id = str(trace.get("userId") or "(unassigned)")
            if trace_id:
                trace_users[trace_id] = user_id
                users[user_id]["traces"].add(trace_id)
        for item in records:
            trace_id = str(item.get("traceId") or item.get("id") or "")
            user_id = trace_users.get(trace_id) or str(item.get("userId") or "(unassigned)")
            if trace_id:
                users[user_id]["traces"].add(trace_id)
            if str(item.get("level") or "").upper() == "ERROR" and trace_id:
                users[user_id]["error_traces"].add(trace_id)
                error_traces.add(trace_id)
            if str(item.get("type") or "").upper() in GENERATION_LIKE_TYPES:
                users[user_id]["total_cost"] += _number(item.get("totalCost"))
                users[user_id]["input_tokens"] += int(_number(item.get("inputUsage")))
                users[user_id]["output_tokens"] += int(_number(item.get("outputUsage")))
                users[user_id]["total_tokens"] += int(_number(item.get("totalUsage")))

        result = [
            UserMetric(
                user_id=user_id,
                requests=len(values["traces"]),
                total_cost=values["total_cost"],
                input_tokens=values["input_tokens"],
                output_tokens=values["output_tokens"],
                total_tokens=values["total_tokens"],
                errors=len(values["error_traces"]),
            )
            for user_id, values in users.items()
        ]
        result.sort(key=lambda row: (row.total_tokens, row.requests), reverse=True)
        return result, len(error_traces)

    async def fetch(self, range_name: str, start: datetime, end: datetime) -> DashboardData:
        if not self.config.langfuse_public_key or not self.config.langfuse_secret_key:
            raise RuntimeError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")

        async with self._client() as client:
            summary_rows, trend_rows, model_rows, observation_result, trace_result = await asyncio.gather(
                self._metrics(client, self._summary_query(start, end)),
                self._metrics(client, self._trend_query(start, end)),
                self._metrics(client, self._models_query(start, end)),
                self._observations(client, start, end),
                self._traces(client, start, end),
            )

        summary_row = summary_rows[0] if summary_rows else {}
        observations, observation_partial = observation_result
        traces, trace_count, trace_partial = trace_result
        users, error_requests = self._users(observations, traces)
        partial = observation_partial or trace_partial
        summary = Summary(
            requests=trace_count,
            observations=int(_number(summary_row.get("count_count"))),
            total_cost=_number(summary_row.get("sum_totalCost")),
            input_tokens=int(_number(summary_row.get("sum_inputTokens"))),
            output_tokens=int(_number(summary_row.get("sum_outputTokens"))),
            total_tokens=int(_number(summary_row.get("sum_totalTokens"))),
            average_latency_ms=_number(summary_row.get("avg_latency")),
            p95_latency_ms=_number(summary_row.get("p95_latency")),
            error_rate=(error_requests / trace_count) if trace_count else 0,
        )
        trend = _complete_trend(trend_rows, start, end)
        models = [
            ModelMetric(
                name=str(row.get("providedModelName") or "(unassigned)"),
                calls=int(_number(row.get("count_count"))),
                total_cost=_number(row.get("sum_totalCost")),
                total_tokens=int(_number(row.get("sum_totalTokens"))),
                average_latency_ms=_number(row.get("avg_latency")),
            )
            for row in model_rows
        ]
        return DashboardData(
            generated_at=_iso(datetime.now(timezone.utc)),
            range=range_name,
            from_timestamp=_iso(start),
            to_timestamp=_iso(end),
            summary=summary,
            trend=trend,
            models=models,
            users=users,
            sources=[
                SourceStatus(
                    name=self.name,
                    status="degraded" if partial else "healthy",
                    message=(
                        f"User aggregation was capped at {self.config.langfuse_max_observations} records"
                        if partial
                        else ""
                    ),
                    partial=partial,
                    details={
                        "observations_scanned": len(observations),
                        "traces_scanned": len(traces),
                        "trace_count": trace_count,
                    },
                )
            ],
        )
