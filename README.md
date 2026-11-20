# SmartSpend

SmartSpend is a responsive personal finance application for managing income, expenses, categories, monthly budgets, reports, and personalized spending guidance. The frontend uses JavaScript, React, Vite, Axios, React Router, and Recharts. The API uses Flask, SQLAlchemy, Flask-Migrate, JWT, Marshmallow dependencies, and Flask-Limiter. MySQL 8 is the target database; SQLite is configured as a local development fallback.

## Current features

- Registration, login, logout, hashed passwords, protected screens, profile and password changes, timed password-reset links through configured SMTP.
- User-owned transactions with validation, search, filters, pagination, editing, deletion, and CSV export.
- Income and expense categories, custom categories, monthly budgets, utilization and overspend warnings.
- Dashboard totals, category breakdowns, monthly/yearly selection, and reports from SQL aggregates.
- AI assistant that sees only authenticated-user aggregates, compares current and previous month, includes category/budget context, and returns a graceful fallback when no API key or provider is available.
- Rate limits on authentication endpoints.

## Environment

The current workspace has Python 3.13, Node 22/npm, and Git. MySQL Server and MySQL Workbench are not installed. Install MySQL 8 separately, then create a database/user. Workbench is optional. The app can run locally against SQLite in the meantime.

## Setup

From the project root in PowerShell:

```powershell
Copy-Item .env.example .env
py -m venv .venv
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

## Optional integrations

Set `OPENAI_API_KEY` and `OPENAI_MODEL` to enable provider generated guidance. Without a key, the assistant still reports deterministic account totals and a month comparison. For password recovery, configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM`. Without SMTP, the request responds safely but cannot deliver the reset link.

For production rate limiting, use a shared Redis service and set `RATELIMIT_STORAGE_URI`; `memory://` is suitable only for local development. Never commit secrets.

## Database migrations and schema

`database/schema.sql` documents MySQL 8 tables and indexes. An initial Flask-Migrate revision is included in `backend/migrations/versions`. For later model changes, run Flask-Migrate from `backend` with `PYTHONPATH=.`; use `python -m flask --app run db migrate -m "describe change"`, review the generated revision, then run `python -m flask --app run db upgrade`.

## Tests and build

From the project root:

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m pytest backend\tests -q
cd frontend
npm.cmd run test -- --run
npm.cmd run build
```

## Deployment status

Hosting, a managed MySQL instance, production email, and a provider API key are not configured here. Configure production secrets, Redis-backed rate limits, database migrations, HTTPS, trusted CORS origins, and health checks before deployment. Public deployment and external account actions require explicit approval.
