import { createWorld } from "/journey/scene.mjs";
import { integrateVehicle } from "/journey/vehicle.mjs";
import { Itinerary } from "/journey/path.mjs";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search),
  capture = params.has("capture");
const get = async (path, args) => {
  const r = await fetch(path + (args ? "?" + new URLSearchParams(args) : ""));
  if (!r.ok) throw Error("Ошибка загрузки " + r.status + " · " + path);
  return r.json();
};
const canvas = $("world"),
  held = new Set();
const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
const distance = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));
const azimuth = (a, b) => Math.atan2(b[1] - a[1], b[0] - a[0]);
const fmt = (n) => Math.round(n).toLocaleString("ru-RU");
async function main() {
  const [config, server] = await Promise.all([
    get("/journey/route.json"),
    get("/api/world"),
  ]);
  const free = params.has("start") && !params.has("end");
  let origin,
    mounted = params.get("mode") === "drive";
  if (free) {
    origin = params.get("start").split(",").map(Number);
    if (origin.length !== 3 || !origin.every(Number.isFinite))
      throw Error("Неверные координаты старта");
    const { levels } = await get("/api/levels", {
      x: origin[0],
      y: origin[1],
      mode: mounted ? "drive" : "walk",
    });
    const level = levels.sort(
      (a, b) => Math.abs(a - origin[2]) - Math.abs(b - origin[2]),
    )[0];
    if (level === undefined || Math.abs(level - origin[2]) > 0.38)
      throw Error("На выбранной высоте нет опоры");
    origin[2] = level;
  }
  const replay = capture ? window.captureAttempt : null;
  let route = replay?.route ?? config;
  if (params.has("start") && params.has("end")) {
    const q = new URLSearchParams();
    for (const key of ["mode", "start", "end", "vehicle"])
      if (params.has(key)) q.set(key, params.get(key));
    const result = await get("/api/path", q);
    if (result.status !== "complete")
      throw Error("Для выбранных точек нет связного маршрута");
    route = result.legs
      ? result
      : { legs: [{ mode: q.get("mode"), path: result.path }] };
  }
  const model = params.get("model") === "premier" ? "premier" : "faggio",
    vehicleName = model === "faggio" ? "Faggio" : "Premier";
  $("model").value = model;
  $("model").onchange = () => {
    const u = new URL(location.href);
    u.searchParams.set("model", $("model").value);
    location.href = u.href;
  };
  const [world, atlas] = await Promise.all([
    createWorld(canvas, config, model),
    createImageBitmap(await (await fetch("/journey/terrain.jpg")).blob()),
  ]);
  const trip = free
      ? null
      : new Itinerary(route, {
          eyeHeight: world.eyeHeight,
          topSpeed: world.bike ? 24 : 37,
        }),
    drive = trip?.legs.find((l) => l.mode === "drive"),
    initial = free
      ? { p: origin, yaw: 0, mounted, distance: 0 }
      : trip.sample(0);
  const bounds = config.terrain.bounds;
  const map = document.createElement("canvas");
  map.width = 640;
  map.height = 640;
  const mp = map.getContext("2d");
  const mapXY = (p) => [
    ((p[0] - bounds.left) / (bounds.right - bounds.left)) * map.width,
    ((bounds.top - p[1]) / (bounds.top - bounds.bottom)) * map.height,
  ];
  mp.fillStyle = "#0b1822";
  mp.fillRect(0, 0, 640, 640);
  mp.globalAlpha = 0.75;
  mp.drawImage(atlas, 0, 0, 640, 640);
  mp.globalAlpha = 1;
  for (const leg of trip?.legs ?? []) {
    for (const [width, color] of [
      [6, "#132930"],
      [3.2, leg.mode === "walk" ? "#ffda95" : "#5bffdd"],
    ]) {
      mp.strokeStyle = color;
      mp.lineWidth = width;
      mp.lineJoin = "round";
      mp.beginPath();
      leg.points.forEach((p, i) => {
        const [x, y] = mapXY(p);
        if (i === 0) mp.moveTo(x, y);
        else mp.lineTo(x, y);
      });
      mp.stroke();
    }
  }
  const radar = $("radar").getContext("2d");
  function drawMap(ctx, x, y, size, p, yaw) {
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(size / 640, size / 640);
    ctx.drawImage(map, 0, 0);
    const [a, b] = mapXY(p);
    ctx.translate(a, b);
    ctx.rotate(-yaw);
    ctx.beginPath();
    ctx.moveTo(15, 0);
    ctx.lineTo(-9, -9);
    ctx.lineTo(-5, 0);
    ctx.lineTo(-9, 9);
    ctx.closePath();
    ctx.lineWidth = 4;
    ctx.strokeStyle = "#162631";
    ctx.fillStyle = "white";
    ctx.stroke();
    ctx.fill();
    ctx.restore();
  }
  let parked,
    carYaw,
    pose,
    manualPitch,
    rolling,
    t = 0,
    following = false,
    changed = false,
    epoch = 0,
    notice = "";
  let steer = 0,
    lean = 0,
    grade = 0,
    lookYaw = 0;
  function reset() {
    steer = lean = grade = lookYaw = 0;
    epoch++;
    parked = drive?.points[0] ?? (free && mounted ? origin : null);
    carYaw = drive ? azimuth(drive.points[0], trip.at(drive, 3)) : 0;
    pose = { ...initial, p: [...initial.p] };
    manualPitch = -0.045;
    rolling = 0;
    t = 0;
    following = false;
    changed = false;
    notice = "";
    held.clear();
  }
  reset();
  function carFor(sample) {
    if (!drive) {
      world.vehicle(null, 0, false);
      return;
    }
    const passed = trip.legs[sample.index].start > drive.start;
    const at = passed ? drive.points.at(-1) : drive.points[0];
    const yaw = passed
      ? azimuth(trip.at(drive, drive.length - 2), at)
      : azimuth(at, trip.at(drive, 2));
    if (sample.mounted) {
      const leg = trip.legs[sample.index],
        station = sample.distance - leg.distance;
      const p = trip.at(leg, Math.max(0, station - 1)),
        q = trip.at(leg, station),
        r = trip.at(leg, Math.min(leg.length, station + 1));
      const bend =
        station > 1 && station < leg.length - 1
          ? Math.atan2(
              Math.sin(azimuth(q, r) - azimuth(p, q)),
              Math.cos(azimuth(q, r) - azimuth(p, q)),
            )
          : 0;
      world.vehicle(
        sample.p,
        sample.yaw,
        true,
        Math.atan(world.profile.wheelbase * bend),
        clamp(Math.atan((sample.speed ** 2 * bend) / 9.81), -0.32, 0.32),
      );
    } else world.vehicle(at, yaw, false);
    return [at, yaw];
  }
  function drawSample(sample) {
    carFor(sample);
    world.draw(sample.camera);
  }
  let runId = null,
    pilotBusy = false,
    lastPoll = 0,
    measurement = null,
    blend = null;
  const storageKey = "journey-rgb:" + location.search;
  function showRun(id) {
    runId = id;
    sessionStorage.setItem(storageKey, id);
    $("traceLink").href = "/api/journey/trace?" + new URLSearchParams({ id });
    $("traceLink").hidden = false;
  }
  if (!capture && !free) {
    const saved = sessionStorage.getItem(storageKey);
    if (saved) {
      try {
        const res = await get("/api/journey/state", { id: saved });
        if (["starting", "running"].includes(res.state)) showRun(saved);
        else sessionStorage.removeItem(storageKey);
      } catch {
        sessionStorage.removeItem(storageKey);
      }
    }
  }
  const post = async (name, data) => {
    const r = await fetch("/api/journey/" + name, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const result = await r.json();
    if (!r.ok) throw Error(result.error || "Стенд недоступен");
    return result;
  };
  const outcomes = {
    starting: "Запуск камеры",
    running: "Управление по изображению",
    arrived: "Финиш подтверждён",
    stopped: "Остановлено",
    time_limit: "Исчерпано время",
    surface_blocked: "Движение ограничила поверхность",
    localization_lost: "Потеряно визуальное положение",
    finish_mismatch: "Положение финиша не подтверждено",
    transfer_out_of_reach: "Место пересадки не достигнуто",
    worker_failed: "Ошибка процесса проверки",
  };
  async function startPilot() {
    if (pilotBusy) return;
    pilotBusy = true;
    try {
      if (runId) {
        await post("stop", { id: runId });
        notice = "Останавливаем проверку";
        return;
      }
      reset();
      const data = { model, mode: params.get("mode") ?? "trip" };
      for (const k of ["start", "end", "vehicle"])
        if (params.has(k)) data[k] = params.get(k).split(",").map(Number);
      const res = await post("start", data);
      showRun(res.id);
      lastPoll = 0;
      measurement = blend = null;
      notice = outcomes.starting;
    } catch (e) {
      notice = e.message;
    } finally {
      pilotBusy = false;
      controls();
    }
  }
  $("pilot").onclick = startPilot;
  async function pollRun(now) {
    if (blend) {
      const f = clamp((now - blend.at) / 200, 0, 1);
      pose.p = blend.from.map((v, i) => v + (blend.to[i] - v) * f);
      pose.yaw = blend.start + blend.turn * f;
    }
    if (now - lastPoll < 80) return;
    lastPoll = now;
    const res = await get("/api/journey/state", { id: runId });
    const previous = measurement;
    measurement = res.row;
    if (measurement) {
      const m = measurement;
      if (m.frame !== previous?.frame) {
        blend = {
          at: now,
          from: [...pose.p],
          to: m.actual,
          start: pose.yaw,
          turn: Math.atan2(
            Math.sin(m.yaw - pose.yaw),
            Math.cos(m.yaw - pose.yaw),
          ),
        };
      }
      pose.mode = m.mode;
      pose.mounted = m.mode === "drive";
      pose.index = m.phase;
      pose.distance = m.distance;
      if (drive && trip.legs[m.phase].start > drive.start) {
        parked = drive.points.at(-1);
        carYaw = azimuth(trip.at(drive, drive.length - 2), parked);
      }
      manualPitch = -0.045;
      lookYaw = m.pan;
      steer = Math.atan(
        (world.profile.wheelbase * m.steering) / Math.max(1, Math.abs(m.speed)),
      );
      lean = world.bike ? Math.atan((m.speed * m.steering) / 9.81) : 0;
    }
    notice =
      (outcomes[res.state] ?? res.state) +
      (measurement
        ? " · " +
          measurement.inliers +
          " опор · " +
          Math.round(measurement.matchMs) +
          " мс"
        : "");
    if (!["starting", "running"].includes(res.state)) {
      if (measurement) {
        pose.p = measurement.actual;
        pose.yaw = measurement.yaw;
      }
      sessionStorage.removeItem(storageKey);
      runId = null;
      blend = null;
      changed = true;
      rolling = 0;
    }
  }
  function controls() {
    const near = parked && distance(pose.p, parked) < 4;
    $("board").disabled =
      following || !(pose.mounted ? Math.abs(rolling) < 0.7 : near);
    $("board").textContent = pose.mounted
      ? "Выйти · F"
      : "Сесть · " + vehicleName + " · F";
    $("follow").hidden = free;
    $("pilot").hidden = free;
    $("pilot").disabled = free || pilotBusy;
    $("pilot").textContent = runId
      ? "Остановить проверку"
      : "Запустить по изображению";
    $("model").disabled = !!runId;
    $("follow").disabled = free || !!runId;
    $("follow").textContent = following
      ? "Приостановить"
      : changed
        ? "Показать маршрут со старта"
        : t > 0 && t < trip.duration
          ? "Продолжить маршрут"
          : "Показать маршрут";
    $("reset").disabled = !!runId;
    if (runId) $("board").disabled = true;
    $("movieLink").hidden = !server.journeyMovie;
    $("reportLink").hidden = !server.journeyReport;
    $("gameplayLink").hidden = !server.gameplay;
    $("mode").textContent = pose.mounted ? "За рулём" : "Пешком";
    $("message").textContent =
      notice ||
      (following
        ? pose.transfer
          ? pose.mounted
            ? "Парковка и выход"
            : "Посадка · " + vehicleName
          : "Поездка по плану"
        : "Ручное управление");
    $("progress").textContent =
      changed || free
        ? "X " + pose.p[0].toFixed(1) + "  ·  Y " + pose.p[1].toFixed(1)
        : fmt(pose.distance) + " / " + fmt(trip.length) + " ед.";
    drawMap(radar, 0, 0, 320, pose.p, pose.yaw);
  }
  function stop() {
    epoch++;
    following = false;
    held.clear();
    rolling = 0;
    controls();
  }
  async function board() {
    if ($("board").disabled) return;
    const id = ++epoch;
    if (pose.mounted) {
      const levels = (
        await get("/api/levels", { mode: "walk", x: pose.p[0], y: pose.p[1] })
      ).levels;
      const z = levels.sort(
        (a, b) => Math.abs(a - pose.p[2]) - Math.abs(b - pose.p[2]),
      )[0];
      if (epoch !== id) return;
      if (z === undefined || Math.abs(z - pose.p[2]) > 0.42) {
        notice = "Здесь нет пешеходной поверхности для выхода";
        controls();
        return;
      }
      parked = [...pose.p];
      carYaw = pose.yaw;
      pose.p = [...parked.slice(0, 2), z];
      pose.mounted = false;
    } else {
      pose.p = [...parked];
      pose.yaw = carYaw;
      pose.mounted = true;
    }
    rolling = steer = lean = grade = lookYaw = 0;
    changed = true;
    notice = "";
    controls();
  }
  function toggle() {
    if (free) return;
    if (changed) reset();
    if (t >= trip.duration) reset();
    following = !following;
    notice = "";
    held.clear();
    rolling = 0;
    epoch++;
    controls();
  }
  $("follow").onclick = toggle;
  $("reset").onclick = () => {
    reset();
    controls();
  };
  $("board").onclick = () => board().catch(fail);
  const codes = new Set([
    "KeyW",
    "KeyS",
    "KeyA",
    "KeyD",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
  ]);
  function press(k) {
    if (runId) return;
    if (codes.has(k)) {
      following = false;
      held.add(k);
      notice = "";
    }
  }
  addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (codes.has(e.code)) {
      e.preventDefault();
      press(e.code);
    }
    if (e.code === "KeyF" && !e.repeat) board().catch(fail);
    if (e.code === "Escape") {
      if (runId) startPilot();
      else stop();
    }
  });
  addEventListener("keyup", (e) => held.delete(e.code));
  addEventListener("blur", () => stop());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
  });
  document.querySelectorAll("[data-code]").forEach((b) => {
    b.onpointerdown = (e) => {
      b.setPointerCapture(e.pointerId);
      press(b.dataset.code);
    };
    b.onlostpointercapture = () => held.delete(b.dataset.code);
  });
  let drag = null;
  canvas.onpointerdown = (e) => {
    canvas.focus({ preventScroll: true });
    canvas.setPointerCapture(e.pointerId);
    drag = [e.clientX, e.clientY];
  };
  canvas.onlostpointercapture = () => (drag = null);
  canvas.onpointermove = (e) => {
    if (!drag || following || runId) return;
    if (pose.mounted)
      lookYaw = clamp(lookYaw - (e.clientX - drag[0]) * 0.004, -1.8, 1.8);
    else pose.yaw -= (e.clientX - drag[0]) * 0.004;
    manualPitch = clamp(
      manualPitch - (e.clientY - drag[1]) * 0.003,
      -0.95,
      0.88,
    );
    drag = [e.clientX, e.clientY];
    changed = true;
  };
  const key = (a, b) => Number(held.has(a) || held.has(b));
  let accumulator = 0;
  async function manual(dt) {
    const throttle = key("KeyW", "ArrowUp") - key("KeyS", "ArrowDown"),
      turn = key("KeyA", "ArrowLeft") - key("KeyD", "ArrowRight");
    if (pose.mounted) {
      const next = integrateVehicle(
        { speed: rolling, steer, lean },
        { axis: throttle, turn, grade },
        world.profile,
        model,
        dt,
      );
      rolling = next.speed;
      steer = next.steer;
      lean = next.lean;
      pose.yaw += next.turn;
    } else {
      rolling += clamp(throttle * 3.1 - rolling, -18 * dt, 18 * dt);
      if (turn) {
        pose.yaw += turn * 1.9 * dt;
        changed = true;
      }
    }
    accumulator = Math.min(0.14, accumulator + dt);
    if (accumulator >= 0.045 && Math.abs(rolling) > 0.015) {
      const d = rolling * accumulator;
      accumulator = 0;
      const id = epoch;
      const dest = [
        pose.p[0] + d * Math.cos(pose.yaw),
        pose.p[1] + d * Math.sin(pose.yaw),
      ];
      const r = await get("/api/step", {
        mode: pose.mounted ? "drive" : "walk",
        start: pose.p.join(","),
        xy: dest.join(","),
      });
      if (id !== epoch) return;
      if (r.moved) {
        grade =
          0.65 * grade +
          0.35 * clamp((r.position[2] - pose.p[2]) / d, -0.35, 0.35);
        pose.p = r.position;
        changed = true;
        notice = "";
      } else {
        rolling = 0;
        notice = "Граница доступной поверхности";
      }
    } else if (Math.abs(rolling) < 0.015) accumulator = 0;
  }
  const api = {
    model,
    vehicleName,
    duration: replay?.rows.at(-1)?.simTime ?? trip?.duration ?? 0,
    length: trip?.length ?? 0,
    legs: (trip?.legs ?? []).map(({ start, end, mode, length }) => ({
      start,
      end,
      mode,
      length,
    })),
    state: () => ({
      p: pose.p,
      yaw: pose.yaw,
      mounted: pose.mounted,
      changed,
      following,
      t,
      ...world.stats(),
    }),
    projectRoute(sample) {
      const leg = trip.legs[sample.index];
      const station = Math.max(0, sample.distance - leg.distance);
      const end = Math.min(leg.length, station + (sample.mounted ? 34 : 15));
      const pixels = [];
      const v = world.camera.position.clone();
      for (let d = station; d <= end; d += 0.7) {
        const p = trip.at(leg, d);
        v.set(p[0], p[1], p[2] + 0.07).project(world.camera);
        pixels.push(
          v.z > -1 && v.z < 1 && Math.abs(v.x) < 1.1 && Math.abs(v.y) < 1.1
            ? [(v.x + 1) / 2, (1 - v.y) / 2]
            : null,
        );
      }
      return pixels;
    },
    async frame(time, w, h) {
      if (!trip) throw Error("В свободном режиме маршрут не выбран");
      if (replay) {
        const rows = replay.rows;
        const sampleIndex = clamp(
          Math.floor((time + 1e-7) / replay.dt) - 1,
          0,
          rows.length - 1,
        );
        const a = rows[sampleIndex],
          b = rows[Math.min(sampleIndex + 1, rows.length - 1)];
        const f =
          a.phase === b.phase ? clamp((time - a.simTime) / replay.dt, 0, 1) : 0;
        const p = a.actual.map((v, i) => v + (b.actual[i] - v) * f);
        const yaw =
          a.yaw +
          Math.atan2(Math.sin(b.yaw - a.yaw), Math.cos(b.yaw - a.yaw)) * f;
        const mounted = a.mode === "drive",
          pan = a.pan + (b.pan - a.pan) * f;
        const parkedAtEnd = drive && trip.legs[a.phase].start > drive.start;
        const at = parkedAtEnd ? drive.points.at(-1) : drive?.points[0];
        const heading = drive
          ? parkedAtEnd
            ? azimuth(trip.at(drive, drive.length - 2), at)
            : azimuth(at, trip.at(drive, 2))
          : 0;
        world.size(w, h);
        await world.ensure(...p);
        world.vehicle(
          mounted ? p : at,
          mounted ? yaw : heading,
          mounted,
          Math.atan(
            (world.profile.wheelbase * a.steering) /
              Math.max(1, Math.abs(a.speed)),
          ),
          world.bike
            ? clamp(Math.atan((a.speed * a.steering) / 9.81), -0.43, 0.43)
            : 0,
        );
        world.draw([
          p[0],
          p[1],
          p[2] + (mounted ? world.eyeHeight : 1.68),
          yaw + pan,
          -0.045 + 0.004 * Math.sin((a.frame - 1) * 0.13),
        ]);
        return {
          p,
          yaw,
          index: a.phase,
          mounted,
          speed: a.groundSpeed ?? a.speed,
          distance: a.distance,
          done: time >= rows.at(-1).simTime && replay.result === "arrived",
          observed: a,
        };
      }
      const s = trip.sample(time);
      world.size(w, h);
      await world.ensure(...s.p);
      drawSample(s);
      return s;
    },
    drawMap,
  };
  let last = performance.now(),
    w = 0,
    h = 0;
  async function tick(now) {
    const dt = Math.min(0.1, Math.max(0, (now - last) * 0.001));
    last = now;
    if (runId) await pollRun(now);
    else if (following) {
      t = Math.min(trip.duration, t + dt);
      pose = trip.sample(t);
      const car = carFor(pose);
      if (car) [parked, carYaw] = car;
      if (t >= trip.duration) {
        following = false;
        notice = "Финиш";
      }
      manualPitch = pose.camera[4];
    } else await manual(dt);
    const rect = canvas.getBoundingClientRect(),
      wid = Math.max(2, Math.round(rect.width)),
      hei = Math.max(2, Math.round(rect.height));
    if (wid !== w || hei !== h) {
      world.size(wid, hei);
      w = wid;
      h = hei;
    }
    await world.ensure(...pose.p);
    if (!following)
      world.vehicle(
        pose.mounted ? pose.p : parked,
        pose.mounted ? pose.yaw : carYaw,
        pose.mounted,
        steer,
        lean,
      );
    world.draw([
      pose.p[0],
      pose.p[1],
      pose.p[2] +
        (following
          ? pose.camera[2] - pose.p[2]
          : pose.mounted
            ? world.eyeHeight
            : 1.68),
      pose.yaw + ((runId || pose.mounted) && !following ? lookYaw : 0),
      manualPitch,
    ]);
    controls();
    requestAnimationFrame((n) => tick(n).catch(fail));
  }
  await world.ensure(...pose.p);
  window.journey = api;
  controls();
  if (!capture) requestAnimationFrame((n) => tick(n).catch(fail));
}
function fail(e) {
  $("message").textContent = e.message;
  window.journeyError = e.message;
  console.error(e);
}
main().catch(fail);
