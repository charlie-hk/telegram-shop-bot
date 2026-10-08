from shopbot import catalog
from shopbot.bot import Bot
from shopbot.config import Config
from shopbot.db import Database
from shopbot.simulator import ConsoleAPI


def make_db():
    db = Database(":memory:")
    cid = catalog.add_category(db, "Coffee")
    p1 = catalog.add_product(db, cid, "Beans", 1000, 5, "Tasty <b>beans</b>")
    p2 = catalog.add_product(db, cid, "Mug", 550, 1)
    return db, cid, p1, p2


class Harness:
    """Drives the Bot with fake Telegram updates and records everything it sends."""

    def __init__(self, admin_ids=(), db=None):
        self.db = db or make_db()[0]
        self.api = ConsoleAPI(out=lambda *_: None)
        self.cfg = Config(admin_ids=frozenset(admin_ids), broadcast_delay=0, currency="USD")
        self.bot = Bot(self.api, self.db, self.cfg)
        self.n = 0

    def _frm(self, uid):
        return {"id": uid, "first_name": f"U{uid}", "username": f"u{uid}"}

    def say(self, uid, text, **extra):
        self.n += 1
        msg = {"message_id": self.n, "from": self._frm(uid), "chat": {"id": uid, "type": "private"}, "text": text}
        msg.update(extra)
        self.bot.handle_update({"update_id": self.n, "message": msg})

    def raw_message(self, uid, **fields):
        self.n += 1
        msg = {"message_id": self.n, "from": self._frm(uid), "chat": {"id": uid, "type": "private"}}
        msg.update(fields)
        self.bot.handle_update({"update_id": self.n, "message": msg})

    def tap(self, uid, data, message_id=None):
        self.n += 1
        self.bot.handle_update({"update_id": self.n, "callback_query": {
            "id": str(self.n), "from": self._frm(uid), "data": data,
            "message": {"message_id": message_id or self.api.next_id - 1, "chat": {"id": uid}}}})

    def last(self, uid=None):
        items = [m for m in self.api.sent if uid is None or m["chat_id"] == uid]
        return items[-1]

    def texts(self, uid):
        return [m["text"] for m in self.api.sent if m["chat_id"] == uid]

    def start(self, uid, lang="en"):
        self.say(uid, "/start")
        self.tap(uid, f"lng:{lang}")
