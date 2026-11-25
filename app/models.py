from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GenerateReportRequest(BaseModel):
    report_name: str = Field(default="Daily Business Report", min_length=1, max_length=120)
    period_start: datetime
    period_end: datetime

    @field_validator("period_start", "period_end")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("A timezone offset is required")
        return value

    @model_validator(mode="after")
    def validate_period(self) -> "GenerateReportRequest":
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be later than period_start")
        duration = self.period_end - self.period_start
        if duration > timedelta(days=366):
            raise ValueError("The reporting period cannot exceed 366 days")
        try:
            self.period_start - duration
        except OverflowError as error:
            raise ValueError("The previous comparison period is out of range") from error
        return self


class Metrics(BaseModel):
    source_records: int
    valid_records: int
    invalid_records: int
    total_revenue: float
    total_transactions: int
    completed_transactions: int
    average_order_value: float
    unique_customers: int
    top_category: str
    status_breakdown: dict[str, int]
    category_breakdown: dict[str, int]


class Trends(BaseModel):
    revenue_change_pct: float | None
    transactions_change_pct: float | None
    average_order_value_change_pct: float | None
    customers_change_pct: float | None


class AiSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str = Field(min_length=1, max_length=1600)
    highlights: list[str] = Field(max_length=5)
    risks: list[str] = Field(max_length=5)
    recommendations: list[str] = Field(max_length=5)

    @field_validator("highlights", "risks", "recommendations")
    @classmethod
    def clean_list(cls, values: list[str]) -> list[str]:
        return [str(value).strip()[:500] for value in values if str(value).strip()]


class SheetRow(BaseModel):
    report_key: str
    generated_at: str
    report_name: str
    period_start: str
    period_end: str
    currency: str
    total_revenue: float
    revenue_change_pct: float | None
    total_transactions: int
    transactions_change_pct: float | None
    completed_transactions: int
    average_order_value: float
    unique_customers: int
    top_category: str
    executive_summary: str
    highlights: str
    risks: str
    recommendations: str
    summary_mode: str
    delivery_status: str
    delivered_at: str


class ReportResponse(BaseModel):
    report_key: str
    generated_at: str
    report_name: str
    period_start: str
    period_end: str
    currency: str
    metrics: Metrics
    previous_metrics: Metrics
    trends: Trends
    summary: AiSummary
    summary_mode: str
    email_subject: str
    email_html: str
    sheet_row: SheetRow
