"""OCR engine switch and adapters (P6 follow-up, docs/03 A08).

Default route is LOCAL OCR: RapidOCR (ONNX runtime running PP-OCR models)
renders nothing itself - page rendering for PDFs comes from pypdfium2. Both
are lazy imports: absent dependencies degrade to honest `needs_ocr_engine`
flags, never to fabricated text. The `vision-api` route sends page images to
a configured multimodal provider and therefore requires egress_allowed=true
plus a filled provider config; until then it refuses loudly.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .providers import ProviderNotConfigured


class OcrEngineError(Exception):
    pass


@dataclass
class OcrConfig:
    engine: str = "local"            # local | vision-api | off
    fallback: Optional[str] = None   # None | vision-api (low-confidence pages)
    fallback_min_confidence: float = 0.6
    languages: list = field(default_factory=lambda: ["ch", "en"])
    render_dpi: int = 200
    min_confidence: float = 0.6
    max_pages_per_doc: int = 200

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OcrConfig":
        if not data:
            return cls()
        return cls(
            engine=str(data.get("engine", "local")),
            fallback=data.get("fallback") or None,
            fallback_min_confidence=float(data.get("fallback_min_confidence", 0.6)),
            languages=list(data.get("languages", ["ch", "en"])),
            render_dpi=int(data.get("render_dpi", 200)),
            min_confidence=float(data.get("min_confidence", 0.6)),
            max_pages_per_doc=int(data.get("max_pages_per_doc", 200)),
        )


class OcrEngine:
    """Protocol: run(image_bytes) -> (text, mean_confidence)."""

    name = "abstract"

    def run(self, image_bytes: bytes) -> tuple:
        raise OcrEngineError("abstract OCR engine cannot run")

    def available(self) -> bool:
        return False


class LocalRapidOcr(OcrEngine):
    """RapidOCR (PP-OCR models on onnxruntime). Offline, CPU-friendly.

    Heavy imports are deferred so the module loads without the packages;
    availability() reports False instead of crashing the pipeline.
    """

    name = "rapidocr-ppocr"

    def __init__(self, languages=None, min_confidence: float = 0.6):
        self.languages = languages or ["ch", "en"]
        self.min_confidence = min_confidence
        self._engine = None
        self._unavailable_reason: Optional[str] = None

    def _load(self):
        if self._engine is not None or self._unavailable_reason:
            return
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            self._unavailable_reason = (
                "rapidocr-onnxruntime not installed (pip install "
                "rapidocr-onnxruntime)")
            raise OcrEngineError(self._unavailable_reason) from exc
        self._engine = RapidOCR()

    def available(self) -> bool:
        try:
            self._load()
            return True
        except OcrEngineError:
            return False

    def run(self, image_bytes: bytes) -> tuple:
        self._load()
        result, _elapsed = self._engine(image_bytes)
        texts, confidences = [], []
        for line in result or []:
            # rapidocr rows: [box, text, confidence]
            if len(line) >= 3:
                text = str(line[1]).strip()
                try:
                    confidence = float(line[2])
                except (TypeError, ValueError):
                    confidence = 1.0
                if text:
                    texts.append(text)
                    confidences.append(confidence)
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return "\n".join(texts), mean_conf


class VisionApiOcr(OcrEngine):
    """Page-image OCR via a configured multimodal chat provider.

    Every page is budget-gated when a ledger is attached (R01): reserve a
    conservative per-page token estimate, settle with the provider-side
    usage, and charge the estimate on transport failure (never zero)."""

    name = "vision-api"

    def __init__(self, chat_provider=None, provider_spec: Optional[Dict] = None,
                 ledger=None, page_token_cap: int = 20000):
        self.chat_provider = chat_provider
        self.provider_spec = provider_spec or {}
        self.ledger = ledger
        self.page_token_cap = int(page_token_cap)

    def available(self) -> bool:
        return self.chat_provider is not None

    def run(self, image_bytes: bytes) -> tuple:
        if self.chat_provider is None:
            raise ProviderNotConfigured(
                "vision OCR requested but no multimodal provider is "
                "configured (fill providers.vision_ocr and set "
                "egress_allowed=true)")
        reservation = None
        if self.ledger is not None:
            from .budget import BudgetExceeded, BudgetLedger  # noqa: F401

            ceiling = self.ledger.budget.max_input_tokens_per_page
            if self.page_token_cap > ceiling:
                raise OcrEngineError(
                    "budget_exceeded_per_page: page estimate %d > cap %d"
                    % (self.page_token_cap, ceiling))
            # U02: when the provider is attempt-gated, physical attempts
            # are the request unit; the page reservation counts a PAGE but
            # not an extra request (mirrors chat/embedding)
            gated = hasattr(self.chat_provider, "attempt_ledger")
            try:
                reservation = self.ledger.reserve(
                    "vision-page", self.page_token_cap, counts_as_page=True,
                    count_request=not gated)
            except BudgetExceeded as exc:
                raise OcrEngineError(str(exc))
        prompt = ("Transcribe ALL text in this document page image. Keep the "
                  "original language (Chinese/English mixed as-is). Output "
                  "plain text only, no commentary.")
        # U02: gate the provider's physical attempts with the same ledger
        if self.ledger is not None and hasattr(self.chat_provider,
                                               "attempt_ledger"):
            self.chat_provider.attempt_ledger = self.ledger
        try:
            text, usage = self.chat_provider.complete_with_image(
                prompt, image_bytes, mime="image/png", max_output_tokens=4000)
        except Exception:
            if reservation is not None:
                from .providers import EgressNotAllowed

                if isinstance(sys.exc_info()[1], EgressNotAllowed):
                    self.ledger.release(reservation)  # no bytes left the box
                else:
                    self.ledger.fail_unknown(reservation)
            raise
        if reservation is not None:
            self.ledger.settle(reservation, usage)
        # vision confidence is unknown -> conservative 0.5 so low-confidence
        # flagging stays honest (usage lands in the ledger above)
        return text, 0.5


def build_ocr_engine(ocr_config: Optional[OcrConfig],
                     providers: Optional[Dict[str, Any]] = None,
                     provider_specs: Optional[Dict[str, Any]] = None,
                     ledger=None,
                     ) -> Optional[OcrEngine]:
    """Resolve the configured OCR route; None means OCR off/unavailable."""
    config = ocr_config or OcrConfig()
    providers = providers or {}
    provider_specs = provider_specs or {}
    if config.engine == "off":
        return None
    if config.engine == "vision-api":
        spec = provider_specs.get("vision_ocr") or {}
        if str(spec.get("api_key", "")).startswith("FILL-ME") or not spec:
            raise ProviderNotConfigured(
                "ocr.engine=vision-api but providers.vision_ocr is not "
                "filled in; refusing to guess an endpoint")
        return VisionApiOcr(chat_provider=providers.get("vision_ocr"),
                            provider_spec=spec, ledger=ledger,
                            page_token_cap=(config.max_input_tokens_per_page
                                            if hasattr(config, "max_input_tokens_per_page")
                                            else 20000))
    # default: local
    engine = LocalRapidOcr(languages=config.languages,
                           min_confidence=config.min_confidence)
    if not engine.available():
        return None  # honest degradation: extraction flags needs_ocr_engine
    return engine


def build_fallback_engine(ocr_config: Optional[OcrConfig],
                          providers: Optional[Dict[str, Any]] = None,
                          provider_specs: Optional[Dict[str, Any]] = None,
                          ledger=None,
                          ) -> Optional[OcrEngine]:
    """Low-confidence page fallback (ocr.fallback). None when not configured.

    vision-api fallback requires a filled providers.vision_ocr with
    egress_allowed=true; anything missing degrades to no fallback rather
    than failing the extraction job.
    """
    config = ocr_config or OcrConfig()
    if config.fallback != "vision-api":
        return None
    spec = provider_specs.get("vision_ocr") or {}
    filled = spec and not str(spec.get("api_key", "")).startswith("FILL-ME")
    if not filled or not spec.get("egress_allowed"):
        return None
    provider = providers.get("vision_ocr")
    if provider is None:
        return None
    return VisionApiOcr(chat_provider=provider, provider_spec=spec,
                        ledger=ledger,
                        page_token_cap=(config.max_input_tokens_per_page
                                        if hasattr(config, "max_input_tokens_per_page")
                                        else 20000))


def render_page_to_png(raw_pdf: bytes, page_number: int,
                       dpi: int = 200) -> bytes:
    """Render one PDF page (1-based) to PNG bytes via pypdfium2."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise OcrEngineError(
            "pypdfium2 not installed (pip install pypdfium2) - cannot "
            "render PDF pages for OCR") from exc
    scale = dpi / 72.0
    document = pdfium.PdfDocument(raw_pdf)
    try:
        if not 1 <= page_number <= len(document):
            raise OcrEngineError("page %d out of range" % page_number)
        page = document[page_number - 1]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        import io

        buffer = io.BytesIO()
        pil_image.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        document.close()
