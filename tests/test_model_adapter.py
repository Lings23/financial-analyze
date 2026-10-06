import contextlib
import io
import json
import unittest
import urllib.error
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from stock_research.__main__ import main
from stock_research.errors import ValidationError
from stock_research.model_adapters.chat import (
    DEFAULT_MODEL, ChatHTTPTransport, ChatModelAdapter, ModelAuthError, ModelConfig,
    ModelConnectionError, ModelError, ModelRateLimitError, ModelResponseError, load_model_config,
)


def completion(**changes):
    result = {"id": "test-request", "model": DEFAULT_MODEL,
              "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}}
    result.update(changes)
    return result


class ModelAdapterTests(unittest.TestCase):
    def setUp(self):
        self.config = ModelConfig("https://models.example.invalid/compatible-mode/v1", "sk-synthetic-only")
        self.messages = [{"role": "user", "content": "Reply OK"}]

    def test_load_actual_file_format_without_logging_secret(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "api.txt"
            path.write_text("\ufeffBase URL:https://models.example.invalid/compatible-mode/v1\nAPI KEY:sk-synthetic-only\n", encoding="utf-8")
            config = load_model_config(path)
        self.assertEqual(config.model, DEFAULT_MODEL)
        self.assertEqual(config.api_key, "sk-synthetic-only")
        self.assertNotIn("sk-synthetic-only", repr(config))
        self.assertTrue(config.endpoint.endswith("/v1/chat/completions"))

    def test_duplicate_or_unknown_configuration_fails_without_echo(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "api.txt"
            for content in ("API KEY:sk-synthetic-only\nAPI KEY:sk-synthetic-only",
                            "secret:sk-synthetic-only", "bad-format-sk-synthetic-only"):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValidationError) as caught:
                    load_model_config(path)
                self.assertNotIn("sk-synthetic-only", str(caught.exception))

    def test_insecure_or_credential_bearing_urls_rejected(self):
        for endpoint in ("http://models.example.invalid/v1", "https://user:password@example.invalid/v1",
                         "https://example.invalid/v1?key=secret", "https://example.invalid/v1#secret"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValidationError):
                replace(self.config, base_url=endpoint)
        with self.assertRaises(ValidationError):
            replace(self.config, api_key="key\r\nInjected: header")

    def test_full_completion_url_not_duplicated(self):
        config = replace(self.config, base_url=self.config.endpoint + "/")
        self.assertEqual(config.endpoint, self.config.endpoint)

    def test_requested_model_and_safe_payload(self):
        transport = MagicMock(return_value=completion())
        result = ChatModelAdapter(self.config, transport).complete(self.messages, max_tokens=16)
        config, payload, timeout = transport.call_args.args
        self.assertEqual(payload["model"], "deepseek-v4-flash-0731")
        self.assertFalse(payload["enable_thinking"])
        self.assertFalse(payload["stream"])
        self.assertNotIn(config.api_key, json.dumps(payload))
        self.assertEqual(result.content, "OK")
        self.assertEqual(result.total_tokens, 11)

    def test_invalid_requests_do_not_call_transport(self):
        transport = MagicMock()
        adapter = ChatModelAdapter(self.config, transport)
        for kwargs in ({"max_tokens": 0}, {"max_tokens": True}, {"timeout": float("nan")}, {"timeout": 121}):
            with self.assertRaises(ValidationError):
                adapter.complete(self.messages, **kwargs)
        with self.assertRaises(ValidationError):
            adapter.complete([{"role": "tool", "content": "untrusted"}])
        transport.assert_not_called()

    def test_unknown_usage_is_not_zero(self):
        result = ChatModelAdapter(self.config, lambda *_: completion(usage=None)).complete(self.messages)
        self.assertIsNone(result.total_tokens)

    def test_bad_usage_and_response_schema(self):
        for response in (completion(usage={"total_tokens": True}), completion(choices=[]),
                         {"error": "sk-synthetic-only"}, completion(model=123)):
            with self.assertRaises(ModelResponseError) as caught:
                ChatModelAdapter(self.config, lambda *_: response).complete(self.messages)
            self.assertNotIn("sk-synthetic-only", str(caught.exception))

    def test_tool_calls_are_not_executed_or_reported_as_text_success(self):
        response = completion(choices=[{"message": {"role": "assistant", "content": None,
                              "tool_calls": [{"function": {"name": "anything"}}]}, "finish_reason": "tool_calls"}])
        with self.assertRaises(ModelResponseError):
            ChatModelAdapter(self.config, lambda *_: response).complete(self.messages)

    def test_truncation_retains_explicit_finish_reason(self):
        response = completion()
        response["choices"][0]["finish_reason"] = "length"
        result = ChatModelAdapter(self.config, lambda *_: response).complete(self.messages)
        self.assertEqual(result.finish_reason, "length")

    def test_http_headers_and_response_normalization(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read1.side_effect = [json.dumps(completion()).encode(), b""]
        opener = MagicMock()
        opener.open.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            result = ChatModelAdapter(self.config).complete(self.messages)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, self.config.endpoint)
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-synthetic-only")
        self.assertEqual(result.content, "OK")

    def test_http_errors_redacted_and_not_retried(self):
        for status, error in ((401, ModelAuthError), (403, ModelAuthError), (429, ModelRateLimitError),
                              (302, ModelError), (500, ModelError)):
            opener = MagicMock()
            opener.open.side_effect = urllib.error.HTTPError(self.config.endpoint, status, "sk-synthetic-only", {}, None)
            with patch("urllib.request.build_opener", return_value=opener), self.assertRaises(error) as caught:
                ChatHTTPTransport()(self.config, {}, 1)
            self.assertNotIn("sk-synthetic-only", str(caught.exception))
            self.assertEqual(opener.open.call_count, 1)

    def test_connection_error_is_redacted(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.URLError("sk-synthetic-only")
        with patch("urllib.request.build_opener", return_value=opener), self.assertRaises(ModelConnectionError) as caught:
            ChatHTTPTransport()(self.config, {}, 1)
        self.assertNotIn("sk-synthetic-only", str(caught.exception))

    def test_cli_check_needs_no_database_and_preserves_model_identity(self):
        result = ChatModelAdapter(self.config, lambda *_: completion()).complete(self.messages)
        output = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), patch(
                "stock_research.model_adapters.chat.load_model_config", return_value=self.config), patch(
                "stock_research.model_adapters.chat.ChatModelAdapter.complete", return_value=result), contextlib.redirect_stdout(output):
            self.assertEqual(main(["llm-check"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "verified")
        self.assertNotIn(self.config.api_key, output.getvalue())

    def test_cli_check_fails_on_unexpected_model_or_truncation(self):
        base = ChatModelAdapter(self.config, lambda *_: completion()).complete(self.messages)
        for result in (replace(base, returned_model="different-model"), replace(base, finish_reason="length")):
            with patch("stock_research.model_adapters.chat.load_model_config", return_value=self.config), patch(
                    "stock_research.model_adapters.chat.ChatModelAdapter.complete", return_value=result), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["llm-check"]), 2)
