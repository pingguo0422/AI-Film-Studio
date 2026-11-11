"""Provider-neutral model adapters, including an OpenAI-compatible HTTP adapter.

Secrets are read from environment at construction time and are never serialized.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os
import urllib.error
import urllib.request
from typing import Any, Protocol

@dataclass(frozen=True)
class ModelRequest:
    purpose: str
    input: dict[str, Any]
    model_key: str | None = None
    response_format: str = "json"
    correlation_id: str | None = None

@dataclass(frozen=True)
class ModelResponse:
    provider_key: str
    model_key: str
    output: dict[str, Any]
    request_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

class ModelAdapterError(RuntimeError): pass
class ModelUnavailableError(ModelAdapterError): pass
class ModelAuthenticationError(ModelAdapterError): pass
class ModelRateLimitError(ModelAdapterError):
    def __init__(self, message: str, retry_after_seconds: float | None = None):
        super().__init__(message); self.retry_after_seconds = retry_after_seconds
class ModelOutputError(ModelAdapterError): pass

class ModelAdapter(Protocol):
    provider_key: str
    model_key: str
    def generate(self, request: ModelRequest) -> ModelResponse: ...

class ModelAdapterRegistry:
    def __init__(self) -> None: self._adapters: dict[tuple[str, str], ModelAdapter] = {}
    def register(self, adapter: ModelAdapter) -> None:
        key = (adapter.provider_key.strip().casefold(), adapter.model_key.strip())
        if not all(key): raise ValueError("adapter provider_key and model_key are required")
        if key in self._adapters: raise ValueError(f"model adapter already registered: {key[0]}/{key[1]}")
        self._adapters[key] = adapter
    def resolve(self, provider_key: str, model_key: str) -> ModelAdapter:
        key = (provider_key.strip().casefold(), model_key.strip())
        try: return self._adapters[key]
        except KeyError as exc: raise ModelUnavailableError(f"no adapter registered for {key[0]}/{key[1]}") from exc
    def generate(self, provider_key: str, request: ModelRequest) -> ModelResponse:
        if not request.model_key: raise ValueError("request.model_key is required for explicit adapter selection")
        response = self.resolve(provider_key, request.model_key).generate(request)
        if not isinstance(response, ModelResponse): raise ModelOutputError("adapter must return ModelResponse")
        if response.provider_key.casefold() != provider_key.casefold() or response.model_key != request.model_key:
            raise ModelOutputError("adapter response provider/model identity does not match requested route")
        if not isinstance(response.output, dict): raise ModelOutputError("model output must be a JSON object")
        return response

class OpenAICompatibleAdapter:
    """Chat-completions-compatible endpoint; actual network calls occur only on generate()."""
    provider_key = "openai_compatible"
    def __init__(self, *, model_key: str, base_url: str | None = None, api_key: str | None = None,
                 timeout_seconds: float = 30.0):
        self.model_key = model_key
        self.base_url = (base_url or os.getenv("AFS_MODEL_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("AFS_MODEL_API_KEY")
        self.timeout_seconds = timeout_seconds
        if not model_key or timeout_seconds <= 0: raise ValueError("model_key and positive timeout are required")
    def generate(self, request: ModelRequest) -> ModelResponse:
        if request.model_key != self.model_key: raise ModelOutputError("request model does not match adapter")
        if not self.api_key: raise ModelAuthenticationError("AFS_MODEL_API_KEY is not configured")
        body = {"model": self.model_key, "messages": [
            {"role": "system", "content": "Return only a JSON object. Follow the requested schema exactly."},
            {"role": "user", "content": json.dumps({"purpose": request.purpose, "input": request.input}, ensure_ascii=False)}],
            "response_format": {"type": "json_object"}}
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403): raise ModelAuthenticationError("model provider rejected credentials") from exc
            if exc.code == 429: raise ModelRateLimitError("model provider rate limited request") from exc
            raise ModelUnavailableError(f"model provider HTTP error {exc.code}") from exc
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise ModelUnavailableError("model provider request failed or timed out") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ModelOutputError("provider returned invalid JSON envelope") from exc
        try:
            choice = payload["choices"][0]["message"]["content"]
            output = json.loads(choice) if isinstance(choice, str) else choice
            if not isinstance(output, dict): raise ValueError
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelOutputError("provider response did not contain a JSON object message") from exc
        return ModelResponse(self.provider_key, self.model_key, output, payload.get("id"),
                             payload.get("usage") or {}, {"mode": "live_http"})

class FakeModelAdapter:
    """Deterministic test adapter. Never represents a live model call."""
    def __init__(self, *, model_key: str, output: dict[str, Any], provider_key: str = "fake"):
        self.provider_key, self.model_key, self.output = provider_key, model_key, output
        self.calls: list[ModelRequest] = []
    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        return ModelResponse(self.provider_key, self.model_key, dict(self.output), metadata={"mode": "test_fake"})
