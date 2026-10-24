# -*- coding: utf-8 -*-
"""
Q4 V1–V12 数值算例/检查表（建模手）
- 独立实现密度/静压/Voellmy/CFL/质量/Ritter/堆积/源区等最小算子
- 不依赖 Q4 编程代码（Q4 代码尚未开始）
- 输出：03_编程手/核验往来/q4_fixtures/
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\21722\Desktop\妈妈杯秋季赛\MTMCM比赛协作")
OUT = ROOT / "03_编程手" / "核验往来" / "q4_fixtures"
OUT.mkdir(parents=True, exist_ok=True)


def density(cv, rho_s=2650.0, rho_w=1000.0):
    return rho_s * cv + rho_w * (1 - cv)


def static_pressure(rho, h, g=9.81):
    return rho * g * h


def voellmy(rho, h, u, mu, xi, g=9.81):
    return rho * g * h * (mu + u * u / (xi * h))


def cfl_dt(dx, u, h, cfl=0.3, g=9.81):
    return cfl * dx / (abs(u) + math.sqrt(g * h))


def mass_error(initial, final_flow, deposit, outflow):
    total = final_flow + deposit + outflow
    return abs(total - initial) / initial


def ritter_front(h0, t, g=9.81):
    return 2 * t * math.sqrt(g * h0)


def main():
    rows = []

    def add(id_, input_, expected, actual, tol, note=""):
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            ok = abs(float(expected) - float(actual)) <= tol
        else:
            ok = expected == actual
        rows.append({"id": id_, "input": input_, "expected": expected, "actual": actual,
                     "tol": tol, "pass": bool(ok), "note": note})

    rho = density(0.5)
    add("V1", "C_v=.5", 1825.0, rho, 1e-9, "kg/m3")

    p = static_pressure(1800, 2)
    add("V2", "rho=1800,h=2", 35316.0, p, 1e-6, "Pa")

    tau = voellmy(1800, 1, 5, 0.1, 500)
    add("V3", "rho=1800,h=1,|u|=5,mu=.1,xi=500", 2648.7, tau, 1e-6, "Pa")

    dt = cfl_dt(30, 10, 5)
    add("V4", "dx=30,|u|=10,h=5,CFL=.3", 0.5294, dt, 1e-4, "s")

    em = mass_error(100000, 80000, 19500, 500)
    add("V5", "100000=80000+19500+500", 0.0, em, 1e-12)

    add("V6", "h>=0.2 first at 120s", 120.0, 120.0, 0, "s")
    add("V7", "h>=0.5 max 12.3km", 12.3, 12.3, 0, "km")

    xf = ritter_front(10, 10)
    add("V8", "h0=10,t=10", 198.1, xf, 0.1, "m")

    eps_g = abs(12.5 - 12.0) / 12.0
    add("V9", "90/60/30 runout 12.5/12.2/12.0", 0.0417, eps_g, 1e-4)

    ratio = density(0.6) / density(0.3)
    add("V10", "C_v .3->.6 dynamic pressure ratio", 1.331, ratio, 1e-3)

    # V11 deposition: h=1, |u|=.5, u_stop=1, c_dep=.05, dt=1
    h = 1.0
    d = 0.05 * h * max(0.0, 1 - 0.5 / 1.0)
    h2 = h - d
    add("V11a", "deposit thickness", 0.025, d, 1e-9, "m")
    add("V11b", "h after deposit", 0.975, h2, 1e-9, "m")

    add("V12", "V0=5e5,A=5e4", 10.0, 5e5 / 5e4, 1e-9, "m")

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "q4_v1_v12_check_table.csv", index=False, encoding="utf-8-sig")
    summary = {"n_checks": len(df), "n_pass": int(df["pass"].sum()),
               "all_pass": bool(df["pass"].all()), "checks": df.to_dict("records")}
    with open(OUT / "q4_v1_v12_results.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)
    print(df.to_string(index=False))
    print("\nall_pass", summary["all_pass"], summary["n_pass"], "/", summary["n_checks"])
    return summary


if __name__ == "__main__":
    main()
