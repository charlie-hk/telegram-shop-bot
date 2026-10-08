"""Command line: run the bot, seed demo data, check the token, or simulate in the terminal."""
from __future__ import annotations

import argparse
import logging
import sys

from .api import TelegramAPI, TelegramError
from .bot import Bot
from .config import Config
from .db import Database
from .profile import setup_profile
from .seed import seed_demo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="shopbot", description="Telegram shop bot")
    ap.add_argument("--seed", action="store_true", help="add a demo catalog if the database is empty")
    ap.add_argument("--check", action="store_true", help="verify BOT_TOKEN with getMe and exit")
    ap.add_argument("--setup", action="store_true",
                    help="publish the pre-START description, command menu and exit")
    ap.add_argument("--simulate", action="store_true", help="try the bot in the terminal, no token needed")
    ap.add_argument("--admin", action="store_true", help="with --simulate: act as the shop owner")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.simulate:
        from .simulator import run
        run(admin=args.admin)
        return 0

    cfg = Config.from_env()
    if not cfg.token:
        print("BOT_TOKEN is not set. Copy .env.example to .env and fill it in "
              "(or try `python -m shopbot --simulate`).", file=sys.stderr)
        return 2
    db = Database(cfg.db_path)
    if args.seed and seed_demo(db):
        print("Demo catalog added.")
    api = TelegramAPI(cfg.token)
    try:
        me = api.call("getMe")
    except TelegramError as exc:
        print(f"Telegram rejected the token or is unreachable: {exc}", file=sys.stderr)
        return 1
    print(f"Connected as @{me.get('username')}")
    if args.check:
        return 0
    problems = setup_profile(api, cfg)
    print("Bot profile (description, commands) updated." if not problems
          else "Some profile updates failed: " + "; ".join(problems))
    print("Picture on the pre-START screen: set it once in @BotFather -> /mybots -> your bot -> "
          "Edit Bot -> Edit Description Picture, using shopbot/assets/description_pic.png.")
    if args.setup:
        return 0
    if not cfg.admin_ids:
        print("Warning: ADMIN_IDS is empty, so nobody can use /admin.", file=sys.stderr)
    Bot(api, db, cfg).run_polling()
    return 0


if __name__ == "__main__":
    sys.exit(main())
