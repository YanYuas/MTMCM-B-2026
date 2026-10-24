# B 题数据来源审计报告

> 生成时间：2026-10-24T11:37:04+08:00
> 工具：`03_编程手/数据获取`（`python -m mtmcm_data fetch all && python -m mtmcm_data report`）
> 配套数据治理：`data/reports/data_governance.md`（角色/质量/不确定性传导）与 `data/data_cards/`。
> 原则：每个来源都保留 URL、抓取时间、HTTP 状态和 sha256；失败也留痕，不绕过登录/反爬。

**汇总**：15 个来源，OK 14，FAILED/BLOCKED 1。

## 1. 来源总表

| 来源 | 类型 | 对应问题 | 状态 | 抓取时间 | 备注 |
|---|---|---|---|---|---|
| `tpdc_01_hourly` | tpdc_dataset | Q1、Q3 | OK | 2026-10-24T03:05:20+00:00 | MET/RADM/SOIL/FLUX 四类逐小时数据；元数据明确北京时间 UTC+8、缺测 9999.9、QC 码 0/1/2/4/8/9。站点约 28.86N/85.29E/4140m；getGoogleJson 的 28.26N 与 detail 不一致，以 detail 为准。 |
| `tpdc_02_temp` | tpdc_dataset | Q1、Q3 | OK | 2026-10-24T03:05:34+00:00 | 长期气温背景；2025 年序列不完整，年度趋势结论需谨慎。 |
| `tpdc_03_glacier_rar` | tpdc_dataset | Q2、Q4 | OK | 2026-10-24T02:58:41+00:00 | 268 MB RAR，7z 可读；含 2000–2020 分时段 dhdt 分幅 TIFF。 |
| `tpdc_04_glacier_nc` | tpdc_dataset | Q2、Q4 | OK | 2026-10-24T03:05:56+00:00 | 30 m 网格；冰厚为估算，速度为 2014–2024 气候态。 |
| `tpdc_05_landcover` | tpdc_dataset | Q2 | OK | 2026-10-24T03:07:09+00:00 | 四期 30 m 栅格；附件无类别图例，保留原始编码。 |
| `tpdc_06_disaster_points` | tpdc_dataset | Q2 | OK | 2026-10-24T03:06:13+00:00 | 84 个沟域多边形；只有解译时间/影像时间，没有事件发生时间。 |
| `tpdc_07_dem` | tpdc_dataset | Q2、Q4 | OK | 2026-10-24T03:06:35+00:00 | 约 30 m DEM；获取时点未在附件名中说明，不能预设为灾前地形。 |
| `tpdc_08_population` | tpdc_dataset | Q4 | OK | 2026-10-24T03:06:44+00:00 | 县级多边形，合计 17,536 人；不含居民点，不能直接细化局部暴露。 |
| `mnr_debris_conditions` | article | Q1、Q2 | OK | 2026-10-24T02:42:41+00:00 | 官方背景页，用来支撑“地形—物质—水源”三条件，不作为观测数据。 |
| `baike_debris_flow` | article | 背景 | BLOCKED | 2026-10-24T02:45:06+00:00 | 百度安全验证 403；不绕过反爬，只保留引用链接并记录失败证据，正文背景以自然资源部页面为准。 |
| `open_meteo_archive` | api_json | Q1、Q2、Q3 | OK | 2026-10-24T02:38:37+00:00 | 公开 API，按 API 条款使用；网格点海拔约 4138 m，不能替代站点实测。 |
| `open_meteo_forecast` | api_json | Q3 | OK | 2026-10-24T02:38:38+00:00 | 用于演示“未来 72 h”预报接口；历史事件复盘不要把它当实测。 |
| `nasa_power` | api_json | Q1、Q3 | OK | 2026-10-24T02:38:40+00:00 | 再分析交叉核对；API 返回的网格海拔约 4995 m，与站点 4140 m 不同，必须标注。 |
| `copernicus_s2` | api_json | Q2 | OK | 2026-10-24T02:50:54+00:00 | 公开元数据检索；空间过滤 bbox 85.15–85.55E, 28.15–28.55N（吉隆口岸/沟谷核心区）；返回产品仍可能只覆盖边缘，使用前需按 GeoFootprint 与核心区求交。产品下载需要 Copernicus 账号/OAuth，本工具只取元数据并记录下载条件。 |
| `copernicus_s1` | api_json | Q2、Q4 | OK | 2026-10-24T02:50:56+00:00 | SAR 元数据；空间过滤 bbox 85.15–85.55E, 28.15–28.55N（吉隆口岸/沟谷核心区），返回产品可能只覆盖边缘。用于冰崩/泥石流灾后范围核查，下载需要账号。 |

