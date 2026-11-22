async () => {
  const attempt = window.captureAttempt;
  const rows = attempt.rows;
  const legs = attempt.route.legs;
  const routePoints = legs.flatMap((leg) => leg.path);
  const map = document.createElement("canvas");
  map.width = 392;
  map.height = 255;
  const context = map.getContext("2d");
  const bounds = routePoints.reduce(
    ([x0, y0, x1, y1], [x, y]) => [
      Math.min(x0, x),
      Math.min(y0, y),
      Math.max(x1, x),
      Math.max(y1, y),
    ],
    [Infinity, Infinity, -Infinity, -Infinity],
  );
  const [x0, y0, x1, y1] = bounds;
  const unit = Math.min(
    338 / Math.max(10, x1 - x0),
    202 / Math.max(10, y1 - y0),
  );
  const xy = ([x, y]) => [
    196 + (x - (x0 + x1) / 2) * unit,
    127.5 - (y - (y0 + y1) / 2) * unit,
  ];
  const colors = {
    bg: "#0b151e",
    panel: "#12232f",
    text: "#f2f6f8",
    muted: "#b0c3cd",
    cyan: "#65daf0",
    mint: "#8ce8b2",
    gold: "#ffc980",
    grid: "#304551",
  };
  const text = (c, x, y, str, size = 18, color = colors.text, weight = 500) => {
    c.fillStyle = color;
    c.font = weight + " " + size + "px Segoe UI, sans-serif";
    c.fillText(str, x, y);
  };
  const box = (c, x, y, w, h, color) => {
    c.fillStyle = color;
    c.fillRect(x, y, w, h);
  };
  function line(c, pts, color, width = 2) {
    if (!pts.length) return;
    c.beginPath();
    c.lineJoin = "round";
    c.lineCap = "round";
    pts.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y)));
    c.strokeStyle = color;
    c.lineWidth = width;
    c.stroke();
  }
  function dot(c, x, y, r, fill) {
    c.beginPath();
    c.arc(x, y, r, 0, Math.PI * 2);
    c.fillStyle = fill;
    c.fill();
  }
  const mapBounds = await (await fetch("/api/world")).json();
  const atlas = await createImageBitmap(
    await (await fetch("/world.png")).blob(),
  );
  const [left, right, bottom, top] = mapBounds.drive.bounds;
  const topLeft = xy([left, top]);
  box(context, 0, 0, 392, 255, "#162932");
  context.globalAlpha = 0.5;
  context.drawImage(
    atlas,
    topLeft[0],
    topLeft[1],
    (right - left) * unit,
    (top - bottom) * unit,
  );
  context.globalAlpha = 1;
  atlas.close();
  for (const leg of legs) {
    line(context, leg.path.map(xy), "#101d28", 7);
    line(
      context,
      leg.path.map(xy),
      leg.mode === "drive" ? colors.cyan : colors.gold,
      4,
    );
  }
  const trace = document.createElement("canvas");
  trace.width = 392;
  trace.height = 255;
  const traceCtx = trace.getContext("2d");
  let drawn = -1;
  const stamp = (n) =>
    Math.floor(n / 60) + ":" + String(Math.floor(n % 60)).padStart(2, "0");
  const duration = rows.at(-1).simTime;
  const speedKey = rows.every((row) => Number.isFinite(row.groundSpeed))
    ? "groundSpeed"
    : "speed";
  const commandCap = Math.max(
    50,
    Math.ceil(Math.max(...rows.map((r) => r.commandMs)) / 25) * 25,
  );
  const speedCap = Math.max(
    5,
    Math.ceil(
      Math.max(...rows.map((r) => Math.max(r[speedKey], r.requestedSpeed))) / 5,
    ) * 5,
  );
  const supportCap = Math.max(
    25,
    Math.ceil(Math.max(...rows.map((r) => r.inliers)) / 25) * 25,
  );
  const lastDrive = legs.findLastIndex((l) => l.mode === "drive");
  function chart(c, x, y, w, label, unitText, cap, series, idx, t) {
    const lo = Math.max(0, t - 12),
      hi = Math.max(12, t);
    const top = y + 45,
      height = 73;
    const latency = series[0][0] === "commandMs";
    const scale = (value) =>
      latency ? Math.log1p(Math.max(0, value)) / Math.log1p(cap) : value / cap;
    text(c, x, y + 17, label, 19, colors.text, 600);
    if (idx >= 0) {
      const val = rows[idx][series[0][0]];
      text(
        c,
        x,
        y + 40,
        (series[0][0] === speedKey ? val.toFixed(1) : Math.round(val)) +
          " " +
          unitText,
        15,
        series[0][1],
      );
    }
    for (const v of [0, 0.5, 1])
      line(
        c,
        [
          [x, top + v * height],
          [x + w, top + v * height],
        ],
        colors.grid,
        1,
      );
    const from = Math.max(0, idx - Math.ceil(12 / attempt.dt) - 1);
    c.save();
    c.beginPath();
    c.rect(x, top - 2, w, height + 4);
    c.clip();
    for (const [key, color] of series) {
      const pts = [];
      for (let j = from; j <= idx; j++) {
        const r = rows[j];
        pts.push([
          x + ((r.simTime - lo) / (hi - lo)) * w,
          top + height - height * Math.min(1, Math.max(0, scale(r[key]))),
        ]);
      }
      line(c, pts, color, 2.4);
      if (pts.length) dot(c, ...pts.at(-1), 2.5, color);
    }
    c.restore();
    text(c, x, top + height + 21, stamp(lo), 13, colors.muted);
    c.textAlign = "right";
    text(c, x + w, top + height + 21, stamp(hi), 13, colors.muted);
    text(
      c,
      x + w,
      y + 40,
      (latency ? "лог. шкала · " : "") + String(cap),
      13,
      colors.muted,
    );
    c.textAlign = "left";
  }
  function bar(c, x, y, name, value, color, signed = false) {
    text(c, x, y, name, 15, colors.muted);
    const left = x + 85,
      width = 215,
      mid = left + width / 2;
    box(c, left, y - 9, width, 5, colors.grid);
    if (signed) {
      const length = (Math.min(1, Math.abs(value) / 1.65) * width) / 2;
      box(c, value < 0 ? mid - length : mid, y - 10, length, 7, color);
      box(c, mid - 1, y - 13, 2, 13, colors.text);
    } else
      box(c, left, y - 10, Math.min(1, Math.max(0, value)) * width, 7, color);
    c.textAlign = "right";
    text(
      c,
      x + 371,
      y,
      signed
        ? Math.round((value * 180) / Math.PI) + "°/с"
        : Math.round(value * 100) + "%",
      14,
      colors.text,
    );
    c.textAlign = "left";
  }
  window.paintJourneyDashboard = (c, src, s, t, w, h) => {
    c.save();
    c.scale(w / 1600, h / 900);
    box(c, 0, 0, 1600, 900, colors.bg);
    text(c, 26, 30, "SPHERE LAB   /   BLACK RUSSIA", 15, colors.cyan, 650);
    text(c, 26, 66, attempt.title, 33, colors.text, 650);
    c.textAlign = "right";
    text(
      c,
      1574,
      34,
      "Геометрический стенд  ·  камера от первого лица",
      18,
      colors.muted,
    );
    text(c, 1574, 64, stamp(t) + " / " + stamp(duration), 20, colors.text, 600);
    c.textAlign = "left";
    const vx = 24,
      vy = 85,
      vw = 1112,
      vh = 625.5;
    c.drawImage(src, vx, vy, vw, vh);
    c.save();
    c.beginPath();
    c.rect(vx, vy, vw, vh);
    c.clip();
    const projected = journey
      .projectRoute(s)
      .map((p) => p && [vx + p[0] * vw, vy + p[1] * vh]);
    let segment = [];
    for (const point of [...projected, null]) {
      if (point) segment.push(point);
      else if (segment.length) {
        line(c, segment, "rgba(7,37,51,.69)", 5);
        line(c, segment, "rgba(113,235,238,.93)", 2.4);
        segment = [];
      }
    }
    c.restore();
    box(c, 1152, 85, 424, 625.5, colors.panel);
    text(c, 1168, 117, "Маршрут и положение", 22, colors.text, 650);
    c.drawImage(map, 1168, 132);
    const idx = Math.min(
      rows.length - 1,
      Math.floor((t + 1e-7) / attempt.dt) - 1,
    );
    if (idx < drawn) {
      traceCtx.clearRect(0, 0, 392, 255);
      drawn = -1;
    }
    for (let j = Math.max(1, drawn + 1); j <= idx; j++)
      line(
        traceCtx,
        [xy(rows[j - 1].actual), xy(rows[j].actual)],
        colors.mint,
        2,
      );
    drawn = idx;
    c.drawImage(trace, 1168, 132);
    const [mx, my] = xy(s.p);
    for (const [name, pt] of [
      ["A", routePoints[0]],
      ["B", routePoints.at(-1)],
    ]) {
      const [x, y] = xy(pt);
      dot(c, 1168 + x, 132 + y, 8, colors.bg);
      text(c, 1168 + x - 5, 136 + y, name, 12, colors.text, 700);
    }
    c.save();
    c.translate(1168 + mx, 132 + my);
    c.rotate(-s.yaw);
    c.beginPath();
    c.moveTo(9, 0);
    c.lineTo(-6, -5);
    c.lineTo(-4, 0);
    c.lineTo(-6, 5);
    c.closePath();
    c.fillStyle = colors.mint;
    c.strokeStyle = colors.bg;
    c.lineWidth = 2;
    c.fill();
    c.stroke();
    c.restore();
    text(c, 1168, 410, "Пешком", 15, colors.gold);
    text(c, 1250, 410, "За рулём", 15, colors.cyan);
    text(c, 1350, 410, "Ход бота", 15, colors.mint);
    const stage = s.done
      ? "Финиш"
      : s.mounted
        ? "За рулём " + journey.vehicleName
        : lastDrive < 0
          ? "Пешком до цели"
          : s.index < lastDrive
            ? "Пешком к транспорту"
            : "Пешком до цели";
    text(c, 1168, 452, stage, 24, colors.text, 650);
    const row = rows[Math.max(0, idx)];
    text(
      c,
      1168,
      482,
      idx < 0
        ? "Ожидание первого кадра"
        : row.visualConfirmed
          ? "Положение подтверждено"
          : "Положение по прогнозу",
      16,
      row.visualConfirmed ? colors.mint : colors.gold,
    );
    const walking = row.mode === "walk";
    bar(c, 1168, 525, walking ? "Ускорение" : "Газ", idx < 0 ? 0 : row.throttle, colors.mint);
    bar(c, 1168, 555, walking ? "Замедление" : "Тормоз", idx < 0 ? 0 : row.brake, colors.gold);
    bar(c, 1168, 585, walking ? "Поворот" : "Руль", idx < 0 ? 0 : row.steering, colors.cyan, true);
    const progress = Math.min(
      1,
      Math.max(0, s.distance / Math.max(0.001, journey.length)),
    );
    text(c, 1168, 643, "По маршруту", 16, colors.muted);
    text(
      c,
      1168,
      675,
      Math.round(s.distance) + " / " + Math.round(journey.length) + " ед.",
      22,
      colors.text,
      600,
    );
    box(c, 1168, 690, 392, 4, colors.grid);
    box(c, 1168, 690, 392 * progress, 4, colors.mint);
    box(c, 24, 729, 1552, 150, colors.panel);
    chart(
      c,
      42,
      736,
      470,
      speedKey === "groundSpeed" ? "Темп  /  цель" : "Оценка темпа  /  цель",
      "ед./с",
      speedCap,
      [
        [speedKey, colors.cyan],
        ["requestedSpeed", colors.gold],
      ],
      idx,
      t,
    );
    chart(
      c,
      558,
      736,
      470,
      "Опоры в кадре",
      "опор",
      supportCap,
      [["inliers", colors.mint]],
      idx,
      t,
    );
    chart(
      c,
      1075,
      736,
      480,
      "От кадра до команды",
      "мс",
      commandCap,
      [["commandMs", colors.gold]],
      idx,
      t,
    );
    c.restore();
  };
};
