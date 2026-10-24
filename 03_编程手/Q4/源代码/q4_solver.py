from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "Q2" / "源代码"))
from q4_core import G, H_MIN, density, hll_flux_1d  # noqa: E402
from q2_geometry import DATA, grid, load_tiff  # noqa: E402

BASE = HERE.parents[2]
OUT = BASE / "03_编程手" / "Q4" / "实验结果"
OUT.mkdir(parents=True, exist_ok=True)


@dataclass
class Corridor:
    b: np.ndarray
    x: np.ndarray
    z: np.ndarray
    s_km: np.ndarray
    n_km: np.ndarray
    dx: float
    source: np.ndarray
    mask: np.ndarray


def sample_dem(dem, tags, x, z):
    west, north, sx, sy = grid(tags)
    rows, cols = dem.shape
    dx_km = abs(sx) * 111.320 * math.cos(math.radians(north - rows * sy / 2))
    dy_km = abs(sy) * 110.574
    width = (cols - 1) * dx_km
    depth = (rows - 1) * dy_km
    i = (x / width + 0.5) * (cols - 1)
    j = (z / depth + 0.5) * (rows - 1)
    i0 = np.clip(np.floor(i).astype(int), 0, cols - 2)
    j0 = np.clip(np.floor(j).astype(int), 0, rows - 2)
    fi = np.clip(i - i0, 0, 1)
    fj = np.clip(j - j0, 0, 1)
    v00 = dem[j0, i0]
    v01 = dem[j0, i0 + 1]
    v10 = dem[j0 + 1, i0]
    v11 = dem[j0 + 1, i0 + 1]
    return (v00 * (1 - fi) * (1 - fj) + v01 * fi * (1 - fj) + v10 * (1 - fi) * fj + v11 * fi * fj)


