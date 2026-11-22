import * as T from "three";

export async function configureTerrain(asset, anisotropy, fineDetail) {
  const materials = new Set(), textures = new Map();
  asset.scene.traverse((mesh) => {
    if (mesh.isMesh)
      for (const material of [mesh.material].flat())
        if (material.userData.arianeTerrain) materials.add(material);
  });
  function layer(index, mask) {
    const key = index + ":" + mask;
    if (!textures.has(key))
      textures.set(key, asset.parser.getDependency("texture", index).then((original) => {
        const tex = original.clone();
        tex.colorSpace = mask ? T.NoColorSpace : T.SRGBColorSpace;
        tex.anisotropy = anisotropy;
        tex.needsUpdate = true;
        return tex;
      }));
    return textures.get(key);
  }
  await Promise.all([...materials].map(async (material) => {
    const { layers, repeats, detailRepeats } = material.userData.arianeTerrain;
    const slots = [0, 1, 2, 3].filter((i) => layers[i] !== null);
    const [mask, ...maps] = await Promise.all([
      layer(layers[4], true), ...slots.map((i) => layer(layers[i], false)),
    ]);
    material.arianeTerrainTextures = [mask, ...maps];
    material.customProgramCacheKey = () => "ariane-terrain-" + slots.join("");
    material.onBeforeCompile = (shader) => {
      shader.uniforms.arianeMask = { value: mask };
      shader.uniforms.arianeMaskRepeat = { value: repeats[4] };
      let uniforms = "uniform sampler2D arianeMask; uniform float arianeMaskRepeat;\n";
      slots.forEach((slot, i) => {
        uniforms += `uniform sampler2D arianeLayer${slot}; uniform vec2 arianeRepeat${slot};\n`;
        shader.uniforms[`arianeLayer${slot}`] = { value: maps[i] };
        shader.uniforms[`arianeRepeat${slot}`] = {
          value: new T.Vector2(...detailRepeats.map((repeat) =>
            fineDetail && repeats[slot] === 1 ? repeat : repeats[slot])),
        };
      });
      const weights = "rgba";
      const sampled = (slot) => `texture2D(arianeLayer${slot}, vMapUv * arianeRepeat${slot}).rgb`;
      const sum = slots.map((slot) => `weights.${weights[slot]}`).join(" + ");
      const color = slots.map((slot) => `${sampled(slot)} * weights.${weights[slot]}`).join(" + ");
      shader.fragmentShader = uniforms + shader.fragmentShader.replace("#include <map_fragment>", `
        vec3 blendMask = texture2D(arianeMask, vMapUv * arianeMaskRepeat).rgb;
        vec4 weights = vec4(blendMask, max(1.0 - dot(blendMask, vec3(1.0)), 0.0));
        float weightSum = ${sum};
        diffuseColor.rgb *= weightSum > 0.000001 ? (${color}) / weightSum : ${sampled(slots[0])};
      `);
    };
  }));
}
