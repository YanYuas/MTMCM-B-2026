# B 题数据获取工具（TPDC + 背景 + 卫星/气象补充源）

> 位置：`03_编程手/数据获取/`
> 目标：把赛题提到的数据网站、以及 Q2 需要的卫星/气象补充源，做成**可复现、可审计、合规**的抓取工具，为模型提供“数据 + 来源 + 引用”三件套。
> 原则：**只抓公开页面/公开 API；遵守 robots 与限速；不绕过登录、验证码、付费墙；失败也留痕。**

---

## 1. 这个工具解决什么问题

比赛里“数据来源”最容易出三类问题：

1. 论文写了“来自 TPDC”，但没有 DOI、没有作者、没有访问日期，评阅无法核验；
2. 不同队员各抓一份，数字/时间范围/坐标不一致，最后无法复现；
3. 把再分析/预报产品当成站点实测，或者把“一次灾害”当成有标签数据集。

本工具用一套统一流程解决：

- **TPDC 八个数据集**：通过公开的 `metadataView/detail` 与 `getGoogleJson` 接口，抓取标题、作者、DOI/CSTR、时间/空间范围、变量说明、使用条款，并生成中文/英文引用；
- **背景网页**：自然资源部“泥石流形成的基本条件”正文抽取；百度百科因反爬被阻断，只留引用与失败证据；
- **Q2 补充源**：Open-Meteo（历史/预报）、NASA POWER（再分析交叉核对）、Copernicus（Sentinel-1/2 产品元数据）；
- **证据链**：每个请求写入 `data/manifest.jsonl`，带 URL、方法、HTTP 状态、抓取时间、sha256、raw 路径；
- **审计报告**：`data/reports/source_audit.md` 自动汇总“哪些源可用、哪些失败、对应哪一问、可直接引用的参考文献”。

---

## 2. 快速开始

在仓库根目录执行：

```powershell
cd "03_编程手\数据获取"

# 1) 看有哪些来源
python -m mtmcm_data list

# 2) 先审计赛题已有 8 组附件（先内后外）
python -m mtmcm_data existing

# 3) 生成 processed 基线（第一批+第二批）
python -m mtmcm_data process --batch all

# 4) 抓全部元数据（首次会建缓存；--refresh 强制重抓）
python -m mtmcm_data fetch all

# 5) 下载 TPDC 数据文件（默认跳过 >50MB；大文件加 --include-large）
python -m mtmcm_data download all

# 6) 生成来源审计报告
python -m mtmcm_data report

# 7) 核对事件前 72 小时站点/再分析降水
python -m mtmcm_data audit

# 8) 按来源逐项核验抓取质量
python -m mtmcm_data validate

# 9) 生成数据治理报告与数据卡
python -m mtmcm_data governance

# 10) 核验 raw 文件与本地附件
python -m mtmcm_data verify
```

如果 `python` 不在 PATH，用仓库环境里的解释器，或直接运行：

```powershell
.\run.ps1 list
.\run.ps1 fetch all
.\run.ps1 report
```

> Windows 默认执行策略可能禁止运行 `.ps1`；可改用 `.\run.cmd list`，或：
> `powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 list`。

只抓某几个来源：

```powershell
python -m mtmcm_data fetch tpdc_01_hourly mnr_debris_conditions open_meteo_archive
python -m mtmcm_data fetch copernicus_s2 --refresh
```

离线复算（只用缓存，不访问网络）：

```powershell
python -m mtmcm_data fetch all --offline
```

---

## 3. 来源清单

### 3.1 赛题明示的网站

