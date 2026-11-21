const pick = document.querySelector("#game-folder");
const message = document.querySelector("#assets");
const scene = document.querySelector("#game");
const plan = await (await fetch("browser-course.json")).json();
function missing(files) {
  return plan.required.filter(
    (path) => !files.has(path) || files.get(path).size <= 0,
  );
}
const served = await (await fetch("game-index.json")).json();
const absent = missing(new Map(served.map((f) => [f.path.toLowerCase(), f])));
message.textContent = absent.length
  ? "В данных стенда отсутствуют " + absent.join(", ") + "."
  : "Файлы игрового клиента доступны. Для запуска выберите подготовленную папку маршрута.";
async function digest(file) {
  const buffer = await file.arrayBuffer();
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", buffer))]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
pick.addEventListener("change", async () => {
  const selection = pick.files;
  if (!selection.length) return;
  pick.disabled = true;
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
    const absent = missing(files);
    if (absent.length) throw Error("Отсутствуют " + absent.join(", "));
    for (const [key, size] of Object.entries(plan.archiveBytes)) {
      if (files.get(key)?.size !== size) throw Error("Неполный архив " + key);
    }
    const receipt = files.get("sphere-full-world.json");
    if (!receipt)
      throw Error("Выбрана папка без подготовленного маршрута Black Russia.");
    const record = JSON.parse(await receipt.text());
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
      if (!files.has(key) || (await digest(files.get(key))) !== hash)
        throw Error("Не совпадает файл " + key);
    }
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
      scene.src = "index.html?strict=1&backend=gl&inworld=0";
      scene.hidden = false;
    });
    message.textContent =
      "Файлы переданы локальному игровому движку. Ход загрузки показан ниже.";
    scene.scrollIntoView({ block: "start" });
  } catch (e) {
    message.textContent = e.message;
  } finally {
    pick.value = "";
    pick.disabled = false;
  }
});
