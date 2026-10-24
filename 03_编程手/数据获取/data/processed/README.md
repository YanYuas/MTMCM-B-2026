# data/processed 基线

> 由 `python -m mtmcm_data process --batch 1/2/all` 生成；原始附件只读。

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

## 关键约束

- TPDC-01 的 `9999.9`/`QC=8` 已标缺失，未补零；
- TPDC-02 的 2025 只有 214 天，年度趋势需排除或标注；
- TPDC-06 的 `解译Time`/`影像Time` 不是事件发生时间；84 个沟域不是 84 次事件；
- TPDC-05 的 0 是 nodata，不是类别；1–10 无官方图例；
- TPDC-07 的 D8 未填洼，sink 单元会终止汇流；坡度按中心纬度近似米制间距；
- 原始附件只读；派生层可由脚本重建。

## 复现

```powershell
python -m mtmcm_data process --batch 1
python -m mtmcm_data process --batch 2
```
