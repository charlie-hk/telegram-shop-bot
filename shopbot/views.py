"""Screens: pure functions that turn data into (text, inline keyboard).

All user-supplied strings go through `esc()` because messages are sent with parse_mode=HTML.
Callback data is kept far below Telegram's 64-byte limit.
"""
from __future__ import annotations

import html

from . import cart as cart_svc
from . import catalog, orders
from .db import Database
from .i18n import LANGUAGES, t

esc = html.escape
Keyboard = dict


def btn(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def kb(*rows) -> Keyboard:
    return {"inline_keyboard": [list(r) for r in rows if r]}


def money(cents: int, currency: str) -> str:
    return catalog.format_money(cents, currency)


def _pager(prefix: str, page: int, total: int, lang: str, size: int = catalog.PAGE_SIZE):
    last = max(0, (total - 1) // size)
    row = []
    if page > 0:
        row.append(btn(t(lang, "btn_prev"), f"{prefix}:{page - 1}"))
    if page < last:
        row.append(btn(t(lang, "btn_next"), f"{prefix}:{page + 1}"))
    return row


# --- customer screens -----------------------------------------------------

def language_picker():
    rows = [[btn(name, f"lng:{code}")] for code, name in LANGUAGES.items()]
    text = "🌐 " + " · ".join(t(code, "choose_lang").rstrip(":") for code in LANGUAGES)
    return text, kb(*rows)


def main_menu(lang: str, shop: str | None = None):
    text = t(lang, "welcome", shop=esc(shop)) if shop else t(lang, "menu_title")
    return text, kb(
        [btn(t(lang, "btn_catalog"), "cats"), btn(t(lang, "btn_cart"), "cart")],
        [btn(t(lang, "btn_orders"), "ords:0"), btn(t(lang, "btn_search"), "srch")],
        [btn(t(lang, "btn_lang"), "lang"), btn(t(lang, "btn_help"), "help")],
    )


def back_to_menu(lang: str, text: str):
    return text, kb([btn(t(lang, "btn_menu"), "m")])


def categories(db: Database, lang: str):
    cats = catalog.list_categories(db)
    if not cats:
        return back_to_menu(lang, t(lang, "no_categories"))
    rows = [[btn(c["name"], f"cat:{c['id']}:0")] for c in cats]
    rows.append([btn(t(lang, "btn_menu"), "m")])
    return t(lang, "categories_title"), kb(*rows)


def product_list(db: Database, lang: str, category_id: int, page: int, currency: str):
    cat = catalog.get_category(db, category_id)
    if cat is None:
        return back_to_menu(lang, t(lang, "not_found"))
    rows_, total, page = catalog.list_products(db, category_id, page)
    if not rows_:
        return t(lang, "products_title", category=esc(cat["name"])) + "\n\n" + t(lang, "no_products"), \
            kb([btn(t(lang, "btn_back"), "cats")])
    rows = []
    for p in rows_:
        label = f"{p['name']} — {money(p['price_cents'], currency)}"
        if p["stock"] <= 0:
            label += " ✖"
        rows.append([btn(label, f"p:{p['id']}")])
    rows.append(_pager(f"cat:{category_id}", page, total, lang))
    rows.append([btn(t(lang, "btn_back"), "cats"), btn(t(lang, "btn_menu"), "m")])
    return t(lang, "products_title", category=esc(cat["name"])), kb(*rows)


def product_page(db: Database, lang: str, product_id: int, currency: str):
    """Returns (text, keyboard, photo_file_id or None)."""
    p = catalog.get_product(db, product_id)
    if p is None or not p["active"]:
        text, keyboard = back_to_menu(lang, t(lang, "not_found"))
        return text, keyboard, None
    stock = t(lang, "in_stock", n=p["stock"]) if p["stock"] > 0 else t(lang, "out_of_stock_label")
    text = f"<b>{esc(p['name'])}</b>\n{money(p['price_cents'], currency)}\n"
    if p["description"]:
        text += f"\n{esc(p['description'])}\n"
    text += f"\n{stock}"
    rows = []
    if p["stock"] > 0:
        rows.append([btn(t(lang, "btn_add"), f"add:{p['id']}")])
    rows.append([btn(t(lang, "btn_view_cart"), "cart")])
    rows.append([btn(t(lang, "btn_back"), f"cat:{p['category_id']}:0"), btn(t(lang, "btn_menu"), "m")])
    return text, kb(*rows), p["photo_file_id"]


def cart_view(db: Database, lang: str, user_id: int, currency: str):
    s = cart_svc.summary(db, user_id)
    if not s["lines"]:
        return back_to_menu(lang, t(lang, "cart_empty"))
    lines = [t(lang, "cart_title"), ""]
    for r in s["lines"]:
        lines.append(f"• {esc(r['name'])} × {r['qty']} — {money(r['price_cents'] * r['qty'], currency)}")
    lines.append("")
    lines.append(f"{t(lang, 'subtotal')}: {money(s['subtotal'], currency)}")
    if s["coupon"]:
        lines.append(f"{t(lang, 'discount', code=esc(s['coupon']), percent=s['percent'])}: "
                     f"-{money(s['discount'], currency)}")
    lines.append(f"<b>{t(lang, 'total')}: {money(s['total'], currency)}</b>")
    if s["problems"]:
        lines += ["", "⚠️ " + t(lang, "cart_problem")]
    rows = []
    for r in s["lines"]:
        rows.append([
            btn("➖", f"cq:{r['product_id']}:-"),
            btn(f"{r['name'][:20]} × {r['qty']}", f"p:{r['product_id']}"),
            btn("➕", f"cq:{r['product_id']}:+"),
        ])
    rows.append([btn(t(lang, "btn_remove_coupon") if s["coupon"] else t(lang, "btn_coupon"),
                     "cpx" if s["coupon"] else "cpn")])
    rows.append([btn(t(lang, "btn_checkout"), "chk"), btn(t(lang, "btn_clear"), "cx")])
    rows.append([btn(t(lang, "btn_menu"), "m")])
    return "\n".join(lines), kb(*rows)


def payment_picker(lang: str):
    return t(lang, "choose_payment"), kb(
        [btn(t(lang, "pay_cod"), "pay:cod")],
        [btn(t(lang, "pay_bank"), "pay:bank")],
        [btn(t(lang, "btn_cancel"), "co_cancel")],
    )


def checkout_confirm(db: Database, lang: str, user_id: int, data: dict, currency: str):
    s = cart_svc.summary(db, user_id)
    lines = [t(lang, "confirm_title"), ""]
    for r in s["lines"]:
        lines.append(f"• {esc(r['name'])} × {r['qty']} — {money(r['price_cents'] * r['qty'], currency)}")
    lines.append("")
    if s["coupon"]:
        lines.append(f"{t(lang, 'discount', code=esc(s['coupon']), percent=s['percent'])}: "
                     f"-{money(s['discount'], currency)}")
    lines.append(f"<b>{t(lang, 'total')}: {money(s['total'], currency)}</b>")
    lines += ["", f"👤 {esc(data['name'])}", f"📱 {esc(data['phone'])}", f"📍 {esc(data['address'])}",
              f"💳 {t(lang, 'pay_' + data['pay'] + '_short')}"]
    return "\n".join(lines), kb(
        [btn(t(lang, "btn_confirm"), "ok")],
        [btn(t(lang, "btn_cancel"), "co_cancel")],
    )


def orders_list(db: Database, lang: str, user_id: int, page: int, currency: str):
    rows_, total, page = orders.list_orders(db, user_id=user_id, page=page)
    if not rows_:
        return back_to_menu(lang, t(lang, "no_orders"))
    rows = [[btn(f"#{o['id']} · {t(lang, 'st_' + o['status'])} · {money(o['total_cents'], currency)}",
                 f"o:{o['id']}")] for o in rows_]
    rows.append(_pager("ords", page, total, lang))
    rows.append([btn(t(lang, "btn_menu"), "m")])
    return t(lang, "orders_title"), kb(*rows)


def order_detail(db: Database, lang: str, order_id: int, currency: str, admin: bool = False):
    data = orders.get_order(db, order_id)
    if data is None:
        return back_to_menu(lang, t(lang, "not_found"))
    o = data["order"]
    lines = [f"<b>{t(lang, 'order_label', id=o['id'])}</b>", ""]
    for r in data["lines"]:
        lines.append(f"• {esc(r['name'])} × {r['qty']} — {money(r['unit_price_cents'] * r['qty'], currency)}")
    lines.append("")
    if o["coupon_code"]:
        lines.append(f"🏷 {esc(o['coupon_code'])}: -{money(o['discount_cents'], currency)}")
    lines.append(f"<b>{t(lang, 'total')}: {money(o['total_cents'], currency)}</b>")
    lines += ["",
              f"{t(lang, 'order_status')}: {t(lang, 'st_' + o['status'])}",
              f"{t(lang, 'order_date')}: {o['created_at']}",
              f"{t(lang, 'order_payment')}: {t(lang, 'pay_' + o['payment_method'] + '_short')}",
              f"{t(lang, 'order_address')}: {esc(o['address'])}"]
    if admin:
        lines += [f"👤 {esc(o['customer_name'])}", f"📱 {esc(o['phone'])}", f"🆔 user {o['user_id']}"]
    return "\n".join(lines), o


def customer_order_view(db: Database, lang: str, order_id: int, currency: str):
    text, o = order_detail(db, lang, order_id, currency)
    if isinstance(o, dict):  # not found -> keyboard dict returned
        return text, o
    rows = []
    if o["status"] == "new":
        rows.append([btn(t(lang, "btn_cancel_order"), f"oc:{o['id']}")])
    rows.append([btn(t(lang, "btn_back"), "ords:0"), btn(t(lang, "btn_menu"), "m")])
    return text, kb(*rows)


# --- admin screens (English only) ----------------------------------------

def admin_menu():
    return "<b>Admin panel</b>", kb(
        [btn("📦 Orders", "a_ord:all:0"), btn("🧺 Products", "a_prod:0")],
        [btn("➕ New product", "a_np"), btn("🗂 New category", "a_nc")],
        [btn("🏷 Coupon", "a_cpn"), btn("📊 Stats", "a_stats")],
        [btn("📣 Broadcast", "a_bc"), btn("📤 Export CSV", "a_exp")],
        [btn("🏠 Shop menu", "m")],
    )


def admin_orders(db: Database, status: str, page: int, currency: str):
    st = None if status == "all" else status
    rows_, total, page = orders.list_orders(db, status=st, page=page)
    filters = [btn(("• " if status == s else "") + s, f"a_ord:{s}:0") for s in ("all",) + orders.STATUSES[:3]]
    filters2 = [btn(("• " if status == s else "") + s, f"a_ord:{s}:0") for s in orders.STATUSES[3:]]
    rows = [filters, filters2]
    for o in rows_:
        rows.append([btn(f"#{o['id']} {o['status']} {money(o['total_cents'], currency)} {o['customer_name'][:16]}",
                         f"a_o:{o['id']}")])
    rows.append(_pager(f"a_ord:{status}", page, total, "en"))
    rows.append([btn("⬅️ Admin", "a")])
    return f"<b>Orders</b> ({total})", kb(*rows)


def admin_order(db: Database, order_id: int, currency: str):
    text, o = order_detail(db, "en", order_id, currency, admin=True)
    if isinstance(o, dict):
        return text, o
    rows = [[btn(f"→ {s}", f"a_st:{o['id']}:{s}") for s in orders.TRANSITIONS[o["status"]]]]
    rows.append([btn("⬅️ Orders", "a_ord:all:0")])
    return text, kb(*rows)


def admin_products(db: Database, page: int, currency: str):
    rows_, total, page = catalog.list_products(db, None, page, include_inactive=True)
    rows = []
    for p in rows_:
        flag = "" if p["active"] else " (hidden)"
        rows.append([btn(f"#{p['id']} {p['name'][:24]} · {money(p['price_cents'], currency)} · "
                         f"stock {p['stock']}{flag}", f"a_p:{p['id']}")])
    rows.append(_pager("a_prod", page, total, "en"))
    rows.append([btn("⬅️ Admin", "a")])
    return f"<b>Products</b> ({total})", kb(*rows)


def admin_product(db: Database, product_id: int, currency: str):
    p = catalog.get_product(db, product_id)
    if p is None:
        return "Product not found.", kb([btn("⬅️ Products", "a_prod:0")])
    cat = catalog.get_category(db, p["category_id"])
    text = (f"<b>#{p['id']} {esc(p['name'])}</b>\nCategory: {esc(cat['name'])}\n"
            f"Price: {money(p['price_cents'], currency)}\nStock: {p['stock']}\n"
            f"Visible: {'yes' if p['active'] else 'no'}")
    return text, kb(
        [btn("📦 Stock", f"a_stk:{p['id']}"), btn("💲 Price", f"a_prc:{p['id']}")],
        [btn("🙈 Hide" if p["active"] else "👁 Show", f"a_tg:{p['id']}")],
        [btn("⬅️ Products", "a_prod:0")],
    )


def admin_stats(db: Database, currency: str):
    s = orders.stats(db)
    lines = ["<b>Stats</b>", f"Customers: {s['customers']}", f"Revenue (excluding cancelled): "
             f"{money(s['revenue'], currency)}", "", "<b>Orders</b>"]
    lines += [f"{name}: {n}" for name, n in s["counts"].items()]
    if s["top"]:
        lines += ["", "<b>Top sellers</b>"] + [f"{esc(r['name'])}: {r['sold']}" for r in s["top"]]
    if s["low_stock"]:
        lines += ["", "<b>Low stock</b>"] + [f"#{r['id']} {esc(r['name'])}: {r['stock']}" for r in s["low_stock"]]
    return "\n".join(lines), kb([btn("⬅️ Admin", "a")])
