# journal-metrics · 数据使用介绍与技术规范

> 面向 **scholar-scout / scholarminer** 等下游项目的开发者：介绍本数据集的定位、数据架构、字段口径、数据量与调用方式。
> 本数据集定位为**内部检索用本地库**：数据来自公开转录渠道，**不是 Clarivate/中科院官方接口**。

- 版本：0.1.0
- 生成日期：2026-09-03
- 重建方式：`pip install -e .` 后 `python -m journal_metrics build && python -m journal_metrics export`

---

## 0. TL;DR（30 秒速览）

| 项 | 值 |
|---|---|
| 主库 | `/usr/OpenCode/journal-metrics/outputs/journal_metrics.db`（SQLite，约 58 MB，纯只读查询） |
| Python 包 | `journal_metrics`（纯标准库实现，无第三方依赖） |
| 安装 | `pip install -e /usr/OpenCode/journal-metrics`，然后 `import journal_metrics` |
| 查询接口 | `from journal_metrics.query import full_metrics, search, cas_with_if, journal_by_issn` |
| 规模 | 登记册 **23,674** 刊（ISSN 主键）；JCR 逐年 **122,740** 行（2020–2025）；中科院分区 **60,365** 行（2021–2025）；预警名单 157 条 |
| 已知缺口 | 中科院分区表 **2020 / 2024** 两整年暂无公开源；少量旧年 JCR 行仅剩刊名（未配 ISSN） |

```python
import sys; sys.path.insert(0, "/usr/OpenCode/journal-metrics/src")
from journal_metrics.query import full_metrics

m = full_metrics(issn="0934-0874")      # 或 full_metrics(name="Transplant International")
print(m["journal"]["name"], m["journal"]["eissn"])
print(m["jcr"][2025]["impact_factor"])  # 3.6
print(m["cas"][2025]["big_category"], m["cas"][2025]["big_quartile"])  # 医学 3
```

---

## 1. 项目定位与目录结构

```
/usr/OpenCode/journal-metrics/
├── pyproject.toml                    # pip 可安装
├── README.md                         # 项目入口说明（中文）
├── DATA_SPEC.md                      # 本文档
├── data/
│   ├── raw/showjcr/                  # 主源 CSV（只读，勿改；来源见 §6）
│   └── raw/manual/                   # 人工补录投递目录（命名约定见 §8）
├── src/journal_metrics/              # 管线 + 查询模块（标准库）
│   ├── sources.py                    #   来源解析
│   ├── build.py                      #   登记册 + SQLite 组装
│   ├── query.py                      #   【下游常用】查询 API
│   ├── export.py                     #   CSV/JSON/覆盖率导出
│   ├── names.py / issn.py / load.py  #   归一化工具
│   └── __main__.py                   #   CLI
└── outputs/
    ├── journal_metrics.db            # SQLite 主库
    ├── csv/                          # 长表 + 宽表导出
    ├── json/journal_metrics.json     # 嵌套 JSON（每刊历年）
    ├── coverage_report.{md,json}     # 覆盖率与未解析清单
    └── manual_supplement_todo.csv    # 人工补录待办（缺口 + 未配 ISSN 行）
```

产物大小（约）：`journal_metrics.db` 58 MB；`csv/` 合计 49 MB；`json/` 12.8 MB；`outputs/` 合计 115 MB。

---

## 2. 数据架构

### 2.1 逻辑分层

```
                     ┌──────────────────────────────────────────┐
                     │  登记册 journals（ISSN 主键，唯一身份）    │
                     │  issn / eissn / name / name_aliases / wos │
                     └───────────────┬──────────────────────────┘
           ┌─────────────────────────┴──────────────────────────┐
   ┌───────▼────────┐                               ┌───────────▼────────┐
   │ jcr  逐年指标表 │                               │ cas   逐年分区表    │
   │ 2020…2025 IF/Q │                               │ 2021…2025 中科院分区│
   └───────┬────────┘                               └───────────┬────────┘
           └────────────── 导出层（可由开发自建） ──────────────┘
    csv/merged_wide.csv · csv/*_long.csv · json/journal_metrics.json
```

