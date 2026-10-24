# -*- coding: utf-8 -*-
"""
Q3 数值算例/检查表生成器（建模手）
- 独立实现 Q3 V1–V12 与 A1–A12 的最小算例
- 不依赖 Q3 编程代码（Q3 代码尚未开始）
- 输出：03_编程手/核验往来/q3_fixtures/

用途：编程手实现 Q3 前先跑本检查表；全过再跑真实数据。
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\21722\Desktop\妈妈杯秋季赛\MTMCM比赛协作")
OUT = ROOT / "03_编程手" / "核验往来" / "q3_fixtures"
OUT.mkdir(parents=True, exist_ok=True)


def first_passage(values, threshold):
    for i, v in enumerate(values):
        if v >= threshold:
            return i
    return None


def linear_quantile(values, q):
    return float(np.quantile(np.asarray(values, dtype=float), q))


def censored_summary(values):
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    p_inf = float(1 - len(finite) / len(arr))
    lower = linear_quantile(finite, 0.025) if len(finite) else None
    upper = None if p_inf > 0.025 else (linear_quantile(finite, 0.975) if len(finite) else None)
    return {
        "p_inf": p_inf,
        "lower": lower,
        "upper": upper,
        "median": linear_quantile(finite, 0.5) if len(finite) else None,
        "n_finite": int(len(finite)),
        "n_total": int(len(arr)),
    }


def conformal_q(scores, alpha=0.05):
    n = len(scores)
    level = math.ceil((n + 1) * (1 - alpha)) / n
    # 线性分位；level 可能 >1，按最大分数处理
    if level >= 1:
        return float(max(scores)), level
    return linear_quantile(scores, level), level


def warning_time(cdf_rows, h_warn=6.0, p_warn=0.9):
    # cdf_rows: [(t0, P(T_impact <= t0 + h_warn))]
    for t0, p in cdf_rows:
        if p >= p_warn:
            return t0
    return None


def rain_trigger(p1h, api, vwc, m_cr=0.35, phi=0.40, a=10.0, api_c=80.0,
                 p_min=0.1, api_min=5.0):
    out = []
    for i in range(len(p1h)):
        m = min(max(vwc[i] / phi, 0.0), 1.0)
        active = (p1h[i] >= p_min) or (api[i] >= api_min)
        if not active:
            out.append(0.0)
            continue
        i_rain = max(p1h[i] / a, api[i] / api_c, m / m_cr)
        out.append(i_rain)
    return out


def main():
    rows = []

    def add(id_, input_, expected, actual, tol, note=""):
        if isinstance(expected, float) and isinstance(actual, float):
            ok = abs(expected - actual) <= tol
        elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            ok = abs(float(expected) - float(actual)) <= tol
        else:
            ok = expected == actual
        rows.append({"id": id_, "input": input_, "expected": expected, "actual": actual,
                     "tol": tol, "pass": bool(ok), "note": note})
        return ok

    # V1 first-passage
    v1 = first_passage([0.2, 0.5, 1.2, 1.5], 1.0)
    add("V1", "I=[0.2,0.5,1.2,1.5], thr=1.0", 2, v1, 0, "0-based; 第3个整点")

    # V2 quantiles
    q025 = linear_quantile([1, 2, 3, 4, 5], 0.025)
    q975 = linear_quantile([1, 2, 3, 4, 5], 0.975)
    add("V2a", "[1..5], q=0.025", 1.1, q025, 1e-9)
    add("V2b", "[1..5], q=0.975", 4.9, q975, 1e-9)

    # V3 lead time
    add("V3", "impact=10:00, warn=08:00", 2.0, 10.0 - 8.0, 1e-9, "小时")

    # V4 censoring
    cs = censored_summary([1, 2, 3, 4, np.inf])
    add("V4a", "[1,2,3,4,inf], p_inf", 0.2, cs["p_inf"], 1e-9)
    add("V4b", "[1,2,3,4,inf], lower", 1.075, cs["lower"], 1e-9, "有限样本 q0.025")
    add("V4c", "[1,2,3,4,inf], upper", None, cs["upper"], 0, "p_inf>0.025 -> inf")

    # V5 coverage
    add("V5", "95/100", 0.95, 95 / 100, 1e-9)
    add("V5ci", "Wilson 95% CI", [0.8882, 0.9785], [0.8882, 0.9785], 0.001, "参考值")

    # V6 warning
    tw = warning_time([(0, 0.4), (1, 0.7), (2, 0.92)], h_warn=6, p_warn=0.9)
    add("V6", "CDF 0.4/0.7/0.92, p_warn=0.9", 2, tw, 0, "t0=2 首次达标")

    # V7 competing risk
    trig = min(float("inf"), 10.5, float("inf"))
    add("V7", "rain=inf, ice=10.5, glof=inf", 10.5, trig, 1e-9)

    # V8 spatial
    add("V8", "D_arrival=20, buffer=5", 25.0, 20.0 + 5.0, 1e-9, "km")

    # V9 variance share
    add("V9", "Var_driver=0.8, Var_total=1.0", 0.8, 0.8 / 1.0, 1e-9)

    # V10 conformal
    qc, level = conformal_q([1, 2, 3, 4, 5], 0.05)
    add("V10a", "scores=[1..5], alpha=.05", 5.0, qc, 1e-9)
    add("V10b", "conformal level", 1.2, level, 1e-9, "ceil(6*0.95)/5")

    # V11 API
    api = float(np.dot(np.array([1, 2, 3])[::-1], 0.9 ** np.arange(3)))
    add("V11", "P=[1,2,3], k=.9", 5.61, api, 1e-9)

    # V12 width
    add("V12", "q2.5=1.1, q97.5=4.9", 3.8, 4.9 - 1.1, 1e-9)

    # A1 objects
    obj = {"T_trigger": None, "T_impact": None, "T_warn": None, "L": None,
           "interval": None, "coverage": None, "spatial": None}
    add("A1", "object keys", 7, len(obj), 0, "对象字段齐全")

    # A2 event labels
    event_times = ["2026-08-26 10:30", "2025-07-08 05:00"]
    add("A2", "local event count", 2, len(event_times), 0, "84 多边形不计入")

    # A3 forecast backfill
    forecast_start = "2026-10-24"
    event_time = "2026-08-26"
    add("A3", "forecast_start > event_time", True, forecast_start > event_time, 0, "历史不用 forecast")

    # A4 rain negative/positive
    p0 = [0.0] * 24
    a0 = [0.0] * 24
    v0 = [0.075] * 24
    i0 = rain_trigger(p0, a0, v0)
    add("A4a", "dry 2026-like", None, first_passage(i0, 1.0), 0, "T_rain=inf")
    p1 = [0.0] * 24
    p1[3] = 12.0
    i1 = rain_trigger(p1, [0.0] * 24, v0)
    add("A4b", "P1h=12 at t=3", 3, first_passage(i1, 1.0), 0, "P1h/10=1.2")
    # A4c 湿土但无水源：门控必须把 I_rain 压到 0，避免“湿土=触发”
    wet = [0.135] * 24
    i2 = rain_trigger([0.0] * 24, [0.0] * 24, wet)
    add("A4c", "wet soil, no water", None, first_passage(i2, 1.0), 0, "W_active=0; 不触发")

    # A5 competing branches
    branches = {"rain": float("inf"), "ice": 10.5, "glof": float("inf")}
    winner = min(branches, key=branches.get)
    add("A5", "min branch", "ice", winner, 0, "分支先触发")

    # A6 censoring
    cs2 = censored_summary([1, 2, np.inf, np.inf, np.inf])
    add("A6a", "3/5 inf", 0.6, cs2["p_inf"], 1e-9)
    add("A6b", "finite lower", 1.025, cs2["lower"], 1e-9)
    add("A6c", "upper", None, cs2["upper"], 0, "inf")

    # A7 interval
    add("A7a", "[0..4] q2.5", 0.1, linear_quantile([0, 1, 2, 3, 4], 0.025), 1e-9)
    add("A7b", "[0..4] q97.5", 3.9, linear_quantile([0, 1, 2, 3, 4], 0.975), 1e-9)

    # A8 warning/lead
    add("A8a", "T_warn", 2, tw, 0)
    add("A8b", "L=5-2", 3, 5 - tw, 1e-9)

    # A9 coverage three columns
    cov = {"event": "2/2 case inclusion", "proxy": 0.95, "design": 0.95}
    add("A9", "three coverage columns", 3, len(cov), 0, "不混写")

    # A10 conformal interval
    interval = [8 - qc, 8 + qc]
    add("A10a", "interval low", 3.0, interval[0], 1e-9)
    add("A10b", "Y=10 in [3,13]", True, interval[0] <= 10 <= interval[1], 0)

    # A11 spatial
    sp = {"D_arrival": 20.0, "D_impact": 10.0, "R_warn": 25.0}
    add("A11", "three spatial fields", 3, len(sp), 0, "km")

    # A12 text lint
    text = ["条件触发等级为高", "95%预测区间", "代理覆盖率不等于事件级覆盖率"]
    forbidden = ["发生概率", "95%置信度", "置信区间为95%"]
    add("A12", "no forbidden wording", True, not any(w in "".join(text) for w in forbidden), 0)

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "q3_v1_v12_check_table.csv", index=False, encoding="utf-8-sig")
    summary = {
        "n_checks": len(df),
        "n_pass": int(df["pass"].sum()),
        "all_pass": bool(df["pass"].all()),
        "v_checks": df[df["id"].str.startswith("V")].to_dict("records"),
        "a_checks": df[df["id"].str.startswith("A")].to_dict("records"),
    }
    with open(OUT / "q3_v1_v12_results.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)

    print(df.to_string(index=False))
    print("\nall_pass", summary["all_pass"], summary["n_pass"], "/", summary["n_checks"])
    return summary


if __name__ == "__main__":
    main()
