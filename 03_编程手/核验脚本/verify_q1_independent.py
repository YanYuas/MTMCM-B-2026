# -*- coding: utf-8 -*-
"""
Q1 独立复算（建模手核验脚本）
- 不 import / 不调用 03_编程手/Q1/源代码/q1_pipeline.py
- 特征构造：从原始 24 CSV 抽样复算 F21/F22/F26/F09/F32 阈值
- 排序：从 q1_features_hourly.csv.gz 独立复算 med/MAD/z/A/A_std/p/q/Top5
- A5：1000 次伪事件 FPR
- A6：原始 z+3 与校正 z=+3 各 100 次
- E72：独立复算 Top5 敏感性

输出：03_编程手/核验往来/q1_recompute/
"""

import json
import os
import zipfile
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = r"C:\Users\21722\Desktop\妈妈杯秋季赛\MTMCM比赛协作"
MATRIX = os.path.join(ROOT, r"03_编程手\Q1\实验结果\q1_features_hourly.csv.gz")
RANKING = os.path.join(ROOT, r"03_编程手\Q1\实验结果\q1_ranking.csv")
RAW_ZIP = os.path.join(
    ROOT,
    r"05_辅助文档\题目附件\附件\（1）西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026）.zip",
)
OUT = os.path.join(ROOT, r"03_编程手\核验往来\q1_recompute")
os.makedirs(OUT, exist_ok=True)

T0 = pd.Timestamp("2026-08-26 10:30:00")
E_PRE_START = pd.Timestamp("2026-08-25 10:00:00")
E_PRE_END = pd.Timestamp("2026-08-26 10:00:00")
E_ALL_END = pd.Timestamp("2026-08-26 16:00:00")
E72_START = pd.Timestamp("2026-08-23 10:00:00")

BINARY = {"p1h_p99", "p24_p95", "ta_p95", "ws_p95"}
RNG = np.random.default_rng(20261024)


def bh_fdr(p):
    p = np.asarray(p, dtype=float)
    n = len(p)
    order = np.argsort(p)
    q = np.empty(n, dtype=float)
    prev = 1.0
    for rank in range(n - 1, -1, -1):
        idx = order[rank]
        val = min(prev, p[idx] * n / (rank + 1))
        q[idx] = val
        prev = val
    return q


def inv_norm(u):
    nd = NormalDist()
    return np.array([nd.inv_cdf(float(x)) for x in np.clip(u, 1e-6, 1 - 1e-6)])


def robust_z(x, med, scale):
    """只做 (x-med)/scale；缺测保持 NaN，不因 NaN 触发分位回退。"""
    return np.clip((x - med) / scale, -10, 10)


def build_masks(ts):
    sy = ((ts.dt.month == 8) & (ts.dt.day >= 11)) | ((ts.dt.month == 9) & (ts.dt.day <= 10))
    sy = sy & ~((ts.dt.year == 2026) & (ts > E_PRE_END))
    e_pre = (ts >= E_PRE_START) & (ts <= E_PRE_END)
    e_all = (ts >= E_PRE_START) & (ts <= E_ALL_END)
    b = sy & ~e_all
    e72 = (ts >= E72_START) & (ts <= E_PRE_END)
    return sy, e_pre, e_all, b, e72


