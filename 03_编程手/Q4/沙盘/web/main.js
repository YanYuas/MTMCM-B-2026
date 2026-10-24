import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const app = $('app');
const labelLayer = $('labels');

const state = {
  manifest: null,
  channel: null,
  sites: [],
  q3: null,
  time: 0,
  duration: 1800,
  playing: false,
  speed: 1,
  scenario: '2026',
  useQ4: true,
  params: { V0: 3.0e5, mu: 0.15, xi: 300, sourceArea: 5.0e4 },
  frames: [],
  scene: null,
  camera: null,
  renderer: null,
  controls: null,
  terrain: null,
  channelLine: null,
  hazard: null,
  hazardGeo: null,
  frontMarker: null,
  labels: [],
  warningGroup: null,
  glacierPoints: null,
  stats: {},
  profileCtx: null,
};

const COLORS = {
  event: 0xff6b6b,
  outlet: 0xffc46b,
  source: 0x6fe7ff,
  terrainLow: new THREE.Color('#1d3327'),
  terrainMid: new THREE.Color('#6f6a4a'),
  terrainHigh: new THREE.Color('#d9e1e8'),
  steep: new THREE.Color('#8a6654'),
};

init();

async function init() {
  try {
    const [manifest, channel, sites, q3, glacier, q4] = await Promise.all([
      fetchJSON('./data/manifest.json'),
      fetchJSON('./data/channel.json'),
      fetchJSON('./data/sites.json'),
      fetchJSON('./data/q3.json'),
      fetchJSON('./data/glacier_points.json'),
      fetchJSON('./data/q4_frames.json').catch(() => null),
    ]);
    state.manifest = manifest;
    state.channel = channel;
    state.sites = sites;
    state.q3 = q3;
    state.glacierPoints = glacier;
    state.q4 = q4;

    const [terrainBuf, slopeBuf] = await Promise.all([
      fetchBin('./data/terrain.bin'),
      fetchBin('./data/slope.bin'),
    ]);
    const n = manifest.grid_shape[0] * manifest.grid_shape[1];
    if (terrainBuf.byteLength !== n * 4) throw new Error('terrain.bin 大小不匹配');
    const heights = new Float32Array(terrainBuf);
    const slopes = new Float32Array(slopeBuf);
    state.heights = heights;
    state.nx = manifest.grid_shape[1];
    state.ny = manifest.grid_shape[0];

    buildScene(heights, slopes);
    buildUI();
    updateQ3Panel();
    setScenario('2026', false);
    const qs = new URLSearchParams(location.search);
    if (qs.get('scenario') === '2025') setScenario('2025', false);
    const t0 = Number(qs.get('t'));
    if (Number.isFinite(t0) && t0 > 0) {
      state.time = Math.min(state.duration, t0);
      updateTime();
    }
    hideLoading();
    animate();
  } catch (err) {
    console.error(err);
    $('loading').innerHTML = `<div style="color:#ff9b9b">加载失败：${escapeHtml(err.message)}</div><div class="hint">请用本地 HTTP 服务器打开（不能直接双击 index.html）。</div>`;
  }
}

async function fetchJSON(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${url} ${res.status}`);
  return res.json();
}
async function fetchBin(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${url} ${res.status}`);
  return res.arrayBuffer();
}

