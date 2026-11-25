from datetime import datetime, timezone

import httpx
import pytest

import app.clients as clients
from app.config import Settings


def make_settings(monkeypatch, **overrides):
    values = {
        "SERVICE_API_KEY": "test-key",
        "BUSINESS_API_BASE_URL": "https://business.example.test/v1",
        "AI_ENABLED": "false",
        **overrides,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    settings.validate()
    return settings


@pytest.mark.asyncio
async def test_pagination_limit_fails_instead_of_truncating(monkeypatch):
    settings = make_settings(
        monkeypatch,
        BUSINESS_API_PAGE_PARAM="page",
        BUSINESS_API_PAGE_SIZE="2",
        BUSINESS_API_MAX_PAGES="2",
    )

    async def full_page(client, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [
                    {"created_at": "2026-11-24T01:00:00Z", "amount": 1},
                    {"created_at": "2026-11-24T02:00:00Z", "amount": 2},
                ]
            },
        )

    monkeypatch.setattr(clients, "_request_with_retry", full_page)
    source = clients.BusinessApiClient(settings)

    with pytest.raises(ValueError, match="pagination limit reached"):
        await source.fetch_records(
            datetime(2026, 11, 24, tzinfo=timezone.utc),
            datetime(2026, 11, 25, tzinfo=timezone.utc),
        )
