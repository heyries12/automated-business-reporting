# Automated Business Reporting System

An n8n and Python pipeline that reads business rows from Google Sheets, calculates current and previous-period KPIs, generates an AI executive summary, logs the report, and delivers a scheduled HTML email.

## Architecture

```text
n8n Cloud schedule
  -> Read Business Data tab
  -> POST rows to the secured Python API
  -> Calculate revenue, transactions, customers, categories, and trends
  -> Generate an OpenAI-compatible structured summary
  -> Check Report Log for an already delivered report
  -> Upsert generated status
  -> Send Gmail report
  -> Upsert delivered status
```

The workflow imports inactive and runs daily at `08:00 UTC` after setup.

## Project Files

- `workflows/automated-business-reporting.json`: import into n8n.
- `business-data-template.csv`: required source columns and an example row.
- `google-sheets-template.csv`: required `Report Log` columns.
- `app/`: FastAPI reporting service.
- `render.yaml`: one-click public API deployment for n8n Cloud.
- `.env.example`: local and optional REST-source configuration.
- `tests/`: Python and workflow validation.

## Quick Setup For n8n Cloud

### 1. Prepare Google Sheets

Create one spreadsheet with two tabs.

Create a tab named `Business Data` and import `business-data-template.csv`. Its columns are:

```text
created_at,amount,status,customer_id,category
```

Example:

```csv
created_at,amount,status,customer_id,category
2026-11-24T10:15:00Z,249.95,paid,customer-42,services
```

Requirements:

- `created_at` must be a timezone-aware ISO timestamp.
- `amount` must be numeric.
- `status` should use values such as `paid`, `completed`, or `fulfilled` for revenue-producing rows.
- `customer_id` identifies unique customers.
- `category` is used for category breakdowns.
- Keep at least the current and previous reporting periods in this tab.

Create another tab named `Report Log` and import `google-sheets-template.csv`. Do not rename or reorder its columns.

### 2. Deploy The Python API

n8n Cloud cannot call an API running on your computer. Deploy this repository to a public HTTPS service.

Recommended Render deployment:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/heyries12/automated-business-reporting)

During deployment, Render asks for two secret environment variables:

```text
SERVICE_API_KEY
OPENAI_API_KEY
```

Generate `SERVICE_API_KEY` locally:

```powershell
py -c "import secrets; print(secrets.token_urlsafe(32))"
```

Use that generated value in Render. Do not put secrets in GitHub or the workflow JSON.

After deployment, Render provides a URL similar to:

```text
https://automated-business-reporting-api.onrender.com
```

Verify:

```text
https://YOUR-RENDER-URL/health
```

It should return:

```json
{"status":"ok"}
```

### 3. Import The n8n Workflow

1. In n8n Cloud, create a workflow.
2. Open the workflow menu and choose **Import from File**.
3. Import `workflows/automated-business-reporting.json`.
4. Keep it inactive while configuring credentials.

### 4. Connect Google Sheets

Create a Google Sheets OAuth2 credential in n8n and connect your Google account.

Apply that credential to these nodes:

- `Read Business Data`
- `Find Existing Report`
- `Log Generated Report`
- `Mark Report Delivered`

Configure the nodes:

- `Read Business Data`: select your spreadsheet and the `Business Data` tab.
- The other three Sheet nodes: select the same spreadsheet and the `Report Log` tab.
- Keep `report_key` as the filter or matching column on the report nodes.

### 5. Connect The Reporting API

In n8n credentials, create a **Header Auth** credential:

```text
Name: X-API-Key
Value: the same SERVICE_API_KEY entered in Render
```

Open `Generate Report`:

1. Select the Header Auth credential.
2. Replace the URL with your Render URL followed by the endpoint:

```text
https://YOUR-RENDER-URL/v1/reports/generate-from-records
```

### 6. Connect Gmail

Create a Gmail OAuth2 credential in n8n and apply it to `Send Report Email`.

Open `Build Daily Period` and replace:

```javascript
const recipientEmail = 'REPLACE_WITH_REPORT_RECIPIENT@example.com';
```

with the destination email address.

### 7. Test And Activate