- 底层 `jcr`/`cas` 均以 `issn` 关联登记册；同一刊的历年数据以 `(issn, year)` 对齐。
- 登记册身份 = **无连字符 8 位 ISSN**；EISSN 作为"别名可反查"（`eISSN` 列的刊也能按 EISSN 命中）。

### 2.2 表结构（SQLite）

#### `journals`（登记册 · 23,674 行）
| 列 | 类型 | 说明 |
|---|---|---|
| `issn` | TEXT **PK** | 8 位无连字符（小写 x 统一为大写 X），如 `09340874` |
| `eissn` | TEXT | 电子版 ISSN（同格式）；无可为 NULL |
| `name` | TEXT | 规范英文全名（优先取 JCR2025 口径） |
| `name_aliases` | TEXT | JSON 数组：各来源曾用名/拼写 |
| `wos` | TEXT | 收录类型，如 `SCIE`/`SSCI`/`AHCI`/`ESCI`；可为 NULL |
| `sources` | TEXT | JSON 数组：哪些来源表出现过该刊 |

索引：主键 `issn`。

#### `jcr`（JCR 逐年指标 · 122,740 行）
| 列 | 类型 | 说明 |
|---|---|---|
| `issn` | TEXT | 该年指标关联到的 ISSN；**可为 NULL**（仅剩刊名、未配 ISSN 的旧年行） |
| `name` | TEXT | 该年来源里的刊名 |
| `year` | INTEGER | 计量年，`2020…2025`（语义见 §4） |
| `impact_factor` | REAL | 影响因子；缺失为 NULL |
| `best_quartile` | TEXT | 最佳分区 `'1'…'4'`（该年多学科分区取最靠前者）；无分区年份为 NULL |
| `category` | TEXT | 首要学科（英文）；`category`+rank 即主分区所在学科 |
| `cat_rank` / `cat_total` | INTEGER | 主学科内排名 / 学科刊数（如 `43 / 321`） |
| `wos` | TEXT | 收录类型 |
| `source` | TEXT | 来源表名 `JCR2020`…`JCR2025` |
| `match_type` | TEXT | `by_issn`（源自带 ISSN）/ `by_name`（旧年无 ISSN，按刊名匹配上）/ `unresolved`（未匹配上） |
| `categories_json` | TEXT | JSON 数组：该年全部学科分区明细（格式见 §2.3） |

索引：`(issn, year)`、`(name)`。无 `(issn, year)` 唯一约束——理论上同 ISSN 同年在多来源不冲突，实际各年单表内 ISSN 唯一。

#### `cas`（中科院分区表升级版 · 60,365 行）
| 列 | 类型 | 说明 |
|---|---|---|
| `issn` | TEXT | 关联登记册；2021/2022/2023/2025 源自带 ISSN，无 NULL |
| `name` | TEXT | 来源刊名 |
| `year` | INTEGER | 分区表年号 `2021/2022/2023/2025` |
| `review` | INTEGER | 1=综述期刊 / 0=非 / NULL=缺 |
| `oa` | INTEGER | 1=Open Access / 0=非 |
| `oaj` | INTEGER | 1=入选 OA Journal Index（仅 2025 版有此列，早期年为 NULL） |
| `wos` | TEXT | 收录类型 |
| `mark` | TEXT | 标注：`Mega-Journal`、`中国SCI期刊支持计划`、`中英文期刊"同质等效"评价`、预警备注等；无则 NULL |
| `big_category` | TEXT | 大类名称（**中文**），如 `医学`、`材料科学` |
| `big_quartile` | TEXT | 大类分区 `'1'…'4'` |
| `big_rank` / `big_total` | INTEGER | 大类内排名/刊数（2025 版含，如 `1276 / 5603`） |
| `top` | INTEGER | 1=Top 期刊 / 0=非 |
| `subcats_json` | TEXT | JSON 数组：小类分区明细（格式见 §2.3） |
| `source` | TEXT | `FQBJCR2021/2022/2023/2025` |

索引：`(issn, year)`、`(name)`。

