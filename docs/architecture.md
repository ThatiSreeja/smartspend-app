# Architecture

The JavaScript React single-page application is served by Vite locally and uses Axios to call a JSON API. Flask exposes the API through a Blueprint. SQLAlchemy models and validates user, category, transaction, budget, and AI insight records. Flask-Migrate is configured for schema evolution; local development can create tables automatically.

JWT protected routes derive the user ID from the signed token and scope queries by that identity. Authentication uses Werkzeug password hashing. Flask-Limiter throttles authentication and reset routes. The AI endpoint aggregates a user's records in Flask and sends only those totals and category/budget summaries to the configured provider; it never creates SQL from a prompt. CSV reports are generated server side.

MySQL 8 is the production target through PyMySQL. SQLite is used by default for a local run before MySQL is available. Production should disable automatic table creation, run reviewed migrations, use HTTPS, and configure shared Redis storage for rate limits.
