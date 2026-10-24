# 数据卡：Copernicus Data Space：Sentinel-1 产品元数据

> 数据治理层生成；来源配置 `config/governance.json`；来源 ID `copernicus_s1`。

## 1. 基本信息

| 项 | 内容 |
|---|---|
| 类型 | api_json |
| URL | https://catalogue.dataspace.copernicus.eu/odata/v1/Products |
| DOI | — |
| 访问日期 | 2026-10-24 |
| 抓取状态 | HTTP 200 |
| 覆盖/规模 | 10 行；2026-08-24T00:18:40.857155Z → 2026-08-28T12:22:10.463264Z；核心区相交 10/10 |
| 对应问题 | Q2、Q4 |

## 2. 角色与尺度

- **角色**：Q2/Q4 SAR 灾后范围/全天候核查
- **时间**：2026-08-24 至 2026-08-28 产品元数据；GRDH/SLC/RAW
- **空间**：Sentinel-1 GRD 约 10 m；核心区 85.15–85.55°E, 28.15–28.55°N
- **坐标系**：EPSG:4326（元数据 bbox）
- **许可**：Copernicus Data Space 公开元数据；产品下载需账号/OAuth

## 3. 能支持 / 不能支持

**能支持：**
- 全天候 SAR 元数据检索
- Q2/Q4 灾后范围与流路核查候选
- 与光学影像互补

**不能支持：**
- 产品下载（需账号）
- 直接给出触发时刻
- 单视 SAR 的精细沟道解译

## 4. 质量标记

- 只取元数据，未下载产品
- 10 个产品全部与研究区相交；含 GRDH/SLC/RAW 混合
- SAR 几何/斑点噪声影响

## 5. 不确定性传导

Q2/Q4 用 SAR 做范围核查，不把它当触发时间证据。

## 6. 风险

- **时间泄漏风险**：高：事件后 SAR 不能用于灾前特征。
- **虚假精度风险**：中：10 m 但几何畸变/斑点噪声。

## 7. 复现

```powershell
python -m mtmcm_data fetch copernicus_s1
python -m mtmcm_data validate
```
