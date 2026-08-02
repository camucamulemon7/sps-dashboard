from __future__ import annotations

from datetime import datetime, timedelta, timezone

import uvicorn

from app.main import app, providers
from app.models import (
    DashboardData,
    ModelMetric,
    SourceStatus,
    Summary,
    TrendPoint,
    UserMetric,
)


class MockProvider:
    async def fetch(self, range_name, start, end):
        values = [41000, 53000, 48000, 67000, 73000, 62000, 89000, 96000, 82000, 105000, 121000, 114000]
        trend = [
            TrendPoint(
                timestamp=(end - timedelta(hours=len(values) - index - 1)).isoformat(),
                observations=18 + index * 2,
                total_cost=round(value * 0.000006, 4),
                total_tokens=value,
                model_tokens={
                    "gpt-5": int(value * (0.32 + (index % 3) * 0.03)),
                    "gpt-5-mini": int(value * (0.30 - (index % 2) * 0.04)),
                    "claude-sonnet-4": int(value * 0.20),
                    "gemini-2.5-pro": value
                    - int(value * (0.32 + (index % 3) * 0.03))
                    - int(value * (0.30 - (index % 2) * 0.04))
                    - int(value * 0.20),
                },
            )
            for index, value in enumerate(values)
        ]
        return DashboardData(
            generated_at=datetime.now(timezone.utc).isoformat(),
            range=range_name,
            from_timestamp=start.strftime("%Y-%m-%d %H:%M UTC"),
            to_timestamp=end.strftime("%Y-%m-%d %H:%M UTC"),
            summary=Summary(
                requests=428,
                observations=963,
                total_cost=12.8472,
                input_tokens=684220,
                output_tokens=327840,
                total_tokens=1012060,
                average_latency_ms=842,
                p95_latency_ms=1860,
                error_rate=0.012,
            ),
            trend=trend,
            models=[
                ModelMetric(name="gpt-5", calls=184, total_cost=6.41, total_tokens=438200),
                ModelMetric(name="gpt-5-mini", calls=151, total_cost=2.32, total_tokens=302400),
                ModelMetric(name="claude-sonnet-4", calls=61, total_cost=3.38, total_tokens=193600),
                ModelMetric(name="gemini-2.5-pro", calls=32, total_cost=0.7372, total_tokens=77860),
            ],
            users=[
                UserMetric(user_id="sato@example.jp", requests=132, total_tokens=317400, total_cost=4.285),
                UserMetric(user_id="tanaka@example.jp", requests=108, total_tokens=258800, total_cost=3.142),
                UserMetric(user_id="suzuki@example.jp", requests=86, total_tokens=211560, total_cost=2.804),
                UserMetric(user_id="yamada@example.jp", requests=64, total_tokens=143200, total_cost=1.793),
                UserMetric(user_id="shared-support", requests=38, total_tokens=81000, total_cost=0.8232),
            ],
            sources=[SourceStatus(name="langfuse", status="healthy")],
        )


providers.clear()
providers["langfuse"] = MockProvider()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8090)
