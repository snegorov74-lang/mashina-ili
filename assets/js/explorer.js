// 3D-разбор S-EVOR: выбор детали, прозрачный кузов, разнесённая сборка, разрез, изоляция.
// Сведения о детали берутся из glTF extras (part, name_ru, group, term), которые
// пишет model/build_sevor.py. Для старой упрощённой модели есть запасной разбор имён.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const MODEL = "model/sevor.glb";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const GROUPS = {
  body:       { ru: "Кузов и антикрыло",   anchor: "node-body" },
  chassis:    { ru: "Шасси и бамперы",     anchor: "node-body" },
  suspension: { ru: "Подвеска",            anchor: "node-suspension" },
  steering:   { ru: "Рулевое",             anchor: "node-steering" },
  hubs:       { ru: "Кулаки и ступицы",    anchor: "node-hubs" },
  wheels:     { ru: "Колёса",              anchor: "node-wheels" },
  drive:      { ru: "Мотор и трансмиссия", anchor: "node-drive" },
  diff:       { ru: "Дифференциалы",       anchor: "node-diff" },
  electric:   { ru: "Электроника",         anchor: "node-electric" }
};
const groupColor = (g) => getComputedStyle(document.documentElement).getPropertyValue("--g-" + g).trim() || "#888";

const TERMS = {};
(window.GLOSSARY || []).forEach((g) => g.terms.forEach((t) => { TERMS[t.id] = t; }));

/* ── Запасные сведения для упрощённой модели (имена вида Arm_FL) ── */
const POS = { FL: "передний левый", FR: "передний правый", RL: "задний левый", RR: "задний правый", F: "передняя", R: "задняя" };
const FALLBACK = [
  [/^Arm_(FL|FR|RL|RR)$/, (p) => ({ part: "P2505", name_ru: "Рычаг подвески " + POS[p], group: "suspension", term: "arm" })],
  [/^Shock_(FL|FR|RL|RR)$/, (p) => ({ part: "P6955", name_ru: "Амортизатор " + POS[p], group: "suspension", term: "shock" })],
  [/^ShockTower_(F|R)$/, (p) => ({ part: "", name_ru: "Стойка амортизаторов " + POS[p], group: "chassis", term: "shock" })],
  [/^Wheel_(FL|FR|RL|RR)$/, (p) => ({ part: "P6973", name_ru: "Колесо " + POS[p], group: "wheels", term: "hex" })],
  [/^Driveshaft_(FL|FR|RL|RR)$/, (p) => ({ part: "M5367", name_ru: "Приводной вал (дог-бон) " + POS[p], group: "drive", term: "dogbone" })],
  [/^Wing_Mount$/, () => ({ part: "", name_ru: "Крепление антикрыла", group: "body", term: "wing" })],
  [/^Wing$/, () => ({ part: "", name_ru: "Антикрыло", group: "body", term: "wing" })],
  [/^Body$/, () => ({ part: "", name_ru: "Кузов S-EVOR", group: "body", term: "body" })],
  [/^Bumper$/, () => ({ part: "P2503", name_ru: "Передний бампер", group: "chassis", term: "bumper" })],
  [/^Bumper_Rear$/, () => ({ part: "P2514", name_ru: "Задний бампер", group: "chassis", term: "bumper" })],
  [/^Chassis$/, () => ({ part: "P2501", name_ru: "Шасси (ванна)", group: "chassis", term: "chassis" })],
  [/^Battery$/, () => ({ part: "", name_ru: "Аккумулятор 7,4 В", group: "electric", term: "liion" })],
  [/^Motor$/, () => ({ part: "E9661", name_ru: "Мотор 390", group: "drive", term: "brushed" })],
  [/^Headlights$/, () => ({ part: "", name_ru: "Светодиодные фары", group: "electric", term: "led" })]
];
function fallbackMeta(name) {
  for (const [re, fn] of FALLBACK) { const m = re.exec(name); if (m) return fn(m[1]); }
  return null;
}

/* ── Сцена ── */
const stage = $("#stage");
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.localClippingEnabled = true;
stage.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;
const camera = new THREE.PerspectiveCamera(32, 1, 0.001, 20);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.screenSpacePanning = true;
controls.zoomToCursor = true;
controls.minDistance = 0.004;
controls.maxDistance = 3;

const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(0.6, 1.2, -0.4);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -0.4, right: 0.4, top: 0.4, bottom: -0.4, near: 0.1, far: 3 });
sun.shadow.bias = -0.0004;
scene.add(sun, new THREE.HemisphereLight(0xffffff, 0x8a939c, 0.5));
const ground = new THREE.Mesh(new THREE.PlaneGeometry(4, 4), new THREE.ShadowMaterial({ opacity: 0.18 }));
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

