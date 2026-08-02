from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Summary(BaseModel):
    requests: int = 0
    observations: int = 0
    total_cost: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    average_latency_ms: float = 0
    p95_latency_ms: float = 0
    error_rate: float = 0


class TrendPoint(BaseModel):
    timestamp: str
    observations: int = 0
    total_cost: float = 0
    total_tokens: int = 0
    model_tokens: dict[str, int] = Field(default_factory=dict)


class ModelMetric(BaseModel):
    name: str
    calls: int = 0
    total_cost: float = 0
    total_tokens: int = 0
    average_latency_ms: float = 0


class UserMetric(BaseModel):
    user_id: str
    requests: int = 0
    total_cost: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    errors: int = 0


class SourceStatus(BaseModel):
    name: str
    status: str
    message: str = ""
    partial: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class DashboardData(BaseModel):
    generated_at: str
    range: str
    from_timestamp: str
    to_timestamp: str
    summary: Summary
    trend: list[TrendPoint]
    models: list[ModelMetric]
    users: list[UserMetric]
    sources: list[SourceStatus]
