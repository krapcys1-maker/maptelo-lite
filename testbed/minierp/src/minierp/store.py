"""Data of the pricing module, kept in an in-memory SQLite database.

A price version is (price, valid_from). It stays effective until a later version starts,
or until its optional end date (a discontinued product). Saving a new price only inserts
a version, exactly like many legacy systems, so a double submit creates a duplicate.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

Status = Literal["Active", "Planned", "Expired"]

_SCHEMA = """
CREATE TABLE customer (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE product (
    customer_id TEXT NOT NULL REFERENCES customer (id),
    cpn TEXT NOT NULL,
    description TEXT NOT NULL,
    currency TEXT NOT NULL,
    PRIMARY KEY (customer_id, cpn)
);
CREATE TABLE price_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    cpn TEXT NOT NULL,
    seq INTEGER NOT NULL,
    price TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    end_date TEXT,
    created REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (customer_id, cpn) REFERENCES product (customer_id, cpn)
);
"""


@dataclass(frozen=True)
class Customer:
    id: str
    name: str


@dataclass(frozen=True)
class Product:
    customer_id: str
    cpn: str
    description: str
    currency: str


@dataclass(frozen=True)
class PriceVersion:
    id: int
    customer_id: str
    cpn: str
    seq: int
    price: Decimal
    valid_from: date
    end_date: date | None
    created: float = 0.0
    """time.monotonic() when it was saved; 0 for the seed data."""

    @property
    def label(self) -> str:
        return f"V{self.seq}"


@dataclass(frozen=True)
class VersionRow:
    """A version as shown on screen: with its status and computed end of validity."""

    version: PriceVersion
    status: Status
    valid_to: date | None


@dataclass(frozen=True)
class SeedData:
    customers: list[Customer]
    products: list[Product]
    versions: list[tuple[str, str, str, date, date | None]]
    """(customer_id, cpn, price, valid_from, end_date)"""


class Store:
    def __init__(self) -> None:
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._db.executescript(_SCHEMA)

    def load(self, data: SeedData) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM price_version")
            self._db.execute("DELETE FROM sqlite_sequence WHERE name = 'price_version'")
            self._db.execute("DELETE FROM product")
            self._db.execute("DELETE FROM customer")
            self._db.executemany(
                "INSERT INTO customer VALUES (?, ?)", [(c.id, c.name) for c in data.customers]
            )
            self._db.executemany(
                "INSERT INTO product VALUES (?, ?, ?, ?)",
                [(p.customer_id, p.cpn, p.description, p.currency) for p in data.products],
            )
            seq: dict[tuple[str, str], int] = {}
            for customer_id, cpn, price, valid_from, end_date in data.versions:
                key = (customer_id, cpn)
                seq[key] = seq.get(key, 0) + 1
                self._db.execute(
                    "INSERT INTO price_version (customer_id, cpn, seq, price, valid_from, end_date)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (customer_id, cpn, seq[key], price, valid_from.isoformat(), _iso(end_date)),
                )

    def customers(self) -> list[Customer]:
        with self._lock:
            rows = self._db.execute("SELECT id, name FROM customer ORDER BY id").fetchall()
        return [Customer(r["id"], r["name"]) for r in rows]

    def customer(self, customer_id: str) -> Customer | None:
        return next((c for c in self.customers() if c.id == customer_id), None)

    def product(self, customer_id: str, cpn: str) -> Product | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM product WHERE customer_id = ? AND cpn = ?", (customer_id, cpn)
            ).fetchone()
        if row is None:
            return None
        return Product(row["customer_id"], row["cpn"], row["description"], row["currency"])

    def versions(self, product: Product, seen_before: float | None = None) -> list[PriceVersion]:
        """All versions; with ``seen_before``, only those saved before that moment (a reader
        that lags behind the database)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM price_version WHERE customer_id = ? AND cpn = ?"
                " ORDER BY valid_from, seq",
                (product.customer_id, product.cpn),
            ).fetchall()
        return [
            PriceVersion(
                id=r["id"],
                customer_id=r["customer_id"],
                cpn=r["cpn"],
                seq=r["seq"],
                price=Decimal(r["price"]),
                valid_from=date.fromisoformat(r["valid_from"]),
                end_date=date.fromisoformat(r["end_date"]) if r["end_date"] else None,
                created=r["created"],
            )
            for r in rows
            if seen_before is None or r["created"] < seen_before
        ]

    def effective(
        self, product: Product, on: date, seen_before: float | None = None
    ) -> tuple[PriceVersion, int] | None:
        """The version in force on a date, and how many versions tie for it (duplicates)."""
        started = [
            v
            for v in self.versions(product, seen_before)
            if v.valid_from <= on and (v.end_date is None or on <= v.end_date)
        ]
        if not started:
            return None
        latest_start = max(v.valid_from for v in started)
        ties = [v for v in started if v.valid_from == latest_start]
        return max(ties, key=lambda v: v.seq), len(ties)

    def rows(self, product: Product, today: date) -> list[VersionRow]:
        versions = self.versions(product)
        current = self.effective(product, today)
        current_start = current[0].valid_from if current else None
        rows = []
        for version in versions:
            status: Status
            if version.valid_from > today:
                status = "Planned"
            elif version.valid_from == current_start:
                status = "Active"
            else:
                status = "Expired"
            next_start = min(
                (v.valid_from for v in versions if v.valid_from > version.valid_from), default=None
            )
            ends = [version.end_date] if version.end_date else []
            if next_start is not None:
                ends.append(next_start - timedelta(days=1))
            rows.append(VersionRow(version, status, min(ends) if ends else None))
        return rows

    def next_seq(self, product: Product) -> int:
        return max((v.seq for v in self.versions(product)), default=0) + 1

    def add_version(self, product: Product, price: Decimal, valid_from: date) -> PriceVersion:
        created = time.monotonic()
        with self._lock, self._db:
            seq = self._db.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM price_version"
                " WHERE customer_id = ? AND cpn = ?",
                (product.customer_id, product.cpn),
            ).fetchone()[0]
            cursor = self._db.execute(
                "INSERT INTO price_version"
                " (customer_id, cpn, seq, price, valid_from, end_date, created)"
                " VALUES (?, ?, ?, ?, ?, NULL, ?)",
                (
                    product.customer_id,
                    product.cpn,
                    seq,
                    f"{price:.2f}",
                    valid_from.isoformat(),
                    created,
                ),
            )
            new_id = cursor.lastrowid
        assert new_id is not None
        return PriceVersion(
            new_id, product.customer_id, product.cpn, seq, price, valid_from, None, created
        )


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None
