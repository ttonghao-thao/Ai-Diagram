"""Lexical helpers for explicit topology names and device counts."""
from __future__ import annotations

import re
import unicodedata

from app.services.materials import alias_lookup, device_aliases

NUMBER_WORDS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_DIGITS = "一二两三四五六七八九"
_QUANTITY = re.compile(r"([\d一二两三四五六七八九十百千零〇]+)\s*[台个部]\s*(.+)")
_CHINESE_NUMBER = re.compile(
    rf"(?:([{_DIGITS}])百)?(?:([{_DIGITS}]?)十)?(?:(零|〇)?([{_DIGITS}]))?"
)
MAX_NODES = 1000
MAX_EDGES = 3000
MAX_LABEL_LENGTH = 500
NUMBERED_SWITCH = re.compile(r"交换机\s*\d+")
QUALIFIED_SWITCH = re.compile(rf"(?:上联|下联)\s*({NUMBERED_SWITCH.pattern})")
NEGATIVE = re.compile(r"未指定|无连接|(?:没有|未|不)(?:直接|明确)?(?:连|接|相连|直连|上联|下联|互联)|"
                      r"\bno\s+(?:physical\s+)?(?:links?|connections?)\b", re.I)
ALL_MEMBERS = re.compile(r"\s*(?:分别|各自|均|都|各)\s*$")
ALTERNATIVE = re.compile(r"或|\bor\b", re.I)


def device_quantity(text: str) -> tuple[int, str] | None:
    """Read an exact number followed by a device classifier and name."""
    match = _QUANTITY.fullmatch(text.strip())
    if not match:
        return None
    number, label = match.groups()
    if number.isdecimal():
        # A longer numeral is already above the GraphDocument node limit.
        digits = number.lstrip("0０")
        count = int(digits or "0") if len(digits) <= 4 else MAX_NODES + 1
    elif number == "一千":
        count = 1000
    else:
        parts = _CHINESE_NUMBER.fullmatch(number)
        if not parts:
            return None
        hundreds, tens, zero, ones = parts.groups()
        if (zero and (not hundreds or tens is not None)) or (hundreds and tens is None and ones and not zero):
            return None
        count = 100 * NUMBER_WORDS.get(hundreds, 0)
        if tens is not None:
            count += 10 * NUMBER_WORDS.get(tens, 1)
        count += NUMBER_WORDS.get(ones, 0)
    return count, label.strip()


def name_key(label: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", label).casefold())


def counted_device_type(label: str) -> tuple[str, str | None] | None:
    alias = re.sub(r"[\s-]+", "_", unicodedata.normalize("NFKC", label).strip().lower())
    device_type = alias_lookup().get(alias)
    if device_type:
        kind = device_aliases()[device_type]["kind"]
        return (kind, device_type) if kind != "service" else None
    if name_key(label) in {"设备", "通用设备", "网络设备"}:
        return "generic", None
    return None


def safe_id(base: str, used: set[str]) -> str:
    """Allocate a schema-valid id without overwriting any existing graph ID."""
    prefix = re.sub(r"[^A-Za-z0-9_-]", "", base.replace(" ", "_")).lstrip("_-0123456789") or "item"
    candidate = prefix[:63]
    sequence = 1
    while candidate in used:
        sequence += 1
        suffix = f"_{sequence}"
        candidate = prefix[:64 - len(suffix)] + suffix
    used.add(candidate)
    return candidate
