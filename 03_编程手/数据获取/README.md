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

# 2) 抓全部（首次会建缓存；--refresh 强制重抓）
python -m mtmcm_data fetch all

# 3) 生成审计报告
python -m mtmcm_data report

# 4) 核验 raw 文件与本地附件
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
│   │   ├── articles/<id>.json   # 背景文章正文
│   │   ├── api/<id>.json        # 补充源元信息
│   │   └── errors/<id>.json     # 失败证据（状态码、body 片段）
│   ├── tables/<id>.csv          # Open-Meteo/NASA/Copernicus 的表格
│   ├── reports/
│   │   ├── source_audit.md      # 来源审计报告（给论文手）
│   │   └── source_audit.csv     # 同上的机读版
│   ├── runs/<run_id>.json       # 每次运行的汇总
│   └── manifest.jsonl           # 一行一个请求的审计清单
├── logs/crawl.log
└── README.md
```

`data/` 的入库策略：**元数据（`meta/`）和审计报告（`reports/`）入库**，作为可复核证据；**原始响应（`raw/`）、缓存（`cache/`）、数据表（`tables/`）、运行日志不入库**，可用 `fetch` 一键重建。见本目录 `.gitignore`。

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
9. **Copernicus**：只取产品元数据；返回产品可能只覆盖研究区边缘，使用前要按 `GeoFootprint` 与核心区求交；下载需账号。
10. **百度百科**：robots/403 阻断，不作为数据证据；背景以自然资源部页面为准。

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

- **TPDC 数据文件**：本工具以元数据 + 本地附件核对为主；TPDC 文件下载通常需要登录/申请，未在工具里代填凭据。若拿到公开直链，可在 `tpdc_dataset` 分支加 `download`。
- **百度百科**：反爬阻断，未做绕过；如比赛允许，可人工保存快照到 `data/manual/`，再用 `article` 解析器离线解析。
- **ERA5/CDS**：需要 API key，未默认启用；如需要，可加一个 `cds` parser，从环境变量读 key。
- **地图/暴露**：OSM/Overpass、WorldPop 等还没纳入；Q4 需要建筑/道路/居民点时可再加。
- **时区**：TPDC 为 UTC+8；NASA POWER 为 LST；Open-Meteo 显式 `Asia/Shanghai`。跨源合并前必须统一时间轴。

---

## 12. 一句话

> 这个工具不是“把网页抓下来”，而是把**数据来源变成可引用、可复核、可复现的证据链**；抓不到的来源也要留下“为什么抓不到”的记录。
