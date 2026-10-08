import unittest

from shopbot import cart, catalog, orders
from shopbot.errors import ShopError
from tests.helpers import make_db


class CatalogTests(unittest.TestCase):
    def test_parse_price(self):
        self.assertEqual(catalog.parse_price("12.50"), 1250)
        self.assertEqual(catalog.parse_price("12,5"), 1250)
        self.assertEqual(catalog.parse_price("7"), 700)
        for bad in ("", "abc", "-1", "1.234", "1e3", "12.", "99999999"):
            with self.assertRaises(ValueError, msg=bad):
                catalog.parse_price(bad)

    def test_format_money(self):
        self.assertEqual(catalog.format_money(5, "USD"), "0.05 USD")
        self.assertEqual(catalog.format_money(123456, "EUR"), "1234.56 EUR")

    def test_search_escapes_wildcards(self):
        db, cid, *_ = make_db()
        catalog.add_product(db, cid, "100% Arabica", 900, 3)
        self.assertEqual([p["name"] for p in catalog.search_products(db, "100%")], ["100% Arabica"])
        self.assertEqual(catalog.search_products(db, "%%"), [])
        with self.assertRaises(ShopError):
            catalog.search_products(db, "a")

    def test_hidden_products_and_empty_categories_not_listed(self):
        db, cid, p1, p2 = make_db()
        catalog.toggle_active(db, p1)
        catalog.toggle_active(db, p2)
        self.assertEqual(catalog.list_categories(db), [])
        self.assertEqual(catalog.search_products(db, "Beans"), [])

    def test_pagination_clamps(self):
        db, cid, *_ = make_db()
        for i in range(8):
            catalog.add_product(db, cid, f"Item {i}", 100, 1)
        rows, total, page = catalog.list_products(db, cid, 99)
        self.assertEqual((total, page), (10, 1))
        self.assertEqual(len(rows), 5)

    def test_duplicate_category_rejected(self):
        db, *_ = make_db()
        with self.assertRaises(ShopError) as cm:
            catalog.add_category(db, "Coffee")
        self.assertEqual(cm.exception.code, "category_exists")


