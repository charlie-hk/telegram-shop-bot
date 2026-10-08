"""Minimal Telegram Bot API client using only the standard library."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
import uuid

log = logging.getLogger("shopbot.api")


class TelegramError(Exception):
    def __init__(self, description: str, code: int | None = None, retry_after: int | None = None):
        super().__init__(description)
        self.description = description
        self.code = code
        self.retry_after = retry_after


class TelegramAPI:
    def __init__(self, token: str, base_url: str = "https://api.telegram.org", timeout: int = 40,
                 max_retries: int = 3):
        if not token:
            raise ValueError("BOT_TOKEN is empty")
        self._url = f"{base_url.rstrip('/')}/bot{token}/"
        self.timeout = timeout
        self.max_retries = max_retries

    # --- transport --------------------------------------------------------

    def call(self, method: str, **params):
        body = json.dumps({k: v for k, v in params.items() if v is not None}).encode()
        return self._request(method, body, {"Content-Type": "application/json"})

    def _request(self, method: str, body: bytes, headers: dict):
        last_exc = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(self._url + method, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.load(resp)
            except urllib.error.HTTPError as exc:
                payload = _read_error_body(exc)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise TelegramError(f"network error: {exc}") from exc
            if payload.get("ok"):
                return payload["result"]
            retry_after = (payload.get("parameters") or {}).get("retry_after")
            if retry_after is not None and attempt < self.max_retries:  # flood control: wait and try again
                time.sleep(min(int(retry_after), 30))
                continue
            raise TelegramError(payload.get("description", "unknown error"),
                                payload.get("error_code"), retry_after)
        raise TelegramError(f"network error: {last_exc}")  # pragma: no cover

    # --- methods used by the bot ------------------------------------------

    def get_updates(self, offset: int | None = None, timeout: int = 30):
        return self.call("getUpdates", offset=offset, timeout=timeout,
                         allowed_updates=["message", "callback_query"])

    def send_message(self, chat_id, text, reply_markup=None, parse_mode="HTML"):
        return self.call("sendMessage", chat_id=chat_id, text=text, reply_markup=reply_markup,
                         parse_mode=parse_mode, disable_web_page_preview=True)

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
        return self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                         reply_markup=reply_markup, parse_mode=parse_mode, disable_web_page_preview=True)

    def send_photo(self, chat_id, photo, caption, reply_markup=None, parse_mode="HTML"):
        return self.call("sendPhoto", chat_id=chat_id, photo=photo, caption=caption,
                         reply_markup=reply_markup, parse_mode=parse_mode)

    def delete_message(self, chat_id, message_id):
        return self.call("deleteMessage", chat_id=chat_id, message_id=message_id)

    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        return self.call("answerCallbackQuery", callback_query_id=callback_query_id, text=text,
                         show_alert=show_alert or None)

    def send_document(self, chat_id, filename: str, content: bytes, caption: str | None = None):
        return self._upload("sendDocument", "document", filename, content, "text/csv",
                            {"chat_id": chat_id, "caption": caption})

    def send_photo_file(self, chat_id, filename: str, content: bytes, caption=None, reply_markup=None,
                        parse_mode="HTML"):
        """Upload a local image. The result's photo[-1].file_id can be reused with send_photo."""
        fields = {"chat_id": chat_id, "caption": caption, "parse_mode": parse_mode,
                  "reply_markup": json.dumps(reply_markup) if reply_markup else None}
        return self._upload("sendPhoto", "photo", filename, content, "image/png", fields)

    def _upload(self, method, field, filename, content: bytes, ctype, fields: dict):
        boundary = uuid.uuid4().hex
        out = bytearray()
        for name, value in fields.items():
            if value is None:
                continue
            out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        out += (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
                f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n').encode()
        out += content + f"\r\n--{boundary}--\r\n".encode()
        return self._request(method, bytes(out), {"Content-Type": f"multipart/form-data; boundary={boundary}"})

    # --- bot profile (what people see before they press START) -------------

    def set_my_commands(self, commands: list, language_code: str | None = None, scope: dict | None = None):
        return self.call("setMyCommands", commands=commands, language_code=language_code, scope=scope)

    def set_my_description(self, description: str, language_code: str | None = None):
        return self.call("setMyDescription", description=description, language_code=language_code)

    def set_my_short_description(self, short_description: str, language_code: str | None = None):
        return self.call("setMyShortDescription", short_description=short_description,
                         language_code=language_code)

    def set_chat_menu_button(self, menu_button: dict | None = None, chat_id=None):
        return self.call("setChatMenuButton", chat_id=chat_id, menu_button=menu_button)


def _read_error_body(exc: urllib.error.HTTPError) -> dict:
    try:
        return json.load(exc)
    except Exception:  # noqa: BLE001 - body may be empty or not JSON
        return {"ok": False, "description": f"HTTP {exc.code}", "error_code": exc.code}