def load_raw_spot():
    """读取原始 CSV 的 Ta/RH/TSTAR/Rld/Rlu，用于特征构造抽样核对。"""
    rows = []
    with zipfile.ZipFile(RAW_ZIP) as z:
        for year in range(2021, 2027):
            met = pd.read_csv(
                z.open(f"MET_Gyirong_{year}.csv"),
                usecols=["Timestamp", "Ta_2m(degree C)", "QC_Ta_2m", "RH_2m(%)", "QC_RH_2m"],
            )
            met["ts"] = pd.to_datetime(met["Timestamp"], format="mixed")
            met = met.rename(columns={"Ta_2m(degree C)": "Ta", "RH_2m(%)": "RH"})
            met["Ta"] = pd.to_numeric(met["Ta"], errors="coerce").replace(9999.9, np.nan)
            met["RH"] = pd.to_numeric(met["RH"], errors="coerce").replace(9999.9, np.nan)

            flux = pd.read_csv(z.open(f"FLUX_Gyirong_{year}.csv"), usecols=["Timestamp", "TSTAR(deg C)"])
            flux["ts"] = pd.to_datetime(flux["Timestamp"], format="mixed")
            flux = flux.rename(columns={"TSTAR(deg C)": "TSTAR"})
            flux["TSTAR"] = pd.to_numeric(flux["TSTAR"], errors="coerce").replace(9999.9, np.nan)

            radm = pd.read_csv(
                z.open(f"RADM_Gyirong_{year}.csv"),
                usecols=["Timestamp", "Rld(W/m2)", "QC_rld", "Rlu(W/m2)", "QC_rlu"],
            )
            radm["ts"] = pd.to_datetime(radm["Timestamp"], format="mixed")
            radm = radm.rename(columns={"Rld(W/m2)": "Rld", "Rlu(W/m2)": "Rlu"})
            radm["Rld"] = pd.to_numeric(radm["Rld"], errors="coerce").replace(9999.9, np.nan)
            radm["Rlu"] = pd.to_numeric(radm["Rlu"], errors="coerce").replace(9999.9, np.nan)

            m = met[["ts", "Ta", "RH"]].merge(flux[["ts", "TSTAR"]], on="ts", how="outer")
            m = m.merge(radm[["ts", "Rld", "Rlu"]], on="ts", how="outer")
            rows.append(m)
    raw = pd.concat(rows, ignore_index=True).sort_values("ts").reset_index(drop=True)
    return raw


