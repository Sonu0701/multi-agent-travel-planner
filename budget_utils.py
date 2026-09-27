"""Helpers for turning the budget agent's free-text output into structured data.

Budget agents tend to write in one of two shapes:
  1. Plain bullet lines:      "- Flights: $450"
  2. Markdown tables:         "| Flights (round-trip) | ₹12,000 | ... |"
This module handles both, and returns {} (no chart) if neither is detected —
a missing chart is safer than a chart built from mis-parsed numbers.
"""

import re

_LINE_PATTERN = re.compile(
    r"^[\s\-\*•]*"                      # leading bullet / indent
    r"([A-Za-z][A-Za-z &/]{2,30}?)"     # category label, e.g. "Flights", "Food & Drink"
    r"\s*[:\-]\s*"                      # separator
    r"[₹$€£]?\s*"                       # optional currency symbol
    r"([\d,]+(?:\.\d+)?)"               # amount
)

_SKIP_LABELS = {
    "total", "grand total", "overall", "sum", "budget", "estimated total",
    "remaining", "category", "item", "expense", "type", "estimated cost",
}


def _parse_line_pattern(budget_text: str) -> dict:
    breakdown: dict = {}
    for line in budget_text.splitlines():
        match = _LINE_PATTERN.match(line.strip())
        if not match:
            continue
        label, amount_str = match.groups()
        label_clean = label.strip().title()
        if label_clean.lower() in _SKIP_LABELS:
            continue
        try:
            amount = float(amount_str.replace(",", ""))
        except ValueError:
            continue
        if amount <= 0:
            continue
        breakdown[label_clean] = breakdown.get(label_clean, 0.0) + amount
    return breakdown


_COST_HEADER_KEYWORDS = ("cost", "amount", "price", "budget", "estimate", "₹", "$", "€", "£")


def _split_row(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator_row(cells: list) -> bool:
    return all(set(c) <= set("-: ") for c in cells)


def _parse_table_rows(budget_text: str) -> dict:
    """Read markdown tables shaped like '| Category | Amount | Details |'.

    Works table-by-table rather than line-by-line: a table is only treated as
    a cost table if its *second column header* actually says something like
    "Cost", "Amount", "Price" or "Budget" — this stops an unrelated table
    (e.g. a "Quick Overview" table with an "Item | Details" header) sitting
    elsewhere in the same text from leaking bogus numbers into the chart.
    """
    breakdown: dict = {}
    lines = budget_text.splitlines()
    i = 0
    while i < len(lines):
        if not (lines[i].strip().startswith("|") and lines[i].strip().endswith("|")):
            i += 1
            continue

        block = []
        while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
            block.append(lines[i].strip())
            i += 1

        rows = [_split_row(l) for l in block]
        rows = [r for r in rows if not _is_separator_row(r)]
        if len(rows) < 2:
            continue

        header, *body = rows
        if len(header) < 2:
            continue
        amount_col_header = header[1].lower()
        if not any(k in amount_col_header for k in _COST_HEADER_KEYWORDS):
            continue  # not a cost table — skip this whole block

        for row in body:
            if len(row) < 2:
                continue
            label_cell = re.sub(r"\*+", "", row[0]).strip()
            if not label_cell or label_cell.lower() in _SKIP_LABELS:
                continue
            amount_match = re.search(r"[\d][\d,]*(?:\.\d+)?", row[1])
            if not amount_match:
                continue
            try:
                amount = float(amount_match.group().replace(",", ""))
            except ValueError:
                continue
            if amount <= 0:
                continue
            label_clean = label_cell.title()
            breakdown[label_clean] = breakdown.get(label_clean, 0.0) + amount

    return breakdown


def parse_budget_breakdown(budget_text: str) -> dict:
    """Best-effort parse of budget text into {category: amount}.
    Tries the simple 'Label: amount' line style first, then falls back to
    reading markdown table rows. Returns {} if nothing parseable was found.
    """
    if not budget_text:
        return {}

    breakdown = _parse_line_pattern(budget_text)
    if breakdown:
        return breakdown
    return _parse_table_rows(budget_text)