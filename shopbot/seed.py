"""Demo catalog so the bot is usable right after install."""
from __future__ import annotations

from . import cart, catalog
from .db import Database

DEMO = {
    "Coffee": [
        ("Ethiopia Yirgacheffe 250g", "Floral and citrus, light roast. Great for filter.", "11.50", 24),
        ("Colombia Huila 250g", "Chocolate and red fruit, medium roast.", "10.90", 30),
        ("Espresso Blend 1kg", "Balanced and creamy, made for milk drinks.", "32.00", 12),
        ("Decaf Swiss Water 250g", "Chemical-free decaf, caramel notes.", "12.50", 3),
    ],
    "Tea": [
        ("Jasmine Pearls 100g", "Hand-rolled green tea scented with jasmine.", "9.80", 18),
        ("Earl Grey Reserve 100g", "Black tea with real bergamot oil.", "7.40", 40),
        ("Chamomile Honey 50g", "Caffeine-free evening tea.", "5.90", 0),
    ],
    "Accessories": [
        ("Ceramic Pour-Over Dripper", "Fits size 02 filters. Dishwasher safe.", "18.00", 9),
        ("Gooseneck Kettle 0.9L", "Precise pour, stainless steel.", "39.90", 5),
        ("Paper Filters x100", "Size 02, unbleached.", "3.50", 100),
    ],
}


def seed_demo(db: Database) -> bool:
    """Fill an empty database. Returns False (and does nothing) if products already exist."""
    if db.one("SELECT 1 FROM products LIMIT 1"):
        return False
    for category, products in DEMO.items():
        cid = catalog.add_category(db, category)
        for name, desc, price, stock in products:
            catalog.add_product(db, cid, name, catalog.parse_price(price), stock, desc)
    cart.create_coupon(db, "WELCOME10", 10, 100)
    return True
