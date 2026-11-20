const d = JSON.parse(document.getElementById("data").textContent),
  $ = (id) => document.getElementById(id),
  fmt = (n, k = 1) => n.toLocaleString("ru", { maximumFractionDigits: k }),
  mode = (m) => (m === "drive" ? "Транспорт" : "Пешком");
const mk = (tag, txt) => {
    const e = document.createElement(tag);
    e.textContent = txt;
    return e;
  },
  link = (name, url) => {
    const a = mk("a", name);
    a.href = url;
    return a;
  },
  ns = "http://www.w3.org/2000/svg",
  map = $("map"),
  marker = $("markers");
const xyz = (p) => p.map((v) => fmt(v, 2)).join(" · "),
  url = (p) =>
    (location.protocol === "file:" ? "http://127.0.0.1:8817" : "") +
    "/detail?" +
    new URLSearchParams({ x: p[0], y: p[1], z: p[2] }),
  source = (s) => s?.surfaces?.[0]?.slice(1).join(" · ") || "Не определён";
let selected = null,
  records = [],
  center = [0, -256],
  width = 7200,
  drag = null;
function stat(a, b) {
  const el = mk("div", "");
  el.append(mk("b", a), mk("small", b));
  $("stats").append(el);
}
for (const m of ["drive", "walk"]) {
  const s = d.summary[m];
  stat(
    s.after + " / " + s.total,
    mode(m) + " · раньше " + s.before + " / " + s.total,
  );
}
stat(d.sites.length, "Проверенных мест");
stat(
  fmt(d.scene.placedTriangles / 1e6, 1) + " млн",
  "Треугольников наружных моделей",
);
function redraw() {
  const aspect = map.clientHeight / Math.max(1, map.clientWidth);
  map.setAttribute(
    "viewBox",
    [
      center[0] - width / 2,
      center[1] - (width * aspect) / 2,
      width,
      width * aspect,
    ].join(" "),
  );
  marker.replaceChildren();
  const r = width / Math.max(1, map.clientWidth);
  function point(p, txt, color, action, small = false) {
    const g = document.createElementNS(ns, "g"),
      c = document.createElementNS(ns, "circle"),
      t = document.createElementNS(ns, "text");
    g.setAttribute("transform", "translate(" + p[0] + "," + -p[1] + ")");
    c.setAttribute("r", (small ? 6 : 10) * r);
    c.setAttribute("fill", color);
    c.setAttribute("stroke", "#0d1d24");
    c.setAttribute("stroke-width", 2 * r);
    g.append(c);
    t.setAttribute("x", 12 * r);
    t.setAttribute("y", (txt === "A" || txt === "B" ? -12 : 4) * r);
    t.setAttribute("font-size", 13 * r);
    t.setAttribute("fill", "#fff");
    t.setAttribute("stroke", "#14232a");
    t.setAttribute("stroke-width", 3 * r);
    t.setAttribute("paint-order", "stroke");
    t.textContent = txt;
    g.append(t);
    g.style.cursor = "pointer";
    g.onpointerdown = (e) => e.stopPropagation();
    g.onclick = (e) => {
      e.stopPropagation();
      action();
    };
    marker.append(g);
  }
  const lines =
    selected?.lines ??
    (selected?.after?.path
      ? [{ mode: selected.mode, path: selected.after.path }]
      : []);
  for (const leg of lines) {
    if (!leg.path.length) continue;
    const line = document.createElementNS(ns, "polyline");
    line.setAttribute(
      "points",
      leg.path.map((p) => p[0] + "," + -p[1]).join(" "),
    );
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", leg.mode === "walk" ? "#ffe2a1" : "#56e4ef");
    line.setAttribute("stroke-width", 3 * r);
    if (leg.mode === "walk")
      line.setAttribute("stroke-dasharray", 5 * r + " " + 3 * r);
    line.setAttribute("pointer-events", "none");
    marker.append(line);
  }
  const clusters = [];
  for (const row of records) {
    const p = (row.site || row).position;
    const near = clusters.find(
      (c) => Math.hypot(c.p[0] - p[0], c.p[1] - p[1]) < 16 * r,
    );
    if (near) near.rows.push(row);
    else clusters.push({ p, rows: [row] });
  }
  for (const c of clusters) {
    const row = c.rows.includes(selected) ? selected : c.rows[0],
      ok = (row.site ? row.status : row.after.status) === "complete";
    point(
      c.p,
      c.rows.map((it) => it.id).join(" / "),
      ok ? "#9de6b2" : "#ffb37d",
      () => choose(c.rows[(c.rows.indexOf(selected) + 1) % c.rows.length]),
      row !== selected,
    );
  }
  if (selected?.points)
    selected.points.forEach((p, i) =>
      point(
        p,
        i ? "B" : "A",
        "#acd9ea",
        () => {
          center = [p[0], -p[1]];
          width = 120;
          redraw();
        },
        true,
      ),
    );
}
function fit() {
  const aspect = map.clientHeight / map.clientWidth;
  const [l, h, b, t] = d.bounds;
  center = [(l + h) / 2, -(b + t) / 2];
  width = 1.04 * Math.max(h - l, (t - b) / aspect);
  redraw();
}
function field(k, v) {
  $("values").append(mk("dt", k), mk("dd", v));
}
function choose(row) {
  selected = row;
  if (!row) return;
  if (location.protocol !== "file:") {
    const address = new URL(location.href);
    address.searchParams.set("case", row.id);
    history.replaceState(null, "", address.href);
  }
  const s = row.site || row,
    pair = !!row.site,
    ok = (pair ? row.status : s.after.status) === "complete";
  $("type").textContent =
    mode(s.mode) + " · " + (pair ? "контрольная пара" : "прежняя граница сети");
  $("title").textContent = (pair ? "Маршрут " : "Участок ") + row.id;
  $("status").textContent = ok
    ? "Путь построен"
    : pair && row.mixed?.modes.length
      ? s.mode === "drive"
        ? "До конца на транспорте проезд не найден"
        : "Весь путь пешком не найден"
      : "Связь пока отсутствует";
  $("status").className = ok ? "ok" : "bad";
  $("reason").textContent = row.reason;
  $("values").replaceChildren();
  field("Участок · XYZ", xyz(s.position));
  if (pair) {
    field("A · XYZ", xyz(row.points[0]));
    field("B · XYZ", xyz(row.points[1]));
    field("Модель у A", source(row.rays[0]));
    field("Модель у B", source(row.rays[1]));
    if (row.mixed)
      field(
        "Путь при смене режима",
        row.mixed.modes.length
          ? row.mixed.modes.map(mode).join(" → ") +
              " · " +
              fmt(row.mixed.length) +
              " ед."
          : "Не найден",
      );
    if (row.alternatives)
      field("Проверено переходов", row.alternatives.sites.length);
  }
  field("Материал между краями", s.materials.join(", "));
  if (ok)
    field("Длина по сетке", fmt(pair ? row.length : s.after.length) + " ед.");
  $("links").replaceChildren(link("Участок в 3D", url(s.position)));
  if (pair)
    $("links").append(
      link("Старт в 3D", url(row.points[0])),
      link("Цель в 3D", url(row.points[1])),
    );
  $("profile").replaceChildren(
    ...s.profile.map((p, i) => {
      const tr = mk("tr", "");
      for (const v of [fmt((i / 16) * 100, 0) + "%", p.floor, p.road, p.water])
        tr.append(mk("td", v === null ? "—" : v));
      return tr;
    }),
  );
  for (const b of $("choices").children)
    b.setAttribute("aria-pressed", String(b.textContent === row.id));
  redraw();
}
function filter() {
  const group = $("filter").value;
  records =
    group === "sites"
      ? d.sites
      : d.failures.filter(
          (r) => (r.status === "complete") === (group === "fixed"),
        );
  $("choices").replaceChildren(
    ...records.map((r) => {
      const b = mk("button", r.id);
      b.onclick = () => choose(r);
      return b;
    }),
  );
  choose(
    records.find(
      (r) => r.id === new URLSearchParams(location.search).get("case"),
    ) || records[0],
  );
  fit();
}
$("filter").onchange = filter;
$("all").onclick = fit;
$("zoom").onclick = () => {
  const s = selected.site || selected;
  center = [s.position[0], -s.position[1]];
  width = 200;
  redraw();
};
map.onwheel = (e) => {
  e.preventDefault();
  width = Math.max(
    25,
    Math.min(18000, width * Math.exp(Math.sign(e.deltaY) * 0.22)),
  );
  redraw();
};
map.onpointerdown = (e) => {
  drag = [e.clientX, e.clientY, ...center];
  map.setPointerCapture(e.pointerId);
};
map.onpointermove = (e) => {
  if (!drag) return;
  const r = width / map.clientWidth;
  center = [
    drag[2] - (e.clientX - drag[0]) * r,
    drag[3] - (e.clientY - drag[1]) * r,
  ];
  redraw();
};
map.onpointerup = async (e) => {
  if (!drag) return;
  const dist = Math.hypot(e.clientX - drag[0], e.clientY - drag[1]);
  drag = null;
  if (dist > 5) return;
  const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(
      map.getScreenCTM().inverse(),
    ),
    x = p.x,
    y = -p.y,
    div = $("place");
  let levels = [];
  try {
    const r = await fetch(
      "/api/levels?" + new URLSearchParams({ mode: "walk", x, y }),
    );
    levels = (await r.json()).levels;
  } catch {}
  div.replaceChildren(
    mk(
      "p",
      "Выбранная точка · " +
        xyz([x, y]) +
        (levels.length ? " · выбрать высоту" : " · опорная высота неизвестна"),
    ),
  );
  for (const z of levels) div.append(link("3D · Z " + fmt(z), url([x, y, z])));
  div.scrollIntoView({ block: "nearest" });
};
const perf = [];
for (const m of ["drive", "walk"]) {
  const s = d.summary[m];
  perf.push(
    mode(m) +
      " · p95 " +
      fmt(s.timing.cluster.complete.p95, 2) +
      " мс, полный поиск по той же сетке " +
      fmt(s.timing.unrestricted.complete.p95, 2) +
      " мс.",
  );
}
$("performance").textContent =
  perf.join(" ") +
  " Замер от запроса на загруженной карте до получения пути, включая список координат. Пешеходная сетка уточнена до 0,125 ед. в " +
  d.summary.walk.manifest.refinedTiles.length +
  " тайлах. Базовый шаг 0,25 ед.";
$("performance").textContent +=
  " По исходной коллизии проверено " +
  d.support.drive.samples +
  " точек на каждом профиле. Ошибка высоты p95 на транспорте " +
  fmt(d.support.drive.heightP95, 2) +
  " ед., пешком " +
  fmt(d.support.walk.heightP95, 2) +
  " ед.";
if (d.httpTiming)
  $("performance").textContent +=
    " В локальном HTTP API при 1, 10 и 20 одновременных клиентах p95 составил " +
    [1, 10, 20].map((n) => fmt(d.httpTiming[n].p95, 1)).join(" / ") +
    " мс. Замер включает передачу полного пути.";
const image = map.querySelector("image"),
  [left, right, bottom, upper] = d.bounds;
for (const [k, v] of Object.entries({
  x: left,
  y: -upper,
  width: right - left,
  height: upper - bottom,
}))
  image.setAttribute(k, v);
const requested = new URLSearchParams(location.search).get("case");
if (d.sites.some((row) => row.id === requested)) $("filter").value = "sites";
else if (
  d.failures.some((row) => row.id === requested && row.status === "complete")
)
  $("filter").value = "fixed";
filter();
new ResizeObserver(redraw).observe(map);