function buildScene(heights, slopes) {
  const m = state.manifest;
  const ny = m.grid_shape[0], nx = m.grid_shape[1];
  const width = m.width_km, depth = m.depth_km;
  const zmin = m.z_min, zmax = m.z_max;
  const vscale = m.vertical_scale || 2.2;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#070b10');
  scene.fog = new THREE.FogExp2('#070b10', 0.0065);
  state.scene = scene;

  const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.1, 300);
  camera.position.set(38, 26, 38);
  state.camera = camera;

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setSize(innerWidth, innerHeight);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  app.appendChild(renderer.domElement);
  state.renderer = renderer;

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 6, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 4;
  controls.maxDistance = 130;
  controls.maxPolarAngle = Math.PI * 0.495;
  state.controls = controls;

  scene.add(new THREE.HemisphereLight(0x9fd8ff, 0x1b1510, 1.0));
  const sun = new THREE.DirectionalLight(0xfff1dd, 2.0);
  sun.position.set(-38, 50, 22);
  scene.add(sun);
  const rim = new THREE.DirectionalLight(0x6fe7ff, 0.6);
  rim.position.set(30, 18, -30);
  scene.add(rim);

  // terrain
  const positions = new Float32Array(nx * ny * 3);
  const colors = new Float32Array(nx * ny * 3);
  const c = new THREE.Color();
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const idx = j * nx + i;
      const x = (i / (nx - 1) - 0.5) * width;
      const z = (j / (ny - 1) - 0.5) * depth;
      const h = heights[idx];
      const y = ((h - zmin) / 1000) * vscale;
      positions[idx * 3] = x;
      positions[idx * 3 + 1] = y;
      positions[idx * 3 + 2] = z;
      const t = THREE.MathUtils.clamp((h - zmin) / (zmax - zmin), 0, 1);
      if (t < 0.5) c.copy(COLORS.terrainLow).lerp(COLORS.terrainMid, t / 0.5);
      else c.copy(COLORS.terrainMid).lerp(COLORS.terrainHigh, (t - 0.5) / 0.5);
      const sl = THREE.MathUtils.clamp((slopes[idx] || 0) / 55, 0, 1);
      c.lerp(COLORS.steep, Math.min(0.35, sl * 0.35));
      colors[idx * 3] = c.r; colors[idx * 3 + 1] = c.g; colors[idx * 3 + 2] = c.b;
    }
  }
  const indices = new Uint32Array((nx - 1) * (ny - 1) * 6);
  let p = 0;
  for (let j = 0; j < ny - 1; j++) {
    for (let i = 0; i < nx - 1; i++) {
      const a = j * nx + i, b = a + 1, c2 = a + nx, d = c2 + 1;
      indices[p++] = a; indices[p++] = c2; indices[p++] = b;
      indices[p++] = b; indices[p++] = c2; indices[p++] = d;
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geo.setIndex(new THREE.BufferAttribute(indices, 1));
  geo.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.96, metalness: 0.02, side: THREE.DoubleSide });
  const terrain = new THREE.Mesh(geo, mat);
  terrain.receiveShadow = false;
  scene.add(terrain);
  state.terrain = terrain;

  // subtle grid at base
  const grid = new THREE.GridHelper(80, 32, 0x123447, 0x0c1a24);
  grid.position.y = -0.15;
  grid.material.opacity = 0.18;
  grid.material.transparent = true;
  scene.add(grid);

  buildChannel();
  buildGlacier();
  buildSites();
  buildWarningRings();
  buildLabels();

  addEventListener('resize', onResize);
  renderer.domElement.addEventListener('pointerdown', () => { state.controls.autoRotate = false; });
}

function baseY(yMeters) {
  return ((yMeters - state.manifest.z_min) / 1000) * (state.manifest.vertical_scale || 2.2);
}

function terrainYAt(x, z) {
  const m = state.manifest;
  if (!state.heights) return 0;
  const nx = state.nx, ny = state.ny;
  const i = Math.max(0, Math.min(nx - 1, Math.round((x / m.width_km + 0.5) * (nx - 1))));
  const j = Math.max(0, Math.min(ny - 1, Math.round((z / m.depth_km + 0.5) * (ny - 1))));
  return baseY(state.heights[j * nx + i]);
}