## 2. TPDC 八个数据集

| 来源 | 标题 | DOI | 时间范围 | 空间范围 | 本地附件 |
|---|---|---|---|---|---|
| `tpdc_01_hourly` | 西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026） | 10.11888/Atmos.tpdc.303600 | 2021-04-26 20:00:00 → 2026-08-27 08:00:00 | 点 (85.2900, 28.8600) | 有，9.83 MB |
| `tpdc_02_temp` | 2005-2025年吉隆县及周边县市逐日平均气温数据 | 10.24381/cds.e9c9c792 | 2005-01-01 02:58:37 → 2025-08-05 02:58:37 | 84.4510–86.1583, 28.2555–29.3217 | 有，0.75 MB |
| `tpdc_03_glacier_rar` | 日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集（2000—2020年） | 10.11888/Cryos.tpdc.303615 | 未给（标题：2000–2020） | 83.4714–87.5492, 26.4885–30.0977 | 有，268.88 MB |
| `tpdc_04_glacier_nc` | 吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集 | 10.11888/Cryos.tpdc.303606 | 未给 | 85.5053–85.5501, 28.2691–28.3069 | 有，0.32 MB |
| `tpdc_05_landcover` | 西藏日喀则市吉隆县泥石流灾害区土地覆盖数据（2020-2023） | 10.1038/s41597-025-04759-6 | 未给（标题：2020–2023） | 84.0000–87.0000, 28.0000–30.0000 | 有，6.61 MB |
| `tpdc_06_disaster_points` | 西藏日喀则市吉隆县泥石流灾害区历史灾点数据 | 无 | 未给 | 85.0100–85.4800, 28.2600–29.0000 | 有，0.12 MB |
| `tpdc_07_dem` | 2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据 | 无 | 未给（标题：2026-08-26） | 84.4500–86.1600, 28.2600–29.3200 | 有，10.38 MB |
| `tpdc_08_population` | 西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据 | 无 | 未给 | 84.4500–86.1600, 28.2600–29.3200 | 有，0.04 MB |

### 2.1 TPDC 文件下载核对

| 来源 | 文件数 | 总大小 | 下载状态 | ZIP | 与本地附件差异 |
|---|---|---|---|---|---|
| `tpdc_01_hourly` | 21 | 25.0 MB | ok | 21 文件 / 7.3 MB | 缺 3 个: FLUX_Gyirong_2024.csv, FLUX_Gyirong_2025.csv, FLUX_Gyirong_2026.csv |
| `tpdc_02_temp` | 2 | 0.8 MB | ok | 2 文件 / 0.7 MB | 一致（嵌套 ZIP） |
| `tpdc_03_glacier_rar` | 1 | 268.9 MB | skipped_large | — | — |
| `tpdc_04_glacier_nc` | 1 | 0.4 MB | ok | 1 文件 / 0.3 MB | 一致 |
| `tpdc_05_landcover` | 4 | 100.4 MB | ok | 4 文件 / 6.6 MB | 一致 |
| `tpdc_06_disaster_points` | 1 | 0.1 MB | ok | 1 文件 / 0.1 MB | 一致（嵌套 ZIP） |
| `tpdc_07_dem` | 5 | 10.7 MB | ok | 5 文件 / 10.4 MB | 一致 |
| `tpdc_08_population` | 1 | 0.0 MB | ok | 1 文件 / 0.0 MB | 一致（嵌套 ZIP） |

### 2.2 关键审计发现（人工摘要）

> 以下结论来自 TPDC 元数据与本地附件核对；逐条可在 `data/meta/tpdc/*.json` 中复核。

