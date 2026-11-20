const hypot = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));
const rad = (a) => Math.atan2(Math.sin(a), Math.cos(a));
function bracket(axis, value) {
  let a = 0,
    b = axis.length - 1;
  while (a + 1 < b) {
    const mid = (a + b) >> 1;
    if (axis[mid] <= value) a = mid;
    else b = mid;
  }
  return Math.min(a, axis.length - 2);
}
export class Itinerary {
  constructor(route, { eyeHeight = 1.23, topSpeed = 37 } = {}) {
    this.eyeHeight = eyeHeight;
    if (!route.legs?.length) throw Error("Непрерывный маршрут не построен");
    this.legs = [];
    let time = 0,
      distance = 0;
    for (const raw of route.legs) {
      const points = raw.path.filter(
        (p, i, all) => i === 0 || hypot(p, all[i - 1]) > 0.00001,
      );
      if (points.length < 2) continue;
      const s = [0];
      for (let i = 1; i < points.length; i++)
        s.push(s[i - 1] + hypot(points[i], points[i - 1]));
      const drive = raw.mode === "drive",
        length = s.at(-1),
        start = time;
      const leg = { points, s, mode: raw.mode, start, distance, length };
      const stations = Array.from(
        { length: Math.max(2, Math.ceil(length / 1.5)) + 1 },
        (_, i) => (length * i) / Math.max(2, Math.ceil(length / 1.5)),
      );
      const speeds = stations.map((x) => {
        if (!drive) return 3.1;
        const before = this.at(leg, Math.max(0, x - 7)),
          point = this.at(leg, x),
          after = this.at(leg, Math.min(length, x + 7));
        const bend = Math.abs(
          rad(
            Math.atan2(after[1] - point[1], after[0] - point[0]) -
              Math.atan2(point[1] - before[1], point[0] - before[0]),
          ),
        );
        return Math.min(topSpeed, Math.sqrt(6.0 / Math.max(0.0001, bend / 7)));
      });
      speeds[0] = 0;
      speeds[speeds.length - 1] = 0;
      for (let i = 1; i < speeds.length; i++)
        speeds[i] = Math.min(
          speeds[i],
          Math.sqrt(
            speeds[i - 1] ** 2 +
              2 * (drive ? 4 : 2.3) * (stations[i] - stations[i - 1]),
          ),
        );
      for (let i = speeds.length - 2; i >= 0; i--)
        speeds[i] = Math.min(
          speeds[i],
          Math.sqrt(
            speeds[i + 1] ** 2 +
              2 * (drive ? 7 : 3) * (stations[i + 1] - stations[i]),
          ),
        );
      const times = [0];
      for (let i = 1; i < speeds.length; i++)
        times.push(
          times[i - 1] +
            (2 * (stations[i] - stations[i - 1])) /
              Math.max(0.01, speeds[i] + speeds[i - 1]),
        );
      Object.assign(leg, {
        stations,
        speeds,
        times,
        end: start + times.at(-1),
      });
      this.legs.push(leg);
      time = leg.end + 1.6;
      distance += length;
    }
    if (!this.legs.length) throw Error("Маршрут не содержит движения");
    this.length = distance;
    this.duration = this.legs.at(-1).end + 1;
  }
  at(leg, s) {
    const i = bracket(leg.s, s),
      f = Math.min(1, Math.max(0, (s - leg.s[i]) / (leg.s[i + 1] - leg.s[i])));
    return leg.points[i].map((v, j) => v + (leg.points[i + 1][j] - v) * f);
  }
  sample(t) {
    const index = this.legs.findIndex(
      (leg, i) => t < (this.legs[i + 1]?.start ?? Infinity),
    );
    const l = this.legs[index],
      local = Math.max(0, Math.min(t - l.start, l.times.at(-1))),
      i = bracket(l.times, local);
    const dt = local - l.times[i],
      rate = (l.speeds[i + 1] - l.speeds[i]) / (l.times[i + 1] - l.times[i]);
    const v = l.speeds[i] + rate * dt,
      s = Math.min(
        l.length,
        l.stations[i] + dt * (l.speeds[i] + 0.5 * rate * dt),
      ),
      p = this.at(l, s);
    const a = this.at(l, Math.max(0, s - (l.mode === "drive" ? 2 : 0.55))),
      b = this.at(
        l,
        Math.min(
          l.length,
          s + (l.mode === "drive" ? Math.max(2.8, v * 0.45) : 2.2),
        ),
      );
    const yaw = Math.atan2(b[1] - a[1], b[0] - a[0]),
      pitch =
        Math.max(
          -0.16,
          Math.min(
            0.12,
            Math.atan2(b[2] - a[2], Math.hypot(b[0] - a[0], b[1] - a[1])),
          ),
        ) - 0.045;
    const wait = Math.max(0, t - l.end),
      next = this.legs[index + 1];
    let angle = yaw,
      lift = l.mode === "drive" ? this.eyeHeight : 1.68;
    if (wait && next) {
      const q = this.at(next, 2),
        r = next.points[0],
        frac = Math.min(1, wait / 1.6),
        u = frac * frac * (3 - 2 * frac);
      angle += rad(Math.atan2(q[1] - r[1], q[0] - r[0]) - angle) * u;
      lift += (next.mode === "drive" ? this.eyeHeight - lift : 1.68 - lift) * u;
    }
    const mounted = l.mode === "drive";
    return {
      p,
      yaw: angle,
      camera: [p[0], p[1], p[2] + lift, angle, pitch],
      mode: l.mode,
      mounted,
      index,
      transfer: wait > 0 && !!next,
      done: t >= this.legs.at(-1).end,
      distance: l.distance + s,
      speed: v,
    };
  }
}
