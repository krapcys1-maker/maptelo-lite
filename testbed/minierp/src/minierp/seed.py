"""Deterministic demo data. Dates are relative to 'today', so scenarios never go stale.

Covers the cases a pricing process meets: one version, several versions (only one
active), a planned future price, and a discontinued product without an active price.
"""

from __future__ import annotations

from datetime import date, timedelta

from minierp.store import Customer, Product, SeedData


def first_of_month_ahead(today: date, months: int) -> date:
    month_index = today.month - 1 + months
    return date(today.year + month_index // 12, month_index % 12 + 1, 1)


def seed_data(today: date) -> SeedData:
    def ago(days: int) -> date:
        return today - timedelta(days=days)

    planned = first_of_month_ahead(today, 2)
    customers = [
        Customer("C001", "Acme Packaging Sp. z o.o."),
        Customer("C002", "Globex Retail S.A."),
        Customer("C003", "Initech Logistics"),
    ]
    products = [
        Product("C001", "48211-A", "Corrugated box 400x300x200", "EUR"),
        Product("C001", "48212-B", "Shelf-ready tray", "EUR"),
        Product("C001", "48213-C", "Pallet wrap 23 um", "EUR"),
        Product("C002", "51001-A", "Display carton", "EUR"),
        Product("C002", "51002-D", "Gift box premium", "EUR"),
        Product("C003", "70010-A", "Shipping label roll", "EUR"),
        Product("C003", "70011-B", "Edge protector 50 mm", "EUR"),
        Product("C003", "70012-C", "Archive box (discontinued)", "EUR"),
    ]
    versions: list[tuple[str, str, str, date, date | None]] = [
        ("C001", "48211-A", "315.00", ago(200), None),
        ("C001", "48212-B", "120.00", ago(600), None),
        ("C001", "48212-B", "125.50", ago(400), None),
        ("C001", "48212-B", "129.90", ago(200), None),
        ("C001", "48213-C", "92.40", ago(150), None),
        ("C001", "48213-C", "88.00", planned, None),
        ("C002", "51001-A", "46.20", ago(300), None),
        ("C002", "51002-D", "18.00", ago(700), None),
        ("C002", "51002-D", "19.20", ago(450), None),
        ("C002", "51002-D", "21.00", ago(180), None),
        ("C002", "51002-D", "22.50", planned, None),
        ("C003", "70010-A", "12.75", ago(90), None),
        ("C003", "70011-B", "3.10", ago(500), None),
        ("C003", "70011-B", "3.35", ago(120), None),
        ("C003", "70012-C", "7.80", ago(500), ago(30)),
    ]
    return SeedData(customers, products, versions)
