"""期刊名规范化与跨年同名匹配工具。"""

from __future__ import annotations

import re

# 常见 JCR 刊名中的噪点
_SUFFIX = re.compile(r"\s*\b(LTD|INC|AND CO|AND COMPANY|PUB|PUBL|PUBLISHING|PUBLISHERS|PRESS)$", re.I)
_STRIP = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str | None) -> str | None:
    """用于跨表/跨年精确匹配的键：小写、去非字母数字、去出版社尾缀。"""
    if not name:
        return None
    s = _SUFFIX.sub(" ", str(name).strip())
    return _STRIP.sub(" ", s.lower()).strip()


def display_name(name: str | None) -> str:
    return (name or "").strip() or ""


_CJK = lambda ch: ord(ch) >= 0x2E80 and ord(ch) <= 0x9FFF or 0xF900 <= ord(ch) <= 0xFAFF


def split_cat(raw: str | None) -> tuple[str | None, str | None]:
    """拆分中科院小类原始名 'SURGERY 外科' → (英文, 中文)。"""
    if not raw:
        return None, None
    s = str(raw).strip()
    cut = None
    for i, ch in enumerate(s):
        if _CJK(ch):
            cut = i
            break
    if cut is None:
        return s, None
    en = s[:cut].strip() or None
    zh = s[cut:].strip() or None
    return en, zh