#### `warnings`（国际期刊预警名单 · 157 行）
| 列 | 类型 | 说明 |
|---|---|---|
| `name` | TEXT | 被预警刊名 |
| `year` | INTEGER | 名单年份 `2020/2021/2023/2024/2025`（2022 官方未发布） |
| `detail` | TEXT | 2020–2023 为预警等级，2024 起为预警原因（如 `引用操纵`） |
| `issn` | TEXT | 按刊名尽力匹配到的登记 ISSN；未匹配为 NULL |

> 该表**只有被预警期刊**，不是全量分区表。

#### `meta`（元信息 · 4 行）
`dataset` / `provenance` / `sources` / `caveat` 四组键值，说明血缘与合规提示。

### 2.3 JSON 嵌套字段格式

`categories_json`（jcr 表，`list[dict]`，2025 版可有 1–6 个学科，2020/2021 版为空）：
```json
[{"category": "SURGERY", "quartile": 1, "rank": 43, "total": 321},
 {"category": "TRANSPLANTATION", "quartile": 2, "rank": 10, "total": 30}]
```

`subcats_json`（cas 表，`list[dict]`，最多 6 个小类；`en`/`zh` 为英文名与中文名的拆分）：
```json
[{"category": "SURGERY 外科", "en": "SURGERY", "zh": "外科", "quartile": 3, "rank": 69, "total": 292},
 {"category": "TRANSPLANTATION 移植", "en": "TRANSPLANTATION", "zh": "移植", "quartile": 3, "rank": 9, "total": 31}]
```

### 2.4 编码约定（务必遵守，否则易踩坑）

| 项 | 约定 |
|---|---|
| ISSN 键 | 一律 **8 位无连字符**（`09340874`）；末位 `X` 大写。展示格式可用 `issn[:4]+"-"+issn[4:]` |
| 分区 | 存为 **TEXT** `'1'…'4'`（不是整数，SQLite TEXT 亲和会把整数转文本）。比较请用 `q >= '1' AND q <= '4'` 或 `CAST(q AS INTEGER)` |
| 布尔 | `1/0`；来源无该列时为 **NULL**（如 `oaj` 在 2021–2023 为 NULL） |
| 缺失 | 一律 **NULL**（导出 CSV 时转空串） |
| 空数组 | 写 `[]`，读取后 `len()==0`，勿当 None |
| 名称匹配 | 库内 `name` 为规范英文名；跨表比对建议用 `normalize_name` 生成的键（见 `src/journal_metrics/names.py`） |
| 同一刊同名 | 极少数不同期刊共享刊名（如 Heart Rhythm 双 ISSN），**务必用 ISSN 定位**，勿只用刊名 |

---

## 3. 年份与来源语义（重要口径）

| 来源表 | 列 `year` 含义 | 行数 | 说明 |
|---|---|---|---|
| `JCR2020` | IF 计量年 2020 | 13,048 | 只有 IF，无分区列 |
| `JCR2021` | IF 计量年 2021 | 21,430 | 只有 IF |
| `JCR2022` | IF 计量年 2022 | 21,522 | IF + Q 分区（无学科明细） |
| `JCR2023` | IF 计量年 2023 | 21,848 | 含 ISSN/学科/分区/排名 |
| `JCR2024` | IF 计量年 2024 | 22,249 | 同上 |
| `JCR2025` | IF 计量年 2025 | 22,643 | 多学科分区全量 |
| `FQBJCR2021` | 中科院 2021 | 12,422 | 分区表升级版 |
| `FQBJCR2022` | 中科院 2022 | 12,359 | 同上 |
| `FQBJCR2023` | 中科院 2023 | 13,812 | 同上 |
| `FQBJCR2025` | 中科院 2025 | 21,772 | 同上（含排名/标注等新列） |
| `GJQKYJMD*` | 预警名单发布年 | 157 | 2022 年官方未发布 |

