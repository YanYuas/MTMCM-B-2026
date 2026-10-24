from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from q4_solver import OUT, build_corridor, front_distance, simulate  # noqa: E402

SCENARIOS = [
    ("S0", 3e5, 0.45, 0.15, 300, 30),
    ("S1", 1e5, 0.45, 0.15, 300, 30),
    ("S2", 1e6, 0.45, 0.15, 300, 30),
    ("S3", 3e5, 0.30, 0.15, 300, 30),
    ("S4", 3e5, 0.60, 0.15, 300, 30),
    ("S5", 3e5, 0.45, 0.05, 300, 30),
    ("S6", 3e5, 0.45, 0.30, 300, 30),
    ("S7", 3e5, 0.45, 0.15, 100, 30),
    ("S8", 3e5, 0.45, 0.15, 1000, 30),
    ("S9", 3e5, 0.45, 0.15, 300, 60),
    ("S10", 3e5, 0.45, 0.15, 300, 90),
    ("S11", 3e5, 0.45, 0.05, 300, 30),
]


def main():
    rows = []
    for sid, v0, cv, mu, xi, dx in SCENARIOS:
        cor = build_corridor(ds=max(1, dx // 30), half_width_km=0.3, dx=float(dx))
        res = simulate(cor, V0=v0, cv=cv, mu=mu, xi=xi, t_end=1800, frame_every=60, c_dep=0.03)
        finite_arr = res["t_arr"][np.isfinite(res["t_arr"])]
        rows.append({
            "scenario": sid, "V0": v0, "C_v": cv, "mu": mu, "xi": xi, "grid_m": dx,
            "front_km": front_distance(cor, res["h"]),
            "max_h": float(res["h"].max()), "max_u": float(res["u"].max()),
            "mass_err": res["mass_err"], "mass_dep": res["mass_dep"], "outflow": res["outflow"],
            "t_arr_min_s": float(finite_arr.min()) if len(finite_arr) else None,
            "t_arr_median_s": float(np.median(finite_arr)) if len(finite_arr) else None,
            "source_cells": res["n_source"], "h0": res["h0"], "steps": res["steps"],
        })
        print(f"{sid}: front={rows[-1]['front_km']:.2f} km hmax={rows[-1]['max_h']:.2f} mass_err={rows[-1]['mass_err']:.2e}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "q4_scenarios.csv", index=False, encoding="utf-8-sig")
    (OUT / "q4_scenarios.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