- **TPDC-01**：站点约 **28.86°N, 85.29°E, 4140 m**，距吉隆口岸约 **65 km**；时间为 **北京时间 UTC+8**；缺测 **9999.9**；QC 码 **0/1/2/4/8/9**。
- **TPDC-01 下载差异**：免登录 ZIP 只有 21 个文件，缺 `FLUX_Gyirong_2024/2025/2026.csv`；本地附件有 24 个，建模以本地附件为准。
- **坐标冲突**：`getGoogleJson` 英文描述写 28.26°N，与 `detail` 的 28.86°N 不一致；本工具以 `detail` 为准，论文引用不要用 GoogleJson 的坐标。
- **TPDC-06**：84 个沟域多边形，字段只有 `解译Time`/`影像Time`，**没有事件发生时间**；只能做“登记沟域”空间标签。
- **TPDC-02/07/08**：日气温 2025 年不完整；DEM 获取时点未说明；人口为县级多边形（合计 17,536 人），不含居民点。
- **TPDC-03**：268.88 MB RAR，`7z` 可读；不是“数据不可用”，只是量大，需要筛选 2000–2020 分时段 dhdt。
- **补充源**：Open-Meteo / NASA POWER 是再分析或预报，不是站点实测；网格海拔约 4138 m / 4995 m，与站点 4140 m 不同。百度百科被 robots/403 阻断，背景以自然资源部页面为准。

## 3. 补充数据与背景来源

| 来源 | 内容 | 行数/字数 | 时间范围 | 状态 |
|---|---|---|---|---|
| `mnr_debris_conditions` | 泥石流形成的基本条件 | 900 字 | 2025-01-14 21:06 | OK |
| `baike_debris_flow` | 百度百科：泥石流灾害 | 未抓取 | 未给 | BLOCKED |
| `open_meteo_archive` | Open-Meteo 历史天气（ERA5 再分析） | 216 行 | 2026-08-20T00:00 → 2026-08-28T23:00 | OK |
| `open_meteo_forecast` | Open-Meteo 天气预报（业务预报接口） | 72 行 | 2026-10-24T00:00 → 2026-10-26T23:00 | OK |
| `nasa_power` | NASA POWER 逐小时气象（MERRA-2 / POWER） | 216 行 | 2026-08-20T00:00:00 → 2026-08-28T23:00:00 | OK |
| `copernicus_s2` | Copernicus Data Space：Sentinel-2 L1C/L2A 产品元数据 | 10 行 | 2026-08-22T04:56:51.024000Z → 2026-08-29T04:47:01.025000Z | OK |
| `copernicus_s1` | Copernicus Data Space：Sentinel-1 产品元数据 | 10 行 | 2026-08-24T00:18:40.857155Z → 2026-08-28T12:22:10.463264Z | OK |

## 4. 与四问的证据对应

> 说明：这里只列“可支撑哪一问的数据证据”，不代表该数据已经足以回答该问。

| 问 | 可用来源 | 用途 |
|---|---|---|
| Q1 | `tpdc_01_hourly`, `tpdc_02_temp`, `mnr_debris_conditions`, `open_meteo_archive`, `nasa_power` | 边界层/辐射/土壤/湍流特征，事件窗口与同季节背景对比。 |
| Q2 | `tpdc_03_glacier_rar`, `tpdc_04_glacier_nc`, `tpdc_05_landcover`, `tpdc_06_disaster_points`, `tpdc_07_dem`, `mnr_debris_conditions`, `open_meteo_archive`, `copernicus_s2`, `copernicus_s1` | 地形、土地覆盖、历史沟域、冰川与卫星元数据，支撑临界条件与空间易发性。 |
| Q3 | `tpdc_01_hourly`, `tpdc_02_temp`, `open_meteo_archive`, `open_meteo_forecast`, `nasa_power` | 再分析/预报/长期气温，支撑触发时间区间与预警提前量的代理验证。 |
| Q4 | `tpdc_03_glacier_rar`, `tpdc_04_glacier_nc`, `tpdc_07_dem`, `tpdc_08_population`, `copernicus_s1` | DEM、冰川厚度/速度、人口与 SAR 元数据，支撑守恒仿真与暴露情景。 |

## 5. 可直接引用的来源

