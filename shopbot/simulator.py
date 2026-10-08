"""Try the bot in a terminal, without a Telegram token.

    python -m shopbot --simulate

Buttons are shown as numbered options; type the number to press one, or type text as a chat message.
Use `--admin` to play the shop owner instead of a customer.
"""
from __future__ import annotations

import html
import re

from .bot import Bot
from .config import Config
from .db import Database
from .seed import seed_demo

USER_ID = 1001


class ConsoleAPI:
    """Stands in for TelegramAPI: prints what the bot would send and remembers the last keyboard."""

    def __init__(self, out=print):
        self.out = out
        self.next_id = 1
        self.buttons: list[dict] = []
        self.sent: list[dict] = []

    def _record(self, kind, chat_id, text, markup):
        mid = self.next_id
        self.next_id += 1
        self.sent.append({"kind": kind, "chat_id": chat_id, "text": text, "markup": markup, "message_id": mid})
        plain = html.unescape(re.sub(r"<[^>]+>", "", text or ""))
        self.out(f"\n[bot → {chat_id}]\n{plain}")
        if markup and "inline_keyboard" in markup:
            self.buttons = [b for row in markup["inline_keyboard"] for b in row]
            for i, b in enumerate(self.buttons, 1):
                self.out(f"  {i}. {b['text']}")
        return {"message_id": mid, "chat": {"id": chat_id}}

    def send_message(self, chat_id, text, reply_markup=None, parse_mode="HTML"):
        return self._record("send", chat_id, text, reply_markup)

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
        return self._record("edit", chat_id, text, reply_markup)

    def send_photo(self, chat_id, photo, caption, reply_markup=None, parse_mode="HTML"):
        return self._record("photo", chat_id, caption, reply_markup)

    def send_photo_file(self, chat_id, filename, content, caption=None, reply_markup=None, parse_mode="HTML"):
        msg = self._record("photo", chat_id, f"[picture: {filename}]\n{caption}", reply_markup)
        msg["photo"] = [{"file_id": "SIM-BANNER"}]
        return msg

    def delete_message(self, chat_id, message_id):
        return True

    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        if text:
            self.out(f"  (toast) {text}")
        return True

    def send_document(self, chat_id, filename, content, caption=None):
        self.out(f"\n[bot → {chat_id}] sent file {filename} ({len(content)} bytes)")
        return True


def run(admin: bool = False, db_path: str = ":memory:") -> None:  # pragma: no cover - interactive
    cfg = Config(admin_ids=frozenset({USER_ID}) if admin else frozenset(), broadcast_delay=0)
    db = Database(db_path)
    seed_demo(db)
    api = ConsoleAPI()
    bot = Bot(api, db, cfg)
    frm = {"id": USER_ID, "first_name": "Demo", "username": "demo"}
    chat = {"id": USER_ID, "type": "private"}
    uid = 0

    def message(text):
        nonlocal uid
        uid += 1
        bot.handle_update({"update_id": uid, "message": {"message_id": uid, "from": frm, "chat": chat, "text": text}})

    print("Shop simulator. Type a button number, or text. /start to begin, 'quit' to exit.")
    message("/start")
    while True:
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if line in ("quit", "exit"):
            return
        if line.isdigit() and 1 <= int(line) <= len(api.buttons):
            uid += 1
            bot.handle_update({"update_id": uid, "callback_query": {
                "id": str(uid), "from": frm, "data": api.buttons[int(line) - 1]["callback_data"],
                "message": {"message_id": api.next_id - 1, "chat": chat}}})
        elif line:
            message(line)
