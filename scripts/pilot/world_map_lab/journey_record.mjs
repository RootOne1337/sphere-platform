async ({ width, height, fps, bitrate }) => {
  const film = document.createElement("canvas");
  film.width = width;
  film.height = height;
  const ctx = film.getContext("2d", { alpha: false });
  const world = document.getElementById("world");
  const heightBar = 74,
    scale = width / 1600;
  const labels = [
    journey.model === "faggio" ? "Пешком к скутеру" : "Пешком к машине",
    "За рулём " + journey.vehicleName,
    "Пешком до цели",
  ];
  let config;
  for (const hardwareAcceleration of [
    "prefer-hardware",
    "no-preference",
    "prefer-software",
  ]) {
    const candidate = {
      codec: "avc1.64002a",
      width,
      height,
      bitrate,
      framerate: fps,
      hardwareAcceleration,
      latencyMode: "realtime",
      avc: { format: "annexb" },
    };
    if ((await VideoEncoder.isConfigSupported(candidate)).supported) {
      config = candidate;
      break;
    }
  }
  if (!config) throw Error("H.264 encoder unavailable");
  const format = (n) => Math.round(n).toLocaleString("ru-RU");
  const clock = (n) =>
    Math.floor(n / 60) + ":" + String(Math.floor(n) % 60).padStart(2, "0");
  window.recordFrames = async (start, count) => {
    const chunks = [];
    let error = null;
    const encoder = new VideoEncoder({
      output: (chunk) => {
        const entry = new Uint8Array(chunk.byteLength);
        chunk.copyTo(entry);
        chunks.push(entry);
      },
      error: (e) => {
        error = e.message;
      },
    });
    try {
      encoder.configure(config);
      for (let i = start; i < start + count; i++) {
        const t = i / fps,
          s = await journey.frame(t, width, height);
        ctx.drawImage(world, 0, 0, width, height);
        ctx.save();
        ctx.scale(scale, scale);
        const h = height / scale;
        ctx.fillStyle = "rgba(10,23,31,.93)";
        ctx.fillRect(0, h - heightBar, 1600, heightBar);
        ctx.fillStyle = "#9ce7d4";
        ctx.font = "600 16px Segoe UI";
        ctx.fillText("SPHERE LAB   /   BLACK RUSSIA", 25, h - 43);
        ctx.fillStyle = "#fff";
        ctx.font = "600 24px Segoe UI";
        ctx.fillText(
          window.captureAttempt?.title ?? "Южный → Нижний",
          25,
          h - 13,
        );
        ctx.font = "600 23px Segoe UI";
        ctx.fillText(
          s.done
            ? "Финиш"
            : s.transfer
              ? s.mounted
                ? "Парковка и выход"
                : "Посадка · " + journey.vehicleName
              : labels[s.index],
          488,
          h - 33,
        );
        ctx.font = "15px Segoe UI";
        ctx.fillStyle = "#b2c8cc";
        ctx.fillText(
          s.observed
            ? "Камера 5 Гц  ·  " +
                s.observed.inliers +
                " опор  ·  " +
                Math.round(s.observed.commandMs) +
                " мс до команды"
            : "Проезд по рассчитанному пути",
          488,
          h - 12,
        );
        ctx.fillStyle = "#fff";
        ctx.font = "600 22px Segoe UI";
        ctx.fillText(
          format(s.distance) + " / " + format(journey.length) + " ед.",
          1054,
          h - 32,
        );
        ctx.font = "15px Segoe UI";
        ctx.fillStyle = "#b2c8cc";
        ctx.fillText(s.speed.toFixed(1) + " ед./с", 1054, h - 12);
        ctx.textAlign = "right";
        ctx.fillText(clock(t) + " / " + clock(journey.duration), 1572, h - 20);
        ctx.fillStyle = "#66daca";
        ctx.fillRect(0, h - heightBar, (1600 * s.distance) / journey.length, 3);
        const side = 176,
          x = 1600 - side - 25,
          y = 22;
        ctx.fillStyle = "rgba(12,27,36,.9)";
        ctx.fillRect(x - 4, y - 4, side + 8, side + 8);
        journey.drawMap(ctx, x, y, side, s.p, s.yaw);
        ctx.restore();
        const frame = new VideoFrame(film, {
          timestamp: Math.round((i * 1e6) / fps),
          duration: Math.round(1e6 / fps),
        });
        try {
          encoder.encode(frame, { keyFrame: i === start || i % 60 === 0 });
        } finally {
          frame.close();
        }
        if (encoder.encodeQueueSize > 6) await encoder.flush();
        if (error) throw Error(error);
      }
      await encoder.flush();
      if (error || chunks.length !== count)
        throw Error(error || "Incomplete encoder batch");
    } finally {
      if (encoder.state !== "closed") encoder.close();
    }
    const all = new Uint8Array(chunks.reduce((sum, x) => sum + x.length, 0));
    let off = 0;
    for (const chunk of chunks) {
      all.set(chunk, off);
      off += chunk.length;
    }
    let str = "";
    for (let j = 0; j < all.length; j += 32768)
      str += String.fromCharCode(...all.subarray(j, j + 32768));
    return btoa(str);
  };
  return {
    duration: journey.duration,
    length: journey.length,
    legs: journey.legs,
    encoder: config.hardwareAcceleration,
  };
};
