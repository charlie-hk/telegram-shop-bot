import json
import unittest

from shopbot import cart, catalog, orders, views
from shopbot.api import TelegramError
from tests.helpers import Harness, make_db

ADMIN = 99
USER = 5


def all_callback_data(markup):
    return [b["callback_data"] for row in (markup or {}).get("inline_keyboard", []) for b in row]


class CustomerFlowTests(unittest.TestCase):
    def setUp(self):
        self.db, self.cid, self.beans, self.mug = make_db()
        self.h = Harness(admin_ids=[ADMIN], db=self.db)

    def checkout(self, uid=USER, pay="cod"):
        self.h.tap(uid, "chk")
        self.h.say(uid, "Ali Amini")
        self.h.say(uid, "+90 555 123 45 67")
        self.h.say(uid, "Istiklal Cad. 10, Istanbul")
        self.h.tap(uid, f"pay:{pay}")
        self.h.tap(uid, "ok")

    def test_first_start_asks_language_then_menu(self):
        self.h.say(USER, "/start")
        self.assertIn("lng:fa", all_callback_data(self.h.last(USER)["markup"]))
        self.h.tap(USER, "lng:tr")
        self.assertIn("hoş geldiniz", self.h.last(USER)["text"])
        self.assertEqual(self.db.one("SELECT lang FROM users WHERE id=?", (USER,))["lang"], "tr")

    def test_buttons_before_language_choice_show_picker(self):
        self.h.say(USER, "hello")
        self.assertIn("lng:en", all_callback_data(self.h.last(USER)["markup"]))
        self.h.tap(USER, "cats")
        self.assertIn("lng:en", all_callback_data(self.h.last(USER)["markup"]))

    def test_full_purchase_with_coupon(self):
        cart.create_coupon(self.db, "SAVE10", 10, 5)
        self.h.start(USER)
        self.h.tap(USER, "cats")
        self.h.tap(USER, f"cat:{self.cid}:0")
        self.h.tap(USER, f"p:{self.beans}")
        self.assertIn("Tasty &lt;b&gt;beans&lt;/b&gt;", self.h.last(USER)["text"])   # user text is escaped
        self.h.tap(USER, f"add:{self.beans}")
        self.h.tap(USER, f"add:{self.beans}")
        self.h.tap(USER, "cpn")
        self.h.say(USER, "save10")
        self.assertIn("18.00 USD", self.h.last(USER)["text"])
        self.checkout()
        self.assertIn("placed", self.h.last(USER)["text"])
        order = self.db.one("SELECT * FROM orders")
        self.assertEqual((order["total_cents"], order["customer_name"], order["status"]), (1800, "Ali Amini", "new"))
        self.assertEqual(catalog.get_product(self.db, self.beans)["stock"], 3)
        admin_msgs = self.h.texts(ADMIN)
        self.assertTrue(any("New order" in m and "Ali Amini" in m for m in admin_msgs))

    def test_bank_transfer_shows_details(self):
        self.h.start(USER)
        self.h.tap(USER, f"add:{self.beans}")
        self.checkout(pay="bank")
        self.assertIn("IBAN", self.h.last(USER)["text"])

    def test_invalid_inputs_keep_the_step(self):
        self.h.start(USER)
        self.h.tap(USER, f"add:{self.beans}")
        self.h.tap(USER, "chk")
        self.h.say(USER, "A")
        self.assertIn("full name", self.h.last(USER)["text"])
        self.h.say(USER, "Ali Amini")
        self.h.say(USER, "call me")
        self.assertIn("phone", self.h.last(USER)["text"])
        self.h.say(USER, "12345678")
        self.h.say(USER, "x")
        self.assertIn("address", self.h.last(USER)["text"])

    def test_shared_contact_must_be_own(self):
        self.h.start(USER)
        self.h.tap(USER, f"add:{self.beans}")
        self.h.tap(USER, "chk")
        self.h.say(USER, "Ali Amini")
        self.h.raw_message(USER, contact={"phone_number": "+905550000000", "user_id": 12345})
        self.assertIn("phone", self.h.last(USER)["text"])
        self.h.raw_message(USER, contact={"phone_number": "+905550000000", "user_id": USER})
        self.assertIn("address", self.h.last(USER)["text"].lower())

    def test_cancel_command_stops_checkout_and_removes_keyboard(self):
        self.h.start(USER)
        self.h.tap(USER, f"add:{self.beans}")
        self.h.tap(USER, "chk")
        self.h.say(USER, "/cancel")
        self.assertEqual(self.db.one("SELECT state FROM users WHERE id=?", (USER,))["state"], "")
        self.h.say(USER, "random text")
        self.assertIn("did not understand", self.h.last(USER)["text"])

    def test_stock_race_at_confirmation(self):
        self.h.start(USER)
        self.h.tap(USER, f"add:{self.mug}")
        self.h.tap(USER, "chk")
        self.h.say(USER, "Ali Amini")
        self.h.say(USER, "+905551234567")
        self.h.say(USER, "Some address 1")
        self.h.tap(USER, "pay:cod")
        catalog.set_stock(self.db, self.mug, 0)       # someone else bought it meanwhile
        self.h.tap(USER, "ok")
        self.assertIn("Stock changed", self.h.last(USER)["text"])
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM orders")["n"], 0)

    def test_empty_cart_cannot_checkout(self):
        self.h.start(USER)
        self.h.tap(USER, "chk")
        self.assertEqual(self.db.one("SELECT state FROM users WHERE id=?", (USER,))["state"], "")

    def test_customer_sees_only_own_orders_and_can_cancel_new_one(self):
        self.h.start(USER)
        self.h.tap(USER, f"add:{self.beans}")
        self.checkout()
        oid = self.db.one("SELECT id FROM orders")["id"]
        self.h.start(777)
        self.h.tap(777, f"o:{oid}")
        self.assertIn("no longer available", self.h.last(777)["text"])
        self.h.tap(USER, f"o:{oid}")
        self.assertIn(f"Order #{oid}", self.h.last(USER)["text"])
        self.h.tap(USER, f"oc:{oid}")
        self.assertEqual(self.db.one("SELECT status FROM orders")["status"], "cancelled")
        self.assertEqual(catalog.get_product(self.db, self.beans)["stock"], 5)

    def test_search(self):
        self.h.start(USER)
        self.h.tap(USER, "srch")
        self.h.say(USER, "mug")
        self.assertIn(f"p:{self.mug}", all_callback_data(self.h.last(USER)["markup"]))
        self.h.tap(USER, "srch")
        self.h.say(USER, "<script>")
        self.assertIn("&lt;script&gt;", self.h.last(USER)["text"])

    def test_persian_cart_is_translated(self):
        self.h.start(USER, "fa")
        self.h.tap(USER, "cart")
        self.assertIn("خالی", self.h.last(USER)["text"])

    def test_not_modified_edit_is_ignored_and_other_errors_fall_back_to_send(self):
        self.h.start(USER)
        real_edit = self.h.api.edit_message_text

        def not_modified(*a, **k):
            raise TelegramError("Bad Request: message is not modified")
        self.h.api.edit_message_text = not_modified
        before = len(self.h.api.sent)
        self.h.tap(USER, "cats")
        self.assertEqual(len(self.h.api.sent), before)

        def gone(*a, **k):
            raise TelegramError("Bad Request: message to edit not found")
        self.h.api.edit_message_text = gone
        self.h.tap(USER, "cats")
        self.assertEqual(len(self.h.api.sent), before + 1)
        self.h.api.edit_message_text = real_edit

    def test_internal_error_does_not_crash_loop(self):
        self.h.start(USER)
        self.h.bot._on_message = lambda msg: 1 / 0
        self.h.say(USER, "hi")                                  # must not raise
        self.assertIn("went wrong", self.h.last(USER)["text"])

    def test_group_chats_are_ignored(self):
        before = len(self.h.api.sent)
        self.h.bot.handle_update({"update_id": 1, "message": {
            "message_id": 1, "from": {"id": 1}, "chat": {"id": -100, "type": "group"}, "text": "/start"}})
        self.assertEqual(len(self.h.api.sent), before)

    def test_all_callback_data_fits_telegram_limit(self):
        self.h.start(USER)
        for d in (f"cat:{self.cid}:0", f"p:{self.beans}", "cart", "ords:0"):
            self.h.tap(USER, d)
        self.h.tap(USER, f"add:{self.beans}")
        self.h.tap(USER, "cart")
        for m in self.h.api.sent:
            for data in all_callback_data(m["markup"]):
                self.assertLessEqual(len(data.encode()), 64, data)


