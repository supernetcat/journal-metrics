"""ISSN 规范化工具。ISSN 一律存为无连字符小写形式的 8 字符键（如 00079235）。"""

from __future__ import annotations

import re

_VALID = re.compile(r"^\d{7}[\dXx]$")


def normalize(value: str | None) -> str | None:
    """去掉连字符/空白并把末位 X 大写；不合法返回 None。"""
    if not value:
        return None
    s = re.sub(r"[^0-9Xx]", "", str(value))
    if len(s) != 8:
        return None
    s = s[:-1] + s[-1].upper()
    if not _VALID.match(s):
        return None
    return s


def primary_and_eissn(cell: str | None) -> tuple[str | None, str | None]:
    """处理 'XXXX-XXXX/YYYY-YYYY' 复合格，返回 (主ISSN键, eISSN键)。"""
    if not cell:
        return None, None
    parts = [p.strip() for p in str(cell).replace(";", "/").split("/") if p.strip()]
    keys = [normalize(p) for p in parts]
    keys = [k for k in keys if k]
    if not keys:
        return None, None
    return keys[0], (keys[1] if len(keys) > 1 else None)


def pretty(issn: str | None) -> str | None:
    """xxxx-yyyy 展示格式。"""
    if not issn:
        return None
    return f"{issn[:4]}-{issn[4:]}"


def validate_checksum(issn: str | None) -> bool:
    """ISSN 校验位校验（用于可疑字段甄别），宽松：失败即 False。"""
    if not issn or not _VALID.match(issn):
        return False
    digits = [int(c) for c in issn[:7]]
    checksum = 0
    for w, d in zip(range(8, 1, -1), digits):
        checksum += w * d
    rem = checksum % 11
    expect = (11 - rem) % 11
    expect_char = str(expect) if expect < 10 else "X"
    return issn[-1] == expect_char