def build_corridor(ds: int = 1, half_width_km: float = 1.5, dx: float = 30.0) -> Corridor:
    dem, tags = load_tiff(DATA / "tpdc07_dem" / "dem_core_30m.tif")
    profile = pd.read_csv(DATA / "tpdc07_channel" / "main_channel_profile.csv")
    profile = profile.iloc[::ds].reset_index(drop=True)
    lon0 = float(tags[33922][3]) + dem.shape[1] * float(tags[33550][0]) / 2
    lat0 = float(tags[33922][4]) - dem.shape[0] * float(tags[33550][1]) / 2
    xs = (profile["lon"].to_numpy() - lon0) * 111.320 * math.cos(math.radians(lat0))
    zs = -(profile["lat"].to_numpy() - lat0) * 110.574
    s_km = profile["distance_m"].to_numpy() / 1000.0
    # tangent/normal
    tx = np.gradient(xs)
    tz = np.gradient(zs)
    tn = np.hypot(tx, tz)
    tx = tx / np.maximum(tn, 1e-9)
    tz = tz / np.maximum(tn, 1e-9)
    nx, nz = -tz, tx
    n_cells = int(round(2 * half_width_km * 1000 / dx)) + 1
    n_km = (np.arange(n_cells) - (n_cells - 1) / 2) * dx / 1000
    X = xs[:, None] + nx[:, None] * n_km[None, :]
    Z = zs[:, None] + nz[:, None] * n_km[None, :]
    b = sample_dem(dem, tags, X, Z)
    mask = np.ones_like(b, dtype=bool)
    # source: one cross-row of 56 central cells, area ~50,400 m2
    center = n_cells // 2
    source = np.zeros_like(mask)
    target_cells = max(6, int(round(50000.0 / (dx * dx))))
    n_cols = min(n_cells, max(3, int(round(math.sqrt(target_cells)))))
    n_rows = max(1, int(math.ceil(target_cells / n_cols)))
    c0 = max(0, center - n_cols // 2)
    c1 = min(n_cells, c0 + n_cols)
    r1 = min(mask.shape[0], n_rows)
    source[0:r1, c0:c1] = True
    return Corridor(b=b, x=X, z=Z, s_km=s_km, n_km=n_km, dx=dx, source=source, mask=mask)


def hll_x(h, hu, hv, g=G):
    """Interfaces along axis 0; returns Fh,Fhu,Fhv shape (N-1,M)."""
    hp = np.vstack([h[0], h, h[-1]])
    up = np.vstack([hu[0], hu, hu[-1]])
    vp = np.vstack([hv[0], hv, hv[-1]])
    return _hll_iface(hp[:-1], up[:-1], vp[:-1], hp[1:], up[1:], vp[1:], g)


def hll_y(h, hu, hv, g=G):
    hp = np.hstack([h[:, 0:1], h, h[:, -1:]])
    up = np.hstack([hu[:, 0:1], hu, hu[:, -1:]])
    vp = np.hstack([hv[:, 0:1], hv, hv[:, -1:]])
    # normal velocity is v (hv); tangential is u (hu)
    return _hll_iface(hp[:, :-1], vp[:, :-1], up[:, :-1], hp[:, 1:], vp[:, 1:], up[:, 1:], g)


def _hll_iface(hL, huL, hvL, hR, huR, hvR, g=G):
    hL = np.maximum(hL, 0.0)
    hR = np.maximum(hR, 0.0)
    uL = np.where(hL > H_MIN, huL / np.maximum(hL, H_MIN), 0.0)
    uR = np.where(hR > H_MIN, huR / np.maximum(hR, H_MIN), 0.0)
    vL = np.where(hL > H_MIN, hvL / np.maximum(hL, H_MIN), 0.0)
    vR = np.where(hR > H_MIN, hvR / np.maximum(hR, H_MIN), 0.0)
    FLh = hL * uL
    FLu = hL * uL * uL + 0.5 * g * hL * hL
    FLv = hL * uL * vL
    FRh = hR * uR
    FRu = hR * uR * uR + 0.5 * g * hR * hR
    FRv = hR * uR * vR
    SL = np.minimum(uL - np.sqrt(g * hL), uR - np.sqrt(g * hR))
    SR = np.maximum(uL + np.sqrt(g * hL), uR + np.sqrt(g * hR))
    den = np.where(np.abs(SR - SL) > 1e-12, SR - SL, 1.0)
    Fh = (SR * FLh - SL * FRh + SL * SR * (hR - hL)) / den
    Fu = (SR * FLu - SL * FRu + SL * SR * (hR * uR - hL * uL)) / den
    Fv = (SR * FLv - SL * FRv + SL * SR * (hR * vR - hL * vL)) / den
    Fh = np.where(SL >= 0, FLh, np.where(SR <= 0, FRh, Fh))
    Fu = np.where(SL >= 0, FLu, np.where(SR <= 0, FRu, Fu))
    Fv = np.where(SL >= 0, FLv, np.where(SR <= 0, FRv, Fv))
    dry = (hL <= H_MIN) & (hR <= H_MIN)
    Fh[dry] = 0.0; Fu[dry] = 0.0; Fv[dry] = 0.0
    return Fh, Fu, Fv


def flux_rhs(h, hu, hv, b, dx, g=G):
    Fx = hll_x(h, hu, hv, g)
    Fy = hll_y(h, hu, hv, g)
    # closed upstream / sides
    Fxh = Fx[0].copy(); Fxu = Fx[1].copy(); Fxv = Fx[2].copy()
    # solid walls: zero mass flux, pressure momentum flux (not zero flux)
    Fxh[0, :] = 0.0; Fxu[0, :] = 0.5 * g * h[0, :] ** 2; Fxv[0, :] = 0.0
    Fyh = Fy[0].copy(); Fyv = Fy[1].copy(); Fyu = Fy[2].copy()
    Fyh[:, 0] = 0.0; Fyv[:, 0] = 0.5 * g * h[:, 0] ** 2; Fyu[:, 0] = 0.0
    Fyh[:, -1] = 0.0; Fyv[:, -1] = 0.5 * g * h[:, -1] ** 2; Fyu[:, -1] = 0.0
    dh = -(Fxh[1:] - Fxh[:-1]) / dx - (Fyh[:, 1:] - Fyh[:, :-1]) / dx
    dhu = -(Fxu[1:] - Fxu[:-1]) / dx - (Fyu[:, 1:] - Fyu[:, :-1]) / dx
    dhv = -(Fxv[1:] - Fxv[:-1]) / dx - (Fyv[:, 1:] - Fyv[:, :-1]) / dx
    # bed slope central difference
    dbdx = np.zeros_like(b); dbdy = np.zeros_like(b)
    dbdx[1:-1, :] = (b[2:, :] - b[:-2, :]) / (2 * dx)
    dbdy[:, 1:-1] = (b[:, 2:] - b[:, :-2]) / (2 * dx)
    hpos = np.maximum(h, 0.0)
    dhu += -g * hpos * dbdx
    dhv += -g * hpos * dbdy
    return dh, dhu, dhv, Fxh[-1]


def simulate(cor: Corridor, V0: float = 3e5, cv: float = 0.45, mu: float = 0.15, xi: float = 300.0,
             t_end: float = 1800.0, frame_every: float = 60.0, cfl: float = 0.25, c_dep: float = 0.03,
             u_stop: float = 1.0, max_speed: float = 60.0):
    rho = density(cv)
    h = np.zeros_like(cor.b, dtype=float)
    cell_area = cor.dx * cor.dx
    n_src = int(cor.source.sum())
    h0 = V0 / (n_src * cell_area)
    h[cor.source] = h0
    hu = np.zeros_like(h)
    hv = np.zeros_like(h)
    b = cor.b.astype(float)
    b_dep = np.zeros_like(h)
    t_arr = np.full_like(h, np.inf)
    h_max = h.copy()
    u_max = np.zeros_like(h)
    outflow = 0.0
    t = 0.0
    frames = []
    mass0 = float(h.sum() * cell_area)
    next_frame = 0.0
    steps = 0
    while t < t_end:
        hh = np.maximum(h, 0.0)
        uu = np.where(hh > H_MIN, hu / np.maximum(hh, H_MIN), 0.0)
        vv = np.where(hh > H_MIN, hv / np.maximum(hh, H_MIN), 0.0)
        speed = np.hypot(uu, vv)
        wave = np.sqrt(G * hh) + speed
        dt = cfl * cor.dx / max(float(np.max(wave)), 1e-6)
        dt = min(dt, 2.0, t_end - t)
        # SSP-RK2 flux + bed
        k1 = flux_rhs(hh, hu, hv, b, cor.dx)
        h1 = hh + dt * k1[0]
        hu1 = hu + dt * k1[1]
        hv1 = hv + dt * k1[2]
        h1 = np.maximum(h1, 0.0)
        hu1 = np.where(h1 > H_MIN, hu1, 0.0)
        hv1 = np.where(h1 > H_MIN, hv1, 0.0)
        k2 = flux_rhs(h1, hu1, hv1, b, cor.dx)
        h2 = 0.5 * hh + 0.5 * (h1 + dt * k2[0])
        hu2 = 0.5 * hu + 0.5 * (hu1 + dt * k2[1])
        hv2 = 0.5 * hv + 0.5 * (hv1 + dt * k2[2])
        # outflow from downstream interface of the second stage
        outflow += float(np.sum(np.maximum(k2[3], 0.0)) * dt * cor.dx)
        h = np.maximum(h2, 0.0)
        hu = np.where(h > H_MIN, hu2, 0.0)
        hv = np.where(h > H_MIN, hv2, 0.0)
        # friction semi-implicit
        speed = np.hypot(np.where(h > H_MIN, hu / np.maximum(h, H_MIN), 0.0),
                         np.where(h > H_MIN, hv / np.maximum(h, H_MIN), 0.0))
        dbdx = np.zeros_like(b); dbdy = np.zeros_like(b)
        dbdx[1:-1, :] = (b[2:, :] - b[:-2, :]) / (2 * cor.dx)
        dbdy[:, 1:-1] = (b[:, 2:] - b[:, :-2]) / (2 * cor.dx)
        cos_t = 1.0 / np.sqrt(1.0 + dbdx * dbdx + dbdy * dbdy)
        coef = G * mu * cos_t / np.maximum(speed, 0.1) + G * speed / np.maximum(xi * h, 1e-6)
        fac = 1.0 / (1.0 + dt * coef)
        hu *= fac
        hv *= fac
        # speed cap
        sp2 = np.hypot(np.where(h > H_MIN, hu / np.maximum(h, H_MIN), 0.0),
                       np.where(h > H_MIN, hv / np.maximum(h, H_MIN), 0.0))
        cap = np.where(sp2 > max_speed, max_speed / np.maximum(sp2, 1e-9), 1.0)
        hu *= cap; hv *= cap
        # deposition
        uu = np.where(h > H_MIN, hu / np.maximum(h, H_MIN), 0.0)
        vv = np.where(h > H_MIN, hv / np.maximum(h, H_MIN), 0.0)
        speed = np.hypot(uu, vv)
        dep = np.where(speed < u_stop, c_dep * h * np.maximum(0.0, 1.0 - speed / u_stop), 0.0)
        dep = np.minimum(dep * dt, 0.5 * h)
        h -= dep
        b_dep += dep
        b += dep
        # dry / NaN guard
        bad = ~np.isfinite(h) | ~np.isfinite(hu) | ~np.isfinite(hv)
        if bad.any():
            h[bad] = 0.0; hu[bad] = 0.0; hv[bad] = 0.0
        h = np.maximum(h, 0.0)
        hu = np.where(h > H_MIN, hu, 0.0)
        hv = np.where(h > H_MIN, hv, 0.0)
        uu = np.where(h > H_MIN, hu / np.maximum(h, H_MIN), 0.0)
        vv = np.where(h > H_MIN, hv / np.maximum(h, H_MIN), 0.0)
        speed = np.hypot(uu, vv)
        newly = (h >= 0.2) & ~np.isfinite(t_arr)
        t_arr[newly] = t
        h_max = np.maximum(h_max, h)
        u_max = np.maximum(u_max, speed)
        t += dt
        steps += 1
        if t >= next_frame - 1e-9:
            frames.append({"t": float(t), "h": h.astype("float32"), "u": speed.astype("float32"), "front_km": front_distance(cor, h)})
            next_frame += frame_every
        if steps % 200 == 0:
            print(f"t={t:7.1f}s steps={steps} maxh={h.max():.2f} maxu={speed.max():.2f} mass_err={abs((h.sum()*cell_area + b_dep.sum()*cell_area + outflow)-mass0)/mass0:.4%}", flush=True)
    mass1 = float(h.sum() * cell_area)
    dep_mass = float(b_dep.sum() * cell_area)
    return {
        "h": h, "hu": hu, "hv": hv, "u": np.hypot(np.where(h > H_MIN, hu / np.maximum(h, H_MIN), 0), np.where(h > H_MIN, hv / np.maximum(h, H_MIN), 0)),
        "us": np.where(h > H_MIN, hu / np.maximum(h, H_MIN), 0.0),
        "vs": np.where(h > H_MIN, hv / np.maximum(h, H_MIN), 0.0),
        "b_dep": b_dep, "t_arr": t_arr, "h_max": h_max, "u_max": u_max,
        "mass0": mass0, "mass_flow": mass1, "mass_dep": dep_mass, "outflow": outflow,
        "mass_err": abs((mass1 + dep_mass + outflow) - mass0) / mass0,
        "frames": frames, "steps": steps, "h0": h0, "n_source": n_src,
    }


def front_distance(cor: Corridor, h: np.ndarray, threshold: float = 0.2) -> float:
    wet = (h >= threshold).any(axis=1)
    if not wet.any():
        return 0.0
    return float(cor.s_km[np.where(wet)[0].max()])


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dx", type=int, default=30, choices=[30, 60, 90])
    ap.add_argument("--t-end", type=float, default=1800.0)
    ap.add_argument("--tag", default="s0")
    ap.add_argument("--v0", type=float, default=3e5)
    ap.add_argument("--cv", type=float, default=0.45)
    ap.add_argument("--mu", type=float, default=0.15)
    ap.add_argument("--xi", type=float, default=300.0)
    ap.add_argument("--hw", type=float, default=0.3, help="numerical corridor half-width km")
    args = ap.parse_args()
    cor = build_corridor(ds=max(1, args.dx // 30), half_width_km=args.hw, dx=float(args.dx))
    print("corridor", cor.b.shape, "dx", cor.dx, "source", int(cor.source.sum()), "h range", float(cor.b.min()), float(cor.b.max()))
    res = simulate(cor, V0=args.v0, cv=args.cv, mu=args.mu, xi=args.xi, t_end=args.t_end, frame_every=60)
    np.savez_compressed(
        OUT / "q4_domain.npz",
        b=cor.b.astype("float32"), x=cor.x.astype("float32"), z=cor.z.astype("float32"),
        s_km=cor.s_km.astype("float32"), n_km=cor.n_km.astype("float32"), source=cor.source,
    )
    np.savez_compressed(
        OUT / f"q4_result_{args.tag}.npz",
        h=res["h"].astype("float32"), u=res["u"].astype("float32"), b_dep=res["b_dep"].astype("float32"),
        t_arr=res["t_arr"].astype("float32"), h_max=res["h_max"].astype("float32"), u_max=res["u_max"].astype("float32"),
    )
    frames_h = np.stack([f["h"] for f in res["frames"]])
    frames_u = np.stack([f["u"] for f in res["frames"]])
    frame_t = np.asarray([f["t"] for f in res["frames"]], dtype="float32")
    np.savez_compressed(OUT / f"q4_frames_{args.tag}.npz", t=frame_t, h=frames_h, u=frames_u)
    mass = pd.DataFrame([{
        "scenario": args.tag, "V0": args.v0, "C_v": args.cv, "mu": args.mu, "xi": args.xi, "grid_m": args.dx,
        "mass0": res["mass0"], "mass_flow": res["mass_flow"], "mass_dep": res["mass_dep"],
        "outflow": res["outflow"], "mass_err": res["mass_err"], "steps": res["steps"],
        "h0": res["h0"], "source_cells": res["n_source"],
    }])
    mass.to_csv(OUT / f"q4_mass_balance_{args.tag}.csv", index=False, encoding="utf-8-sig")
    summary = {
        args.tag: {"mass_err": res["mass_err"], "max_h": float(res["h"].max()), "max_u": float(res["u"].max()),
                   "front_km": front_distance(cor, res["h"]), "steps": res["steps"], "h0": res["h0"]},
        "domain": {"shape": list(cor.b.shape), "dx_m": cor.dx, "source_cells": int(cor.source.sum())},
    }
    (OUT / f"q4_summary_{args.tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
