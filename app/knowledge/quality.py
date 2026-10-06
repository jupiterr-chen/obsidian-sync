"""Text quality assessment and OCR routing signals (A06/A08 helpers).

Every signal is conservative: unknown or suspicious content routes to
``review`` (human/OCR confirmation), never silently to ``ready``. Thresholds
are versioned configuration, not magic numbers scattered in extractors.

TQ1/TQ2 (2026-10-06): the routing now sees the failure fingerprints the
historical corpus actually has - C0/C1 control bytes from byte-decoded
glyph indexes, dense high-Latin runs (CID-style), replacement chars and
a degraded/legacy PDF engine - instead of only sparse/replacement text.
HIGH-LATIN CHARACTERS ALONE ARE LEGITIMATE (¥, £, Ø, Ë, accents):
damage is judged by CONTROL bytes and dense high-byte RUNS, never by
deleting or forbidding individual legal characters. Block-level
evidence usability lets downstream consumers (search, analysis,
summaries) exclude binary-polluted text without hiding it from reading
or deleting anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Versioned thresholds; changing values is a config change and must produce a
# new config_digest for extraction jobs. v2 adds the damage-routing signals.
QUALITY_CONFIG = {
    "version": 2,
    "min_chars": 40,               # below this the doc is "too_short" (review)
    "replacement_ratio_max": 0.02,  # U+FFFD ratio above this -> review
    "repetition_line_ratio": 0.6,   # most-common line share above this -> review
    "repetition_min_lines": 8,
    "sparse_page_ratio": 0.5,       # zero-char pages above this share -> review
    # --- TQ1 damage signals (page level) ---
    "control_ratio_max": 0.02,      # C0 (non \n\t\r) share above -> damaged
    "control_run_length": 4,        # consecutive C0 bytes >= this -> damaged
    "c1_del_ratio_max": 0.02,       # C1 (0x80-0x9F) / DEL share above -> damaged
    "high_latin_run_length": 6,     # consecutive 0xA0-0xFF chars >= this ->
                                    # CID-style glyph-index fingerprint
    "high_latin_run_min_count": 3,  # ... and at least this many such runs
}

STATUS_READY = "ready"
STATUS_REVIEW = "review"
STATUS_FAILED = "failed"

REVIEW_WEIGHT = {STATUS_READY: 0, STATUS_REVIEW: 1, STATUS_FAILED: 2}

# engines whose text layer is produced by the simplified stdlib parser or
# a degraded fallback - their text is NOT trusted as clean by default
LEGACY_PDF_ENGINES = ("stdlib-pdf", "stdlib-pdf-degraded")


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


def _is_c0(ch: str) -> bool:
    return ord(ch) < 32 and ch not in "\n\t\r"


def _is_c1_or_del(ch: str) -> bool:
    return 0x7F <= ord(ch) <= 0x9F


def _is_high_latin(ch: str) -> bool:
    return 0xA0 <= ord(ch) <= 0xFF


def damage_signals(text: str) -> List[str]:
    """Damage fingerprints in one text unit (page or block).

    Returns issue tags, empty for healthy text. NOTE the deliberate
    asymmetry: isolated high-Latin characters are fine (¥ £ Ø Ë é …);
    only LONG consecutive runs of them repeat the way byte-decoded
    glyph indexes do, and only together with enough such runs do they
    flag damage. Control bytes are stricter: any dense share or a
    single run of control bytes is damage."""
    if not text:
        return []
    issues: List[str] = []
    length = max(1, len(text))
    control = sum(1 for ch in text if _is_c0(ch))
    if control / length > QUALITY_CONFIG["control_ratio_max"] or _has_run(
            text, _is_c0, QUALITY_CONFIG["control_run_length"]):
        issues.append("control_characters")
    c1 = sum(1 for ch in text if _is_c1_or_del(ch))
    if c1 / length > QUALITY_CONFIG["c1_del_ratio_max"]:
        issues.append("c1_or_del_characters")
    run_len = QUALITY_CONFIG["high_latin_run_length"]
    runs = 0
    run = 0
    longest = 0
    for ch in text:
        if _is_high_latin(ch):
            run += 1
            longest = max(longest, run)
            if run == run_len:
                runs += 1
        else:
            run = 0
    if (runs >= QUALITY_CONFIG["high_latin_run_min_count"]
            or longest >= run_len * 3):
        issues.append("cid_style_glyph_runs")
    return issues


def _has_run(text: str, predicate, length: int) -> bool:
    run = 0
    for ch in text:
        if predicate(ch):
            run += 1
            if run >= length:
                return True
        else:
            run = 0
    return False


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

    issues.extend(damage_signals(text))

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


def route_page_to_ocr(page_chars: int, page_text: str,
                      parser_id: Optional[str] = None,
                      engine_kind: Optional[str] = None
                      ) -> Tuple[bool, List[str]]:
    """Per-page OCR/re-extraction routing decision (A08 + TQ1).

    A sparse page is not necessarily scanned (covers/charts are legit);
    a DAMAGED page (control bytes, CID-style glyph runs, C1/DEL, many
    replacement chars) has an untrustworthy text layer regardless of
    its character count - high volume of garbage is still garbage.

    The legacy/degraded ENGINE alone does NOT force page OCR: a legacy
    engine that produced demonstrably clean text keeps its page (the
    engine marker still goes to the document issues and the TQ0
    inventory, where native RE-EXTRACTION - not page OCR - is the
    remedy). The decision is a routing hint; the OCR engine result
    still gets its own quality assessment."""
    reasons: List[str] = []
    if page_chars == 0:
        reasons.append("no_text_layer")
    elif len(page_text.strip()) < 10:
        reasons.append("very_sparse_text")
    if page_text:
        replacement = page_text.count("\ufffd") / max(1, len(page_text))
        if replacement > QUALITY_CONFIG["replacement_ratio_max"]:
            reasons.append("replacement_chars")
        reasons.extend(damage_signals(page_text))
    return (bool(reasons), reasons)


def block_evidence_usable(text: str) -> Tuple[bool, List[str]]:
    """May this block's text be used as research evidence downstream
    (search postings, analysis prompts, summary evidence)?

    TQ2: binary-polluted text stays readable in the vault and in
    diagnostics, but is not treated as a valid research fact source.
    Display-legitimate characters are never a reason to reject."""
    issues = damage_signals(text)
    if text.count("\ufffd") / max(1, len(text)) > \
            QUALITY_CONFIG["replacement_ratio_max"]:
        issues.append("replacement_chars")
    return (not issues, issues)


def damaged_reasons(text: str) -> List[str]:
    """Public alias for damage fingerprints of a text unit."""
    return damage_signals(text)
