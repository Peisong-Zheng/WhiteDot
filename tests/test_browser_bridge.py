import http.client
import json
import secrets
import unittest

from whitedot.browser_bridge import BrowserBridge, MAX_BODY, MAX_CHARS
from whitedot.types import Issue


ORIGIN = "chrome-extension://" + "a" * 32
FIELD = {"browser": "chrome", "field": "fixture-id", "text": "🙂 teh"}


class BridgeStateTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.bridge = BrowserBridge(secrets.token_urlsafe(32), clock=lambda: self.now)
        self.issue = Issue(2, 5, "teh", ("the",), "拼写")

    def test_publishes_only_matching_target_and_revision(self):
        self.assertFalse(self.bridge._sync(FIELD)["active"])
        target = self.bridge.snapshot("chrome")
        self.assertEqual(target.token, "web:chrome:fixture-id")
        self.bridge.publish(target, [self.issue, Issue(0, 3, "bad", ("x",), "wrong anchor")])
        reply = self.bridge._sync(FIELD)
        self.assertTrue(reply["active"])
        self.assertEqual(reply["issues"], [{"start": 2, "end": 5, "original": "teh",
                                            "suggestions": ["the"], "explanation": "拼写"}])
        self.assertFalse(self.bridge._sync({**FIELD, "text": "new"})["active"])
        self.bridge.publish(target, [self.issue])
        self.assertFalse(self.bridge._sync(FIELD)["active"])
        self.bridge.publish(self.bridge.snapshot("chrome"), [])
        self.assertTrue(self.bridge._sync(FIELD)["active"])
        self.bridge.publish(None, [])
        self.assertFalse(self.bridge._sync(FIELD)["active"])

    def test_clears_only_matching_field_and_browser(self):
        self.bridge._sync(FIELD)
        self.bridge._sync({**FIELD, "field": "second"})
        self.bridge._sync({**FIELD, "browser": "edge"})
        self.bridge._sync({"browser": "chrome", "field": "fixture-id", "clear": True})
        self.assertEqual(self.bridge.snapshot("chrome").token, "web:chrome:second")
        self.bridge._sync({"browser": "chrome", "field": "second", "clear": True})
        self.assertIsNone(self.bridge.snapshot("chrome"))
        self.assertIsNotNone(self.bridge.snapshot("edge"))

    def test_expiry_and_pause_clear_text_and_approval(self):
        self.bridge._sync(FIELD)
        self.bridge.publish(self.bridge.snapshot("chrome"), [self.issue])
        self.now += 2.0
        self.assertIsNone(self.bridge.snapshot("chrome"))
        self.assertFalse(self.bridge._sync(FIELD)["active"])
        self.bridge.pause(True)
        self.assertTrue(self.bridge._sync(FIELD)["paused"])
        self.assertIsNone(self.bridge.snapshot("chrome"))
        self.bridge.pause(False)
        self.assertFalse(self.bridge._sync(FIELD)["active"])

    def test_malformed_or_excessive_fields(self):
        for bad in [
            None, [], {}, {**FIELD, "clear": True}, {**FIELD, "text": "\udc00"},
            {**FIELD, "field": "x" * 129}, {**FIELD, "browser": ["edge"]},
            {**FIELD, "text": "x" * (MAX_CHARS + 1)}, {**FIELD, "extra": 1},
        ]:
            with self.subTest(representation=type(bad).__name__), self.assertRaises(ValueError):
                self.bridge._sync(bad)
        self.assertIsNone(self.bridge.snapshot("chrome"))


class BridgeHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = secrets.token_urlsafe(32)
        cls.bridge = BrowserBridge(cls.key, port=0)
        cls.bridge.start()
        cls.port = cls.bridge._server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.bridge.stop()

    def request(self, method="POST", headers=None, body=None, path="/v1/sync"):
        params = {"Origin": ORIGIN, "Authorization": "Bearer " + self.key, "Content-Type": "application/json"}
        params.update(headers or {})
        raw = json.dumps(FIELD).encode() if body is None else body
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, raw, params)
            response = connection.getresponse()
            return response.status, dict(response.headers), response.read()
        finally:
            connection.close()

    def test_authorized_json_and_preflight(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(json.loads(body)["issues"], [])
        status, headers, _ = self.request("OPTIONS", {"Authorization": "",
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type, authorization",
            "Access-Control-Request-Private-Network": "true"})
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Private-Network"], "true")

    def test_denies_wrong_host_origin_path_key_or_format(self):
        for method, headers, path, status in [
            ("POST", {"Host": "example.test"}, "/v1/sync", 403),
            ("POST", {"Origin": "https://example.test"}, "/v1/sync", 403),
            ("POST", {"Origin": ORIGIN + ".bad"}, "/v1/sync", 403),
            ("POST", {"Authorization": "Bearer wrong"}, "/v1/sync", 401),
            ("POST", {}, "/v1/sync/other", 404),
            ("POST", {"Content-Type": "text/plain"}, "/v1/sync", 415),
            ("POST", {"Content-Length": str(MAX_BODY + 1)}, "/v1/sync", 413),
            ("POST", {"Content-Length": "garbage"}, "/v1/sync", 400),
            ("OPTIONS", {"Access-Control-Request-Method": "GET"}, "/v1/sync", 403),
            ("OPTIONS", {"Origin": "null", "Access-Control-Request-Method": "POST"}, "/v1/sync", 403),
        ]:
            with self.subTest(method=method, status=status):
                actual, received, _ = self.request(method, headers, path=path)
                self.assertEqual(actual, status)
                if status == 403:
                    self.assertNotIn("Access-Control-Allow-Origin", received)
        self.assertEqual(self.request(body=b"not-json")[0], 400)

    def test_paused_server_does_not_parse_body(self):
        self.bridge.pause(True)
        try:
            status, _, body = self.request(body=b"deliberately-invalid")
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["paused"])
            self.assertIsNone(self.bridge.snapshot("chrome"))
        finally:
            self.bridge.pause(False)