| ID | 来源 | 用途 | 状态 |
|---|---|---|---|
| `tpdc_01_hourly` | TPDC：吉隆高寒山区地气相互作用逐小时综合观测（2021–2026） | Q1/Q3 的 MET/RADM/SOIL/FLUX | ✅ |
| `tpdc_02_temp` | TPDC：2005–2025 吉隆县及周边逐日平均气温 | Q1/Q3 长期背景 | ✅ |
| `tpdc_03_glacier_rar` | TPDC：200 km 冰川及表面高程变化（2000–2020） | Q2/Q4 冰川变化 | ✅ |
| `tpdc_04_glacier_nc` | TPDC：蓝塘里壤峰冰崩前冰川地形/冰厚/速度 | Q2/Q4 冰崩源区 | ✅ |
| `tpdc_05_landcover` | TPDC：泥石流灾害区土地覆盖（2020–2023） | Q2 地表条件 | ✅ |
| `tpdc_06_disaster_points` | TPDC：历史灾点数据 | Q2 空间标签 | ✅ |
| `tpdc_07_dem` | TPDC：2026-08-26 灾害区 DEM | Q2/Q4 地形 | ✅ |
| `tpdc_08_population` | TPDC：吉隆县第七次人口普查 | Q4 暴露 | ✅ |
| `mnr_debris_conditions` | 自然资源部：泥石流形成的基本条件 | Q1/Q2 三条件背景 | ✅ |
| `baike_debris_flow` | 百度百科：泥石流灾害 | 背景（可选） | ⛔ robots/403，已留痕 |

### 3.2 Q2 补充源（题目要求“自行选取并补充”）

| ID | 来源 | 用途 | 备注 |
|---|---|---|---|
| `open_meteo_archive` | Open-Meteo 历史（ERA5 再分析） | 事件窗口逐小时气象 | 公开 API；网格海拔约 4138 m，不能代替站点实测 |
| `open_meteo_forecast` | Open-Meteo 预报 | Q3 未来 72 h 接口演示 | 预报不是实测 |
| `nasa_power` | NASA POWER 逐小时 | 再分析交叉核对 | 网格海拔约 4995 m，与站点 4140 m 不同 |
| `copernicus_s2` | Copernicus Sentinel-2 元数据 | Q2 光学遥感 | 只取元数据；下载需账号/OAuth |
| `copernicus_s1` | Copernicus Sentinel-1 元数据 | Q2/Q4 SAR | 只取元数据；下载需账号/OAuth |

> 这些补充源的选择理由：**免费/公开、无需申请密钥、能覆盖 2026-08-26 事件窗口、能与 TPDC 站点数据做交叉核对**。商业卫星（Planet 等）和需要审批的 ERA5/CDS 没有放进默认配置，避免比赛期间卡在权限上。

### 3.3 原始链接

```text
TPDC 门户            https://data.tpdc.ac.cn
TPDC-01              https://www.tpdc.ac.cn/zh-hans/data/5b09afd1-d11b-4150-a291-50f0484dddf1
TPDC-02              https://www.tpdc.ac.cn/zh-hans/data/94d1bc8e-b912-413e-bd2b-851f2ff8f8f7
TPDC-03              https://www.tpdc.ac.cn/zh-hans/data/f94c33c4-f521-4247-80ec-55dfa2dd453a
TPDC-04              https://www.tpdc.ac.cn/zh-hans/data/c2875b3e-7fd4-4b38-9814-fef64193d1a4
TPDC-05              https://www.tpdc.ac.cn/zh-hans/data/4e1e74fb-dcee-4ce4-8b07-ec3f3109eabe
TPDC-06              https://www.tpdc.ac.cn/zh-hans/data/db142594-2819-403b-8da0-5ebb2a0ca951
TPDC-07              https://www.tpdc.ac.cn/zh-hans/data/88b5ab22-19a1-480f-bcdc-cec41776ab46
TPDC-08              https://www.tpdc.ac.cn/zh-hans/data/8662c472-43d6-4e92-bff8-e26923970642
自然资源部             https://www.mnr.gov.cn/zt/hd/dqr/43earthday/dqkp/201203/t20120316_2057013.html
百度百科               https://baike.baidu.com/item/泥石流灾害/9911941
Open-Meteo 历史        https://archive-api.open-meteo.com/v1/archive
Open-Meteo 预报        https://api.open-meteo.com/v1/forecast
NASA POWER            https://power.larc.nasa.gov/api/temporal/hourly/point
Copernicus OData      https://catalogue.dataspace.copernicus.eu/odata/v1/Products
```

TPDC 元数据接口（本工具实际使用）：