- **"JCR20xx" = 官方 JCR 版次 20xx 的 IF 计量年 20xx**（与来源表头 `IF(2025)` 一致；官方于次年 6 月发布）。做"论文发表当年的 IF"请自行按计量年选择（例如论文发表于 2024 年，取 `year=2024` 的官方口径，而非发表年+2）。
- **中科院只出分区、不出影响因子**。`cas` 表内没有 IF。需要"中科院同年 IF"时用 `cas_with_if()` 或 SQL 自行 LEFT JOIN `jcr(issn, year)` 得到 **近似口径**——年份完全对齐是"便捷假设"，分区表制表实际基于其内部指标（3 年平均/超越指数等），以官方说明为准。
- **历史年份口径不可沿用"当年最新"做发表认定**：官方每年只认当年发布的指标，回溯序列仅供趋势/对比参考。

来源渠道（均为公开转录，见 `meta` / README）：
- JCR：ShowJCR 仓库整理的 journalsimpactfactors.com 转录 CSV。
- 中科院分区升级版：advanced.fenqubiao.com 的用户转录。
- 预警名单：fenqubiao 公开页。
- 合规：转录数据仅限**内部检索**；对外发表 / 商业化请改用官方授权数据。

---

## 4. 数据量与覆盖率

**ISSN 关联情况（`jcr` 表按年）**

| 年 | 行数 | 已关联 ISSN | 覆盖率 | 说明 |
|---|---|---|---|---|
| 2020 | 13,048 | 12,870 | 98.6% | 其余 178 行仅剩刊名 |
| 2021 | 21,430 | 20,943 | 97.7% | 其余 487 行仅剩刊名 |
| 2022 | 21,522 | 21,206 | 98.5% | 其余 316 行仅剩刊名 |
| 2023 | 21,848 | 21,845 | ~100% | 源自带 ISSN |
| 2024 | 22,249 | 22,249 | 100% | 同上 |
| 2025 | 22,643 | 22,643 | 100% | 同上 |
| **合计** | **122,740** | — | — | 仅剩刊名未配 ISSN 共 984 行 |

**中科院分区（`cas` 表按年）**：2021=12,422 · 2022=12,359 · 2023=13,812 · **2024=0（缺口）** · 2025=21,772。另 **2020 年（基础版）亦为整年缺口**。

**预警名单（`warnings`）**：2020=65 · 2021=35 · 2023=28 · 2024=24 · 2025=5。

**覆盖率报告**：`outputs/coverage_report.{md,json}`（含逐年解析数）；**补录待办**：`outputs/manual_supplement_todo.csv`（984 条未配 ISSN 行 + 两个缺年份提示）。缺整年可通过 §8 投递 `FQBJCR2024-UTF8.csv` / `FQBJCR2020-UTF8.csv` 后重建补齐。

---

## 5. 快速上手

### 5.1 CLI

```bash
# ① 安装（任选其一）
pip install -e /usr/OpenCode/journal-metrics        # 正式集成用
#   （若系统 Python 受 PEP668 保护：请在项目的 venv 里执行，或用下方 PYTHONPATH 免安装方式）
# 或免安装：PYTHONPATH=src python3 -m journal_metrics ...

# ② 重建（通常不需要；改动 data/raw 后才需）
python -m journal_metrics build

# ③ 导出（同样按需）
python -m journal_metrics export

# ④ 查询
python -m journal_metrics query "0934-0874"     # 按 ISSN（自动去连字符）
python -m journal_metrics query "transplant"    # 按刊名关键词模糊
```

`query` 输出示例（Transplant International）：
```
TRANSPLANT INTERNATIONAL
  ISSN 09340874 / EISSN 14322277  WoS SCIE
  JCR:
    2020: IF=3.782 分区=-  来源=JCR2020
    ...
    2025: IF=3.6 分区=Q1  来源=JCR2025
  中科院分区:
    2021: 医学 2区 Top  小类=[('SURGERY 外科', 2), ('TRANSPLANTATION 移植', 2)]
    ...
    2025: 医学 3区  小类=[('SURGERY 外科', 3), ('TRANSPLANTATION 移植', 3)]
```

### 5.2 Python 查询 API（下游主用）