- **tpdc_01_hourly**：马耀明，马伟强，谢志鹏，等. 西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026）[DS]. 国家青藏高原科学数据中心, 2026. DOI: 10.11888/Atmos.tpdc.303600.
- **tpdc_02_temp**：Copernicus Climate Change Service. 2005-2025年吉隆县及周边县市逐日平均气温数据[DS]. 国家青藏高原科学数据中心, 2026. DOI: 10.24381/cds.e9c9c792.
- **tpdc_03_glacier_rar**：汪嬴政. 日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集（2000—2020年）[DS]. 国家青藏高原科学数据中心, 2026. DOI: 10.11888/Cryos.tpdc.303615.
- **tpdc_04_glacier_nc**：赵宏宇，张通. 吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集[DS]. 国家青藏高原科学数据中心, 2026. DOI: 10.11888/Cryos.tpdc.303606.
- **tpdc_05_landcover**：李思雅. 西藏日喀则市吉隆县泥石流灾害区土地覆盖数据（2020-2023）[DS]. 国家青藏高原科学数据中心, 2026. DOI: 10.1038/s41597-025-04759-6.
- **tpdc_06_disaster_points**：邹强. 西藏日喀则市吉隆县泥石流灾害区历史灾点数据[DS]. 国家青藏高原科学数据中心, 2026.
- **tpdc_07_dem**：高分辨率对地观测系统甘肃数据与应用中心. 2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据[DS]. 国家青藏高原科学数据中心, 2026.
- **tpdc_08_population**：国家统计局，吉隆县统计局. 西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据[DS]. 国家青藏高原科学数据中心, 2026.
- **mnr_debris_conditions**：自然资源部 地球科普. 泥石流形成的基本条件[EB/OL]. 2025-01-14 21:06. https://www.mnr.gov.cn/zt/hd/dqr/43earthday/dqkp/201203/t20120316_2057013.html（访问日期 2026-10-24）.
- **baike_debris_flow**：百度百科. 泥石流灾害[EB/OL]. https://baike.baidu.com/item/%E6%B3%A5%E7%9F%B3%E6%B5%81%E7%81%BE%E5%AE%B3/9911941（访问日期 2026-10-24）.
- **open_meteo_archive**：Open-Meteo. Historical/Forecast Weather API[DB/OL]. https://open-meteo.com/（访问日期 2026-10-24）.
- **open_meteo_forecast**：Open-Meteo. Historical/Forecast Weather API[DB/OL]. https://open-meteo.com/（访问日期 2026-10-24）.
- **nasa_power**：NASA POWER. Hourly Point Data[DB/OL]. https://power.larc.nasa.gov/（访问日期 2026-10-24）.
- **copernicus_s2**：Copernicus Data Space Ecosystem. Sentinel product metadata via OData API[DB/OL]. https://dataspace.copernicus.eu/（访问日期 2026-10-24）.
- **copernicus_s1**：Copernicus Data Space Ecosystem. Sentinel product metadata via OData API[DB/OL]. https://dataspace.copernicus.eu/（访问日期 2026-10-24）.

- TPDC 八个数据集已生成 `data/meta/tpdc/<uuid>.ris`，可直接导入 Zotero/EndNote。

## 6. 失败、受限与合规说明

- `baike_debris_flow`：BLOCKED；robots.txt 禁止抓取。

- 百度百科返回 403（百度安全验证），本工具**不绕过**反爬，只保留引用链接并记录失败证据；背景知识以自然资源部页面为准。
- Copernicus 只取公开产品元数据；产品下载需要账号/OAuth，工具不代填凭据。
- Open-Meteo / NASA POWER 为再分析或预报产品，不能当作站点实测；网格海拔与站点海拔不同，引用时必须标注。
- TPDC 数据使用需按元数据中的 `useTerms` 注明数据来源与作者；本报告已生成 `citation_cn`。

## 7. 复现

```powershell
cd "03_编程手/数据获取"
python -m mtmcm_data fetch all --refresh
python -m mtmcm_data download all
python -m mtmcm_data existing
python -m mtmcm_data process --batch 1
python -m mtmcm_data report
python -m mtmcm_data audit
python -m mtmcm_data validate
python -m mtmcm_data governance
python -m mtmcm_data verify
```
