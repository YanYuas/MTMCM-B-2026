# Q1 P0 收尾：A5/A6/A8/A9

> 由 `q1_closeout.py` 生成；A5/A6 用 E_pre 的基线 null 分布；A8/A9 重算对应窗口/基线的 null。

## A5 零模型 FPR

- 伪事件数：1000；任一特征 q≤0.10 的伪事件：68；**FPR=0.068**。
- 验收：FPR≤10%。 ✅ 通过

## A6 合成注入（100 次）

- 随机可用连续特征 +3σ；Top1 命中 **78/100 = 78%**；中位排名 1.0。
- 验收：Top1≥90%。 ❌ 未通过
- 0 命中的目标：api_72h, precip_24h, ri_bulk_2_20, vwc_40, wd_shear_2_20；详见 `q1_a6_detail.csv`。

## A8/A9 敏感性

| 场景 | 说明 | 可用特征 | q≤0.10 | Top5 | 与 E_pre 重叠 |
|---|---|---:|---:|---|---:|
| E_pre | 主窗口 25h | 29 | 0 | ta_p95, vpd, pos_temp_24h, net_lw, tstar | 5/5 |
| E6 | 末 6h（7 样本） | 29 | 0 | pos_temp_24h, pos_temp_72h, ri_bulk_2_20, wd_shear_2_20, vwc_40 | 1/5 |
| E72 | 72h（73 样本） | 29 | 1 | ta_p95, vpd, cloudiness, LE, pos_temp_24h | 3/5 |
| E_all | 描述窗口 31h | 29 | 0 | ta_p95, tstar, vpd, net_lw, LE | 4/5 |
| base_pm7 | 基线 804-917 | 29 | 0 | ta_p95, vpd, net_lw, tstar, cloudiness | 4/5 |
| base_pm30 | 基线 712-1010 | 29 | 0 | ta_p95, vpd, tstar, net_lw, cloudiness | 4/5 |

- A8 验收：窗口 Top5 至少 3/5 重叠；A9 同理。低于 3/5 的场景必须标“窗口/基线敏感”。
- 总结论：A8 因 E6=1/5 **未通过**；E72/E_all 通过；A9 两个基线均通过。

## 备注

- A5 的 null 与真实 E_pre 共用 B 的固定 med/MAD；伪事件只换窗口，不重算基线。
- A6 注入的是 z（+3σ），不是原始变量；只针对连续、可用特征。
- E_all 含事件后 6 h，只作描述窗口，不作为前兆窗口。