class CartTests(unittest.TestCase):
    def test_add_remove_and_stock_cap(self):
        db, cid, beans, mug = make_db()
        self.assertEqual(cart.add_item(db, 1, beans), 1)
        self.assertEqual(cart.add_item(db, 1, beans), 2)
        self.assertEqual(cart.add_item(db, 1, beans, -1), 1)
        self.assertEqual(cart.add_item(db, 1, beans, -1), 0)
        self.assertEqual(cart.items(db, 1), [])
        cart.add_item(db, 1, mug)
        with self.assertRaises(ShopError) as cm:
            cart.add_item(db, 1, mug)
        self.assertEqual(cm.exception.code, "max_qty")

    def test_out_of_stock_and_hidden(self):
        db, cid, beans, mug = make_db()
        catalog.set_stock(db, beans, 0)
        with self.assertRaises(ShopError) as cm:
            cart.add_item(db, 1, beans)
        self.assertEqual(cm.exception.code, "out_of_stock")
        catalog.toggle_active(db, mug)
        with self.assertRaises(ShopError):
            cart.add_item(db, 1, mug)

    def test_coupon_math_and_limits(self):
        db, cid, beans, mug = make_db()
        cart.add_item(db, 1, beans, 3)       # 30.00
        cart.create_coupon(db, "save10", 10, 1)
        self.assertEqual(cart.apply_coupon(db, 1, " save10 "), 10)
        s = cart.summary(db, 1)
        self.assertEqual((s["subtotal"], s["discount"], s["total"]), (3000, 300, 2700))
        with self.assertRaises(ShopError):
            cart.apply_coupon(db, 1, "NOPE")
        with self.assertRaises(ShopError):
            cart.create_coupon(db, "x", 10, 1)
        with self.assertRaises(ShopError):
            cart.create_coupon(db, "BIG100", 100, 1)

    def test_discount_rounds_down_in_integer_cents(self):
        db, cid, *_ = make_db()
        p = catalog.add_product(db, cid, "Odd", 333, 5)
        cart.add_item(db, 1, p)
        cart.create_coupon(db, "TEN", 10, 5)
        cart.apply_coupon(db, 1, "TEN")
        s = cart.summary(db, 1)
        self.assertEqual((s["discount"], s["total"]), (33, 300))


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.db, self.cid, self.beans, self.mug = make_db()

    def _order(self, uid=1, qty_beans=2, coupon=None):
        cart.add_item(self.db, uid, self.beans, qty_beans)
        if coupon:
            cart.apply_coupon(self.db, uid, coupon)
        return orders.create_order(self.db, uid, "Ali", "+905551234567", "Somewhere 1", "cod")

    def test_create_decrements_stock_and_clears_cart(self):
        oid = self._order()
        self.assertEqual(catalog.get_product(self.db, self.beans)["stock"], 3)
        self.assertEqual(cart.items(self.db, 1), [])
        data = orders.get_order(self.db, oid)
        self.assertEqual(data["order"]["total_cents"], 2000)
        self.assertEqual(len(data["lines"]), 1)

    def test_last_unit_cannot_be_sold_twice(self):
        cart.add_item(self.db, 1, self.mug)
        cart.add_item(self.db, 2, self.mug)      # both carts hold the single mug
        orders.create_order(self.db, 1, "A", "1234567", "Address 1", "cod")
        with self.assertRaises(ShopError) as cm:
            orders.create_order(self.db, 2, "B", "1234567", "Address 2", "cod")
        self.assertEqual(cm.exception.code, "stock_changed")
        self.assertEqual(catalog.get_product(self.db, self.mug)["stock"], 0)
        self.assertEqual(len(cart.items(self.db, 2)), 1)   # cart kept so the user can fix it

    def test_failed_order_changes_nothing(self):
        cart.add_item(self.db, 1, self.beans, 2)
        catalog.set_stock(self.db, self.beans, 1)
        with self.assertRaises(ShopError):
            orders.create_order(self.db, 1, "A", "1234567", "Address 1", "cod")
        self.assertEqual(catalog.get_product(self.db, self.beans)["stock"], 1)
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM orders")["n"], 0)

    def test_empty_cart_and_bad_payment(self):
        with self.assertRaises(ShopError) as cm:
            orders.create_order(self.db, 9, "A", "1234567", "Address 1", "cod")
        self.assertEqual(cm.exception.code, "cart_empty")
        cart.add_item(self.db, 9, self.beans)
        with self.assertRaises(ShopError):
            orders.create_order(self.db, 9, "A", "1234567", "Address 1", "bitcoin")

    def test_status_workflow(self):
        oid = self._order()
        with self.assertRaises(ShopError):
            orders.set_status(self.db, oid, "delivered")      # cannot skip steps
        for st in ("confirmed", "shipped", "delivered"):
            self.assertEqual(orders.set_status(self.db, oid, st)["status"], st)
        with self.assertRaises(ShopError):
            orders.set_status(self.db, oid, "cancelled")      # finished orders are final

    def test_cancel_restores_stock_and_coupon(self):
        cart.create_coupon(self.db, "SAVE10", 10, 1)
        oid = self._order(coupon="SAVE10")
        self.assertEqual(self.db.one("SELECT used FROM coupons")["used"], 1)
        orders.cancel_by_customer(self.db, oid, 1)
        self.assertEqual(catalog.get_product(self.db, self.beans)["stock"], 5)
        self.assertEqual(self.db.one("SELECT used FROM coupons")["used"], 0)

    def test_customer_cannot_cancel_other_users_or_confirmed_orders(self):
        oid = self._order()
        with self.assertRaises(ShopError):
            orders.cancel_by_customer(self.db, oid, 2)
        orders.set_status(self.db, oid, "confirmed")
        with self.assertRaises(ShopError) as cm:
            orders.cancel_by_customer(self.db, oid, 1)
        self.assertEqual(cm.exception.code, "cancel_not_allowed")

    def test_coupon_use_limit(self):
        cart.create_coupon(self.db, "ONCE", 10, 1)
        self._order(uid=1, coupon="ONCE")
        with self.assertRaises(ShopError):
            cart.apply_coupon(self.db, 2, "ONCE")

    def test_stats_and_csv_injection(self):
        cart.add_item(self.db, 1, self.beans, 1)
        orders.create_order(self.db, 1, "=HYPERLINK(\"x\")", "+905551234567", "Address 1", "bank")
        oid2 = self._order(uid=2, qty_beans=1)
        orders.set_status(self.db, oid2, "cancelled")
        s = orders.stats(self.db)
        self.assertEqual(s["counts"]["new"], 1)
        self.assertEqual(s["counts"]["cancelled"], 1)
        self.assertEqual(s["revenue"], 1000)
        text = orders.export_csv(self.db)
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("+905551234567", text)


if __name__ == "__main__":
    unittest.main()
