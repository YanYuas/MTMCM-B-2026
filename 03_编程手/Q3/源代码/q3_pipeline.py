from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "Q2" / "源代码"))
from q3_core import (  # noqa: E402
    censored_summary,
    conformal_q,
    first_passage,
    quantile,
    rain_indicator,
    spatial_range,
    warning_time,
    wilson_interval,
)
from q2_core import m_cr as q2_mcr  # noqa: E402

BASE = HERE.parents[2]
OUT = BASE / "03_编程手" / "Q3" / "实验结果"
OUT.mkdir(parents=True, exist_ok=True)
DRIVER_DIR = BASE / "03_编程手" / "核验往来" / "q3_drivers"
RNG = np.random.default_rng(20261024)
N = 2000


def load_driver(year: int):
    return pd.read_csv(DRIVER_DIR / f"q3_driver_example_{year}.csv")


def specs(df: pd.DataFrame, year: int):
    out = {
        "station": ("station_precip_mm", "station_api72_mm", "station_vwc"),
        "chirps": ("chirps_event_area_mm_h_uniform", "chirps_api72_mm_uniform", "station_vwc"),
    }
    if year == 2026:
        out["era5"] = ("era5_precip_mm", "era5_api72_mm", "station_vwc")
        out["nasa"] = ("nasa_precip_mm_lst", "nasa_api72_mm_lst", "station_vwc")
    return {k: tuple(v) for k, v in out.items()}


def rain_branch(df: pd.DataFrame, cols: tuple[str, str, str], a: float, api_c: float, mcr: float):
    p, api, vwc = (df[c].to_numpy(dtype=float) for c in cols)
    ir = rain_indicator(p, api, vwc, a=a, api_c=api_c, m_cr=mcr)
    t = first_passage(ir, 1.0)
    return (np.inf if t is None else float(t)), float(np.nanmax(ir)), int(np.sum(ir > 0))


def build_drivers():
    rows = []
    for year in (2026, 2025):
        df = load_driver(year)
        for name, (pc, ac, vc) in specs(df, year).items():
            p = df[pc].to_numpy(dtype=float)
            api = df[ac].to_numpy(dtype=float)
            vwc = df[vc].to_numpy(dtype=float)
            ir = rain_indicator(p, api, vwc)
            for i, ts in enumerate(df["timestamp_bjt"]):
                rows.append(
                    {
                        "timestamp_bjt": ts,
                        "year": year,
                        "driver": name,
                        "precip_mm_h": p[i],
                        "api72_mm": api[i],
                        "vwc_m3m3": vwc[i],
                        "active": bool((p[i] >= 0.1) or (np.isfinite(api[i]) and api[i] >= 5)),
                        "I_rain_fixed": ir[i],
                        "time_standard": "LST" if name == "nasa" else ("daily_uniform" if name == "chirps" else "Asia/Shanghai"),
                        "qc": "B" if name in {"era5", "nasa", "chirps"} else "A",
                    }
                )
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "q3_drivers.csv", index=False, encoding="utf-8-sig")
    return out


