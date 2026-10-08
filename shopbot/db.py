"""SQLite storage: schema and a thin connection wrapper."""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    lang        TEXT NOT NULL DEFAULT 'en',
    state       TEXT NOT NULL DEFAULT '',
    state_data  TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE,
    active  INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS products (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id    INTEGER NOT NULL REFERENCES categories(id),
    name           TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    price_cents    INTEGER NOT NULL CHECK (price_cents >= 0),
    stock          INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    photo_file_id  TEXT,
    active         INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id, active);
CREATE TABLE IF NOT EXISTS cart_items (
    user_id     INTEGER NOT NULL,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    qty         INTEGER NOT NULL CHECK (qty > 0),
    PRIMARY KEY (user_id, product_id)
);
CREATE TABLE IF NOT EXISTS cart_coupons (
    user_id  INTEGER PRIMARY KEY,
    code     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coupons (
    code      TEXT PRIMARY KEY,
    percent   INTEGER NOT NULL CHECK (percent BETWEEN 1 AND 90),
    max_uses  INTEGER NOT NULL CHECK (max_uses > 0),
    used      INTEGER NOT NULL DEFAULT 0,
    active    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'new',
    customer_name    TEXT NOT NULL,
    phone            TEXT NOT NULL,
    address          TEXT NOT NULL,
    payment_method   TEXT NOT NULL,
    coupon_code      TEXT,
    subtotal_cents   INTEGER NOT NULL,
    discount_cents   INTEGER NOT NULL DEFAULT 0,
    total_cents      INTEGER NOT NULL,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, id DESC);
CREATE TABLE IF NOT EXISTS order_items (
    order_id          INTEGER NOT NULL REFERENCES orders(id),
    product_id        INTEGER NOT NULL,
    name              TEXT NOT NULL,
    unit_price_cents  INTEGER NOT NULL,
    qty               INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
"""


class Database:
    """One connection, used from a single thread (the polling loop)."""

    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, isolation_level=None)  # we manage transactions
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)

    def one(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params).fetchall()

    def run(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params)

    def transaction(self):
        return _Tx(self.conn)

    def close(self):
        self.conn.close()

    def __del__(self):
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001 - interpreter shutdown
            pass


class _Tx:
    """BEGIN IMMEDIATE ... COMMIT/ROLLBACK, so stock checks cannot interleave."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False
