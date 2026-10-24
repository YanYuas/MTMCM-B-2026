# Q1 独立复算报告（建模手）

> 脚本：`03_编程手/核验脚本/verify_q1_independent.py`；不 import/调用 `q1_pipeline.py`。

## 1. 规模与掩码

- 行数：49545；特征：33；E_pre=25；B=4066；E72=73

## 2. 原始特征抽样核对

```json
{
  "vpd": {
    "n_common": 46768,
    "max_abs_diff": 4.440892098500626e-16,
    "median_abs_diff": 0.0,
    "match_1e-6": 1.0
  },
  "net_lw": {
    "n_common": 45595,
    "max_abs_diff": 5.684341886080802e-14,
    "median_abs_diff": 0.0,
    "match_1e-6": 1.0
  },
  "tstar": {
    "n_common": 36051,
    "max_abs_diff": 0.0,
    "median_abs_diff": 0.0,
    "match_1e-6": 1.0
  },
  "pos_temp_24h": {
    "n_common": 46693,
    "max_abs_diff": 5.684341886080802e-14,
    "median_abs_diff": 0.0,
    "match_1e-6": 1.0
  },
  "ta_q95_B": {
    "raw": 18.31,
    "matrix_summary": 18.31
  }
}
```

## 3. 排序复算

- 复算 Top5：ta_p95, vpd, tstar, pos_temp_24h, net_lw

- 参考 Top5：net_lw, vpd, tstar, pos_temp_24h, ta_p95

- 复算 q≤0.10：0；参考：0

## 4. A5/A6

- A5 FPR 复算：0.072；参考：0.068

- A6 原始（z+3）：{'n': 100, 'top1': 0.77, 'top3': 0.77, 'cluster_top1': 0.77, 'median_rank': 1.0}

- A6 校正（z=+3）：{'n': 100, 'top1': 0.66, 'top3': 0.8, 'cluster_top1': 0.66, 'median_rank': 1.0}

## 5. E72 Top5

- 复算：ta_p95, vpd, cloudiness, rn, net_sw

- 参考：ta_p95, vpd, cloudiness, LE, pos_temp_24h

## 6. 对照差异（A/A_std/p）

