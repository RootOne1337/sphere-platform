const SURFACE_SCHEMA = 'sphere.raster-surface.v1';

function decodeBytes(value, expectedLength) {
  if (typeof value !== 'string' || value.length !== Math.ceil(expectedLength / 3) * 4) {
    throw new Error('invalid surface stream length');
  }
  const raw = atob(value);
  if (raw.length !== expectedLength) throw new Error('invalid surface stream');
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

/** Plans a preview on one verified surface layer. Position coordinates are in world units. */
function createPlanner(tile) {
  if (tile?.schema !== SURFACE_SCHEMA || typeof tile.worldId !== 'string' || !tile.worldId
      || typeof tile.areaId !== 'string' || !tile.areaId || !/^[a-f0-9]{64}$/.test(tile.mapRevision)
      || !['drive', 'walk'].includes(tile.mode)) {
    throw new Error('invalid surface identity');
  }
  const {worldId, mapRevision, areaId, mode, minClearance, maxGrade} = tile;
  const {width, height, step, left, top, baseZ} = tile.grid ?? {};
  const cellCount = width * height;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0
      || cellCount > 1_000_000 || ![step, left, top, baseZ].every(Number.isFinite) || step < .1 || step > 4
      || !Number.isFinite(minClearance) || minClearance < 0 || minClearance > 10
      || !Number.isFinite(maxGrade) || maxGrade <= 0 || maxGrade > 1) {
    throw new Error('invalid surface grid');
  }
  const free = decodeBytes(tile.free, cellCount);
  const clearance = new DataView(decodeBytes(tile.clearanceCentiUnits, cellCount * 2).buffer);
  const heights = new DataView(decodeBytes(tile.heightCentiUnits, cellCount * 2).buffer);
  const surfaceHeight = i => baseZ + heights.getInt16(i * 2, true) / 100;
  const clearanceAt = i => clearance.getUint16(i * 2, true) / 100;
  const available = i => i >= 0 && i < cellCount && free[i] === 1 && clearanceAt(i) >= minClearance;
  const world = i => [left + (i % width + .5) * step, top - (Math.floor(i / width) + .5) * step, surfaceHeight(i)];
  const at = (col, row) => col < 0 || col >= width || row < 0 || row >= height ? -1 : row * width + col;

  function snap(point) {
    if (!Array.isArray(point) || ![2, 3].includes(point.length) || !point.every(Number.isFinite)) return null;
    const [x, y, z] = point;
    const col = Math.floor((x - left) / step);
    const row = Math.floor((top - y) / step);
    if (at(col, row) < 0) return null;
    const snapRadius = 2.5;
    const maxHeightDifference = .6;
    const span = Math.ceil(snapRadius / step);
    let best = null;
    let bestScore = Infinity;
    for (let r = Math.max(0, row - span); r <= Math.min(height - 1, row + span); r++) {
      for (let c = Math.max(0, col - span); c <= Math.min(width - 1, col + span); c++) {
        const index = at(c, r);
        if (!available(index)) continue;
        const xyz = world(index);
        const distance = Math.hypot(xyz[0] - x, xyz[1] - y);
        const heightDifference = z === undefined ? 0 : Math.abs(xyz[2] - z);
        const score = Math.hypot(distance, heightDifference);
        if (distance <= snapRadius && heightDifference <= maxHeightDifference && score < bestScore) {
          best = {index, xyz, distance, heightDifference: z === undefined ? null : heightDifference};
          bestScore = score;
        }
      }
    }
    return best;
  }

  function adjacency(i, j, scale) {
    return available(j) && Math.abs(surfaceHeight(i) - surfaceHeight(j)) <= maxGrade * step * scale + .01;
  }

  function plan(a, b) {
    const start = snap(a), goal = snap(b);
    if (!start || !goal) return {status: 'unreachable', reason: start ? 'goal' : 'start', start, goal};
    const open = [];
    function push(item) {
      let i = open.length;
      open.push(item);
      while (i > 0) {
        const parent = (i-1) >> 1;
        if (open[parent].priority <= item.priority) break;
        open[i] = open[parent];
        i = parent;
      }
      open[i] = item;
    }
    function pop() {
      const first = open[0];
      const item = open.pop();
      if (open.length) {
        let i = 0;
        while (i*2+1 < open.length) {
          let child = i*2+1;
          if (child+1 < open.length && open[child+1].priority < open[child].priority) child++;
          if (open[child].priority >= item.priority) break;
          open[i] = open[child];
          i = child;
        }
        open[i] = item;
      }
      return first;
    }
    const prev = new Int32Array(cellCount).fill(-1);
    const cost = new Float64Array(cellCount).fill(Infinity);
    const targetCol = goal.index % width, targetRow = Math.floor(goal.index/width);
    cost[start.index] = 0;
    push({i:start.index,g:0,priority:0});
    let visited = 0;
    while (open.length) {
      const {i,g} = pop();
      if (g !== cost[i]) continue;
      visited++;
      if (i === goal.index) {
        const path = [];
        for (let current = i; current >= 0; current = prev[current]) path.push(current);
        path.reverse();
        let length = 0, minClearance = Infinity;
        const points = path.map((p,k) => {
          const xyz = world(p);
          if (k) {
            const last = world(path[k-1]);
            length += Math.hypot(xyz[0] - last[0], xyz[1] - last[1], xyz[2] - last[2]);
          }
          minClearance = Math.min(minClearance,clearanceAt(p));
          return xyz;
        });
        return {
          status: 'preview', worldId, mapRevision, areaId, mode, points, start, goal, length, minClearance, visited,
        };
      }
      const col = i % width, row = Math.floor(i / width);
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          if (!dx && !dy) continue;
          const scale = dx && dy ? Math.SQRT2 : 1;
          const j = at(col + dx, row + dy);
          if (!adjacency(i,j,scale)) continue;
          if (dx && dy) {
            const h = at(col + dx, row), v = at(col, row + dy);
            if (!adjacency(i,h,1) || !adjacency(i,v,1) || !adjacency(h,j,1) || !adjacency(v,j,1)) continue;
          }
          const tentative = g + step * scale * (1 + .85 / (.35 + clearanceAt(j)));
          if (tentative >= cost[j]) continue;
          cost[j] = tentative;
          prev[j] = i;
          const remaining = step * Math.hypot(col + dx - targetCol, row + dy - targetRow);
          push({i: j, g: tentative, priority: tentative + remaining});
        }
      }
    }
    return {status: 'unreachable', reason: 'disconnected', start, goal};
  }

  return {plan, snap, available};
}

export {createPlanner};