```text
POST /view/metadataView/detail/                 body: {"userId":"","metadataId":"<uuid>"}
GET  /view/metadataView/getGoogleJson?metadataId=<uuid>
```

---

## 4. 输出结构

```
03_编程手/数据获取/
├── config/sources.json          # 所有来源、参数、限速、缓存 TTL
├── mtmcm_data/                  # 代码
├── tests/                       # 解析器单元测试（不联网）
├── data/
│   ├── raw/<source_id>/         # 原始响应（HTML/JSON），带时间戳+hash
│   ├── cache/<source_id>/       # HTTP 缓存（body + meta）
│   ├── meta/
│   │   ├── tpdc/<uuid>.json     # 八个数据集的统一元数据
│   │   ├── tpdc/<uuid>.ris      # TPDC 公开 RIS 引用（可导入 Zotero/EndNote）
│   │   ├── tpdc/<uuid>.files.json # 文件清单 + 下载状态 + 与本地附件差异
│   │   ├── articles/<id>.json   # 背景文章正文
│   │   ├── api/<id>.json        # 补充源元信息
│   │   └── errors/<id>.json     # 失败证据（状态码、body 片段）
│   ├── tables/<id>.csv          # Open-Meteo/NASA/Copernicus 的表格
│   ├── manual/                  # 人工保存的公开页面快照（gitignore）
│   ├── tpdc_files/<id>/*.zip    # TPDC 免登录下载的原始 ZIP（gitignore）
│   ├── reports/
│   │   ├── source_audit.md      # 来源审计报告（给论文手）
│   │   ├── source_audit.csv     # 同上的机读版
│   │   ├── validation.md        # 逐来源质量核验（FAIL/WARN/BLOCKED）
│   │   ├── validation.csv
│   │   ├── data_governance.md   # 数据来源角色/质量/不确定性传导
│   │   ├── data_governance.csv
│   │   ├── existing_data_audit.md # 已有 8 组附件的格式/时间/空间/质量审计
│   │   ├── existing_data_audit.csv
│   │   └── event_window_audit.md
│   ├── data_cards/<id>.md       # 每来源一张数据卡（角色/边界/质量/风险）
│   ├── processed/               # 第一批基线（TPDC-01/02/06），可再生
│   │   ├── manifest.json
│   │   ├── README.md
│   │   ├── tpdc01_hourly/
│   │   ├── tpdc02_temp/
│   │   └── tpdc06_points/
│   ├── runs/<run_id>.json       # 每次运行的汇总
│   └── manifest.jsonl           # 一行一个请求的审计清单
├── logs/crawl.log
└── README.md
```

`data/` 的入库策略：**元数据（`meta/`）、审计/治理报告（`reports/`）和数据卡（`data_cards/`）入库**，作为可复核证据；**原始响应（`raw/`）、缓存（`cache/`）、数据表（`tables/`）、TPDC 下载 ZIP（`tpdc_files/`）、人工快照、运行日志不入库**，可用 `fetch`/`download` 一键重建。见本目录 `.gitignore`。

---

## 5. 每个来源抓什么

### 5.1 TPDC 八个数据集

对每个 UUID 调两个公开接口：

- `POST https://www.tpdc.ac.cn/view/metadataView/detail/`
  body：`{"userId": "", "metadataId": "<uuid>"}`
  返回：`metadataVO`、作者、主题词、相关数据、文献等。
- `GET https://www.tpdc.ac.cn/view/metadataView/getGoogleJson?metadataId=<uuid>`
  返回：schema.org JSON-LD（英文标题、关键词、creator、publisher）。

统一后的字段包括：

`title/title_en`、`doi/doi_url`、`cstr`、`authors`、`publisher`、`year`、`description`、`instructions`、`use_terms`、`time_coverage`、`spatial_coverage`、`keywords`、`citation_cn`、`citation_en`、`local_mirror`、`download_status`。

**本地附件核对**：配置里 `local_mirror` 指向 `05_辅助文档/题目附件/附件/...`，工具会记录文件是否存在、大小、sha256（>64 MiB 的 RAR 只记大小，避免每次抓元数据都重算）。

