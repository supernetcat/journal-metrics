"""原始来源文件解析：把 ShowJCR 各 CSV 归一化为标准 record 字典。

JCR record 字段:
  source, year, name, issn_key, eissn_key, wos, impact_factor,
  categories=[{category, quartile, rank, total}], best_quartile

CAS(中科院分区表升级版) record 字段:
  source, year, name, issn_key, eissn_key, review, oa, oaj, wos, mark,
  big_category, big_quartile, big_rank, big_total, top, subcats=[...]

预警名单 record 字段: source, year, name, detail
"""

from __future__ import annotations

import re
from pathlib import Path

from . import issn as issnmod
from .names import split_cat
from .load import iter_rows
from .paths import runtime_root

RAW_DIR = runtime_root() / "data" / "raw" / "showjcr"
MANUAL_DIR = runtime_root() / "data" / "raw" / "manual"


def _find(kind: str) -> list[Path]:
    """按前缀在 showjcr/ 与 manual/ 目录递归查找来源文件（manual 可投递新年份）。"""
    pats = {"JCR": "JCR20", "CAS": "FQBJCR20", "WARN": "GJQKYJMD"}
    stem = pats[kind]
    found = []
    for root in (RAW_DIR, MANUAL_DIR):
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.name.startswith(stem) and p.suffix.lower() in (".csv", ".txt"):
                found.append(p)
    return sorted(found)


