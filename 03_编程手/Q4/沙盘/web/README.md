# 吉隆沟 3D 推演沙盘 v0.2

> 技术栈：Three.js + 原生 ES modules + 本地 DEM 数据
> 状态：**v0.2 地形/沟道/冰川/Q3 预警 + Q4 60 m S5 帧 + 快速预览**
> Q4 帧是 2D HLL/Voellmy 首轮结果（μ=0.05），**未通过网格收敛/2026 量级一致性**；不是 2026 官方复现。

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
- **Q4 60 米 S5 帧**（2D HLL/Voellmy，μ=0.05）：时间轴播放，数据源标“Q4 60 米帧”；
- 关闭“使用 Q4 帧”后：释放体积 V0、Voellmy 摩擦/湍流系数滑杆的快速预览；
- 外采驱动图：站点/ERA5/NASA/CHIRPS 累计降水；
- 数据来源折叠卡：附件 TPDC-01..08、外采 Open-Meteo/NASA/CHIRPS/Copernicus 元数据、Q2/Q3/Q4 模型输出；
- 灾害参数：最大水深、平均水深、最大流速、峰值动压、影响距离、锋面速度；
- 灾害面沿沟道推进、时间轴播放/暂停/倍速、水深纵剖面；
- 图层开关、电影巡航、复制链接。

## 数据来源

| 类别 | 内容 | 用途 |
|---|---|---|
| 附件 | TPDC-01/02 气象；TPDC-03/04 冰川；TPDC-05 土地覆盖；TPDC-06 历史沟域；TPDC-07 DEM/沟道；TPDC-08 人口 | 地形、沟道、冰川、背景、暴露 |
| 外采 | Open-Meteo archive、NASA POWER、CHIRPS 日值 | Q3 降雨/土壤驱动、沙盘外采曲线 |
| 外采 | Copernicus S1/S2 **仅元数据**（各 10 景 bbox） | 数据治理/候选核查；**未下载影像** |
| 模型 | Q2 WOE、Q3 A+C、Q4 2D HLL/Voellmy | 易发性/预警/情景帧 |

> Copernicus 只取了元数据，没有 SAR/光学像素；沙盘不能声称“用了卫星影像”。若要叠加真实影像，需要提供已下载的 S1/S2 产品或账号下载后的本地文件。

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
