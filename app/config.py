import os
from dataclasses import dataclass


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_tuple(value: str | None, default: str) -> tuple[str, ...]:
    return tuple(
        part.strip().lower()
        for part in (value or default).split(",")
        if part.strip()
    )


@dataclass(frozen=True)
class Settings:
    service_api_key: str
    business_api_base_url: str
    business_api_path: str
    business_api_token: str
    business_api_key_header: str
    business_api_key_value: str
    business_api_date_from_param: str
    business_api_date_to_param: str
    business_api_page_param: str
    business_api_page_size_param: str
    business_api_page_size: int
    business_api_max_pages: int
    business_api_records_path: str
    business_api_timeout_seconds: float
    report_generation_timeout_seconds: float
    date_field: str
    amount_field: str
    status_field: str
    customer_field: str
    category_field: str
    success_statuses: tuple[str, ...]
    currency: str
    max_records: int
    ai_enabled: bool
    openai_api_key: str
    openai_base_url: str
    openai_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            service_api_key=os.getenv("SERVICE_API_KEY", ""),
            business_api_base_url=os.getenv("BUSINESS_API_BASE_URL", ""),
            business_api_path=os.getenv("BUSINESS_API_PATH", "/orders"),
            business_api_token=os.getenv("BUSINESS_API_TOKEN", ""),
            business_api_key_header=os.getenv("BUSINESS_API_KEY_HEADER", ""),
            business_api_key_value=os.getenv("BUSINESS_API_KEY_VALUE", ""),
            business_api_date_from_param=os.getenv(
                "BUSINESS_API_DATE_FROM_PARAM", "start_date"
            ),
            business_api_date_to_param=os.getenv(
                "BUSINESS_API_DATE_TO_PARAM", "end_date"
            ),
            business_api_page_param=os.getenv("BUSINESS_API_PAGE_PARAM", ""),
            business_api_page_size_param=os.getenv(
                "BUSINESS_API_PAGE_SIZE_PARAM", "limit"
            ),
            business_api_page_size=int(os.getenv("BUSINESS_API_PAGE_SIZE", "100")),
            business_api_max_pages=int(os.getenv("BUSINESS_API_MAX_PAGES", "20")),
            business_api_records_path=os.getenv("BUSINESS_API_RECORDS_PATH", "data"),
            business_api_timeout_seconds=float(
                os.getenv("BUSINESS_API_TIMEOUT_SECONDS", "30")
            ),
            report_generation_timeout_seconds=float(
                os.getenv("REPORT_GENERATION_TIMEOUT_SECONDS", "150")
            ),
            date_field=os.getenv("REPORT_DATE_FIELD", "created_at"),
            amount_field=os.getenv("REPORT_AMOUNT_FIELD", "amount"),
            status_field=os.getenv("REPORT_STATUS_FIELD", "status"),
            customer_field=os.getenv("REPORT_CUSTOMER_FIELD", "customer_id"),
            category_field=os.getenv("REPORT_CATEGORY_FIELD", "category"),
            success_statuses=_as_tuple(
                os.getenv("REPORT_SUCCESS_STATUSES"), "paid,completed,fulfilled"
            ),
            currency=os.getenv("REPORT_CURRENCY", "USD").upper(),
            max_records=int(os.getenv("REPORT_MAX_RECORDS", "10000")),
            ai_enabled=_as_bool(os.getenv("AI_ENABLED"), True),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            ).rstrip("/"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        )

    def validate(self) -> None:
        missing = []
        if not self.service_api_key:
            missing.append("SERVICE_API_KEY")
        if self.ai_enabled and not self.openai_api_key:
            missing.append("OPENAI_API_KEY (or set AI_ENABLED=false)")
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        if self.business_api_page_size < 1 or self.business_api_max_pages < 1:
            raise ValueError("Business API page size and max pages must be positive")
        if self.business_api_timeout_seconds <= 0 or self.report_generation_timeout_seconds <= 0:
            raise ValueError("API and report generation timeouts must be positive")
        if self.max_records < 1:
            raise ValueError("REPORT_MAX_RECORDS must be positive")
        if self.business_api_page_param and not self.business_api_page_size_param:
            raise ValueError(
                "BUSINESS_API_PAGE_SIZE_PARAM is required when pagination is enabled"
            )
        required_paths = {
            "BUSINESS_API_DATE_FROM_PARAM": self.business_api_date_from_param,
            "BUSINESS_API_DATE_TO_PARAM": self.business_api_date_to_param,
            "REPORT_DATE_FIELD": self.date_field,
            "REPORT_AMOUNT_FIELD": self.amount_field,
            "REPORT_STATUS_FIELD": self.status_field,
            "REPORT_CUSTOMER_FIELD": self.customer_field,
            "REPORT_CATEGORY_FIELD": self.category_field,
        }
        blank_paths = [name for name, value in required_paths.items() if not value.strip()]
        if blank_paths:
            raise ValueError(f"Configuration cannot be blank: {', '.join(blank_paths)}")
        if not self.success_statuses:
            raise ValueError("REPORT_SUCCESS_STATUSES must contain at least one status")
