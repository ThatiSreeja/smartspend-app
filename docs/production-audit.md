# SmartSpend production-readiness audit

## Scope and baseline

Reviewed the React/Vite client, Flask routes and models, chatbot routing and analytics, migrations, MySQL schema, environment templates, dependency manifests, Git remotes, and Render Blueprint. The checkout tracks the replacement GitHub repository on master. It has no GitHub Actions workflow. Local baseline passed 14 backend tests, seven frontend tests, the frontend production build, and pip check. npm's production advisory scan returned zero advisories at the time of testing.

## Findings before fixes

| Severity | Finding |
| --- | --- |
| Critical | The Blueprint provisions expiring free Postgres and enables schema creation on worker startup. An absent database URL silently selects SQLite. Production needs a durable, explicitly configured database and a reviewed migration path. |
| High | The timestamp migration adds required columns without backfilling populated databases. Databases created by the older startup path may also lack an Alembic revision. |
| High | Password reset links can be reused until expiry. Existing JWTs remain valid after password changes. |
| High | Production defaults allow localhost CORS origins, random per-worker signing keys, and process-local rate limits. |
| High | Spreadsheet exports emit user-entered fields as spreadsheet formulas when they have formula prefixes. |
| High | The legacy chat sends detailed account summaries to an external provider automatically. The newer chat also sends financial summaries for certain questions. |
| Medium | Invalid JSON shapes, out-of-range budgets and dates, and sub-cent positive amounts can produce server errors or inconsistent records. |
| Medium | The health endpoint does not check database readiness. Chat calls have general request limits but no dedicated ceiling. |
| Medium | Browser bearer tokens persist across browser restarts. Chat history can remain in session storage after signing out. |
| Medium | Production build settings, actual cloud database history, SMTP and AI provider reachability require release verification. |
| Low | The replacement repository has no checked-in CI workflow. Dashboard display rounds away fractional amounts. |

## Changes and outcomes

| Severity | Issue | Result |
| --- | --- | --- |
| Critical | Expiring database and startup schema creation | The Blueprint no longer provisions a database. Production requires an explicit MySQL or PostgreSQL URL and disables automatic table creation. Migrations run in a pre-deploy step on paid API compute. |
| Critical | Vulnerable Vitest and Tinypool tooling | Updated Vitest and removed the vulnerable transitive tooling. Moved Vite and the React plugin to development dependencies. The full npm rescan found zero advisories. |
| High | Python dependency maintenance and test advisories | Raised the PyJWT and Flask-CORS minimum versions, moved the API to a maintained Gunicorn release, and upgraded pytest after the advisory scan. Pytest is now installed only for tests and CI. |
| High | Timestamp migration on existing rows | Adds nullable columns, backfills from known timestamps, and then enforces non-null constraints. Verified with populated SQLite and a separate MySQL 8 instance. |
| High | Reusable reset links and stale JWTs | A successful reset consumes the link using a conditional write. Password changes invalidate older JWTs. Existing signed-in users and previously issued reset links will require fresh sign-in or a fresh link at cutover. |
| High | Insecure production defaults | Explicit HTTPS CORS origins, independent secrets, shared Redis-compatible rate limits, and database fail-fast settings. The readiness path checks the database and shared limiter. |
| High | CSV spreadsheet formula interpretation | User-entered category and description cells with formula prefixes are escaped on export. Recorded text is preserved in the database. |
| High | External AI data sharing | Production routes both chat endpoints through the scoped handler. Verified account summaries stay local by default. Sharing selected summaries requires an explicit opt-in, and transaction lists are excluded from summary sharing. General chat text can still reach the configured provider. |
| Medium | Malformed requests and reporting edge cases | Added JSON structure and size checks, budget and date validation, rate-limit responses, fractional currency display, and grouped budget queries. |
| Medium | Browser session exposure | Bearer tokens use tab-scoped session storage. Sign-out removes the active user's chat history and revokes the current token on the server when reachable. |
| Low | Missing automated GitHub checks | Added backend, frontend, advisory, and isolated PostgreSQL migration checks. The workflow has not run on GitHub yet. |

## Verification

- Final result was 20 backend tests and eight frontend tests passing. The frontend production build and `pip check` passed. The final npm and Python dependency scans reported no known advisories in their tested dependency sets. Local `/api/ready` returned 200.
- Flask integration tests exercised account creation and login, password hashing, reset replay rejection, JWT expiry/revocation behavior after reset, transaction create/edit/delete, category and monthly totals, chart payloads, budgets, exports, chat follow-ups, provider failures, and account isolation. Rejected foreign account access, invalid input, and an unapproved CORS origin.
- React tests exercised registration and sign-in states, dashboard chart data and month selection, the chat UI and storage, and sign-out cleanup. The static production build used an HTTPS API build variable.
- Existing development SQLite was checked in read-only mode. Expected tables and the Alembic version table were present, and the foreign-key consistency check returned no violations.
- An isolated MySQL 8 service on a different loopback port migrated populated tables, retained transaction amounts and primary/foreign keys, and served an authenticated category-analysis request. It used synthetic data. The existing MySQL service and application records were not changed.
- PostgreSQL migration SQL compiled offline. Live Render PostgreSQL, Redis, SMTP, AI credentials, browser rendering under Render headers, and Linux Gunicorn startup still require staging verification. The GitHub PostgreSQL job is configured for the equivalent isolated migration and API test.
- Render's published JSON Schema accepted the Blueprint. The CI YAML parsed locally. Render workspace validation and actual GitHub workflow runs are still pending.

