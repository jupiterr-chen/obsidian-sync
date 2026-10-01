"""Text quality assessment and OCR routing signals (A06/A08 helpers).

Every signal is conservative: unknown or suspicious content routes to
``review`` (human/OCR confirmation), never silently to ``ready``. Thresholds
are versioned configuration, not magic numbers scattered in extractors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Versioned thresholds; changing values is a config change and must produce a
# new config_digest for extraction jobs.
QUALITY_CONFIG = {
    "version": 1,
    "min_chars": 40,               # below this the doc is "too_short" (review)
    "replacement_ratio_max": 0.02,  # U+FFFD ratio above this -> review
    "repetition_line_ratio": 0.6,   # most-common line share above this -> review
    "repetition_min_lines": 8,
    "sparse_page_ratio": 0.5,       # zero-char pages above this share -> review
}

STATUS_READY = "ready"
STATUS_REVIEW = "review"
STATUS_FAILED = "failed"

REVIEW_WEIGHT = {STATUS_READY: 0, STATUS_REVIEW: 1, STATUS_FAILED: 2}


@dataclass
class Quality:
    status: str
    issues: List[str] = field(default_factory=list)


def merge_statuses(*statuses: str) -> str:
    worst = STATUS_READY
    for status in statuses:
        if REVIEW_WEIGHT.get(status, 1) > REVIEW_WEIGHT[worst]:
            worst = status
    return worst


def analyze_text(text: str,
                 per_page_chars: Optional[List[int]] = None) -> Quality:
    issues: List[str] = []
    if not text or not text.strip():
        return Quality(STATUS_FAILED, ["no_text"])
    if len(text) < QUALITY_CONFIG["min_chars"]:
        issues.append("too_short")

    replacement = text.count("\ufffd")
    ratio = replacement / len(text)
    if ratio > QUALITY_CONFIG["replacement_ratio_max"]:
        issues.append("replacement_chars")

    control = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\t\r")
    if control:
        issues.append("control_characters")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= QUALITY_CONFIG["repetition_min_lines"]:
        counts: Dict[str, int] = {}
        for line in lines:
            counts[line] = counts.get(line, 0) + 1
        top = max(counts.values())
        if top / len(lines) > QUALITY_CONFIG["repetition_line_ratio"]:
            issues.append("repetitive_lines")

    if per_page_chars is not None and per_page_chars:
        sparse = sum(1 for chars in per_page_chars if chars == 0)
        if sparse / len(per_page_chars) > QUALITY_CONFIG["sparse_page_ratio"]:
            issues.append("mostly_sparse_pages")

    status = STATUS_REVIEW if issues else STATUS_READY
    return Quality(status, issues)


def route_page_to_ocr(page_chars: int, page_text: str) -> Tuple[bool, List[str]]:
    """Per-page OCR routing decision (A08): sparse page -> OCR candidate.

    A sparse page is not necessarily scanned (covers/charts are legit); the
    decision is a routing hint, the OCR engine result still gets its own
    quality assessment.
    """
    reasons: List[str] = []
    if page_chars == 0:
        reasons.append("no_text_layer")
    elif len(page_text.strip()) < 10:
        reasons.append("very_sparse_text")
    replacement = page_text.count("\ufffd") / max(1, len(page_text))
    if replacement > QUALITY_CONFIG["replacement_ratio_max"]:
        reasons.append("replacement_chars")
    return (bool(reasons), reasons)
