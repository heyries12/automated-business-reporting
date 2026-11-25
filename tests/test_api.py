from fastapi.testclient import TestClient

from app.clients import BusinessApiClient
from app.main import app, get_settings


def configure_test_environment(monkeypatch):
    monkeypatch.setenv("SERVICE_API_KEY", "test-service-key")
    monkeypatch.setenv("BUSINESS_API_BASE_URL", "https://business.example.test/v1")
    monkeypatch.setenv("AI_ENABLED", "false")
    monkeypatch.setenv("REPORT_SUCCESS_STATUSES", "paid")
    get_settings.cache_clear()


def test_generate_report_requires_api_key(monkeypatch):
    configure_test_environment(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/v1/reports/generate",
            json={
                "report_name": "Daily Report",
                "period_start": "2026-11-24T00:00:00Z",
                "period_end": "2026-11-25T00:00:00Z",
            },
        )
    assert response.status_code == 401
    get_settings.cache_clear()


def test_generate_report_returns_email_and_sheet_row(monkeypatch):
    configure_test_environment(monkeypatch)

    async def fake_fetch(self, period_start, period_end):
        if period_start.day == 24:
            return [
                {
                    "created_at": "2026-11-24T10:00:00Z",
                    "amount": "250.00",
                    "status": "paid",
                    "customer_id": "customer-1",
                    "category": "Services",
                }
            ]
        return [
            {
                "created_at": "2026-11-23T10:00:00Z",
                "amount": "200.00",
                "status": "paid",
                "customer_id": "customer-1",
                "category": "Services",
            }
        ]

    monkeypatch.setattr(BusinessApiClient, "fetch_records", fake_fetch)

    with TestClient(app) as client:
        response = client.post(
            "/v1/reports/generate",
            headers={"X-API-Key": "test-service-key"},
            json={
                "report_name": "Daily Report",
                "period_start": "2026-11-24T00:00:00Z",
                "period_end": "2026-11-25T00:00:00Z",
            },
        )

    assert response.status_code == 200
    report = response.json()
    assert report["summary_mode"] == "deterministic"
    assert report["metrics"]["total_revenue"] == 250.0
    assert report["trends"]["revenue_change_pct"] == 25.0
    assert report["sheet_row"]["report_key"] == report["report_key"]
    assert report["sheet_row"]["delivery_status"] == "generated"
    assert "<html" in report["email_html"].lower()
    assert "24 Nov 2026 to 24 Nov 2026" in report["email_html"]
    get_settings.cache_clear()
