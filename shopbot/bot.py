"""Update routing: commands, buttons, checkout and admin flows."""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from . import cart as cart_svc
from . import catalog, orders, views
from .api import TelegramAPI, TelegramError
from .config import Config
from .db import Database
from .errors import ShopError
from .i18n import DEFAULT_LANG, LANGUAGES, t

log = logging.getLogger("shopbot")

BANNER = Path(__file__).parent / "assets" / "banner.png"
PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()\-]{6,19}$")
REMOVE_KB = {"remove_keyboard": True}
ADMIN_ERRORS = {
    "bad_number": "That number is not valid.",
    "bad_name_len": "The name must be 2–80 characters (categories: 2–40).",
    "category_exists": "That category already exists.",
    "not_found": "Not found.",
    "bad_coupon_code": "Coupon code: 3–20 letters or digits.",
    "bad_transition": "That status change is not allowed from the current status.",
}


class Bot:
    def __init__(self, api: TelegramAPI, db: Database, config: Config):
        self.api, self.db, self.cfg = api, db, config

    # ------------------------------------------------------------------ entry

    def handle_update(self, update: dict) -> None:
        """Never raises: one bad update must not stop the polling loop."""
        chat_id = None
        try:
            if "callback_query" in update:
                chat_id = (update["callback_query"].get("message") or {}).get("chat", {}).get("id")
                self._on_callback(update["callback_query"])
            elif "message" in update:
                chat_id = update["message"]["chat"]["id"]
                self._on_message(update["message"])
        except TelegramError as exc:
            log.warning("Telegram error: %s", exc)
        except Exception:  # noqa: BLE001
            log.exception("Unhandled error for update %s", update.get("update_id"))
            if chat_id:
                try:
                    self.api.send_message(chat_id, t(DEFAULT_LANG, "error_generic"))
                except TelegramError:
                    pass

    def run_polling(self) -> None:  # pragma: no cover - needs the real network
        offset = None
        backoff = 1
        log.info("Polling started")
        while True:
            try:
                for upd in self.api.get_updates(offset=offset):
                    offset = upd["update_id"] + 1
                    self.handle_update(upd)
                backoff = 1
            except TelegramError as exc:
                log.warning("getUpdates failed: %s (retry in %ss)", exc, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
            except KeyboardInterrupt:
                log.info("Stopped")
                return

    # ------------------------------------------------------------------ users

    def _ensure_user(self, frm: dict):
        row = self.db.one("SELECT * FROM users WHERE id = ?", (frm["id"],))
        if row is None:
            self.db.run("INSERT INTO users(id, username, first_name, lang, state) VALUES (?,?,?,?,?)",
                        (frm["id"], frm.get("username"), frm.get("first_name", ""), DEFAULT_LANG, "new"))
            row = self.db.one("SELECT * FROM users WHERE id = ?", (frm["id"],))
        return row

    def _user(self, uid: int):
        return self.db.one("SELECT * FROM users WHERE id = ?", (uid,))

    def _set_state(self, uid: int, state: str = "", **data) -> None:
        self.db.run("UPDATE users SET state = ?, state_data = ? WHERE id = ?", (state, json.dumps(data), uid))

    def _state(self, user) -> tuple[str, dict]:
        try:
            return user["state"], json.loads(user["state_data"] or "{}")
        except ValueError:
            return "", {}

    def _is_admin(self, uid: int) -> bool:
        return uid in self.cfg.admin_ids

    # --------------------------------------------------------------- sending

    def _send(self, chat_id, text, keyboard=None):
        return self.api.send_message(chat_id, text, reply_markup=keyboard)

    def _show(self, chat_id, message, text, keyboard=None, photo=None):
        """Edit the tapped message in place when possible, otherwise replace it."""
        had_photo = bool(message and message.get("photo"))
        if photo:
            self._delete(chat_id, message)
            try:
                return self.api.send_photo(chat_id, photo, text, reply_markup=keyboard)
            except TelegramError:  # stale file id: fall back to text so the product is still visible
                return self._send(chat_id, text, keyboard)
        if message and not had_photo:
            try:
                return self.api.edit_message_text(chat_id, message["message_id"], text, reply_markup=keyboard)
            except TelegramError as exc:
                if "not modified" in exc.description.lower():
                    return None
        else:
            self._delete(chat_id, message)
        return self._send(chat_id, text, keyboard)

    def _delete(self, chat_id, message) -> None:
        if message:
            try:
                self.api.delete_message(chat_id, message["message_id"])
            except TelegramError:
                pass

    def _meta_get(self, key: str):
        row = self.db.one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def _meta_set(self, key: str, value: str) -> None:
        self.db.run("INSERT INTO meta(key, value) VALUES (?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def _send_banner(self, chat_id, caption, keyboard=None):
        """Welcome screen: the banner picture with the text as caption.

        The first send uploads the file; Telegram's file_id is cached so later sends are instant.
        Falls back to plain text if the picture is missing or Telegram refuses it.
        """
        file_id = self._meta_get("banner_file_id")
        if file_id:
            try:
                return self.api.send_photo(chat_id, file_id, caption, reply_markup=keyboard)
            except TelegramError:
                pass  # stale id: upload again below
        if BANNER.is_file():
            try:
                msg = self.api.send_photo_file(chat_id, BANNER.name, BANNER.read_bytes(), caption, keyboard)
                self._meta_set("banner_file_id", msg["photo"][-1]["file_id"])
                return msg
            except (TelegramError, KeyError, IndexError) as exc:
                log.warning("Banner upload failed, using text: %s", exc)
        return self._send(chat_id, caption, keyboard)

    def _error_text(self, lang: str, exc: ShopError) -> str:
        return t(lang, exc.code, **exc.params)

    # -------------------------------------------------------------- messages

    def _on_message(self, msg: dict) -> None:
        if msg.get("chat", {}).get("type") != "private" or "from" not in msg:
            return
        user = self._ensure_user(msg["from"])
        uid, chat_id, lang = user["id"], msg["chat"]["id"], user["lang"]
        text = (msg.get("text") or "").strip()

        if text.startswith("/"):
            command = text.split()[0].split("@")[0].lower()
            return self._on_command(command, user, chat_id)

        state, data = self._state(user)
        if state == "co_phone" and msg.get("contact"):
            if msg["contact"].get("user_id") != uid:  # only the sender's own number
                return self._send(chat_id, t(lang, "bad_phone"))
            text = msg["contact"]["phone_number"]
        if state == "a_p_photo" and msg.get("photo") and self._is_admin(uid):
            return self._admin_new_product_finish(user, chat_id, data, photo=msg["photo"][-1]["file_id"])
        if state == "new":
            return self._send(chat_id, *views.language_picker())
        if not state:
            return self._send(chat_id, *views.back_to_menu(lang, t(lang, "unknown")))
        if not text:
            return None
        return self._on_state_text(user, chat_id, state, data, text)

    def _on_command(self, command: str, user, chat_id) -> None:
        uid, lang = user["id"], user["lang"]
        if command == "/start":
            if user["state"] == "new":
                self._set_state(uid, "")
                return self._send_banner(chat_id, *views.language_picker())
            self._set_state(uid, "")
            return self._send_banner(chat_id, *views.main_menu(lang, self.cfg.shop_name))
        if user["state"] == "new":  # language not chosen yet
            return self._send(chat_id, *views.language_picker())
        if command == "/cancel":
            self._set_state(uid, "")
            self.api.send_message(chat_id, t(lang, "flow_cancelled"), reply_markup=REMOVE_KB)
            return self._send(chat_id, *views.main_menu(lang))
        if command == "/menu":
            self._set_state(uid, "")
            return self._send(chat_id, *views.main_menu(lang))
        if command == "/help":
            return self._send(chat_id, *views.back_to_menu(lang, t(lang, "help_text")))
        if command == "/admin" and self._is_admin(uid):
            self._set_state(uid, "")
            return self._send(chat_id, *views.admin_menu())
        return self._send(chat_id, *views.back_to_menu(lang, t(lang, "unknown")))

    # ----------------------------------------------------- text in a state

    def _on_state_text(self, user, chat_id, state: str, data: dict, text: str) -> None:
        uid, lang = user["id"], user["lang"]
        cur = self.cfg.currency
        if state == "co_name":
            if not 2 <= len(text) <= 60:
                return self._send(chat_id, t(lang, "bad_name"))
            self._set_state(uid, "co_phone", name=text)
            keyboard = {"keyboard": [[{"text": t(lang, "btn_share_phone"), "request_contact": True}]],
                        "resize_keyboard": True, "one_time_keyboard": True}
            return self._send(chat_id, t(lang, "ask_phone"), keyboard)
        if state == "co_phone":
            if not PHONE_RE.match(text):
                return self._send(chat_id, t(lang, "bad_phone"))
            self._set_state(uid, "co_addr", name=data["name"], phone=text)
            return self.api.send_message(chat_id, t(lang, "ask_addr"), reply_markup=REMOVE_KB)
        if state == "co_addr":
            if not 5 <= len(text) <= 300:
                return self._send(chat_id, t(lang, "bad_addr"))
            self._set_state(uid, "co_pay", name=data["name"], phone=data["phone"], address=text)
            return self._send(chat_id, *views.payment_picker(lang))
        if state == "search":
            self._set_state(uid, "")
            try:
                found = catalog.search_products(self.db, text)
            except ShopError as exc:
                self._set_state(uid, "search")
                return self._send(chat_id, self._error_text(lang, exc))
            if not found:
                return self._send(chat_id, *views.back_to_menu(lang, t(lang, "search_none", q=views.esc(text))))
            rows = [[views.btn(f"{p['name']} — {catalog.format_money(p['price_cents'], cur)}", f"p:{p['id']}")]
                    for p in found]
            rows.append([views.btn(t(lang, "btn_menu"), "m")])
            return self._send(chat_id, t(lang, "search_results", q=views.esc(text)), views.kb(*rows))
        if state == "coupon":
            self._set_state(uid, "")
            try:
                percent = cart_svc.apply_coupon(self.db, uid, text)
                self._send(chat_id, t(lang, "coupon_ok", percent=percent))
            except ShopError as exc:
                self._send(chat_id, self._error_text(lang, exc))
            return self._send(chat_id, *views.cart_view(self.db, lang, uid, cur))
        if state.startswith("a_") and self._is_admin(uid):
            return self._on_admin_state_text(user, chat_id, state, data, text)
        self._set_state(uid, "")
        return self._send(chat_id, *views.main_menu(lang))

    # ------------------------------------------------------------- callbacks

    def _on_callback(self, cq: dict) -> None:
        frm, message, data = cq["from"], cq.get("message"), cq.get("data", "")
        user = self._ensure_user(frm)
        uid, lang = user["id"], user["lang"]
        chat_id = message["chat"]["id"] if message else uid
        cur = self.cfg.currency
        parts = data.split(":")
        action = parts[0]

        def answer(text=None, alert=False):
            try:
                self.api.answer_callback_query(cq["id"], text, alert)
            except TelegramError:
                pass

        if action.startswith("a") and (action == "a" or action.startswith("a_")):
            if not self._is_admin(uid):
                return answer("Not allowed", True)
            answer()
            return self._on_admin_callback(user, chat_id, message, parts)

        if action == "lng":
            code = parts[1] if len(parts) > 1 else ""
            if code in LANGUAGES:
                self.db.run("UPDATE users SET lang = ? WHERE id = ?", (code, uid))
                if user["state"] == "new":
                    self._set_state(uid, "")
                answer(t(code, "lang_set"))
                self._delete(chat_id, message)
                return self._send_banner(chat_id, *views.main_menu(code, self.cfg.shop_name))
            return answer()
        if user["state"] == "new":  # never chose a language: ask first
            answer()
            return self._show(chat_id, message, *views.language_picker())

        answer_later = True
        if action == "m":
            self._set_state(uid, "")
            self._show(chat_id, message, *views.main_menu(lang))
        elif action == "help":
            self._show(chat_id, message, *views.back_to_menu(lang, t(lang, "help_text")))
        elif action == "lang":
            self._show(chat_id, message, *views.language_picker())
        elif action == "cats":
            self._show(chat_id, message, *views.categories(self.db, lang))
        elif action == "cat":
            self._show(chat_id, message, *views.product_list(self.db, lang, int(parts[1]), int(parts[2]), cur))
        elif action == "p":
            text, keyboard, photo = views.product_page(self.db, lang, int(parts[1]), cur)
            self._show(chat_id, message, text, keyboard, photo)
        elif action == "add":
            try:
                cart_svc.add_item(self.db, uid, int(parts[1]), 1)
                answer_later = False
                answer(t(lang, "added"))
            except ShopError as exc:
                answer_later = False
                answer(self._error_text(lang, exc), True)
        elif action == "cart":
            self._show(chat_id, message, *views.cart_view(self.db, lang, uid, cur))
        elif action == "cq":
            try:
                cart_svc.add_item(self.db, uid, int(parts[1]), 1 if parts[2] == "+" else -1)
            except ShopError as exc:
                answer_later = False
                answer(self._error_text(lang, exc), True)
            self._show(chat_id, message, *views.cart_view(self.db, lang, uid, cur))
        elif action == "cx":
            cart_svc.clear(self.db, uid)
            self._show(chat_id, message, *views.cart_view(self.db, lang, uid, cur))
        elif action == "cpn":
            self._set_state(uid, "coupon")
            self._send(chat_id, t(lang, "coupon_prompt"))
        elif action == "cpx":
            cart_svc.remove_coupon(self.db, uid)
            self._show(chat_id, message, *views.cart_view(self.db, lang, uid, cur))
        elif action == "chk":
            summ = cart_svc.summary(self.db, uid)
            if not summ["lines"]:
                answer_later = False
                answer(t(lang, "cart_empty"), True)
            elif summ["problems"]:
                answer_later = False
                answer(t(lang, "cart_problem"), True)
            else:
                self._set_state(uid, "co_name")
                self._send(chat_id, t(lang, "ask_name"))
        elif action == "pay":
            state, sdata = self._state(user)
            if state == "co_pay" and parts[1] in orders.PAYMENT_METHODS:
                sdata["pay"] = parts[1]
                self._set_state(uid, "co_confirm", **sdata)
                self._show(chat_id, message, *views.checkout_confirm(self.db, lang, uid, sdata, cur))
        elif action == "co_cancel":
            self._set_state(uid, "")
            self._show(chat_id, message, *views.main_menu(lang))
        elif action == "ok":
            self._place_order(user, chat_id, message)
        elif action == "ords":
            self._show(chat_id, message, *views.orders_list(self.db, lang, uid, int(parts[1]), cur))
        elif action == "o":
            row = self.db.one("SELECT user_id FROM orders WHERE id = ?", (int(parts[1]),))
            if row and row["user_id"] == uid:
                self._show(chat_id, message, *views.customer_order_view(self.db, lang, int(parts[1]), cur))
            else:
                self._show(chat_id, message, *views.back_to_menu(lang, t(lang, "not_found")))
        elif action == "oc":
            try:
                orders.cancel_by_customer(self.db, int(parts[1]), uid)
                self._notify_admins(f"Order #{parts[1]} was cancelled by the customer.")
                answer_later = False
                answer(t(lang, "order_cancelled"))
            except ShopError as exc:
                answer_later = False
                answer(self._error_text(lang, exc), True)
            self._show(chat_id, message, *views.customer_order_view(self.db, lang, int(parts[1]), cur))
        elif action == "srch":
            self._set_state(uid, "search")
            self._send(chat_id, t(lang, "search_prompt"))
        if answer_later:
            answer()

    # ----------------------------------------------------------- order flow

    def _place_order(self, user, chat_id, message) -> None:
        uid, lang, cur = user["id"], user["lang"], self.cfg.currency
        state, data = self._state(user)
        if state != "co_confirm":
            return self._show(chat_id, message, *views.main_menu(lang))
        try:
            order_id = orders.create_order(self.db, uid, data["name"], data["phone"], data["address"], data["pay"])
        except ShopError as exc:
            self._set_state(uid, "")
            self._show(chat_id, message, *views.back_to_menu(lang, self._error_text(lang, exc)))
            return
        self._set_state(uid, "")
        text = t(lang, "order_placed", id=order_id)
        if data["pay"] == "bank":
            text += "\n\n" + t(lang, "bank_details", details=views.esc(self.cfg.bank_details), id=order_id)
        self._show(chat_id, message, *views.back_to_menu(lang, text))
        text_admin, _ = views.order_detail(self.db, "en", order_id, cur, admin=True)
        self._notify_admins("🆕 <b>New order</b>\n\n" + text_admin,
                            views.kb([views.btn("Open", f"a_o:{order_id}")]))

    def _notify_admins(self, text: str, keyboard=None) -> None:
        for admin_id in self.cfg.admin_ids:
            try:
                self._send(admin_id, text, keyboard)
            except TelegramError as exc:  # the admin may not have started the bot yet
                log.warning("Could not notify admin %s: %s", admin_id, exc)

    # ---------------------------------------------------------------- admin

    def _on_admin_callback(self, user, chat_id, message, parts: list) -> None:
        uid, cur = user["id"], self.cfg.currency
        action = parts[0]
        show = lambda *view: self._show(chat_id, message, *view)  # noqa: E731
        if action == "a":
            self._set_state(uid, "")
            show(*views.admin_menu())
        elif action == "a_ord":
            show(*views.admin_orders(self.db, parts[1], int(parts[2]), cur))
        elif action == "a_o":
            show(*views.admin_order(self.db, int(parts[1]), cur))
        elif action == "a_st":
            try:
                order = orders.set_status(self.db, int(parts[1]), parts[2])
            except ShopError as exc:
                self._send(chat_id, f"⚠️ {ADMIN_ERRORS.get(exc.code, exc.code)}")
            else:
                cust = self._user(order["user_id"])
                if cust:
                    self._try_send(cust["id"], t(cust["lang"], "status_notify", id=order["id"],
                                                 status=t(cust["lang"], "st_" + order["status"])))
            show(*views.admin_order(self.db, int(parts[1]), cur))
        elif action == "a_prod":
            show(*views.admin_products(self.db, int(parts[1]), cur))
        elif action == "a_p":
            show(*views.admin_product(self.db, int(parts[1]), cur))
        elif action == "a_tg":
            try:
                catalog.toggle_active(self.db, int(parts[1]))
            except ShopError:
                pass
            show(*views.admin_product(self.db, int(parts[1]), cur))
        elif action in ("a_stk", "a_prc"):
            self._set_state(uid, "a_stock" if action == "a_stk" else "a_price", pid=int(parts[1]))
            self._send(chat_id, "Send the new stock quantity:" if action == "a_stk"
                       else "Send the new price (example 12.50):")
        elif action == "a_nc":
            self._set_state(uid, "a_cat_name")
            self._send(chat_id, "Send the new category name:")
        elif action == "a_np":
            cats = catalog.list_categories(self.db, include_inactive=True)
            if not cats:
                self._set_state(uid, "a_cat_name")
                return self._send(chat_id, "Create a category first. Send its name:")
            rows = [[views.btn(c["name"], f"a_npc:{c['id']}")] for c in cats]
            rows.append([views.btn("⬅️ Admin", "a")])
            show("Pick a category for the new product:", views.kb(*rows))
        elif action == "a_npc":
            self._set_state(uid, "a_p_name", cat=int(parts[1]))
            self._send(chat_id, "Product name?")
        elif action == "a_cpn":
            self._set_state(uid, "a_coupon")
            self._send(chat_id, "Send: CODE PERCENT MAX_USES\nExample: WELCOME10 10 100")
        elif action == "a_stats":
            show(*views.admin_stats(self.db, cur))
        elif action == "a_bc":
            self._set_state(uid, "a_bcast")
            self._send(chat_id, "Send the message to broadcast to all customers (plain text):")
        elif action == "a_bcok":
            state, data = self._state(user)
            if state == "a_bc_confirm":
                self._set_state(uid, "")
                sent, failed = self._broadcast(data["text"])
                self._send(chat_id, f"Broadcast finished: {sent} delivered, {failed} failed.",
                           views.kb([views.btn("⬅️ Admin", "a")]))
        elif action == "a_exp":
            content = orders.export_csv(self.db).encode("utf-8-sig")
            self.api.send_document(chat_id, "orders.csv", content, caption="All orders")

    def _try_send(self, chat_id, text) -> bool:
        try:
            self._send(chat_id, text)
            return True
        except TelegramError:
            return False

    def _broadcast(self, text: str) -> tuple[int, int]:
        sent = failed = 0
        for row in self.db.all("SELECT id FROM users WHERE state != 'new'"):
            if self._try_send(row["id"], views.esc(text)):
                sent += 1
            else:
                failed += 1
            if self.cfg.broadcast_delay:
                time.sleep(self.cfg.broadcast_delay)
        return sent, failed

    def _on_admin_state_text(self, user, chat_id, state: str, data: dict, text: str) -> None:
        uid, cur = user["id"], self.cfg.currency
        back = views.kb([views.btn("⬅️ Admin", "a")])
        try:
            if state == "a_cat_name":
                catalog.add_category(self.db, text)
                self._set_state(uid, "")
                return self._send(chat_id, f"Category “{views.esc(text)}” created.", back)
            if state == "a_stock":
                catalog.set_stock(self.db, data["pid"], int(text))
                self._set_state(uid, "")
                return self._send(chat_id, *views.admin_product(self.db, data["pid"], cur))
            if state == "a_price":
                catalog.set_price(self.db, data["pid"], catalog.parse_price(text))
                self._set_state(uid, "")
                return self._send(chat_id, *views.admin_product(self.db, data["pid"], cur))
            if state == "a_coupon":
                code, percent, uses = text.split()
                cart_svc.create_coupon(self.db, code, int(percent), int(uses))
                self._set_state(uid, "")
                return self._send(chat_id, f"Coupon {views.esc(code.upper())} saved.", back)
            if state == "a_p_name":
                if not 2 <= len(text) <= 80:
                    return self._send(chat_id, "Name must be 2–80 characters.")
                self._set_state(uid, "a_p_price", cat=data["cat"], name=text)
                return self._send(chat_id, "Price? (example 19.90)")
            if state == "a_p_price":
                price = catalog.parse_price(text)
                self._set_state(uid, "a_p_stock", cat=data["cat"], name=data["name"], price=price)
                return self._send(chat_id, "Stock quantity?")
            if state == "a_p_stock":
                stock = int(text)
                if stock < 0:
                    raise ValueError
                self._set_state(uid, "a_p_desc", cat=data["cat"], name=data["name"], price=data["price"], stock=stock)
                return self._send(chat_id, "Short description? (send - to skip)")
            if state == "a_p_desc":
                desc = "" if text == "-" else text
                self._set_state(uid, "a_p_photo", cat=data["cat"], name=data["name"], price=data["price"],
                                stock=data["stock"], desc=desc)
                return self._send(chat_id, "Send a product photo (or - to skip)")
            if state == "a_p_photo":
                if text == "-":
                    return self._admin_new_product_finish(user, chat_id, data, photo=None)
                return self._send(chat_id, "Please send a photo, or - to skip.")
            if state == "a_bcast":
                self._set_state(uid, "a_bc_confirm", text=text)
                count = self.db.one("SELECT COUNT(*) AS n FROM users WHERE state != 'new'")["n"]
                return self._send(chat_id, f"Send this to {count} customers?\n\n{views.esc(text)}", views.kb(
                    [views.btn("✅ Send", "a_bcok")], [views.btn("✖️ Cancel", "a")]))
        except ShopError as exc:
            return self._send(chat_id, f"⚠️ {ADMIN_ERRORS.get(exc.code, exc.code)} Try again or /cancel.")
        except ValueError:
            return self._send(chat_id, "⚠️ That value is not valid. Try again or /cancel.")
        self._set_state(uid, "")
        return None

    def _admin_new_product_finish(self, user, chat_id, data: dict, photo) -> None:
        pid = catalog.add_product(self.db, data["cat"], data["name"], data["price"], data["stock"],
                                  data.get("desc", ""), photo)
        self._set_state(user["id"], "")
        self._send(chat_id, *views.admin_product(self.db, pid, self.cfg.currency))
