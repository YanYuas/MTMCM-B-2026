# 数据获取质量核验

**结论：通过** — OK 154 / WARN 5 / FAIL 0 / BLOCKED 1

> 说明：FAIL 表示工具/数据不满足最低要求；WARN 表示可用但需在论文中说明；BLOCKED 表示来源被合规地放弃（如 robots/403）。

## 按来源汇总

| 来源 | 最差状态 | 说明 |
|---|---|---|
| `tpdc_01_hourly` | WARN | 下载 ZIP 缺 3 个本地文件: FLUX_Gyirong_2024.csv, FLUX_Gyirong_2025.csv, FLUX_Gyirong_2026.csv |
| `tpdc_02_temp` | OK | 字段齐全 |
| `tpdc_03_glacier_rar` | WARN | 总大小 268.9 MB > max_mb=50.0；如需下载用 --include-large |
| `tpdc_04_glacier_nc` | WARN | 未给 |
| `tpdc_05_landcover` | OK | 字段齐全 |
| `tpdc_06_disaster_points` | WARN | 未给 |
| `tpdc_07_dem` | OK | 字段齐全 |
| `tpdc_08_population` | WARN | 未给 |
| `mnr_debris_conditions` | OK | 字段齐全 |
| `baike_debris_flow` | BLOCKED | robots.txt 禁止抓取 |
| `open_meteo_archive` | OK | 字段齐全 |
| `open_meteo_forecast` | OK | 字段齐全 |
| `nasa_power` | OK | 字段齐全 |
| `copernicus_s2` | OK | 字段齐全 |
| `copernicus_s1` | OK | 字段齐全 |

## 逐项检查

