from calendar import month_abbr, month_name
from datetime import date, timedelta
from decimal import Decimal
import re

from sqlalchemy import func, or_

from app import db
from app.models import Budget, Category, Transaction

MONTHS = {name.lower(): i for i in range(1, 13) for name in (month_name[i], month_abbr[i])}
MONTH_PATTERN = r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b(?:\s+(\d+))?"
DATE_PATTERN = r"\b\d{4}-\d{1,2}-\d{1,2}\b"
MONTH_WORDS = "|".join(sorted(MONTHS, key=len, reverse=True))
TEXT_DATE_PATTERN = re.compile(
    rf"\b(?:(?P<month_first>{MONTH_WORDS})\s+(?P<after>\d{{1,2}})(?:st|nd|rd|th)?"
    rf"|(?P<before>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month_last>{MONTH_WORDS}))"
    r"\b(?:,?\s+(?P<year>\d{4}))?", re.I
)
NO_RECORDS = "I couldn't find any matching transactions for the selected period."
INTENTS = {
    "GENERAL_CONVERSATION", "FINANCIAL_INCOME", "FINANCIAL_EXPENSE", "FINANCIAL_SAVINGS",
    "TRANSACTION_SEARCH", "CATEGORY_ANALYSIS", "MONTHLY_ANALYSIS", "COMPARISON",
    "BUDGET_ANALYSIS", "FINANCIAL_RECOMMENDATION", "FINANCIAL_PREDICTION", "CLARIFICATION_REQUIRED",
}


def shift(month, offset):
    year, index = divmod(month.year * 12 + month.month - 1 + offset, 12)
    return date(year, index + 1, 1)


def read_periods(prompt, today, inherited_year=None):
    periods = []
    matches = list(re.finditer(MONTH_PATTERN, prompt, re.I))
    explicit_years = {int(match[2]) for match in matches if match[2]}
    default_year = next(iter(explicit_years)) if len(explicit_years) == 1 else inherited_year or today.year
    for match in matches:
        month, year = match.groups()
        if month.lower() == "may" and match.start() == 0 and not year and len(prompt.split()) > 1:
            if not re.match(r"may\s+(?:and|vs|versus)\b", prompt, re.I):
                continue
        periods.append(date(int(year) if year else default_year, MONTHS[month.lower()], 1))
    if re.search(r"\b(?:this|current) month\b", prompt):
        periods.append(today.replace(day=1))
    if "last month" in prompt or "previous month" in prompt:
        periods.append(shift(today.replace(day=1), -1))
    for year, month in re.findall(r"\b(\d{4})-(\d{1,2})\b(?!-)", prompt):
        periods.append(date(int(year), int(month), 1))
    if any(not 1900 <= period.year < 9999 for period in periods):
        raise ValueError
    return list(dict.fromkeys(periods))


def read_date_range(prompt, today, inherited_year=None):
    iso_dates = [(match.start(), date.fromisoformat(match[0])) for match in re.finditer(DATE_PATTERN, prompt)]
    matches = list(TEXT_DATE_PATTERN.finditer(prompt))
    years = {int(match["year"]) for match in matches if match["year"]} | {day.year for _, day in iso_dates}
    default_year = next(iter(years)) if len(years) == 1 else inherited_year or today.year
    text_dates = [
        (match.start(), date(int(match["year"]) if match["year"] else default_year,
                            MONTHS[(match["month_first"] or match["month_last"]).lower()],
                            int(match["after"] or match["before"]))) for match in matches
    ]
    dates = [day for _, day in sorted(iso_dates + text_dates)]
    if dates:
        if (len(dates) > 2 or dates[-1] < dates[0] or dates[-1] == date.max or dates[0].year < 1900
                or (len(dates) == 1 and re.search(r"\b(?:from|between)\b.*\b(?:to|and)\b", prompt))):
            raise ValueError
        return dates[0], dates[-1] + timedelta(days=1), " to ".join(day.strftime("%d %B %Y") for day in dates)
    if re.search(r"\blast 30 days\b", prompt):
        return today - timedelta(days=29), today + timedelta(days=1), "the last 30 days"
    match = re.search(r"\b(today|yesterday)\b", prompt)
    if match:
        day = today - timedelta(days=match[1] == "yesterday")
        return day, day + timedelta(days=1), day.strftime("%d %B %Y")
    return None


