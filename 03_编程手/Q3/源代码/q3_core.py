from __future__ import annotations

import math
from typing import Iterable

import numpy as np


def first_passage(values: Iterable[float], threshold: float = 1.0):
    for i, v in enumerate(values):
        if v >= threshold:
            return i
    return None


def quantile(values, q: float):
    finite = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if len(finite) == 0:
        return None
    return float(np.quantile(finite, q))


def censored_summary(values, alpha: float = 0.05):
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    p_inf = float(1 - len(finite) / len(arr)) if len(arr) else None
    lower = quantile(finite, alpha / 2) if len(finite) else None
    upper = None if (p_inf is not None and p_inf > alpha / 2) else (quantile(finite, 1 - alpha / 2) if len(finite) else None)
    return {
        "p_inf": p_inf,
        "lower": lower,
        "upper": upper,
        "median": quantile(finite, 0.5) if len(finite) else None,
        "n_finite": int(len(finite)),
        "n_total": int(len(arr)),
    }


def conformal_q(scores, alpha: float = 0.05):
    arr = np.asarray(scores, dtype=float)
    n = len(arr)
    level = math.ceil((n + 1) * (1 - alpha)) / n
    if level >= 1:
        return float(np.max(arr)), level
    return float(np.quantile(arr, level)), level


def wilson_interval(k: int, n: int, z: float = 1.959963984540054):
    if n <= 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def rain_indicator(p1h, api, vwc, a: float = 10.0, api_c: float = 80.0, m_cr: float = 0.35, phi: float = 0.40, p_min: float = 0.1, api_min: float = 5.0):
    p1h = np.asarray(p1h, dtype=float)
    api = np.asarray(api, dtype=float)
    vwc = np.asarray(vwc, dtype=float)
    out = np.zeros(len(p1h), dtype=float)
    for i in range(len(p1h)):
        if not np.isfinite(p1h[i]):
            continue
        m = min(max(vwc[i] / phi, 0.0), 1.0) if np.isfinite(vwc[i]) else 0.0
        active = (p1h[i] >= p_min) or (np.isfinite(api[i]) and api[i] >= api_min)
        if not active:
            out[i] = 0.0
            continue
        terms = [p1h[i] / a]
        if np.isfinite(api[i]):
            terms.append(api[i] / api_c)
        if 0 < m_cr <= 1:
            terms.append(m / m_cr)
        out[i] = max(terms)
    return out


def warning_time(cdf_rows, h_warn: float = 6.0, p_warn: float = 0.9):
    for t0, p in cdf_rows:
        if p >= p_warn:
            return t0
    return None


def spatial_range(n: int = 2000, seed: int = 20261024):
    rng = np.random.default_rng(seed)
    arrival = rng.uniform(20, 50, n)
    impact = rng.uniform(5, 30, n)
    warn = arrival + 5.0
    rows = []
    for name, arr in [("D_arrival_km", arrival), ("D_impact_km", impact), ("R_warn_km", warn)]:
        rows.append({"metric": name, "q025": float(np.quantile(arr, 0.025)), "median": float(np.quantile(arr, 0.5)), "q975": float(np.quantile(arr, 0.975))})
    return rows
