# Script Studio: доставка проверенного веба без локального rebuild

**Дата:** 7 октября 2026, Asia/Yekaterinburg. **PR:** [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
**Статус:** source implemented; первый hosted image admission ещё не получен.
**Адрес рабочей витрины:** http://127.0.0.1:3015. Installed UI остаётся
`1c26ffc7def8c1a16ac90d2f0607f857b21d28cb`, API — `eb7a7c26c2e644f24eb3f785b3da1c29a65929be`.

## Проблема и изменение

Frontend CI проверял standalone output, но не сохранял переносимый runtime.
Для установки на ПК требовался новый локальный Next/Docker build. Это увеличивало
нагрузку и build-cache footprint на системном SSD, где выявлены NTFS defects.
Успешный CI поэтому не означал, что новая версия уже доступна оператору на3015.

[Frontend workflow](../../../.github/workflows/ci-frontend.yml) теперь проверяет
точный PR head: checkout ref, `git rev-parse HEAD` и `NEXT_PUBLIC_BUILD_SHA`
должны совпасть. После unit tests/types/build/standalone HTTP probe он упаковывает
**тот же output** в Linux/amd64 runtime image. Второго npm install или Next build
на этом шаге нет. Node/Debian base закреплён digest, runtime работает как1001:1001.

[`package_reviewed_web.mjs`](../../../tests/containers/package_reviewed_web.mjs)
проверяет действительный image ID через unprivileged read-only контейнер с
cap-dropALL, no-new-privileges и loopback port. Применяется тот же bounded
HTTP contract ко всем concrete pages и объявленным client JS/CSS/fonts.
Child container удаляется в finally; чужие контейнеры не останавливаются.

## Пакет и хранение

Artifact `sphere-reviewed-web-<full head SHA>` содержит только:

- `image.tar.gz` — Docker-save archive одного image, максимум300MiB compressed,
  максимум1GiB до gzip. Формат не называется raw OCI export.
- `receipt.json` — source/run/attempt, image ID/tag/platform, archive size/SHA256,
  exact page statuses и asset count; без HTML, Docker config и credentials.

Artifact загружается только после image probe и archive admission. Retention —
**3дня**, compression-level0: gzip уже выполнен. Он не копирует `.local-pilot`,
локальные `.env`, database volumes, APK или host reports. Upload action pinned
на `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` (v7); никаких package write/deploy
permissions не добавлено. [Official upload-artifact options](https://github.com/actions/upload-artifact#inputs).

CI packaging base, проверенный remote manifest6октябряUTC:
`node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20`.
Ubuntu standalone содержит glibc native dependencies; его нельзя автоматически
переносить в Alpine runtime. Это отдельный delivery Dockerfile, shipped
[frontend Dockerfile](../../../frontend/Dockerfile) не заменён. Native dependency
compatibility подтверждается image admission, а не названием base.

## Read-only admission до Docker load

[`reviewed_web_artifact.py`](../../../scripts/pilot/reviewed_web_artifact.py)
не извлекает архив, не запускает Docker и не меняет runtime. Он проверяет:

1. Full source SHA, repository, положительные run/attempt и schema version.
2. Byte/SHA256 budgets, regular files, отсутствие symlink/path traversal,
   duplicate member/special file, максимум2048tar entries и1GiB payload/headers.
3. Ровно один manifest, точный RepoTag, наличие layers и SHA256 actual config
   равный image ID. Поля config platform/entry/User и labels source/run/attempt
   должны соответствовать receipt.
4. Core routes, успешные HTTP statuses и проверенный Next redirect для root,
   положительное количество client assets. HTTP probe не доказывает hydration,
   APK action или получение данных API — соответствующие flags остаются false.

Пример после получения пакета **из проверенного успешного run**:

```powershell
python scripts/pilot/reviewed_web_artifact.py --directory '<private artifact directory>' --source '<40-character head SHA>'
```

JSON receipt внутри архива не является подписью или независимой provenance.
Перед загрузкой оператор/agent отдельно сверяет GitHub repository, workflow,
run ID/attempt, успешный conclusion и head SHA. Artifact ID/digest download
проверяется отдельно; receipt не разрешает запуск неизвестного image.

## Host gate и следующие действия

Read-only срез7октября: C: **Warning / Full Repair Needed**, boot остаётся
4октября21:39:32UTC+5, свободно60 146 794 496bytes. `git fsck --no-dangling`
прошёл. Свободное место и исправный Git не доказывают исправность NTFS.
Предыдущее чтение конкретного private build directory вернуло OS error1392.
Сборка/установка на этом ПК пока не выполнены; текущий веб сохранён.

Перед Docker load/deploy нужны [postboot host acceptance](../2026-10-06/HOST-FILESYSTEM-INCIDENT.md):
новый boot, завершённый queued NTFS repair, Healthy/OK, отсутствие unresolved
defects, Git/source/artifact hashes. Это ремонт файловой системы, а не откат
проекта, сброс данных или переустановка Windows. Reboot без окна оператора
не выполняется. CI package подготовлен независимо от этого окна.

После host admission: скачать один admitted image, проверить receipt/archive,
сравнить Compose delta (только review-ui), загрузить без rebuild, обновить только
review-ui с rollback readiness; сохранить API/OTA/tunnels/observability identity.
Затем проверить authenticated UI в реальном браузере: palette drag/drop,
detached node/explicit insertion, connection delete/reconnect, branch errors,
Undo/Redo, parameters, mobile layout и device recorder. Только этот результат
может закрыть source→installed→visual gate.

## Проверки и ограничения

Локально: **11unittest methods с41 отдельными positive/negative cases**,
Python Ruff и Node syntax check прошли. Tests используют только временные tiny
archives: tamper, wrong SHA/platform/CI/entry/User, missing route/layer, extra
image/tag, traversal/links/duplicates и ложные runtime flags. Docker image
build/probe/upload ещё должны пройти hosted workflow нового head.

Это не тест500–1000устройств, не новый Android encoder/injector, не установка
APK и не admission continuous DOWN/MOVE/UP. [Studio priorities](../2026-10-06/STUDIO-INTERACTION-FOLLOWUP.md)
и [free canvas source](../2026-10-06/STUDIO-FREE-CANVAS.md) сохраняют эти границы.
Общий ledger остаётся **9accepted/41open**; screenshots ранее приняты оператором.
