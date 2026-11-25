from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from app.models import AiSummary, Metrics, Trends


def get_path(value: Any, path: str) -> Any:
    current = value
    if not path:
        return current
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _money(value: Decimal) -> float:
    try:
        return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except InvalidOperation as error:
        raise ValueError("Calculated monetary value is outside the supported range") from error


def calculate_metrics(
    records: list[dict[str, Any]],
    period_start: datetime,
    period_end: datetime,
    *,
    date_field: str,
    amount_field: str,
    status_field: str,
    customer_field: str,
    category_field: str,
    success_statuses: tuple[str, ...],
) -> Metrics:
    valid: list[tuple[Decimal, str, str, str]] = []
    invalid_records = 0

    for record in records:
        occurred_at = _parse_datetime(get_path(record, date_field))
        if not occurred_at or not (period_start <= occurred_at < period_end):
            invalid_records += 1
            continue
        try:
            amount = Decimal(str(get_path(record, amount_field)))
            if not amount.is_finite() or abs(amount) > Decimal("1000000000000000"):
                raise InvalidOperation
            amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError, ValueError):
            invalid_records += 1
            continue

        status = str(get_path(record, status_field) or "unknown").strip().lower()
        customer = str(get_path(record, customer_field) or "").strip()
        category = str(get_path(record, category_field) or "uncategorized").strip()
        valid.append((amount, status, customer, category))

    successful = [item for item in valid if item[1] in success_statuses]
    revenue = sum((item[0] for item in successful), Decimal("0"))
    status_counts = Counter(item[1] for item in valid)
    category_counts = Counter(item[3] for item in valid)
    top_category = category_counts.most_common(1)[0][0] if category_counts else "n/a"
    completed = len(successful)

    return Metrics(
        source_records=len(records),
        valid_records=len(valid),
        invalid_records=invalid_records,
        total_revenue=_money(revenue),
        total_transactions=len(valid),
        completed_transactions=completed,
        average_order_value=_money(revenue / completed) if completed else 0.0,
        unique_customers=len({item[2] for item in valid if item[2]}),
        top_category=top_category,
        status_breakdown=dict(sorted(status_counts.items())),
        category_breakdown=dict(sorted(category_counts.items())),
    )


def _change(current: float | int, previous: float | int) -> float | None:
    if previous == 0:
        return 0.0 if current == 0 else None
    return round(((current - previous) / abs(previous)) * 100, 2)


def calculate_trends(current: Metrics, previous: Metrics) -> Trends:
    return Trends(
        revenue_change_pct=_change(current.total_revenue, previous.total_revenue),
        transactions_change_pct=_change(
            current.total_transactions, previous.total_transactions
        ),
        average_order_value_change_pct=_change(
            current.average_order_value, previous.average_order_value
        ),
        customers_change_pct=_change(
            current.unique_customers, previous.unique_customers
        ),
    )


def deterministic_summary(
    current: Metrics, trends: Trends, currency: str
) -> AiSummary:
    revenue_trend = (
        "not comparable because the previous period was zero"
        if trends.revenue_change_pct is None
        else f"{trends.revenue_change_pct:+.2f}% versus the previous period"
    )
    risks = []
    if current.invalid_records:
        risks.append(
            f"{current.invalid_records} source records were excluded because required fields were invalid."
        )
    if current.total_transactions and not current.completed_transactions:
        risks.append("No transactions had a configured successful status.")

    return AiSummary(
        executive_summary=(
            f"Revenue was {currency} {current.total_revenue:,.2f} from "
            f"{current.completed_transactions} completed transactions, {revenue_trend}."
        ),
        highlights=[
            f"{current.total_transactions} transactions and {current.unique_customers} unique customers were recorded.",
            f"The leading category was {current.top_category}.",
        ],
        risks=risks,
        recommendations=[
            "Review category and status breakdowns before making operational decisions."
        ],
    )
