from __future__ import annotations

import json
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "实验结果"
WEB = BASE / "沙盘" / "web" / "data"
WEB.mkdir(parents=True, exist_ok=True)


def main():
    dom = np.load(OUT / "q4_domain.npz")
    fr = np.load(OUT / "q4_frames_s5_60.npz")
    s = dom["s_km"].astype(float)
    h = fr["h"]
    u = fr["u"]
    t = fr["t"]
    frames = []
    for i in range(len(t)):
        hm = h[i].max(axis=1)
        um = u[i].max(axis=1)
        wet = np.where(hm >= 0.2)[0]
        front = float(s[wet.max()]) if len(wet) else 0.0
        frames.append({
            "t": float(t[i]),
            "front_km": front,
            "h": [round(float(v), 3) for v in hm],
            "u": [round(float(v), 3) for v in um],
        })
    meta = {
        "scenario": "S5",
        "grid_m": 60,
        "half_width_km": 0.3,
        "V0": 3e5,
        "C_v": 0.45,
        "mu": 0.05,
        "xi": 300,
        "source": "Q4 2D HLL + Voellmy, t_end=1800s",
        "note": "数值走廊半宽 0.3 km；不是 1.5 km 全走廊；2026 仅量级参考，不反演",
    }
    obj = {"meta": meta, "s_km": [round(float(v), 4) for v in s], "frames": frames}
    (WEB / "q4_frames.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"frames": len(frames), "s_points": len(s), "front_max": max(f["front_km"] for f in frames), "size_kb": round((WEB / 'q4_frames.json').stat().st_size / 1024, 1)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