def intent_for(prompt):
    if re.match(r"^(?:what (?:is|are)|define|explain) (?:a |an )?(?:money|inflation|artificial intelligence|machine learning|python)\b", prompt):
        return "GENERAL_CONVERSATION"
    if re.search(r"difference between.*income.*expenses?|what (?:is|does).*savings rate[?!.]*$", prompt) and "my" not in prompt.split():
        return "GENERAL_CONVERSATION"
    if re.search(r"predict|forecast|next month.s expenses", prompt):
        return "FINANCIAL_PREDICTION"
    if re.search(r"\b(?:what (?:is|are)|define|explain)\s+(?:a |an )?(?:finance|personal finance|income|expenses?|budget|budgeting|savings|debt|interest|investments?|emergency fund)[?!.]*$", prompt):
        return "GENERAL_CONVERSATION"
    if re.search(r"monthly financial health|analy[sz]e|why .*expens|category increased|unusual|financial report", prompt):
        return "MONTHLY_ANALYSIS"
    if re.search(r"\b(?:my|over) budgets?\b|budget utilization|budget (?:is )?remaining|exceeded.*budget|budget control", prompt):
        return "BUDGET_ANALYSIS"
    if re.search(r"too much|recommendation|(?:where|how) can i reduce (?:my|what i spend)|suggestions.*(?:my|spending habits)", prompt):
        return "FINANCIAL_RECOMMENDATION"
    if re.search(r"\btransactions?\b|\b(?:biggest|highest|largest|smallest) expense\b|(?:top|latest) (?:\d+|five|three|ten) expenses", prompt):
        return "TRANSACTION_SEARCH"
    if re.search(r"income.*(?:versus|vs|and).*expenses?", prompt):
        return "MONTHLY_ANALYSIS"
    if re.search(r"compare|versus|\bvs\b|last (?:three|3) months|trend|highest income month|which month.*spend.*most|spending increase", prompt):
        return "COMPARISON"
    if re.search(r"\b(?:savings|saved|left after|my balance)\b|money did i save|more than i earn", prompt):
        return "FINANCIAL_SAVINGS"
    if re.search(r"where .*spen|\bin which areas?\b|categor(?:y|ies)|spend on|spent on|(?:spending|expense) breakdown|percentage.*expenses?.*went", prompt):
        return "CATEGORY_ANALYSIS"
    if re.search(r"\b(?:income|earn|earned|salary|freelanc\w*)\b", prompt):
        if re.search(r"\b(?:expens\w*|spend\w*)\b", prompt):
            return "MONTHLY_ANALYSIS"
        return "FINANCIAL_INCOME"
    if re.search(r"\b(?:expens\w*|spent|spend)\b", prompt) and not re.search(r"tips|reduce unnecessary|difference between", prompt):
        return "FINANCIAL_EXPENSE"
    if re.search(r"^(?:what about|how about|and)\b", prompt):
        return "CLARIFICATION_REQUIRED"
    return "GENERAL_CONVERSATION"


