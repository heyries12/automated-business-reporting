# Automated Business Reporting System

An end-to-end reporting pipeline that retrieves transactional data from a REST API, calculates comparable KPIs in Python, generates an AI executive summary, logs each report in Google Sheets, and delivers a scheduled HTML email through n8n.

## What Is Included

- A FastAPI reporting service with API-key authentication.
- Configurable REST API field mapping and optional page-number pagination.
- Current-period and previous-period KPI comparisons.
- OpenAI-compatible structured summaries with deterministic fallback.
- An importable n8n workflow scheduled for 08:00 UTC every day.
- Idempotent Google Sheets rows keyed by report name and UTC period.
- A delivered-report check that prevents normal reruns from sending duplicate email.
- A responsive HTML email report.
- Python and workflow validation tests.

## Architecture

```text
n8n Schedule Trigger
  -> Build reporting period
  -> POST /v1/reports/generate
       -> Retrieve current and previous REST API records
       -> Validate and aggregate records in Python
       -> Generate structured AI summary
       -> Render HTML email and Google Sheets row
  -> Validate report response
  -> Find report_key in Google Sheets
       delivered -> stop
       not delivered -> upsert status=generated
                     -> send Gmail message
                     -> upsert status=delivered
```

Raw business records and business API credentials stay in the Python service. Only aggregate metrics and summary text reach n8n, Google Sheets, and OpenAI.

## Project Files

- `app/`: FastAPI service, REST/AI clients, KPI calculations, and email rendering.
- `workflows/automated-business-reporting.json`: import this into n8n.
- `google-sheets-template.csv`: exact header required by the workflow.
- `.env.example`: all service configuration options.
- `compose.yaml` and `Dockerfile`: container deployment.
- `tests/`: Python and n8n workflow validation tests.

## Source API Contract

The default mapping expects this response:

```json
{
  "data": [
    {
      "id": "order-1001",
      "created_at": "2026-11-24T10:15:00Z",
      "amount": 249.95,
      "status": "paid",
      "customer_id": "customer-42",
      "category": "services"
    }
  ]
}
```

The endpoint receives an inclusive start and exclusive end:

```text
GET /orders?start_date=2026-11-24T00:00:00+00:00&end_date=2026-11-25T00:00:00+00:00
```

Field names do not need to match the example. Configure dot paths such as `totals.grand_total` or `customer.id` in `.env`.

Revenue includes only records whose normalized status appears in `REPORT_SUCCESS_STATUSES`. All valid records count toward total transactions. A record is excluded when its date is outside the requested period, its date has no timezone, its amount is invalid, or its amount exceeds the supported magnitude.

## 1. Configure The Python Service

Create the local environment file:

```powershell
Copy-Item .env.example .env
```

Generate a service key:

```powershell
py -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put that value in `SERVICE_API_KEY`. The same value will later be stored in an n8n Header Auth credential.

Configure the business API:

```dotenv
BUSINESS_API_BASE_URL=https://api.your-company.com/v1
BUSINESS_API_PATH=/orders
BUSINESS_API_TOKEN=your-business-api-token
BUSINESS_API_DATE_FROM_PARAM=start_date
BUSINESS_API_DATE_TO_PARAM=end_date
BUSINESS_API_RECORDS_PATH=data

REPORT_DATE_FIELD=created_at
REPORT_AMOUNT_FIELD=amount
REPORT_STATUS_FIELD=status
REPORT_CUSTOMER_FIELD=customer_id
REPORT_CATEGORY_FIELD=category
REPORT_SUCCESS_STATUSES=paid,completed,fulfilled
REPORT_CURRENCY=USD
```

Authentication options:

- `BUSINESS_API_TOKEN` sends `Authorization: Bearer <token>`.
- `BUSINESS_API_KEY_HEADER` and `BUSINESS_API_KEY_VALUE` send a custom API-key header.
- Both can be set when the source requires both headers.

Set the AI credential:

```dotenv
AI_ENABLED=true
OPENAI_API_KEY=your-openai-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
```

The configured model must support Chat Completions structured JSON output. If AI is disabled, or if the AI request fails after retries, the report still runs with a deterministic summary. The Sheet `summary_mode` is `ai`, `deterministic`, or `deterministic_fallback`.

### Pagination

Leave `BUSINESS_API_PAGE_PARAM` blank if the source returns all records for the period.

For page-number pagination:

```dotenv
BUSINESS_API_PAGE_PARAM=page
BUSINESS_API_PAGE_SIZE_PARAM=limit
BUSINESS_API_PAGE_SIZE=100
BUSINESS_API_MAX_PAGES=20
```

The service fails rather than silently truncating when the final allowed page is full. Cursor-based APIs require adapting `BusinessApiClient.fetch_records` in `app/clients.py`.

## 2. Run The Service

### Docker

```powershell
docker compose up --build -d
```

### Local Python

```powershell
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --env-file .env
```

Check liveness:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Open `http://localhost:8000/docs` to inspect and test the API.