**数据文件下载**：TPDC 详情页提供“免登录下载”按钮，前端调用公开接口：

```text
GET  /file/file/getRootFileDataList?metadataId=<uuid>
POST /file/file/batchDownloadFile?metadataId=<uuid>   body: {"noToken": true}
```

`download` 命令复用同一公开接口，不伪造登录态；下载的 ZIP 存到 `data/tpdc_files/<id>/`，会做 ZIP 完整性校验，并与本地附件比对文件成员。默认跳过总大小 >50 MB 的数据集（3 号冰川 RAR、5 号土地覆盖），用 `--include-large` 可下载。

> 实测发现：TPDC-01 的免登录 ZIP 只有 21 个文件，缺 `FLUX_Gyirong_2024/2025/2026.csv`；本地附件有 24 个。建模以本地附件为准，下载 ZIP 作为“公开可获取性”的证据。

### 5.2 背景文章

通用 `article` 解析器：

- 按配置的 XPath 取标题、发布时间、正文容器；
- 删除 `script/style/noscript`，去掉私有区字符与零宽字符；
- 保存正文、段落数、字数、正文 hash、链接、图片；
- 正文容器找不到时，退化为“包含最多 `<p>` 文本的 div”。

### 5.3 补充 API

- `open_meteo`：`hourly` 字典 → 一行一小时；保留单位、时区、海拔、API 参数；
- `nasa_power`：`properties.parameter` → 一行一小时；`fill_value` 转 `None`；保留单位、时间标准、网格海拔；
- `copernicus`：OData `value[]` → 产品元数据表；解析 `GeoFootprint` 的 bbox；不下载产品。

---

## 6. 合规与边界

- **robots.txt**：默认遵守；`open_meteo`/`nasa_power`/`copernicus` 是公开 API，配置里显式 `respect_robots: false`，按 API 条款使用，不抓 HTML 页面。
- **限速**：TPDC 0.8 s/请求，MNR 2 s，Baidu 3 s，API 1 s；避免给公共服务器造成压力。
- **不绕过**：百度百科返回“百度安全验证”，本工具不伪造 cookie、不接打码、不绕过；只保留引用链接，并在 `data/meta/errors/` 记录失败。
- **不代填凭据**：Copernicus 下载需要账号/OAuth；工具只取公开元数据，不读取/保存任何账号密码。
- **TPDC 数据文件**：官网提供免登录下载接口（`batchDownloadFile` + `noToken`），工具直接复用；大文件（3 号 268.9 MB、5 号 100.4 MB）默认跳过，`--include-large` 可下载。下载 ZIP 与本地附件不一致时会在 `validate` 里报 WARN。
- **百度百科**：反爬阻断，支持人工保存公开页面到 `data/manual/baike_debris_flow.html`，再用 `fetch baike_debris_flow` 离线解析；不伪造 cookie、不接打码。
- **不伪造**：所有数值来自响应；缺失写 `null`/空，不补零、不猜测。TPDC 的 9999.9 只在原始数据里保留，元数据层不把它转成 0。
- **可复现**：每个请求有 URL、参数、状态、时间、sha256；`--offline` 可只用缓存复算。

---

## 7. 已知数据审计结论（写论文时直接用）
这些是抓取/核对后得到的关键事实，建议写进“数据来源与预处理”一节：