```json
[
  {
    "name": "ta_p95",
    "A_diff": 0.0,
    "A_std_diff": -0.28588481327837867,
    "p_diff": 0.01787644060824526
  },
  {
    "name": "vpd",
    "A_diff": -6.661338147750939e-16,
    "A_std_diff": 0.12639982588225673,
    "p_diff": -0.012107533543226433
  },
  {
    "name": "tstar",
    "A_diff": 4.440892098500626e-16,
    "A_std_diff": 0.030595167080450292,
    "p_diff": 0.005186842143363957
  },
  {
    "name": "pos_temp_24h",
    "A_diff": 0.0,
    "A_std_diff": 0.06898013190700025,
    "p_diff": -0.012229047124361125
  },
  {
    "name": "net_lw",
    "A_diff": 0.0,
    "A_std_diff": -0.023842209917161794,
    "p_diff": 0.012658328710173222
  },
  {
    "name": "cloudiness",
    "A_diff": 9.992007221626409e-16,
    "A_std_diff": 0.2079553185748534,
    "p_diff": -0.05725381298661458
  },
  {
    "name": "pos_temp_72h",
    "A_diff": -1.5543122344752192e-15,
    "A_std_diff": -0.19233394800142078,
    "p_diff": 0.03856462580291098
  },
  {
    "name": "net_sw",
    "A_diff": 1.1102230246251565e-16,
    "A_std_diff": NaN,
    "p_diff": NaN
  },
  {
    "name": "tke",
    "A_diff": 0.0,
    "A_std_diff": 0.11977595117626821,
    "p_diff": -0.04458705545662067
  },
  {
    "name": "vwc_40",
    "A_diff": 0.0,
    "A_std_diff": 0.08158603163443379,
    "p_diff": -0.012631436360249881
  },
  {
    "name": "rn",
    "A_diff": 0.0,
    "A_std_diff": NaN,
    "p_diff": NaN
  },
  {
    "name": "pressure_tendency_3h",
    "A_diff": 0.0,
    "A_std_diff": 0.0904792131339802,
    "p_diff": -0.032824603113735695
  },
  {
    "name": "vwc_storage_0_40",
    "A_diff": -1.1102230246251565e-15,
    "A_std_diff": 0.025089479992504715,
    "p_diff": 0.0414164515687358
  },
  {
    "name": "ri_bulk_2_20",
    "A_diff": -1.3322676295501878e-15,
    "A_std_diff": 0.23551287374071064,
    "p_diff": -0.10572179565200496
  },
  {
    "name": "ustar",
    "A_diff": 0.0,
    "A_std_diff": 0.13669996594340622,
    "p_diff": -0.07749617532226233
  },
  {
    "name": "H",
    "A_diff": -4.440892098500626e-16,
    "A_std_diff": 0.024928612453413844,
    "p_diff": -0.05620466490031706
  },
  {
    "name": "g_0.1",
    "A_diff": 0.0,
    "A_std_diff": 0.580396692507269,
    "p_diff": -0.25564565046120374
  },
  {
    "name": "LE",
    "A_diff": 0.0,
    "A_std_diff": -0.3894406692667159,
    "p_diff": 0.10145892754588415
  },
  {
    "name": "ws_shear_2_10",
    "A_diff": -1.4432899320127035e-15,
    "A_std_diff": 0.15615040478765108,
    "p_diff": -0.08791706797688847
  },
  {
    "name": "theta_v_diff_2_20",
    "A_diff": -2.220446049250313e-16,
    "A_std_diff": 0.22363255637106777,
    "p_diff": -0.08404855363977992
  },
  {
    "name": "p24_p95",
    "A_diff": -6.938893903907228e-18,
    "A_std_diff": -0.046462042786208885,
    "p_diff": 0.0
  },
  {
    "name": "p1h_p99",
    "A_diff": -4.683753385137379e-17,
    "A_std_diff": -0.03119553986232565,
    "p_diff": 0.0
  },
  {
    "name": "ws_shear_2_20",
    "A_diff": 3.3306690738754696e-16,
    "A_std_diff": 0.1413310576119553,
    "p_diff": -0.0661621529019335
  },
  {
    "name": "precip_72h",
    "A_diff": 0.0,
    "A_std_diff": -0.3424470463213423,
    "p_diff": 0.003903374790712788
  },
  {
    "name": "precip_1h",
    "A_diff": -1.4142097932971769,
    "A_std_diff": -0.1331009469274419,
    "p_diff": 0.0
  },
  {
    "name": "precip_24h",
    "A_diff": 0.0,
    "A_std_diff": 0.040201406222909464,
    "p_diff": 0.0
  },
  {
    "name": "bowen",
    "A_diff": 0.0,
    "A_std_diff": NaN,
    "p_diff": NaN
  },
  {
    "name": "api_72h",
    "A_diff": 0.0,
    "A_std_diff": -0.09569016072346637,
    "p_diff": -0.013380438106260661
  },
  {
    "name": "ws_p95",
    "A_diff": -9.020562075079397e-17,
    "A_std_diff": 0.17366114516234055,
    "p_diff": 0.0
  },
  {
    "name": "albedo",
    "A_diff": 5.551115123125783e-16,
    "A_std_diff": NaN,
    "p_diff": NaN
  },
  {
    "name": "soilT_0.4",
    "A_diff": 5.551115123125783e-17,
    "A_std_diff": 0.07719250840806702,
    "p_diff": 0.006474084240784106
  },
  {
    "name": "soilT_grad_0.1_0.4",
    "A_diff": 0.0,
    "A_std_diff": 0.7378639950083693,
    "p_diff": -0.16239891713470989
  },
  {
    "name": "wd_shear_2_20",
    "A_diff": -9.992007221626409e-16,
    "A_std_diff": -0.17076102348020306,
    "p_diff": -0.002889433597309865
  }
]
```