class AdminFlowTests(unittest.TestCase):
    def setUp(self):
        self.db, self.cid, self.beans, self.mug = make_db()
        self.h = Harness(admin_ids=[ADMIN], db=self.db)
        self.h.start(ADMIN)

    def test_non_admin_is_blocked(self):
        self.h.start(USER)
        self.h.say(USER, "/admin")
        self.assertNotIn("Admin panel", self.h.last(USER)["text"])
        before = self.db.one("SELECT stock FROM products WHERE id=?", (self.beans,))["stock"]
        self.h.tap(USER, f"a_tg:{self.beans}")
        self.h.tap(USER, f"a_stk:{self.beans}")
        self.h.say(USER, "9999")
        self.assertEqual(self.db.one("SELECT stock FROM products WHERE id=?", (self.beans,))["stock"], before)
        self.assertEqual(catalog.get_product(self.db, self.beans)["active"], 1)

    def test_add_product_end_to_end(self):
        self.h.say(ADMIN, "/admin")
        self.h.tap(ADMIN, "a_np")
        self.h.tap(ADMIN, f"a_npc:{self.cid}")
        for answer in ("Cold Brew 1L", "8,90", "12", "Ready to drink", "-"):
            self.h.say(ADMIN, answer)
        p = self.db.one("SELECT * FROM products WHERE name='Cold Brew 1L'")
        self.assertEqual((p["price_cents"], p["stock"], p["description"], p["photo_file_id"]), (890, 12, "Ready to drink", None))

    def test_add_product_with_photo(self):
        self.h.tap(ADMIN, "a_npc:%d" % self.cid)
        for answer in ("Poster", "5", "2", "-"):
            self.h.say(ADMIN, answer)
        self.h.raw_message(ADMIN, photo=[{"file_id": "small"}, {"file_id": "BIG"}])
        self.assertEqual(self.db.one("SELECT photo_file_id FROM products WHERE name='Poster'")[0], "BIG")

    def test_invalid_values_keep_state(self):
        self.h.tap(ADMIN, f"a_stk:{self.beans}")
        self.h.say(ADMIN, "lots")
        self.assertIn("not valid", self.h.last(ADMIN)["text"])
        self.h.say(ADMIN, "-3")
        self.assertIn("not valid", self.h.last(ADMIN)["text"])
        self.h.say(ADMIN, "40")
        self.assertEqual(catalog.get_product(self.db, self.beans)["stock"], 40)

    def test_price_stock_toggle_category_coupon(self):
        self.h.tap(ADMIN, f"a_prc:{self.beans}")
        self.h.say(ADMIN, "12.99")
        self.assertEqual(catalog.get_product(self.db, self.beans)["price_cents"], 1299)
        self.h.tap(ADMIN, f"a_tg:{self.mug}")
        self.assertEqual(catalog.get_product(self.db, self.mug)["active"], 0)
        self.h.tap(ADMIN, "a_nc")
        self.h.say(ADMIN, "Tea")
        self.assertEqual(len(catalog.list_categories(self.db, include_inactive=True)), 2)
        self.h.tap(ADMIN, "a_cpn")
        self.h.say(ADMIN, "welcome15 15 20")
        self.assertEqual(self.db.one("SELECT percent FROM coupons WHERE code='WELCOME15'")["percent"], 15)

    def test_order_status_change_notifies_customer_in_their_language(self):
        self.h.start(USER, "tr")
        self.h.tap(USER, f"add:{self.beans}")
        self.h.tap(USER, "chk")
        for s in ("Ali", "+905551234567", "Adres 12345"):
            self.h.say(USER, s)
        self.h.tap(USER, "pay:cod")
        self.h.tap(USER, "ok")
        oid = self.db.one("SELECT id FROM orders")["id"]
        self.h.tap(ADMIN, f"a_st:{oid}:confirmed")
        self.assertIn("Onaylandı", self.h.last(USER)["text"])
        self.h.tap(ADMIN, f"a_st:{oid}:delivered")           # illegal jump -> order unchanged
        self.assertEqual(self.db.one("SELECT status FROM orders")["status"], "confirmed")
        self.h.tap(ADMIN, "a_ord:confirmed:0")
        self.assertIn(f"a_o:{oid}", all_callback_data(self.h.last(ADMIN)["markup"]))

    def test_stats_and_export(self):
        self.h.tap(ADMIN, "a_stats")
        self.assertIn("Revenue", self.h.last(ADMIN)["text"])
        sent = []
        self.h.api.send_document = lambda chat, name, content, caption=None: sent.append((name, content))
        self.h.tap(ADMIN, "a_exp")
        self.assertEqual(sent[0][0], "orders.csv")
        self.assertTrue(sent[0][1].startswith(b"\xef\xbb\xbf"))

    def test_broadcast_requires_confirmation_and_escapes_html(self):
        self.h.start(USER)
        self.h.tap(ADMIN, "a_bc")
        self.h.say(ADMIN, "Sale <b>today</b>!")
        self.assertNotIn("Sale", " ".join(self.h.texts(USER)))
        self.h.tap(ADMIN, "a_bcok")
        self.assertIn("Sale &lt;b&gt;today&lt;/b&gt;!", self.h.texts(USER))

    def test_every_admin_screen_renders(self):
        for data in ("a", "a_ord:all:0", "a_prod:0", f"a_p:{self.beans}", "a_stats", "a_np"):
            self.h.tap(ADMIN, data)
            self.assertTrue(self.h.last(ADMIN)["text"])


if __name__ == "__main__":
    unittest.main()
