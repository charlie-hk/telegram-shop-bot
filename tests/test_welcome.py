import json
import unittest

from shopbot import bot as bot_module
from shopbot.api import TelegramError
from shopbot.config import Config
from shopbot.i18n import LANGUAGES, t
from shopbot.profile import commands_for, setup_profile
from tests.helpers import Harness


class RecordingAPI:
    def __init__(self, fail_on=()):
        self.calls, self.fail_on = [], set(fail_on)

    def _rec(self, name, *a, **k):
        if name in self.fail_on:
            raise TelegramError(f"{name} refused")
        self.calls.append((name, a, k))

    def set_my_description(self, d, language_code=None): self._rec("desc", d, language_code)
    def set_my_short_description(self, d, language_code=None): self._rec("short", d, language_code)
    def set_my_commands(self, c, language_code=None, scope=None): self._rec("cmds", c, language_code, scope)
    def set_chat_menu_button(self, m=None, chat_id=None): self._rec("menu", m)


class WelcomeBannerTests(unittest.TestCase):
    def test_banner_file_exists_and_is_png(self):
        self.assertTrue(bot_module.BANNER.is_file())
        self.assertEqual(bot_module.BANNER.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_first_start_shows_banner_with_language_buttons_and_caches_file_id(self):
        h = Harness()
        h.say(1, "/start")
        first = h.last(1)
        self.assertEqual(first["kind"], "photo")
        self.assertIn("English", json.dumps(first["markup"], ensure_ascii=False))
        self.assertIn("فارسی", first["text"] + json.dumps(first["markup"], ensure_ascii=False))
        h.tap(1, "lng:en")
        self.assertEqual(h.last(1)["kind"], "photo")             # welcome screen is a banner too
        self.assertIn("Welcome to", h.last(1)["text"])
        self.assertEqual(h.bot._meta_get("banner_file_id"), "SIM-BANNER")

    def test_returning_user_start_reuses_cached_file_id(self):
        h = Harness()
        h.start(1)
        uploads = []
        real = h.api.send_photo_file
        h.api.send_photo_file = lambda *a, **k: uploads.append(1) or real(*a, **k)
        h.say(1, "/start")
        self.assertEqual(uploads, [])
        self.assertEqual(h.last(1)["kind"], "photo")

    def test_stale_file_id_triggers_reupload(self):
        h = Harness()
        h.start(1)
        calls = []
        def stale(*a, **k):
            calls.append("photo")
            raise TelegramError("wrong file identifier")
        h.api.send_photo = stale
        h.say(1, "/start")
        self.assertEqual(calls, ["photo"])
        self.assertEqual(h.last(1)["kind"], "photo")             # re-uploaded from disk

    def test_missing_or_refused_banner_falls_back_to_text(self):
        h = Harness()
        def refuse(*a, **k):
            raise TelegramError("Bad Request: wrong file")
        h.api.send_photo_file = refuse
        h.say(1, "/start")
        self.assertEqual(h.last(1)["kind"], "send")
        self.assertIn("lng:en", json.dumps(h.last(1)["markup"]))
        old = bot_module.BANNER
        try:
            bot_module.BANNER = old.with_name("nope.png")
            h.tap(1, "lng:en")
            self.assertIn("Welcome", h.last(1)["text"])
        finally:
            bot_module.BANNER = old

    def test_menu_after_banner_still_works(self):
        h = Harness()
        h.start(1)
        h.tap(1, "cats")                                         # tapped message is a photo -> replaced
        self.assertTrue(h.last(1)["text"])


class ProfileTests(unittest.TestCase):
    def test_setup_sets_every_language_and_command_menu(self):
        api = RecordingAPI()
        problems = setup_profile(api, Config(shop_name="Beans & Co", admin_ids=frozenset({7})))
        self.assertEqual(problems, [])
        descs = {a[1]: a[0] for n, a, k in api.calls if n == "desc"}
        self.assertEqual(set(descs), {None, "fa", "tr"})
        self.assertIn("Beans & Co", descs[None])
        self.assertTrue(all(len(d) <= 512 for d in descs.values()))
        shorts = [a[0] for n, a, k in api.calls if n == "short"]
        self.assertTrue(all(len(s) <= 120 for s in shorts))
        cmds = [a for n, a, k in api.calls if n == "cmds"]
        admin = [c for c in cmds if c[2] == {"type": "chat", "chat_id": 7}]
        self.assertEqual(len(admin), 1)
        self.assertIn("admin", [c["command"] for c in admin[0][0]])
        public = [c for c in cmds if c[2] is None]
        self.assertTrue(all("admin" not in [x["command"] for x in c[0]] for c in public))
        self.assertIn(("menu", ({"type": "commands"},), {}), api.calls)

    def test_failures_are_reported_not_raised(self):
        problems = setup_profile(RecordingAPI(fail_on={"menu"}), Config())
        self.assertEqual(len(problems), 1)
        self.assertIn("menu button", problems[0])

    def test_command_descriptions_fit_telegram_limits_in_all_languages(self):
        for lang in LANGUAGES:
            for c in commands_for(lang):
                self.assertTrue(1 <= len(c["description"]) <= 256)
                self.assertTrue(c["command"].islower())


if __name__ == "__main__":
    unittest.main()
