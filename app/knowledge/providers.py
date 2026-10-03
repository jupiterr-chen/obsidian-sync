"""Model provider abstraction (P4, ADR0006).

Real providers are NOT implemented or registered here: until the user
supplies provider, credentials usage, data-egress scope and budget, every
code path stays offline. Mocks validate protocol behaviour only and must
never be presented as quality or cost evidence (docs/09, docs/13 V4).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


class ProviderNotConfigured(Exception):
    """A provider is named but no credentials/implementation exist."""


class ProviderCallError(Exception):
    """Transport/rate-limit style failure; retryable per `retryable`."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class Usage:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_basis: str = "unknown"  # e.g. "openai:input", "local:cpu"
    extra: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider, "model": self.model,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "cost_basis": self.cost_basis, "extra": self.extra,
        }


class EmbeddingProvider:
    """Protocol: embed(texts) -> (vectors, usage)."""

    name: str = "abstract"
    model: str = "abstract"
    dimensions: int = 0

    def embed(self, texts: Sequence[str]) -> Tuple[List[List[float]], Usage]:
        raise ProviderNotConfigured("embedding provider %r not configured" % self.name)


class ChatProvider:
    """Protocol: complete(prompt) -> (text, usage)."""

    name: str = "abstract"
    model: str = "abstract"

    def complete(self, prompt: str, max_output_tokens: int = 2000
                 ) -> Tuple[str, Usage]:
        raise ProviderNotConfigured("chat provider %r not configured" % self.name)


class EgressNotAllowed(Exception):
    """Real provider call attempted while egress_allowed is false."""


class _HttpProvider:
    """Shared OpenAI-compatible HTTP plumbing (stdlib urllib only)."""

    kind = "openai-compatible"

    def __init__(self, name: str, model: str, base_url: str, api_key: str,
                 egress_allowed: bool = False, timeout: int = 60,
                 max_retries: int = 1):
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.egress_allowed = bool(egress_allowed)
        self.timeout = timeout
        self.max_retries = max_retries
        # T02: optional per-PHYSICAL-ATTEMPT gate; budgeted_embed / the
        # analysis runner attach the ledger so internal retries are gated
        self.attempt_ledger = None

    # ---------------------------------------------------------------- http
    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        import json as json_mod
        import urllib.error
        import urllib.request

        self._require_egress()
        url = "%s%s" % (self.base_url, path)
        body = json_mod.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            self._gate_attempt()  # T02: retries are gated too
            try:
                return self._transport(url, body)
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    pass
                retryable = exc.code in (429, 500, 502, 503, 504)
                last_error = ProviderCallError(
                    "HTTP %d from %s: %s" % (exc.code, path, detail),
                    retryable=retryable)
                if not retryable or attempt >= self.max_retries:
                    raise last_error
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = ProviderCallError(
                    "transport error on %s: %s" % (path, exc), retryable=True)
                if attempt >= self.max_retries:
                    raise last_error
        raise last_error or ProviderCallError("unreachable", retryable=True)

    def _transport(self, url: str, body: bytes) -> Dict[str, Any]:
        """One physical HTTP POST (override seam for tests/transport layers)."""
        import urllib.request

        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Authorization", "Bearer %s" % self.api_key)
        request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _gate_attempt(self) -> None:
        """T02: every PHYSICAL attempt - including internal retries - passes
        the request gate; a budget rejection aborts before any bytes go."""
        if getattr(self, "attempt_ledger", None) is not None:
            from .budget import BudgetExceeded

            try:
                self.attempt_ledger.reserve("http-attempt", 1)
            except BudgetExceeded:
                raise ProviderCallError(
                    "request budget exhausted before attempt", retryable=False)

    def _require_egress(self) -> None:
        if not self.egress_allowed:
            raise EgressNotAllowed(
                "provider %r has egress_allowed=false; refusing to send "
                "anything to %s" % (self.name, self.base_url))


class OpenAICompatibleChat(_HttpProvider, ChatProvider):
    def __init__(self, name: str, model: str, base_url: str, api_key: str,
                 egress_allowed: bool = False, timeout: int = 60,
                 max_retries: int = 1, **_extra):
        super().__init__(name, model, base_url, api_key,
                         egress_allowed=egress_allowed, timeout=timeout,
                         max_retries=max_retries)

    def complete(self, prompt: str, max_output_tokens: int = 2000
                 ) -> Tuple[str, Usage]:
        return self.complete_messages(
            [{"role": "user", "content": prompt}], max_output_tokens)

    def complete_messages(self, messages: List[Dict[str, Any]],
                          max_output_tokens: int = 2000) -> Tuple[str, Usage]:
        response = self._post("/chat/completions", {
            "model": self.model, "messages": messages,
            "max_tokens": max_output_tokens,
        })
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        usage_raw = response.get("usage") or {}
        usage = Usage(
            self.name, self.model,
            input_tokens=int(usage_raw.get("prompt_tokens") or 0),
            output_tokens=int(usage_raw.get("completion_tokens") or 0),
            cost_basis="openai-compatible:chat:%s" % self.model,
            extra={k: v for k, v in usage_raw.items()
                   if k not in ("prompt_tokens", "completion_tokens")},
        )
        return text, usage

    def complete_with_image(self, prompt: str, image_bytes: bytes,
                            mime: str = "image/png",
                            max_output_tokens: int = 2000) -> Tuple[str, Usage]:
        import base64

        encoded = base64.b64encode(image_bytes).decode("ascii")
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": "data:%s;base64,%s" % (mime, encoded)}},
            ],
        }]
        return self.complete_messages(messages, max_output_tokens)


