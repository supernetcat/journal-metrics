"""journal-metrics CLI：build / export / report / query。

用法：
  PYTHONPATH=src python3 -m journal_metrics build    # 从 data/raw 重建 SQLite
  PYTHONPATH=src python3 -m journal_metrics export   # 生成 CSV/JSON/覆盖率报告
  PYTHONPATH=src python3 -m journal_metrics query "ISSN或刊名关键词"
"""

from __future__ import annotations

import json
import sys

from . import build, export
from .query import full_metrics, search


def _show_full(m):
    j = m["journal"]
    print(f"\n{ j['name'] }\n  ISSN {j['issn']} / EISSN {j['eissn']}  WoS {j['wos']}")
    if m["jcr"]:
        print("  JCR:")
        for y in sorted(m["jcr"]):
            r = m["jcr"][y]
            q = f"Q{r['best_quartile']}" if r["best_quartile"] else "-"
            print(f"    {y}: IF={r['impact_factor']} 分区={q}  来源={r['source']}")
    if m["cas"]:
        print("  中科院分区:")
        for y in sorted(m["cas"]):
            r = m["cas"][y]
            top = "Top" if r["top"] else ""
            print(f"    {y}: {r['big_category']} {r['big_quartile']}区 {top}  "
                  f"小类={[(s['category'], s['quartile']) for s in r['subcats']]}")


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd, rest = args[0], args[1:]
    if cmd == "build":
        jcr, cas, warn = build.load_all()
        print(json.dumps(build.build(jcr, cas, warn), ensure_ascii=False, indent=2))
    elif cmd == "export":
        export.run_all()
        print("导出完成 ->", export.OUT)
    elif cmd == "report":
        export.coverage_report()
    elif cmd == "query":
        if not rest:
            print("用法: query <关键词或ISSN>")
            return
        kw = " ".join(rest)
        if kw and kw[0].isdigit():
            m = full_metrics(issn=kw)
            if m:
                _show_full(m)
            else:
                print("未找到该 ISSN")
            return
        hits = search(keyword=kw, limit=15)
        if not hits:
            print("无匹配")
            return
        for h in hits:
            print(f"{h['issn']}  {h['name']}  (eISSN {h['eissn'] or '-'})  {h['wos'] or ''}")
    else:
        print("未知命令:", cmd)
        print(__doc__)


if __name__ == "__main__":
    main()