function buildChannel() {
  const pts = state.channel.points;
  const stride = Math.max(1, Math.round(pts.length / 420));
  const sampled = [];
  for (let i = 0; i < pts.length; i += stride) sampled.push(pts[i]);
  if (sampled[sampled.length - 1] !== pts[pts.length - 1]) sampled.push(pts[pts.length - 1]);
  state.channel.sampled = sampled;

  const linePos = new Float32Array(sampled.length * 3);
  for (let i = 0; i < sampled.length; i++) {
    linePos[i * 3] = sampled[i].x;
    linePos[i * 3 + 1] = Math.max(baseY(sampled[i].y), terrainYAt(sampled[i].x, sampled[i].z)) + 0.16;
    linePos[i * 3 + 2] = sampled[i].z;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(linePos, 3));
  const line = new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0x6fe7ff, transparent: true, opacity: 0.9, depthTest: false }));
  line.renderOrder = 5;
  state.scene.add(line);
  state.channelLine = line;

  // hazard ribbon
  const n = sampled.length;
  const hPos = new Float32Array(n * 2 * 3);
  const hCol = new Float32Array(n * 2 * 3);
  const idx = new Uint32Array((n - 1) * 6);
  for (let i = 0; i < n - 1; i++) {
    const a = i * 2, b = a + 1, c = a + 2, d = a + 3;
    idx.set([a, c, b, b, c, d], i * 6);
  }
  const hg = new THREE.BufferGeometry();
  hg.setAttribute('position', new THREE.BufferAttribute(hPos, 3));
  hg.setAttribute('color', new THREE.BufferAttribute(hCol, 3));
  hg.setIndex(new THREE.BufferAttribute(idx, 1));
  hg.setDrawRange(0, 0);
  const hm = new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false, depthTest: false });
  const hazard = new THREE.Mesh(hg, hm);
  hazard.renderOrder = 10;
  hazard.frustumCulled = false;
  state.scene.add(hazard);
  state.hazard = hazard;
  state.hazardGeo = hg;
  hazard.visible = false;

  // Instanced ribbon is more robust than a dynamic indexed mesh in WebGL.
  const box = new THREE.BoxGeometry(1, 1, 1);
  const instMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, depthWrite: false, depthTest: false });
  const inst = new THREE.InstancedMesh(box, instMat, sampled.length);
  inst.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  inst.frustumCulled = false;
  inst.renderOrder = 10;
  inst.count = 0;
  const zero = new THREE.Color(0x000000);
  for (let i = 0; i < sampled.length; i++) inst.setColorAt(i, zero);
  state.scene.add(inst);
  state.hazardInst = inst;
  inst.visible = false;

  const hzGroup = new THREE.Group();
  hzGroup.renderOrder = 10;
  const unitBox = new THREE.BoxGeometry(1, 1, 1);
  for (let i = 0; i < sampled.length; i++) {
    const mat = new THREE.MeshBasicMaterial({ color: 0x3b7dff, transparent: true, opacity: 0.9, depthWrite: false, depthTest: false });
    const mesh = new THREE.Mesh(unitBox, mat);
    mesh.visible = false;
    mesh.renderOrder = 10;
    hzGroup.add(mesh);
  }
  state.scene.add(hzGroup);
  state.hazardGroup = hzGroup;
  state.hazard = hzGroup;

  const front = new THREE.Mesh(
    new THREE.SphereGeometry(0.22, 16, 12),
    new THREE.MeshBasicMaterial({ color: 0xbff8ff, transparent: true, opacity: 0.95, depthTest: false })
  );
  front.visible = false;
  front.renderOrder = 12;
  state.scene.add(front);
  state.frontMarker = front;
}

function buildGlacier() {
  const pts = state.glacierPoints;
  const arr = new Float32Array(pts.length * 3);
  for (let i = 0; i < pts.length; i++) {
    arr[i * 3] = pts[i].x;
    arr[i * 3 + 1] = baseY(5200) + 0.05;
    arr[i * 3 + 2] = pts[i].z;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(arr, 3));
  const m = new THREE.PointsMaterial({ color: 0x8ff3ff, size: 0.16, transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending });
  const p = new THREE.Points(g, m);
  state.scene.add(p);
  state.glacierPointsObj = p;
}

function buildSites() {
  for (const s of state.sites) {
    const color = s.kind === 'event' ? COLORS.event : s.kind === 'outlet' ? COLORS.outlet : COLORS.source;
    const geo = new THREE.ConeGeometry(0.22, 0.7, 8);
    const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95 });
    const pin = new THREE.Mesh(geo, mat);
    pin.position.set(s.x, Math.max(baseY(s.y), terrainYAt(s.x, s.z)) + 0.55, s.z);
    pin.rotation.x = Math.PI;
    state.scene.add(pin);
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.35, 0.42, 32),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.7, side: THREE.DoubleSide })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(s.x, Math.max(baseY(s.y), terrainYAt(s.x, s.z)) + 0.06, s.z);
    state.scene.add(ring);
  }
}

function buildWarningRings() {
  const group = new THREE.Group();
  const positions = [
    state.sites.find(s => s.kind === 'event'),
    state.sites.find(s => s.kind === 'outlet'),
  ].filter(Boolean);
  positions.forEach((s, i) => {
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(1.2, 1.3, 48),
      new THREE.MeshBasicMaterial({ color: i === 0 ? 0xff6b6b : 0xffc46b, transparent: true, opacity: 0.5, side: THREE.DoubleSide })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(s.x, Math.max(baseY(s.y), terrainYAt(s.x, s.z)) + 0.1, s.z);
    group.add(ring);
  });
  state.scene.add(group);
  state.warningGroup = group;
}

