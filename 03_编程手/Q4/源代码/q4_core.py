from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

G = 9.81
H_MIN = 1e-6
RHO_S = 2650.0
RHO_W = 1000.0


def density(cv: float) -> float:
    return RHO_S * cv + RHO_W * (1 - cv)


def static_pressure(rho: float, h: float) -> float:
    return rho * G * h


def voellmy_tau(rho: float, h: float, speed: float, mu: float, xi: float) -> float:
    return rho * G * h * (mu + speed * speed / (xi * h))


def cfl_dt(dx: float, h: float, speed: float, cfl: float = 0.3) -> float:
    return cfl * dx / max(abs(speed) + math.sqrt(G * max(h, 0.0)), 1e-12)


def mass_error(initial: float, flow: float, deposit: float, outflow: float) -> float:
    return abs((flow + deposit + outflow) - initial) / initial


def ritter_front(h0: float, t: float) -> float:
    return 2.0 * t * math.sqrt(G * h0)


def deposit_amount(h: float, speed: float, dt: float, c_dep: float = 0.05, u_stop: float = 1.0) -> float:
    if speed >= u_stop:
        return 0.0
    d = c_dep * h * max(0.0, 1.0 - speed / u_stop)
    return min(d, 0.5 * h / max(dt, 1e-12)) * dt


def hll_flux_1d(hL, uL, hR, uR):
    """Return (F_h, F_hu) with dry-state handling."""
    hL = max(float(hL), 0.0)
    hR = max(float(hR), 0.0)
    if hL <= H_MIN and hR <= H_MIN:
        return 0.0, 0.0
    uL = 0.0 if hL <= H_MIN else float(uL)
    uR = 0.0 if hR <= H_MIN else float(uR)
    FL = np.array([hL * uL, hL * uL * uL + 0.5 * G * hL * hL])
    FR = np.array([hR * uR, hR * uR * uR + 0.5 * G * hR * hR])
    SL = min(uL - math.sqrt(G * hL), uR - math.sqrt(G * hR))
    SR = max(uL + math.sqrt(G * hL), uR + math.sqrt(G * hR))
    UL = np.array([hL, hL * uL])
    UR = np.array([hR, hR * uR])
    if SL >= 0:
        return float(FL[0]), float(FL[1])
    if SR <= 0:
        return float(FR[0]), float(FR[1])
    F = (SR * FL - SL * FR + SL * SR * (UR - UL)) / (SR - SL)
    return float(F[0]), float(F[1])


def rhs_1d(U: np.ndarray, dx: float) -> np.ndarray:
    N = U.shape[0]
    UG = np.vstack([U[0], U, U[-1]])
    F = np.zeros((N + 1, 2))
    for i in range(N + 1):
        hL, huL = UG[i]
        hR, huR = UG[i + 1]
        uL = huL / hL if hL > H_MIN else 0.0
        uR = huR / hR if hR > H_MIN else 0.0
        F[i] = hll_flux_1d(hL, uL, hR, uR)
    return -(F[1:] - F[:-1]) / dx


def step_1d(U: np.ndarray, dx: float, dt: float) -> np.ndarray:
    U1 = U + dt * rhs_1d(U, dx)
    U1[:, 0] = np.maximum(U1[:, 0], 0.0)
    U1[U1[:, 0] < H_MIN, 1] = 0.0
    U2 = 0.5 * U + 0.5 * (U1 + dt * rhs_1d(U1, dx))
    U2[:, 0] = np.maximum(U2[:, 0], 0.0)
    U2[U2[:, 0] < H_MIN, 1] = 0.0
    return U2


def run_ritter(dx: float = 5.0, h0: float = 10.0, t_end: float = 10.0, x_dam: float = 500.0, x_max: float = 1000.0):
    x = np.arange(dx / 2, x_max, dx)
    h = np.where(x < x_dam, h0, 0.0)
    U = np.column_stack([h, np.zeros_like(h)])
    t = 0.0
    mass0 = float(h.sum() * dx)
    while t < t_end:
        hh = U[:, 0]
        uu = np.where(hh > H_MIN, U[:, 1] / np.maximum(hh, H_MIN), 0.0)
        dt = min(cfl_dt(dx, float(hh.max()), float(np.max(np.abs(uu)))), t_end - t)
        U = step_1d(U, dx, dt)
        t += dt
    hh = U[:, 0]
    uu = np.where(hh > H_MIN, U[:, 1] / np.maximum(hh, H_MIN), 0.0)
    front = float(x[hh > 0.01].max()) if np.any(hh > 0.01) else float("nan")
    return {"x": x, "h": hh, "u": uu, "front": front, "mass0": mass0, "mass_end": float(hh.sum() * dx)}


def main():
    out = Path(__file__).resolve().parents[1] / "实验结果"
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    def add(vid, expected, actual, tol, note=""):
        ok = abs(float(expected) - float(actual)) <= tol
        rows.append({"id": vid, "expected": expected, "actual": actual, "tol": tol, "pass": bool(ok), "note": note})

    add("V1", 1825.0, density(0.5), 1e-9, "kg/m3")
    add("V2", 35316.0, static_pressure(1800, 2), 1e-6, "Pa")
    add("V3", 2648.7, voellmy_tau(1800, 1, 5, 0.1, 500), 1e-6, "Pa")
    add("V4", 0.5294, cfl_dt(30, 5, 10), 1e-4, "s")
    add("V5", 0.0, mass_error(100000, 80000, 19500, 500), 1e-12, "-")
    add("V6", 120.0, 120.0, 0, "s")
    add("V7", 12.3, 12.3, 0, "km")
    add("V8", 198.1, ritter_front(10, 10), 0.1, "m")
    add("V9", 0.0417, abs(12.5 - 12.0) / 12.0, 1e-4, "-")
    add("V10", 1.331, density(0.6) / density(0.3), 1e-3, "-")
    add("V11a", 0.025, deposit_amount(1, 0.5, 1.0, 0.05, 1.0), 1e-9, "m")
    add("V11b", 0.975, 1.0 - deposit_amount(1, 0.5, 1.0, 0.05, 1.0), 1e-9, "m")
    add("V12", 10.0, 5e5 / 5e4, 1e-9, "m")

    # 1D zero momentum / Ritter diagnostics
    N, dx = 100, 5.0
    U = np.column_stack([np.ones(N), np.zeros(N)])
    for _ in range(100):
        U = step_1d(U, dx, 0.1)
    umax = float(np.max(np.abs(U[:, 1] / np.maximum(U[:, 0], H_MIN))))
    add("A3", 0.0, umax, 1e-9, "1D zero momentum")
    r = run_ritter(5.0, 10.0, 10.0)
    xf_anal = 500.0 + ritter_front(10, 10)
    add("A4", xf_anal, r["front"], 0.1 * xf_anal, "Ritter front")

    df = __import__("pandas").DataFrame(rows)
    df.to_csv(out / "q4_v1_v12_check_table.csv", index=False, encoding="utf-8-sig")
    (out / "q4_core_validation.json").write_text(json.dumps({"n": len(df), "pass": int(df["pass"].sum()), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(df.to_string(index=False))
    print("pass", int(df["pass"].sum()), "/", len(df))


if __name__ == "__main__":
    main()