```python
from journal_metrics.query import (
    full_metrics,      # 聚合视图：登记 + 历年 JCR + 历年 CAS
    journal_by_issn,   # 登记册单条
    search,            # 刊名模糊检索
    cas_with_if,       # CAS 行附带同年 JCR IF
)

# --- 按 ISSN（可传 8 位键，也可传 '0934-0874' 带连字符）---
m = full_metrics(issn="0934-0874")
m["journal"]           # {'issn','eissn','name','wos','name_aliases':[...],'sources':[...]}
m["jcr"]               # {2020:{...}, 2021:{...}, ..., 2025:{...}}  键为 int year
m["jcr"][2025]["impact_factor"], m["jcr"][2025]["best_quartile"]
m["jcr"][2025]["categories"]      # list[dict]，见 §2.3
m["cas"]               # {2021:{...}, 2022:{...}, 2023:{...}, 2025:{...}}
m["cas"][2025]["subcats"]         # list[dict]，含 en/zh/quartile/rank/total

# --- 按 EISSN 反查（登记的 eissn 也能命中）---
full_metrics(issn="1432-2277")["journal"]["name"]   # TRANSPLANT INTERNATIONAL

# --- 按精确刊名（不分大小写）---
full_metrics(name="Transplant International")

# --- 刊名模糊检索：返回 [{issn,name,eissn,wos}, ...] ---
hits = search(keyword="transplant", limit=20)

# --- CAS 行附带同年 JCR IF（近似口径，见 §3）---
for r in cas_with_if(issn="0934-0874"):
    r["jcr_if"], r["big_quartile"], r["big_category"]
```

### 5.3 直接 SQL（只读）

```sql
-- 单刊历年 JCR + CAS 横向并排
SELECT j.year,
       j.impact_factor AS jcr_if, j.best_quartile AS jcr_q,
       c.big_category AS cas_cat, c.big_quartile AS cas_q, c.top
FROM jcr j
LEFT JOIN cas c ON c.issn = j.issn AND c.year = j.year
WHERE j.issn = '09340874' ORDER BY j.year;

-- 检索：中科院 2025 医学大类 Q1 且为 Top
SELECT c.issn, name, impact_factor
FROM cas c JOIN jcr j ON j.issn=c.issn AND j.year=c.year
WHERE c.year=2025 AND c.big_category='医学' AND c.big_quartile='1' AND c.top=1
ORDER BY j.impact_factor DESC;

-- 按 2025 最佳分区筛选（用 CAST 避免文本比较陷阱）
SELECT issn, name, impact_factor FROM jcr
WHERE year=2025 AND CAST(best_quartile AS INTEGER) <= 2;

-- 是否在 2024 预警名单
SELECT w.* FROM warnings w WHERE w.year=2024 AND w.issn=?
```

> 提示：SQLite 建议以**只读**方式打开主库，勿把该 db 当工程写库。
> `sqlite3.connect("file:.../journal_metrics.db?mode=ro", uri=True)`

---

## 6. 与 scholar-scout 的集成建议

当前 scholar-scout 用 `data/jcr_index.json`（JCR 单年）做第 1 级回退、`jcr_by_issn.json` 做快照。接入本库可整体替换为**结构化的逐年查询**：

1. **安装**：`pip install -e /usr/OpenCode/journal-metrics`（PEP668 受管系统请在项目 venv 内安装），或直接把 `src` 加入 `sys.path`（零第三方依赖）。
2. **推荐调用路径**（把"论文 → 期刊指标"落到代码）：
   ```python
   from journal_metrics.query import full_metrics, search

   def journal_metric(issn=None, name=None, year=None):
       """返回最匹配年份的 (impact_factor, best_quartile)。"""
       m = full_metrics(issn=issn) if issn else (full_metrics(name=name) if name else None)
       if not m:
           return None
       jcr = m["jcr"]
       y = year if year in jcr else max(jcr)          # 落回最新可得年
       r = jcr[y]
       cas = m["cas"].get(y) or (m["cas"].get(max(m["cas"])) if m["cas"] else None)
       return {"year": y, "jif": r["impact_factor"], "jcr_q": r["best_quartile"],
               "cas_cat": cas and cas["big_category"], "cas_q": cas and cas["big_quartile"],
               "cas_top": bool(cas and cas["top"]), "issn": m["journal"]["issn"]}
   ```