function buildLabels() {
  state.labels = state.sites.map(s => {
    const el = document.createElement('div');
    el.className = `label ${s.kind}`;
    el.textContent = s.name;
    labelLayer.appendChild(el);
    const pos = new THREE.Vector3(s.x, Math.max(baseY(s.y), terrainYAt(s.x, s.z)) + 1.15, s.z);
    return { el, pos, kind: s.kind, site: s };
  });
}

function updateLabels() {
  if (!state.labels.length) return;
  const v = new THREE.Vector3();
  const show = $('layer-labels').checked;
  for (const l of state.labels) {
    if (!show) { l.el.style.display = 'none'; continue; }
    v.copy(l.pos).project(state.camera);
    const inFront = v.z < 1 && v.z > -1;
    const x = (v.x * 0.5 + 0.5) * innerWidth;
    const y = (-v.y * 0.5 + 0.5) * innerHeight;
    const visible = inFront && x > 0 && x < innerWidth && y > 0 && y < innerHeight;
    l.el.style.display = visible ? 'block' : 'none';
    if (visible) {
      l.el.style.left = `${x}px`;
      l.el.style.top = `${y}px`;
      l.el.style.opacity = String(THREE.MathUtils.clamp(1.2 - v.z, 0.2, 1));
    }
  }
}

function buildUI() {
  $('btn-play').onclick = () => togglePlay();
  $('btn-speed').onclick = () => {
    const speeds = [1, 2, 4, 8];
    const i = speeds.indexOf(state.speed);
    state.speed = speeds[(i + 1) % speeds.length];
    $('btn-speed').textContent = `${state.speed}×`;
  };
  $('time').oninput = (e) => {
    state.time = Number(e.target.value);
    state.playing = false;
    $('btn-play').textContent = '▶ 播放';
    updateTime();
  };
  $('btn-cinema').onclick = () => {
    state.controls.autoRotate = !state.controls.autoRotate;
    state.controls.autoRotateSpeed = 0.55;
    $('btn-cinema').textContent = state.controls.autoRotate ? '停止巡航' : '电影巡航';
  };
  $('btn-reset').onclick = () => {
    state.camera.position.set(38, 26, 38);
    state.controls.target.set(0, 6, 0);
    state.controls.update();
  };
  $('btn-share').onclick = async () => {
    const url = location.href;
    try {
      await navigator.clipboard.writeText(url);
      toast('已复制当前链接；外网分享需用 cloudflared 隧道。');
    } catch {
      toast(url);
    }
  };
  $('v0').oninput = (e) => {
    switchToPreview();
    state.params.V0 = Number(e.target.value) * 1e5;
    $('v0-out').textContent = `${(state.params.V0 / 1e5).toFixed(1)}e5 m³`;
    updateHazard();
  };
  $('mu').oninput = (e) => {
    switchToPreview();
    state.params.mu = Number(e.target.value);
    $('mu-out').textContent = state.params.mu.toFixed(2);
    updateHazard();
  };
  $('xi').oninput = (e) => {
    switchToPreview();
    state.params.xi = Number(e.target.value);
    $('xi-out').textContent = `${state.params.xi}`;
    updateHazard();
  };
  $('use-q4').onchange = (e) => {
    state.useQ4 = e.target.checked && !!state.q4 && state.scenario === '2026';
    $('scenario-note').textContent = state.useQ4
      ? '2026-08-26 10:30；Q4 60 m 基线帧（S5，μ=0.05）；3D 地形为 30 m DEM。'
      : '2026-08-26 10:30；快速情景预览；滑杆生效，不是 Q4 验证结果。';
    updateHazard();
  };
  for (const [id, key] of [['layer-hazard', 'hazard'], ['layer-channel', 'channel'], ['layer-glacier', 'glacier'], ['layer-warning', 'warning']]) {
    $(id).onchange = () => {
      if (key === 'hazard') state.hazard.visible = $(id).checked;
      if (key === 'channel') state.channelLine.visible = $(id).checked;
      if (key === 'glacier') state.glacierPointsObj.visible = $(id).checked;
      if (key === 'warning') state.warningGroup.visible = $(id).checked;
    };
  }
  document.querySelectorAll('#scenario-seg button').forEach(btn => {
    btn.onclick = () => setScenario(btn.dataset.scenario);
  });
  state.profileCtx = $('profile').getContext('2d');
}

