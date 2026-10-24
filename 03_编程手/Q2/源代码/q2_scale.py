from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

import sys
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from q2_geometry import DATA, grid, load_tiff, rasterize  # noqa: E402

BASE = HERE.parents[2]
OUT = BASE / "03_编程手" / "Q2" / "实验结果"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    dem, tags = load_tiff(DATA / "tpdc07_dem" / "dem_core_30m.tif")
    slope, _ = load_tiff(DATA / "tpdc07_dem" / "slope_deg.tif")
    gj = json.loads((DATA / "tpdc06_points" / "tpdc06_points.geojson").read_text(encoding="utf-8"))
    west, north, sx, sy = grid(tags)
    rows = []
    for factor in [1, 2, 3]:
        if factor == 1:
            d, s = dem.astype(float), slope.astype(float)
        else:
            d = np.asarray(Image.fromarray(dem.astype("float32")).resize((dem.shape[1] // factor, dem.shape[0] // factor), Image.Resampling.BILINEAR))
            s = np.asarray(Image.fromarray(slope.astype("float32")).resize((slope.shape[1] // factor, slope.shape[0] // factor), Image.Resampling.BILINEAR))
        for feature in gj["features"]:
            mask = rasterize(feature, d.shape[0], d.shape[1], west, north, sx * factor, sy * factor)
            if mask.sum() == 0:
                continue
            z = d[mask]
            sl = s[mask]
            rows.append(
                {
                    "scale_m": 30 * factor,
                    "id": feature.get("id"),
                    "cells": int(mask.sum()),
                    "G1_slope_mean": float(np.nanmean(sl)),
                    "G2_slope_p90": float(np.nanpercentile(sl, 90)),
                    "G3_relief_m": float(np.nanmax(z) - np.nanmin(z)),
                    "G4_HI": float((np.nanmean(z) - np.nanmin(z)) / (np.nanmax(z) - np.nanmin(z))),
                }
            )
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "q2_scale_sensitivity_raw.csv", index=False, encoding="utf-8-sig")
    summary = df.groupby("scale_m")[["G1_slope_mean", "G2_slope_p90", "G3_relief_m", "G4_HI"]].agg(["mean", "std", "min", "max"]).reset_index()
    summary.columns = ["_".join([c for c in col if c]).strip("_") if isinstance(col, tuple) else col for col in summary.columns]
    summary.to_csv(OUT / "q2_scale_sensitivity.csv", index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
