# 吉隆沟 3D 推演沙盘 v0.1

> 技术栈：Three.js + 原生 ES modules + 本地 DEM 数据
> 状态：**v0.1 地形/沟道/冰川/Q3 预警 + 快速情景预览**；尚未接 Q4 HLL/Voellmy 求解器。
> 这不是 Q4 验证结果；动画只用于交互和画面演示。

## 运行

```powershell
cd 03_编程手\Q4\沙盘
.\start_sandbox.ps1
```

或手动：

```powershell
cd 03_编程手\Q4\沙盘\web
python -m http.server 8765 --bind 127.0.0.1
```

浏览器打开：`http://127.0.0.1:8765/`

> 不要直接双击 `index.html`；浏览器会因 CORS 拒绝读取 `.bin` 数据。

## 当前功能

- 30 m DEM 4× 降采样地形，顶点色=高程/坡度；
- 主沟中心线（49.622 km）与源头/沟口/事件源区 marker；
- TPDC-04 冰川源区点云；
- Q3 2026/2025 条件预警时间线（H=6/p=0.9）；
- 快速情景预览：释放体积 V0、Voellmy μ/ξ 滑杆；
- 灾害面沿沟道推进、时间轴播放/暂停/倍速、水深纵剖面；
- 图层开关、电影巡航、复制链接。

## 分享链接

临时公网链接（免费、无需账号，机器要开着）：

```powershell
cloudflared tunnel --url http://127.0.0.1:8765
```

得到 `https://xxx.trycloudflare.com`。安装：

```powershell
winget install Cloudflare.cloudflared
```

稳定链接需要 Cloudflare 免费账号 + named tunnel，或把 `web/` 静态部署到 Cloudflare Pages/Netlify（只适合预计算场景）。

## 数据

`web/data/` 由 `export_sandbox.py` 生成：

- `manifest.json`：网格/范围/高程范围；
- `terrain.bin` / `slope.bin`：Float32 高度/坡度；
- `channel.json`：主沟 1470 点（x/z/y/距离）；
- `glacier_points.json`：冰川源区点；
- `sites.json`：源头/沟口/事件 marker；
- `q3.json`：Q3 预警/区间/案例。

重新生成：

```powershell
python export_sandbox.py
```

## 已知限制

1. 灾害面是 **快速情景预览**（V0/μ/ξ 的经验波前），不是 Q4 2D HLL/Voellmy 结果；
2. 没有建筑/道路/正射影像，只到山谷—沟道尺度；
3. 30 m DEM 对窄沟道偏粗；
4. Q3 是条件预测区间，不是事件级 95% 覆盖率；2026 集合有 4% 降雨分支；
5. 分享链接依赖本机服务器/隧道，不是永久托管。

## 下一步

1. 接 Q4 2D 求解器，替换 `updateHazard()` 的预览波前；
2. 帧数据缓存/流式加载，支持 12 组 Q4 情景；
3. 建筑/道路 glTF、正射影像、断面/影响统计；
4. 自动化截图/视频（Playwright + ffmpeg）。