function switchToPreview() {
  if (!state.useQ4) return;
  state.useQ4 = false;
  const box = $('use-q4');
  if (box) box.checked = false;
  $('scenario-note').textContent = '2026-08-26 10:30；快速情景预览；滑杆生效，不是 Q4 验证结果。';
}

function setScenario(id, announce = true) {  state.scenario = id;
  document.querySelectorAll('#scenario-seg button').forEach(b => b.classList.toggle('active', b.dataset.scenario === id));
  if (id === '2026') {
    const m = state.q4?.meta || {};
    state.params = { V0: Number(m.V0) || 3.0e5, mu: Number.isFinite(Number(m.mu)) ? Number(m.mu) : 0.05, xi: Number(m.xi) || 300, sourceArea: 5.0e4 };
    state.useQ4 = !!state.q4;
    $('use-q4').checked = state.useQ4;
    $('use-q4').disabled = !state.q4;
    $('scenario-note').textContent = state.useQ4
      ? '2026-08-26 10:30；Q4 60 m 基线帧（S5，μ=0.05）；3D 地形为 30 m DEM。'
      : '2026-08-26 10:30；快速情景预览；关闭 Q4 帧后滑杆生效。';
    state.duration = 1800;
  } else {
    state.useQ4 = false;
    $('use-q4').checked = false;
    $('use-q4').disabled = true;
    state.params = { V0: 5.0e5, mu: 0.22, xi: 260, sourceArea: 5.0e4 };
    $('scenario-note').textContent = '2025-07-08 05:00；冰湖溃决（GLOF）；仅作条件情景。';
    state.duration = 1800;
  }
  $('v0').value = state.params.V0 / 1e5;
  $('mu').value = state.params.mu;
  $('xi').value = state.params.xi;
  $('v0-out').textContent = `${(state.params.V0 / 1e5).toFixed(1)}e5 m³`;
  $('mu-out').textContent = state.params.mu.toFixed(2);
  $('xi-out').textContent = `${state.params.xi}`;
  $('time').max = state.duration;
  state.time = 0;
  state.playing = false;
  $('btn-play').textContent = '▶ 播放';
  updateQ3Panel();
  updateTime();
  if (announce) toast(id === '2026' ? '已切到 2026 冰崩链情景' : '已切到 2025 GLOF 情景');
}

function updateQ3Panel() {
  const el = $('q3-panel');
  if (!state.q3) { el.textContent = '无 Q3 数据'; return; }
  const event = Number(state.scenario);
  const rows = state.q3.warning.filter(r => Number(r.event) === event);
  const main = rows.find(r => Number(r.H_warn_h) === 6 && Number(r.p_warn) === 0.9) || rows[0];
  const interval = state.q3.interval.filter(r => Number(r.event) === event && r.quantity === 'T_trigger_h')[0];
  const caseRow = state.q3.cases.find(r => Number(r.event) === event);
  const fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v))) ? 'NA' : Number(v).toFixed(d);
  el.innerHTML = `
    <div class="row"><span>事件</span><b>${escapeHtml(String(caseRow?.event_time_bjt || event))}</b></div>
    <div class="row"><span>主分支</span><b>${escapeHtml(String(caseRow?.dominant_branch || 'NA'))}</b></div>
    <div class="row"><span>站点 T_rain</span><b>${caseRow && caseRow.T_rain_station_h ? escapeHtml(String(caseRow.T_rain_station_h)) : '∞'}</b></div>
    <div class="row"><span>T_trigger 中位</span><b>${fmt(interval?.median, 1)} h</b></div>
    <div class="row"><span>95% 区间</span><b>${fmt(interval?.q025, 1)}–${interval?.q975 ? fmt(interval.q975, 1) : '∞'} h</b></div>
    <div class="row"><span>p_inf</span><b>${fmt(interval?.p_inf, 2)}</b></div>
    <div class="row"><span>T_warn</span><b class="warn">${escapeHtml(String(main?.T_warn_bjt || '无预警'))}</b></div>
    <div class="row"><span>lead 中位</span><b class="warn">${fmt(main?.lead_median_h, 2)} h</b></div>
    <p class="hint">Q3 是条件预测区间；2026 集合有 4% 降雨分支，lead 下尾可为负。</p>
  `;
}

