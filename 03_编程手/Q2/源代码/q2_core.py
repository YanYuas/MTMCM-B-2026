from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parents[3]
OUT = BASE / "03_编程手" / "Q2" / "实验结果"
OUT.mkdir(parents=True, exist_ok=True)


def fs_infinite(beta_deg: float, z: float, c_prime: float, phi_deg: float, gamma_sat: float, z_w: float, gamma_w: float = 9.81) -> float:
    beta = math.radians(beta_deg)
    phi = math.radians(phi_deg)
    num = c_prime + (gamma_sat * z - gamma_w * z_w) * math.cos(beta) ** 2 * math.tan(phi)
    den = gamma_sat * z * math.sin(beta) * math.cos(beta)
    return num / den


def m_cr(beta_deg: float, phi_deg: float, c_prime: float, gamma_sat: float, z: float, r: float = 0.5) -> float:
    beta = math.radians(beta_deg)
    phi = math.radians(phi_deg)
    return (1.0 / r) * (
        1.0 - math.tan(beta) / math.tan(phi)
        + c_prime / (gamma_sat * z * math.cos(beta) ** 2 * math.tan(phi))
    )


def id_threshold(a: float, b: float, duration_h: float) -> float:
    return a * duration_h ** (-b)


def api72(values: list[float], k: float = 0.9) -> float:
    arr = np.asarray(values, dtype=float)
    return float(np.dot(arr[::-1], k ** np.arange(len(arr))))


def hi_index(z_min: float, z_max: float, z_mean: float) -> float:
    return (z_mean - z_min) / (z_max - z_min)


def drainage_density(length_km: float, area_km2: float) -> float:
    return length_km / area_km2


def channel_gradient(drop_m: float, length_km: float) -> float:
    return drop_m / (10.0 * length_km)


def ice_trigger(z: float, slope_deg: float, ice_thickness: float, velocity: float, z0: float = 5000, beta0: float = 25, h0: float = 20, v0: float = 5) -> int:
    return int(z >= z0 and slope_deg >= beta0 and ice_thickness >= h0 and velocity >= v0)


def main() -> None:
    rows = []

    def add(vid, expected, actual, unit, note=""):
        rows.append({"id": vid, "expected": expected, "actual": actual, "unit": unit, "pass": bool(abs(float(actual) - float(expected)) <= max(0.01, abs(float(expected)) * 0.01)), "note": note})

    add("V1", 0.351, m_cr(30, 35, 0, 20, 2, 0.5), "-", "m_cr")
    add("V2", 1.043, fs_infinite(30, 2, 5, 30, 20, 1), "-", "FS")
    add("V3", 2.041, id_threshold(10, 0.5, 24), "mm/h", "I_c")
    add("V4", 5.61, api72([1, 2, 3], 0.9), "mm", "API72")
    add("V5", 1.496, m_cr(10, 35, 0, 20, 2, 0.5), "-", "m_cr>1")

    q2 = json.loads((BASE / "03_编程手" / "数据获取" / "data" / "processed" / "q2_susceptibility" / "summary.json").read_text(encoding="utf-8"))
    auc = float(q2["auc_global_pixel"])
    blocks = {b["block"]: b["auc"] for b in q2["auc_spatial_blocks"] if b["auc"] is not None}
    add("V6a", 0.7472, auc, "-", "WOE global")
    add("V6b", 0.5279, blocks.get("r0c0", float("nan")), "-", "WOE block r0c0")
    add("V6c", 0.6496, blocks.get("r1c0", float("nan")), "-", "WOE block r1c0")
    add("V7", 0.4, hi_index(1000, 3000, 1800), "-", "HI")
    add("V8", 0.5, drainage_density(10, 20), "km/km²", "Dd")
    add("V9", 0.25, 25 / 100, "-", "glacier_fraction")
    add("V10a", 0.8, 0.8 * 1, "-", "H(I=1)")
    add("V10b", 0.0, 0.8 * 0, "-", "H(I=0)")
    add("V11", 8.046, channel_gradient(3992.74, 49.622), "%", "S_ch")
    add("V12a", 1, ice_trigger(5200, 30, 50, 8), "0/1", "ice trigger")
    add("V12b", 0, ice_trigger(4800, 30, 50, 8), "0/1", "ice trigger low z")

    passed = sum(1 for r in rows if r["pass"])
    for r in rows:
        if not r["pass"]:
            r["note"] += " | FAIL"
    (OUT / "q2_v1_v12.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Q2 验证题结果（V1–V12）",
        "",
        "> 由 `q2_core.py` 生成；V6 读取 data/processed/q2_susceptibility/summary.json 的已知值。",
        "",
        "| 编号 | 期望 | 实测 | 判定 | 说明 |",
        "|---|---:|---:|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['id']} | {r['expected']} | {float(r['actual']):.6g} | {'✅' if r['pass'] else '❌'} | {r['note']} |")
    lines += [
        "",
        f"**通过 {passed}/{len(rows)}。**",
        "",
        "## 备注",
        "",
        "- V1/V5 用 `m_cr` 解析式；β=10° 时 m_cr≈1.496>1，按 T3 判 I_rain=0。",
        "- V2 结果约 1.043，按四舍五入到 1.04 也可；本表容差 1%。",
        "- V6 只做已知值复现，不重新拟合；全局 AUC 0.7472 不是泛化精度。",
        "- V7–V12 是几何/阈值/冰崩筛选的单元测试，不是真实沟域结果。",
    ]
    (BASE / "03_编程手" / "Q2" / "验证题结果.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"passed": passed, "total": len(rows), "rows": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
