const finitePoint = (point, count) => Array.isArray(point) && point.length === count && point.every(Number.isFinite);

function interpolate(a, b, y) {
  const t = (y - a[1]) / (b[1] - a[1]);
  return a.map((coordinate, i) => coordinate + (b[i] - coordinate) * t);
}

function laneAt(lane, y) {
  let low = 0;
  let high = lane.points.length - 1;
  while (high - low > 1) {
    const middle = (high + low) >> 1;
    if (lane.points[middle][1] <= y) low = middle;
    else high = middle;
  }
  return interpolate(lane.points[low], lane.points[high], y);
}

/** A geometry-only preview of measured lane strips. */
function createLanePlanner(surface, asset) {
  if (!asset || asset.schema !== 'sphere.lane-preview.v1'
      || ['worldId', 'areaId', 'mapRevision'].some(key => surface[key] !== asset[key])
      || surface.sources.orthomapSha256 !== asset.orthomapSha256
      || !Array.isArray(asset.lanes) || asset.lanes.length < 1
      || !Array.isArray(asset.separators) || asset.separators.length !== asset.lanes.length + 1) {
    throw new Error('lane layer belongs to another map revision');
  }
  const walls = asset.separators.map(separator => separator.ends);
  const [yMin, yMax] = walls[0].map(point => point[1]);
  if (!(yMin < yMax) || walls.some(line => line.length !== 2
      || !finitePoint(line[0], 2) || !finitePoint(line[1], 2)
      || line[0][1] !== yMin || line[1][1] !== yMax)) {
    throw new Error('invalid painted boundaries');
  }
  const lanes = asset.lanes;
  const ids = new Set();
  for (let i = 0; i < lanes.length; i++) {
    const lane = lanes[i];
    const [a, b] = walls.slice(i, i + 2);
    if (typeof lane.id !== 'string' || ids.has(lane.id) || lane.direction !== 'unverified'
        || !Number.isFinite(lane.min_static_clearance_units)
        || lane.min_static_clearance_units < surface.minClearance
        || !Array.isArray(lane.points) || lane.points.length < 2
        || lane.points.some(point => !finitePoint(point, 3))
        || lane.points[0][1] !== yMin || lane.points.at(-1)[1] !== yMax
        || lane.points.some((point, index) => {
          if (index && point[1] <= lane.points[index - 1][1]) return true;
          const left = interpolate(a[0], a[1], point[1])[0];
          const right = interpolate(b[0], b[1], point[1])[0];
          return point[0] - left < surface.minClearance || right - point[0] < surface.minClearance;
        })) {
      throw new Error('invalid lane centerline');
    }
    ids.add(lane.id);
  }

  function snap(point) {
    if (!finitePoint(point, 2) && !finitePoint(point, 3)) return null;
    const [x, y, z] = point;
    if (y < yMin || y > yMax) return null;
    const limits = walls.map(([a, b]) => interpolate(a, b, y)[0]);
    const margin = .25;
    const index = limits.findIndex((left, i) => left + margin <= x && x <= limits[i + 1] - margin);
    if (index < 0) return null;
    const lane = lanes[index];
    const xyz = laneAt(lane, y);
    if (z !== undefined && Math.abs(z - xyz[2]) > .6) return null;
    return {laneId: lane.id, xyz, distance: Math.abs(x - xyz[0])};
  }

  function plan(a, b) {
    const start = snap(a);
    const goal = snap(b);
    if (!start || !goal) return {status: 'unreachable', reason: start ? 'goal' : 'start', start, goal};
    if (start.laneId !== goal.laneId) return {status: 'unreachable', reason: 'no_verified_lane_connection', start, goal};
    const lane = lanes.find(candidate => candidate.id === start.laneId);
    const forward = start.xyz[1] <= goal.xyz[1];
    const interior = lane.points.filter(point => Math.min(start.xyz[1], goal.xyz[1]) < point[1]
      && point[1] < Math.max(start.xyz[1], goal.xyz[1]));
    const points = [start.xyz, ...(forward ? interior : interior.reverse()), goal.xyz];
    let length = 0;
    for (let i = 1; i < points.length; i++) {
      length += Math.hypot(...points[i].map((value, axis) => value - points[i - 1][axis]));
    }
    return {status: 'preview', mode: 'lane', executionQualified: false,
      mapRevision: asset.mapRevision, laneId: lane.id, direction: lane.direction,
      start, goal, points, length, minClearance: lane.min_static_clearance_units};
  }

  return {plan, snap};
}

export {createLanePlanner};
