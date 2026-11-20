# API documentation

All routes are prefixed by `/api`. Protected routes require `Authorization: Bearer <access_token>`. JSON validation errors use `{"error":"..."}`. Monetary inputs are positive decimal strings or numbers; dates use `YYYY-MM-DD`.

## Auth and profile

- `POST /auth/register` with `{name,email,password}` creates an account and its standard categories, returning `{user,access_token}`.
- `POST /auth/login` with `{email,password}` returns `{user,access_token}`.
- `GET /auth/me` returns the authenticated user.
- `POST /auth/forgot-password` with `{email}` requests a time-limited reset email. SMTP must be configured.
- `POST /auth/reset-password` with `{token,password}` changes the password.
- `PUT /profile` updates name, email, and currency; `PUT /profile/password` changes a password.

## Finance data

- `GET/POST /categories`; `DELETE /categories/:id` manages user categories.
- `GET/POST /transactions`; `PUT/DELETE /transactions/:id` manage transactions. List filters include `search`, `type`, `category_id`, `from`, `to`, `page`, and `per_page`.
- `GET/POST /budgets`; `DELETE /budgets/:id` manages a monthly category budget. Posting an existing category and period updates it.
- `GET /dashboard?month=1..12|all&year=YYYY` returns period totals, previous period, category totals, and recent entries.
- `GET /reports?month=1..12|all&year=YYYY` returns totals and category counts; `GET /reports/export` returns CSV.
- `POST /ai/ask` with `{question}` sends server-aggregated data for the signed-in user to the configured provider. Without a key it returns local summary data.
- `GET /api/health` returns service status.

Registration, login, reset requests, and reset completion are rate limited. Every record lookup is scoped to the authenticated user.
