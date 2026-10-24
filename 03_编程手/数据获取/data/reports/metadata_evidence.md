# 元数据证据核查：DEM 时点与土地覆盖图例

> 目的：回答“DEM 获取时点”和“土地覆盖 1–10 图例”能否从 TPDC 元数据补齐。  
> 结论：**不能补齐**；只能确认“没有给出”，并把风险写死。以下字段均来自 TPDC 元数据 JSON（`data/raw/tpdc_05_landcover`、`data/raw/tpdc_07_dem`），访问日期 2026-10-24。

## 1. TPDC-07 DEM

| 字段 | 值 | 说明 |
|---|---|---|
| `title` | 2026年8月26日日喀则市吉隆县泥石流灾害区DEM数据 | 标题含事件日，但不是获取时间 |
| `startTime` | `None` | 元数据没有时间范围 |
| `endTime` | `None` | 同上 |
| `tsCreated` | **2026-08-26 17:57:08** | 平台创建/发布时间，不是 DEM 获取时间 |
| `tsUpdated` | 2026-08-26 19:39:27 | 平台更新时间 |
| `description` | 30 m DEM，用于灾害链地形演化/易发性/救援通道 | 没有传感器、航摄/测量日期 |
| `instructions` | “该数据集以tif格式给出。” | 没有时点 |

**判读：**

- 平台创建时间 **2026-08-26 17:57**，晚于事件 10:30；这**不能证明** DEM 是灾前或灾后，但足以否定“默认灾前 DEM”的写法；
- `tsCreated` 只是元数据发布时间，不能当 `acquisition_time`；
- 论文中必须写“获取时点未知”，并做“灾前/灾后 DEM”情景敏感性；不能把该 DEM 直接当灾前地形。

## 2. TPDC-05 土地覆盖

| 字段 | 值 | 说明 |
|---|---|---|
| `title` | 西藏日喀则市吉隆县泥石流灾害区土地覆盖数据（2020-2023） | 年份范围 |
| `description` | 利用李思雅等 Annual 30 m land cover dataset on the Tibetan Plateau from 1990 to 2023 裁剪 | 只给源数据集，没有类别码本 |
| `instructions` | `jilong_LUCD_yyyy`，yyyy 为年份 | 只说明文件命名 |
| `startTime` / `endTime` | `None` / `None` | 没有逐期时间 |
| `projection` / `crs` | 空 / `None` | 栅格标签里是 EPSG:4326 |
| 类别码本 | **无** | 1–10 没有官方图例 |

**判读：**

- 附件只给“1–10 编码”，没有图例；**不能自行命名**草地/裸地/冰川等；
- 可以引用源数据集（Li et al., Annual 30 m land cover dataset）作为“编码来源”，但在拿到该产品图例前，正文只能写“编码 1–10”；
- 2023 期与 2026 事件存在 3 年时间差，不能当事件时相。

## 3. 对治理状态的影响

| 待办 | 状态 | 处理 |
|---|---|---|
| DEM 获取时点 | ❌ 元数据未给 | 写“未知”；做灾前/灾后情景；不默认灾前 |
| 土地覆盖图例 | ❌ 元数据未给 | 保留编码；不命名类别；需源产品图例后才能重分类 |
| DEM 平台发布时间 | ✅ 已核 | 2026-08-26 17:57（≠获取时间） |
| 土地覆盖源数据集 | ✅ 已核 | Li et al. Annual 30 m land cover dataset, 1990–2023 |

## 4. 引用位置

- 已有附件审计：[existing_data_audit.md](existing_data_audit.md)
- 治理状态：[data_governance_status.md](data_governance_status.md)
- 数据卡：[tpdc_05_landcover.md](../data_cards/tpdc_05_landcover.md)、[tpdc_07_dem.md](../data_cards/tpdc_07_dem.md)