def _f(value):
    s = (value or "").replace(",", "").replace("%", "").strip()
    if s in ("", "-", "n/a", "No", "N/A", "NA", "NULL", "Not available"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_rank(cell):
    """'13/98' 或 '13 [12/98]' → (rank, total)；宽松解析。"""
    s = (cell or "").strip()
    if not s:
        return None, None
    m = re.search(r"(\d+)\s*\[\s*(\d+)\s*/\s*(\d+)\s*\]", s)
    if m:
        return int(m.group(2)), int(m.group(3))
    m = re.search(r"(\d+)\s*/\s*(\d+)", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _quartile_rank_int(cell):
    """分区单元格可能为 '1'、'4 [625/778]'、'Q1' → (quartile_int, rank, total)。"""
    s = (cell or "").strip()
    if not s:
        return None, None, None
    q = None
    mq = re.search(r"\bQ([1-4])\b", s, re.I)
    if mq:
        q = int(mq.group(1))
    md = re.match(r"^([1-4])", s)
    if md and q is None:
        q = int(md.group(1))
    rank, total = _parse_rank(s)
    return q, rank, total


def _int01(value):
    if value is None:
        return None
    s = str(value).strip()
    if s == "是":
        return 1
    if s == "否":
        return 0
    return None


def _year_from_name(name: str) -> int:
    m = re.search(r"(20\d{2})", name)
    return int(m.group(1)) if m else 0


def _issn_cells(d: dict):
    """从行字典解析 (issn_key, eissn_key)。兼容分列 ISSN/EISSN 与合并 ISSN/EISSN。"""
    if "ISSN/EISSN" in d:
        return issnmod.primary_and_eissn(d["ISSN/EISSN"])
    ik = issnmod.normalize(d.get("ISSN"))
    ek = issnmod.normalize(d.get("EISSN") or d.get("eISSN"))
    if not ik:
        ik, ek = ek, None
    return ik, ek


def _pick_if(d: dict):
    for k, v in d.items():
        if k.startswith("IF"):
            val = _f(v)
            if val is not None:
                return val
    return None


# ---------------------------------------------------------------- JCR

def _jcr_rows(path: Path):
    csv_name = path.name
    src = csv_name.split("-")[0]  # JCR2020 ...
    year = _year_from_name(src)
    for header, row in iter_rows(path):
        d = dict(zip(header, row))
        name = (d.get("Journal") or "").strip()
        if not name:
            continue
        rec = {
            "source": src,
            "year": year,
            "name": name,
            "issn_key": None,
            "eissn_key": None,
            "wos": (d.get("Web of Science") or "").strip() or None,
            "impact_factor": _pick_if(d),
            "categories": [],
            "best_quartile": None,
        }
        rec["issn_key"], rec["eissn_key"] = _issn_cells(d)
        # 单类别年份：2022/2023/2024
        cat = (d.get("Category") or "").strip()
        q = None
        if src == "JCR2022":
            qs = d.get("IF Quartile(2022)") or d.get("IF Quartile")
        elif src == "JCR2023":
            qs = d.get("IF Quartile(2023)")
        elif src == "JCR2024":
            qs = d.get("IF Quartile(2024)")
        else:
            qs = None
        if qs:
            mq = re.search(r"Q([1-4])", qs, re.I)
            q = int(mq.group(1)) if mq else None
        rank, total = _parse_rank(d.get("Category Rank(2023)") or d.get("IF Rank(2024)"))
        if cat or q or rank:
            rec["categories"].append({
                "category": cat or None,
                "quartile": q,
                "rank": rank,
                "total": total,
            })
        # 2025 多类别年份
        for i in range(1, 7):
            catk = f"Category_{i}"
            if catk not in d:
                continue
            cname = (d.get(catk) or "").strip()
            qname = d.get(f"IF Quartile(2025)_{i}")
            rname = d.get(f"IF Rank(2025)_{i}")
            qi = None
            if qname:
                mq = re.search(r"Q([1-4])", qname, re.I)
                qi = int(mq.group(1)) if mq else None
            ri, ti = _parse_rank(rname)
            if cname or qi or ri:
                rec["categories"].append({
                    "category": cname or None,
                    "quartile": qi,
                    "rank": ri,
                    "total": ti,
                })
        if rec["categories"]:
            rec["best_quartile"] = min(
                (c["quartile"] for c in rec["categories"] if c["quartile"]), default=None)
        yield rec


# ---------------------------------------------------------------- CAS

def _cas_rows(path: Path):
    csv_name = path.name
    src = csv_name.split("-")[0]  # FQBJCR2025
    fallback_year = _year_from_name(src)
    for header, row in iter_rows(path):
        d = dict(zip(header, row))
        name = (d.get("Journal") or "").strip()
        if not name:
            continue
        year = _f_year = None
        yv = (d.get("年份") or "").strip()
        try:
            year = int(float(yv))
        except (ValueError, TypeError):
            year = fallback_year
        ik, ek = _issn_cells(d)
        bq, brank, btotal = _quartile_rank_int(d.get("大类分区"))
        subcats = []
        for i in range(1, 7):
            catk = f"小类{i}"
            if catk not in d:
                continue
            cname = (d.get(catk) or "").strip()
            q, r, t = _quartile_rank_int(d.get(f"小类{i}分区"))
            en, zh = split_cat(cname)
            if cname or q:
                subcats.append({"category": cname or None, "en": en, "zh": zh,
                                "quartile": q, "rank": r, "total": t})
        rec = {
            "source": src,
            "year": year,
            "name": name,
            "issn_key": ik,
            "eissn_key": ek,
            "review": _int01(d.get("Review")),
            "oa": _int01(d.get("Open Access")),
            "oaj": _int01(d.get("OA Journal Index（OAJ）")) if "OA Journal Index（OAJ）" in d else None,
            "wos": (d.get("Web of Science") or "").strip() or None,
            "mark": (d.get("标注") or "").strip() or None,
            "big_category": (d.get("大类") or "").strip() or None,
            "big_quartile": bq,
            "big_rank": brank,
            "big_total": btotal,
            "top": _int01(d.get("Top")),
            "subcats": subcats,
        }
        yield rec


# ---------------------------------------------------------------- warning lists

def _warn_rows(path: Path):
    csv_name = path.name
    src = csv_name.rsplit(".", 1)[0]
    year = _year_from_name(csv_name)
    for header, row in iter_rows(path):
        d = dict(zip(header, row))
        name = (d.get("Journal") or "").strip()
        if not name:
            continue
        detail = ""
        for k, v in d.items():
            if k not in ("Journal",) and v:
                detail = str(v).strip()
                break
        yield {"source": src, "year": year, "name": name, "detail": detail}


def load_all():
    """返回 (jcr_records, cas_records, warn_records)。扫描 showjcr/ + manual/ 目录。"""
    jcr = []
    for p in _find("JCR"):
        jcr.extend(_jcr_rows(p))
    cas = []
    for p in _find("CAS"):
        cas.extend(_cas_rows(p))
    warn = []
    for p in _find("WARN"):
        warn.extend(_warn_rows(p))
    return jcr, cas, warn