1. **站点与时间**：TPDC-01 元数据写明站点位于吉隆县城（约 **28.86°N, 85.29°E, 4140 m**），距吉隆口岸直线约 **65 km**；时间采用 **北京时间 UTC+8**；缺测标记 **9999.9**；QC 码 **0 正确 / 1 可疑 / 2 错误 / 4 插补 / 8 缺失 / 9 未质控**。
2. **坐标不一致**：`getGoogleJson` 的英文描述里写 28.26°N，与 `detail` 的 28.86°N 不一致；本工具以 `detail` 为准，论文引用时不要用 GoogleJson 的坐标。
3. **TPDC-06 历史灾点**：84 个沟域多边形，字段含 `解译Time`/`影像Time`，**没有事件发生时间**；只能做“登记沟域”空间标签，不能当逐次灾害时间标签。
4. **TPDC-02 长期气温**：序列到 2025-08-05 附近，2025 年不完整；做年度趋势时要排除 2025 或明确标注。
5. **TPDC-03 冰川 RAR**：268.88 MB，`7z` 可读，含 2000–2020 分时段 dhdt 分幅；不是“不可用”，只是量大，需要筛选。
6. **TPDC-07 DEM**：约 30 m；附件名没有说明获取时点，不能预设为“灾前 DEM”。
7. **TPDC-08 人口**：县级多边形合计 **17,536 人**，不含居民点；不能把“县人口/县面积”当作局部暴露。
8. **Open-Meteo / NASA POWER**：都是再分析/预报，不是站点实测；两者网格海拔分别约 4138 m 和 4995 m，和站点 4140 m 的差异要在论文里说明。
9. **Copernicus**：只取产品元数据；查询用吉隆口岸核心区 bbox，当前 S2/S1 各 10 个产品均与研究区相交；仍建议使用前按 `GeoFootprint` 复核；下载需账号。
10. **百度百科**：robots/403 阻断，不作为数据证据；背景以自然资源部页面为准。
11. **TPDC 免登录下载**：`download` 命令可绕过登录页直接拿公开 ZIP（`noToken` 是官网前端公开流程），但 TPDC-01 的 ZIP 只有 21 个文件，缺 **FLUX 2024–2026**；本地附件有 24 个，建模以本地附件为准。

### 7.1 事件窗口核对（`audit` 命令）

`python -m mtmcm_data audit` 会读取 TPDC-01 的 2026 年 MET 文件、Open-Meteo 历史表和 NASA POWER 表，算事件前 72 小时的降水：

| 来源 | 变量 | 累计 | 非零小时 | 说明 |
|---|---|---|---|---|
| TPDC-01 站点 | `Precip(mm)` | **0.00 mm** | 0 | 单点观测，距口岸约 65 km |
| Open-Meteo（ERA5） | `precipitation` | 0.70 mm | 6 | 再分析网格，海拔约 4138 m |
| NASA POWER | `PRECTOTCORR` | 8.46 mm | 58 | 再分析网格，海拔约 4995 m |

结论：**站点灾前 72 小时无降水，但再分析网格有非零降水**；不能把“本站零降雨”写成“没有水源”，也不能把再分析降水写成“站点实测”。这段核对可以直接支撑 Q1 的“事件窗口异常”与 Q3 的“预警不能只看本站雨量”。完整输出见 `data/reports/event_window_audit.md`。

### 7.2 质量核验结果（`validate` 命令）

当前一次实测运行的结果：

- **15 个来源：FAIL 0，WARN 5，BLOCKED 1。**
- **WARN（时间）**：TPDC-04/06/08 的元数据没有给 `startTime/endTime`，标题/附件也没有可提取的时间提示；不是抓取失败，论文中写“元数据未给出时间范围”即可。
- **WARN（下载）**：TPDC-03 的 268.9 MB RAR 默认跳过；TPDC-01 的免登录 ZIP 缺 3 个 FLUX 文件（2024–2026），本地附件 24 个完整。
- **BLOCKED**：百度百科 robots/403；工具不绕过，只保留引用链接。
- **Copernicus**：S2 返回 10 个产品（5 个 L1C、5 个 L2A），S1 返回 10 个（4 个 GRDH、2 个 SLC、2 个 RAW），全部与研究区相交；产品下载仍需账号/OAuth。
- **TPDC 引用**：八个数据集均已生成 `.ris`，可直接导入 Zotero/EndNote。

> 质量核验不是“抓到了就算”，而是逐项检查：元数据字段、本地附件、时间/空间范围、正文长度、API 行数、研究区相交、产品类型。详细结果见 `data/reports/validation.md`。

### 7.3 数据治理报告（`governance` 命令）

按《DS 关于数据治理的建议》落地：**爬虫是采集手段，数据治理才是论文贡献**。`governance` 生成：

