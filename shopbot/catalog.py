"""Categories and products."""
from __future__ import annotations

import re
import sqlite3
from decimal import Decimal, InvalidOperation

from .db import Database
from .errors import ShopError

PAGE_SIZE = 5


def parse_price(text: str) -> int:
    """'12.5' -> 1250. Accepts a comma as decimal separator. Raises ValueError."""
    text = text.strip().replace(",", ".")
    if not re.fullmatch(r"\d{1,7}(\.\d{1,2})?", text):
        raise ValueError("bad price")
    try:
        return int((Decimal(text) * 100).to_integral_value())
    except InvalidOperation as exc:  # pragma: no cover - regex already guards this
        raise ValueError("bad price") from exc


def format_money(cents: int, currency: str = "USD") -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d} {currency}"


# --- categories -----------------------------------------------------------

def add_category(db: Database, name: str) -> int:
    name = name.strip()
    if not 2 <= len(name) <= 40:
        raise ShopError("bad_name_len")
    try:
        cur = db.run("INSERT INTO categories(name) VALUES (?)", (name,))
    except sqlite3.IntegrityError:
        raise ShopError("category_exists") from None
    return cur.lastrowid


def list_categories(db: Database, include_inactive: bool = False):
    """Only categories that still have at least one sellable product are shown to customers."""
    if include_inactive:
        return db.all("SELECT * FROM categories ORDER BY name")
    return db.all(
        """SELECT c.* FROM categories c
           WHERE c.active = 1 AND EXISTS
                 (SELECT 1 FROM products p WHERE p.category_id = c.id AND p.active = 1)
           ORDER BY c.name"""
    )


def get_category(db: Database, category_id: int):
    return db.one("SELECT * FROM categories WHERE id = ?", (category_id,))


# --- products -------------------------------------------------------------

def add_product(db: Database, category_id: int, name: str, price_cents: int, stock: int,
                description: str = "", photo_file_id: str | None = None) -> int:
    name = name.strip()
    if not 2 <= len(name) <= 80:
        raise ShopError("bad_name_len")
    if price_cents < 0 or stock < 0:
        raise ShopError("bad_number")
    if get_category(db, category_id) is None:
        raise ShopError("not_found")
    cur = db.run(
        "INSERT INTO products(category_id, name, description, price_cents, stock, photo_file_id) "
        "VALUES (?,?,?,?,?,?)",
        (category_id, name, description.strip()[:600], price_cents, stock, photo_file_id),
    )
    return cur.lastrowid


def get_product(db: Database, product_id: int):
    return db.one("SELECT * FROM products WHERE id = ?", (product_id,))


def list_products(db: Database, category_id: int | None = None, page: int = 0,
                  include_inactive: bool = False):
    where, params = [], []
    if category_id is not None:
        where.append("category_id = ?")
        params.append(category_id)
    if not include_inactive:
        where.append("active = 1")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.one(f"SELECT COUNT(*) AS n FROM products {clause}", tuple(params))["n"]
    page = max(0, min(page, max(0, (total - 1) // PAGE_SIZE)))
    rows = db.all(
        f"SELECT * FROM products {clause} ORDER BY id LIMIT ? OFFSET ?",
        tuple(params) + (PAGE_SIZE, page * PAGE_SIZE),
    )
    return rows, total, page


def search_products(db: Database, query: str, limit: int = 10):
    query = query.strip()
    if len(query) < 2:
        raise ShopError("search_short")
    like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return db.all(
        "SELECT * FROM products WHERE active = 1 AND "
        "(name LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\') ORDER BY name LIMIT ?",
        (like, like, limit),
    )


def set_stock(db: Database, product_id: int, stock: int) -> None:
    if stock < 0:
        raise ShopError("bad_number")
    _must_update(db.run("UPDATE products SET stock = ? WHERE id = ?", (stock, product_id)))


def set_price(db: Database, product_id: int, price_cents: int) -> None:
    if price_cents < 0:
        raise ShopError("bad_number")
    _must_update(db.run("UPDATE products SET price_cents = ? WHERE id = ?", (price_cents, product_id)))


def toggle_active(db: Database, product_id: int) -> bool:
    _must_update(db.run("UPDATE products SET active = 1 - active WHERE id = ?", (product_id,)))
    return bool(get_product(db, product_id)["active"])


def _must_update(cur) -> None:
    if cur.rowcount == 0:
        raise ShopError("not_found")