const cutPlane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 10);

function resize() {
  const w = stage.clientWidth, h = stage.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(stage);

/* ── Состояние ── */
const parts = [];          // { obj, meta, meshes, center, origLocal, localDelta }
let modelBox = new THREE.Box3();
let modelCenter = new THREE.Vector3();
let modelRadius = 0.2;
let selected = null;
let bodyMode = "solid";
let explode = 0;
let isolate = false;
let anim = null;
let homeDist = 0.6;

/* ── Загрузка ── */
new GLTFLoader().load(MODEL, (gltf) => {
  const root = gltf.scene;
  scene.add(root);
  root.updateMatrixWorld(true);

  // Объект-деталь = ближайший предок меша (или сам меш), у которого есть сведения.
  const byObj = new Map();
  root.traverse((o) => {
    if (!o.isMesh) return;
    o.castShadow = true;
    o.receiveShadow = true;
    o.material = o.material.clone();
    o.material.clippingPlanes = [cutPlane];
    o.material.clipShadows = true;
    o.userData._base = { color: o.material.color?.clone(), emissive: o.material.emissive?.clone(), emissiveIntensity: o.material.emissiveIntensity, opacity: o.material.opacity, transparent: o.material.transparent, side: o.material.side };

    let owner = null, meta = null;
    for (let a = o; a && a !== root; a = a.parent) {
      if (a.userData && a.userData.name_ru) { owner = a; meta = { ...a.userData }; break; }
    }
    if (!owner) {
      for (let a = o; a && a !== root; a = a.parent) {
        const fb = fallbackMeta(a.name);
        if (fb) { owner = a; meta = fb; break; }
      }
    }
    if (!owner) { owner = o; meta = { part: "", name_ru: o.name.replace(/_/g, " "), group: "chassis" }; }
    if (!GROUPS[meta.group]) meta.group = "chassis";
    if (!byObj.has(owner)) byObj.set(owner, { obj: owner, meta, meshes: [] });
    byObj.get(owner).meshes.push(o);
  });

  modelBox.setFromObject(root);
  modelBox.getCenter(modelCenter);
  modelRadius = modelBox.getSize(new THREE.Vector3()).length() / 2;
  ground.position.y = modelBox.min.y - 0.0005;

  byObj.forEach((p) => {
    p.center = new THREE.Box3().setFromObject(p.obj).getCenter(new THREE.Vector3());
    p.origLocal = p.obj.position.clone();
    p.id = p.obj.name;
    parts.push(p);
  });
  computeExplodeVectors(root);
  buildTree();
  resetView(true);
  $("#loading").hidden = true;
  selectFromHash();
}, undefined, () => {
  $("#loading").textContent = "Не удалось загрузить модель. Обновите страницу.";
  $("#tree").innerHTML = '<p class="x__muted">Модель не загрузилась.</p>';
});

// Разнос: деталь уходит от центра машины, а внутри узла (амортизатор, дифференциал, колесо)
// ещё и от центра своего узла. Кузов и антикрыло поднимаются вверх.
function computeExplodeVectors(root) {
  const partSet = new Set(parts.map((p) => p.obj));
  const assemblyCenter = new Map();
  function assemblyOf(obj) {
    for (let a = obj.parent; a && a !== root; a = a.parent) {
      let n = 0;
      a.traverse((c) => { if (partSet.has(c)) n++; });
      if (n >= 2 && !GROUPS[a.name?.toLowerCase()] && a.parent !== root) return a;
      if (a.parent === root) return null;
    }
    return null;
  }
  parts.forEach((p) => {
    const off = p.center.clone().sub(modelCenter).multiplyScalar(0.9);
    const asm = assemblyOf(p.obj);
    if (asm) {
      if (!assemblyCenter.has(asm)) assemblyCenter.set(asm, new THREE.Box3().setFromObject(asm).getCenter(new THREE.Vector3()));
      off.add(p.center.clone().sub(assemblyCenter.get(asm)).multiplyScalar(1.8));
    }
    if (p.meta.group === "body") off.y += /wing/i.test(p.id + p.meta.term) ? 0.2 : 0.14;
    const parent = p.obj.parent;
    const w0 = p.obj.getWorldPosition(new THREE.Vector3());
    const l0 = parent.worldToLocal(w0.clone());
    const l1 = parent.worldToLocal(w0.clone().add(off));
    p.localDelta = l1.sub(l0);
  });
}

function applyExplode() {
  parts.forEach((p) => p.obj.position.copy(p.origLocal).addScaledVector(p.localDelta, explode));
}

/* ── Внешний вид ── */
function applyLook() {
  parts.forEach((p) => {
    const isBody = p.meta.group === "body";
    const hiddenByIso = isolate && selected && p !== selected;
    p.obj.visible = !(isBody && bodyMode === "off") && !hiddenByIso;
    p.meshes.forEach((m) => {
      const b = m.userData._base, mat = m.material;
      const glass = isBody && bodyMode === "glass" && p !== selected;
      mat.transparent = glass || b.transparent;
      mat.opacity = glass ? 0.16 : b.opacity;
      mat.depthWrite = !glass;
      mat.side = cutPlane.constant < 5 ? THREE.DoubleSide : b.side;
      if (mat.emissive) {
        if (p === selected) { mat.emissive.set(0xd7262e); mat.emissiveIntensity = 0.45; }
        else { mat.emissive.copy(b.emissive); mat.emissiveIntensity = b.emissiveIntensity; }
      }
      mat.needsUpdate = true;
    });
  });
}

/* ── Камера ── */
function flyTo(target, dist, dir) {
  const fromPos = camera.position.clone(), fromTgt = controls.target.clone();
  const d = dir || camera.position.clone().sub(controls.target).normalize();
  const toPos = target.clone().addScaledVector(d, dist);
  const t0 = performance.now(), dur = matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : 650;
  anim = (now) => {
    const k = Math.min(1, (now - t0) / dur), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    camera.position.lerpVectors(fromPos, toPos, e);
    controls.target.lerpVectors(fromTgt, target, e);
    if (k >= 1) anim = null;
  };
}
function focusPart(p) {
  const box = new THREE.Box3().setFromObject(p.obj);
  const size = box.getSize(new THREE.Vector3()).length();
  flyTo(box.getCenter(new THREE.Vector3()), Math.max(size * 2.2, 0.03));
}
function resetView(instant) {
  const dir = new THREE.Vector3(0.78, 0.5, -0.95).normalize();
  homeDist = modelRadius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 0.95;
  const dist = homeDist * (1 + explode * 0.9);
  if (instant) {
    controls.target.copy(modelCenter);
    camera.position.copy(modelCenter).addScaledVector(dir, dist);
  } else flyTo(modelCenter.clone(), dist, dir);
}

/* ── Выбор ── */
function select(p, opts = {}) {
  selected = p;
  applyLook();
  document.querySelectorAll(".tpart").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === p?.id)));
  const info = $("#info");
  if (!p) { info.hidden = true; if (isolate) toggleIsolate(false); return; }
  const m = p.meta, g = GROUPS[m.group], t = TERMS[m.term];
  $("#i-group").innerHTML = `<span class="sw" style="background:${groupColor(m.group)}"></span>${esc(g.ru)}`;
  $("#i-name").textContent = m.name_ru;
  $("#i-pn").textContent = m.part ? "Номер детали: " + m.part : "";
  $("#i-term").innerHTML = t ? `<div class="x__term"><img class="x__termimg" src="assets/img/glossary/${esc(t.id)}.webp" alt="" width="720" height="540" onerror="this.remove()"><h3>${esc(t.term)} — что это?</h3><p>${esc(t.what)}</p><p class="why"><b>Зачем:</b> ${esc(t.why)}</p></div>` : "";
  const links = [`<a href="index.html#${g.anchor}">В каталоге запчастей</a>`];
  if (m.part) links.push(`<a href="https://aliexpress.ru/wholesale?SearchText=${encodeURIComponent("Remo Hobby " + m.part)}" target="_blank" rel="noopener">Искать ${esc(m.part)}</a>`);
  if (t) links.push(`<a href="index.html#t-${esc(t.id)}">В словарике</a>`);
  $("#i-links").innerHTML = links.join("");
  info.hidden = false;
  if (isolate) { applyLook(); focusPart(p); }
  if (opts.focus) focusPart(p);
  if (opts.scroll) document.querySelector(`.tpart[data-id="${CSS.escape(p.id)}"]`)?.scrollIntoView({ block: "nearest" });
  try { history.replaceState(null, "", "#" + encodeURIComponent(p.id)); } catch (_) {}
}
function selectFromHash() {
  const h = decodeURIComponent(location.hash.slice(1));
  if (!h) return;
  const p = parts.find((x) => x.id === h) || parts.find((x) => x.meta.part === h);
  if (p) select(p, { focus: true, scroll: true });
}

