// Read-only diagnostics for the classic SA wasm32 memory layout used by the test engine.
function inspectNativeSurfaces(wasm, state, ids) {
  if (state !== 9) return null;
  const buffer = wasm.memory.buffer;
  const words = new Uint32Array(buffer);
  const floats = new Float32Array(buffer);
  const shorts = new Uint16Array(buffer);
  const bytes = new Uint8Array(buffer);
  const word = (address) => words[address >>> 2];
  const float = (address) => floats[address >>> 2];
  const visible = new Set();
  // Each native array ends at the next fixed symbol, irrespective of the reported count.
  for (const [array, count, capacity] of [
    [0xb748f8, 0xb76840, 1000],
    [0xb75898, 0xb76844, 1000],
    [0xb74830, 0xb76838, 50],
  ]) {
    for (let i = 0; i < Math.min(capacity, word(count)); i++) {
      visible.add(word(array + i * 4));
    }
  }
  const models = new Map();
  for (const id of ids) {
    const info = word(0xa9b0c8 + id * 4);
    if (!info) continue;
    const col = word(info + 0x14);
    models.set(id, {
      load: bytes[0x8e4cc0 + id * 20 + 16],
      modelRw: Boolean(word(info + 28)),
      draw: float(info + 24),
      colbox: col ? Array.from(floats.subarray(col / 4, col / 4 + 10)) : null,
      instances: [],
    });
  }
  for (const address of [0xb74498, 0xb744a0]) {
    const pool = word(address);
    if (!pool) continue;
    const objects = word(pool);
    const flags = word(pool + 4);
    const count = Math.min(32768, word(pool + 8));
    for (let i = 0; i < count; i++) {
      if (bytes[flags + i] & 128) continue;
      const entity = objects + i * 0x38;
      const model = models.get(shorts[(entity + 0x22) / 2]);
      if (!model) continue;
      const matrix = word(entity + 0x14);
      const pos = matrix ? matrix + 0x30 : entity + 4;
      const lod = word(entity + 48);
      model.instances.push({
        xyz: Array.from(floats.subarray(pos / 4, pos / 4 + 3)),
        flags: word(entity + 28),
        lod: lod ? shorts[(lod + 34) / 2] : null,
        children: bytes[entity + 52],
        rw: Boolean(word(entity + 24)),
        listed: visible.has(entity),
      });
    }
  }
  function countLinks(head, tail) {
    let current = word(head + 8);
    let count = 0;
    while (current && current !== tail && count < 65536) {
      current = word(current + 8);
      count++;
    }
    return count;
  }
  return {
    usedLinks: countLinks(0x9654f0, 0x9654fc),
    freeLinks: countLinks(0x965508, 0x965514),
    streamMiB: word(0x8e4cb4) / 1048576,
    queue: word(0x8e4cb8),
    priority: word(0x8e4ba0),
    models: Object.fromEntries(models),
    visible: word(0xb76844),
    lods: word(0xb76840),
    drawScale: float(0xb6f118),
    far: float(0xb76848),
  };
}
