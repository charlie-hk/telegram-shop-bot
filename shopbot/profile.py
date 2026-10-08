"""What people see in Telegram before they press START: description, short description, command menu."""
from __future__ import annotations

import logging

from .api import TelegramAPI, TelegramError
from .config import Config
from .i18n import DEFAULT_LANG, LANGUAGES, t

log = logging.getLogger("shopbot.profile")

CUSTOMER_COMMANDS = ("start", "menu", "help", "cancel")


def commands_for(lang: str) -> list:
    return [{"command": c, "description": t(lang, f"cmd_{c}")} for c in CUSTOMER_COMMANDS]


def setup_profile(api: TelegramAPI, cfg: Config) -> list:
    """Push texts and commands to Telegram. Returns a list of problems (empty = all fine).

    The picture shown on the pre-START screen cannot be set through the Bot API; see README.
    """
    problems = []

    def attempt(label, fn):
        try:
            fn()
        except TelegramError as exc:
            problems.append(f"{label}: {exc}")
            log.warning("%s failed: %s", label, exc)

    for lang in LANGUAGES:
        code = None if lang == DEFAULT_LANG else lang  # the default text covers every other language
        attempt(f"description[{lang}]", lambda l=lang, c=code: api.set_my_description(
            t(l, "bot_description", shop=cfg.shop_name)[:512], c))
        attempt(f"short description[{lang}]", lambda l=lang, c=code: api.set_my_short_description(
            t(l, "bot_short")[:120], c))
        attempt(f"commands[{lang}]", lambda l=lang, c=code: api.set_my_commands(commands_for(l), c))
    attempt("menu button", lambda: api.set_chat_menu_button({"type": "commands"}))
    for admin_id in cfg.admin_ids:  # the owner also sees /admin in their own command menu
        admin_cmds = commands_for(DEFAULT_LANG) + [{"command": "admin", "description": "Admin panel"}]
        attempt(f"admin commands[{admin_id}]", lambda a=admin_id: api.set_my_commands(
            admin_cmds, scope={"type": "chat", "chat_id": a}))
    return problems
