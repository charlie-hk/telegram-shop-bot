"""Orders: creation from a cart, status workflow, reporting."""
from __future__ import annotations

import csv
import io

from . import cart
from .db import Database
from .errors import ShopError

STATUSES = ("new", "confirmed", "shipped", "delivered", "cancelled")
TRANSITIONS = {
    "new": ("confirmed", "cancelled"),
    "confirmed": ("shipped", "cancelled"),
    "shipped": ("delivered",),
    "delivered": (),
    "cancelled": (),
}
PAYMENT_METHODS = ("cod", "bank")
COUNTED_AS_SALES = ("new", "confirmed", "shipped", "delivered")


def create_order(db: Database, user_id: int, name: str, phone: str, address: str,
                 payment_method: str) -> int:
    """Turn the cart into an order atomically.

    Stock is re-checked and decremented inside one IMMEDIATE transaction, so two
    customers can never both buy the last unit.
    """
    if payment_method not in PAYMENT_METHODS:
        raise ShopError("bad_payment")
    with db.transaction():
        summ = cart.summary(db, user_id)
        if not summ["lines"]:
            raise ShopError("cart_empty")
        if summ["problems"]:
            raise ShopError("stock_changed")
        cur = db.run(
            """INSERT INTO orders(user_id, customer_name, phone, address, payment_method,
                                  coupon_code, subtotal_cents, discount_cents, total_cents)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, name, phone, address, payment_method, summ["coupon"],
             summ["subtotal"], summ["discount"], summ["total"]),
        )
        order_id = cur.lastrowid
        for line in summ["lines"]:
            db.run(
                "INSERT INTO order_items(order_id, product_id, name, unit_price_cents, qty) VALUES (?,?,?,?,?)",
                (order_id, line["product_id"], line["name"], line["price_cents"], line["qty"]),
            )
            db.run("UPDATE products SET stock = stock - ? WHERE id = ?", (line["qty"], line["product_id"]))
        if summ["coupon"]:
            db.run("UPDATE coupons SET used = used + 1 WHERE code = ?", (summ["coupon"],))
        db.run("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
        db.run("DELETE FROM cart_coupons WHERE user_id = ?", (user_id,))
    return order_id


def get_order(db: Database, order_id: int):
    order = db.one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if order is None:
        return None
    lines = db.all("SELECT * FROM order_items WHERE order_id = ? ORDER BY rowid", (order_id,))
    return {"order": order, "lines": lines}


def list_orders(db: Database, user_id: int | None = None, status: str | None = None,
                page: int = 0, page_size: int = 5):
    where, params = [], []
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    if status:
        where.append("status = ?")
        params.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.one(f"SELECT COUNT(*) AS n FROM orders {clause}", tuple(params))["n"]
    page = max(0, min(page, max(0, (total - 1) // page_size)))
    rows = db.all(
        f"SELECT * FROM orders {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        tuple(params) + (page_size, page * page_size),
    )
    return rows, total, page


def set_status(db: Database, order_id: int, new_status: str):
    """Move an order along the workflow. Cancelling puts the stock (and coupon use) back."""
    if new_status not in STATUSES:
        raise ShopError("bad_status")
    with db.transaction():
        order = db.one("SELECT * FROM orders WHERE id = ?", (order_id,))
        if order is None:
            raise ShopError("not_found")
        if new_status not in TRANSITIONS[order["status"]]:
            raise ShopError("bad_transition", old=order["status"], new=new_status)
        if new_status == "cancelled":
            for line in db.all("SELECT * FROM order_items WHERE order_id = ?", (order_id,)):
                db.run("UPDATE products SET stock = stock + ? WHERE id = ?", (line["qty"], line["product_id"]))
            if order["coupon_code"]:
                db.run("UPDATE coupons SET used = MAX(used - 1, 0) WHERE code = ?", (order["coupon_code"],))
        db.run("UPDATE orders SET status = ?, updated_at = datetime('now') WHERE id = ?", (new_status, order_id))
    return db.one("SELECT * FROM orders WHERE id = ?", (order_id,))


def cancel_by_customer(db: Database, order_id: int, user_id: int):
    order = db.one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if order is None or order["user_id"] != user_id:
        raise ShopError("not_found")
    if order["status"] != "new":
        raise ShopError("cancel_not_allowed")
    return set_status(db, order_id, "cancelled")


def stats(db: Database) -> dict:
    counts = {s: 0 for s in STATUSES}
    for row in db.all("SELECT status, COUNT(*) AS n FROM orders GROUP BY status"):
        counts[row["status"]] = row["n"]
    marks = ",".join("?" * len(COUNTED_AS_SALES))
    revenue = db.one(
        f"SELECT COALESCE(SUM(total_cents), 0) AS s FROM orders WHERE status IN ({marks})",
        COUNTED_AS_SALES,
    )["s"]
    top = db.all(
        f"""SELECT i.name, SUM(i.qty) AS sold FROM order_items i JOIN orders o ON o.id = i.order_id
            WHERE o.status IN ({marks}) GROUP BY i.product_id, i.name ORDER BY sold DESC, i.name LIMIT 3""",
        COUNTED_AS_SALES,
    )
    customers = db.one("SELECT COUNT(*) AS n FROM users")["n"]
    low = db.all("SELECT id, name, stock FROM products WHERE active = 1 AND stock <= 3 ORDER BY stock, name LIMIT 5")
    return {"counts": counts, "revenue": revenue, "top": top, "customers": customers, "low_stock": low}


def export_csv(db: Database) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["order_id", "created_at", "status", "customer", "phone", "address",
                     "payment", "coupon", "subtotal", "discount", "total", "items"])
    for o in db.all("SELECT * FROM orders ORDER BY id"):
        items = "; ".join(
            f"{r['qty']} x {r['name']}"
            for r in db.all("SELECT * FROM order_items WHERE order_id = ? ORDER BY rowid", (o["id"],))
        )
        writer.writerow([
            o["id"], o["created_at"], o["status"], _csv_safe(o["customer_name"]), o["phone"],
            _csv_safe(o["address"]), o["payment_method"], o["coupon_code"] or "",
            f"{o['subtotal_cents'] / 100:.2f}", f"{o['discount_cents'] / 100:.2f}",
            f"{o['total_cents'] / 100:.2f}", _csv_safe(items),
        ])
    return out.getvalue()


def _csv_safe(value: str) -> str:
    """Stop spreadsheet formula injection: customer text that starts with = + - @ gets a quote."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value
