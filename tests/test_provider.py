import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from whitedot.provider import MAX_TEXT, PRESETS, Provider, ProviderConfig, ProviderError
from whitedot.settings import Settings, StorageError


TOKEN = "unit-test-placeholder"


def response(content, reason="stop"):
    data = {"choices": [{"message": {"content": content}, "finish_reason": reason}]}
    return io.BytesIO(json.dumps(data).encode())


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.api = Provider(PRESETS["DeepSeek"], TOKEN)
        self.opener = self.enterContext(patch("whitedot.provider.build_opener")).return_value

    def test_connection_probe_model_and_disabled_thinking(self):
        self.opener.open.return_value = response('{"issues":[]}')
        self.api.validate()
        req = self.opener.open.call_args.args[0]
        payload = json.loads(req.data)
        self.assertEqual(req.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["model"], "deepseek-flash")
        self.assertEqual(req.get_header("Authorization"), "Bearer " + TOKEN)

    def test_deepseek_blank_json_retried_only_once(self):
        self.opener.open.side_effect = [response("  "), response('{"issues":[]}')]
        self.api.validate()
        self.assertEqual(self.opener.open.call_count, 2)
        self.opener.open.reset_mock()
        self.opener.open.side_effect = [response(""), response("")]
        with self.assertRaises(ProviderError):
            self.api.validate()
        self.assertEqual(self.opener.open.call_count, 2)

    def test_response_offsets_and_overlaps(self):
        text = "🐋 She go there. I go too. Tehh day is nice."
        self.opener.open.return_value = response(json.dumps({"issues": [
            {"original": "not there", "suggestions": ["missing"], "occurrence": 1},
            {"original": "go", "suggestions": ["goes"], "occurrence": 1},
            {"original": "go", "suggestions": ["goes"]},  # ambiguous
            {"original": "Tehh", "suggestions": ["The", "The"], "explanation": "拼写"},
            {"original": "Tehh day", "suggestions": ["The day"]},
        ]}))
        issues = self.api.check(text)
        self.assertEqual([(i.start, i.end) for i in issues], [(6, 8), (26, 30)])
        self.assertEqual(issues[-1].suggestions, ("The",))
        for issue in issues:
            self.assertEqual(text[issue.start:issue.end], issue.original)

    def test_repeated_occurrence_at_second_literal(self):
        self.opener.open.return_value = response(
            '{"issues":[{"original":"lead","occurrence":2,"suggestions":["led"]}]}'
        )
        self.assertEqual(self.api.check("I lead. He lead.")[0].start, 11)

    def test_rewrite_preserves_linebreaks_indentation_and_non_english(self):
        self.opener.open.return_value = response('{"lines":["She goes.","The end."]}')
        original = "\tShe go.  \r\n\r\n只有中文。\nTeh end.\n"
        expected = "\tShe goes.  \r\n\r\n只有中文。\nThe end.\n"
        self.assertEqual(self.api.rewrite(original), expected)
        req = self.opener.open.call_args.args[0]
        data = json.loads(json.loads(req.data)["messages"][1]["content"])
        self.assertEqual(data["lines"], ["She go.", "Teh end."])

    def test_reject_modified_paragraph_structure(self):
        self.opener.open.return_value = response('{"lines":["Combined."]}')
        with self.assertRaises(ProviderError):
            self.api.rewrite("First\nSecond")

    def test_skip_non_english_and_limit_before_submission(self):
        self.assertEqual(self.api.check("今天 🌳"), [])
        self.assertEqual(self.api.rewrite("今天 🌳"), "今天 🌳")
        with self.assertRaises(ProviderError):
            self.api.check("x" * (MAX_TEXT + 1))
        self.opener.open.assert_not_called()

    def test_unsupported_content_or_truncation_is_reported(self):
        for content, reason in (("garbage", "stop"), ('{"issues":[]}', "length"),
                                ('{"issues":"invalid"}', "stop")):
            with self.subTest(content=content, reason=reason):
                self.opener.open.return_value = response(content, reason)
                with self.assertRaises(ProviderError):
                    self.api.check("World.")

    def test_reject_credential_redirect_or_server_echo(self):
        for code in (301, 302, 307, 308, 401, 429, 500):
            with self.subTest(code=code):
                self.opener.open.side_effect = HTTPError(
                    self.api.url, code, TOKEN, {}, io.BytesIO(TOKEN.encode())
                )
                with self.assertRaises(ProviderError) as failure:
                    self.api.validate()
                self.assertNotIn(TOKEN, str(failure.exception))

    def test_reject_remote_plain_http_and_authority_credentials(self):
        for url in ("http://example.org", "https://user@api.example",
                    "https://example.org?v=1", "file:///foo", "https://a:badport"):
            with self.subTest(url=url), self.assertRaises(ProviderError):
                Provider(ProviderConfig("Custom", url, "model"), TOKEN)
        local = Provider(ProviderConfig("Custom", "http://127.0.0.1:11434/v1", "local"), TOKEN)
        self.assertTrue(local.url.endswith("/v1/chat/completions"))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(root) / "WhiteDot" / "settings.json"
        self.settings = Settings(self.path)
        self.secrets = {}
        self.vault = Mock()
        self.vault.get_password.side_effect = lambda service, user: self.secrets.get(user)
        self.vault.set_password.side_effect = lambda service, user, value: self.secrets.update({user: value})
        self.vault.delete_password.side_effect = lambda service, user: self.secrets.pop(user)
        self.backend = self.enterContext(patch("whitedot.settings._vault", return_value=self.vault))

    def test_first_run_and_roundtrip_without_plaintext(self):
        self.assertEqual(self.settings.config, PRESETS["DeepSeek"])
        self.assertEqual(self.settings.get_key(), "")
        self.backend.assert_not_called()
        self.settings.set("position", [21, 42])
        self.settings.save_provider(PRESETS["OpenAI"], TOKEN)
        restored = Settings(self.path)
        self.assertEqual(restored.get_key(), TOKEN)
        self.assertEqual(restored.config, PRESETS["OpenAI"])
        self.assertEqual(restored.get("position"), [21, 42])
        self.assertNotIn(TOKEN, self.path.read_text())
        different_endpoint = ProviderConfig("OpenAI", "https://other.example/v1", "model")
        self.assertEqual(restored.get_key(different_endpoint), "")

    def test_failed_vault_save_preserves_preferences(self):
        self.vault.set_password.side_effect = RuntimeError(TOKEN)
        with self.assertRaises(StorageError) as failure:
            self.settings.save_provider(PRESETS["OpenAI"], TOKEN)
        self.assertNotIn(TOKEN, str(failure.exception))
        self.assertFalse(self.path.exists())
        self.assertEqual(self.settings.config, PRESETS["DeepSeek"])

    def test_failed_config_write_restores_key(self):
        self.settings.save_provider(PRESETS["OpenAI"], "previous")
        with patch.object(self.settings, "_write", side_effect=StorageError("test")):
            with self.assertRaises(StorageError):
                self.settings.save_provider(PRESETS["OpenAI"], TOKEN)
        self.assertEqual(self.settings.get_key(), "previous")

    def test_invalid_pref_file(self):
        self.path.parent.mkdir()
        self.path.write_text("invalid")
        with self.assertRaises(StorageError):
            Settings(self.path)