Test report generation before configuring n8n:

```powershell
$headers = @{ "X-API-Key" = "YOUR_SERVICE_API_KEY" }
$body = @{
  report_name = "Daily Business Report"
  period_start = "2026-11-24T00:00:00Z"
  period_end = "2026-11-25T00:00:00Z"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/v1/reports/generate -Headers $headers -ContentType "application/json" -Body $body
```

Confirm that the metrics match the source system before continuing.

## 3. Create The Google Sheet

1. Create a blank spreadsheet.
2. Rename its first tab to `Report Log`.
3. Import `google-sheets-template.csv`, or paste its header row into row 1.
4. Do not rename or reorder the columns.
5. Copy the spreadsheet ID from the URL between `/d/` and `/edit`.

`report_key` is the upsert key. It is a hash of the report name and UTC-normalized period. Sheet writes use raw cell input so summary text cannot be interpreted as a spreadsheet formula.

## 4. Import And Connect n8n

1. In n8n, create a workflow and choose **Import from File**.
2. Import `workflows/automated-business-reporting.json`.
3. Keep the workflow inactive during setup.

### Reporting API credential

Create an n8n **Header Auth** credential:

```text
Name:  X-API-Key
Value: the SERVICE_API_KEY value from .env
```

Select it in `Generate Report`.

Set the node URL according to the deployment:

| Deployment | Reporting API URL |
| --- | --- |
| n8n and API on the same Docker network | `http://reporting-api:8000/v1/reports/generate` |
| n8n in Docker, API on the host | `http://host.docker.internal:8000/v1/reports/generate` |
| n8n running directly on the same host | `http://localhost:8000/v1/reports/generate` |
| n8n Cloud | A public HTTPS service URL |

n8n Cloud cannot call `localhost` or a private Docker service name. Deploy the API behind HTTPS on a reachable host and restrict inbound access where possible.

### Google Sheets credential

1. Create or select a Google Sheets OAuth2 credential with edit access to the spreadsheet.
2. Apply it to `Find Existing Report`, `Log Generated Report`, and `Mark Report Delivered`.
3. In all three nodes, replace `REPLACE_WITH_SPREADSHEET_ID` with the real spreadsheet.
4. Select the `Report Log` tab and refresh the column mappings if n8n requests it.
5. Keep `report_key` as the matching/filter column.

For self-hosted n8n, create a Google OAuth client in Google Cloud and add the redirect URL displayed by the n8n credential screen. Enable the Google Sheets API for that project.

### Gmail credential

1. Create or select a Gmail OAuth2 credential.
2. Apply it to `Send Report Email`.
3. Ensure it can send messages from the connected account.

For self-hosted n8n, enable the Gmail API in the same Google Cloud project and use the n8n OAuth redirect URL.

### Recipient and schedule

Open `Build Daily Period` and replace:

```javascript
const recipientEmail = 'REPLACE_WITH_REPORT_RECIPIENT@example.com';
```

The workflow uses the previous complete UTC day and runs at `08:00 UTC` with this cron expression:

```text
0 8 * * *
```

Change the `Daily Schedule` cron and the period code together if the business reports in another timezone or cadence. Keep timezone-aware ISO boundaries and use an exclusive `period_end`.

## 5. Test Safely

