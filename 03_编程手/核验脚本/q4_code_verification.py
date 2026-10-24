# -*- coding: utf-8 -*-
"""
Q4 代码级数值验证（建模手）
- 1D HLL 浅水参考解：零动量、Ritter 溃坝、网格收敛、质量守恒、堆积
- HLL 通量/CFL/堆积的单元算例
- 输出：03_编程手/核验往来/q4_code_check/
- 目的：给编程手的 2D 求解器提供组件级/集成级对照，不是 Q4 真实 2D 结果
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\21722\Desktop\妈妈杯秋季赛\MTMCM比赛协作")
OUT = ROOT / "03_编程手" / "核验往来" / "q4_code_check"
OUT.mkdir(parents=True, exist_ok=True)

G = 9.81
H_MIN = 1e-6


def hll_flux(hL, uL, hR, uR, g=G):
    """1D HLL flux for [h, hu]; returns (F_h, F_hu)."""
    if hL <= H_MIN and hR <= H_MIN:
        return 0.0, 0.0
    uL = 0.0 if hL <= H_MIN else uL
    uR = 0.0 if hR <= H_MIN else uR
    FL = np.array([hL * uL, hL * uL * uL + 0.5 * g * hL * hL])
    FR = np.array([hR * uR, hR * uR * uR + 0.5 * g * hR * hR])
    SL = min(uL - math.sqrt(g * hL), uR - math.sqrt(g * hR))
    SR = max(uL + math.sqrt(g * hL), uR + math.sqrt(g * hR))
    UL = np.array([hL, hL * uL])
    UR = np.array([hR, hR * uR])
    if SL >= 0:
        return float(FL[0]), float(FL[1])
    if SR <= 0:
        return float(FR[0]), float(FR[1])
    F = (SR * FL - SL * FR + SL * SR * (UR - UL)) / (SR - SL)
    return float(F[0]), float(F[1])


def cfl_dt(dx, h, u, cfl=0.3, g=G):
    return cfl * dx / max(abs(u) + math.sqrt(g * max(h, 0.0)), 1e-12)


def deposit_step(h, u, dt, c_dep=0.05, u_stop=1.0):
    """Return (h_new, deposit); mass h+deposit conserved."""
    if abs(u) < u_stop:
        d = c_dep * h * max(0.0, 1.0 - abs(u) / u_stop)
    else:
        d = 0.0
    d = min(d, 0.5 * h / max(dt, 1e-12))
    return h - d * dt, d * dt


def rhs(U, dx, g=G):
    """1D shallow water, flat bed, transmissive ghosts; U shape (N,2)."""
    N = U.shape[0]
    # ghosts: zero-gradient
    UL = np.vstack([U[0], U, U[-1]])
    F = np.zeros((N + 1, 2))
    for i in range(N + 1):
        hL, huL = UL[i]
        hR, huR = UL[i + 1]
        uL = huL / hL if hL > H_MIN else 0.0
        uR = huR / hR if hR > H_MIN else 0.0
        fh, fhu = hll_flux(hL, uL, hR, uR, g)
        F[i] = [fh, fhu]
    dU = -(F[1:] - F[:-1]) / dx
    return dU


def step(U, dx, dt, g=G):
    U1 = U + dt * rhs(U, dx, g)
    U1[:, 0] = np.maximum(U1[:, 0], 0.0)
    U1[U1[:, 0] < H_MIN, 1] = 0.0
    U2 = 0.5 * U + 0.5 * (U1 + dt * rhs(U1, dx, g))
    U2[:, 0] = np.maximum(U2[:, 0], 0.0)
    U2[U2[:, 0] < H_MIN, 1] = 0.0
    return U2


def run_dam_break(dx, t_end=10.0, h0=10.0, x_dam=500.0, x_max=1000.0, cfl=0.3):
    x = np.arange(dx / 2, x_max, dx)
    h = np.where(x < x_dam, h0, 0.0)
    U = np.column_stack([h, np.zeros_like(h)])
    t = 0.0
    mass0 = float(h.sum() * dx)
    while t < t_end:
        h = U[:, 0]
        u = np.where(h > H_MIN, U[:, 1] / np.maximum(h, H_MIN), 0.0)
        dt = cfl_dt(dx, float(h.max()), float(np.max(np.abs(u))), cfl)
        dt = min(dt, t_end - t)
        U = step(U, dx, dt)
        t += dt
    h = U[:, 0]
    u = np.where(h > H_MIN, U[:, 1] / np.maximum(h, H_MIN), 0.0)
    front = float(x[h > 0.01].max()) if np.any(h > 0.01) else float("nan")
    mass = float(h.sum() * dx)
    return {"dx": dx, "t_end": t_end, "front": front, "mass0": mass0, "mass_end": mass,
            "x": x, "h": h, "u": u}


def main():
    checks = []

    def add(id_, desc, expected, actual, tol, note=""):
        ok = abs(float(expected) - float(actual)) <= tol
        checks.append({"id": id_, "desc": desc, "expected": expected, "actual": actual,
                       "tol": tol, "pass": bool(ok), "note": note})

    # U1 HLL uniform state
    fh, fhu = hll_flux(1.0, 2.0, 1.0, 2.0)
    add("U1a", "HLL uniform F_h", 2.0, fh, 1e-9)
    add("U1b", "HLL uniform F_hu", 2.0 * 2.0 + 0.5 * G, fhu, 1e-9)

    # U2 CFL
    dt = cfl_dt(30, 5, 10)
    add("U2", "CFL dt", 0.3 * 30 / (10 + math.sqrt(G * 5)), dt, 1e-9)

    # U3 deposition mass
    h, dep = deposit_step(1.0, 0.5, 1.0, c_dep=0.05, u_stop=1.0)
    add("U3a", "deposit thickness", 0.025, dep, 1e-12)
    add("U3b", "h+dep mass", 1.0, h + dep, 1e-12)

    # U4 zero momentum
    N = 100
    dx = 5.0
    U = np.column_stack([np.ones(N), np.zeros(N)])
    for _ in range(100):
        U = step(U, dx, 0.1)
    umax = float(np.max(np.abs(U[:, 1] / np.maximum(U[:, 0], H_MIN))))
    add("U4", "zero momentum max abs(u)", 0.0, umax, 1e-9)

    # U5 Ritter / grid convergence（用剖面 L1 误差，不用前端阈值，避免粗网格“前端超射”）
    rows = []
    for dx in [20.0, 10.0, 5.0]:
        res = run_dam_break(dx, t_end=10.0)
        x = res["x"]
        h = res["h"]
        xi = (x - 500.0) / 10.0
        h_anal = np.where(
            xi < -math.sqrt(G * 10.0), 10.0,
            np.where(xi <= 2 * math.sqrt(G * 10.0),
                     (2 * math.sqrt(G * 10.0) - xi) ** 2 / (9 * G), 0.0),
        )
        xf_anal = 500.0 + 2 * 10.0 * math.sqrt(G * 10.0)
        front_err = abs(res["front"] - xf_anal) / (xf_anal - 500.0)
        l1 = float(np.mean(np.abs(h - h_anal)) / 10.0)
        l2 = float(np.sqrt(np.mean((h - h_anal) ** 2)) / 10.0)
        rows.append({"dx": dx, "front_sim": res["front"], "front_anal": xf_anal,
                     "front_rel_err": front_err, "L1_rel_err": l1, "L2_rel_err": l2,
                     "mass0": res["mass0"], "mass_end": res["mass_end"]})
        if dx == 5.0:
            pd.DataFrame({"x": x, "h_sim": h, "h_anal": h_anal, "u": res["u"]}).to_csv(
                OUT / "q4_ritter_profile_dx5.csv", index=False, encoding="utf-8-sig")
    conv = pd.DataFrame(rows)
    conv.to_csv(OUT / "q4_ritter_convergence.csv", index=False, encoding="utf-8-sig")
    add("U5a", "Ritter dx=5 L1 rel err", 0.0,
        float(conv.loc[conv.dx == 5, "L1_rel_err"].iloc[0]), 0.02)
    add("U5b", "Ritter dx=10 L1 rel err", 0.0,
        float(conv.loc[conv.dx == 10, "L1_rel_err"].iloc[0]), 0.03)
    e20 = float(conv.loc[conv.dx == 20, "L1_rel_err"].iloc[0])
    e10 = float(conv.loc[conv.dx == 10, "L1_rel_err"].iloc[0])
    e5 = float(conv.loc[conv.dx == 5, "L1_rel_err"].iloc[0])
    checks.append({"id": "U5c", "desc": "Ritter L1 error decreases with dx",
                   "expected": "e20>=e10>=e5", "actual": f"{e20:.4f}/{e10:.4f}/{e5:.4f}",
                   "tol": 0, "pass": bool(e20 >= e10 >= e5), "note": ""})
    add("U5d", "Ritter dx=5 front rel err (diagnostic)", 0.0,
        float(conv.loc[conv.dx == 5, "front_rel_err"].iloc[0]), 0.15)

    # U6 HLL cases for component comparison
    cases = []
    for hL, uL, hR, uR in [(1, 2, 1, 2), (2, 0, 1, 0), (1, 1, 0.5, 0.5), (0, 0, 1, 0), (1, 0, 0, 0)]:
        fh, fhu = hll_flux(float(hL), float(uL), float(hR), float(uR))
        cases.append({"hL": hL, "uL": uL, "hR": hR, "uR": uR, "F_h": fh, "F_hu": fhu})
    pd.DataFrame(cases).to_csv(OUT / "q4_hll_cases.csv", index=False, encoding="utf-8-sig")

    # U7 mass conservation closed boundary? rhs uses transmissive; for closed, spec only.
    # We provide deposition mass check U3; full 2D mass check is programming-hand.

    df = pd.DataFrame(checks)
    df.to_csv(OUT / "q4_code_check_table.csv", index=False, encoding="utf-8-sig")
    summary = {"n_checks": len(df), "n_pass": int(df["pass"].sum()),
               "all_pass": bool(df["pass"].all()),
               "ritter": conv.to_dict("records"),
               "checks": df.to_dict("records")}
    with open(OUT / "q4_code_check_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2, default=str)
    print(df.to_string(index=False))
    print("\nall_pass", summary["all_pass"], summary["n_pass"], "/", summary["n_checks"])
    print(conv.to_string(index=False))


if __name__ == "__main__":
    main()
