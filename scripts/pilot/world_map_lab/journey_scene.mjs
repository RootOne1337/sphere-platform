import * as T from "three";
import { GLTFLoader } from "/detail/js/GLTFLoader.js";

export async function createWorld(canvas, settings, model = "faggio") {
  if (!["faggio", "premier"].includes(model))
    throw Error("Неизвестный транспорт");
  const renderer = new T.WebGLRenderer({
    canvas,
    antialias: true,
    powerPreference: "high-performance",
  });
  const scene = new T.Scene(),
    camera = new T.PerspectiveCamera(62, 1, 0.16, 5500);
  camera.up.set(0, 0, 1);
  scene.fog = new T.FogExp2(0xbbcfda, 0.00135);
  scene.background = new T.Color(0xb9d4e8);
  const sky = new T.Mesh(
    new T.SphereGeometry(4600, 32, 16),
    new T.ShaderMaterial({
      side: T.BackSide,
      depthWrite: false,
      uniforms: {},
      vertexShader:
        "varying vec3 v;void main(){v=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}",
      fragmentShader:
        "varying vec3 v;void main(){vec3 n=normalize(v);float h=max(n.z,0.);vec3 c=mix(vec3(.79,.84,.86),vec3(.23,.52,.77),smoothstep(0.,.82,h));float s=clamp(dot(n,normalize(vec3(-.5,-.72,.43))),0.,1.);c+=vec3(.25,.19,.10)*pow(s,35.)+vec3(.8,.66,.43)*smoothstep(.9997,.99994,s);gl_FragColor=vec4(c,1.);}",
    }),
  );
  sky.frustumCulled = false;
  scene.add(sky);
  const light = new T.HemisphereLight(0xffffef, 0xb7a997, 2.0);
  light.up.set(0, 0, 1);
  light.position.z = 1;
  scene.add(light);
  const sun = new T.DirectionalLight(0xfff3da, 1.7);
  sun.position.set(-100, -150, 170);
  scene.add(sun);
  const get = async (url, type) => {
    const r = await fetch(url);
    if (!r.ok) throw Error("Недоступен ресурс " + url);
    return type === "json" ? r.json() : r.arrayBuffer();
  };
  async function loadModel(url) {
    let lastError;
    for (let attempt = 0; attempt < 3; attempt++) {
      const manager = new T.LoadingManager();
      let missing = null;
      manager.onError = (resource) => {
        missing = resource;
      };
      try {
        const model = await new GLTFLoader(manager).loadAsync(
          new URL(url, location.href).href,
        );
        if (!missing) return model;
        disposeModel(model);
        throw Error("Не загружена текстура " + missing);
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError;
  }
  const [field, top, carAsset, profiles] = await Promise.all([
    get("/journey/horizon.bin"),
    new T.TextureLoader().loadAsync("/journey/terrain.jpg"),
    loadModel("/journey/" + model + ".glb"),
    get("/journey/vehicles.json", "json"),
  ]);
  const car = carAsset.scene;
  scene.add(car);
  const profile = profiles[model],
    bike = model === "faggio";
  const eyeHeight = bike ? profile.lift + profile.seat[2] + 0.61 : 1.23;
  const steerGroup = new T.Group();
  if (bike) {
    steerGroup.position.fromArray(profile.sockets.handlebars);
    car.add(steerGroup);
    car.updateMatrixWorld(true);
    for (const name of [
      "handlebars",
      "forks_front",
      "wheel_front",
      "mudguard",
    ]) {
      const part = car.getObjectByName(name);
      if (part) steerGroup.attach(part);
    }
  }

  top.colorSpace = T.SRGBColorSpace;
  const terrain = settings.terrain,
    { bounds, cols, rows, nx, ny, stride } = terrain;
  const heights = new Int16Array(field),
    vertices = [],
    uv = [],
    indices = [];
  if (heights.length !== cols * rows)
    throw Error("Повреждена дальняя геометрия");
  for (let y = 0; y < rows; y++)
    for (let x = 0; x < cols; x++) {
      const i = y * cols + x,
        u = (x * stride + 0.5) / nx,
        v = (y * stride + 0.5) / ny;
      vertices.push(
        bounds.left + u * (bounds.right - bounds.left),
        bounds.top - v * (bounds.top - bounds.bottom),
        heights[i] / 8 - 1.3,
      );
      uv.push(u, 1 - v);
      if (
        x &&
        y &&
        [i, i - 1, i - cols, i - cols - 1].every((j) => heights[j] !== -32768)
      ) {
        indices.push(i - 1, i, i - cols - 1, i - cols - 1, i, i - cols);
      }
    }
  const g = new T.BufferGeometry();
  g.setAttribute("position", new T.Float32BufferAttribute(vertices, 3));
  g.setAttribute("uv", new T.Float32BufferAttribute(uv, 2));
  g.setIndex(indices);
  const distant = new T.MeshBasicMaterial({ map: top, side: T.DoubleSide });
  distant.onBeforeCompile = (s) => {
    s.vertexShader =
      "varying vec3 worldTerrain;\n" +
      s.vertexShader.replace(
        "#include <begin_vertex>",
        "#include <begin_vertex>\nworldTerrain=position;",
      );
    s.fragmentShader =
      "varying vec3 worldTerrain;\n" +
      s.fragmentShader.replace(
        "#include <map_fragment>",
        "if(distance(worldTerrain.xy,cameraPosition.xy)<205.) discard;\n#include <map_fragment>",
      );
  };
  scene.add(new T.Mesh(g, distant));
  const cache = new Map();
  let group = new T.Group(),
    anchor = null,
    pending = null,
    sectors = 0;
  scene.add(group);
  function disposeModel(a) {
    const geo = new Set(),
      mats = new Set(),
      tx = new Set();
    a.scene.traverse((m) => {
      if (m.isMesh) {
        geo.add(m.geometry);
        for (const mat of [].concat(m.material)) {
          mats.add(mat);
          if (mat.map) tx.add(mat.map);
        }
      }
    });
    geo.forEach((m) => m.dispose());
    mats.forEach((m) => m.dispose());
    tx.forEach((t) => {
      t.dispose();
      t.source.data?.close?.();
    });
  }
  async function asset(id) {
    if (!cache.has(id))
      cache.set(
        id,
        loadModel("/detail/model/" + id + ".glb").catch((e) => {
          cache.delete(id);
          throw e;
        }),
      );
    return cache.get(id);
  }
  async function zone(x, y, z) {
    const data = await get(
      "/api/neighborhood?" + new URLSearchParams({ x, y, z, radius: 320 }),
      "json",
    );
    const next = new T.Group(),
      keep = new Set(data.map((v) => v.id));
    let cursor = 0;
    async function worker() {
      while (cursor < data.length) {
        const e = data[cursor++],
          a = await asset(e.id);
        a.scene.updateMatrixWorld(true);
        a.scene.traverse((mesh) => {
          if (!mesh.isMesh) return;
          if (!mesh.geometry.attributes.normal)
            mesh.geometry.computeVertexNormals();
          const inst = new T.InstancedMesh(
            mesh.geometry,
            mesh.material,
            e.instances.length,
          );
          const mat = new T.Matrix4(),
            pos = new T.Vector3(),
            q = new T.Quaternion(),
            scale = new T.Vector3(1, 1, 1);
          e.instances.forEach((t, i) => {
            pos.fromArray(t);
            q.fromArray(t, 3);
            mat.compose(pos, q, scale).multiply(mesh.matrixWorld);
            inst.setMatrixAt(i, mat);
          });
          inst.computeBoundingSphere();
          next.add(inst);
        });
      }
    }
    const done = await Promise.allSettled(
      Array.from({ length: Math.min(7, data.length) }, worker),
    );

    if (done.some((v) => v.status === "rejected"))
      throw Error("Не все ресурсы сектора загружены");
    scene.remove(group);
    group.traverse((m) => {
      if (m.isInstancedMesh) m.dispose();
    });
    group = next;
    scene.add(group);
    for (const [id, promise] of cache) {
      if (keep.has(id)) continue;
      const a = await promise;
      disposeModel(a);
      cache.delete(id);
    }
    anchor = [x, y, z];
    sectors++;
  }
  async function ensure(x, y, z) {
    if (
      anchor &&
      Math.hypot(x - anchor[0], y - anchor[1]) < 96 &&
      Math.abs(z - anchor[2]) < 36
    )
      return;
    if (pending) await pending;
    if (
      !anchor ||
      Math.hypot(x - anchor[0], y - anchor[1]) >= 96 ||
      Math.abs(z - anchor[2]) >= 36
    ) {
      pending = zone(x, y, z);
      try {
        await pending;
      } finally {
        pending = null;
      }
    }
  }
  function pose(pose) {
    const [x, y, z, a, p] = pose;
    camera.position.set(x, y, z);
    camera.lookAt(
      x + Math.cos(a) * Math.cos(p),
      y + Math.sin(a) * Math.cos(p),
      z + Math.sin(p),
    );
    sky.position.copy(camera.position);
    camera.updateMatrixWorld();
  }
  function size(width, height) {
    if (canvas.width === width && canvas.height === height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  function vehicle(p, a, mounted, steer = 0, lean = 0) {
    car.visible = !!p && (!mounted || bike);
    if (!car.visible) return;
    const forward = mounted ? -profile.seat[1] : 0;
    const right = mounted ? 0 : profile.size[0] * 0.5 + 0.12;
    car.position.set(
      p[0] + Math.cos(a) * forward + Math.sin(a) * right,
      p[1] + Math.sin(a) * forward - Math.cos(a) * right,
      p[2] + profile.lift,
    );
    car.rotation.order = "ZYX";
    car.rotation.z = a - Math.PI / 2;
    car.rotation.y = mounted ? -lean : 0;
    steerGroup.rotation.z = mounted ? steer : 0;
  }
  function draw(p) {
    pose(p);
    renderer.setRenderTarget(null);
    renderer.render(scene, camera);
  }
  return {
    profile,
    eyeHeight,
    bike,
    ensure,
    pose,
    draw,
    size,
    vehicle,
    camera,
    scene,
    renderer,
    stats: () => ({ sectors, models: cache.size }),
  };
}