/* ── Список деталей ── */
function buildTree() {
  const q = ($("#part-q").value || "").trim().toLowerCase();
  const html = Object.keys(GROUPS).map((g) => {
    const list = parts.filter((p) => p.meta.group === g && (!q || [p.meta.name_ru, p.meta.part, p.id].some((v) => v && v.toLowerCase().includes(q))))
      .sort((a, b) => a.meta.name_ru.localeCompare(b.meta.name_ru, "ru"));
    if (!list.length) return "";
    return `<div class="tgroup" data-g="${g}">
      <button type="button" aria-expanded="true"><span class="sw" style="background:${groupColor(g)}"></span>${esc(GROUPS[g].ru)}<span class="n">${list.length}</span></button>
      <ul>${list.map((p) => `<li><button type="button" class="tpart" data-id="${esc(p.id)}" aria-current="${p === selected}"><span>${esc(p.meta.name_ru)}</span><small>${esc(p.meta.part || "")}</small></button></li>`).join("")}</ul>
    </div>`;
  }).join("");
  $("#tree").innerHTML = html || '<p class="x__muted">Ничего не нашлось.</p>';
}
$("#part-q").addEventListener("input", buildTree);
$("#tree").addEventListener("click", (e) => {
  const b = e.target.closest(".tpart");
  if (b) { select(parts.find((p) => p.id === b.dataset.id), { focus: true }); return; }
  const h = e.target.closest(".tgroup > button");
  if (h) { const g = h.parentElement; g.classList.toggle("is-collapsed"); h.setAttribute("aria-expanded", String(!g.classList.contains("is-collapsed"))); }
});

