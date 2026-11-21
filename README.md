# SmartSpend

SmartSpend is a responsive personal finance application for managing income, expenses, categories, monthly budgets, reports, and personalized spending guidance. The frontend uses JavaScript, React, Vite, Axios, React Router, and Recharts. The API uses Flask, SQLAlchemy, Flask-Migrate, JWT, Marshmallow dependencies, and Flask-Limiter. MySQL 8 is the target database; SQLite is configured as a local development fallback.

## Current features

- Registration, login, logout, hashed passwords, protected screens, profile and password changes, timed password-reset links through configured SMTP.
- User-owned transactions with validation, search, filters, pagination, editing, deletion, and CSV export.
- Income and expense categories, custom categories, monthly budgets, utilization and overspend warnings.
- Dashboard totals, category breakdowns, monthly/yearly selection, and reports from SQL aggregates.
- AI assistant for general questions, personal finance, and mixed queries. The backend calculates account answers from the signed-in user's transactions and budgets.
- Rate limits on authentication endpoints.

## Environment

The project uses Python 3.13, Node 22/npm, and Git. To run against MySQL 8, create a database and application user and configure `DATABASE_URL`. MySQL Workbench is optional. When `DATABASE_URL` is unset, the development app uses SQLite.

## Setup

From the project root in PowerShell:

```powershell
Copy-Item .env.example .env
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
cd frontend
npm.cmd install
```

Set unique random `SECRET_KEY` and `JWT_SECRET_KEY` values in `.env`. To use MySQL, set `DATABASE_URL` to `mysql+pymysql://user:password@localhost:3306/smartspend`. Keep `.env` private. The current app creates tables on startup by default; set `AUTO_CREATE_TABLES=false` when using migrations in production.

Create the MySQL schema and initial shared categories with:

```powershell
mysql -u root -p < database\schema.sql
mysql -u root -p smartspend < database\seed.sql
```

## Run locally

Start the backend in one terminal from the project root:

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe backend\run.py
```

Start the frontend in another terminal:

```powershell
cd frontend
npm.cmd run dev
```

Open <http://localhost:5173>. Register a new account to begin; there is no preloaded demo login. The API health route is <http://127.0.0.1:5000/api/health>. The frontend `.npmrc` configures PowerShell as npm's script shell because the workspace path contains `&`.

The app verifies the saved session on refresh before loading protected pages. Sessions live in the current browser tab and last up to one hour. Reopening in a new browser session requires sign-in. Signing out clears the tab's session and chat history and revokes the access token when the server is reachable.

## Optional integrations

### Chat assistant

Set `OPENAI_API_KEY` and `OPENAI_MODEL` in the backend environment for open-ended chat. Alternatively, set `GROQ_API_KEY` and `GROQ_MODEL`. Groq takes precedence when its key is set. Restart the Flask backend after changing these values and open the AI assistant in the app.

General questions go to the configured provider without querying transaction records. Mixed questions and personalized advice use the backend's calculations. By default, the application keeps calculated account figures local. Set `AI_SHARE_FINANCIAL_SUMMARIES=true` only if you intend the provider to receive selected calculated summaries. When the provider is unavailable, account calculations and a limited set of general explanations still work.

Try “What is money?”, “How much did I spend this month?”, or “Explain inflation and show my expenses.” Account answers use the database selected by `DATABASE_URL`. The MySQL connection uses the existing schema in `database/schema.sql`.

For a spending breakdown, ask “In which areas did I spend my money in September?” You can follow it with “What about food?” and “Show the transactions.” A named month uses the current year unless a year was established in the conversation. For a specific date range, use “Show transactions from 2026-09-01 to 2026-09-30.” Both dates are included.

For password recovery, configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM`. Without SMTP, the request responds safely but cannot deliver the reset link.

For production rate limiting, use a shared Redis service and set `RATELIMIT_STORAGE_URI`; `memory://` is suitable only for local development. Never commit secrets.

## Database migrations and schema

`database/schema.sql` documents MySQL 8 tables and indexes. An initial Flask-Migrate revision is included in `backend/migrations/versions`. For later model changes, run Flask-Migrate from `backend` with `PYTHONPATH=.`; use `python -m flask --app run db migrate -m "describe change"`, review the generated revision, then run `python -m flask --app run db upgrade`.

## Tests and build

From the project root:

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest backend\tests -q
cd frontend
npm.cmd run test -- --run
npm.cmd run build
```

## Deployment status

See the [production-readiness audit and Render runbook](docs/production-audit.md) for the deployment commands, environment settings, and database migration checks.
