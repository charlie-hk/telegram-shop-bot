"""The HTTP client against a local stub server that behaves like api.telegram.org."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from shopbot.api import TelegramAPI, TelegramError


class Stub(BaseHTTPRequestHandler):
    calls = []
    flood_once = True

    def log_message(self, *a):
        pass

    def _reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        method = self.path.rsplit("/", 1)[-1]
        Stub.calls.append((self.path, self.headers.get("Content-Type"), raw))
        if method == "getMe":
            return self._reply(200, {"ok": True, "result": {"username": "demo_bot"}})
        if method == "flood":
            if Stub.flood_once:
                Stub.flood_once = False
                return self._reply(429, {"ok": False, "error_code": 429, "description": "Too Many Requests",
                                         "parameters": {"retry_after": 0}})
            return self._reply(200, {"ok": True, "result": "ok after retry"})
        if method == "sendMessage":
            return self._reply(400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})
        if method == "sendPhoto":
            return self._reply(200, {"ok": True, "result": {"message_id": 2, "photo": [{"file_id": "A"}, {"file_id": "B"}]}})
        if method in ("setMyDescription", "setMyCommands", "setChatMenuButton", "setMyShortDescription"):
            return self._reply(200, {"ok": True, "result": True})
        if method == "sendDocument":
            return self._reply(200, {"ok": True, "result": {"message_id": 1}})
        self._reply(404, {"ok": False, "error_code": 404, "description": "Not Found"})


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.api = TelegramAPI("123:ABC", base_url=f"http://127.0.0.1:{cls.server.server_port}", timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Stub.calls.clear()
        Stub.flood_once = True

    def test_success_returns_result_and_drops_none_params(self):
        self.assertEqual(self.api.call("getMe", foo=None)["username"], "demo_bot")
        path, ctype, raw = Stub.calls[0]
        self.assertEqual(path, "/bot123:ABC/getMe")
        self.assertEqual(ctype, "application/json")
        self.assertEqual(json.loads(raw), {})

    def test_api_error_becomes_exception(self):
        with self.assertRaises(TelegramError) as cm:
            self.api.send_message(1, "hi")
        self.assertEqual(cm.exception.code, 400)
        self.assertIn("chat not found", cm.exception.description)

    def test_flood_control_is_retried(self):
        self.assertEqual(self.api.call("flood"), "ok after retry")
        self.assertEqual(len(Stub.calls), 2)

    def test_multipart_document(self):
        self.api.send_document(5, "orders.csv", "a,b\n1,2\n".encode(), caption="All")
        _, ctype, raw = Stub.calls[0]
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="chat_id"\r\n\r\n5', raw)
        self.assertIn(b'filename="orders.csv"', raw)
        self.assertIn(b"a,b\n1,2\n", raw)

    def test_photo_upload_returns_file_id_and_sends_keyboard(self):
        kb = {"inline_keyboard": [[{"text": "Go", "callback_data": "x"}]]}
        res = self.api.send_photo_file(5, "banner.png", b"\x89PNGdata", caption="Hi <b>x</b>", reply_markup=kb)
        self.assertEqual(res["photo"][-1]["file_id"], "B")
        _, ctype, raw = Stub.calls[0]
        self.assertTrue(ctype.startswith("multipart/form-data"))
        self.assertIn(b'name="photo"; filename="banner.png"', raw)
        self.assertIn(b"image/png", raw)
        self.assertIn(b'"callback_data": "x"', raw)
        self.assertIn(b"Hi <b>x</b>", raw)

    def test_profile_methods_send_json(self):
        self.api.set_my_description("Hello", "fa")
        self.api.set_my_commands([{"command": "start", "description": "Go"}], scope={"type": "chat", "chat_id": 1})
        self.api.set_chat_menu_button({"type": "commands"})
        bodies = [json.loads(c[2]) for c in Stub.calls]
        self.assertEqual(bodies[0], {"description": "Hello", "language_code": "fa"})
        self.assertEqual(bodies[1]["scope"], {"type": "chat", "chat_id": 1})
        self.assertEqual([c[0].rsplit("/", 1)[-1] for c in Stub.calls],
                         ["setMyDescription", "setMyCommands", "setChatMenuButton"])

    def test_unreachable_server_raises_telegram_error(self):
        dead = TelegramAPI("1:X", base_url="http://127.0.0.1:9", timeout=1, max_retries=0)
        with self.assertRaises(TelegramError):
            dead.call("getMe")

    def test_empty_token_rejected(self):
        with self.assertRaises(ValueError):
            TelegramAPI("")


if __name__ == "__main__":
    unittest.main()