1. Keep the workflow inactive.
2. In `Build Daily Period`, temporarily set dates for which the source API has known data if necessary.
3. Select **Execute Workflow**.
4. Confirm `Generate Report` returns current metrics, previous metrics, trends, summary, HTML, and `sheet_row`.
5. Confirm `Report Log` first receives the row and ends with `delivery_status` equal to `delivered`.
6. Confirm the recipient receives one formatted email.
7. Execute the same period again. `Already Delivered?` should stop the run before another email.
8. Activate the workflow only after these checks pass.

To intentionally resend a report, first clear or change that row's `delivery_status`, then manually execute the same period.

## Sheet Columns

| Column | Purpose |
| --- | --- |
| `report_key` | Stable period key and Sheet match column |
| `generated_at` | UTC generation timestamp |
| `report_name` | Human-readable report name |
| `period_start`, `period_end` | UTC report boundaries; end is exclusive |
| `currency` | Configured ISO-style currency code |
| `total_revenue` | Sum for configured successful statuses |
| `revenue_change_pct` | Change from the equal-length previous period |
| `total_transactions` | All valid records in the period |
| `transactions_change_pct` | Transaction-count period change |
| `completed_transactions` | Records with configured successful statuses |
| `average_order_value` | Revenue divided by completed transactions |
| `unique_customers` | Count of non-empty customer IDs |
| `top_category` | Most frequent category across valid records |
| `executive_summary` | AI or deterministic summary |
| `highlights`, `risks`, `recommendations` | Newline-separated report points |
| `summary_mode` | `ai`, `deterministic`, or `deterministic_fallback` |
| `delivery_status` | `generated` before Gmail, then `delivered` |
| `delivered_at` | UTC delivery completion timestamp |

A trend is blank when the previous value was zero and the current value is nonzero because no meaningful percentage can be calculated.

## Reliability And Security

- Keep `.env` out of source control and store production secrets in the deployment platform's secret manager.
- Restrict network access to the reporting API and always use HTTPS outside a trusted private network.
- The service retries transient connection, `429`, and selected `5xx` errors three times.
- The service rejects ambiguous pagination instead of publishing a partial report.
- OpenAI receives aggregate metrics, not raw business records.
- HTML values are escaped and Google Sheets uses raw input mode.
- A delivered-row lookup prevents sequential duplicate sends.
- Google Sheets is not a transactional database. Do not run overlapping executions for the same report period. Use a database with a unique constraint and delivery ledger if strict concurrent exactly-once processing is required.
- Gmail cannot guarantee exactly-once delivery after an ambiguous network timeout. Inspect Gmail Sent and the Sheet before retrying a failed send step.
- Limit access to n8n execution data because it contains business metrics and generated report text.

## Troubleshooting

### `401 Invalid API key`

Confirm the n8n Header Auth credential is named `X-API-Key` and its value exactly matches `SERVICE_API_KEY`.

### n8n cannot reach the reporting API

Use the URL table above. `reporting-api` resolves only inside the same Docker network; n8n Cloud requires a public HTTPS URL.

### `Business API records path did not resolve to a JSON array`

Set `BUSINESS_API_RECORDS_PATH` to the array's dot path. Use an empty value if the response itself is an array.

### Pagination limit reached

Verify that the API honors page and page-size parameters, then increase `BUSINESS_API_MAX_PAGES` or reduce the reporting period. Do not bypass this error unless completeness is independently guaranteed.

### Report uses a deterministic summary

Inspect `summary_mode`. `deterministic_fallback` means the OpenAI-compatible request failed or returned invalid structured output. Check the service logs, model access, API key, and provider compatibility.

### Google Sheets node reports missing columns

Restore the exact header from `google-sheets-template.csv`, reselect the document and tab in every Sheet node, then refresh mappings.

### A row remains `generated`

The Sheet write succeeded but Gmail or the final Sheet update failed. Check n8n execution details and Gmail Sent before retrying to avoid an ambiguous duplicate.

## Development Tests

```powershell
npm test
& .\.venv\Scripts\python.exe -m pytest -q
```

The workflow test validates graph connections, safe Sheet options, schema alignment, period calculation, response validation, and delivery-row construction. The Python suite covers API authentication, report output, KPI/trend calculations, invalid amounts, and pagination truncation protection.