| 来源 | 检查项 | 状态 | 说明 |
|---|---|---|---|
| `tpdc_01_hourly` | 治理配置 | OK | 字段齐全 |
| `tpdc_01_hourly` | 抓取 | OK | HTTP 200，2026-10-24T03:05:20+00:00 |
| `tpdc_01_hourly` | 元数据文件 | OK |  |
| `tpdc_01_hourly` | 标题 | OK | 西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026） |
| `tpdc_01_hourly` | metadata_id | OK |  |
| `tpdc_01_hourly` | landing_url | OK |  |
| `tpdc_01_hourly` | citation_cn | OK | 马耀明，马伟强，谢志鹏，等. 西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026）[DS]. 国家青藏高原科学数据中心, 2026. DOI: 10.11888/Atmos.tpdc |
| `tpdc_01_hourly` | 本地附件 | OK | 05_辅助文档/题目附件/附件/（1）西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026）.zip |
| `tpdc_01_hourly` | 空间范围 | OK | {'west': 85.29, 'east': 85.29, 'south': 28.86, 'north': 28.86} |
| `tpdc_01_hourly` | 时间范围 | OK | 2021-04-26 20:00:00 |
| `tpdc_01_hourly` | 描述长度 | OK | 909 字 |
| `tpdc_01_hourly` | 关键词 | OK | 26 个 |
| `tpdc_01_hourly` | RIS 引用 | OK | 255 字符 |
| `tpdc_01_hourly` | 数据文件下载 | OK | 21 个文件，7.3 MB ZIP |
| `tpdc_01_hourly` | 下载与本地附件差异 | WARN | 下载 ZIP 缺 3 个本地文件: FLUX_Gyirong_2024.csv, FLUX_Gyirong_2025.csv, FLUX_Gyirong_2026.csv |
| `tpdc_02_temp` | 治理配置 | OK | 字段齐全 |
| `tpdc_02_temp` | 抓取 | OK | HTTP 200，2026-10-24T03:05:34+00:00 |
| `tpdc_02_temp` | 元数据文件 | OK |  |
| `tpdc_02_temp` | 标题 | OK | 2005-2025年吉隆县及周边县市逐日平均气温数据 |
| `tpdc_02_temp` | metadata_id | OK |  |
| `tpdc_02_temp` | landing_url | OK |  |
| `tpdc_02_temp` | citation_cn | OK | Copernicus Climate Change Service. 2005-2025年吉隆县及周边县市逐日平均气温数据[DS]. 国家青藏高原科学数据中心, 2026. DOI: 10.24381 |
| `tpdc_02_temp` | 本地附件 | OK | 05_辅助文档/题目附件/附件/（2）2005-2025年吉隆县及周边县市逐日平均气温数据.zip |
| `tpdc_02_temp` | 空间范围 | OK | {'west': 84.450983, 'east': 86.158269, 'south': 28.255499, 'north': 29.321711} |
| `tpdc_02_temp` | 时间范围 | OK | 2005-01-01 02:58:37 |
| `tpdc_02_temp` | 描述长度 | OK | 229 字 |
| `tpdc_02_temp` | 关键词 | OK | 11 个 |
| `tpdc_02_temp` | RIS 引用 | OK | 216 字符 |
| `tpdc_02_temp` | 数据文件下载 | OK | 2 个文件，0.7 MB ZIP |
| `tpdc_02_temp` | 下载与本地附件差异 | OK | 嵌套 ZIP，展开后与本地附件一致 |
| `tpdc_03_glacier_rar` | 治理配置 | OK | 字段齐全 |
| `tpdc_03_glacier_rar` | 抓取 | OK | HTTP 200，2026-10-24T02:58:41+00:00 |
| `tpdc_03_glacier_rar` | 元数据文件 | OK |  |
| `tpdc_03_glacier_rar` | 标题 | OK | 日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集（2000—2020年） |
| `tpdc_03_glacier_rar` | metadata_id | OK |  |
| `tpdc_03_glacier_rar` | landing_url | OK |  |
| `tpdc_03_glacier_rar` | citation_cn | OK | 汪嬴政. 日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集（2000—2020年）[DS]. 国家青藏高原科学数据中心, 2026. DOI: 10.11888/Cryos.t |
| `tpdc_03_glacier_rar` | 本地附件 | OK | 05_辅助文档/题目附件/附件/（3）日喀则市吉隆县特大洪水——200km周围内的冰川及冰川表面高程变化数据集 (2000-2020).rar |
| `tpdc_03_glacier_rar` | 空间范围 | OK | {'west': 83.471351, 'east': 87.549247, 'south': 26.488456, 'north': 30.097681} |
| `tpdc_03_glacier_rar` | 时间范围 | OK | 2000–2020 |
| `tpdc_03_glacier_rar` | 描述长度 | OK | 457 字 |
| `tpdc_03_glacier_rar` | 关键词 | OK | 17 个 |
| `tpdc_03_glacier_rar` | RIS 引用 | OK | 218 字符 |
| `tpdc_03_glacier_rar` | 数据文件下载 | WARN | 总大小 268.9 MB > max_mb=50.0；如需下载用 --include-large |
| `tpdc_04_glacier_nc` | 治理配置 | OK | 字段齐全 |
| `tpdc_04_glacier_nc` | 抓取 | OK | HTTP 200，2026-10-24T03:05:56+00:00 |
| `tpdc_04_glacier_nc` | 元数据文件 | OK |  |
| `tpdc_04_glacier_nc` | 标题 | OK | 吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集 |
| `tpdc_04_glacier_nc` | metadata_id | OK |  |
| `tpdc_04_glacier_nc` | landing_url | OK |  |
| `tpdc_04_glacier_nc` | citation_cn | OK | 赵宏宇，张通. 吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集[DS]. 国家青藏高原科学数据中心, 2026. DOI: 10.11888/Cryos.tpdc.303606. |
| `tpdc_04_glacier_nc` | 本地附件 | OK | 05_辅助文档/题目附件/附件/（4）吉隆口岸山洪灾害-蓝塘里壤峰冰崩前冰川地形、冰厚及表面速度数据集.zip |
| `tpdc_04_glacier_nc` | 空间范围 | OK | {'west': 85.505265, 'east': 85.550125, 'south': 28.269098, 'north': 28.306935} |
| `tpdc_04_glacier_nc` | 时间范围 | WARN | 未给 |
| `tpdc_04_glacier_nc` | 描述长度 | OK | 255 字 |
| `tpdc_04_glacier_nc` | 关键词 | OK | 25 个 |
| `tpdc_04_glacier_nc` | RIS 引用 | OK | 211 字符 |
| `tpdc_04_glacier_nc` | 数据文件下载 | OK | 1 个文件，0.3 MB ZIP |
| `tpdc_04_glacier_nc` | 下载与本地附件差异 | OK | 与本地附件一致 |
| `tpdc_05_landcover` | 治理配置 | OK | 字段齐全 |
| `tpdc_05_landcover` | 抓取 | OK | HTTP 200，2026-10-24T03:07:09+00:00 |
| `tpdc_05_landcover` | 元数据文件 | OK |  |
| `tpdc_05_landcover` | 标题 | OK | 西藏日喀则市吉隆县泥石流灾害区土地覆盖数据（2020-2023） |
| `tpdc_05_landcover` | metadata_id | OK |  |
| `tpdc_05_landcover` | landing_url | OK |  |
| `tpdc_05_landcover` | citation_cn | OK | 李思雅. 西藏日喀则市吉隆县泥石流灾害区土地覆盖数据（2020-2023）[DS]. 国家青藏高原科学数据中心, 2026. DOI: 10.1038/s41597-025-04759-6. |
| `tpdc_05_landcover` | 本地附件 | OK | 05_辅助文档/题目附件/附件/（5）西藏日喀则市吉隆县泥石流灾害区土地覆盖数据（2020-2023）.zip |
| `tpdc_05_landcover` | 空间范围 | OK | {'west': 84.0, 'east': 87.0, 'south': 28.0, 'north': 30.0} |
| `tpdc_05_landcover` | 时间范围 | OK | 2020–2023 |
| `tpdc_05_landcover` | 描述长度 | OK | 249 字 |
| `tpdc_05_landcover` | 关键词 | OK | 4 个 |
| `tpdc_05_landcover` | RIS 引用 | OK | 202 字符 |
| `tpdc_05_landcover` | 数据文件下载 | OK | 4 个文件，6.6 MB ZIP |
| `tpdc_05_landcover` | 下载与本地附件差异 | OK | 与本地附件一致 |
| `tpdc_06_disaster_points` | 治理配置 | OK | 字段齐全 |
| `tpdc_06_disaster_points` | 抓取 | OK | HTTP 200，2026-10-24T03:06:13+00:00 |
| `tpdc_06_disaster_points` | 元数据文件 | OK |  |
| `tpdc_06_disaster_points` | 标题 | OK | 西藏日喀则市吉隆县泥石流灾害区历史灾点数据 |
| `tpdc_06_disaster_points` | metadata_id | OK |  |
| `tpdc_06_disaster_points` | landing_url | OK |  |
| `tpdc_06_disaster_points` | citation_cn | OK | 邹强. 西藏日喀则市吉隆县泥石流灾害区历史灾点数据[DS]. 国家青藏高原科学数据中心, 2026. |
| `tpdc_06_disaster_points` | 本地附件 | OK | 05_辅助文档/题目附件/附件/（6）西藏日喀则市吉隆县泥石流灾害区历史灾点数据.zip |
| `tpdc_06_disaster_points` | 空间范围 | OK | {'west': 85.01, 'east': 85.48, 'south': 28.26, 'north': 29.0} |
| `tpdc_06_disaster_points` | 时间范围 | WARN | 未给 |
| `tpdc_06_disaster_points` | 描述长度 | OK | 202 字 |
| `tpdc_06_disaster_points` | 关键词 | OK | 9 个 |
| `tpdc_06_disaster_points` | RIS 引用 | OK | 138 字符 |
| `tpdc_06_disaster_points` | 数据文件下载 | OK | 1 个文件，0.1 MB ZIP |
| `tpdc_06_disaster_points` | 下载与本地附件差异 | OK | 嵌套 ZIP，展开后与本地附件一致 |
| `tpdc_07_dem` | 治理配置 | OK | 字段齐全 |
| `tpdc_07_dem` | 抓取 | OK | HTTP 200，2026-10-24T03:06:35+00:00 |
| `tpdc_07_dem` | 元数据文件 | OK |  |
| `tpdc_07_dem` | 标题 | OK | 2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据 |
| `tpdc_07_dem` | metadata_id | OK |  |
| `tpdc_07_dem` | landing_url | OK |  |
| `tpdc_07_dem` | citation_cn | OK | 高分辨率对地观测系统甘肃数据与应用中心. 2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据[DS]. 国家青藏高原科学数据中心, 2026. |
| `tpdc_07_dem` | 本地附件 | OK | 05_辅助文档/题目附件/附件/（7）2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据.zip |
| `tpdc_07_dem` | 空间范围 | OK | {'west': 84.45, 'east': 86.16, 'south': 28.26, 'north': 29.32} |
| `tpdc_07_dem` | 时间范围 | OK | 2026-08-26 |
| `tpdc_07_dem` | 描述长度 | OK | 222 字 |
| `tpdc_07_dem` | 关键词 | OK | 10 个 |
| `tpdc_07_dem` | RIS 引用 | OK | 162 字符 |
| `tpdc_07_dem` | 数据文件下载 | OK | 5 个文件，10.4 MB ZIP |
| `tpdc_07_dem` | 下载与本地附件差异 | OK | 与本地附件一致 |
| `tpdc_08_population` | 治理配置 | OK | 字段齐全 |
| `tpdc_08_population` | 抓取 | OK | HTTP 200，2026-10-24T03:06:44+00:00 |
| `tpdc_08_population` | 元数据文件 | OK |  |
| `tpdc_08_population` | 标题 | OK | 西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据 |
| `tpdc_08_population` | metadata_id | OK |  |
| `tpdc_08_population` | landing_url | OK |  |
| `tpdc_08_population` | citation_cn | OK | 国家统计局，吉隆县统计局. 西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据[DS]. 国家青藏高原科学数据中心, 2026. |
| `tpdc_08_population` | 本地附件 | OK | 05_辅助文档/题目附件/附件/（8）西藏日喀则市吉隆县泥石流灾害区吉隆县第七次人口普查数据.zip |
| `tpdc_08_population` | 空间范围 | OK | {'west': 84.45, 'east': 86.16, 'south': 28.26, 'north': 29.32} |
| `tpdc_08_population` | 时间范围 | WARN | 未给 |
| `tpdc_08_population` | 描述长度 | OK | 345 字 |
| `tpdc_08_population` | 关键词 | OK | 11 个 |
| `tpdc_08_population` | RIS 引用 | OK | 160 字符 |
| `tpdc_08_population` | 数据文件下载 | OK | 1 个文件，0.0 MB ZIP |
| `tpdc_08_population` | 下载与本地附件差异 | OK | 嵌套 ZIP，展开后与本地附件一致 |
| `mnr_debris_conditions` | 治理配置 | OK | 字段齐全 |
| `mnr_debris_conditions` | 抓取 | OK | HTTP 200，2026-10-24T02:42:41+00:00 |
| `mnr_debris_conditions` | 正文元数据 | OK |  |
| `mnr_debris_conditions` | 标题 | OK | 泥石流形成的基本条件 |
| `mnr_debris_conditions` | 正文长度 | OK | 900 字 |
| `mnr_debris_conditions` | 正文 hash | OK |  |
| `mnr_debris_conditions` | 获取方式 | OK | http |
| `baike_debris_flow` | 治理配置 | OK | 字段齐全 |
| `baike_debris_flow` | 抓取 | BLOCKED | robots.txt 禁止抓取 |
| `open_meteo_archive` | 治理配置 | OK | 字段齐全 |
| `open_meteo_archive` | 抓取 | OK | HTTP 200，2026-10-24T02:38:37+00:00 |
| `open_meteo_archive` | API 元数据 | OK |  |
| `open_meteo_archive` | 数据行数 | OK | 216 行 |
| `open_meteo_archive` | 时间起止 | OK | 2026-08-20T00:00 → 2026-08-28T23:00 |
| `open_meteo_archive` | 变量数 | OK | 13 个 |
| `open_meteo_forecast` | 治理配置 | OK | 字段齐全 |
| `open_meteo_forecast` | 抓取 | OK | HTTP 200，2026-10-24T02:38:38+00:00 |
| `open_meteo_forecast` | API 元数据 | OK |  |
| `open_meteo_forecast` | 数据行数 | OK | 72 行 |
| `open_meteo_forecast` | 时间起止 | OK | 2026-10-24T00:00 → 2026-10-26T23:00 |
| `open_meteo_forecast` | 变量数 | OK | 8 个 |
| `nasa_power` | 治理配置 | OK | 字段齐全 |
| `nasa_power` | 抓取 | OK | HTTP 200，2026-10-24T02:38:40+00:00 |
| `nasa_power` | API 元数据 | OK |  |
| `nasa_power` | 数据行数 | OK | 216 行 |
| `nasa_power` | 时间起止 | OK | 2026-08-20T00:00:00 → 2026-08-28T23:00:00 |
| `nasa_power` | 变量数 | OK | 6 个 |
| `copernicus_s2` | 治理配置 | OK | 字段齐全 |
| `copernicus_s2` | 抓取 | OK | HTTP 200，2026-10-24T02:50:54+00:00 |
| `copernicus_s2` | API 元数据 | OK |  |
| `copernicus_s2` | 数据行数 | OK | 10 行 |
| `copernicus_s2` | 时间起止 | OK | 2026-08-22T04:56:51.024000Z → 2026-08-29T04:47:01.025000Z |
| `copernicus_s2` | 研究区相交 | OK | 10 个产品与 study_area 相交 |
| `copernicus_s2` | 产品类型 | OK | {'MSIL1C': 5, 'MSIL2A': 5} |
| `copernicus_s1` | 治理配置 | OK | 字段齐全 |
| `copernicus_s1` | 抓取 | OK | HTTP 200，2026-10-24T02:50:56+00:00 |
| `copernicus_s1` | API 元数据 | OK |  |
| `copernicus_s1` | 数据行数 | OK | 10 行 |
| `copernicus_s1` | 时间起止 | OK | 2026-08-24T00:18:40.857155Z → 2026-08-28T12:22:10.463264Z |
| `copernicus_s1` | 研究区相交 | OK | 10 个产品与 study_area 相交 |
| `copernicus_s1` | 产品类型 | OK | {'RAW': 2, 'SLC': 2, 'GRDH': 4} |

## 如何解读

- TPDC 八数据集：元数据、引用、本地附件三项齐全才算高质量；时间范围缺失但标题有范围的记为 WARN。
- 背景文章：正文 ≥300 字为 OK；百度百科被 robots/403 阻断，记为 BLOCKED，不视为工具失败。
- 补充 API：行数 >0、时间起止齐全为 OK；Copernicus 额外检查产品是否与研究区相交。
- 任何 FAIL 都应先修工具或配置，再让论文手引用。
