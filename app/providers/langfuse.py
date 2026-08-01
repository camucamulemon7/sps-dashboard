from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
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


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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

    @staticmethod
    def _base_query(start: datetime, end: datetime) -> dict[str, Any]:
        return {
            "view": "observations",
            "filters": [],
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
        hours = (end - start).total_seconds() / 3600
        granularity = "hour" if hours <= 48 else "day"
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
    def _users(records: list[dict[str, Any]]) -> tuple[list[UserMetric], int, int]:
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
        all_traces: set[str] = set()
        error_traces: set[str] = set()
        for item in records:
            user_id = str(item.get("userId") or "(unassigned)")
            trace_id = str(item.get("traceId") or item.get("id") or "")
            if trace_id:
                users[user_id]["traces"].add(trace_id)
                all_traces.add(trace_id)
            if str(item.get("level") or "").upper() == "ERROR" and trace_id:
                users[user_id]["error_traces"].add(trace_id)
                error_traces.add(trace_id)
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
        return result, len(all_traces), len(error_traces)

    async def fetch(self, range_name: str, start: datetime, end: datetime) -> DashboardData:
        if not self.config.langfuse_public_key or not self.config.langfuse_secret_key:
            raise RuntimeError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")

        async with self._client() as client:
            summary_rows, trend_rows, model_rows, observation_result = await asyncio.gather(
                self._metrics(client, self._summary_query(start, end)),
                self._metrics(client, self._trend_query(start, end)),
                self._metrics(client, self._models_query(start, end)),
                self._observations(client, start, end),
            )

        summary_row = summary_rows[0] if summary_rows else {}
        observations, partial = observation_result
        users, requests, error_requests = self._users(observations)
        summary = Summary(
            requests=requests,
            observations=int(_number(summary_row.get("count_count"))),
            total_cost=_number(summary_row.get("sum_totalCost")),
            input_tokens=int(_number(summary_row.get("sum_inputTokens"))),
            output_tokens=int(_number(summary_row.get("sum_outputTokens"))),
            total_tokens=int(_number(summary_row.get("sum_totalTokens"))),
            average_latency_ms=_number(summary_row.get("avg_latency")),
            p95_latency_ms=_number(summary_row.get("p95_latency")),
            error_rate=(error_requests / requests) if requests else 0,
        )
        trend = [
            TrendPoint(
                timestamp=str(row.get("time_dimension", "")),
                observations=int(_number(row.get("count_count"))),
                total_cost=_number(row.get("sum_totalCost")),
                total_tokens=int(_number(row.get("sum_totalTokens"))),
            )
            for row in trend_rows
        ]
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
                        f"User aggregation was capped at {self.config.langfuse_max_observations} observations"
                        if partial
                        else ""
                    ),
                    partial=partial,
                    details={"observations_scanned": len(observations)},
                )
            ],
        )
