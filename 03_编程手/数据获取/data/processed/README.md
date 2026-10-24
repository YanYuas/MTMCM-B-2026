# data/processed 基线

> 由 `python -m mtmcm_data process --batch 1-6/all` 生成；原始附件只读。

## 第一批（batch 1）

- `tpdc01_hourly/tpdc01_key_vars_long.csv.gz`：时间×变量长表，含 `qc_flag`/`missing_flag`/`qc_missing`/`qc_suspect`；
- `tpdc01_hourly/tpdc01_missing_by_variable.csv` + `tpdc01_variable_dictionary.csv`；
- `tpdc02_temp/tpdc02_temp_long.csv.gz`：日期×县长表；`tpdc02_temp_wide.csv.gz`：宽表；
- `tpdc06_points/tpdc06_points.geojson`：84 个沟域多边形 + 属性；`tpdc06_fields.csv`：字段字典。

## 第二批（batch 2）

- `tpdc05_landcover/jilong_LUCD_2023.tif`：2023 土地覆盖（LZW 重写，nodata=0）；
- `tpdc05_landcover/jilong_LUCD_2023_nodata_mask.tif`：1=nodata，0=有效；
- `tpdc05_landcover/tpdc05_class_counts_2023.csv`：类别计数（0=nodata）；
- `tpdc07_dem/dem_core_30m.tif`：核心沟谷 DEM；
- `tpdc07_dem/slope_deg.tif`：坡度（度）；
- `tpdc07_dem/flow_accumulation_cells.tif`：D8 汇流累积（cells）；
- `tpdc07_dem/flow_direction_d8.tif`：D8 流向（1–8，0=sink）；
- `tpdc07_dem/channel_mask_acc1000.tif`：沟道掩膜（accum≥1000 cells）；
- `tpdc07_dem/tpdc07_terrain_stats.csv`：地形统计。

## 第三批（batch 3）

- `tpdc07_channel/main_channel_profile.csv`：主流路纵剖面（距离/原始高程/路由高程/水力坡度/汇流）；
- `tpdc07_channel/main_channel.geojson`：主流路 LineString；
- `tpdc07_channel/main_channel_mask.tif`：主流路栅格；
- `tpdc07_channel/dem_filled_30m.tif`、`flow_direction_filled_d8.tif`、`flow_accumulation_filled.tif`：填洼+epsilon 后的 D8 层；
- `tpdc07_channel/main_channel_summary.json`：长度/落差/比降/源汇点/填洼前后 sink 数。

## 第四批（batch 4）

- `spatial_baseline/tpdc06_gully_overlay_stats.csv`：84 个沟域 × DEM/坡度/汇流/土地覆盖；
- `spatial_baseline/tpdc06_gully_id_mask.tif`：沟域 ID 栅格（1–84，0=outside）；
- `spatial_baseline/summary.json`：in_dem 数量、总像元、平均坡度等。

## 第五批（batch 5）

- `tpdc07_channel_sensitivity/main_channel_sensitivity_runs.csv`：3 个阈值 × 3 种填洼模式的 9 次主流路；
- `tpdc07_channel_sensitivity/main_channel_sensitivity.geojson`：各次主流路 LineString；
- `tpdc07_channel_sensitivity/summary.json`：长度/比降范围与推荐参数。

## 第六批（batch 6）

- `q2_susceptibility/q2_susceptibility_score.tif`：WOE 相对易发性分数；
- `q2_susceptibility/q2_susceptibility_class.tif`：1–5 分级（背景 20/40/60/80 分位）；
- `q2_susceptibility/q2_woe_bins.csv`：坡度/高程/汇流/土地覆盖的分箱 WOE；
- `q2_susceptibility/q2_gully_scores.csv`：84 个沟域的均分与背景百分位；
- `q2_susceptibility/summary.json`：全局/空间块 AUC、沟域百分位。

## 关键约束

- TPDC-01 的 `9999.9`/`QC=8` 已标缺失，未补零；
- TPDC-02 的 2025 只有 214 天，年度趋势需排除或标注；
- TPDC-06 的 `解译Time`/`影像Time` 不是事件发生时间；84 个沟域不是 84 次事件；
- TPDC-05 的 0 是 nodata，不是类别；1–10 无官方图例；
- batch 2 的 D8 未填洼；batch 3 主流路用填洼+epsilon D8，两者不能混用；
- batch 6 的 WOE 是相对易发性，不是概率；空间块 AUC 较弱，不能外推；
- 原始附件只读；派生层可由脚本重建。

## 复现

```powershell
python -m mtmcm_data process --batch all
```