## Remaining findings

| Severity | Finding |
| --- | --- |
| High | Confirm the existing Render database's durability, backup and exact Alembic history before the first pre-deploy migration. PostgreSQL and Redis must be tested using the approved staging endpoints. |
| Medium | Confirm password-reset delivery, AI provider responses, and effective per-client rate limits through Render ingress. General-chat outage behavior and financial calculations were tested with synthetic or mocked inputs. |
| Medium | The SQL bootstrap file and migration history are separate schema paths. MySQL bootstrap constraints and indexes differ in places from the portable migrations. Inspect an unversioned production schema before assigning a migration revision. |
| Medium | If the browser cannot reach the server during sign-out, it clears its local session immediately. Server-side revocation depends on delivery of the logout request. |
| Low | GitHub branch protection, Render build permissions and auto-sync settings were not verified against the account. |

## Render release runbook

1. Confirm the existing Render web service and static site both track `ThatiSreeja/smartspend-app`, branch `master`. Confirm the linked Blueprint and disable its Auto Sync before pushing if a push must not trigger a change. Keep the existing services and database. The local Blueprint sets service auto-deploy to off. The paid API plan and its cost require approval. [Render Blueprint management](https://render.com/docs/infrastructure-as-code)
2. Confirm the existing database engine, reachability, durable plan, and backup or restore point. If the original free Postgres database has expired, recover from a retained backup; a new empty database will not restore user history. Keep the current engine and use the correct existing connection URL. For managed Render Postgres, use its internal URL in the same region. [Render free-instance limits](https://render.com/docs/free)
3. On a restored staging copy, run `python -m flask --app run db current` from `backend` with automatic table creation disabled. For a versioned database, rehearse `db upgrade` and compare record counts. If tables exist without `alembic_version`, inspect every table and column against a known revision before deciding whether to stamp. Stamp only the revision whose schema actually matches. Resolve partially applied or divergent migrations on the copy before touching production.
4. Configure the environment below on both existing services. Confirm the protected branch and green GitHub checks. Use the existing Blueprint's manual sync or apply the equivalent settings in the Render Dashboard only after approval. The new Blueprint intentionally leaves datastore selection to the operator. Removing the original datastore definition from this Blueprint does not delete that datastore. [Render Blueprint management](https://render.com/docs/infrastructure-as-code)
5. After the approved release, require `GET /api/ready` to return 200 and check the API logs. Verify TLS, the HTTPS frontend origin, the ingress proxy hop count used for client-IP rate limiting, two existing test accounts, browser charts, AI, password reset delivery, and Redis rate limits. If staging or production checks fail, pause the rollout. Confirm schema compatibility before rolling back an app version. Use the database restore plan for a failed migration. [Render deploy lifecycle](https://render.com/docs/deploys) · [Render ingress and rate limiting](https://render.com/articles/how-render-handles-ddos-attacks)

### Environment variables

| Service | Variables | Purpose |
| --- | --- | --- |
| API | `SMARTSPEND_ENV=production`, `AUTO_CREATE_TABLES=false`, `PYTHON_VERSION=3.13.18` | Enable production validation and reviewed migrations. |
| API | `DATABASE_URL`, `RATELIMIT_STORAGE_URI` | Existing database URL and the internal Redis/Render Key Value URL. Use `mysql+pymysql://...` or a PostgreSQL URL, and `redis://...` or `rediss://...`. |
| API | `SECRET_KEY`, `JWT_SECRET_KEY`, `FRONTEND_ORIGIN` | Independent random secrets of at least 32 characters and the deployed HTTPS frontend origin. The first origin is used for reset links. Preserve valid existing secrets where practical. |
| API | `TRUSTED_PROXY_HOPS` | Set according to the verified staging ingress chain. The default is zero because proxy headers are trusted only when the chain is known. |
| API | `OPENAI_API_KEY` / `OPENAI_MODEL` or `GROQ_API_KEY` / `GROQ_MODEL` | Optional for financial calculations. Configure one provider for open-ended general chat. Groq takes precedence if both keys are set. |
| API | `AI_SHARE_FINANCIAL_SUMMARIES=false` | Optional opt-in for sharing selected calculated summaries. |
| API | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Required for password-reset delivery. The SMTP sender uses STARTTLS. Render Free blocks common SMTP ports. [Render SMTP policy](https://render.com/changelog/free-web-services-will-no-longer-allow-outbound-traffic-to-smtp-ports) |
| Static site | `VITE_RENDER_API_ORIGIN`, `NODE_VERSION=~22` | Full HTTPS API origin without `/api`; Node 22.12 or newer in the 22 series. Only public configuration belongs in `VITE_*` variables. |

### Commands

| Render setting | Command/value |
| --- | --- |
| API build | `python -m pip install -r backend/requirements.txt` |
| API pre-deploy | `cd backend && python -m flask --app run db upgrade` |
| API start | `cd backend && gunicorn --workers 2 --threads 2 --bind 0.0.0.0:$PORT run:app` |
| API health path | `/api/ready` |
| Static build | `test -n "$VITE_RENDER_API_ORIGIN" && cd frontend && export npm_config_script_shell=/bin/sh && npm ci --include=dev && npm run build` |
| Static publish directory | `frontend/dist` |
| SPA routing | Rewrite `/*` to `/index.html`. |
