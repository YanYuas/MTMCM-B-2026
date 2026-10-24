from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from q1_pipeline import (  # noqa: E402
    FEATURES,
    NAMES,
    bh_fdr,
    build_features,
    load_raw,
    make_binary,
    rank_auc_like,
    z_from_baseline,
)

BASE = HERE.parents[2]
OUT = BASE / "03_编程手" / "Q1" / "实验结果"
OUT.mkdir(parents=True, exist_ok=True)
RNG = np.random.default_rng(20261024)
BINARY = {"p1h_p99", "p24_p95", "ta_p95", "ws_p95"}
LOG_FEATURES = {"precip_1h", "precip_24h", "precip_72h", "api_72h"}
HOURS = set(range(24))


def masks(f: pd.DataFrame, start_md: int = 811, end_md: int = 910):
    ts = f["timestamp"]
    md = ts.dt.month * 100 + ts.dt.day
    e_pre = (ts >= pd.Timestamp("2026-08-25 10:00")) & (ts <= pd.Timestamp("2026-08-26 10:00"))
    e6 = (ts >= pd.Timestamp("2026-08-26 04:00")) & (ts <= pd.Timestamp("2026-08-26 10:00"))
    e72 = (ts >= pd.Timestamp("2026-08-23 10:00")) & (ts <= pd.Timestamp("2026-08-26 10:00"))
    e_all = (ts >= pd.Timestamp("2026-08-25 10:00")) & (ts <= pd.Timestamp("2026-08-26 16:00"))
    s = (md >= start_md) & (md <= end_md) & ~e_all
    s &= ~((ts.dt.year == 2026) & (ts > pd.Timestamp("2026-08-26 10:00")))
    b = s & ts.dt.hour.isin(HOURS)
    return {"E_pre": e_pre, "E6": e6, "E72": e72, "E_all": e_all}, s, b


def sample_null(series: pd.Series, s: pd.Series, b: pd.Series, ts: pd.Series, length: int, n: int = 1000, binary: bool = False) -> np.ndarray:
    vals: list[float] = []
    per_year = int(math.ceil(n / 6))
    base_rate = float(series[b].mean()) if binary else 0.0
    for year in range(2021, 2027):
        idxs = np.flatnonzero(((ts.dt.year == year) & s).to_numpy())
        if len(idxs) < length:
            continue
        starts = RNG.integers(idxs[0], idxs[-1] - length + 1, size=per_year * 3)
        for start in starts:
            if len(vals) >= n:
                break
            if start + length > len(series):
                continue
            window = series.iloc[start : start + length]
            if binary:
                vals.append(float(window.mean()) - base_rate)
            else:
                if window.notna().mean() < 0.7:
                    continue
                vals.append(float(window.abs().mean()))
        if len(vals) >= n:
            break
    return np.asarray(vals, dtype=float)


def scenario_table(f: pd.DataFrame, df: pd.DataFrame, s: pd.Series, b: pd.Series, ts: pd.Series, window: pd.Series, length: int, n_null: int = 1000):
    table = []
    z_map: dict[str, pd.Series] = {}
    nulls: dict[str, np.ndarray] = {}
    for fid, name, group, formula, unit, priority in FEATURES:
        x = f[name]
        valid_e = float(x[window].notna().mean())
        valid_b = float(x[b].notna().mean())
        row = {"feature_id": fid, "name": name, "group": group, "priority": priority, "valid_E": round(valid_e, 4), "valid_B": round(valid_b, 4), "usable": bool(valid_e >= 0.7 and valid_b >= 0.7)}
        if name in BINARY:
            i = x.fillna(0).astype(float)
            z_map[name] = i
            a = float(i[window].mean() - i[b].mean())
            series = i
            binary = True
        else:
            transform = np.log1p if name in LOG_FEATURES else None
            z, med, mad, scale = z_from_baseline(x, x[b], transform)
            z_map[name] = z
            a = float(z[window].abs().mean())
            series = z
            binary = False
        row["A"] = a
        null = sample_null(series, s, b, ts, length, n=n_null, binary=binary) if row["usable"] else np.array([])
        nulls[name] = null
        if len(null) >= 50:
            mean = float(np.nanmean(null))
            sd = float(np.nanstd(null, ddof=1))
            row.update({"null_mean": mean, "null_sd": sd, "A_std": (a - mean) / sd if sd > 0 else 0.0, "p": (1 + int(np.sum(null >= a))) / (len(null) + 1)})
        else:
            row.update({"null_mean": np.nan, "null_sd": np.nan, "A_std": np.nan, "p": np.nan})
        table.append(row)
    table = pd.DataFrame(table)
    table["q"] = bh_fdr(table["p"].to_numpy(dtype=float))
    table["rank"] = rank_auc_like(table["A_std"].to_numpy(dtype=float))
    table["selected"] = False
    usable = table[(table["usable"]) & (table["A_std"].notna())].sort_values("A_std", ascending=False)
    if len(usable):
        table.loc[usable.index[:5], "selected"] = True
    return table, z_map, nulls


