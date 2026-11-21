import init, {
  add_game_file,
  check_bike_response,
  check_image_slots,
} from "./pkg/sa_game.js";

const files = [];
const read = (id, start, count) => {
  const item = files[id];
  if (!Number.isSafeInteger(start) || start < 0 || start + count > item.size)
    throw Error("Запрос за пределами архива");
  const xhr = new XMLHttpRequest();
  xhr.open(
    "GET",
    "/game/" + item.path.split("/").map(encodeURIComponent).join("/"),
    false,
  );
  xhr.responseType = "arraybuffer";
  xhr.setRequestHeader("Range", `bytes=${start}-${start + count - 1}`);
  xhr.send();
  if (xhr.status !== 206 || xhr.response?.byteLength !== count)
    throw Error("Неполный сектор " + item.path);
  return new Uint8Array(xhr.response);
};
let panic = "";
self.saGameIo = {
  read,
  ready: () => true,
  waited: () => 0,
  panic: (message) => {
    panic = message;
  },
};

self.onmessage = async ({ data }) => {
  try {
    await init();
    if (data === "controls") {
      const values = check_bike_response();
      const inputs = Array.from({ length: 8 }, (_, i) =>
        Array.from(values.slice(i * 3, i * 3 + 3)),
      );
      const springs = Array.from({ length: 3 }, (_, i) =>
        Array.from(values.slice(24 + i * 2, 26 + i * 2)),
      );
      const valid =
        inputs.every((row) => row.every(Number.isFinite)) &&
        springs.every((row) => row.every(Number.isFinite)) &&
        inputs[0][0] === 0 &&
        inputs[1][0] === 1 &&
        inputs[5][0] === 0 &&
        inputs[6][1] === 1 &&
        inputs[2][2] > 0 &&
        inputs[3][2] > inputs[2][2] &&
        inputs[4][2] > inputs[3][2] &&
        inputs[5][2] > 0 &&
        inputs[5][2] < inputs[4][2] &&
        springs[0][0] === 0 &&
        springs[2][0] > springs[1][0] &&
        springs[1][0] > 0 &&
        springs[2][1] > springs[1][1] &&
        springs[1][1] > 0;
      if (!valid)
        throw Error("Контроль отклика: " + JSON.stringify({ inputs, springs }));
      postMessage({ inputs, springs });
    } else if (data === "archives") {
      const response = await fetch("game-index.json");
      if (!response.ok) throw Error("Недоступен индекс карты");
      const idx = await response.json();
      const plan = await (await fetch("archive-check.json")).json();
      for (const bank of plan) {
        const row = idx.find((f) => f.path.toLowerCase() === bank.path);
        if (!row || row.size !== bank.bytes)
          throw Error("Неверный архив " + bank.path);
        add_game_file(row.path, files.length, row.size);
        files.push(row);
      }
      const raw = check_image_slots(
        plan.map((b) => b.path),
        Uint32Array.from(plan, (b) => b.bytes / 2048 - 1),
      );
      const seen = new Set();
      for (let i = 0; i < plan.length; i++) {
        const [slot, first, last] = raw.slice(i * 3, i * 3 + 3);
        if (seen.has(slot) || first !== plan[i].first || last !== plan[i].last)
          throw Error("Ошибка чтения " + plan[i].path);
        seen.add(slot);
      }
      postMessage({
        archives: plan.length,
        sectors: plan.length * 2,
        slots: [...seen],
      });
    } else throw Error("Неизвестная проверка");
  } catch (e) {
    postMessage({ error: panic || String(e) });
  }
};
