USE smartspend;
INSERT INTO categories (user_id, name, type, is_default) VALUES
(NULL, 'Salary', 'income', TRUE), (NULL, 'Freelance', 'income', TRUE),
(NULL, 'Business', 'income', TRUE), (NULL, 'Investments', 'income', TRUE),
(NULL, 'Other Income', 'income', TRUE), (NULL, 'Food', 'expense', TRUE),
(NULL, 'Shopping', 'expense', TRUE), (NULL, 'Travel', 'expense', TRUE),
(NULL, 'Rent', 'expense', TRUE), (NULL, 'Bills', 'expense', TRUE),
(NULL, 'Healthcare', 'expense', TRUE), (NULL, 'Education', 'expense', TRUE),
(NULL, 'Entertainment', 'expense', TRUE), (NULL, 'Other Expenses', 'expense', TRUE);