1. Keep the workflow inactive.
2. Make sure `Business Data` contains rows for yesterday and the day before yesterday in UTC.
3. Select **Execute Workflow**.
4. Confirm `Read Business Data` returns your rows.
5. Confirm `Generate Report` returns metrics, trends, summary, and HTML.
6. Confirm `Report Log` ends with `delivery_status` set to `delivered`.
7. Confirm the email arrives.
8. Run the same period again and confirm `Already Delivered?` stops a duplicate email.
9. Activate the workflow.

## Reporting Rules

Revenue includes rows whose lowercase status is listed in `REPORT_SUCCESS_STATUSES`. The Render blueprint defaults to:

```text
paid,completed,fulfilled
```

The API compares the requested period with the immediately preceding period of equal length. The default workflow reports the previous complete UTC day.

Metrics include:

- Total revenue
- Total and completed transactions
- Average order value
- Unique customers
- Top category
- Status and category breakdowns
- Revenue, transaction, customer, and average-order-value changes

OpenAI receives aggregate metrics rather than the original Sheet rows. If AI generation fails after retries, the API produces a deterministic summary and records `deterministic_fallback` in `summary_mode`.

## Customize Existing Sheet Columns

If your Sheet already uses different headers, change these Render environment variables:

```text
REPORT_DATE_FIELD=Date
REPORT_AMOUNT_FIELD=Total
REPORT_STATUS_FIELD=Payment Status
REPORT_CUSTOMER_FIELD=Customer ID
REPORT_CATEGORY_FIELD=Product Category
```

The values must exactly match the Google Sheet header names. Dot paths are supported for REST-source JSON but are normally unnecessary for Sheet rows.

## Schedule

The default cron expression is:

```text
0 8 * * *
```

This runs at `08:00 UTC`. Change the `Daily Schedule` node and `Build Daily Period` code together when using another timezone or weekly/monthly periods.

## API Endpoints

### Google Sheets rows

```text
POST /v1/reports/generate-from-records
```

Request:

```json
{
  "report_name": "Daily Business Report",
  "period_start": "2026-11-24T00:00:00Z",
  "period_end": "2026-11-25T00:00:00Z",
  "records": [
    {
      "created_at": "2026-11-24T10:15:00Z",
      "amount": 249.95,
      "status": "paid",
      "customer_id": "customer-42",
      "category": "services"
    }
  ]
}
```

### Optional REST source

```text
POST /v1/reports/generate
```

This original endpoint retrieves current and previous records from an environment-configured REST API. Configure `BUSINESS_API_*` values from `.env.example` when using it.

Both endpoints require:

```text
X-API-Key: SERVICE_API_KEY
```

Interactive API documentation is available at `/docs`.

## Local Development

```powershell
Copy-Item .env.example .env
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --env-file .env
```

Run tests:

```powershell
npm test
& .\.venv\Scripts\python.exe -m pytest -q
```

## Reliability And Security

- Keep all secrets in Render and n8n credentials, never in workflow fields or GitHub.
- The API uses constant-time service-key comparison.
- The API accepts at most `REPORT_MAX_RECORDS` rows per request.
- Dynamic HTML is escaped and Google Sheets uses raw cell input.
- The stable `report_key` prevents normal sequential duplicate delivery.
- Do not run overlapping executions for the same period; Google Sheets is not a transactional lock.
- Gmail cannot guarantee exactly-once delivery after an ambiguous network timeout. Check Gmail Sent and `Report Log` before retrying a failed delivery.
- Restrict access to n8n execution data because it can contain the source business rows.

## Troubleshooting

### `401 Invalid API key`

The n8n Header Auth value does not match Render's `SERVICE_API_KEY`.

### `Generate Report` cannot connect

Confirm the node uses the public Render HTTPS URL, not `localhost`. Open `/health` in a browser. A free Render service may need time to wake from sleep.

### The report contains zero transactions

Check that `created_at` timestamps fall within yesterday or the preceding day in UTC. Also verify that the Render `REPORT_*_FIELD` values exactly match your Sheet headers.

### Google Sheets reports missing columns

Restore the exact headers from both CSV templates, reselect the spreadsheet tabs, and refresh node mappings.

### A row remains `generated`

The report was logged but Gmail or the final Sheet update failed. Check n8n execution details and Gmail Sent before retrying.
