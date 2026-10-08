import re
import unittest

from shopbot.i18n import DEFAULT_LANG, LANGUAGES, TEXTS, t
from shopbot.orders import STATUSES

FIELD = re.compile(r"{(\w+)}")


class I18nTests(unittest.TestCase):
    def test_all_languages_have_same_keys(self):
        base = set(TEXTS[DEFAULT_LANG])
        for lang in LANGUAGES:
            self.assertEqual(base, set(TEXTS[lang]), lang)

    def test_placeholders_match_english(self):
        for key, en in TEXTS["en"].items():
            for lang in ("fa", "tr"):
                self.assertEqual(set(FIELD.findall(en)), set(FIELD.findall(TEXTS[lang][key])), f"{lang}:{key}")

    def test_status_and_payment_labels_exist(self):
        for lang in LANGUAGES:
            for s in STATUSES:
                self.assertIn(f"st_{s}", TEXTS[lang])
            for p in ("cod", "bank"):
                self.assertIn(f"pay_{p}_short", TEXTS[lang])

    def test_unknown_language_falls_back(self):
        self.assertEqual(t("xx", "btn_menu"), TEXTS["en"]["btn_menu"])


if __name__ == "__main__":
    unittest.main()
