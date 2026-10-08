"""Settings from environment variables (a .env file is read if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Config:
    token: str = ""
    admin_ids: frozenset = field(default_factory=frozenset)
    db_path: str = "shop.db"
    currency: str = "USD"
    shop_name: str = "Demo Shop"
    bank_details: str = "Bank: Example Bank\nIBAN: XX00 0000 0000 0000 0000 00\nHolder: Demo Shop Ltd"
    broadcast_delay: float = 0.06  # Telegram allows ~30 messages per second overall

    @classmethod
    def from_env(cls) -> "Config":
        _load_dotenv()
        ids = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
        return cls(
            token=os.environ.get("BOT_TOKEN", ""),
            admin_ids=frozenset(ids),
            db_path=os.environ.get("DB_PATH", "shop.db"),
            currency=os.environ.get("CURRENCY", "USD"),
            shop_name=os.environ.get("SHOP_NAME", "Demo Shop"),
            bank_details=os.environ.get("BANK_DETAILS", cls.bank_details).replace("\\n", "\n"),
        )