function togglePlay() {
  state.playing = !state.playing;
  $('btn-play').textContent = state.playing ? '⏸ 暂停' : '▶ 播放';
  if (state.playing && state.time >= state.duration) state.time = 0;
}

let last = performance.now();
function animate(now = performance.now()) {
  requestAnimationFrame(animate);
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  if (state.playing) {
    state.time += dt * state.speed;
    if (state.time >= state.duration) { state.time = state.duration; state.playing = false; $('btn-play').textContent = '▶ 播放'; }
    updateTime();
  }
  state.controls.update();
  updateLabels();
  if (state.warningGroup) state.warningGroup.children.forEach((r, i) => {
    r.material.opacity = 0.35 + 0.2 * Math.sin(now / 600 + i);
  });
  state.renderer.render(state.scene, state.camera);
}

function updateTime() {
  $('time').value = state.time;
  $('time-out').textContent = `${clock(state.time)} / ${clock(state.duration)}`;
  updateHazard();
}

function clock(s) {
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

function q4FrameAt(t) {
  if (!state.q4 || !state.q4.frames?.length) return null;
  const fs = state.q4.frames;
  let best = fs[0];
  let bestD = Infinity;
  for (const f of fs) {
    const d = Math.abs(f.t - t);
    if (d < bestD) { bestD = d; best = f; }
  }
  return best;
}

function q4Value(arr, d) {
  const s = state.q4.s_km;
  if (!s || !arr) return 0;
  let lo = 0, hi = s.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (s[mid] < d) lo = mid + 1; else hi = mid;
  }
  if (lo === 0) return arr[0] || 0;
  const x0 = s[lo - 1], x1 = s[lo];
  const y0 = arr[lo - 1] || 0, y1 = arr[lo] || 0;
  const f = x1 > x0 ? (d - x0) / (x1 - x0) : 0;
  return Math.max(0, y0 + f * (y1 - y0));
}

