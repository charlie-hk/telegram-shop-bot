"""Shopping cart and coupons."""
from __future__ import annotations

from .db import Database
from .errors import ShopError


def add_item(db: Database, user_id: int, product_id: int, delta: int = 1) -> int:
    """Change a line by `delta`. Returns the new quantity (0 = line removed).

    Raises out_of_stock / max_qty so the UI can tell the user why nothing changed.
    """
    product = db.one("SELECT * FROM products WHERE id = ? AND active = 1", (product_id,))
    if product is None:
        raise ShopError("not_found")
    row = db.one("SELECT qty FROM cart_items WHERE user_id = ? AND product_id = ?", (user_id, product_id))
    current = row["qty"] if row else 0
    new = current + delta
    if delta > 0:
        if product["stock"] <= 0:
            raise ShopError("out_of_stock")
        if new > product["stock"]:
            raise ShopError("max_qty", stock=product["stock"])
    if new <= 0:
        db.run("DELETE FROM cart_items WHERE user_id = ? AND product_id = ?", (user_id, product_id))
        return 0
    db.run(
        "INSERT INTO cart_items(user_id, product_id, qty) VALUES (?,?,?) "
        "ON CONFLICT(user_id, product_id) DO UPDATE SET qty = excluded.qty",
        (user_id, product_id, new),
    )
    return new


def items(db: Database, user_id: int):
    return db.all(
        """SELECT p.id AS product_id, p.name, p.price_cents, p.stock, p.active, c.qty
           FROM cart_items c JOIN products p ON p.id = c.product_id
           WHERE c.user_id = ? ORDER BY p.name""",
        (user_id,),
    )


def clear(db: Database, user_id: int) -> None:
    db.run("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    db.run("DELETE FROM cart_coupons WHERE user_id = ?", (user_id,))


# --- coupons --------------------------------------------------------------

def create_coupon(db: Database, code: str, percent: int, max_uses: int) -> None:
    code = code.strip().upper()
    if not (3 <= len(code) <= 20 and code.isalnum()):
        raise ShopError("bad_coupon_code")
    if not 1 <= percent <= 90 or max_uses < 1:
        raise ShopError("bad_number")
    db.run(
        "INSERT INTO coupons(code, percent, max_uses) VALUES (?,?,?) "
        "ON CONFLICT(code) DO UPDATE SET percent = excluded.percent, "
        "max_uses = excluded.max_uses, active = 1",
        (code, percent, max_uses),
    )


def apply_coupon(db: Database, user_id: int, code: str) -> int:
    """Attach a coupon to the cart. Returns the percentage."""
    code = code.strip().upper()
    row = db.one("SELECT * FROM coupons WHERE code = ?", (code,))
    if row is None or not row["active"] or row["used"] >= row["max_uses"]:
        raise ShopError("coupon_bad")
    db.run(
        "INSERT INTO cart_coupons(user_id, code) VALUES (?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET code = excluded.code",
        (user_id, code),
    )
    return row["percent"]


def remove_coupon(db: Database, user_id: int) -> None:
    db.run("DELETE FROM cart_coupons WHERE user_id = ?", (user_id,))


def summary(db: Database, user_id: int) -> dict:
    """Lines, subtotal, discount and total for the current cart (all integer cents)."""
    lines = items(db, user_id)
    subtotal = sum(r["price_cents"] * r["qty"] for r in lines)
    code, percent = None, 0
    row = db.one(
        "SELECT c.code, c.percent, c.used, c.max_uses, c.active FROM cart_coupons k "
        "JOIN coupons c ON c.code = k.code WHERE k.user_id = ?",
        (user_id,),
    )
    if row and row["active"] and row["used"] < row["max_uses"]:
        code, percent = row["code"], row["percent"]
    discount = subtotal * percent // 100
    return {
        "lines": lines,
        "subtotal": subtotal,
        "coupon": code,
        "percent": percent,
        "discount": discount,
        "total": subtotal - discount,
        "problems": [r for r in lines if (not r["active"]) or r["qty"] > r["stock"]],
    }
