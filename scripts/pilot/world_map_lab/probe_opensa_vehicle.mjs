import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import RAPIER from "@dimforge/rapier3d-compat";
import { parseDff } from "renderware/parsers/binary/dff.ts";
import { parseDffCollision } from "renderware/parsers/binary/col.ts";
import { buildVehicle } from "renderware/three/build-vehicle.ts";
import { PhysicsWorld } from "game/physics/physics-world.ts";

const [archive, output] = process.argv.slice(2);
if (
  !archive ||
  !output ||
  !/^[a-f0-9]{40}$/.test(process.env.OPENSA_REVISION ?? "")
)
  throw new Error("Expected IMG path, output JSON and OPENSA_REVISION");

const parameters = {
  hz: 60,
  settleSeconds: 2,
  commandSeconds: 3,
  mass: 1000,
  wheelScale: [0.55, 0.55],
  force: 4200,
  ground: "flat static collider",
};

function readBlock(fd, size, offset) {
  const buf = Buffer.alloc(size);
  if (fs.readSync(fd, buf, 0, size, offset) !== size)
    throw new Error("Incomplete IMG block");
  return buf;
}

function readModels(archive) {
  const fd = fs.openSync(archive, "r");
  try {
    const head = readBlock(fd, 8, 0);
    if (8 + head.readUInt32LE(4) * 32 > fs.fstatSync(fd).size)
      throw new Error("Truncated IMG directory");
    if (head.toString("ascii", 0, 4) !== "VER2")
      throw new Error("Expected VER2 IMG");
    const directory = readBlock(fd, head.readUInt32LE(4) * 32, 8);
    const results = new Map();
    for (let i = 0; i < directory.length; i += 32) {
      const name = directory
        .toString("ascii", i + 8, i + 32)
        .split("\0")[0]
        .toLowerCase();
      if (!["faggio.dff", "premier.dff"].includes(name)) continue;
      if (results.has(name))
        throw new Error("Ambiguous vehicle entry: " + name);
      const size =
        directory.readUInt16LE(i + 6) || directory.readUInt16LE(i + 4);
      const buf = readBlock(fd, size * 2048, directory.readUInt32LE(i) * 2048);
      results.set(name, buf);
    }
    if (results.size !== 2) throw new Error("Both models must exist in input");
    return results;
  } finally {
    fs.closeSync(fd);
  }
}

function trial(col, wheels, force) {
  const world = new PhysicsWorld(RAPIER);
  try {
    world.createStaticBox([0, 0, -0.5], [200, 200, 0.5]);
    const extents = col.bounds.max.map((v, i) =>
      Math.max(Math.abs(v), Math.abs(col.bounds.min[i])),
    );
    const shape = {
      boxes: col.boxes,
      spheres: col.spheres,
      vertices: col.vertices,
      indices: Uint32Array.from(col.faces.flatMap((f) => [f.a, f.b, f.c])),
    };
    const { body, controller } = world.createDynamicVehicle(
      [0, 0, 1],
      0,
      shape,
      parameters.mass,
      wheels,
      extents,
    );
    const dt = 1 / parameters.hz;
    for (let i = 0; i < parameters.settleSeconds * parameters.hz; i++) world.step(dt);
    const start = world.readBody(body).position;
    for (let i = 0; i < parameters.commandSeconds * parameters.hz; i++) {
      world.setVehicleControls(controller, wheels, force, 0, 0);
      world.step(dt);
    }
    const end = world.readBody(body).position;
    return {
      deltaXY: [end[0] - start[0], end[1] - start[1]],
      controllerWheels: controller.numWheels(),
    };
  } finally {
    world.dispose();
  }
}

await RAPIER.init();
const models = {};
for (const [name, buf] of readModels(archive)) {
  const data = buf.buffer.slice(
    buf.byteOffset,
    buf.byteOffset + buf.byteLength,
  );
  const clump = parseDff(data);
  const col = parseDffCollision(data);
  if (!col) throw new Error("Missing model collision " + name);
  const white = [255, 255, 255];
  const model = buildVehicle(clump, new Map(), {
    primary: white,
    secondary: white,
    tertiary: white,
    quaternary: white,
    wheelScale: parameters.wheelScale,
  });
  const wheels = model.wheels.map((w) => ({
    connection: w.connection,
    radius: w.radius,
    front: w.front,
  }));
  const coast = trial(col, wheels, 0);
  const power = trial(col, wheels, parameters.force);
  models[name] = {
    sectorPaddedSha256: createHash("sha256").update(buf).digest("hex"),
    wheelFrameNames: clump.frames
      .map((f) => f.name)
      .filter((n) => /wheel/i.test(n)),
    collision: {
      version: col.version,
      boxes: col.boxes.length,
      spheres: col.spheres.length,
      triangles: col.faces.length,
    },
    coast,
    power,
    inputEffectXY: Math.hypot(
      power.deltaXY[0] - coast.deltaXY[0],
      power.deltaXY[1] - coast.deltaXY[1],
    ),
  };
}
const report = {
  archive: path.basename(archive),
  openSARevision: process.env.OPENSA_REVISION,
  parameters,
  models,
};
fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify(report));
