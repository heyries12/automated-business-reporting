from datetime import datetime, timezone

from app.reporting import calculate_metrics, calculate_trends, deterministic_summary


START = datetime(2026, 11, 24, tzinfo=timezone.utc)
END = datetime(2026, 11, 25, tzinfo=timezone.utc)
OPTIONS = {
    "date_field": "created_at",
    "amount_field": "totals.amount",
    "status_field": "status",
    "customer_field": "customer.id",
    "category_field": "category",
    "success_statuses": ("paid", "completed"),
}


def test_calculate_metrics_filters_and_aggregates_records():
    records = [
        {
            "created_at": "2026-11-24T08:00:00Z",
            "totals": {"amount": "120.50"},
            "status": "PAID",
            "customer": {"id": "customer-1"},
            "category": "Hardware",
        },
        {
            "created_at": "2026-11-24T12:00:00+00:00",
            "totals": {"amount": 79.5},
            "status": "completed",
            "customer": {"id": "customer-2"},
            "category": "Hardware",
        },
        {
            "created_at": "2026-11-24T14:00:00Z",
            "totals": {"amount": 50},
            "status": "pending",
            "customer": {"id": "customer-1"},
            "category": "Services",
        },
        {
            "created_at": "2026-11-23T14:00:00Z",
            "totals": {"amount": 999},
            "status": "paid",
            "customer": {"id": "customer-3"},
            "category": "Services",
        },
        {
            "created_at": "2026-11-24T15:00:00Z",
            "totals": {"amount": "not-a-number"},
            "status": "paid",
            "customer": {"id": "customer-4"},
            "category": "Services",
        },
    ]

    metrics = calculate_metrics(records, START, END, **OPTIONS)

    assert metrics.source_records == 5
    assert metrics.valid_records == 3
    assert metrics.invalid_records == 2
    assert metrics.total_revenue == 200.0
    assert metrics.total_transactions == 3
    assert metrics.completed_transactions == 2
    assert metrics.average_order_value == 100.0
    assert metrics.unique_customers == 2
    assert metrics.top_category == "Hardware"
    assert metrics.status_breakdown == {"completed": 1, "paid": 1, "pending": 1}


def test_trends_and_deterministic_fallback():
    current = calculate_metrics(
        [
            {
                "created_at": "2026-11-24T08:00:00Z",
                "totals": {"amount": 100},
                "status": "paid",
                "customer": {"id": "customer-1"},
                "category": "Services",
            }
        ],
        START,
        END,
        **OPTIONS,
    )
    previous = calculate_metrics([], START, END, **OPTIONS)

    trends = calculate_trends(current, previous)
    summary = deterministic_summary(current, trends, "USD")

    assert trends.revenue_change_pct is None
    assert trends.transactions_change_pct is None
    assert summary.executive_summary.startswith("Revenue was USD 100.00")
    assert summary.recommendations


def test_extreme_amount_is_rejected_as_invalid():
    metrics = calculate_metrics(
        [
            {
                "created_at": "2026-11-24T08:00:00Z",
                "totals": {"amount": "1e1000"},
                "status": "paid",
                "customer": {"id": "customer-1"},
                "category": "Services",
            }
        ],
        START,
        END,
        **OPTIONS,
    )

    assert metrics.valid_records == 0
    assert metrics.invalid_records == 1
