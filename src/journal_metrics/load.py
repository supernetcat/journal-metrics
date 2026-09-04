"""CSV 读取工具：自动编码探测（utf-8-sig/utf-8/gb18030），行宽对齐。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator


def sniff_encoding(path: Path) -> str:
    raw = path.read_bytes()[:8192]
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin1"


def iter_rows(path: Path) -> Iterator[tuple[list[str], list[str]]]:
    """逐行产出 (header, row)。行宽不足时以空串补齐；超宽保留。"""
    path = Path(path)
    enc = sniff_encoding(path)
    with open(path, encoding=enc, errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        header = None
        for row in reader:
            if not row or all(c.strip() == "" for c in row):
                continue
            if header is None:
                header = [c.strip() for c in row]
                continue
            if len(row) < len(header):
                row = row + [""] * (len(header) - len(row))
            yield header, row