class FinancialAnalytics:
    def __init__(self, uid, currency):
        self.uid = uid
        self.currency = currency

    def money(self, amount):
        prefix = "₹" if self.currency == "INR" else f"{self.currency} "
        return f"{prefix}{amount:,.2f}"

    def transactions(self, start, end):
        query = db.session.query(Transaction, self.category_label).outerjoin(Category).filter(
            Transaction.user_id == self.uid,
            or_(Category.user_id.is_(None), Category.user_id == self.uid),
            Transaction.transaction_date.is_not(None),
        )
        if start:
            query = query.filter(Transaction.transaction_date >= start)
        if end:
            query = query.filter(Transaction.transaction_date < end)
        return query

    @property
    def category_label(self):
        return func.coalesce(func.nullif(func.trim(Category.name), ""), "Uncategorized")

    def totals(self, start, end, category=None):
        query = self.transactions(start, end).with_entities(
            Transaction.type, self.category_label.label("category_label"),
            func.sum(Transaction.amount), func.count(Transaction.id)
        )
        if category:
            query = query.filter(func.lower(self.category_label) == category.lower())
        groups = query.group_by(Transaction.type, "category_label").all()
        breakdown = {"income": {}, "expense": {}}
        counts = {"income": {}, "expense": {}}
        for kind, name, amount, count in groups:
            breakdown[kind][name] = amount
            counts[kind][name] = count
        totals = {kind: sum(values.values(), Decimal(0)) for kind, values in breakdown.items()}
        return totals, breakdown, counts, sum(count for _, _, _, count in groups)

    def categories_in(self, prompt):
        names = db.session.query(Category.name).filter(
            or_(Category.user_id.is_(None), Category.user_id == self.uid)
        ).distinct().all()
        matches = []
        for name in sorted({row.name for row in names}, key=lambda name: (-len(name), name)):
            aliases = {"groceries": ("grocery",), "clothing": ("clothes", "apparel"), "clothes": ("clothing", "apparel")}
            words = (name.lower(), *aliases.get(name.lower(), ()))
            match = re.search(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b", prompt)
            if match:
                matches.append((match.start(), name))
                prompt = prompt[:match.start()] + " " * len(match[0]) + prompt[match.end():]
        return [name for _, name in sorted(matches)]

    def category_in(self, prompt):
        return next(iter(self.categories_in(prompt)), None)

    def budgets(self, month):
        return Budget.query.join(Category).filter(
            Budget.user_id == self.uid, Budget.budget_month == month.month, Budget.budget_year == month.year,
            or_(Category.user_id.is_(None), Category.user_id == self.uid),
        ).all()

    def spending_by_category_id(self, start, end):
        return dict(self.transactions(start, end).filter(Transaction.type == "expense").with_entities(
            Transaction.category_id, func.sum(Transaction.amount),
        ).group_by(Transaction.category_id).all())


def answer_financial(service, intent, prompt, periods, today, category=None, selected_range=None, compared_categories=()):
    current = today.replace(day=1)
    period = periods[-1] if periods else None
    start = period
    end = shift(period, 1) if period else None
    label = period.strftime("%B %Y") if period else "all recorded dates"
    if selected_range:
        start, end, label = selected_range
    if not start and re.search(r"\b(?:this year|last year|\d{4})\b", prompt):
        explicit = re.search(r"\b(\d{4})\b", prompt)
        year = int(explicit[1]) if explicit else today.year - ("last year" in prompt)
        if not 1900 <= year < 9999:
            return "Please enter a year between 1900 and 9998.", None
        start, end, label = date(year, 1, 1), date(year + 1, 1, 1), str(year)
    if not start and (intent == "BUDGET_ANALYSIS" or
                      (intent == "MONTHLY_ANALYSIS" and not re.search(r"\b(?:total|all)\b", prompt)) or
                      (intent == "FINANCIAL_RECOMMENDATION" and "too much" in prompt) or
                      ("monthly" in prompt and intent in {"CATEGORY_ANALYSIS", "FINANCIAL_EXPENSE", "FINANCIAL_INCOME"})):
        start, end, label = current, shift(current, 1), current.strftime("%B %Y")
    money = service.money
    if compared_categories:
        values, breakdown, counts, _ = service.totals(start, end)
        ranked = sorted(((name, breakdown["expense"].get(name, Decimal(0))) for name in compared_categories),
                        key=lambda item: (-item[1], item[0]))
        if not any(name in counts["expense"] for name in compared_categories):
            return NO_RECORDS, None
        return category_answer(ranked, values["expense"], counts["expense"], label, money, len(ranked), partial=True)
    if intent in {"FINANCIAL_PREDICTION", "COMPARISON"}:
        best_kind = ("income" if "highest income month" in prompt else
                     "expense" if re.search(r"which month.*spend.*most", prompt) else None)
        if best_kind:
            rows = service.transactions(start, end).filter(Transaction.type == best_kind).with_entities(
                func.extract("year", Transaction.transaction_date).label("year"),
                func.extract("month", Transaction.transaction_date).label("month"),
                func.sum(Transaction.amount).label("income"),
            ).group_by("year", "month").order_by(func.sum(Transaction.amount).desc(), "year", "month").first()
            metric = "income" if best_kind == "income" else "spending"
            return (f"Your highest recorded {metric} was {money(rows.income)} in {month_name[int(rows.month)]} {int(rows.year)}." if rows else NO_RECORDS), None
        if intent == "COMPARISON" and not periods and "compare" in prompt and not re.search(r"last|trend|income.*expense", prompt):
            return "Which two months should I compare?", None
        if intent == "COMPARISON" and not periods and re.search(r"income.*expense", prompt):
            return answer_financial(service, "MONTHLY_ANALYSIS", prompt, periods, today, category)
        if intent == "FINANCIAL_PREDICTION" or (not periods and re.search(r"three|\b3\b", prompt)):
            months = [shift(current, offset) for offset in (-3, -2, -1)]
        elif not periods and "trend" in prompt:
            months = ([shift(start, offset) for offset in range(12)] if start and not selected_range else
                      [shift(current, offset) for offset in range(-11, 1)])
        else:
            month = periods[-1] if periods else current
            months = sorted(periods) if len(periods) > 1 else [shift(month, -1), month]
        metric = "income" if "income" in prompt else "savings" if "sav" in prompt else "expenses"
        series = []
        for month in months:
            values, _, _, count = service.totals(month, shift(month, 1), category)
            series.append({
                "name": month.strftime("%b %Y"), "income": values["income"], "expenses": values["expense"],
                "savings": values["income"] - values["expense"], "count": count,
            })
        if not any(row["count"] for row in series):
            return NO_RECORDS, None
        if intent == "FINANCIAL_PREDICTION":
            if any(not row["count"] for row in series):
                return "I need records in each of the last three completed months to estimate next month's expenses.", None
            average = sum(row["expenses"] for row in series) / len(series)
            return (f"Estimated expenses for {shift(current, 1):%B %Y}: {money(average)}. "
                    "This estimate uses the average of the last three completed months. Actual spending may differ."), None
        lines = [f"{row['name']}: {money(row[metric])}" if row["count"] else f"{row['name']}: no matching transactions" for row in series]
        if len(series) == 2 and all(row["count"] for row in series):
            first, second = (row[metric] for row in series)
            change = second - first
            percent = f" ({change / abs(first):+.1%})" if first else ""
            lines.append(f"Change in {metric} from {series[0]['name']} to {series[1]['name']}: {money(change)}{percent}.")
        return "\n".join(lines), {"type": "trend" if len(series) > 2 else "comparison", "metric": metric,
                                  "rows": [{**row, **{key: str(row[key]) for key in ("income", "expenses", "savings")}} for row in series]}

    if intent == "BUDGET_ANALYSIS":
        if end != shift(start, 1):
            return "Which month should I use to check your budgets?", None
        budgets = service.budgets(start)
        if not budgets:
            return f"No budgets are configured for {label}.", None
        spending = service.spending_by_category_id(start, end)
        lines = []
        over_only = bool(re.search(r"\bover budget\b|\bexceed(?:ed|ing)\b", prompt))
        attention = "budget control" in prompt
        balances = []
        for budget in budgets:
            if category and category != budget.category.name:
                continue
            spent = spending.get(budget.category_id, Decimal(0))
            balance = budget.amount - spent
            if over_only and balance >= 0:
                continue
            utilization = f"{spent / budget.amount:.0%} used, " if budget.amount else ""
            balances.append((balance, budget.category.name))
            lines.append(
                f"{budget.category.name}: {money(spent)} spent of {money(budget.amount)} "
                f"({utilization}{money(abs(balance))} {'remaining' if balance >= 0 else 'over budget'})."
            )
        if not lines:
            return (f"No matching categories are over budget in {label}." if over_only else
                    f"No budget is configured for {category} in {label}."), None
        if attention:
            balance, name = min(balances)
            lines.append(f"Review {name} first. It has the {'largest budget overrun' if balance < 0 else 'least budget remaining'}.")
        if not category and not over_only and len(balances) > 1:
            balance = sum(amount for amount, _ in balances)
            lines.append(f"Net budget balance: {money(abs(balance))} {'remaining' if balance >= 0 else 'over budget'}.")
        return f"Budgets for {label}\n" + "\n".join(lines), None
    values, breakdown, counts, count = service.totals(start, end, category)
    income, expense = values["income"], values["expense"]
    savings = income - expense
    rate = f"{savings / income:.2%}" if income else "Unavailable with zero income"
    ranked = sorted(breakdown["expense"].items(), key=lambda item: (-item[1], item[0]))
    if not count:
        return NO_RECORDS, None
    if intent == "FINANCIAL_INCOME":
        if not breakdown["income"]:
            return NO_RECORDS, None
        sources = "\n".join(f"• {name}: {money(value)}" for name, value in sorted(breakdown["income"].items()))
        return f"Income for {label}: {money(income)}\n{sources}\nIncome sources: {len(breakdown['income'])}.", None
    if intent == "FINANCIAL_EXPENSE":
        return (f"Expenses for {label}: {money(expense)}" if ranked else NO_RECORDS), None
    if intent == "FINANCIAL_SAVINGS":
        return (f"For {label}\nIncome: {money(income)}\nExpenses: {money(expense)}"
                f"\nNet savings: {money(savings)}\nSavings rate: {rate}."), {
                    "type": "savings", "rows": [{"name": name, "display": money(value)}
                                               for name, value in (("Income", income), ("Expenses", expense), ("Net savings", savings))]}
    query = service.transactions(start, end)
    if category:
        query = query.filter(func.lower(service.category_label) == category.lower())
    if intent == "TRANSACTION_SEARCH":
        top = re.search(r"\b(top|latest) (\d+|five|three|ten) (?:expenses|transactions)\b", prompt)
        smallest = "smallest" in prompt
        largest = bool(re.search(r"biggest|highest|largest", prompt))
        if re.search(r"\bexpenses?\b", prompt):
            query = query.filter(Transaction.type == "expense")
        elif re.search(r"\bincome\b", prompt):
            query = query.filter(Transaction.type == "income")
        threshold = re.search(r"\b(above|over|below|under|at least|at most)\s*(?:₹|inr\s*)?(\d[\d,]*(?:\.\d{1,2})?)(?!\d|\.\d)", prompt)
        if threshold:
            amount = Decimal(threshold[2].replace(",", ""))
            conditions = {
                "above": Transaction.amount > amount, "over": Transaction.amount > amount,
                "below": Transaction.amount < amount, "under": Transaction.amount < amount,
                "at least": Transaction.amount >= amount, "at most": Transaction.amount <= amount,
            }
            query = query.filter(conditions[threshold[1]])
        if re.search(r"\bhow many\b|\bcount\b", prompt):
            matched = query.count()
            return (f"Recorded transactions for {label}: {matched}." if matched else NO_RECORDS), None
        order = (Transaction.amount.asc() if smallest else Transaction.amount.desc()
                 if largest or (top and top[1] == "top") else Transaction.transaction_date.desc())
        limit = 1 if largest or smallest else 101
        if top:
            limit = {"three": 3, "five": 5, "ten": 10}.get(top[2]) or min(max(int(top[2]), 1), 100)
        selected = query.order_by(order, Transaction.id.desc()).limit(limit).all()
        if not selected:
            return NO_RECORDS, None
        rows = [{"date": tx.transaction_date.isoformat(), "name": name, "type": tx.type,
                 "description": tx.description, "display": money(tx.amount)}
                for tx, name in selected[:100]]
        suffix = " Showing the first 100 matches. Ask for a narrower period to see more." if len(selected) > 100 else ""
        first = rows[0]
        answer = (f"{'Smallest' if smallest else 'Largest'} matching transaction for {label}: "
                  f"{first['display']} in {first['name']} on {first['date']}."
                  if largest or smallest else f"Transactions for {label}.{suffix}")
        return answer, {"type": "transactions", "rows": rows}
    if intent == "CATEGORY_ANALYSIS":
        if not ranked:
            return NO_RECORDS, None
        requested = re.search(r"\btop\s+(\d+|five|three|ten)\b", prompt)
        limits = {"five": 5, "three": 3, "ten": 10}
        limit = len(ranked) if not requested else limits.get(requested[1]) or min(max(int(requested[1]), 1), len(ranked))
        overall_expense = service.totals(start, end)[0]["expense"] if category else expense
        return category_answer(ranked, overall_expense, counts["expense"], label, money, limit,
                               partial=bool(category), lowest_first="lowest" in prompt)
    recommendation = (f"Review {ranked[0][0]} first. It was your largest recorded spending category "
                      f"at {money(ranked[0][1])}. Review its transactions for purchases you could reduce or skip."
                      if ranked else "There are no recorded expenses to base a spending recommendation on.")
    if intent == "FINANCIAL_RECOMMENDATION":
        if category and start and end == shift(start, 1):
            budget = next((item for item in service.budgets(start) if item.category.name == category), None)
            if budget:
                spent = service.spending_by_category_id(start, end).get(budget.category_id, Decimal(0))
                delta = spent - budget.amount
                return (f"You spent {money(spent)} on {category} in {label}, "
                        f"{money(abs(delta))} {'over' if delta > 0 else 'under'} your budget of {money(budget.amount)}."), None
        return f"For {label}, expenses totalled {money(expense)}.\nSuggestion: {recommendation}", None

    largest = query.order_by(Transaction.amount.desc(), Transaction.id).first()
    largest_expense = query.filter(Transaction.type == "expense").order_by(Transaction.amount.desc(), Transaction.id).first()
    days = (min(end, today + timedelta(days=1)) - start).days if start and end else 0
    lines = [f"Financial analysis for {label}", f"Income: {money(income)}", f"Expenses: {money(expense)}",
             f"Net savings: {money(savings)}", f"Savings rate: {rate}", f"Total transactions: {count}"]
    if days > 0:
        lines.append(f"Average daily spending: {money(expense / days)}")
    if largest:
        tx, name = largest
        lines.append(f"Largest transaction: {money(tx.amount)} in {name} on {tx.transaction_date:%d %b} ({tx.type}).")
    if largest_expense and expense and largest_expense[0].amount / expense >= Decimal("0.5"):
        tx, name = largest_expense
        lines.append(f"Spending observation: one {name} expense accounted for {tx.amount / expense:.1%} of recorded spending.")
    elif "unusual" in prompt:
        lines.append("No single expense accounted for half or more of recorded spending in this period.")
    if start and not selected_range and end == shift(start, 1):
        previous, prior_breakdown, _, previous_count = service.totals(shift(start, -1), start, category)
        if previous_count:
            lines.append(f"Expense change from the previous month: {money(expense - previous['expense'])}.")
            increases = [(name, value - prior_breakdown["expense"].get(name, Decimal(0))) for name, value in ranked]
            if increases:
                name, increase = max(increases, key=lambda item: item[1])
                if increase > 0:
                    lines.append(f"Largest category increase: {name}, up {money(increase)}.")
        else:
            lines.append("There were no matching transactions in the previous month to compare.")
    category_text, display = (
        category_answer(ranked, expense, counts["expense"], label, money, len(ranked))
        if ranked else ("No recorded expenses.", None)
    )
    return "\n".join([*lines, category_text, f"Suggestion: {recommendation}"]), display


def category_answer(ranked, expense, counts, label, money, limit, partial=False, lowest_first=False):
    if lowest_first:
        ranked = sorted(ranked, key=lambda item: (item[1], item[0]))
    selected_total = sum(value for _, value in ranked)
    count = sum(counts.get(name, 0) for name, _ in ranked)
    rows = [{"name": name, "amount": str(value), "display": money(value),
             "count": counts.get(name, 0), "percentage": f"{value / expense:.2%}" if expense else "—"}
            for name, value in ranked[:limit]]
    title = "Selected category spending" if partial else "Spending breakdown"
    lines = [f"{title} for {label}: {money(selected_total)}."]
    lines.extend(f"• {row['name']}: {row['display']} ({row['percentage']})" for row in rows)
    lines.append(f"Expense transactions: {count}. Average expense: {money(selected_total / count) if count else '—'}.")
    if not partial and expense:
        highest = max(ranked, key=lambda item: item[1])
        lowest = min(ranked, key=lambda item: item[1])
        lines.append(f"Highest spending category: {highest[0]} ({highest[1] / expense:.2%} of total expenses).")
        lines.append(f"Lowest spending category: {lowest[0]} ({lowest[1] / expense:.2%} of total expenses).")
    summary = {"display": money(selected_total), "count": count,
               "percentage": f"{selected_total / expense:.2%}" if expense else "—", "partial": partial}
    return "\n".join(lines), {"type": "categories", "rows": rows, "summary": summary}