function updateHazard() {
  const sampled = state.channel.sampled;
  if (!sampled) return;
  const L = state.channel.meta.length_km;
  const q4Frame = state.scenario === '2026' && state.useQ4 ? q4FrameAt(state.time) : null;
  const useQ4 = !!q4Frame;
  const h0 = useQ4 ? Math.max(...q4Frame.h) : state.params.V0 / state.params.sourceArea;
  const meanSlope = 8.0;
  let vfront = 18 + 4 * Math.sqrt(Math.max(1, h0));
  vfront *= 1 / (1 + 2 * state.params.mu);
  vfront *= Math.pow(300 / state.params.xi, 0.12);
  const acc = 0.06 * (meanSlope / 8.0);
  const t = state.time;
  const frontKm = useQ4 ? q4Frame.front_km : Math.min(L, (vfront * t + 0.5 * acc * t * t) / 1000);
  const frontIndex = Math.min(sampled.length - 1, Math.floor((frontKm / L) * (sampled.length - 1)));

  const pos = state.hazardGeo.attributes.position.array;
  const col = state.hazardGeo.attributes.color.array;
  const c = new THREE.Color();
  const low = new THREE.Color('#2b6fdb');
  const high = new THREE.Color('#ffd166');
  let maxDepth = 0, sumDepth = 0, count = 0;
  let minY = Infinity, maxY = -Infinity;

  for (let i = 0; i < sampled.length; i++) {
    const p = sampled[i];
    const d = p.d_km;
    const on = d <= frontKm + 1e-9;
    let depth = 0, vel = 0, width = 0;
    if (on) {
      if (useQ4) {
        depth = q4Value(q4Frame.h, d);
        vel = q4Value(q4Frame.u, d);
        width = Math.min(0.38, Math.max(0.12, 0.08 + 0.008 * d));
        if (depth <= 0) depth = 0;
      } else {
        const rel = d / Math.max(0.001, frontKm);
        depth = Math.max(0.05, h0 * Math.exp(-d / 10) * (1 - 0.55 * Math.min(1, rel)));
        vel = vfront * Math.exp(-d / 14);
        width = Math.min(0.38, Math.max(0.12, 0.08 + 0.008 * d));
      }
      if (depth > 0) {
        maxDepth = Math.max(maxDepth, depth);
        sumDepth += depth; count++;
      }
    }
    const terrainY = Math.max(baseY(p.y), terrainYAt(p.x, p.z));
    const y = terrainY + (on ? 0.12 + Math.max(0.04, depth / 1000 * 10.0) : 0.06);
    const dx = p.x, dz = p.z;
    const prev = sampled[Math.max(0, i - 1)], next = sampled[Math.min(sampled.length - 1, i + 1)];
    let tx = next.x - prev.x, tz = next.z - prev.z;
    const tl = Math.hypot(tx, tz) || 1; tx /= tl; tz /= tl;
    const px = -tz, pz = tx;
    const half = width / 2;
    const a = i * 2, b = a + 1;
    pos[a * 3] = dx + px * half; pos[a * 3 + 1] = y; pos[a * 3 + 2] = dz + pz * half;
    pos[b * 3] = dx - px * half; pos[b * 3 + 1] = y; pos[b * 3 + 2] = dz - pz * half;
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    const q = THREE.MathUtils.clamp(vel / Math.max(1, vfront), 0, 1);
    c.copy(low).lerp(high, on ? 0.25 + 0.75 * q : 0);
    col[a * 3] = c.r; col[a * 3 + 1] = c.g; col[a * 3 + 2] = c.b;
    col[b * 3] = c.r; col[b * 3 + 1] = c.g; col[b * 3 + 2] = c.b;
  }
  state.hazardGeo.attributes.position.needsUpdate = true;
  state.hazardGeo.attributes.color.needsUpdate = true;
  state.hazardGeo.setDrawRange(0, Math.max(0, frontIndex) * 6);

  // instanced ribbon
  const inst = state.hazardInst;
  const m4 = new THREE.Matrix4();
  const q4 = new THREE.Quaternion();
  const axis = new THREE.Vector3(0, 1, 0);
  const v3 = new THREE.Vector3();
  const s3 = new THREE.Vector3();
  const color = new THREE.Color();
  for (let i = 0; i <= frontIndex; i++) {
    const p = sampled[i];
    const prev = sampled[Math.max(0, i - 1)], next = sampled[Math.min(sampled.length - 1, i + 1)];
    let tx = next.x - prev.x, tz = next.z - prev.z;
    const tl = Math.hypot(tx, tz) || 1; tx /= tl; tz /= tl;
    const rel = p.d_km / Math.max(0.001, frontKm);
    const depth = Math.max(0.05, h0 * Math.exp(-p.d_km / 10) * (1 - 0.55 * Math.min(1, rel)));
    const vel = vfront * Math.exp(-p.d_km / 14);
    const w = Math.min(0.38, Math.max(0.12, 0.08 + 0.008 * p.d_km));
    const h = 0.06 + depth / 1000 * 10.0;
    q4.setFromAxisAngle(axis, Math.atan2(tx, tz));
    v3.set(p.x, Math.max(baseY(p.y), terrainYAt(p.x, p.z)) + h / 2 + 0.08, p.z);
    s3.set(w, h, 0.18);
    m4.compose(v3, q4, s3);
    inst.setMatrixAt(i, m4);
    color.copy(low).lerp(high, THREE.MathUtils.clamp(vel / Math.max(1, vfront), 0, 1));
    inst.setColorAt(i, color);
  }
  inst.count = Math.max(0, frontIndex + 1);
  inst.instanceMatrix.needsUpdate = true;
  if (inst.instanceColor) inst.instanceColor.needsUpdate = true;

  // group of boxes: robust on all WebGL drivers
  const grp = state.hazardGroup;
  for (let i = 0; i < grp.children.length; i++) {
    const mesh = grp.children[i];
    if (i > frontIndex) { mesh.visible = false; continue; }
    const p = sampled[i];
    const prev = sampled[Math.max(0, i - 1)], next = sampled[Math.min(sampled.length - 1, i + 1)];
    let tx = next.x - prev.x, tz = next.z - prev.z;
    const tl = Math.hypot(tx, tz) || 1; tx /= tl; tz /= tl;
    const rel = p.d_km / Math.max(0.001, frontKm);
    const depth = Math.max(0.05, h0 * Math.exp(-p.d_km / 10) * (1 - 0.55 * Math.min(1, rel)));
    const vel = vfront * Math.exp(-p.d_km / 14);
    const w = 0.22;
    const h = 0.3 + depth / 1000 * 6.0;
    mesh.visible = true;
    mesh.position.set(p.x, Math.max(baseY(p.y), terrainYAt(p.x, p.z)) + h / 2 + 0.08, p.z);
    mesh.rotation.y = Math.atan2(tx, tz);
    mesh.scale.set(w, h, 0.3);
    mesh.material.color.copy(low).lerp(high, THREE.MathUtils.clamp(vel / Math.max(1, vfront), 0, 1));
    mesh.material.opacity = 0.86;
  }
  grp.visible = state.hazard.visible !== false;

  if (frontIndex > 0 && frontKm < L - 0.01) {
    const p = sampled[frontIndex];
    state.frontMarker.visible = true;
    state.frontMarker.position.set(p.x, Math.max(baseY(p.y), terrainYAt(p.x, p.z)) + 0.25, p.z);
    const s = 0.8 + 0.4 * Math.sin(performance.now() / 250);
    state.frontMarker.scale.setScalar(s);
  } else {
    state.frontMarker.visible = false;
  }

  state.stats = { frontKm, maxDepth, sumDepth, count, h0, vfront, t };
  $('stats').innerHTML = `
    <span>锋面 <b>${frontKm.toFixed(1)} km</b></span>
    <span>数据 <b>${useQ4 ? 'Q4 60m' : '情景预览'}</b></span>
    <span>最大水深 <b>${maxDepth.toFixed(1)} m</b></span>
    <span>平均水深 <b>${(count ? sumDepth / count : 0).toFixed(1)} m</b></span>
    <span>锋面速度 <b>${vfront.toFixed(1)} m/s</b></span>
    <span>初始水深 <b>${h0.toFixed(1)} m</b></span>
    <span>已历时 <b>${clock(state.time)}</b></span>
  `;
  drawProfile(sampled, frontIndex, h0, frontKm, q4Frame, useQ4);
}

