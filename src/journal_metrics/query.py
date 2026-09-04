"""查询 API：以 ISSN / 名称 / 关键词检索期刊的历年 JCR 与中科院分区。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import issn as issnmod
from .paths import runtime_root

DEFAULT_DB = runtime_root() / "outputs" / "journal_metrics.db"


def _connect(db: Path | str = DEFAULT_DB):
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def _jrow(r: sqlite3.Row):
    d = dict(r)
    d["categories"] = json.loads(d.pop("categories_json") or "[]")
    return d


def _crow(r: sqlite3.Row):
    d = dict(r)
    d["subcats"] = json.loads(d.pop("subcats_json") or "[]")
    return d


def journal_by_issn(db: Path | str = DEFAULT_DB, issn=None, eissn=False):
    """按 ISSN/EISSN 查登记册单条。issn 传 8 位键或 'XXXX-XXXX' 均可。"""
    conn = _connect(db)
    key = issnmod.normalize(issn)
    row = conn.execute("SELECT * FROM journals WHERE issn=?", (key,)).fetchone()
    if not row and eissn:
        row = conn.execute("SELECT * FROM journals WHERE eissn=?", (key,)).fetchone()
    conn.close()
    return dict(row) if row else None


def full_metrics(db: Path | str = DEFAULT_DB, issn=None, name=None):
    """聚合视图：期刊登记 + {year: jcr} + {year: cas}。
    返回 dict 或 None。issn 优先；未提供 issn 时按精确名称。"""
    conn = _connect(db)
    j = None
    if issn:
        key = issnmod.normalize(issn)
        j = conn.execute("SELECT * FROM journals WHERE issn=?", (key,)).fetchone()
        if not j:
            j = conn.execute("SELECT * FROM journals WHERE eissn=?", (key,)).fetchone()
    if not j and name:
        j = conn.execute("SELECT * FROM journals WHERE name=? COLLATE NOCASE",
                         (name.strip(),)).fetchone()
    if not j:
        conn.close()
        return None
    jdict = dict(j)
    jdict["name_aliases"] = json.loads(jdict.get("name_aliases") or "[]")
    jdict["sources"] = json.loads(jdict.get("sources") or "[]")
    jcr = {r["year"]: _jrow(r) for r in conn.execute(
        "SELECT * FROM jcr WHERE issn=? ORDER BY year", (j["issn"],)).fetchall()}
    cas = {r["year"]: _crow(r) for r in conn.execute(
        "SELECT * FROM cas WHERE issn=? ORDER BY year", (j["issn"],)).fetchall()}
    conn.close()
    return {"journal": jdict, "jcr": jcr, "cas": cas}


def search(db: Path | str = DEFAULT_DB, keyword=None, limit=50):
    """按名称模糊搜索（子串），返回简化登记列表。"""
    conn = _connect(db)
    rows = []
    if keyword:
        rows = conn.execute(
            "SELECT issn,name,eissn,wos FROM journals WHERE name LIKE ? ESCAPE '\\' "
            "ORDER BY length(name) LIMIT ?",
            (f"%{_escape_like(keyword)}%", limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _escape_like(s: str):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def cas_with_if(db: Path | str = DEFAULT_DB, issn=None):
    """CAS 行并附带同年 JCR IF（若该年 JCR 可得）。"""
    conn = _connect(db)
    rows = conn.execute("""
        SELECT c.*, j.impact_factor AS jcr_if, j.best_quartile AS jcr_q
        FROM cas c LEFT JOIN jcr j ON j.issn=c.issn AND j.year=c.year
        WHERE c.issn=? ORDER BY c.year""", (issn,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