3. **批处理建议**：`full_metrics` 每次开/关一个连接，几千条场景无压力（纯 SQLite）。更大批量可直接一次 `SELECT` 拉全表构建 `dict[issn → rows]`（内存 < 100 MB），本库 exporter 即此做法，可参考 `export.export_wide_csv`。
4. **匹配策略**（沿用你现有回退思想）：
   - 第 1 级：`issn`（优先）→ `full_metrics`。
   - 第 2 级：登记刊名精确 `full_metrics(name=...)`（不区分大小写）。
   - 第 3 级：`search()` 模糊，返回候选让上层选或人工补录。
   - ISSN 缺失/论文不是 SCI/SSCI 期刊：返回空，交给你现有的人工表通道。
5. **口径提醒**（务必传达给产品/报告口径）：
   - IF 用 JCR 计量年；若项目里习惯"发表年 +1"取 IF，请统一口径后再对接。
   - 中科院无官方 IF，`cas_with_if` 的同年 IF 是近似；报告里建议分别标注 `JCR(Clarivate)` 与 `CAS分区(中科院)` 两个数据源。
   - 2024/2020 中科院分区为缺口；2025 与 2021–2023 并存，比较时注意别混年份。
6. 需要更贴近 scholar-scout 现有 `JournalMetric` 的**薄适配层**（把本库封装成其接口），或产出 `.xlsx` 导出，可让两边开发者对一份接口约定再开发。

---

## 7. 更新 / 新增年份

全流程幂等：**投递源文件 → `build` → `export`**（结果落 `outputs/`）。

```bash
# 放入新文件后：
python -m journal_metrics build     # 重建 DB（扫描 data/raw/showjcr 与 data/raw/manual）
python -m journal_metrics export    # 重导 CSV/JSON + 覆盖率
```

| 想补 | 文件名（放 `data/raw/manual/`） | 表头要求 |
|---|---|---|
| 中科院某年 | `FQBJCR2024-UTF8.csv` | 与 `showjcr/FQBJCR2023-UTF8.csv` 一致（含 `Journal,年份,ISSN,Review,…,大类,大类分区,Top,小类1,…`） |
| JCR 某年 | `JCR2026-UTF8.csv` | 参考 `JCR2025-UTF8.csv`（含 `Journal,ISSN,EISSN,IF(2026),…`） |
| 预警名单 | `GJQKYJMD2026.csv` | `Journal,预警原因（2026）` |

模板：`data/raw/manual/FQBJCR-template.csv`（无数据行的表头模板）。注意：**代码只读 CSV、不硬编码任何数值**；人工改数请另走隔离维护表（参照 scholar-scout 既有 `cnki_if`/`curated_if` 口径，代码不回写数值）。

---

## 8. 常见问题与踩坑清单

1. **分区列是文本**：`best_quartile`/`big_quartile` 为 TEXT（`'1'`…`'4'`），比较用 `CAST(... AS INTEGER)`。
2. **ISSN 两种写法**：库内一律 8 位无连字符；对外展示可自转 `xxxx-yyyy`。按 EISSN 也能查到刊。
3. **同名不同刊**：个别同名刊（不同 ISSN）存在——凡程序取数一律以 ISSN 锚定；刊名只能做检索/回退。
4. **2020/2021 JCR 无分区**：`best_quartile=NULL`、`categories=[]`，只有 IF。
5. **CAS 无官方 IF**：需要 IF 时用同年 JCR LEFT JOIN（近似口径，报告需注明）。
6. **预警名单不等于黑名单**：只是官方预警提示，且 2022 年未发布名单。
7. **主库只读**：请以 `mode=ro` 打开，避免误写/并发锁。
8. **合规**：转录数据勿对外分发；商用/发表口径请走 Clarivate 与中科院分区表官方渠道。

---

*问题/扩展（Excel 导出、scholar-scout 适配层、接入 CI 更新）可直接找本库维护者协商。*