- `data/reports/data_governance.md`
  - 数据来源与角色表（来源、角色、时间/空间分辨率、许可、对应问题、状态、访问日期）；
  - 治理流程图（Mermaid：采集→去重→坐标/单位→时空对齐→缺失/QC→质量标记→快照→模型）；
  - 质量评估表（完整率、时间戳基准、空间分辨率、代表性/质量标记、参与建模、不确定性用途）；
  - 四问证据链；
  - **质量不确定性如何进入四问**（Q1 排序不确定性、Q2 空间外推边界、Q3 时间区间条件、Q4 情景包络）；
  - 风险检查（时间泄漏、虚假精度）；
  - 可复现性附录。
- `data/data_cards/<source_id>.md`：每来源一张数据卡（能支持/不能支持/质量标记/风险/复现）。
- `config/governance.json`：治理配置，新增来源时必须补条目；`validate` 会检查。

> 关键写法：不要把“爬了很多数据”当亮点；要写“可追溯的多源数据治理 + 质量不确定性传导 + 关键缺口补齐”。

### 7.4 已有 8 组附件的审计（`existing` 命令）

`python -m mtmcm_data existing` 直接读 `05_辅助文档/题目附件/附件/`，输出 `data/reports/existing_data_audit.md`。它回答“先内后外”的第一步：

| 数据集 | 关键审计结果 |
|---|---|
| TPDC-01 | 24 CSV / 210,336 行；MET/SOIL 缺测约 11%，FLUX 约 32%；有效观测约 2021-04-23 至 2026-08-27；事件前 72 h 降水 0.0 mm |
| TPDC-02 | 21 XLSX / 7,519 行；2025 只有 214 天（到 08-02） |
| TPDC-03 | 168 个 TIFF，4 个 5 年时段；含 dhdt 与 dhdt_err |
| TPDC-04 | HDF5/NetCDF4；变量含 DEM/slope/thickness/velocity；CRS 为 UTM45N |
| TPDC-05 | 4 期 6336×3957、30 m；0 是 nodata，1–10 无图例 |
| TPDC-06 | 84 个多边形、33 字段；**无事件发生时间**，只有解译/影像时间 |
| TPDC-07 | 1816×1148、30 m；实际 85.1898–85.6941E, 28.2455–28.5644N；高程 1621–7254 m |
| TPDC-08 | 1 个县多边形；合计 17,536，另有“人口数”16,155（口径不同） |

报告还给出 7 步治理流水线（登记冻结→格式审计→时空基准→缺失/异常→质量标记→派生层→冻结交接）和“先内后外”的外部补充准入条件。

当前总体治理状态与四问“能写/不能写”见 [`data/reports/data_governance_status.md`](data/reports/data_governance_status.md)。

### 7.5 processed 基线（`process --batch 1-7/all`）

`--batch 1` 气象/灾点长表；`--batch 2` 土地覆盖/DEM 派生；`--batch 3` 主流路纵剖面；`--batch 4` 历史沟域空间叠加；`--batch 5` 主流路阈值/填洼敏感性；`--batch 6` Q2 WOE 易发性基线；`--batch 7` 事件时间/降雨/历史灾情目录；`--batch all` 全部。只做已有数据的“可建模基线”，不掺外部数据。

**第一批（TPDC-01/02/06）**

| 目录 | 内容 | 规模 |
|---|---|---|
| `tpdc01_hourly/` | `tpdc01_key_vars_long.csv.gz`：时间×变量长表，含 `qc_flag`/`missing_flag`/`qc_missing`/`qc_suspect` | 578,424 行 / 11 变量 / 3.5 MB gz |
| `tpdc01_hourly/` | `tpdc01_missing_by_variable.csv` + `tpdc01_variable_dictionary.csv` | 11 行缺测汇总 + 变量字典 |
| `tpdc02_temp/` | 长表 + 宽表（日期×县） | 37,595 行 / 7,519 行 |
| `tpdc06_points/` | `tpdc06_points.geojson`：84 个沟域多边形 + 属性；`tpdc06_fields.csv` | 84 features / 33 字段 |

**第二批（TPDC-05/07）**

