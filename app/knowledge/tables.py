"""Table cell model and numeric normalization (P2-04 baseline).

Financial correctness gates (A09) require real annotated samples and remain
BLOCKED; what ships here is a strict, conservative normalizer: anything not
unambiguously parseable becomes value=None with a reason, never a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# (1,234.56) / 1,234.56 / -12.3% / $1,234 / 1 234 / 1.234,56 - shape gate;
# strict semantics are enforced by the parser below, not this regex.
_NUM_RE = re.compile(
    r"^\s*[\(\uFF08]?\s*[-\u2212$¥€£\s]*\d[\d.,\u00A0\s]*[%\uFF05]?\s*[\)\uFF09]?\s*$"
)
_MINUS_CHARS = "-\u2212\u2013\u2014"
_EMPTY_MARKS = {"", "-", "—", "–", "n/a", "N/A", "NA", "na", "null", "NULL", "不适用", "-"}


@dataclass
class NumericValue:
    raw: str
    value: Optional[float] = None
    is_percent: bool = False
    negative_style: Optional[str] = None  # "parentheses" | "minus" | None
    currency_symbol: Optional[str] = None
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw, "value": self.value, "is_percent": self.is_percent,
            "negative_style": self.negative_style, "currency": self.currency_symbol,
            "issues": self.issues,
        }


def normalize_number(raw: str) -> NumericValue:
    raw = (raw or "").strip()
    result = NumericValue(raw=raw)
    cleaned = raw.strip()
    if cleaned in _EMPTY_MARKS or not cleaned:
        result.issues.append("empty")
        return result
    if not _NUM_RE.match(cleaned):
        result.issues.append("not_a_plain_number")
        return result

    negative = False
    if (cleaned.startswith("(") and cleaned.endswith(")")) or (
            cleaned.startswith("\uFF08") and cleaned.endswith("\uFF09")):
        negative = True
        result.negative_style = "parentheses"
        cleaned = cleaned[1:-1].strip()
    for symbol in ("$", "¥", "€", "£"):
        if symbol in cleaned:
            result.currency_symbol = symbol
            cleaned = cleaned.replace(symbol, "")
    cleaned = cleaned.strip()
    if "%" in cleaned or "\uFF05" in cleaned:
        result.is_percent = True
        cleaned = cleaned.replace("%", "").replace("\uFF05", "")
    if not result.negative_style and cleaned[:1] in _MINUS_CHARS:
        negative = True
        result.negative_style = "minus"
        cleaned = cleaned.lstrip(_MINUS_CHARS + " \u00A0")
    # thousands separators: space/nbsp or comma; reject mixed , and . decimals
    cleaned = cleaned.replace("\u00A0", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):  # 1.234,56 style
            integer, _, decimal = cleaned.rpartition(",")
            if not all(len(g) == 3 for g in integer.split(".")[1:]):
                result.issues.append("malformed_grouping")
                return result
            cleaned = integer.replace(".", "") + "." + decimal
        else:  # 1,234.56 style: every comma group must be exactly 3 digits
            integer, _, decimal = cleaned.rpartition(".")
            groups = integer.split(",")
            if not all(len(g) == 3 for g in groups[1:]):
                result.issues.append("malformed_grouping")
                return result
            cleaned = "".join(groups) + "." + decimal
    elif "," in cleaned:
        # comma is a thousands separator only when groups are exactly 3 digits
        parts = cleaned.split(",")
        if len(parts[-1]) == 3 and all(len(p) == 3 for p in parts[1:]):
            cleaned = "".join(parts)
        elif len(parts) == 2:  # ambiguous 1,5 -> decimal in some locales
            result.issues.append("ambiguous_decimal_comma")
            return result
        else:
            result.issues.append("malformed_grouping")
            return result
    try:
        value = float(cleaned)
    except ValueError:
        result.issues.append("unparseable")
        return result
    result.value = -value if negative else value
    return result


@dataclass
class TableBlock:
    """Structured table attached to an extraction (cells kept as displayed)."""

    rows: List[List[str]]
    header_rows: int = 0
    locator: Dict[str, Any] = field(default_factory=dict)

    def normalized_cells(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r, row in enumerate(self.rows):
            for c, cell in enumerate(row):
                out.append({
                    "row": r, "col": c, "raw_text": cell,
                    "is_header": r < self.header_rows,
                    "number": normalize_number(cell).to_dict() if r >= self.header_rows else None,
                })
        return out
