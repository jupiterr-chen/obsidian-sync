"""Model provider abstraction (P4, ADR0006).

Real providers are NOT implemented or registered here: until the user
supplies provider, credentials usage, data-egress scope and budget, every
code path stays offline. Mocks validate protocol behaviour only and must
never be presented as quality or cost evidence (docs/09, docs/13 V4).
"""

from __future__ import annotations

import hashlib
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


def load_providers(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Build providers from config. No credentials in repo -> none by default."""
    specs = config_dict.get("providers") or {}
    providers: Dict[str, Any] = {}
    for name, spec in specs.items():
        kind = str(spec.get("kind", "")).lower()
        if kind == "mock-embedder":
            providers[name] = MockEmbedder(dimensions=int(spec.get("dimensions", 64)))
        # real kinds intentionally unimplemented until provider+budget are set
        elif kind:
            raise ProviderNotConfigured(
                "provider %r of kind %r has no implementation; real providers "
                "require user-supplied credentials and budget" % (name, kind))
    return providers