function drawProfile(sampled, frontIndex, h0, frontKm, q4Frame = null, useQ4 = false) {
  const ctx = state.profileCtx;
  const W = $('profile').width, H = $('profile').height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = 'rgba(4,8,12,.65)';
  ctx.fillRect(0, 0, W, H);
  const L = state.channel.meta.length_km;
  const x = (d) => 10 + (d / L) * (W - 20);
  const y = (v) => H - 14 - Math.min(1, v / 12) * (H - 26);
  ctx.strokeStyle = 'rgba(120,190,230,.35)';
  ctx.beginPath(); ctx.moveTo(10, H - 14); ctx.lineTo(W - 10, H - 14); ctx.stroke();
  ctx.strokeStyle = 'rgba(111,231,255,.8)';
  ctx.beginPath();
  for (let i = 0; i <= frontIndex; i++) {
    const p = sampled[i];
    const rel = p.d_km / Math.max(0.001, frontKm);
    const depth = useQ4
      ? q4Value(q4Frame.h, p.d_km)
      : Math.max(0.05, h0 * Math.exp(-p.d_km / 10) * (1 - 0.55 * Math.min(1, rel)));
    if (i === 0) ctx.moveTo(x(p.d_km), y(depth)); else ctx.lineTo(x(p.d_km), y(depth));
  }
  ctx.stroke();
  ctx.lineTo(x(sampled[frontIndex]?.d_km || 0), H - 14);
  ctx.lineTo(x(sampled[0].d_km), H - 14);
  ctx.closePath();
  ctx.fillStyle = 'rgba(43,111,219,.25)';
  ctx.fill();
  ctx.fillStyle = 'rgba(220,232,242,.7)';
  ctx.font = '10px Consolas, monospace';
  ctx.fillText('水深剖面（m，情景预览）', 12, 12);
}

function onResize() {
  state.camera.aspect = innerWidth / innerHeight;
  state.camera.updateProjectionMatrix();
  state.renderer.setSize(innerWidth, innerHeight);
}

function hideLoading() { $('loading').style.display = 'none'; }
function toast(msg) {
  const t = $('toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('show'), 2400);
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}
