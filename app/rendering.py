from html import escape

from app.models import AiSummary, Metrics, Trends


def _trend(value: float | None) -> str:
    if value is None:
        return "New / no prior baseline"
    return f"{value:+.2f}%"


def _items(values: list[str], empty: str) -> str:
    rows = values or [empty]
    return "".join(f"<li>{escape(value)}</li>" for value in rows)


def render_email(
    *,
    report_name: str,
    period_label: str,
    currency: str,
    metrics: Metrics,
    trends: Trends,
    summary: AiSummary,
) -> str:
    return f"""<!doctype html>
<html lang="en">
<body style="margin:0;background:#f3f5f4;color:#17201c;font-family:Arial,sans-serif">
  <div style="max-width:720px;margin:0 auto;padding:28px 16px">
    <div style="background:#173d32;color:#fff;padding:28px;border-radius:14px 14px 0 0">
      <div style="font-size:12px;letter-spacing:1.5px;text-transform:uppercase;color:#b9d7cc">Automated report</div>
      <h1 style="margin:8px 0 4px;font-size:28px">{escape(report_name)}</h1>
      <div style="color:#d8e8e2">{escape(period_label)}</div>
    </div>
    <div style="background:#fff;padding:24px;border:1px solid #dfe5e2;border-top:0">
      <p style="font-size:17px;line-height:1.6;margin-top:0">{escape(summary.executive_summary)}</p>
      <table role="presentation" style="width:100%;border-collapse:collapse;margin:22px 0">
        <tr>
          <td style="padding:14px;background:#eef5f2;border:4px solid #fff"><strong style="font-size:22px">{escape(currency)} {metrics.total_revenue:,.2f}</strong><br><span style="color:#53635c">Revenue ({_trend(trends.revenue_change_pct)})</span></td>
          <td style="padding:14px;background:#eef5f2;border:4px solid #fff"><strong style="font-size:22px">{metrics.total_transactions:,}</strong><br><span style="color:#53635c">Transactions ({_trend(trends.transactions_change_pct)})</span></td>
        </tr>
        <tr>
          <td style="padding:14px;background:#eef5f2;border:4px solid #fff"><strong style="font-size:22px">{escape(currency)} {metrics.average_order_value:,.2f}</strong><br><span style="color:#53635c">Average order value</span></td>
          <td style="padding:14px;background:#eef5f2;border:4px solid #fff"><strong style="font-size:22px">{metrics.unique_customers:,}</strong><br><span style="color:#53635c">Unique customers</span></td>
        </tr>
      </table>
      <h2 style="font-size:18px;margin:24px 0 8px">Highlights</h2>
      <ul style="line-height:1.6;margin-top:0">{_items(summary.highlights, 'No highlights identified.')}</ul>
      <h2 style="font-size:18px;margin:24px 0 8px">Risks and watch items</h2>
      <ul style="line-height:1.6;margin-top:0">{_items(summary.risks, 'No material risks identified from these metrics.')}</ul>
      <h2 style="font-size:18px;margin:24px 0 8px">Recommended follow-up</h2>
      <ul style="line-height:1.6;margin-top:0">{_items(summary.recommendations, 'Continue monitoring the same KPIs.')}</ul>
      <p style="font-size:12px;color:#6b7772;margin:28px 0 0">Generated from aggregate API data. Validate material decisions against the source system.</p>
    </div>
  </div>
</body>
</html>"""