def main() -> None:
    build_drivers()
    summary = {"N": N, "events": {}, "drivers": {}}
    scenario_rows = []
    case_rows = []
    interval_rows = []
    warning_rows = []

    event_meta = {
        2026: {"event_time": pd.Timestamp("2026-08-26 10:30"), "window_start": pd.Timestamp("2026-08-23 10:00"), "branch": "ice", "detect": 72.5},
        2025: {"event_time": pd.Timestamp("2025-07-08 05:00"), "window_start": pd.Timestamp("2025-07-05 05:00"), "branch": "glof", "detect": 72.0},
    }

    for year in (2026, 2025):
        df = load_driver(year)
        sp = specs(df, year)
        drivers = list(sp)
        # 固定参数负控制
        controls = {}
        for d in drivers:
            tr, max_i, active_n = rain_branch(df, sp[d], 10, 80, 0.35)
            controls[d] = {"T_rain_h": None if not np.isfinite(tr) else tr, "max_I": max_i, "active_n": active_n}
        summary["drivers"][str(year)] = controls

        for k in range(N):
            d = str(RNG.choice(drivers))
            a = float(RNG.uniform(5, 20))
            b = float(RNG.uniform(0.3, 0.7))
            api_c = float(RNG.uniform(60, 120))
            c = float(RNG.uniform(0, 20))
            phi = float(RNG.uniform(25, 40))
            z = float(RNG.uniform(0.5, 3.0))
            gamma = float(RNG.uniform(18, 22))
            mcr = float(q2_mcr(30, phi, c, gamma, z, 0.5))
            tr, max_i, active_n = rain_branch(df, sp[d], a, api_c, mcr)
            tice = np.inf
            tglof = np.inf
            if year == 2026:
                tice = 72.5 - float(RNG.uniform(0, 3))
            else:
                dg = float(RNG.uniform(3, 6))
                tglof = 72.0 - float(RNG.uniform(0, dg))
            trig = min(tr, tice, tglof)
            if not np.isfinite(trig):
                winner = "none"
            elif trig == tr:
                winner = "rain"
            elif trig == tice:
                winner = "ice"
            else:
                winner = "glof"
            travel = float(RNG.uniform(0.5, 3.0))
            impact = trig + travel if np.isfinite(trig) else np.inf
            scenario_rows.append(
                {
                    "event": year,
                    "sample": k,
                    "driver": d,
                    "a": a,
                    "b": b,
                    "api_c": api_c,
                    "c_prime": c,
                    "phi_deg": phi,
                    "z_m": z,
                    "gamma_sat": gamma,
                    "m_cr": mcr,
                    "T_rain_h": tr,
                    "T_ice_h": tice,
                    "T_glof_h": tglof,
                    "T_trigger_h": trig,
                    "winner": winner,
                    "T_travel_h": travel,
                    "T_impact_h": impact,
                    "max_I_rain": max_i,
                    "active_n": active_n,
                }
            )
        sc = pd.DataFrame([r for r in scenario_rows if r["event"] == year]).copy()
        for name in ("T_rain_h", "T_ice_h", "T_glof_h", "T_trigger_h", "T_impact_h"):
            sc[name] = pd.to_numeric(sc[name], errors="coerce")
        finite_trig = sc.loc[np.isfinite(sc["T_trigger_h"]), "T_trigger_h"]
        finite_impact = sc.loc[np.isfinite(sc["T_impact_h"]), "T_impact_h"]
        p_inf = 1 - len(finite_trig) / len(sc)
        trig_summary = censored_summary(sc["T_trigger_h"].to_numpy(dtype=float))
        imp_summary = censored_summary(sc["T_impact_h"].to_numpy(dtype=float))
        branch_counts = sc["winner"].value_counts().to_dict()
        interval_rows.append(
            {
                "event": year,
                "quantity": "T_trigger_h",
                "p_inf": p_inf,
                "q025": trig_summary["lower"],
                "median": trig_summary["median"],
                "q975": trig_summary["upper"],
                "width_h": None if trig_summary["upper"] is None else trig_summary["upper"] - trig_summary["lower"],
                "n_finite": trig_summary["n_finite"],
                "branch_counts": json.dumps(branch_counts, ensure_ascii=False),
            }
        )
        interval_rows.append(
            {
                "event": year,
                "quantity": "T_impact_h",
                "p_inf": p_inf,
                "q025": imp_summary["lower"],
                "median": imp_summary["median"],
                "q975": imp_summary["upper"],
                "width_h": None if imp_summary["upper"] is None else imp_summary["upper"] - imp_summary["lower"],
                "n_finite": imp_summary["n_finite"],
                "branch_counts": json.dumps(branch_counts, ensure_ascii=False),
            }
        )
        summary["events"][str(year)] = {
            "event_time": str(event_meta[year]["event_time"]),
            "T_trigger": trig_summary,
            "T_impact": imp_summary,
            "p_inf": p_inf,
            "branch_counts": branch_counts,
            "fixed_driver_controls": controls,
        }

        # 预警主值 + 敏感性
        for h_warn, p_warn in [(6, 0.9), (1, 0.9), (3, 0.9), (12, 0.9), (6, 0.8), (6, 0.95)]:
            impacts = sc["T_impact_h"].to_numpy(dtype=float)
            cdf = [(t0, float(np.mean(impacts <= t0 + h_warn))) for t0 in range(0, 73)]
            tw = warning_time(cdf, h_warn, p_warn)
            if tw is None:
                lead = None
                lead_rows = None
            else:
                leads = finite_impact - tw
                lead_rows = {
                    "q025": float(np.quantile(leads, 0.025)),
                    "median": float(np.quantile(leads, 0.5)),
                    "q975": float(np.quantile(leads, 0.975)),
                    "n_negative": int((leads < 0).sum()),
                }
                lead = float(np.median(leads))
            warning_rows.append(
                {
                    "event": year,
                    "H_warn_h": h_warn,
                    "p_warn": p_warn,
                    "T_warn_h": tw,
                    "T_warn_bjt": None if tw is None else str(event_meta[year]["window_start"] + pd.Timedelta(hours=tw)),
                    "lead_median_h": lead,
                    "lead_q025_h": None if lead_rows is None else lead_rows["q025"],
                    "lead_q975_h": None if lead_rows is None else lead_rows["q975"],
                    "n_negative_lead": None if lead_rows is None else lead_rows["n_negative"],
                }
            )

        case_rows.append(
            {
                "event": year,
                "event_time_bjt": str(event_meta[year]["event_time"]),
                "I_rain_station": 0,
                "T_rain_station_h": controls["station"]["T_rain_h"],
                "T_ice_h_scenario": "∞" if year == 2025 else "finite (detect−τ)",
                "T_glof_h_scenario": "∞" if year == 2026 else "finite (detect−τ)",
                "T_trigger_q025_h": trig_summary["lower"],
                "T_trigger_median_h": trig_summary["median"],
                "T_trigger_q975_h": trig_summary["upper"],
                "p_inf": p_inf,
                "dominant_branch": max(branch_counts, key=branch_counts.get),
                "note": "case consistency only; not event-level coverage",
            }
        )

    pd.DataFrame(scenario_rows).to_csv(OUT / "q3_scenarios.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(scenario_rows).to_csv(OUT / "q3_trigger_ensemble.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(interval_rows).to_csv(OUT / "q3_interval_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(warning_rows).to_csv(OUT / "q3_warning_timeline.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(case_rows).to_csv(OUT / "q3_event_cases.csv", index=False, encoding="utf-8-sig")

    # 空间三分（Q4 未回填，C 类情景）
    sp_rows = spatial_range(N, 20261024)
    pd.DataFrame(sp_rows).to_csv(OUT / "q3_spatial_range.csv", index=False, encoding="utf-8-sig")

    # 代理共形：24h 降水 / 6h 气温
    proxy_rows, proxy_detail = proxy_conformal()
    pd.DataFrame(proxy_rows).to_csv(OUT / "q3_proxy_coverage.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(proxy_detail).to_csv(OUT / "q3_proxy_detail.csv", index=False, encoding="utf-8-sig")

    summary["proxy"] = proxy_rows
    summary["spatial"] = sp_rows
    (OUT / "q3_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:8000])


def proxy_conformal():
    path = BASE / "03_编程手" / "数据获取" / "data" / "processed" / "tpdc01_hourly" / "tpdc01_key_vars_long.csv.gz"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    clean = df.copy()
    clean.loc[clean["qc_missing"] == 1, "value"] = np.nan
    clean.loc[clean["qc_suspect"] == 1, "value"] = np.nan
    pivot = clean.pivot_table(index="timestamp", columns="variable", values="value", aggfunc="first").sort_index()
    p = pivot["Precip"].astype(float)
    p = p.where((p >= 0) & (p < 1000))
    ta = pivot["Ta_2m"].astype(float)
    ta = ta.where((ta > -50) & (ta < 60))
    out = []
    detail = []
    # 24h 降水：用前 24h 作为持续性预报，目标为后 24h
    prev24 = p.rolling(24).sum().shift(1)
    next24 = p.shift(-24).rolling(24).sum()
    tx = ta.shift(-6).rolling(6).mean()
    for target, pred, y in [
        ("precip_24h_next", prev24, next24),
        ("temp_6h_next_mean", ta, tx),
    ]:
        use = pd.DataFrame({"pred": pred, "y": y}).dropna()
        cal = use[use.index.year <= 2024]
        test = use[use.index.year == 2025]
        if len(cal) < 100 or len(test) < 50:
            out.append({"target": target, "cal_n": len(cal), "test_n": len(test), "coverage": None, "width": None, "wilson_low": None, "wilson_high": None})
            continue
        scores = np.abs(cal["y"].to_numpy() - cal["pred"].to_numpy())
        q, level = conformal_q(scores, 0.05)
        lo = test["pred"].to_numpy() - q
        hi = test["pred"].to_numpy() + q
        hit = (test["y"].to_numpy() >= lo) & (test["y"].to_numpy() <= hi)
        k = int(hit.sum())
        n = len(test)
        wl, wh = wilson_interval(k, n)
        out.append(
            {
                "target": target,
                "cal_n": int(len(cal)),
                "test_n": int(n),
                "alpha": 0.05,
                "q_conf": q,
                "coverage": k / n,
                "width": 2 * q,
                "wilson_low": wl,
                "wilson_high": wh,
                "note": "split conformal; calibration 2021-2024, test 2025; persistence forecast",
            }
        )
        for i in range(min(200, n)):
            detail.append({"target": target, "pred": float(test["pred"].iloc[i]), "y": float(test["y"].iloc[i]), "lo": float(lo[i]), "hi": float(hi[i]), "hit": bool(hit[i])})
    return out, detail


if __name__ == "__main__":
    main()
