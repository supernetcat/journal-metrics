"""导出：long/wide CSV、嵌套 JSON、覆盖率与人工补录报告。"""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from . import issn as issnmod
from .paths import runtime_root
from .query import DEFAULT_DB, _connect

OUT = runtime_root() / "outputs"
CSV_DIR = OUT / "csv"
JSON_DIR = OUT / "json"

JCR_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
CAS_YEARS = [2021, 2022, 2023, 2024, 2025]


def _writers():
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- long csv

def export_long_csv(db=DEFAULT_DB):
    _writers()
    conn = _connect(db)
    c = conn.cursor()

    def dump(name, sql, header, path):
        c.execute(sql)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(header)
            for r in c:
                w.writerow(["" if v is None else v for v in r])

    dump("journals", "SELECT issn,eissn,name,wos,sources,name_aliases FROM journals ORDER BY issn",
         ["issn", "eissn", "name", "wos", "sources_json", "name_aliases_json"],
         CSV_DIR / "registry.csv")
    dump("jcr", "SELECT issn,name,year,impact_factor,best_quartile,category,"
                "cat_rank,cat_total,wos,source,match_type,categories_json "
                "FROM jcr ORDER BY issn,year",
         ["issn", "name", "year", "impact_factor", "best_quartile", "category",
          "cat_rank", "cat_total", "wos", "source", "match_type", "categories_json"],
         CSV_DIR / "jcr_metrics_long.csv")
    dump("cas", "SELECT issn,name,year,review,oa,oaj,wos,mark,big_category,"
                "big_quartile,big_rank,big_total,top,subcats_json,source "
                "FROM cas ORDER BY issn,year",
         ["issn", "name", "year", "review", "oa", "oaj", "wos", "mark",
          "big_category", "big_quartile", "big_rank", "big_total", "top",
          "subcats_json", "source"],
         CSV_DIR / "cas_partition_long.csv")
    dump("warnings", "SELECT name,year,detail,issn FROM warnings ORDER BY year",
         ["name", "year", "detail", "issn"], CSV_DIR / "warning_list.csv")
    conn.close()


# ---------------------------------------------------------------- wide csv

