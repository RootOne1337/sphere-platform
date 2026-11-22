async ({ width: w, height: h, model = "faggio", verticalFov = null, detailRadius }) => {
  const T = await import("three"),
    { createWorld } = await import("/journey/scene.mjs");
  const canvas = document.getElementById("eye"),
    config = await (await fetch("/journey/route.json")).json();
  const settings = detailRadius === undefined ? config : { ...config, detailRadius };
  const world = await createWorld(canvas, settings, model);
  world.size(w, h);
  const { renderer, scene, camera } = world;
  if (verticalFov !== null) {
    camera.fov = verticalFov;
    camera.updateProjectionMatrix();
  }
  const target = new T.WebGLRenderTarget(w, h, {
    minFilter: T.NearestFilter,
    magFilter: T.NearestFilter,
  });
  target.depthTexture = new T.DepthTexture(w, h, T.UnsignedIntType);
  const packed = new T.WebGLRenderTarget(w, h, { depthBuffer: false });
  const quad = new T.Scene(),
    ortho = new T.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const pack = new T.ShaderMaterial({
    uniforms: {
      depth: { value: target.depthTexture },
      color: { value: target.texture },
      near: { value: camera.near },
      far: { value: camera.far },
    },
    vertexShader:
      "varying vec2 uv0;void main(){uv0=uv;gl_Position=vec4(position.xy,0.,1.);}",
    fragmentShader:
      "uniform sampler2D depth,color;uniform float near,far;varying vec2 uv0;void main(){float d=texture2D(depth,uv0).r;float z=min(65535.,round(128.*near*far/(far-d*(far-near))));float v=dot(texture2D(color,uv0).rgb,vec3(.299,.587,.114));gl_FragColor=vec4(v,mod(z,256.)/255.,floor(z/256.)/255.,1.);}",
  });
  quad.add(new T.Mesh(new T.PlaneGeometry(2, 2), pack));
  const raw = new Uint8Array(w * h * 4);
  function bytes(v) {
    let r = "";
    for (let i = 0; i < v.length; i += 8192)
      r += String.fromCharCode(...v.subarray(i, i + 8192));
    return btoa(r);
  }
  let observation,
    ride = false,
    panAngle = 0;
  async function view(p, depth, rawOnly = false) {
    if (ride)
      world.vehicle(
        [p[0], p[1], p[2] - world.eyeHeight],
        p[3] - panAngle,
        true,
      );
    world.pose(p);
    renderer.setRenderTarget(target);
    renderer.render(scene, camera);
    renderer.setRenderTarget(packed);
    renderer.render(quad, ortho);
    renderer.readRenderTargetPixels(packed, 0, 0, w, h, raw);
    renderer.setRenderTarget(null);
    const grey = new Uint8Array(w * h),
      z = depth ? new Uint16Array(w * h) : null;
    for (let y = 0; y < h; y++)
      for (let x = 0; x < w; x++) {
        const k = y * w + x,
          i = ((h - y - 1) * w + x) * 4;
        grey[k] = raw[i];
        if (z) z[k] = raw[i + 1] + 256 * raw[i + 2];
      }
    return rawOnly
      ? grey
      : z
        ? [bytes(grey), bytes(new Uint8Array(z.buffer))]
        : bytes(grey);
  }
  // Offline reference capture: render only the static environment at the selected map pose.
  window.mapReference = async (pose) => {
    ride = false;
    world.vehicle(null, 0, false);
    await world.ensure(...pose.slice(0, 3));
    return view(pose, true);
  };
  window.mapReferenceRGBD = async (pose) => {
    const [, depth] = await window.mapReference(pose);
    renderer.setRenderTarget(null);
    renderer.render(scene, camera);
    return [canvas.toDataURL("image/jpeg", 0.96).split(",")[1], depth];
  };
  window.observePair = async ([prior, actual, vehicle]) => {
    ride = vehicle.mounted;
    panAngle = vehicle.pan ?? 0;
    if (!ride) world.vehicle(vehicle.park, vehicle.yaw ?? 0, false);
    await world.ensure(...prior.slice(0, 3));
    const [ref, depth] = await view(prior, true);
    // The simulator streams the body's own neighborhood even if the estimator drifts.
    await world.ensure(...actual.slice(0, 3));
    observation = await view(actual, false, true);
    await world.ensure(...prior.slice(0, 3));
    return [ref, depth, bytes(observation)];
  };
  window.mapPairWithLastImage = async (cameraPose) => {
    const [grey, depth] = await view(cameraPose, true);
    return [grey, depth, bytes(observation)];
  };
  // Average blocks before ranking broad hypotheses so windows and lane markings
  // still overlap between views several metres or degrees apart.
  function thumbnail(pixels) {
    const step = 8,
      cols = Math.floor(w / step),
      rows = Math.floor(h / step);
    const tile = new Float32Array(cols * rows);
    for (let y = 0; y < rows * step; y++) {
      for (let x = 0; x < cols * step; x++) {
        tile[Math.floor(y / step) * cols + Math.floor(x / step)] +=
          pixels[y * w + x] / (step * step);
      }
    }
    return tile;
  }
  window.rankRenderedPoses = async (poses, coarse = false) => {
    const obs = coarse ? thumbnail(observation) : observation;
    const width = coarse ? Math.floor(w / 8) : w,
      height = coarse ? Math.floor(h / 8) : h;
    const stride = coarse ? 1 : 3;
    const scores = [];
    for (const p of poses) {
      const pixels = await view(p, false, true);
      const ref = coarse ? thumbnail(pixels) : pixels;
      let loss = 0,
        weight = 0;
      for (let y = Math.floor(height * 0.2); y < height * 0.77; y += stride)
        for (let x = 2; x < width - 2; x += stride) {
          const i = y * width + x;
          const grad = Math.min(
            35,
            Math.abs(obs[i + 2] - obs[i - 2]) +
              Math.abs(obs[i + width] - obs[i - width]),
          );
          if (grad < 3) continue;
          weight += grad;
          loss += grad * Math.min(60, Math.abs(obs[i] - ref[i]));
        }
      scores.push(weight < (coarse ? 600 : 4500) ? 1000 : loss / weight);
    }
    return scores;
  };
  return h / (2 * Math.tan(T.MathUtils.degToRad(camera.fov) / 2));
};
