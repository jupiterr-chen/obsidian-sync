"""OCR engine switch and adapters (P6 follow-up, docs/03 A08).

Default route is LOCAL OCR: RapidOCR (ONNX runtime running PP-OCR models)
renders nothing itself - page rendering for PDFs comes from pypdfium2. Both
are lazy imports: absent dependencies degrade to honest `needs_ocr_engine`
flags, never to fabricated text. The `vision-api` route sends page images to
a configured multimodal provider and therefore requires egress_allowed=true
plus a filled provider config; until then it refuses loudly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .providers import ProviderNotConfigured


class OcrEngineError(Exception):
    pass


@dataclass
class OcrConfig:
    engine: str = "local"            # local | vision-api | off
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
    """Page-image OCR via a configured multimodal chat provider."""

    name = "vision-api"

    def __init__(self, chat_provider=None, provider_spec: Optional[Dict] = None):
        self.chat_provider = chat_provider
        self.provider_spec = provider_spec or {}

    def available(self) -> bool:
        return self.chat_provider is not None

    def run(self, image_bytes: bytes) -> tuple:
        if self.chat_provider is None:
            raise ProviderNotConfigured(
                "vision OCR requested but no multimodal provider is "
                "configured (fill providers.vision_ocr and set "
                "egress_allowed=true)")
        raise OcrEngineError(
            "vision provider adapter lands with the real provider work "
            "(needs the user-supplied API config first)")


def build_ocr_engine(ocr_config: Optional[OcrConfig],
                     providers: Optional[Dict[str, Any]] = None,
                     provider_specs: Optional[Dict[str, Any]] = None
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
                            provider_spec=spec)
    # default: local
    engine = LocalRapidOcr(languages=config.languages,
                           min_confidence=config.min_confidence)
    if not engine.available():
        return None  # honest degradation: extraction flags needs_ocr_engine
    return engine


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
