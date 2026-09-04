"""数据集组装：构建 ISSN 登记册、跨年/跨表关联、写入 SQLite。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import issn as issnmod
from .names import normalize_name
from .paths import runtime_root
from .sources import load_all

OUT = runtime_root() / "outputs"
DB_PATH = OUT / "journal_metrics.db"

# 登记册权威度：越靠前越优先提供 canonical_name / eissn / wos
_PRIORITY = ["JCR2025", "FQBJCR2025", "JCR2024", "JCR2023",
             "FQBJCR2023", "FQBJCR2022", "FQBJCR2021", "JCR2022",
             "JCR2021", "JCR2020"]


class Registry:
    def __init__(self):
        self.journals = {}       # issn_key -> dict
        self.name_index = {}     # name_key -> set(issn_key)

    def _add_name(self, ik, name):
        if not ik or not name:
            return
        j = self.journals[ik]
        aliases = j["aliases"]
        aliases.add(name)
        nk = normalize_name(name)
        if nk:
            self.name_index.setdefault(nk, set()).add(ik)

    def register(self, records):
        """records: 标准 record dict 列表，含 issn_key/eissn_key/name/source/wos。"""
        for rec in sorted(records, key=lambda r: _PRIORITY.index(r["source"])
                          if r["source"] in _PRIORITY else 99):
            ik = rec.get("issn_key")
            name = rec.get("name")
            source = rec.get("source")
            if ik and ik not in self.journals:
                self.journals[ik] = {"issn": ik, "eissn": None, "name": None,
                                     "aliases": set(), "wos": None, "sources": set()}
            if ik:
                self._add_name(ik, name)
                j = self.journals[ik]
                j["sources"].add(source)
                if j["name"] is None and name:
                    j["name"] = name
                ek = rec.get("eissn_key")
                if ek and ek != ik and j["eissn"] is None and source in (
                        "JCR2025", "FQBJCR2025", "JCR2024", "JCR2023"):
                    j["eissn"] = ek
                if j["wos"] is None and rec.get("wos"):
                    j["wos"] = rec["wos"]
                elif rec.get("wos") and rec["wos"] not in ("ESCI",) and source in (
                        "JCR2025", "FQBJCR2025"):
                    j["wos"] = rec["wos"]
            # eissn 作为别名索引，便于 ISSN 反查（不单独立登记条目，仅在 name_index 使用）
            # 若某年把 eissn 当主键，则后续 build 阶段无法并入主登记，仅靠此 map 缓解。
        # 名字别名兜底：让登记册名字尽量完整（含未以 issn 主键出现的别名）
        for ik, j in self.journals.items():
            for nk in list(j["aliases"]):
                nkey = normalize_name(nk)
                if nkey:
                    self.name_index.setdefault(nkey, set()).add(ik)

    def resolve_name(self, name):
        """name → (issn_keys, is_unique)。唯一返回 issn，否则 None。"""
        nk = normalize_name(name)
        if not nk:
            return None
        hits = self.name_index.get(nk, set())
        if len(hits) == 1:
            return next(iter(hits))
        return None

    def finalize(self):
        self.journals = {ik: {**j, "sources": sorted(j["sources"])}
                         for ik, j in self.journals.items()}
        return self.journals


def _metric_row(rec, match_type):
    cats = rec.get("categories") or []
    first = cats[0] if cats else {}
    return {
        "issn": rec.get("issn_key"),
        "name": rec.get("name"),
        "year": rec.get("year"),
        "impact_factor": rec.get("impact_factor"),
        "best_quartile": rec.get("best_quartile"),
        "category": first.get("category"),
        "cat_rank": first.get("rank"),
        "cat_total": first.get("total"),
        "wos": rec.get("wos"),
        "source": rec.get("source"),
        "match_type": match_type,
        "categories_json": json.dumps(cats, ensure_ascii=False),
    }


def build(jcr, cas, warn, db_path: Path = DB_PATH):
    """组装登记册 + 写库。返回统计 dict。"""
    reg = Registry()
    reg.register(jcr)
    reg.register(cas)
    journals = reg.finalize()

    stats = {"journals": len(journals), "jcr_name_only_unresolved": 0,
             "jcr_name_only_matched": 0, "cas_no_issn": 0, "jcr_no_issn": 0}

    # 组装 jcr 行：先 ISSN 直连，再按名字解析（2020/2021/2022 无 ISSN 来源）
    jcr_rows = []
    for rec in jcr:
        if rec.get("issn_key") and rec["issn_key"] in journals:
            jcr_rows.append(_metric_row(rec, "by_issn"))
        else:
            ik = reg.resolve_name(rec["name"])
            if ik:
                rec2 = dict(rec, issn_key=ik)
                jcr_rows.append(_metric_row(rec2, "by_name"))
                stats["jcr_name_only_matched"] += 1
            else:
                # 保留 name-only 行（issn=None），供查询与人工补录
                jcr_rows.append(_metric_row(rec, "unresolved"))
                stats["jcr_name_only_unresolved"] += 1

    cas_rows = []
    for rec in cas:
        if not rec.get("issn_key"):
            stats["cas_no_issn"] += 1
        cas_rows.append({
            "issn": rec.get("issn_key"),
            "name": rec.get("name"),
            "year": rec.get("year"),
            "review": rec.get("review"),
            "oa": rec.get("oa"),
            "oaj": rec.get("oaj"),
            "wos": rec.get("wos"),
            "mark": rec.get("mark"),
            "big_category": rec.get("big_category"),
            "big_quartile": rec.get("big_quartile"),
            "big_rank": rec.get("big_rank"),
            "big_total": rec.get("big_total"),
            "top": rec.get("top"),
            "subcats_json": json.dumps(rec.get("subcats") or [], ensure_ascii=False),
            "source": rec.get("source"),
        })

    warn_rows = []
    for rec in warn:
        ik = reg.resolve_name(rec["name"])
        warn_rows.append({"name": rec["name"], "year": rec["year"],
                          "detail": rec["detail"], "issn": ik})

    _write_db(db_path, journals, jcr_rows, cas_rows, warn_rows)
    return stats


def _write_db(db_path, journals, jcr_rows, cas_rows, warn_rows):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.executescript("""
    PRAGMA journal_mode=OFF;
    CREATE TABLE meta (k TEXT, v TEXT);
    CREATE TABLE journals (
        issn TEXT PRIMARY KEY,
        eissn TEXT,
        name TEXT,
        wos TEXT,
        sources TEXT,
        name_aliases TEXT
    );
    CREATE TABLE jcr (
        issn TEXT,
        name TEXT NOT NULL,
        year INTEGER NOT NULL,
        impact_factor REAL,
        best_quartile TEXT,
        category TEXT,
        cat_rank INTEGER,
        cat_total INTEGER,
        wos TEXT,
        source TEXT,
        match_type TEXT,
        categories_json TEXT
    );
    CREATE INDEX idx_jcr_issn_year ON jcr(issn, year);
    CREATE INDEX idx_jcr_name ON jcr(name);
    CREATE TABLE cas (
        issn TEXT,
        name TEXT NOT NULL,
        year INTEGER NOT NULL,
        review INTEGER, oa INTEGER, oaj INTEGER,
        wos TEXT, mark TEXT,
        big_category TEXT, big_quartile TEXT,
        big_rank INTEGER, big_total INTEGER,
        top INTEGER,
        subcats_json TEXT,
        source TEXT
    );
    CREATE INDEX idx_cas_issn_year ON cas(issn, year);
    CREATE INDEX idx_cas_name ON cas(name);
    CREATE TABLE warnings (
        name TEXT NOT NULL, year INTEGER NOT NULL, detail TEXT, issn TEXT
    );
    """)
    meta = [
        ("dataset", "journal-metrics: 期刊影响因子与分区本地数据集"),
        ("provenance", "ShowJCR 公开转录 CSV (https://github.com/hitfyd/ShowJCR)" ),
        ("sources", "JCR2020-2025 (journalsimpactfactors 转录); FQBJCR2021/2022/2023/2025 (中科院分区表升级版, advanced.fenqubiao.com 转录); GJQKYJMD2020-2025 国际期刊预警名单"),
        ("caveat", "公开转录数据，非 Clarivate/中科院官方接口，仅供内部检索；核对/商用请走官方授权"),
    ]
    c.executemany("INSERT INTO meta VALUES(?,?)", meta)
    c.executemany(
        "INSERT INTO journals VALUES(?,?,?,?,?,?)",
        [(j["issn"], j["eissn"], j["name"], j["wos"],
          json.dumps(j["sources"], ensure_ascii=False),
          json.dumps(sorted(j["aliases"]), ensure_ascii=False))
         for j in journals.values()])
    c.executemany(
        "INSERT INTO jcr VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r["issn"], r["name"], r["year"], r["impact_factor"], r["best_quartile"],
          r["category"], r["cat_rank"], r["cat_total"], r["wos"], r["source"],
          r["match_type"], r["categories_json"]) for r in jcr_rows])
    c.executemany(
        "INSERT INTO cas VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r["issn"], r["name"], r["year"], r["review"], r["oa"], r["oaj"],
          r["wos"], r["mark"], r["big_category"], r["big_quartile"],
          r["big_rank"], r["big_total"], r["top"], r["subcats_json"], r["source"])
         for r in cas_rows])
    c.executemany("INSERT INTO warnings VALUES(?,?,?,?)",
                  [(r["name"], r["year"], r["detail"], r["issn"]) for r in warn_rows])
    conn.commit()
    conn.close()


def main_build():
    jcr, cas, warn = load_all()
    stats = build(jcr, cas, warn)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("DB ->", DB_PATH)


if __name__ == "__main__":
    main_build()
