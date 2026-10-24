from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from q2_core import id_threshold, ice_trigger, m_cr  # noqa: E402
from q2_geometry import DATA, load_tiff  # noqa: E402

BASE = HERE.parents[2]
OUT = BASE / "03_编程手" / "Q2" / "实验结果"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    mc_rows = []
    for beta in range(5, 50, 5):
        for c in [0, 5, 10]:
            for phi in [25, 30, 35]:
                for z in [1, 2, 3]:
                    mc_rows.append({"beta_deg": beta, "c_prime_kpa": c, "phi_deg": phi, "z_m": z, "r": 0.5, "m_cr": round(m_cr(beta, phi, c, 20, z, 0.5), 4)})
    mc = pd.DataFrame(mc_rows)
    mc.to_csv(OUT / "q2_mcr_scan.csv", index=False, encoding="utf-8-sig")

    id_rows = [{"D_h": d, "a": 10, "b": 0.5, "I_c_mm_h": round(id_threshold(10, 0.5, d), 4)} for d in [1, 3, 6, 12, 24, 48, 72]]
    pd.DataFrame(id_rows).to_csv(OUT / "q2_id_curve.csv", index=False, encoding="utf-8-sig")

    dem, _ = load_tiff(DATA / "tpdc04_glacier" / "dem.tif")
    slope, _ = load_tiff(DATA / "tpdc04_glacier" / "slope.tif")
    thick, _ = load_tiff(DATA / "tpdc04_glacier" / "thickness.tif")
    vel, _ = load_tiff(DATA / "tpdc04_glacier" / "v.tif")
    mask = (
        (dem >= 5000) & (slope >= 25) & (thick >= 20) & (vel >= 5)
        & np.isfinite(dem) & np.isfinite(slope) & np.isfinite(thick) & np.isfinite(vel)
    )
    ice_summary = {
        "cells": int((np.isfinite(dem)).sum()),
        "z_ge_5000": int((dem >= 5000).sum()),
        "slope_ge_25": int((slope >= 25).sum()),
        "thickness_ge_20": int((thick >= 20).sum()),
        "velocity_ge_5": int((vel >= 5).sum()),
        "all_four": int(mask.sum()),
        "z_max": round(float(np.nanmax(dem)), 1),
        "slope_max": round(float(np.nanmax(slope)), 1),
        "thickness_max": round(float(np.nanmax(thick)), 1),
        "velocity_max": round(float(np.nanmax(vel)), 1),
    }
    pd.DataFrame([ice_summary]).to_csv(OUT / "q2_ice_screen.csv", index=False, encoding="utf-8-sig")

    cases = [
        {"event_id": "E20260826", "date": "2026-08-26", "I_rain": 0, "I_ice": 1 if ice_summary["all_four"] > 0 else 0, "I_glof": 0, "I_trig": 1, "S": "NA", "H": "NA", "note": "source outside 23 gully units; case consistency only"},
        {"event_id": "E20250708", "date": "2025-07-08", "I_rain": 0, "I_ice": 0, "I_glof": 1, "I_trig": 1, "S": "NA", "H": "NA", "note": "GLOF; no ice-lake inventory; qualitative branch"},
        {"event_id": "E20020523", "date": "2002-05-23", "I_rain": 0, "I_ice": 0, "I_glof": 1, "I_trig": 1, "S": "NA", "H": "NA", "note": "regional analogue; not local frequency"},
        {"event_id": "E20150425", "date": "2015-04-25", "I_rain": 0, "I_ice": 0, "I_glof": 0, "I_trig": 0, "S": "NA", "H": "NA", "note": "earthquake precondition, not debris-flow trigger"},
    ]
    pd.DataFrame(cases).to_csv(OUT / "q2_event_cases.csv", index=False, encoding="utf-8-sig")

    summary = {
        "mcr_rows": len(mc),
        "mcr_range": [float(mc["m_cr"].min()), float(mc["m_cr"].max())],
        "mcr_default": {"beta_30_phi35_c0_z2_r05": round(m_cr(30, 35, 0, 20, 2, 0.5), 4)},
        "id_curve": id_rows,
        "ice_screen": ice_summary,
        "cases": cases,
        "notes": [
            "m_cr/I-D/冰崩筛选均为 C 类情景参数；不是标定值",
            "冰崩筛选用 TPDC-04 30 m 像元，all_four=满足 z/slope/H/v 四条件的像元数",
            "2026/2025 事件源区不在 23 个登记沟域内，S/H 记 NA；只做触发分支一致性",
            "2002 嘉龙错是区域类比，不计入吉隆频率",
        ],
    }
    (OUT / "q2_threshold_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
