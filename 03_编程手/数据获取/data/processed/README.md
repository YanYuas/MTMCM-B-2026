# data/processed 第一批基线

> 由 `python -m mtmcm_data process --batch 1` 生成；原始附件只读。

## 内容

- `tpdc01_hourly/tpdc01_key_vars_long.csv.gz`：时间×变量长表，含 `qc_flag`/`missing_flag`/`qc_missing`/`qc_suspect`；
- `tpdc01_hourly/tpdc01_missing_by_variable.csv`：按变量缺测率汇总；
- `tpdc02_temp/tpdc02_temp_long.csv.gz`：日期×县长表；`tpdc02_temp_wide.csv.gz`：宽表；
- `tpdc06_points/tpdc06_points.geojson`：84 个沟域多边形 + 属性；
- `tpdc06_points/tpdc06_fields.csv`：字段字典；
- 每个数据集目录下有 `manifest.json`（源文件 sha256、规则、输出 sha256）。

## 关键约束

- TPDC-01 的 `9999.9`/`QC=8` 已标缺失，未补零；
- TPDC-02 的 2025 只有 214 天，年度趋势需排除或标注；
- TPDC-06 的 `解译Time`/`影像Time` 不是事件发生时间；84 个沟域不是 84 次事件；
- 第二批（TPDC-05 土地覆盖、TPDC-07 DEM 派生层）尚未生成。

## 复现

```powershell
python -m mtmcm_data process --batch 1
```
