import asyncio
import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status

from app.clients import AiClient, BusinessApiClient
from app.config import Settings
from app.models import (
    GenerateRecordsReportRequest,
    GenerateReportRequest,
    ReportResponse,
    SheetRow,
)
from app.rendering import render_email
from app.reporting import (
    calculate_metrics,
    calculate_trends,
    deterministic_summary,
    get_path,
    parse_datetime,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
app = FastAPI(title="Automated Business Reporting API", version="1.0.0")


@lru_cache
def get_settings() -> Settings:
    settings = Settings.from_env()
    settings.validate()
    return settings


def require_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.service_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/reports/generate",
    response_model=ReportResponse,
    dependencies=[Depends(require_api_key)],
)
async def generate_report(
    request: GenerateReportRequest,
    settings: Settings = Depends(get_settings),
) -> ReportResponse:
    period_start_dt = request.period_start.astimezone(timezone.utc)
    period_end_dt = request.period_end.astimezone(timezone.utc)
    duration = period_end_dt - period_start_dt
    previous_start = period_start_dt - duration
    previous_end = period_start_dt
    source = BusinessApiClient(settings)

    try:
        async with asyncio.timeout(settings.report_generation_timeout_seconds):
            current_records, previous_records = await asyncio.gather(
                source.fetch_records(period_start_dt, period_end_dt),
                source.fetch_records(previous_start, previous_end),
            )
    except httpx.HTTPStatusError as error:
        logger.warning("Upstream API returned status %s", error.response.status_code)
        raise HTTPException(status_code=502, detail="An upstream API request failed") from error
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Report generation failed: %s", error)
        raise HTTPException(status_code=502, detail="Report source data is unavailable or invalid") from error
    except TimeoutError as error:
        logger.warning("Report generation exceeded its configured deadline")
        raise HTTPException(status_code=504, detail="Report generation timed out") from error

    return await build_report_response(
        request, settings, current_records, previous_records
    )


@app.post(
    "/v1/reports/generate-from-records",
    response_model=ReportResponse,
    dependencies=[Depends(require_api_key)],
)
async def generate_report_from_records(
    request: GenerateRecordsReportRequest,
    settings: Settings = Depends(get_settings),
) -> ReportResponse:
    if len(request.records) > settings.max_records:
        raise HTTPException(
            status_code=413,
            detail=f"The request exceeds the {settings.max_records} record limit",
        )

    period_start = request.period_start.astimezone(timezone.utc)
    period_end = request.period_end.astimezone(timezone.utc)
    duration = period_end - period_start
    previous_start = period_start - duration
    current_records = []
    previous_records = []

    for record in request.records:
        occurred_at = parse_datetime(get_path(record, settings.date_field))
        if occurred_at is None:
            current_records.append(record)
        elif period_start <= occurred_at < period_end:
            current_records.append(record)
        elif previous_start <= occurred_at < period_start:
            previous_records.append(record)

    return await build_report_response(
        request, settings, current_records, previous_records
    )


async def build_report_response(
    request: GenerateReportRequest,
    settings: Settings,
    current_records: list[dict],
    previous_records: list[dict],
) -> ReportResponse:
    period_start_dt = request.period_start.astimezone(timezone.utc)
    period_end_dt = request.period_end.astimezone(timezone.utc)
    duration = period_end_dt - period_start_dt
    previous_start = period_start_dt - duration
    previous_end = period_start_dt
    metric_options = {
        "date_field": settings.date_field,
        "amount_field": settings.amount_field,
        "status_field": settings.status_field,
        "customer_field": settings.customer_field,
        "category_field": settings.category_field,
        "success_statuses": settings.success_statuses,
    }
    try:
        metrics = calculate_metrics(
            current_records,
            period_start_dt,
            period_end_dt,
            **metric_options,
        )
        previous_metrics = calculate_metrics(
            previous_records, previous_start, previous_end, **metric_options
        )
        trends = calculate_trends(metrics, previous_metrics)
    except ValueError as error:
        logger.warning("Report records could not be aggregated: %s", error)
        raise HTTPException(status_code=422, detail="Report records are invalid") from error

    if settings.ai_enabled:
        try:
            async with asyncio.timeout(settings.report_generation_timeout_seconds):
                summary = await AiClient(settings).summarize(
                    request.report_name,
                    settings.currency,
                    metrics,
                    previous_metrics,
                    trends,
                )
            summary_mode = "ai"
        except (httpx.HTTPError, ValueError, TimeoutError) as error:
            logger.warning("AI summary failed; using deterministic fallback: %s", error)
            summary = deterministic_summary(metrics, trends, settings.currency)
            summary_mode = "deterministic_fallback"
    else:
        summary = deterministic_summary(metrics, trends, settings.currency)
        summary_mode = "deterministic"

    generated_at = datetime.now(timezone.utc).isoformat()
    period_start = period_start_dt.isoformat()
    period_end = period_end_dt.isoformat()
    key_source = f"{request.report_name}|{period_start}|{period_end}"
    report_key = hashlib.sha256(key_source.encode("utf-8")).hexdigest()[:24]
    display_end = period_end_dt - timedelta(microseconds=1)
    period_label = f"{period_start_dt:%d %b %Y} to {display_end:%d %b %Y}"
    email_subject = f"{request.report_name} | {period_start_dt:%Y-%m-%d}"
    email_html = render_email(
        report_name=request.report_name,
        period_label=period_label,
        currency=settings.currency,
        metrics=metrics,
        trends=trends,
        summary=summary,
    )
    sheet_row = SheetRow(
        report_key=report_key,
        generated_at=generated_at,
        report_name=request.report_name,
        period_start=period_start,
        period_end=period_end,
        currency=settings.currency,
        total_revenue=metrics.total_revenue,
        revenue_change_pct=trends.revenue_change_pct,
        total_transactions=metrics.total_transactions,
        transactions_change_pct=trends.transactions_change_pct,
        completed_transactions=metrics.completed_transactions,
        average_order_value=metrics.average_order_value,
        unique_customers=metrics.unique_customers,
        top_category=metrics.top_category,
        executive_summary=summary.executive_summary,
        highlights="\n".join(summary.highlights),
        risks="\n".join(summary.risks),
        recommendations="\n".join(summary.recommendations),
        summary_mode=summary_mode,
        delivery_status="generated",
        delivered_at="",
    )

    return ReportResponse(
        report_key=report_key,
        generated_at=generated_at,
        report_name=request.report_name,
        period_start=period_start,
        period_end=period_end,
        currency=settings.currency,
        metrics=metrics,
        previous_metrics=previous_metrics,
        trends=trends,
        summary=summary,
        summary_mode=summary_mode,
        email_subject=email_subject,
        email_html=email_html,
        sheet_row=sheet_row,
    )
