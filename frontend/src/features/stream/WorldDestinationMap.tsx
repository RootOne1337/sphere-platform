"use client";

import { useEffect, useRef, useState } from "react";
import { Crosshair, Layers, Maximize, Minus, Plus } from "lucide-react";
import {
  worldService,
  type Decision,
  type WorldInfo,
  type XYZ,
} from "./worldDestination";
import styles from "./worldConsole.module.css";

type XY = [number, number];
type Camera = { x: number; y: number; zoom: number };
const districts = [
  { name: "Нижегородск", x: -2400, y: 2500 },
  { name: "Арзамас", x: 707, y: 633 },
  { name: "Южный", x: 2570, y: -2370 },
  { name: "Батырево", x: 1778, y: 2110 },
];
const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, v));
type Props = {
  info: WorldInfo;
  point: XY | null;
  decision: Decision | null;
  origin: XYZ | null;
  observation: XYZ | null;
  preview: XYZ[];
  onChoose: (x: number, y: number) => void;
};
export function WorldDestinationMap(props: Props) {
  const { info } = props;
  const canvas = useRef<HTMLCanvasElement>(null);
  const latest = useRef(props);
  const actions = useRef<{
    go: (id: string) => void;
    zoom: (n: number) => void;
    render: () => void;
  } | null>(null);
  const [roads, setRoads] = useState(false),
    [coverage, setCoverage] = useState(true);
  const [sector, setSector] = useState("world"),
    [mapError, setMapError] = useState(false),
    [retry, setRetry] = useState(0);
  const layers = useRef({ roads, coverage });
  useEffect(() => {
    latest.current = props;
    layers.current = { roads, coverage };
    actions.current?.render();
  }, [props, roads, coverage]);
  useEffect(() => {
    const el = canvas.current!;
    const ctx = el.getContext("2d", { alpha: false });
    if (!ctx || !info.tiles) {
      setMapError(true);
      return;
    }
    const [left, right, bottom, top] = info.bounds;
    const { tileSize, width: iw, height: ih, revision } = info.tiles;
    const wWorld = right - left,
      hWorld = top - bottom;
    let w = 0,
      h = 0,
      frame = 0,
      alive = true;
    const camera: Camera = {
      x: (left + right) / 2,
      y: (top + bottom) / 2,
      zoom: 1,
    };
    const fit = () => Math.min(w / wWorld, h / hWorld) * 0.96;
    const scale = () => fit() * camera.zoom;
    const images = new Map<string, HTMLImageElement>();
    const pointer = new Map<number, XY>();
    let dragged = false,
      origin: XY = [0, 0];
    function render() {
      if (alive && !frame) frame = requestAnimationFrame(draw);
    }
    function image(key: string) {
      const old = images.get(key);
      if (old) return old;
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.decoding = "async";
      img.onload = render;
      img.onerror = () => {
        if (alive && key === "terrain/overview") setMapError(true);
      };
      img.src = worldService + "/tiles/" + revision + "/" + key + ".webp";
      images.set(key, img);
      return img;
    }
    function pixel(x: number, y: number): XY {
      return [
        (x - camera.x) * scale() + w / 2,
        (camera.y - y) * scale() + h / 2,
      ];
    }
    function world(x: number, y: number): XY {
      return [
        (x - w / 2) / scale() + camera.x,
        camera.y - (y - h / 2) / scale(),
      ];
    }
    function limit() {
      const s = scale(),
        dx = Math.min(w / (2 * s), wWorld / 2),
        dy = Math.min(h / (2 * s), hWorld / 2);
      camera.x = clamp(camera.x, left + dx, right - dx);
      camera.y = clamp(camera.y, bottom + dy, top - dy);
    }
    function zoomAt(n: number, x = w / 2, y = h / 2) {
      const anchor = world(x, y);
      camera.zoom = clamp(camera.zoom * n, 1, 128);
      camera.x = anchor[0] - (x - w / 2) / scale();
      camera.y = anchor[1] + (y - h / 2) / scale();
      limit();
      render();
    }
    function go(id: string) {
      const area = districts.find((d) => d.name === id);
      const region = info.searchRegions?.find(
        (item) => "search-" + item.name === id,
      );
      const trace = region?.points ?? info.atlas.visualTrace;
      if (id === "position" && latest.current.observation) {
        [camera.x, camera.y] = latest.current.observation;
        camera.zoom = clamp(Math.min(w, h) / 260 / fit(), 1, 128);
      } else if ((id === "coverage" || region) && trace.length) {
        const xx = trace.map((p) => p[0]),
          yy = trace.map((p) => p[1]);
        camera.x = (Math.min(...xx) + Math.max(...xx)) / 2;
        camera.y = (Math.min(...yy) + Math.max(...yy)) / 2;
        camera.zoom = clamp(
          Math.min(
            w / (Math.max(...xx) - Math.min(...xx) + 55),
            h / (Math.max(...yy) - Math.min(...yy) + 55),
          ) / fit(),
          1,
          128,
        );
      } else if (area) {
        camera.x = area.x;
        camera.y = area.y;
        camera.zoom = clamp(Math.min(w, h) / 650 / fit(), 1, 128);
      } else {
        camera.x = (left + right) / 2;
        camera.y = (bottom + top) / 2;
        camera.zoom = 1;
      }
      setSector(id);
      limit();
      render();
    }
    function plot(points: XYZ[], color: string, width: number) {
      if (points.length < 2) return;
      ctx!.beginPath();
      points.forEach(([x, y], i) => {
        const [a, b] = pixel(x, y);
        if (i) ctx!.lineTo(a, b);
        else ctx!.moveTo(a, b);
      });
      ctx!.strokeStyle = color;
      ctx!.lineWidth = width;
      ctx!.lineJoin = "round";
      ctx!.lineCap = "round";
      ctx!.stroke();
    }
    function draw() {
      frame = 0;
      if (!alive || w <= 0 || h <= 0 || !ctx) return;
      const dpr = el.width / w;
      ctx.setTransform(dpr, 0, 0, el.height / h, 0, 0);
      ctx.fillStyle = "#1b3039";
      ctx.fillRect(0, 0, w, h);
      const s = scale(),
        [x0, y0] = pixel(left, top),
        mw = wWorld * s,
        mh = hWorld * s;
      function paint(layer: string) {
        if (!ctx) return;
        const overview = image(layer + "/overview");
        if (overview.complete && overview.naturalWidth)
          ctx.drawImage(overview, x0, y0, mw, mh);
        if (mh * dpr <= 1024 && mw * dpr <= 1024) return;
        const sx = mw / iw,
          sy = mh / ih;
        const firstCol = Math.max(0, Math.floor(-x0 / (tileSize * sx))),
          lastCol = Math.min(
            Math.ceil(iw / tileSize) - 1,
            Math.floor((w - x0) / (tileSize * sx)),
          );
        const firstRow = Math.max(0, Math.floor(-y0 / (tileSize * sy))),
          lastRow = Math.min(
            Math.ceil(ih / tileSize) - 1,
            Math.floor((h - y0) / (tileSize * sy)),
          );
        for (let row = firstRow; row <= lastRow; row++)
          for (let col = firstCol; col <= lastCol; col++) {
            const tile = image(layer + "/" + col + "-" + row);
            if (tile.complete && tile.naturalWidth)
              ctx.drawImage(
                tile,
                x0 + col * tileSize * sx,
                y0 + row * tileSize * sy,
                tile.naturalWidth * sx,
                tile.naturalHeight * sy,
              );
          }
      }
      paint("terrain");
      if (layers.current.roads) {
        ctx.globalAlpha = 0.55;
        paint("roads");
        ctx.globalAlpha = 1;
      }
      if (layers.current.coverage)
        plot(
          info.atlas.visualTrace,
          "rgba(72,227,222,.8)",
          clamp(info.atlas.coverageRadius * 2 * s, 2, 18),
        );
      if (layers.current.coverage)
        for (const region of info.searchRegions ?? []) {
          ctx.fillStyle = "rgba(198,164,242,.45)";
          ctx.beginPath();
          for (const [x, y] of region.points) {
            const [a, b] = pixel(x, y),
              radius = Math.max(1.3, region.radius * s);
            ctx.moveTo(a + radius, b);
            ctx.arc(a, b, radius, 0, Math.PI * 2);
          }
          ctx.fill();
        }
      if (camera.zoom < 8) {
        ctx.font = "600 12px system-ui";
        ctx.textAlign = "center";
        for (const d of districts) {
          const [x, y] = pixel(d.x, d.y);
          ctx.lineWidth = 3.5;
          ctx.strokeStyle = "#17282c";
          ctx.strokeText(d.name, x, y);
          ctx.fillStyle = "#fff";
          ctx.fillText(d.name, x, y);
        }
      }
      const { point, decision, origin, preview } = latest.current;
      if (!decision?.path) plot(preview, "#ffce76", 3);
      if (decision?.path) plot(decision.path, "#68f3a8", 3);
      for (const [p, color] of [
        [latest.current.observation, "#c9aaff"],
        [origin, "#b8f39b"],
        [point, "#ffb957"],
        [decision?.pose?.eye, "#51dbe5"],
      ] as const) {
        if (!p) continue;
        const [x, y] = pixel(p[0], p[1]);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x, y, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#15252c";
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      const power = 10 ** Math.floor(Math.log10(82 / s));
      const meters = ([5, 2, 1].find((n) => n * power * s <= 82) ?? 1) * power,
        bar = meters * s;
      ctx.textAlign = "left";
      ctx.font = "11px system-ui";
      ctx.fillStyle = "#102329de";
      ctx.fillRect(10, h - 36, Math.max(54, bar + 15), 27);
      ctx.fillStyle = "#e5f3ef";
      ctx.fillText(
        meters >= 1000 ? meters / 1000 + " км" : Math.round(meters) + " м",
        17,
        h - 23,
      );
      ctx.fillRect(17, h - 17, bar, 2);
    }
    function resize() {
      const box = el.getBoundingClientRect();
      w = box.width;
      h = box.height;
      if (!w || !h) return;
      const dpr = Math.min(devicePixelRatio || 1, 2);
      el.width = Math.round(w * dpr);
      el.height = Math.round(h * dpr);
      limit();
      render();
    }
    function local(e: { clientX: number; clientY: number }): XY {
      const r = el.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    }
    function choose(x: number, y: number) {
      const [wx, wy] = world(x, y);
      if (wx >= left && wx <= right && wy >= bottom && wy <= top)
        latest.current.onChoose(wx, wy);
    }
    function down(e: PointerEvent) {
      if (e.button !== 0) return;
      el.focus({ preventScroll: true });
      el.setPointerCapture(e.pointerId);
      const xy = local(e);
      if (!pointer.size) {
        origin = xy;
        dragged = false;
      } else dragged = true;
      pointer.set(e.pointerId, xy);
    }
    function move(e: PointerEvent) {
      const prev = pointer.get(e.pointerId);
      if (!prev) return;
      const p = local(e);
      const other = [...pointer].find(([id]) => id !== e.pointerId)?.[1];
      if (!dragged && Math.hypot(p[0] - origin[0], p[1] - origin[1]) < 4)
        return;
      dragged = true;
      el.style.cursor = "grabbing";
      setSector("custom");
      pointer.set(e.pointerId, p);
      if (other) {
        const before = Math.hypot(prev[0] - other[0], prev[1] - other[1]),
          after = Math.hypot(p[0] - other[0], p[1] - other[1]);
        if (before > 2 && after > 2)
          zoomAt(
            after / before,
            (prev[0] + other[0]) / 2,
            (prev[1] + other[1]) / 2,
          );
      }
      const div = other ? 2 : 1;
      camera.x -= (p[0] - prev[0]) / scale() / div;
      camera.y += (p[1] - prev[1]) / scale() / div;
      limit();
      render();
    }
    function up(e: PointerEvent) {
      if (!pointer.has(e.pointerId)) return;
      const [x, y] = local(e);
      if (
        !dragged &&
        e.type === "pointerup" &&
        Math.hypot(x - origin[0], y - origin[1]) < 4
      )
        choose(x, y);
      pointer.delete(e.pointerId);
      if (!pointer.size) el.style.cursor = "grab";
    }
    function wheel(e: WheelEvent) {
      e.preventDefault();
      const [x, y] = local(e);
      setSector("custom");
      zoomAt(
        Math.exp(
          -clamp(
            e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? h : 1),
            -400,
            400,
          ) * 0.0028,
        ),
        x,
        y,
      );
    }
    function key(e: KeyboardEvent) {
      const delta: Record<string, XY> = {
        ArrowLeft: [-1, 0],
        ArrowRight: [1, 0],
        ArrowUp: [0, 1],
        ArrowDown: [0, -1],
      };
      if (delta[e.key]) {
        const [dx, dy] = delta[e.key];
        camera.x += (dx * w) / 5 / scale();
        camera.y += (dy * h) / 5 / scale();
        limit();
        render();
        setSector("custom");
      } else if (["=", "+", "-"].includes(e.key))
        zoomAt(e.key === "-" ? 1 / 1.6 : 1.6);
      else if (e.key === "Home") go("world");
      else if (e.key === "Enter") choose(w / 2, h / 2);
      else return;
      e.preventDefault();
    }
    actions.current = {
      go,
      zoom: (n) => {
        setSector("custom");
        zoomAt(n);
      },
      render,
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    el.addEventListener("lostpointercapture", up);
    el.addEventListener("wheel", wheel, { passive: false });
    el.addEventListener("keydown", key);
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      observer.disconnect();
      actions.current = null;
      for (const img of images.values()) {
        img.onload = null;
        img.onerror = null;
      }
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      el.removeEventListener("lostpointercapture", up);
      el.removeEventListener("wheel", wheel);
      el.removeEventListener("keydown", key);
    };
  }, [info, retry]);
  useEffect(() => {
    if (props.observation) actions.current?.go("position");
    else setSector((id) => (id === "position" ? "custom" : id));
  }, [props.observation]);
  return (
    <>
      <div className={styles.mapbar}>
        <label className={styles.selectLabel}>
          <span>Район</span>
          <select
            aria-label="Район карты"
            value={sector}
            onChange={(e) => actions.current?.go(e.target.value)}
          >
            <option value="world">Вся карта</option>
            {districts.map((d) => (
              <option key={d.name}>{d.name}</option>
            ))}
            {props.observation && (
              <option value="position">Последняя проверка</option>
            )}
            <option value="coverage">Кремль · автопоездка</option>
            {info.searchRegions?.map((r) => (
              <option key={r.name} value={"search-" + r.name}>
                {r.name} · проверка кадра
              </option>
            ))}
            {sector === "custom" && (
              <option value="custom">Свой масштаб</option>
            )}
          </select>
        </label>
        <details className={styles.layers}>
          <summary>
            <Layers size={15} />
            Слои
          </summary>
          <div>
            <label>
              <input
                type="checkbox"
                checked={roads}
                onChange={(e) => setRoads(e.target.checked)}
              />
              Дороги
            </label>
            <label>
              <input
                type="checkbox"
                checked={coverage}
                onChange={(e) => setCoverage(e.target.checked)}
              />
              Визуальные ориентиры
            </label>
          </div>
        </details>
      </div>
      <div className={styles.mapViewport}>
        <canvas
          ref={canvas}
          tabIndex={0}
          aria-label="Карта Black Russia. Стрелки перемещают карту, плюс и минус меняют масштаб, Enter ставит метку в центре."
        />
        <div className={styles.zoomGroup}>
          <button
            title="Приблизить"
            aria-label="Приблизить"
            onClick={() => actions.current?.zoom(1.6)}
          >
            <Plus size={17} />
          </button>
          <button
            title="Отдалить"
            aria-label="Отдалить"
            onClick={() => actions.current?.zoom(1 / 1.6)}
          >
            <Minus size={17} />
          </button>
          <button
            title="Вся карта"
            aria-label="Вся карта"
            onClick={() => actions.current?.go("world")}
          >
            <Maximize size={15} />
          </button>
          <button
            title="К ориентирам"
            aria-label="К ориентирам"
            onClick={() => actions.current?.go("coverage")}
          >
            <Crosshair size={16} />
          </button>
        </div>
        {mapError && (
          <button
            className={styles.tileError}
            onClick={() => {
              setMapError(false);
              setRetry((n) => n + 1);
            }}
          >
            Подложка недоступна · Повторить
          </button>
        )}
      </div>
    </>
  );
}