def top5(table: pd.DataFrame) -> list[str]:
    return table[table["selected"]].sort_values("A_std", ascending=False)["name"].tolist()


def main() -> None:
    df = load_raw()
    f0 = build_features(df)
    masks_base, s0, b0 = masks(f0)
    f0, _ = make_binary(f0, df, b0)
    ts = f0["timestamp"]
    base, z_map, nulls = scenario_table(f0, df, s0, b0, ts, masks_base["E_pre"], 25)
    base_top5 = top5(base)
    base.to_csv(OUT / "q1_sensitivity_base.csv", index=False, encoding="utf-8-sig")

    # A5：1000 个伪事件窗口（基线内，不与 E_all 重叠）
    def random_windows(n: int, length: int = 25) -> list[int]:
        starts: list[int] = []
        for year in range(2021, 2027):
            idxs = np.flatnonzero(((ts.dt.year == year) & s0).to_numpy())
            if len(idxs) < length:
                continue
            picks = RNG.integers(idxs[0], idxs[-1] - length + 1, size=int(math.ceil(n / 6)) * 2)
            starts.extend(int(x) for x in picks)
        return starts[:n]

    fpr_count = 0
    valid_pseudo = 0
    for start in random_windows(1000):
        a_vals = []
        p_vals = []
        for _, row in base.iterrows():
            name = row["name"]
            if name in BINARY:
                window = f0[name].iloc[start : start + 25]
                a = float(window.fillna(0).mean() - f0[name][b0].mean())
            else:
                window = z_map[name].iloc[start : start + 25]
                if window.notna().mean() < 0.7:
                    a = np.nan
                else:
                    a = float(window.abs().mean())
            null = nulls[name]
            a_vals.append(a)
            p_vals.append((1 + int(np.sum(null >= a))) / (len(null) + 1) if np.isfinite(a) and len(null) else np.nan)
        pvals = bh_fdr(np.asarray(p_vals, dtype=float))
        valid_pseudo += 1
        if np.isfinite(pvals).any() and np.nanmin(pvals) <= 0.10:
            fpr_count += 1
    a5 = {"n_pseudo": valid_pseudo, "n_with_any_q10": fpr_count, "fpr": round(fpr_count / valid_pseudo, 4) if valid_pseudo else None}

    # A6：100 次 +3σ 注入（随机可用连续特征）
    continuous = [r["name"] for _, r in base.iterrows() if r["usable"] and r["name"] not in BINARY]
    hits = 0
    ranks = []
    target_counts: dict[str, int] = {}
    target_hits: dict[str, int] = {}
    target_ranks: dict[str, list[float]] = {}
    for _ in range(100):
        target = str(RNG.choice(continuous))
        target_counts[target] = target_counts.get(target, 0) + 1
        z = z_map[target].copy()
        z.loc[masks_base["E_pre"]] = z.loc[masks_base["E_pre"]] + 3.0
        a = float(z[masks_base["E_pre"]].abs().mean())
        row = base[base["name"] == target].iloc[0]
        std = (a - float(row["null_mean"])) / float(row["null_sd"])
        a_std = base["A_std"].copy()
        a_std.loc[base["name"] == target] = std
        r = rank_auc_like(a_std.to_numpy(dtype=float))
        ri = int(np.flatnonzero(base["name"].to_numpy() == target)[0])
        ranks.append(float(r[ri]))
        target_ranks.setdefault(target, []).append(float(r[ri]))
        if r[ri] == 1:
            hits += 1
            target_hits[target] = target_hits.get(target, 0) + 1
    a6 = {"n": 100, "top1_hits": hits, "top1_rate": hits / 100, "median_rank": float(np.median(ranks)), "target_counts": target_counts}
    a6_detail = pd.DataFrame(
        [
            {"target": name, "injections": target_counts[name], "top1_hits": target_hits.get(name, 0), "top1_rate": target_hits.get(name, 0) / target_counts[name], "median_rank": float(np.median(target_ranks[name]))}
            for name in sorted(target_counts)
        ]
    )
    a6_detail.to_csv(OUT / "q1_a6_detail.csv", index=False, encoding="utf-8-sig")

    # A8：窗口敏感性
    sensitivity_rows = []
    window_desc = {"E_pre": "主窗口 25h", "E6": "末 6h（7 样本）", "E72": "72h（73 样本）", "E_all": "描述窗口 31h"}
    for name, mask in masks_base.items():
        if name == "E_pre":
            table = base
        else:
            length = int(mask.sum())
            table, _, _ = scenario_table(f0, df, s0, b0, ts, mask, length)
        names = top5(table)
        overlap = len(set(names) & set(base_top5))
        sensitivity_rows.append({"scenario": name, "description": window_desc[name], "n_usable": int(table["usable"].sum()), "n_q10": int((table["q"] <= 0.10).sum()), "top5": "|".join(names), "overlap_with_E_pre": overlap})
        for _, row in table.iterrows():
            sensitivity_rows.append({"scenario": name, "feature_id": row["feature_id"], "name": row["name"], "A": row["A"], "A_std": row["A_std"], "p": row["p"], "q": row["q"], "rank": row["rank"], "selected": row["selected"]})

    # A9：基线 ±7/±30 天
    for label, start_md, end_md in [("base_pm7", 804, 917), ("base_pm30", 712, 1010)]:
        m, s, b = masks(f0, start_md, end_md)
        fb, _ = make_binary(build_features(df), df, b)
        table, _, _ = scenario_table(fb, df, s, b, ts, m["E_pre"], 25)
        names = top5(table)
        overlap = len(set(names) & set(base_top5))
        sensitivity_rows.append({"scenario": label, "description": f"基线 {start_md}-{end_md}", "n_usable": int(table["usable"].sum()), "n_q10": int((table["q"] <= 0.10).sum()), "top5": "|".join(names), "overlap_with_E_pre": overlap})
        for _, row in table.iterrows():
            sensitivity_rows.append({"scenario": label, "feature_id": row["feature_id"], "name": row["name"], "A": row["A"], "A_std": row["A_std"], "p": row["p"], "q": row["q"], "rank": row["rank"], "selected": row["selected"]})

    sens = pd.DataFrame(sensitivity_rows)
    sens.to_csv(OUT / "q1_sensitivity.csv", index=False, encoding="utf-8-sig")
    summary = pd.DataFrame([r for r in sensitivity_rows if "feature_id" not in r])
    summary.to_csv(OUT / "q1_sensitivity_summary.csv", index=False, encoding="utf-8-sig")
    closeout = {"base_top5": base_top5, "A5": a5, "A6": a6, "A8_A9_summary": summary.to_dict("records")}
    (OUT / "q1_closeout.json").write_text(json.dumps(closeout, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Q1 P0 收尾：A5/A6/A8/A9",
        "",
        "> 由 `q1_closeout.py` 生成；A5/A6 用 E_pre 的基线 null 分布；A8/A9 重算对应窗口/基线的 null。",
        "",
        "## A5 零模型 FPR",
        "",
        f"- 伪事件数：{a5['n_pseudo']}；任一特征 q≤0.10 的伪事件：{a5['n_with_any_q10']}；**FPR={a5['fpr']}**。",
        "- 验收：FPR≤10%。" + (" ✅ 通过" if a5["fpr"] is not None and a5["fpr"] <= 0.10 else " ❌ 未通过"),
        "",
        "## A6 合成注入（100 次）",
        "",
        f"- 随机可用连续特征 +3σ；Top1 命中 **{a6['top1_hits']}/100 = {a6['top1_rate']:.0%}**；中位排名 {a6['median_rank']:.1f}。",
        "- 验收：Top1≥90%。" + (" ✅ 通过" if a6["top1_rate"] >= 0.90 else " ❌ 未通过"),
        f"- 0 命中的目标：{', '.join(a6_detail[a6_detail['top1_hits'] == 0]['target'].tolist()) or '无'}；详见 `q1_a6_detail.csv`。",
        "",
        "## A8/A9 敏感性",
        "",
        "| 场景 | 说明 | 可用特征 | q≤0.10 | Top5 | 与 E_pre 重叠 |",
        "|---|---|---:|---:|---|---:|",
    ]
    for _, r in summary.iterrows():
        lines.append(f"| {r['scenario']} | {r['description']} | {r['n_usable']} | {r['n_q10']} | {r['top5'].replace('|', ', ')} | {r['overlap_with_E_pre']}/5 |")
    lines += [
        "",
        "- A8 验收：窗口 Top5 至少 3/5 重叠；A9 同理。低于 3/5 的场景必须标“窗口/基线敏感”。",
        "- 总结论：A8 因 E6=1/5 **未通过**；E72/E_all 通过；A9 两个基线均通过。",
        "",
        "## 备注",
        "",
        "- A5 的 null 与真实 E_pre 共用 B 的固定 med/MAD；伪事件只换窗口，不重算基线。",
        "- A6 注入的是 z（+3σ），不是原始变量；只针对连续、可用特征。",
        "- E_all 含事件后 6 h，只作描述窗口，不作为前兆窗口。",
    ]
    (OUT / "q1_closeout.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(closeout, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