/* ── Клики по модели ── */
const ray = new THREE.Raycaster();
const ptr = new THREE.Vector2();
let down = null;
function pick(ev) {
  const r = renderer.domElement.getBoundingClientRect();
  ptr.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ptr, camera);
  const meshes = [];
  parts.forEach((p) => {
    if (!p.obj.visible) return;
    if (p.meta.group === "body" && bodyMode === "glass" && p !== selected) return;
    p.meshes.forEach((m) => meshes.push(m));
  });
  const hits = ray.intersectObjects(meshes, false).filter((h) => cutPlane.distanceToPoint(h.point) >= 0);
  if (!hits.length) return null;
  return parts.find((p) => p.meshes.includes(hits[0].object));
}
renderer.domElement.addEventListener("pointerdown", (e) => { down = { x: e.clientX, y: e.clientY }; });
renderer.domElement.addEventListener("pointerup", (e) => {
  if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) return;
  const p = pick(e);
  if (p) select(p, { scroll: true }); else if (!isolate) select(null);
});
renderer.domElement.addEventListener("dblclick", (e) => { const p = pick(e); if (p) select(p, { focus: true, scroll: true }); });
renderer.domElement.addEventListener("pointermove", (e) => {
  if (e.buttons) return;
  renderer.domElement.style.cursor = pick(e) ? "pointer" : "grab";
});

/* ── Панель инструментов ── */
$("#body-mode").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  bodyMode = b.dataset.v;
  $("#body-mode").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  applyLook();
});
$("#explode").addEventListener("input", (e) => {
  explode = e.target.value / 100;
  applyExplode();
  // Без выбранной детали камера отъезжает, чтобы разобранная машина помещалась в кадр.
  if (!selected && !anim) {
    const dir = camera.position.clone().sub(controls.target).normalize();
    camera.position.copy(controls.target).addScaledVector(dir, homeDist * (1 + explode * 0.9));
  }
});
$("#cut").addEventListener("input", (e) => {
  const v = e.target.value / 100;
  cutPlane.constant = v >= 0.999 ? 10 : THREE.MathUtils.lerp(modelBox.min.x - 0.002, modelBox.max.x, v);
  applyLook();
});
function toggleIsolate(on) {
  isolate = on ?? !isolate;
  if (isolate && !selected) isolate = false;
  $("#isolate").setAttribute("aria-pressed", String(isolate));
  applyLook();
  if (isolate) focusPart(selected); else resetView(false);
}
$("#isolate").addEventListener("click", () => toggleIsolate());
$("#i-iso").addEventListener("click", () => toggleIsolate(true));
$("#i-focus").addEventListener("click", () => selected && focusPart(selected));
$("#info-close").addEventListener("click", () => select(null));
$("#reset").addEventListener("click", () => {
  explode = 0; $("#explode").value = 0; applyExplode();
  cutPlane.constant = 10; $("#cut").value = 100;
  bodyMode = "solid"; $("#body-mode").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.v === "solid")));
  isolate = false; $("#isolate").setAttribute("aria-pressed", "false");
  select(null);
  resetView(false);
});
window.addEventListener("keydown", (e) => { if (e.key === "Escape") { if (isolate) toggleIsolate(false); else select(null); } });
window.addEventListener("hashchange", selectFromHash);

/* ── Цикл отрисовки ── */
renderer.setAnimationLoop((now) => {
  if (anim) anim(now);
  controls.update();
  renderer.render(scene, camera);
});
resize();
