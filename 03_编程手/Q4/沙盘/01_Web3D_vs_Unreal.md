# Web 3D 与 Unreal 的差别、耗费与组合方案

> 目的：回答“方案 A（Three.js）和方案 C（Unreal）能不能综合、差多少、要多少人天”。

---

## 0. 先给结论

**能综合，而且推荐“一个物理后端 + 两个渲染端”：**

```
Python Q4/Q3 求解器
  → 统一帧数据（地形、h、|u|、b_dep、预警时间线）
      ├─ Web/Three.js：交互分析沙盘（参数扫描、图层、剖面、预警）
      └─ Unreal：电影级回放/汇报（同一场景、同一帧数据）
```

**不建议一上来就用 Unreal 做“唯一”的交互沙盘。** Unreal 不是泥石流物理 solver；它只换渲染器，Q4 的 HLL/Voellmy 仍然要写。先做 Web 交互端，再用 Unreal 做“选定情景的 cinematic renderer”，风险和成本最低。

---

## 1. 差别

| 维度 | A. Web/Three.js | C. Unreal 5 + Pixel Streaming |
|---|---|---|
| 画面 | 干净的科学可视化；材质/光照/植被弱 | 电影级：Lumen/Nanite/ Niagara/体积雾 |
| 交互 | 浏览器原生，参数/图层/剖面改起来快 | 画面强，但 UI/数据联动要额外写 UMG/WebSocket |
| 地理坐标 | 本地 DEM 直接建 mesh；不做全球底图 | Cesium for Unreal 可真实经纬度；需 3D Tiles/heightmap |
| 物理 | 不负责物理，接 Python 帧 | 也不负责泥石流物理；Niagara 只是视觉粒子 |
| 建筑/道路 | 需 glTF/GeoJSON 资产；弱 | 强，但需要建模/资产管线 |
| 部署 | 静态文件或 FastAPI，任何人打开链接 | 需要 GPU 服务器 + Pixel Streaming 信令 + WebRTC |
| 硬件 | 普通笔记本 WebGL2 | 编辑 RTX 3060+；串流 RTX 4080/4090 级 |
| 开发速度 | 快，天级迭代 | 慢，周级迭代；材质/光照/打包都耗时 |
| 免费程度 | Three.js MIT、Python/FastAPI 免费 | UE5 免费（超 $1M 收入有 5% royalty）；Cesium for Unreal 免费；Ion 商业 token 可能收费 |
| 适合 | 科研分析、参数敏感、内部推演 | 汇报、公众展示、沉浸式演示 |

---

## 2. 耗费（按一个人、已有数据估算）

### A. Web 3D

| 阶段 | 内容 | 人天 |
|---|---|---:|
| v0.1 | DEM 地形 + 主沟 + 冰川 + 事件 marker + 时间轴 | 2–3 |
| v1.0 | Q4 帧接入、参数面板、剖面、图层、预警时间线 | 5–8 |
| v1.1 | 建筑/道路 glTF、导出视频/报告、部署 | 3–5 |
| **合计** | 可用的交互沙盘 | **10–16 人天** |

### C. Unreal

| 阶段 | 内容 | 人天 |
|---|---|---:|
| 环境 | UE5、Cesium for Unreal、Pixel Streaming、GPU 环境 | 2–3 |
| 地形 | DEM → Landscape/Heightmap 或 Cesium 地形；材质 | 2–4 |
| 场景 | 主沟、冰川、口岸、道路；基础资产 | 3–5 |
| 流场 | 帧数据 → 纹理/顶点动画/Niagara；时间轴 | 3–5 |
| 光影 | Lumen/后期/体积雾/镜头 | 2–4 |
| 串流 | Pixel Streaming 打包、信令、Web 前端嵌入 | 3–5 |
| 建筑级 | OSM/测绘建筑、道路、植被（如需要） | 5–15 |
| **合计** | 电影级单场景（不含建筑级） | **15–26 人天** |
| **合计** | 建筑/街道级 | **25–45+ 人天** |

### 组合

| 组合 | 内容 | 人天 |
|---|---|---:|
| **A + C（离线渲染）** | Web 交互沙盘 + Unreal 对选定情景出片 | **18–28** |
| **A + C（实时 Pixel Streaming）** | Web UI 控制 Unreal 实时渲染 | **25–40** |

> 以上不含 Q4 求解器开发（另计 5–10 人天）和建筑资产制作。

---

## 3. 三种“综合”方式

### 方式 1：一个后端 + 两个渲染端（推荐）

- Python 求解器输出统一帧（`h/u/b_dep`）；
- Web 端读帧做交互分析；
- Unreal 端读同一帧做电影级回放；
- 不需要实时耦合，稳定、便宜、可复现。

### 方式 2：Web UI + Unreal Pixel Streaming（真·实时）

- 浏览器只收视频，Unreal 在 GPU 服务器跑；
- Web 控件通过 WebSocket 发参数；
- 优点：画面最好且浏览器可看；
- 缺点：GPU 服务器、延迟、打包/信令/并发，维护成本高。

### 方式 3：Unreal 桌面 + WebView UI

- 本地 GPU 跑 Unreal，内嵌 Web UI；
- 简单，但不能分享链接；适合本地汇报。

---

## 4. 免费工具链（不付费能接的）

- **Three.js**（MIT）、**Vite**、**FastAPI**、**Python**：全免费。
- **QGIS**：DEM/GeoJSON 预处理、切片、检查。
- **Blender**：建筑/地形/冰川资产；glTF 导出。
- **Unreal Engine 5**：个人/小团队免费；注意 royalty 条款。
- **Cesium for Unreal**：免费插件；Cesium Ion 有免费额度，商业/高精度资产可能收费。
- **OBS Studio**：录演示视频。
- **MeshLab/CloudCompare**：点云/地形检查。

**不免费/慎用**：Google 3D Tiles、商业正射影像、Cesium Ion 高配额、Unreal 官方高质量建筑资产包（部分付费）。

---

## 5. 我的建议

1. **先做 A 的 v0.1**（2–3 天）：DEM 地形 + 主沟 + 冰川 + 事件 marker + Q3 预警时间线；不需要你接任何付费工具。
2. **接 Q4 求解器**（5–10 天）：2D HLL/Voellmy 出 `h/u/b_dep` 帧；Web 参数面板。
3. **再决定 Unreal**：
   - 如果只是汇报/视频：用 Unreal 做 **离线 cinematic**，同一帧数据，2–4 天出片；
   - 如果要浏览器实时电影级：再上 **Pixel Streaming + GPU 服务器**，额外 1–2 周。
4. **建筑/街道级**只在拿到建筑/道路/影像后再做；当前 30 m DEM 不做“每栋楼”。

---

## 6. 需要你确认

1. 你更看重 **交互分析** 还是 **汇报画面**？
2. 有没有 **NVIDIA GPU（RTX 3060+）** 的 Windows 机器？有的话 Unreal 本地可跑；没有就只能云 GPU 或放弃实时串流。
3. 是否需要 **浏览器分享链接**？需要 → Pixel Streaming；不需要 → Unreal 桌面/离线出片即可。
4. 能否接 **建筑/道路/正射影像/5–10 m DEM**？没有就按山谷尺度做。

---

*一句话：Web 是“能改参数、能分析”的沙盘；Unreal 是“好看、能汇报”的渲染器。两者共用一个物理后端，不要各写一套。*
