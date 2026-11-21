const pick = document.querySelector("#game-folder");
const message = document.querySelector("#assets");
const scene = document.querySelector("#game");
const start = document.querySelector("#start-served");
const gameUrl = "index.html?strict=1&backend=gl&inworld=0";
const plan = await (await fetch("browser-course.json")).json();
function missing(files) {
  return plan.required.filter(
    (path) => !files.has(path) || files.get(path).size <= 0,
  );
}
async function digest(file) {
  const buffer = await file.arrayBuffer();
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", buffer))]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
async function verifyGame(files, read) {
  const absent = missing(files);
  if (absent.length) throw Error("Отсутствуют " + absent.join(", "));
  for (const [key, size] of Object.entries(plan.archiveBytes)) {
    if (files.get(key)?.size !== size) throw Error("Неполный архив " + key);
  }
  const receipt = files.get("sphere-full-world.json");
  if (!receipt)
    throw Error("Выбрана папка без подготовленного маршрута Black Russia.");
  const record = JSON.parse(await (await read("sphere-full-world.json")).text());
  if (
    record.runtime !== "browser-wasm" ||
    record.worldManifestSha256 !== plan.world ||
    record.routeSha256 !== plan.route
  )
    throw Error("Папка подготовлена для другой карты, миссии или движка.");
  const sums = {
    "sphere-route.json": plan.route,
    "data/script/main.scm": plan.scm,
    "data/script/script.img": plan.scriptImg,
    "data/gta.dat": record.layoutSha256?.["gta.dat"],
    "data/default.dat": record.layoutSha256?.["default.dat"],
  };
  for (const [key, hash] of Object.entries(sums)) {
    if (!files.has(key) || (await digest(await read(key))) !== hash)
      throw Error("Не совпадает файл " + key);
  }
  if (plan.packedScenesRequired)
    await verifyPackedScenes(record, files, read, plan.placementCount);
}

export async function verifyPackedScenes(record, files, read, placementCount) {
  const entries = Object.entries(record.packedScenes ?? {});
  const names = entries.map(([name]) => "data/maps/brworld/" + name);
  const layout = await (await read("data/gta.dat")).text();
  const active = layout.split(/\r?\n/)
    .map((line) => line.split("#")[0].trim())
    .filter((line) => /^IPL\s+/i.test(line))
    .map((line) => line.replace(/^IPL\s+/i, "").replaceAll("\\", "/").toLowerCase());
  if (!entries.length || entries.length > 40 || names.length !== active.length ||
      names.some((name, i) => name !== active[i]))
    throw Error("Компоновка сцен в gta.dat не совпадает с картой для браузера.");
  let count = 0;
  for (const [i, [name, part]] of entries.entries()) {
    if (!/^brp\d{3}\.ipl$/.test(name) || !Number.isInteger(part?.instances) ||
        part.instances < 1 || part.instances > 4096 || !files.has(names[i]) ||
        (await digest(await read(names[i]))) !== part.sha256)
      throw Error("Не удалось проверить сцену " + name);
    count += part.instances;
  }
  if (count !== placementCount)
    throw Error("Число объектов в браузерной сборке не совпало с исходной картой.");
}
pick.addEventListener("change", async () => {
  const selection = pick.files;
  if (!selection.length) return;
  start.disabled = pick.disabled = true;
  scene.hidden = true;
  scene.onload = null;
  scene.removeAttribute("src");
  try {
    const files = new Map();
    for (const file of selection) {
      const key = file.webkitRelativePath
        .split("/")
        .slice(1)
        .join("/")
        .toLowerCase();
      if (files.has(key)) throw Error("Дублируется файл " + key);
      files.set(key, file);
    }
    await verifyGame(files, async (key) => files.get(key));
    message.textContent = "Запускается игровой движок…";
    await new Promise((resolve, reject) => {
      scene.onload = () => {
        try {
          const target = scene.contentDocument.querySelector("#pick");
          if (!target) throw Error("Загрузчик sa-engine недоступен.");
          target.files = selection;
          target.dispatchEvent(new Event("change", { bubbles: true }));
          resolve();
        } catch (e) {
          reject(e);
        }
      };
      scene.src = gameUrl;
      scene.hidden = false;
    });
    message.textContent =
      "Файлы переданы локальному игровому движку. Ход загрузки показан ниже.";
    scene.scrollIntoView({ block: "start" });
  } catch (e) {
    message.textContent = e.message;
  } finally {
    pick.value = "";
    start.disabled = pick.disabled = false;
  }
});

async function checkServedGame() {
  const response = await fetch("game-index.json", { cache: "no-store" });
  if (!response.ok) throw Error("Индекс файлов стенда недоступен.");
  const files = new Map();
  for (const entry of await response.json()) {
    const key = entry.path.toLowerCase();
    if (files.has(key)) throw Error("Повторяющийся путь в данных стенда " + key);
    files.set(key, entry);
  }
  await verifyGame(files, async (key) => {
    const path = files.get(key).path.split("/").map(encodeURIComponent).join("/");
    const res = await fetch("/game/" + path, { cache: "no-store" });
    if (!res.ok) throw Error("Не удалось прочитать " + key);
    return res.blob();
  });
}
try {
  await checkServedGame();
  message.textContent = "Карта и миссия на стенде готовы к запуску движка.";
  start.hidden = false;
} catch (error) {
  message.textContent = error.message;
}
start.addEventListener("click", async () => {
  start.disabled = pick.disabled = true;
  try {
    await checkServedGame();
    scene.onload = null;
    scene.src = gameUrl + "&autostart=1";
    scene.hidden = false;
    message.textContent = "Запускается игровой движок с данными стенда.";
    scene.scrollIntoView({ block: "start" });
  } catch (error) {
    message.textContent = error.message;
  } finally {
    start.disabled = pick.disabled = false;
  }
});