def export_wide_csv(db=DEFAULT_DB):
    """按刊宽表：ISSN 主键 + JCR2020-2025(IF/Q) + 中科院2021-2025(分区/Top/大类) 纵列。"""
    _writers()
    conn = _connect(db)
    c = conn.cursor()

    journals = {r["issn"]: r for r in
                (dict(x) for x in c.execute("SELECT issn,eissn,name,wos FROM journals"))}
    jcr_by = defaultdict(dict)
    for r in c.execute("SELECT issn,year,impact_factor,best_quartile FROM jcr"):
        if r[0]:
            jcr_by[r[0]][r[1]] = (r[2], r[3])
    cas_by = defaultdict(dict)
    for r in c.execute("SELECT issn,year,big_category,big_quartile,top FROM cas"):
        if r[0]:
            cas_by[r[0]][r[1]] = (r[2], r[3], r[4])
    warn_by = {}
    for r in c.execute("SELECT issn,year,detail FROM warnings"):
        if r[0]:
            warn_by[r[0]] = (r[1], r[2])
    conn.close()

    header = (["issn", "eissn", "name", "wos"]
              + [f"jcr_{y}_if" for y in JCR_YEARS]
              + [f"jcr_{y}_q" for y in JCR_YEARS]
              + [f"cas_{y}_cat" for y in CAS_YEARS]
              + [f"cas_{y}_q" for y in CAS_YEARS]
              + [f"cas_{y}_top" for y in CAS_YEARS]
              + ["warn_year", "warn_detail"])
    with open(CSV_DIR / "merged_wide.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for issn in sorted(journals):
            j = journals[issn]
            row = [j["issn"], j["eissn"], j["name"], j["wos"]]
            for y in JCR_YEARS:
                v = jcr_by.get(issn, {}).get(y)
                row.append(v[0] if v else "")
            for y in JCR_YEARS:
                v = jcr_by.get(issn, {}).get(y)
                row.append(f"Q{v[1]}" if v and v[1] else "")
            for y in CAS_YEARS:
                v = cas_by.get(issn, {}).get(y)
                row.append(v[0] if v else "")
            for y in CAS_YEARS:
                v = cas_by.get(issn, {}).get(y)
                row.append(v[1] if v and v[1] else "")
            for y in CAS_YEARS:
                v = cas_by.get(issn, {}).get(y)
                row.append("yes" if v and v[2] else "")
            wv = warn_by.get(issn)
            row.append(wv[0] if wv else "")
            row.append(wv[1] if wv else "")
            w.writerow(row)
    print("merged_wide.csv rows:", len(journals))


# ---------------------------------------------------------------- json

def export_json(db=DEFAULT_DB):
    _writers()
    conn = _connect(db)
    c = conn.cursor()
    out = {}
    for issn, name, eissn, wos in c.execute(
            "SELECT issn,name,eissn,wos FROM journals ORDER BY issn"):
        out[issn] = {"name": name, "eissn": eissn, "wos": wos,
                     "jcr": {}, "cas": {}}
    for issn, year, if_, q, cat in c.execute(
            "SELECT issn,year,impact_factor,best_quartile,category FROM jcr"):
        if issn and issn in out:
            out[issn]["jcr"][str(year)] = {"if": if_, "q": q, "category": cat}
    for issn, year, cat, q, top, mark in c.execute(
            "SELECT issn,year,big_category,big_quartile,top,mark FROM cas"):
        if issn and issn in out:
            out[issn]["cas"][str(year)] = {"category": cat, "q": q,
                                           "top": top, "mark": mark}
    conn.close()
    with open(JSON_DIR / "journal_metrics.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("journal_metrics.json journals:", len(out))


# ---------------------------------------------------------------- coverage

def coverage_report(db=DEFAULT_DB):
    _writers()
    conn = _connect(db)
    c = conn.cursor()
    rep = {"jcr_per_year": {}, "cas_per_year": {},
           "issn_per_year_jcr": {}, "issns_resolved_per_year": {},
           "unresolved_rows": []}
    for y in JCR_YEARS:
        n, = c.execute("SELECT COUNT(*) FROM jcr WHERE year=?", (y,)).fetchone()
        ni, = c.execute("SELECT COUNT(*) FROM jcr WHERE year=? AND issn IS NOT NULL", (y,)).fetchone()
        rep["jcr_per_year"][y] = n
        rep["issns_resolved_per_year"][y] = ni
    for y in CAS_YEARS:
        n, = c.execute("SELECT COUNT(*) FROM cas WHERE year=?", (y,)).fetchone()
        rep["cas_per_year"][y] = n
    total, = c.execute("SELECT COUNT(*) FROM journals").fetchone()
    rep["registry_total"] = total
    rep["warnings_total"], = c.execute("SELECT COUNT(*) FROM warnings").fetchone()
    for r in c.execute(
            "SELECT name,year,impact_factor,source FROM jcr "
            "WHERE issn IS NULL ORDER BY year"):
        rep["unresolved_rows"].append({"name": r[0], "year": r[1],
                                       "if": r[2], "source": r[3]})
    conn.close()

    with open(OUT / "coverage_report.json", "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    with open(OUT / "coverage_report.md", "w", encoding="utf-8") as f:
        f.write("# 期刊影响因子与分区数据集 · 覆盖率报告\n\n")
        f.write("登记刊种数：**%d**\n\n" % rep["registry_total"])
        f.write("| 表 | 年 | 行数 | 已关联ISSN |\n|---|---|---|---|\n")
        for y, n in rep["jcr_per_year"].items():
            f.write(f"| JCR | {y} | {n} | {rep['issns_resolved_per_year'][y]} |\n")
        for y, n in rep["cas_per_year"].items():
            f.write(f"| 中科院分区 | {y} | {n} | - |\n")
        f.write(f"| 预警名单 | - | {rep['warnings_total']} | - |\n\n")
        f.write("> 注：中科院2020与2024分区表暂无公开全量转录，缺口见数据补录清单。\n\n")
        f.write("## 未解析(仅刊名)行\n\n")
        f.write("| 刊名 | 年份 | IF | 来源 |\n|---|---|---|---|\n")
        for u in rep["unresolved_rows"]:
            f.write(f"| {u['name']} | {u['year']} | {u['if']} | {u['source']} |\n")
    print("coverage_report written")


def export_manual_todo(db=DEFAULT_DB):
    """人工补录待办清单：未关联 ISSN 的刊名行 + 缺失年份提示。"""
    conn = _connect(db)
    c = conn.cursor()
    rows = c.execute(
        "SELECT name,year,impact_factor,source FROM jcr "
        "WHERE issn IS NULL ORDER BY year,name").fetchall()
    conn.close()
    with open(OUT / "manual_supplement_todo.csv", "w", newline="",
              encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["说明：以下 JCR 行仅有刊名、未能按名称匹配到 ISSN，请人工核对补 ISSN 或确认刊已更名/停刊",
                    "", "", ""])
        w.writerow(["类型", "刊名", "年份", "IF", "来源"])
        for r in rows:
            w.writerow(["未解析刊名", r[0], r[1], r[2], r[3]])
        w.writerow([])
        w.writerow(["中科院分区缺整年源文件", "", "", "", ""])
        for y in (2020, 2024):
            w.writerow([f"缺 FQBJCR{y}-UTF8.csv（放 data/raw/manual/ 后重跑 build+export 即可）",
                        "", "", "", ""])
    print("manual_supplement_todo.csv written")


def run_all(db=DEFAULT_DB):
    export_long_csv(db)
    export_wide_csv(db)
    export_json(db)
    coverage_report(db)
    export_manual_todo(db)