| 目录 | 内容 | 规模 |
|---|---|---|
| `tpdc05_landcover/` | `jilong_LUCD_2023.tif`（LZW 重写，nodata=0） | 1.6 MB |
| `tpdc05_landcover/` | `jilong_LUCD_2023_nodata_mask.tif`（1=nodata，0=有效） | 0.3 MB |
| `tpdc05_landcover/` | `tpdc05_class_counts_2023.csv`（0=nodata，1–10 原编码） | 11 类 |
| `tpdc07_dem/` | `dem_core_30m.tif`、`slope_deg.tif`、`flow_accumulation_cells.tif`、`flow_direction_d8.tif`、`channel_mask_acc1000.tif` | DEM 8.0 MB / 坡度 8.9 MB / 汇流 2.1 MB |
| `tpdc07_dem/` | `tpdc07_terrain_stats.csv` | 地形/沟道统计 |

**第三批（TPDC-07 主流路）**

| 目录 | 内容 | 关键值 |
|---|---|---|
| `tpdc07_channel/` | `main_channel_profile.csv`：纵剖面（距离/原始高程/路由高程/水力坡度/汇流） | **1,470 像元 / 49.62 km** |
| `tpdc07_channel/` | `main_channel.geojson` + `main_channel_mask.tif` | LineString / 栅格 |
| `tpdc07_channel/` | `main_channel_summary.json` | 落差 **3,992.74 m**，纵向比降 **8.05%**（4.60°）；填洼前 4,888 sinks → 填洼后 161 |
| `tpdc07_channel/` | `dem_filled_30m.tif`、`flow_direction_filled_d8.tif`、`flow_accumulation_filled.tif` | 主流路使用的填洼 D8 层 |

**第四批（历史沟域 × 地形）**

| 目录 | 内容 | 关键值 |
|---|---|---|
| `spatial_baseline/` | `tpdc06_gully_overlay_stats.csv`：84 个沟域 × DEM/坡度/汇流/土地覆盖 | **23/84 落在 DEM 内** |
| `spatial_baseline/` | `tpdc06_gully_id_mask.tif`：沟域 ID 栅格（1–84） | 27.5 KB |
| `spatial_baseline/` | `summary.json` | DEM 内 408,718 像元；平均坡度 34.04°；沟道像元 **7,574**（填洼 D8） |

**第五批（主流路敏感性）**

| 目录 | 内容 | 关键值 |
|---|---|---|
| `tpdc07_channel_sensitivity/` | `main_channel_sensitivity_runs.csv`：3 阈值 × 3 填洼模式 | **9/9 成功**；填洼后长度 49.57–50.06 km，比降 8.05–8.13% |
| `tpdc07_channel_sensitivity/` | `main_channel_sensitivity.geojson` | 9 条 LineString |
| `tpdc07_channel_sensitivity/` | `summary.json` | 推荐 `epsilon_1e-4 + 1000 cells` |

**第六批（Q2 WOE 易发性）**

| 目录 | 内容 | 关键值 |
|---|---|---|
| `q2_susceptibility/` | `q2_susceptibility_score.tif`：WOE 相对分数 | 全局像素 AUC **0.747** |
| `q2_susceptibility/` | `q2_susceptibility_class.tif`：1–5 分级 | 背景 20/40/60/80 分位 |
| `q2_susceptibility/` | `q2_woe_bins.csv`：坡度/高程/汇流/土地覆盖分箱 WOE | 4 个协变量 |
| `q2_susceptibility/` | `q2_gully_scores.csv` | 23/84 在 DEM 内；沟域均分中位百分位 **0.815** |
| `q2_susceptibility/` | `summary.json` | 2×2 空间块 AUC 仅 **0.528 / 0.650**（两块无正样本） |

**第七批（事件时间/降雨/历史灾情）**

| 目录 | 内容 | 关键值 |
|---|---|---|
| `event_catalog/` | `event_catalog.csv`：已确认事件 | **2 个泥石流事件 + 1 个地震背景** |
| `event_catalog/` | `event_rainfall_windows.csv`：站点/Open-Meteo/NASA 事件窗口降水 | 2026 72h：**0.0 / 0.7 / 8.46 mm** |
| `event_catalog/` | `event_rainfall_hourly.csv.gz` + `evidence_register.csv` | 逐小时降水 + 证据登记 |
| `event_catalog/` | `event_catalog.md` | “非降雨触发”结论与来源 |

