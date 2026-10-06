from __future__ import annotations

import json
import math
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from ..errors import DataError, ValidationError

DEFAULT_MODEL = "deepseek-v4-flash-0731"


class ModelError(DataError):
    pass


class ModelAuthError(ModelError):
    pass


class ModelRateLimitError(ModelError):
    pass


class ModelConnectionError(ModelError):
    pass


class ModelResponseError(ModelError):
    pass


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str = DEFAULT_MODEL

    def __post_init__(self):
        try:
            url = urlsplit(self.base_url)
            valid_port = url.port is None or 1 <= url.port <= 65535
        except ValueError:
            raise ValidationError("invalid model endpoint") from None
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or not valid_port
                or any(c.isspace() for c in self.base_url)):
            raise ValidationError("model endpoint must be HTTPS without userinfo, query or fragment")
        if not re.fullmatch(r"[\x21-\x7e]+", self.api_key):
            raise ValidationError("invalid model API key format")
        if not re.fullmatch(r"[A-Za-z0-9_./:-]{1,128}", self.model):
            raise ValidationError("invalid model identifier")
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[:-len("/chat/completions")]
        object.__setattr__(self, "base_url", base)

    @property
    def endpoint(self):
        return self.base_url + "/chat/completions"


def load_model_config(path: str | Path = "test_api.txt", model: str = DEFAULT_MODEL) -> ModelConfig:
    """Read the user's local Base URL / API KEY file without copying its secret."""
    try:
        with Path(path).open("r", encoding="utf-8-sig") as stream:
            content = stream.read(16_385)
    except (OSError, UnicodeError):
        raise ValidationError("cannot read model config file") from None
    if len(content) > 16_384:
        raise ValidationError("model config file is too large")
    values = {}
    aliases = {"baseurl": "base_url", "apibase": "base_url", "apikey": "api_key"}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z_ ]+)\s*[:=：]\s*(.+)", line)
        if not match:
            raise ValidationError("expected Base URL and API KEY entries in model config")
        key = aliases.get(re.sub(r"[_ ]", "", match[1]).lower())
        if not key or key in values:
            raise ValidationError("unknown or duplicate model config entry")
        value = match[2].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    if set(values) != {"base_url", "api_key"}:
        raise ValidationError("model config requires Base URL and API KEY")
    return ModelConfig(**values, model=model)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ChatHTTPTransport:
    """One request; no automatic retries, redirects, or implicit model fallback."""

    def __call__(self, config: ModelConfig, payload: dict, timeout: float) -> dict:
        request = urllib.request.Request(
            config.endpoint, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + config.api_key,
                     "Content-Type": "application/json", "Accept": "application/json"},
            method="POST")
        deadline = time.monotonic() + timeout
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
                chunks, size = [], 0
                while True:
                    if time.monotonic() >= deadline:
                        raise ModelConnectionError("model response deadline exceeded")
                    chunk = response.read1(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise ModelResponseError("model response exceeds size limit")
                    chunks.append(chunk)
                if time.monotonic() >= deadline:
                    raise ModelConnectionError("model response deadline exceeded")
                return json.loads(b"".join(chunks))
        except urllib.error.HTTPError as exc:
            # Never echo response bodies: gateways may include secrets or request headers.
            if exc.code in {401, 403}:
                raise ModelAuthError("model authentication or access denied") from None
            if exc.code == 429:
                raise ModelRateLimitError("model rate limit or quota exceeded") from None
            raise ModelError(f"model endpoint returned HTTP {exc.code}; verify model access and endpoint") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            raise ModelConnectionError("model connection failed or timed out") from None
        except (ValueError, UnicodeError):
            raise ModelResponseError("model endpoint returned invalid JSON") from None


@dataclass(frozen=True)
class ChatResult:
    requested_model: str
    returned_model: str | None
    content: str
    finish_reason: str
    request_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: int


class ChatModelAdapter:
    """Text chat adapter; tool execution and agent loops are deliberately separate."""

    def __init__(self, config: ModelConfig, transport=None):
        self.config = config
        self._transport = transport or ChatHTTPTransport()

    def complete(self, messages: list[dict], *, max_tokens=256, timeout=30.0) -> ChatResult:
        if type(max_tokens) is not int or not 1 <= max_tokens <= 4096:
            raise ValidationError("max_tokens must be between 1 and 4096")
        if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
                or not math.isfinite(timeout) or not 0 < timeout <= 120):
            raise ValidationError("timeout must be between 0 and 120 seconds")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 64:
            raise ValidationError("between 1 and 64 text messages required")
        clean_messages = []
        for message in messages:
            if (not isinstance(message, dict) or set(message) != {"role", "content"}
                    or message["role"] not in {"system", "user", "assistant"}
                    or not isinstance(message["content"], str) or not message["content"].strip()):
                raise ValidationError("only system/user/assistant text messages are supported")
            clean_messages.append(dict(message))
        if sum(len(m["content"]) for m in clean_messages) > 32_000:
            raise ValidationError("message content exceeds adapter input limit")
        payload = {"model": self.config.model, "messages": clean_messages, "max_tokens": max_tokens,
                   "temperature": 0, "stream": False, "enable_thinking": False}
        started = time.monotonic()
        response = self._transport(self.config, payload, timeout)
        elapsed = time.monotonic() - started
        if elapsed > timeout:
            raise ModelConnectionError("late model response discarded")
        if not isinstance(response, dict) or "error" in response:
            raise ModelResponseError("model returned an error response")
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ModelResponseError("expected one chat completion choice")
        choice = choices[0]
        message = choice.get("message")
        if (not isinstance(message, dict) or message.get("role") != "assistant"
                or message.get("tool_calls") or not isinstance(message.get("content"), str)
                or not message["content"].strip()):
            raise ModelResponseError("expected nonempty assistant text; no tool execution supported")
        finish = choice.get("finish_reason")
        if finish not in {"stop", "length"}:
            raise ModelResponseError("model did not return a supported completion status")
        usage = response.get("usage")
        if usage is None:
            usage = {}
        if not isinstance(usage, dict):
            raise ModelResponseError("invalid model token usage")
        tokens = []
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(name)
            if value is not None and (type(value) is not int or value < 0):
                raise ModelResponseError("invalid model token usage")
            tokens.append(value)
        for name in ("id", "model"):
            if response.get(name) is not None and not isinstance(response[name], str):
                raise ModelResponseError("invalid model response metadata")
        return ChatResult(self.config.model, response.get("model"), message["content"], finish,
                          response.get("id"), *tokens, round(elapsed * 1000))
