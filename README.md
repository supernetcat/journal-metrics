# journal-metrics · 期刊影响因子与分区本地数据集

把公开转录渠道的 **JCR 影响因子/分区** 与 **中科院(CAS)分区表升级版** 整理成一份本地、可查询、可按年回溯的数据集，
产出 `SQLite + CSV/JSON + 查询模块`，供 scholar-scout / scholarminer 等工程 `import` 使用或人工查阅。

## 覆盖与口径

| 来源 | 年份 | 行数 | 内容 |
|---|---|---|---|
| JCR2020 | 2020 | 13,048 | IF（无分区列） |
| JCR2021 | 2021 | 21,430 | IF |
| JCR2022 | 2022 | 21,522 | IF + Q 分区 |
| JCR2023 | 2023 | 21,848 | IF + 学科/Q/排名 + ISSN |
| JCR2024 | 2024 | 22,249 | 同上 |
| JCR2025 | 2025 | 22,643 | 多学科分区全量（含 2025 版口径） |
| 中科院2021–2025（升级版） | 2021/22/23/25 | 12,422 / 12,359 / 13,812 / 21,772 | 大类分区、小类分区、Top、Review、OA |
| 国际期刊预警名单 | 2020/21/23/24/25 | 157 | 预警等级/原因 |

登记册（按 ISSN 主键）共 **约 2.36 万** 种期刊。

**口径说明 / 重要局限**
- JCR 数据来自 [journalsimpactfactors.com](https://www.journalsimpactfactors.com) 的公开转录（ShowJCR 仓库整理），
  **不是 Clarivate 官方接口**；中科院分区表升级版来自 [advanced.fenqubiao.com](http://advanced.fenqubiao.com) 的用户转录。
- “JCR20xx”文件指 **IF 计量年 20xx**（对应次年 6 月发布的官方 JCR 版次）。官方每年只认当年最新版，历史年序列仅供趋势参考。
- **中科院官方不单独发布影响因子**，其分区表只含分区。本库的“CAS 同年 IF”是把同年 JCR IF 关联上去的便捷口径，
  年份配对按双方年份一致近似处理，未必是分区表制表所用的指标年，请以官方文档为准。
- 2020、2024 两年的中科院分区表暂无公开全量转录 → 属**人工补录缺口**（见 `outputs/manual_supplement_todo.csv`）。
- 合规提示：转录数据仅限内部检索使用；对外发表/商业化请改用 Clarivate 与中科院分区表官方授权数据。

## 目录结构

```
journal-metrics/
├── data/raw/showjcr/            # 主数据源 CSV（只读，勿改）
├── data/raw/manual/             # 人工补录投递目录（新文件放这里）
├── src/journal_metrics/         # 管线 + 查询模块（纯标准库）
├── outputs/journal_metrics.db   # SQLite 主库
├── outputs/csv/                 # registry / jcr_metrics_long / cas_partition_long / merged_wide / warning_list
├── outputs/json/journal_metrics.json
├── outputs/coverage_report.md   # 覆盖率与未解析刊名清单
└── outputs/manual_supplement_todo.csv
```

## 使用

```bash
# 重建（扫描 data/raw 下 JCR20*/FQBJCR20*/GJQKYJMD20* 文件）
PYTHONPATH=src python3 -m journal_metrics build
# 导出 CSV/JSON/覆盖率/补录清单
PYTHONPATH=src python3 -m journal_metrics export
# 查询（ISSN 或刊名关键词）
PYTHONPATH=src python3 -m journal_metrics query "0934-0874"
PYTHONPATH=src python3 -m journal_metrics query "transplant"
```

程序内调用：

```python
import sys; sys.path.insert(0, "src")
from journal_metrics.query import full_metrics, search, cas_with_if

m = full_metrics(issn="0934-0874")   # 或 name="Transplant International"
m["journal"], m["jcr"], m["cas"]      # 历年 JCR 与中科院分区
cas_with_if(issn="0934-0874")         # 中科院行 + 同年 JCR IF
```

## 补录新数据（关键流程）

把渠道获取的文件按下列命名放入 `data/raw/manual/`，重跑 `build` + `export` 即并入库：

| 想补 | 文件名 | 必备列（其余按表头即可，行数不限） |
|---|---|---|
| 中科院某年 | `FQBJCR2024-UTF8.csv` | `Journal,年份,ISSN,Review,Open Access,Web of Science,大类,大类分区,Top,小类1,小类1分区,…`（与 2021/22/23 版表头一致） |
| JCR 某年 | `JCR2026-UTF8.csv` | `Journal,ISSN,EISSN,IF(2026),…` 见 `JCR2025-UTF8.csv` 表头 |
| 预警名单 | `GJQKYJMD2026.csv` | `Journal,预警原因（2026）` |

数值改动请走人工维护表（如同 scholar-scout 的 `cnki_if/curated_if` 隔离口径），**代码只读原始 CSV、不硬编码数值**。

## 打包与二进制发布

GitHub Actions（`.github/workflows/build-binaries.yml`）在 `v*` 标签/手动触发时，用 PyInstaller 在
Linux/macOS/Windows 各产出一个免安装二进制并附到 Release。本地也可直接：

```bash
python -m pip install pyinstaller
python -m PyInstaller --clean --noconfirm journal-metrics.spec   # 产物 dist/journal-metrics(.exe)
```

二进制运行时以**可执行文件所在目录**为基准：读该目录下的 `outputs/journal_metrics.db` 供查询；
要 `build` 重建库则把 `data/raw/`（JCR/FQBJCR 转录 CSV）放到同目录下。源码运行不受影响。

> 说明：原始转录数据（`data/raw/`）与构建产物（`outputs/`）按数据合规不入公开库，
> 请自行从本地/ShowJCR 仓库获取 CSV 后 `build`，或在可执行文件旁放置已生成的 DB 直接 `query`。
