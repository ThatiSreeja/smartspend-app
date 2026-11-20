# Database design

`database/schema.sql` defines MySQL 8 tables for users, categories, transactions, budgets, and AI insights. SQLAlchemy models in `backend/app/models.py` map to those tables. Monetary values use `DECIMAL(12,2)`. Foreign keys and indexes support user/date and category reporting queries. A unique constraint prevents duplicate budgets for a user, category, and month. Shared default categories are seeded by `database/seed.sql`; registration also creates user-owned defaults for isolated accounts.

SQLite is the default local development database. Set `DATABASE_URL` to a MySQL PyMySQL URL to use MySQL. The schema script and model metadata should be kept aligned; use Flask-Migrate for reviewed production schema changes.
