-- MySQL 8 schema for SmartSpend. Apply to a database named `smartspend`.
CREATE DATABASE IF NOT EXISTS smartspend CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE smartspend;

CREATE TABLE users (
  id INT NOT NULL AUTO_INCREMENT,
  name VARCHAR(120) NOT NULL,
  email VARCHAR(254) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'INR',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB;

CREATE TABLE categories (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NULL,
  name VARCHAR(80) NOT NULL,
  type ENUM('income', 'expense') NOT NULL,
  is_default BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_categories_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  UNIQUE KEY uq_category_owner_name_type (user_id, name, type),
  INDEX ix_categories_owner_type (user_id, type)
) ENGINE=InnoDB;

CREATE TABLE transactions (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  category_id INT NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  type ENUM('income', 'expense') NOT NULL,
  description VARCHAR(500) NOT NULL DEFAULT '',
  transaction_date DATE NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_transactions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_transactions_category FOREIGN KEY (category_id) REFERENCES categories(id),
  CONSTRAINT chk_transactions_amount CHECK (amount > 0),
  INDEX ix_transactions_user_date (user_id, transaction_date),
  INDEX ix_transactions_user_type_date (user_id, type, transaction_date),
  INDEX ix_transactions_category_date (category_id, transaction_date)
) ENGINE=InnoDB;

CREATE TABLE budgets (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  category_id INT NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  budget_month TINYINT UNSIGNED NOT NULL,
  budget_year SMALLINT UNSIGNED NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_budgets_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_budgets_category FOREIGN KEY (category_id) REFERENCES categories(id),
  CONSTRAINT chk_budgets_amount CHECK (amount > 0),
  CONSTRAINT chk_budgets_month CHECK (budget_month BETWEEN 1 AND 12),
  UNIQUE KEY uq_budget_user_category_month (user_id, category_id, budget_month, budget_year),
  INDEX ix_budgets_user_period (user_id, budget_year, budget_month)
) ENGINE=InnoDB;

CREATE TABLE ai_insights (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  insight_type VARCHAR(50) NOT NULL,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  content JSON NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_ai_insights_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX ix_ai_insights_user_period (user_id, period_start, period_end)
) ENGINE=InnoDB;