class OpenAICompatibleVision(OpenAICompatibleChat):
    kind = "openai-compatible-vision"


class OpenAICompatibleEmbedding(_HttpProvider, EmbeddingProvider):
    def __init__(self, name: str, model: str, base_url: str, api_key: str,
                 dimensions: int = 0, egress_allowed: bool = False,
                 timeout: int = 60, max_retries: int = 1, **_extra):
        super().__init__(name, model, base_url, api_key,
                         egress_allowed=egress_allowed, timeout=timeout,
                         max_retries=max_retries)
        self.dimensions = int(dimensions or 0)

    def embed(self, texts: Sequence[str]) -> Tuple[List[List[float]], Usage]:
        payload: Dict[str, Any] = {"model": self.model,
                                   "input": list(texts)}
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        response = self._post("/embeddings", payload)
        data = sorted(response.get("data") or [], key=lambda d: d.get("index", 0))
        vectors = [[float(v) for v in item.get("embedding") or []]
                   for item in data]
        usage_raw = response.get("usage") or {}
        usage = Usage(
            self.name, self.model,
            input_tokens=int(usage_raw.get("prompt_tokens")
                             or usage_raw.get("total_tokens") or 0),
            output_tokens=0,
            cost_basis="openai-compatible:embedding:%s" % self.model,
        )
        return vectors, usage


# ------------------------------------------------------------------- mocks
class MockEmbedder(EmbeddingProvider):
    """Deterministic bag-of-hashed-terms vector. PROTOCOL TESTING ONLY."""

    def __init__(self, dimensions: int = 64):
        self.name = "mock"
        self.model = "mock-hash-v1"
        self.dimensions = dimensions

    def _vector(self, text: str) -> List[float]:
        vec = [0.0] * self.dimensions
        for term in set(text.lower().split()) | {text[i:i + 2]
                                                 for i in range(max(0, len(text) - 1))}:
            digest = hashlib.sha256(term.encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], "big") % self.dimensions
            vec[slot] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts: Sequence[str]) -> Tuple[List[List[float]], Usage]:
        vectors = [self._vector(text) for text in texts]
        usage = Usage(self.name, self.model,
                      input_tokens=sum(len(t) // 4 + 1 for t in texts),
                      cost_basis="mock:none")
        return vectors, usage


class ScriptedChat(ChatProvider):
    """Returns a scripted reply (optionally per-call list). PROTOCOL ONLY."""

    def __init__(self, replies: Sequence[str] = (), fail_with: Optional[Exception] = None):
        self.name = "mock"
        self.model = "scripted-v1"
        self.replies = list(replies) or [
            "分析结论（mock）：毛利率改善。\n引用：[1]"
        ]
        self.fail_with = fail_with
        self.calls = 0

    def complete(self, prompt: str, max_output_tokens: int = 2000
                 ) -> Tuple[str, Usage]:
        self.calls += 1
        if self.fail_with:
            raise self.fail_with
        reply = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        usage = Usage(self.name, self.model,
                      input_tokens=len(prompt) // 4 + 1,
                      output_tokens=len(reply) // 4 + 1,
                      cost_basis="mock:none")
        return reply, usage


_REGISTRY: Dict[str, Any] = {}


def register_provider(name: str, provider: Any) -> None:
    _REGISTRY[name] = provider


def get_provider(name: str):
    provider = _REGISTRY.get(name)
    if provider is None:
        raise ProviderNotConfigured("provider %r is not registered" % name)
    return provider


def _is_unfilled(spec: Dict[str, Any]) -> bool:
    """Placeholders the user has not filled in yet -> treat as absent."""
    for key in ("api_key", "base_url", "model"):
        value = str(spec.get(key, ""))
        if not value or value.startswith("FILL-ME"):
            return True
    return False


def load_providers(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Build providers from config. No credentials in repo -> none by default.

    Segments still holding FILL-ME placeholders are skipped silently (the
    user has not filled them server-side yet); real-looking values for an
    unknown kind raise instead of degrading.
    """
    specs = config_dict.get("providers") or {}
    providers: Dict[str, Any] = {}
    for name, spec in specs.items():
        if not isinstance(spec, dict):
            continue
        kind = str(spec.get("kind", "")).lower()
        if kind == "mock-embedder":
            providers[name] = MockEmbedder(dimensions=int(spec.get("dimensions", 64)))
            continue
        if _is_unfilled(spec):
            continue
        common = dict(name=name, model=str(spec.get("model", "")),
                      base_url=str(spec.get("base_url", "")),
                      api_key=str(spec.get("api_key", "")),
                      egress_allowed=bool(spec.get("egress_allowed", False)))
        if kind == "openai-compatible" and name == "chat":
            providers[name] = OpenAICompatibleChat(**common)
        elif kind == "openai-compatible-vision" or (
                kind == "openai-compatible" and name == "vision_ocr"):
            providers[name] = OpenAICompatibleVision(**common)
        elif kind == "openai-compatible" and name == "embedding":
            providers[name] = OpenAICompatibleEmbedding(
                dimensions=int(spec.get("dimensions", 0) or 0), **common)
        elif kind:
            raise ProviderNotConfigured(
                "provider %r of kind %r has no implementation" % (name, kind))
    return providers
