import asyncio
import json
from datetime import datetime
from typing import Any

import httpx

from app.config import Settings
from app.models import AiSummary, Metrics, Trends
from app.reporting import get_path


async def _request_with_retry(
    client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
) -> httpx.Response:
    retry_statuses = {429, 500, 502, 503, 504}
    for attempt in range(3):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError:
            if attempt == 2:
                raise
        else:
            if response.status_code not in retry_statuses or attempt == 2:
                response.raise_for_status()
                return response
            retry_after = response.headers.get("Retry-After", "")
            try:
                delay = min(float(retry_after), 10.0)
            except ValueError:
                delay = 0.5 * (2**attempt)
            await response.aclose()
            await asyncio.sleep(delay)
            continue
        await asyncio.sleep(0.5 * (2**attempt))

    raise RuntimeError("Upstream retry loop ended unexpectedly")


class BusinessApiClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def fetch_records(
        self, period_start: datetime, period_end: datetime
    ) -> list[dict[str, Any]]:
        settings = self.settings
        url = (
            f"{settings.business_api_base_url.rstrip('/')}"
            f"/{settings.business_api_path.lstrip('/')}"
        )
        headers = {"Accept": "application/json"}
        if settings.business_api_token:
            headers["Authorization"] = f"Bearer {settings.business_api_token}"
        if settings.business_api_key_header and settings.business_api_key_value:
            headers[settings.business_api_key_header] = settings.business_api_key_value

        base_params: dict[str, Any] = {
            settings.business_api_date_from_param: period_start.isoformat(),
            settings.business_api_date_to_param: period_end.isoformat(),
        }
        all_records: list[dict[str, Any]] = []
        pages = settings.business_api_max_pages if settings.business_api_page_param else 1

        async with httpx.AsyncClient(
            timeout=settings.business_api_timeout_seconds, follow_redirects=False
        ) as client:
            for page in range(1, pages + 1):
                params = dict(base_params)
                if settings.business_api_page_param:
                    params[settings.business_api_page_param] = page
                    params[settings.business_api_page_size_param] = (
                        settings.business_api_page_size
                    )
                response = await _request_with_retry(
                    client, "GET", url, headers=headers, params=params
                )
                payload = response.json()
                records = get_path(payload, settings.business_api_records_path)
                if not isinstance(records, list):
                    raise ValueError(
                        "Business API records path did not resolve to a JSON array"
                    )
                if not all(isinstance(record, dict) for record in records):
                    raise ValueError("Business API array must contain JSON objects")
                all_records.extend(records)
                if len(all_records) > settings.max_records:
                    raise ValueError(
                        f"Business API returned more than {settings.max_records} records"
                    )
                if not settings.business_api_page_param or len(
                    records
                ) < settings.business_api_page_size:
                    break
                if page == pages:
                    raise ValueError(
                        "Business API pagination limit reached before the final page; "
                        "increase BUSINESS_API_MAX_PAGES"
                    )

        return all_records


class AiClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def summarize(
        self,
        report_name: str,
        currency: str,
        current: Metrics,
        previous: Metrics,
        trends: Trends,
    ) -> AiSummary:
        schema = AiSummary.model_json_schema()
        body = {
            "model": self.settings.openai_model,
            "temperature": 0.1,
            "max_completion_tokens": 900,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "business_report_summary",
                    "strict": True,
                    "schema": schema,
                },
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You write concise executive business reports. Use only the supplied "
                        "aggregate metrics. Do not invent causes, forecasts, targets, or facts. "
                        "Call out non-comparable trends when a percentage is null. Give practical "
                        "recommendations as items to investigate, not unsupported conclusions. "
                        "Return only JSON matching the supplied schema."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "report_name": report_name,
                            "currency": currency,
                            "current_period": current.model_dump(),
                            "previous_period": previous.model_dump(),
                            "trends": trends.model_dump(),
                        },
                        separators=(",", ":"),
                    ),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await _request_with_retry(
                client,
                "POST",
                f"{self.settings.openai_base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            payload = response.json()

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("The AI response did not contain a completion choice")
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else None
        if not isinstance(message, dict):
            raise ValueError("The AI response did not contain a completion message")
        if message.get("refusal"):
            raise ValueError("The AI provider refused to generate the summary")
        if choice.get("finish_reason") not in (None, "stop"):
            raise ValueError(
                f"The AI response was incomplete ({choice.get('finish_reason')})"
            )
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("The AI response did not contain a summary")
        return AiSummary.model_validate_json(content)