关键约束：TPDC-01 的 `9999.9`/`QC=8` 已标缺失、不补零；TPDC-02 的 2025 只有 214 天；TPDC-06 的 `解译Time`/`影像Time` 不是事件发生时间；TPDC-05 的 0 是 nodata，不是类别；batch 2 的 D8 未填洼（4,888 sinks），batch 3/5 主流路用填洼+epsilon D8，两者不能混用；batch 6 的 WOE 是**相对易发性，不是概率**，空间块 AUC 弱；batch 7 只确认 2 个泥石流事件，**2026/2025 均为冰崩/冰湖溃决触发，不是降雨触发**。

---

## 8. 和四问的对应

| 问 | 直接可用 | 用法 |
|---|---|---|
| Q1 | TPDC-01/02、MNR、Open-Meteo、NASA POWER | 构造边界层/辐射/土壤/湍流特征；事件窗口 vs 同季节背景 |
| Q2 | TPDC-03~07、Sentinel-1/2 元数据、Open-Meteo | 地形/土地覆盖/冰川/历史沟域；临界条件与空间易发性 |
| Q3 | TPDC-01/02、Open-Meteo archive/forecast、NASA POWER | 触发时间区间、预警提前量的代理验证；不要把预报当实测 |
| Q4 | TPDC-03/04/07/08、Sentinel-1 元数据 | DEM/冰川厚度速度/人口/SAR 范围；守恒仿真与暴露情景 |

---

## 9. 如何新增一个来源

1. 在 `config/sources.json` 的 `sources` 里加一项；
2. 如果是 HTML，`kind: "article"` + `selectors` 三个 XPath；
3. 如果是 JSON API，`kind: "api_json"` + `parser`（`open_meteo`/`nasa_power`/`copernicus`）；
4. 如果是 TPDC 数据集，`kind: "tpdc_dataset"` + `metadata_id` + `local_mirror`；
5. 跑 `python -m mtmcm_data fetch <id> --refresh`，再跑 `report` 和 `verify`。

新增 parser 时，在 `mtmcm_data/parsers/` 加一个模块，返回 `(meta, rows)`，并在 `cli.fetch_api` 里注册。

---

## 10. 测试

```powershell
python -m unittest discover -s tests -v
```

测试不联网，覆盖：

- TPDC detail + GoogleJson 的归一化与引用生成；
- MNR 风格 HTML 的标题/日期/正文抽取；
- Open-Meteo / NASA POWER / Copernicus 的字段与 bbox；
- 配置完整性、manifest 追加/读取、URL 参数编码。

---

## 11. 已知限制 / 下一步

- **TPDC 数据文件**：已支持免登录下载；3 号（268.9 MB RAR）与 5 号（100.4 MB 土地覆盖）默认跳过，后者已用 `--include-large` 实测通过。TPDC-01 免登录 ZIP 缺 3 个 FLUX 文件，已在 `validate` 里留 WARN；建模以本地 24 文件附件为准。
- **百度百科**：反爬阻断，未做绕过；如比赛允许，可人工保存快照到 `data/manual/`，再用 `article` 解析器离线解析。
- **ERA5/CDS**：需要 API key，未默认启用；如需要，可加一个 `cds` parser，从环境变量读 key。
- **地图/暴露**：OSM/Overpass、WorldPop 等还没纳入；Q4 需要建筑/道路/居民点时可再加。
- **时区**：TPDC 为 UTC+8；NASA POWER 为 LST；Open-Meteo 显式 `Asia/Shanghai`。跨源合并前必须统一时间轴。
- **治理配置**：新增来源必须同时补 `config/governance.json`（角色、能/不能、质量标记、不确定性、风险），否则 `validate` 报 WARN。

---

## 12. 一句话

> 这个工具不是“把网页抓下来”，而是把**数据来源变成可引用、可复核、可复现的证据链**；抓不到的来源也要留下“为什么抓不到”的记录。
