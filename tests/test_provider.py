import io
import json
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

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
        self.assertIn("explanation in plain English", payload["messages"][0]["content"])

    def test_deletion_suggestion_for_repeated_word(self):
        draft = "We can can leave."
        self.opener.open.return_value = response(
            '{"issues":[{"original":"can ","occurrence":2,"suggestions":[""]}]}'
        )
        issue, = self.api.check(draft)
        self.assertEqual(issue.suggestions, ("",))
        self.assertEqual(draft[:issue.start] + issue.suggestions[0] + draft[issue.end:], "We can leave.")

    def test_connection_problems_have_actionable_messages(self):
        for failure, hint in ((TimeoutError(), "timed out"), (URLError(TimeoutError()), "timed out"),
                              (URLError(ssl.SSLCertVerificationError()), "certificate"),
                              (URLError("unreachable"), "connection")):
            with self.subTest(failure=failure):
                self.opener.open.side_effect = failure
                with self.assertRaisesRegex(ProviderError, hint):
                    self.api.validate()

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
            {"original": "Tehh", "suggestions": ["The", "The"], "explanation": "Spelling."},
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

    def test_occurrence_ignores_matches_inside_other_words_or_identifiers(self):
        draft = "This is sample_is. The results is clear."
        self.opener.open.return_value = response(
            '{"issues":[{"original":"is","occurrence":2,"suggestions":["are"]}]}'
        )
        issue, = self.api.check(draft)
        self.assertEqual(issue.start, draft.rindex("is"))
        self.assertEqual(draft[:issue.start] + "are" + draft[issue.end:],
                         "This is sample_is. The results are clear.")

    def test_rewrite_preserves_linebreaks_indentation_and_non_english(self):
        self.opener.open.return_value = response('{"lines":["She goes.","The end."]}')
        original = "\tShe go.  \r\n\r\n\N{GREEK CAPITAL LETTER DELTA}\nTeh end.\n"
        expected = "\tShe goes.  \r\n\r\n\N{GREEK CAPITAL LETTER DELTA}\nThe end.\n"
        self.assertEqual(self.api.rewrite(original), expected)
        req = self.opener.open.call_args.args[0]
        data = json.loads(json.loads(req.data)["messages"][1]["content"])
        self.assertEqual(data["lines"], ["She go.", "Teh end."])

    def test_reject_modified_paragraph_structure(self):
        self.opener.open.return_value = response('{"lines":["Combined."]}')
        with self.assertRaises(ProviderError):
            self.api.rewrite("First\nSecond")

    def test_skip_non_english_and_limit_before_submission(self):
        self.assertEqual(self.api.check("\N{GREEK CAPITAL LETTER DELTA} 🌳"), [])
        self.assertEqual(self.api.rewrite("\N{GREEK CAPITAL LETTER DELTA} 🌳"), "\N{GREEK CAPITAL LETTER DELTA} 🌳")
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

    def test_switch_providers_recovers_custom_endpoint_model_and_key_after_upgrade(self):
        custom = ProviderConfig("Custom", "https://model.example/v1", "my-editor")
        self.settings.save_provider(custom, TOKEN)
        legacy = json.loads(self.path.read_text())
        del legacy["profiles"]
        self.path.write_text(json.dumps(legacy))
        upgraded = Settings(self.path)
        upgraded.save_provider(PRESETS["OpenAI"], "second-key")
        restored = Settings(self.path)
        self.assertEqual(restored.config, PRESETS["OpenAI"])
        self.assertEqual(restored.config_for("Custom"), custom)
        self.assertEqual(restored.get_key(restored.config_for("Custom")), TOKEN)
        self.assertNotIn(TOKEN, self.path.read_text())
        self.assertNotIn("second-key", self.path.read_text())

    def test_incomplete_account_index_can_be_repaired_by_validating_a_key(self):
        self.settings.set("accounts", None)
        self.assertEqual(self.settings.get_key(), "")
        self.settings.save_provider(PRESETS["DeepSeek"], TOKEN)
        self.assertEqual(self.settings.get_key(), TOKEN)

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
