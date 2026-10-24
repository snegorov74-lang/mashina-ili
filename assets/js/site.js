(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
  function fmtDate(iso, short) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    if (!m) return esc(iso);
    if (short) return `${m[3]}.${m[2]}.${m[1].slice(2)}`;
    return `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}`;
  }

  /* ── Каталог ── */
  const PARTS = window.PARTS || [];
  const aliUrl = (q) => "https://aliexpress.ru/wholesale?SearchText=" + encodeURIComponent("Remo Hobby " + q);

  // Номер детали → термин словарика, чтобы название в каталоге открывало объяснение.
  const TERM_BY_PART = {
    P2505: "arm", F5281: "arm", P6955: "shock", A6955: "shock", M5367: "dogbone",
    P6956: "servosaver", P2511: "servosaver", P2512: "servo", P2529: "servo", P2519: "servo",
    P2506: "chub", P2507: "knuckle", P2513: "hub", M5368: "hub", P2021: "hex", F5226: "hex",
    E9661: "brushed", G2713: "gearT", G2715: "gearT", G2717: "gearT", A4027: "m390",
    G1610: "spur", G1611: "diff", P2527: "shaft", P2516: "spur",
    P6952: "diff", G1612: "diff", G1613: "diff", G1614: "diff", P2521: "dogbone", P2528: "diff",
    P2501: "chassis", P2502: "chassis", P2503: "bumper", P2514: "bumper", M5387: "clips",
    B5509: "bearing", B5510: "bearing", B5511: "bearing",
    F5271: "screw", F5272: "screw", F5274: "screw", F5277: "screw", F5280: "chub"
  };
  const TERM_BY_NAME = { "Антикрыло S-EVOR": "wing", "Кузов S-EVOR": "body", "Регулятор 3 в 1": "3in1",
    "Сервопривод 5-проводной": "servo", "Аккумулятор 7,4 В Li-Ion": "liion", "USB-зарядка": "balance" };
  const termLink = (id, text) => id ? `<a class="term" href="#t-${id}" data-term="${id}">${esc(text)}</a>` : esc(text);

  function partRow(p) {
    const hasNo = p.no && p.no !== "—";
    const term = TERM_BY_PART[p.no] || TERM_BY_NAME[p.name];
    const no = hasNo
      ? `<span class="part__no">${esc(p.no)}${p.alt ? `<small>или ${esc(p.alt)}</small>` : ""}</span>`
      : `<span class="part__no part__no--none">без номера</span>`;
    const q = hasNo ? p.no : "1661 " + p.name;
    return `<li class="part">
      ${no}
      <div><div class="part__name">${termLink(term, p.name)}${p.weak ? '<span class="weak">слабое место</span>' : ""}</div>
      ${p.text ? `<p class="part__text">${esc(p.text)}</p>` : ""}</div>
      <span class="part__links">${hasNo ? `<a href="3d.html#${encodeURIComponent(p.no)}">В 3D</a>` : ""}<a href="${aliUrl(q)}" rel="noopener" target="_blank">Искать →</a></span>
    </li>`;
  }

  function renderCatalog() {
    const box = $("#catalog");
    if (!box) return;
    const q = ($("#part-search").value || "").trim().toLowerCase();
    const weakOnly = $("#part-weak").checked;
    let shown = 0;
    box.innerHTML = PARTS.map((node) => {
      const nodeHit = q && node.title.toLowerCase().includes(q);
      const parts = node.parts.filter((p) => {
        if (weakOnly && !p.weak) return false;
        if (!q || nodeHit) return true;
        return [p.no, p.alt, p.name, p.text].some((v) => v && v.toLowerCase().includes(q));
      });
      if (!parts.length) return "";
      shown += parts.length;
      return `<article class="node" id="node-${esc(node.id)}">
        <div class="node__media">
          <img class="node__scheme" src="${esc(node.scheme)}" alt="Схема: ${esc(node.title)}" loading="lazy" data-zoom>
          ${node.photo ? `<img class="node__photo" src="${esc(node.photo)}" alt="Фото: ${esc(node.title)}" loading="lazy" data-zoom>` : ""}
        </div>
        <div>
          <header class="node__head"><h3>${esc(node.title)}</h3>${node.note ? `<p>${esc(node.note)}</p>` : ""}</header>
          <ul class="parts">${parts.map(partRow).join("")}</ul>
        </div>
      </article>`;
    }).join("");
    $("#catalog-empty").hidden = shown > 0;
  }

  /* ── Гараж ── */
  const G = window.GARAGE || {};
  const STATUS = { ok: "в порядке", watch: "присмотреть", broken: "сломано", replaced: "заменено" };
  const PRIO = { now: "сразу", soon: "когда понадобится", later: "потом" };
  const LOGTYPE = { ride: "катание", break: "поломка", repair: "ремонт", buy: "покупка", event: "событие" };

  function renderGarage() {
    if (G.since && $("#since")) $("#since").textContent = fmtDate(G.since);

    const nodes = $("#nodes");
    if (nodes) nodes.innerHTML = (G.nodes || []).map((n) => `<li>
      <span class="status status--${esc(n.status)}">${esc(STATUS[n.status] || n.status)}</span>
      <b>${esc(n.name)}</b>
      <time datetime="${esc(n.checked)}" title="Последний осмотр">${fmtDate(n.checked, true)}</time>
      ${n.note ? `<small>${esc(n.note)}</small>` : ""}
    </li>`).join("");

    const plans = $("#plans");
    if (plans) {
      const order = { now: 0, soon: 1, later: 2 };
      const list = [...(G.plans || [])].sort((a, b) => (a.done - b.done) || (order[a.priority] - order[b.priority]));
      plans.innerHTML = list.map((p) => `<li class="${p.done ? "done" : ""}">
        <span class="box" aria-hidden="true">${p.done ? "✓" : ""}</span>
        <div><b>${esc(p.title)}</b>${!p.done && p.priority ? `<span class="prio prio--${esc(p.priority)}">${esc(PRIO[p.priority] || p.priority)}</span>` : ""}${p.done ? '<span class="sr"> (сделано)</span>' : ""}</div>
        ${p.note ? `<small>${esc(p.note)}</small>` : ""}
      </li>`).join("");
    }

    const rep = $("#replaced");
    if (rep) rep.innerHTML = (G.replaced || []).length
      ? G.replaced.map((r) => `<li><b>${esc(r.name)}</b>${r.part ? ` <span class="pn">${esc(r.part)}</span>` : ""}
          <small>${fmtDate(r.date)}${r.reason ? " · " + esc(r.reason) : ""}${r.cost ? " · " + esc(r.cost) + " ₽" : ""}</small></li>`).join("")
      : `<li class="empty">Пока ничего не меняли: машина новая. Первую замену запишите в <code>data/garage.js</code>, в список <code>replaced</code>.</li>`;

    const log = $("#log");
    if (log) log.innerHTML = (G.log || []).map((e) => `<li>
      <time datetime="${esc(e.date)}">${fmtDate(e.date, true)}</time>
      <div><span class="tag">${esc(LOGTYPE[e.type] || e.type)}</span>${esc(e.text)}</div>
    </li>`).join("");

    const kit = $("#kit");
    if (kit) kit.innerHTML = (G.kit || []).map((k) => `<li><b>${esc(k.name)}</b>${k.note ? `<small>${esc(k.note)}</small>` : ""}</li>`).join("");
  }

  /* ── Словарик ── */
  const GLOSSARY = window.GLOSSARY || [];
  const TERMS = {};
  GLOSSARY.forEach((g) => g.terms.forEach((t) => { TERMS[t.id] = t; }));

  function termCard(t) {
    return `<li class="gterm" id="t-${esc(t.id)}">
      <h4>${esc(t.term)}</h4>${t.aka ? `<p class="aka">${esc(t.aka)}</p>` : ""}
      <p>${esc(t.what)}</p>
      <p class="why"><b>Зачем:</b> ${esc(t.why)}</p>
    </li>`;
  }

  function renderGlossary() {
    const box = $("#glossary");
    if (!box) return;
    const q = ($("#term-search")?.value || "").trim().toLowerCase();
    box.innerHTML = GLOSSARY.map((g) => {
      const list = g.terms.filter((t) => !q || [t.term, t.aka, t.what].some((v) => v && v.toLowerCase().includes(q)));
      if (!list.length) return "";
      return `<section class="glossary__group"><h3>${esc(g.group)}</h3><ul class="glossary__list">${list.map(termCard).join("")}</ul></section>`;
    }).join("") || `<p class="empty">Такого слова пока нет в словарике.</p>`;
  }

  function initTermPopover() {
    const pop = $("#termpop");
    if (!pop) return;
    let current = null;
    function close() { pop.hidden = true; current = null; }
    function open(a) {
      const t = TERMS[a.dataset.term];
      if (!t) return;
      current = a;
      pop.innerHTML = `<h4>${esc(t.term)}</h4>${t.aka ? `<p class="aka">${esc(t.aka)}</p>` : ""}
        <p>${esc(t.what)}</p><p class="why"><b>Зачем:</b> ${esc(t.why)}</p>
        <div class="termpop__foot"><a href="#t-${esc(t.id)}" data-goto="${esc(t.id)}">В словарике →</a><button type="button" class="termpop__close">Закрыть</button></div>`;
      pop.hidden = false;
      const r = a.getBoundingClientRect();
      const w = pop.offsetWidth;
      const left = Math.max(16, Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - w - 16));
      let top = window.scrollY + r.bottom + 8;
      if (r.bottom + pop.offsetHeight + 16 > window.innerHeight && r.top > pop.offsetHeight + 80) top = window.scrollY + r.top - pop.offsetHeight - 8;
      pop.style.left = left + "px";
      pop.style.top = top + "px";
    }
    document.addEventListener("click", (e) => {
      const a = e.target.closest("a.term");
      if (a) {
        e.preventDefault();
        if (current === a) close(); else open(a);
        return;
      }
      if (e.target.closest(".termpop__close")) { close(); return; }
      const go = e.target.closest("[data-goto]");
      if (go) {
        close();
        if ($("#term-search")) { $("#term-search").value = ""; renderGlossary(); }
        const card = document.getElementById("t-" + go.dataset.goto);
        if (card) { e.preventDefault(); card.scrollIntoView({ block: "center" }); card.classList.add("is-flash"); setTimeout(() => card.classList.remove("is-flash"), 1600); }
        return;
      }
      if (!e.target.closest("#termpop")) close();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  }

  /* ── Увеличение картинок ── */
  function initLightbox() {
    const dlg = $("#lightbox");
    if (!dlg || typeof dlg.showModal !== "function") return;
    const img = $("#lightbox-img"), cap = $("#lightbox-cap");
    document.addEventListener("click", (e) => {
      const t = e.target.closest("img[data-zoom]");
      if (!t) return;
      img.src = t.currentSrc || t.src;
      img.alt = t.alt;
      const fc = t.closest("figure")?.querySelector("figcaption");
      cap.textContent = fc ? fc.textContent : t.alt;
      dlg.showModal();
    });
    dlg.addEventListener("click", (e) => { if (e.target === dlg || e.target === img) dlg.close(); });
  }

  /* ── 3D-модель: подключается, если рядом лежит model/sevor.glb ── */
  const MODEL = "model/sevor.glb";
  const MV_SRC = "https://cdn.jsdelivr.net/npm/@google/model-viewer@3.5.0/dist/model-viewer.min.js";
  // Метки слабых мест. Координаты glTF в метрах (x, вверх, назад), сняты с объектов модели.
  const HOTSPOTS = [
    { label: "Антикрыло", position: "0.07 0.128 0.122", normal: "0 1 0", target: "#node-body" },
    { label: "Рычаги подвески", position: "0.05 0.03 -0.112", normal: "0 0 -1", target: "#node-suspension" },
    { label: "Колёса", position: "0.109 0.045 -0.093", normal: "1 0 0", target: "#node-wheels" }
  ];

  async function initModel() {
    const viewer = $("#viewer");
    if (!viewer || location.protocol === "file:") return;
    try {
      const r = await fetch(MODEL, { method: "HEAD" });
      if (!r.ok) return;
    } catch (_) { return; }

    const s = document.createElement("script");
    s.type = "module";
    s.src = MV_SRC;
    document.head.appendChild(s);

    const photo = $(".viewer__photo", viewer);
    const cap = $("#viewer-cap");
    const mv = document.createElement("model-viewer");
    mv.setAttribute("src", MODEL);
    mv.setAttribute("alt", "3D-модель Remo Hobby S-EVOR, её можно вращать");
    mv.setAttribute("camera-controls", "");
    mv.setAttribute("auto-rotate", "");
    mv.setAttribute("auto-rotate-delay", "1500");
    mv.setAttribute("rotation-per-second", "18deg");
    mv.setAttribute("shadow-intensity", "1");
    mv.setAttribute("exposure", "1.05");
    mv.setAttribute("camera-orbit", "140deg 70deg auto");
    mv.setAttribute("interaction-prompt", "none");
    mv.setAttribute("touch-action", "pan-y");
    mv.setAttribute("poster", "model/preview.png");
    HOTSPOTS.forEach((h, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "hotspot";
      b.slot = "hotspot-" + i;
      b.dataset.position = h.position;
      b.dataset.normal = h.normal;
      b.setAttribute("aria-label", h.label + " — открыть в каталоге");
      b.innerHTML = `<span>${esc(h.label)}</span>`;
      b.addEventListener("click", () => { location.hash = h.target; });
      mv.appendChild(b);
    });

    const tabs = document.createElement("div");
    tabs.className = "viewer__tabs";
    tabs.innerHTML = '<button type="button" data-v="3d" aria-pressed="true">3D</button><button type="button" data-v="photo" aria-pressed="false">Фото</button>';
    function show(v) {
      mv.hidden = v !== "3d";
      photo.hidden = v === "3d";
      cap.textContent = v === "3d" ? "Крутите мышкой или пальцем" : "Фото Remo Hobby";
      tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === v)));
    }
    tabs.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) show(b.dataset.v); });

    viewer.prepend(mv);
    viewer.appendChild(tabs);
    show("3d");
  }

  $("#part-search")?.addEventListener("input", renderCatalog);
  $("#part-weak")?.addEventListener("change", renderCatalog);
  $("#term-search")?.addEventListener("input", renderGlossary);
  renderGlossary();
  renderCatalog();
  renderGarage();
  initTermPopover();
  initLightbox();
  initModel();
})();