def main():
    df = pd.read_csv(MATRIX)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    ts = df["timestamp"]
    features = [c for c in df.columns if c != "timestamp"]
    sy, e_pre, e_all, b, e72 = build_masks(ts)
    print("rows", len(df), "features", len(features))
    print("E_pre", int(e_pre.sum()), "B", int(b.sum()), "E72", int(e72.sum()))

    # ---------- 1) 原始特征抽样核对 ----------
    raw = load_raw_spot()
    raw = raw.set_index("ts")
    spot = {}
    # F21 vpd
    es = 0.6108 * np.exp(17.27 * raw["Ta"] / (raw["Ta"] + 237.3))
    raw_vpd = es * (1 - raw["RH"] / 100)
    # F09 net_lw
    raw_net_lw = raw["Rld"] - raw["Rlu"]
    # F22 tstar
    raw_tstar = raw["TSTAR"]
    # F26 pos_temp_24h
    raw_pos24 = raw["Ta"].clip(lower=0).rolling(24, min_periods=24).sum()
    # F32 threshold from B
    raw_b = raw.loc[raw.index.isin(ts[b])]
    raw_ta_q95 = raw_b["Ta"].quantile(0.95)

    for name, series in [("vpd", raw_vpd), ("net_lw", raw_net_lw), ("tstar", raw_tstar), ("pos_temp_24h", raw_pos24)]:
        common = df.set_index("timestamp")[name].index.intersection(series.index)
        a = df.set_index("timestamp").loc[common, name].to_numpy(float)
        c = series.loc[common].to_numpy(float)
        ok = np.isfinite(a) & np.isfinite(c)
        if ok.sum():
            diff = np.abs(a[ok] - c[ok])
            spot[name] = {
                "n_common": int(ok.sum()),
                "max_abs_diff": float(np.nanmax(diff)),
                "median_abs_diff": float(np.nanmedian(diff)),
                "match_1e-6": float(np.mean(diff < 1e-6)),
            }
        else:
            spot[name] = {"n_common": 0}
    spot["ta_q95_B"] = {"raw": float(raw_ta_q95), "matrix_summary": 18.31}

    # ---------- 2) 独立排序复算 ----------
    B = df.loc[b, features]
    E = df.loc[e_pre, features]
    med = B.median(numeric_only=True)
    mad = (B - med).abs().median(numeric_only=True)
    scale = 1.4826 * mad
    # 有效比例
    valid = pd.DataFrame(
        {
            "valid_E": E.notna().mean(),
            "valid_B": B.notna().mean(),
        }
    )

    A = {}
    D = {}
    Z = {}
    for name in features:
        if name in BINARY:
            # 二值：率差
            eb = E[name].dropna()
            bb = B[name].dropna()
            A[name] = float(eb.mean() - bb.mean()) if len(eb) and len(bb) else np.nan
            D[name] = np.sign(A[name]) if np.isfinite(A[name]) else np.nan
            Z[name] = df[name].astype(float)
        else:
            med_j = float(med[name])
            scale_j = float(scale[name])
            if not np.isfinite(scale_j) or scale_j <= 0:
                scale_j = float((B[name].quantile(0.75) - B[name].quantile(0.25)) / 1.349)
            if not np.isfinite(scale_j) or scale_j <= 0:
                # 分位映射
                x = df[name].to_numpy(float)
                finite = np.isfinite(x)
                ranks = pd.Series(x[finite]).rank(method="average").to_numpy()
                u = (ranks - 0.5) / finite.sum()
                z = np.full_like(x, np.nan, dtype=float)
                z[finite] = inv_norm(u)
                Z[name] = np.clip(z, -10, 10)
            else:
                Z[name] = robust_z(df[name].to_numpy(float), med_j, scale_j)
            z_e = Z[name][e_pre.to_numpy()]
            A[name] = float(np.nanmean(np.abs(z_e)))
            D[name] = float(np.nanmean(z_e))

    # 置换零分布：每年内随机 25h 连续窗口
    nulls = {name: [] for name in features}
    n_null = 1000
    for year in range(2021, 2027):
        pos = np.flatnonzero((ts.dt.year == year) & sy & ~e_all)
        if len(pos) <= 25:
            continue
        for _ in range(n_null // 6 + 1):
            start = int(RNG.integers(0, len(pos) - 25))
            idx = pos[start : start + 25]
            for name in features:
                if name in BINARY:
                    vals = df[name].to_numpy(float)[idx]
                    vals = vals[np.isfinite(vals)]
                    if len(vals) == 0:
                        continue
                    # 伪事件率 vs B 率
                    bb = B[name].dropna()
                    if len(bb) == 0:
                        continue
                    nulls[name].append(float(vals.mean() - bb.mean()))
                else:
                    vals = Z[name][idx]
                    vals = vals[np.isfinite(vals)]
                    if len(vals) < 10:
                        continue
                    nulls[name].append(float(np.mean(np.abs(vals))))

    rows = []
    for name in features:
        nl = np.asarray(nulls[name], dtype=float)
        nl = nl[np.isfinite(nl)]
        a = A[name]
        if len(nl) >= 100 and np.isfinite(a):
            mean_null = float(np.mean(nl))
            sd_null = float(np.std(nl, ddof=1))
            a_std = float((a - mean_null) / sd_null) if sd_null > 0 else 0.0
            p = float((1 + np.sum(nl >= a)) / (len(nl) + 1))
        else:
            mean_null = sd_null = a_std = p = np.nan
        rows.append(
            {
                "name": name,
                "A": a,
                "D": D[name],
                "valid_E": float(valid.loc[name, "valid_E"]),
                "valid_B": float(valid.loc[name, "valid_B"]),
                "null_mean": mean_null,
                "null_sd": sd_null,
                "A_std": a_std,
                "p": p,
            }
        )
    rec = pd.DataFrame(rows)
    rec["q"] = bh_fdr(rec["p"].to_numpy(float)) if rec["p"].notna().any() else np.nan
    rec["usable"] = (rec["valid_E"] >= 0.7) & (rec["valid_B"] >= 0.7) & rec["A_std"].notna()
    rec["rank"] = rec["A_std"].rank(ascending=False, method="min")
    rec = rec.sort_values("A_std", ascending=False).reset_index(drop=True)
    rec.to_csv(os.path.join(OUT, "q1_recompute_ranking.csv"), index=False, encoding="utf-8-sig")

    top5 = rec[rec["usable"]].head(5)[["name", "A", "A_std", "p", "q", "D"]].to_dict("records")
    n_q10 = int((rec["q"] <= 0.10).sum())

    # 对照编程手 ranking
    ref = pd.read_csv(RANKING)
    ref_top5 = ref[ref["selected"] == True]["name"].tolist() if "selected" in ref.columns else []
    ref_by_name = ref.set_index("name")
    comp = []
    for row in rec.itertuples():
        if row.name in ref_by_name.index:
            r = ref_by_name.loc[row.name]
            comp.append(
                {
                    "name": row.name,
                    "A_diff": float(row.A - r["A"]) if np.isfinite(r["A"]) else np.nan,
                    "A_std_diff": float(row.A_std - r["A_std"]) if np.isfinite(r["A_std"]) else np.nan,
                    "p_diff": float(row.p - r["p"]) if np.isfinite(r["p"]) else np.nan,
                }
            )

    # ---------- 3) A5 独立 FPR ----------
    fpr_count = 0
    n_pseudo = 1000
    for _ in range(n_pseudo):
        # 随机 25h 窗口（每年内）
        year = int(RNG.choice([2021, 2022, 2023, 2024, 2025, 2026]))
        pos = np.flatnonzero((ts.dt.year == year) & sy & ~e_all)
        if len(pos) <= 25:
            continue
        start = int(RNG.integers(0, len(pos) - 25))
        idx = pos[start : start + 25]
        ps = []
        for name in features:
            if name in BINARY:
                vals = df[name].to_numpy(float)[idx]
                vals = vals[np.isfinite(vals)]
                bb = B[name].dropna()
                if len(vals) == 0 or len(bb) == 0:
                    ps.append(np.nan)
                    continue
                a = float(vals.mean() - bb.mean())
            else:
                vals = Z[name][idx]
                vals = vals[np.isfinite(vals)]
                if len(vals) < 10:
                    ps.append(np.nan)
                    continue
                a = float(np.mean(np.abs(vals)))
            nl = np.asarray(nulls[name], dtype=float)
            nl = nl[np.isfinite(nl)]
            ps.append(float((1 + np.sum(nl >= a)) / (len(nl) + 1)) if len(nl) else np.nan)
        ps = np.asarray(ps, dtype=float)
        if np.isfinite(ps).any():
            qs = bh_fdr(ps)
            if np.nanmin(qs) <= 0.10:
                fpr_count += 1
    fpr = fpr_count / n_pseudo

    # ---------- 4) A6 原始 vs 校正 ----------
    usable_cont = [
        n for n in features
        if n not in BINARY and bool(valid.loc[n, "valid_E"] >= 0.7) and bool(valid.loc[n, "valid_B"] >= 0.7)
    ]
    # 相关聚类（连续特征，B 上 Pearson）
    corr = df.loc[b, usable_cont].corr(method="pearson").abs()
    clusters = {n: [m for m in usable_cont if corr.loc[n, m] >= 0.85] for n in usable_cont}

    def a6_run(corrected):
        hits = top3 = cluster_hits = 0
        ranks = []
        for _ in range(100):
            target = str(RNG.choice(usable_cont))
            z = Z[target].copy()
            if corrected:
                z[e_pre.to_numpy()] = 3.0
            else:
                z[e_pre.to_numpy()] = z[e_pre.to_numpy()] + 3.0
            a = float(np.nanmean(np.abs(z[e_pre.to_numpy()])))
            nl = np.asarray(nulls[target], dtype=float)
            nl = nl[np.isfinite(nl)]
            if len(nl) < 100:
                continue
            std = (a - float(np.mean(nl))) / float(np.std(nl, ddof=1)) if np.std(nl, ddof=1) > 0 else 0.0
            a_std = rec.set_index("name")["A_std"].copy()
            a_std.loc[target] = std
            r = a_std.rank(ascending=False, method="min")
            ri = r.loc[target]
            ranks.append(float(ri))
            if ri == 1:
                hits += 1
            if ri <= 3:
                top3 += 1
            if any(r.loc[m] == 1 for m in clusters[target]):
                cluster_hits += 1
        return {
            "n": len(ranks),
            "top1": hits / len(ranks) if ranks else None,
            "top3": top3 / len(ranks) if ranks else None,
            "cluster_top1": cluster_hits / len(ranks) if ranks else None,
            "median_rank": float(np.median(ranks)) if ranks else None,
        }

    a6_orig = a6_run(False)
    a6_corr = a6_run(True)

    # ---------- 5) E72 Top5 复算 ----------
    e72_null = {name: [] for name in features}
    for year in range(2021, 2027):
        pos = np.flatnonzero((ts.dt.year == year) & sy & ~e_all)
        if len(pos) <= 73:
            continue
        for _ in range(200):
            start = int(RNG.integers(0, len(pos) - 73))
            idx = pos[start : start + 73]
            for name in features:
                if name in BINARY:
                    vals = df[name].to_numpy(float)[idx]
                    vals = vals[np.isfinite(vals)]
                    bb = B[name].dropna()
                    if len(vals) and len(bb):
                        e72_null[name].append(float(vals.mean() - bb.mean()))
                else:
                    vals = Z[name][idx]
                    vals = vals[np.isfinite(vals)]
                    if len(vals) >= 30:
                        e72_null[name].append(float(np.mean(np.abs(vals))))
    e72_rows = []
    for name in features:
        if name in BINARY:
            vals = df.loc[e72, name].dropna()
            bb = B[name].dropna()
            a = float(vals.mean() - bb.mean()) if len(vals) and len(bb) else np.nan
        else:
            vals = Z[name][e72.to_numpy()]
            vals = vals[np.isfinite(vals)]
            a = float(np.mean(np.abs(vals))) if len(vals) >= 10 else np.nan
        nl = np.asarray(e72_null[name], dtype=float)
        nl = nl[np.isfinite(nl)]
        if len(nl) >= 50 and np.isfinite(a):
            sd = float(np.std(nl, ddof=1))
            astd = (a - float(np.mean(nl))) / sd if sd > 0 else 0.0
            p = float((1 + np.sum(nl >= a)) / (len(nl) + 1))
        else:
            astd = p = np.nan
        e72_rows.append({"name": name, "A": a, "A_std": astd, "p": p})
    e72df = pd.DataFrame(e72_rows)
    e72df["q"] = bh_fdr(e72df["p"].to_numpy(float))
    e72df = e72df.sort_values("A_std", ascending=False)
    e72_top5 = e72df.head(5)["name"].tolist()

    summary = {
        "rows": int(len(df)),
        "features": len(features),
        "E_pre_n": int(e_pre.sum()),
        "B_n": int(b.sum()),
        "E72_n": int(e72.sum()),
        "spotcheck": spot,
        "top5_recomputed": top5,
        "top5_reference": ref_top5,
        "n_q10_recomputed": n_q10,
        "n_q10_reference": int((ref["q"] <= 0.10).sum()) if "q" in ref.columns else None,
        "A5_fpr_recomputed": float(fpr),
        "A5_fpr_reference": 0.068,
        "A6_original_recomputed": a6_orig,
        "A6_corrected_recomputed": a6_corr,
        "E72_top5_recomputed": e72_top5,
        "E72_top5_reference": ["ta_p95", "vpd", "cloudiness", "LE", "pos_temp_24h"],
        "comparison": comp,
    }
    with open(os.path.join(OUT, "q1_recompute_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=float)

    # 简化 markdown
    lines = []
    lines.append("# Q1 独立复算报告（建模手）\n")
    lines.append("> 脚本：`03_编程手/核验脚本/verify_q1_independent.py`；不 import/调用 `q1_pipeline.py`。\n")
    lines.append("## 1. 规模与掩码\n")
    lines.append(f"- 行数：{len(df)}；特征：{len(features)}；E_pre={int(e_pre.sum())}；B={int(b.sum())}；E72={int(e72.sum())}\n")
    lines.append("## 2. 原始特征抽样核对\n")
    lines.append("```json\n" + json.dumps(spot, ensure_ascii=False, indent=2, default=float) + "\n```\n")
    lines.append("## 3. 排序复算\n")
    lines.append(f"- 复算 Top5：{', '.join([x['name'] for x in top5])}\n")
    lines.append(f"- 参考 Top5：{', '.join(ref_top5)}\n")
    lines.append(f"- 复算 q≤0.10：{n_q10}；参考：{summary['n_q10_reference']}\n")
    lines.append("## 4. A5/A6\n")
    lines.append(f"- A5 FPR 复算：{fpr:.3f}；参考：0.068\n")
    lines.append(f"- A6 原始（z+3）：{a6_orig}\n")
    lines.append(f"- A6 校正（z=+3）：{a6_corr}\n")
    lines.append("## 5. E72 Top5\n")
    lines.append(f"- 复算：{', '.join(e72_top5)}\n")
    lines.append(f"- 参考：{', '.join(summary['E72_top5_reference'])}\n")
    lines.append("## 6. 对照差异（A/A_std/p）\n")
    lines.append("```json\n" + json.dumps(comp, ensure_ascii=False, indent=2, default=float) + "\n```\n")
    with open(os.path.join(OUT, "q1_recompute_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=float))


if __name__ == "__main__":
    main()
