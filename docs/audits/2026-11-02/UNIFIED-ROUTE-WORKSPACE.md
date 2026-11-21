# Единое рабочее пространство записанного маршрута

Дата: 2 ноября 2026. Статус: **новый web установлен и healthy; локальный API перезагружен; полный автономный заезд не подтверждён**.

Документ разделяет исходники, изолированную браузерную проверку, локальные вычислительные пробы и установленный runtime. Локальные receipts в `.local-pilot` не входят в Git; приведённые ссылки действуют в проверенном checkout. Их компактные публичные копии для постоянного архива выбираются отдельно. Этот draft не изменяет первичную геометрию, исходную запись, навигационное состояние или управление.

## Что исправляет UI

Пользователь видел полный диагностический проход **173 камеры / 20 556 точек** в 2D, но при переходе в 3D получал основную модель на **144 камеры**. Это были разные сохранённые результаты одной записи. Единый заголовок скрывал различие, а отображение длительности подмножества могло создавать впечатление, что восстановлена вся запись.

Для `skuter1`, job `6a77040681d142ec97d51831a22785fb`, primary содержит интервал **5,678–36,404 с**. В source-интервале **0–36,903 с** отсутствуют первые 5,678 с и последние 0,499 с. Primary проходит ограниченные проверки сцены, но не проходит проверку крайних участков маршрута. Preferred alternative `fixed-k-fused-173-supported-diagnostic` содержит все 173 выбранных ракурса. Её диагностическая публикация не заменила primary и не выдала разрешение на движение.

Новый [TeachingReview](../../../frontend/src/features/stream/TeachingReview.tsx) передаёт один выбранный результат в 2D, временную шкалу и 3D через [SceneGeometrySelection](../../../frontend/src/features/stream/sceneGeometrySelection.ts). Контракт связывает выбор с account/source key, job, SHA-256 manifest и подтверждёнными ticks. `geometry:null` означает ожидание; в этот момент 3D не должен незаметно загружать primary. Поздний ответ от предыдущей записи или предыдущего выбора не получает новый заголовок и authority текущего результата.

В [ReconstructedScene](../../../frontend/src/features/stream/ReconstructedScene.tsx) альтернативная или импортированная схема показывает собственные камеры и точки. Исторические primary/surface/Gaussian нельзя открыть внутри выбранной alternative под её заголовком: сначала требуется выбрать primary во внешнем selector. Рендер поверхности остаётся отдельным представлением, а не доказательством, что это геометрия выбранной альтернативы. Общий `selectedTicks` и seek callback используют исходные timestamps; новые позы и промежуточные камеры не интерполируются.

Полный source-range передаётся отдельно от camera-range. Покрытие 144 камер не называется всей записью или 100%; видны незакрытые начало и конец. Покрытие 173 ракурсов относится к наблюдаемому времени исходника, а не к точности поз или возможности проезда.

[TeachingReconstruction](../../../frontend/src/features/stream/TeachingReconstruction.tsx) сохраняет одну подготовку и один экземпляр polling. [CompactReconstructionWorkflow](../../../frontend/src/features/stream/CompactReconstructionWorkflow.tsx) показывает основное действие и этапы «Исходная запись», «Камеры и точки», «Основная карта для проверки». История попыток, Gaussian, поверхности и подробные метрики вынесены в раскрываемые блоки. Карточка подготовки не отправляет игровые команды. Библиотека выбирает запись, а просмотр результата не запускает повторный расчёт.

## Проверка настоящих компонентов в изолированном браузере

[browser-evidence.json](unified-route-evidence/browser-evidence.json) содержит **21/21 проверку**, без console/page errors. Использованы настоящие React-компоненты, CSS, WebGL и декодирование настоящего source H.264 через WebCodecs. Исходные media-файлы читались только для просмотра; API-ответы были замокированы. Это не пользовательский IAB, не production API, не Next SSR/hydration acceptance и не доступ к пользовательскому OPFS/profile. Adapter для `next/dynamic` указан в boundary receipt.

Проверены выбор 173 в 2D и 3D, отдельная маркировка primary 144, отсутствие primary-fetch/fallback при alternative, общий конец временной шкалы и видео, честный пропущенный prefix primary, возврат к 173, отсутствие фонового archive-polling, переход в библиотеку и выбор записи. Проверка на ширине 390 px не обнаружила горизонтального переполнения. В fixture нет API/file writes, внешнего доступа, обработки записи или игровых действий: `physicalActions:0`.

Визуальные артефакты:

- [2D, 173](unified-route-evidence/final-map-173.png);
- [WebGL 3D, 173](unified-route-evidence/final-scene-173.png);
- [primary 144 и пропущенное начало](unified-route-evidence/final-primary-144-range.png);
- [mobile, 390 px](unified-route-evidence/final-mobile-390.png).

Хеши компонентов сохранены в browser receipt. Эта проверка относится к состоянию UI для `132c4acbbcee048c5cb2b9189d026390d19ce4bc`, до последующего исправления `let` → `const` в resize observer. Последнее исправление не является новой браузерной приёмкой.

## Версии, CI и граница установки

| Версия / попытка | Измеренный результат | Что не доказано |
| --- | --- | --- |
| `132c4acbbcee048c5cb2b9189d026390d19ce4bc` | Canonical frontend CI: 3171/3171 тест, 233 suites; затем один Next build остановился на `prefer-const`, `ReconstructedScene.tsx:80` | Успешный image/package/install отсутствует |
| `15ce01edc7846f2842e52c3ad37df1b77cfafbd0`, delivery v2 | Исправлен observer; Jest 3171/3171, 233 suites; обязательный последующий resource-check отказал по диску | Полный canonical CI не успешен; build не запускался |
| Та же версия, delivery v3 | Свежий preflight: healthy volume, свободно 20 452 651 008 bytes при минимуме 21 474 836 480 bytes; `disk_headroom_low` | CI/build/dry-run/install не запускались |
| Та же версия, local delivery v4/v5 | После восстановления disk headroom локальный admission отказал по `commit_headroom_low`, действующий предел commit 85%; v5 canonical CI остановлен до шагов (`executedSteps:0`) | Порог не ослаблен; local CI/build/install не прошли |
| `60e7f6ffdab4265d3b838aa8ca1320e003289419`, один cloud dispatch | [GitHub Actions run 41454423270](https://github.com/RootOne1337/sphere-platform/actions/runs/41454423270): все 19 шагов PASS; 3171/3171 тест, 233 suites, types, Next production build, packaged pages и runtime-image probe | Не доказывает authenticated browser hydration, реальный игровой input или автономный заезд |

Источники: [delivery v1 outcome](../../../.local-pilot/unified-route-delivery-20261102-v1/outcome.json), [delivery v2 outcome](../../../.local-pilot/unified-route-delivery-20261102-v2/outcome.json), [delivery v3 refusal](../../../.local-pilot/unified-route-delivery-20261102-v3/preflight-refusal.json), [v4 preflight](../../../.local-pilot/unified-route-delivery-20261102-v4/preflight.json), [v5 outcome](../../../.local-pilot/unified-route-delivery-20261102-v5/outcome.json). Отдельные локальные отказы не являются успешным local CI 15ce. Фактическая доставка ниже опирается на независимый полный hosted CI 60e и последующую установку. Disk-отказ не доказывает неисправность диска: volume-health был Healthy, не хватило установленного запаса свободного места. Последующий commit-отказ — отдельная граница. Ослабления порогов и автоматического цикла повторов не выполнялось.

Cloud wrapper первоначально не распознал ID уже отправленного dispatch (`new_dispatch_run_not_identified`). Этот [результат wrapper](../../../.local-pilot/unified-route-cloud-20261102-v2/result.json) сохранён; последующее [identity reconciliation](../../../.local-pilot/unified-route-cloud-20261102-v2/run-identity-reconciliation.json) привязало существующий run, без второго запуска. [Progress receipt](../../../.local-pilot/unified-route-cloud-20261102-v2/reconciled-progress.json) на 13:39:57 UTC показывает выполняющийся build, а не итоговый PASS. Временно включённый workflow уже возвращён в исходное состояние `disabled_manually`, пока один разрешённый dispatch продолжает работу: [restoration receipt](../../../.local-pilot/unified-route-cloud-20261102-v2/workflow-restored.json). Это не постоянное включение автоматических GitHub workflow.

**Frontend delivery подтверждён.** Artifact 13145688030 из run 41454423270 проверен по GitHub ZIP digest, archive digest, OCI и независимому image ID из authenticated CI job log: [archive admission](unified-route-evidence/cloud-archive-admission.json), [CI image binding](unified-route-evidence/cloud-ci-image-binding.json). Установлен source `60e7f6ffdab4265d3b838aa8ca1320e003289419`, image/config ID `sha256:5288835ba424dcdae75e28786134f8e8c7f0bd69ef1411285c345dd9fa943c4a`, gateway `127.0.0.1:3015`, UI healthy. [Runtime receipt](unified-route-evidence/ui-runtime.json) подтверждает 105 client assets по HTTP, два worker SHA и 13 compiled tokens, включая новые подписи. Все 45 остальных контейнеров, полный уникальный ENV mapping UI, HostConfig/Mounts, API PID 54464, OTA и 562 защищённых source/results assets сохранены. Исторические images/archives не удалялись. Установщик использовал явный отдельный UI admission budget и три свежих проверки с пустыми findings; его граница описана ниже. Это HTTP/runtime acceptance, а не новая authenticated browser/игровая проверка.

**Backend/runtime delivery подтверждён отдельно.** Изменения вошли в `da6cc0428538e4cdcbadccb4e680ccebb5bb8426`; health-контракты добавлены в `60e7f6ffdab4265d3b838aa8ca1320e003289419`. [Safe API reload receipt](../../../.local-pilot/unified-route-api-reload-20261102-v1/receipt.json) имеет `outcome:verified`, `reloadPerformed:true`: listener 54464, launcher 29740, прежний watchdog 4444. Health подтверждает `fused_recovery_contract:gated_cpu_native_v1`, `fused_recovery_enabled:false`, `native_reference_contract:offline_unqualified_v1`, `live_session_active:false`; запрос без capability получил 403. Все 562 защищённых assets и все 46 контейнеров сохранены; `physicalActions:0`. Эта перезагрузка API не обновила web-image и не повторила terminal jobs. Доставку UI и backend нельзя выводить друг из друга.

Доставка выполнена через существующий hosted CI, канонические [reviewed_web_artifact](../../../scripts/pilot/reviewed_web_artifact.py) и [install_reviewed_web](../../../scripts/pilot/install_reviewed_web.py). Перед заменой отдельный read-only capped контейнер проверил public chunks; после замены gateway вернул ровно те же SHA. Ошибки раннего private probe относились к его собственному UTF8/CP1251 token-list и allowlist публичных Next catch-all chunk names: product bundle содержал правильные подписи. Старые отрицательные receipts сохранены, probe-контейнеры удалены после подтверждения владения. Финальный [HTTP proof](../../../.local-pilot/unified-route-install-20261102-v6/http-proof-handoff.json) и runtime receipt не заменяют реальную игровую проверку.

## Автоматический fused engine: результаты и отключённый default

Новый [route_fused_recovery](../../../scripts/pilot/route_fused_recovery.py) — отдельный ограниченный CPU-кандидат. Он сохраняет явные пространства VIDEO-prefix и SIFT-suffix, заново проверяет соответствия и оценивает модель через общие quality/conditioning/endpoint/gap/motion gates. Увеличение числа камер или точек и нулевой exit native-процесса сами по себе не допускают результат. Подробности исходной автоматической очереди и её restart/idempotency fences описаны в [ROUTE-CATALOG-DELIVERY.md](ROUTE-CATALOG-DELIVERY.md).

Четыре настоящие пробы использовали отдельные рабочие папки и повторно использовали подготовленные исходники; это не четыре успешных реконструкции:

| Проба | Результат | Wall time | Принятие |
| --- | --- | --- | --- |
| [v1 outcome](../../../.local-pilot/skuter1-automatic-fused-20261102-v1/outcome.json) | SQLite отказал: обязательный `descriptors.type` не был записан | 14,641 с | Нет |
| [v2 outcome](../../../.local-pilot/skuter1-automatic-fused-20261102-v2/outcome.json) | OpenCV USAC/Sampson отказал на вырожденной модели | 94,265 с | Нет |
| [v3 outcome](../../../.local-pilot/skuter1-automatic-fused-20261102-v3/outcome.json) | SIFT/F: 694 пары из 1153 proposals; отдельный native verification завершён, `view_graph_calibrator` превысил 45-секундный предел; global model не получен | 222,344 с | Нет |
| [v4 outcome](../../../.local-pilot/skuter1-automatic-fused-20261102-v4/outcome.json) | После явного закрытия SQLite и zero-WAL handoff calibrator снова превысил 45 с; `candidate:null`, global model не получен | 225,594 с | Нет |

Для v3 [calibrate receipt](../../../.local-pilot/skuter1-automatic-fused-20261102-v3/job/prepared/fused-recovery/calibrate-receipt.json) фиксирует `status:failed`, `reason:fused_native_timeout`, 45,375 с. Его поле `exit_code:0` не отменяет timeout и не доказывает завершённую калибровку. Исходный baseline 144 камер сохранился; `candidate:null`, защищённые оригиналы не изменены, `navigation_promoted:false`, `physical_actions:0`. Эти результаты не доказывают, что алгоритм успешно восстановит полный маршрут нового пользователя.

Для v4 [database boundary receipt](../../../.local-pilot/skuter1-automatic-fused-20261102-v4/job/prepared/fused-recovery/database-boundaries.json) подтверждает zero-WAL перед verify/calibrate. Тем не менее [calibrator receipt](../../../.local-pilot/skuter1-automatic-fused-20261102-v4/job/prepared/fused-recovery/calibrate-receipt.json) снова фиксирует `fused_native_timeout`, 45,844 с. Закрытие handles и стабильность cache hashes исправлены, но **причина timeout не установлена и не объявлена устранённой**. Это не доказанный memory leak.

Отдельная [быстрая calibrator-проба v1](../../../.local-pilot/skuter1-calibrator-handoff-20261102-v1/calibrate-receipt.json) завершилась за 0,297 с, однако использовала **уже откалиброванную v3 DB**: focal 2317,346 px, `prior_focal:1`, камера не изменилась. [Сравнение snapshots](../../../.local-pilot/skuter1-calibrator-comparison-20261102-v1/result.json) показывает, что v4 до calibrator имела focal 2304 px, `prior_focal:0`; различаются также config 117 two-view pairs. Одинаковая schema и большая часть таблиц не делают эти входы эквивалентными. Поэтому быстрый результат нельзя приписывать только lifetime/SQLite fix.

Разрешённая отдельная [byte-exact v4-copy probe v2](../../../.local-pilot/skuter1-calibrator-handoff-20261102-v2/outcome.json), без повторной extraction/полного engine run, тоже завершилась `fused_native_timeout` (47,859 с суммарно). Камера осталась 2304 px / prior 0; source unchanged, global mapper не вызывался, adoption отсутствует. Это уточняет отрицательное evidence и не разрешает автоматические дополнительные прогоны или увеличение deadline.

**Текущий default — OFF.** Hook в [reconstruct_route](../../../scripts/pilot/reconstruct_route.py) вызывает этот engine только при точном внутреннем opt-in `SPHERE_EXPERIMENTAL_FUSED_RECOVERY=1`. Значения `true`, `yes`, пустое значение или отсутствие переменной не включают его. Opt-in не отменяет admission, лимиты или quality gates. Измеренный неуспех не превращён в автоматический повтор. Каноническая подготовка runtime-карты сохраняет legacy exporter; новый native-reference путь автоматически не выбран.

## Исправленные proof/resource границы backend

В рабочем дереве исправлены обязательный COLMAP 4.2 `FeatureExtractorType.SIFT=0`, обработка вырожденного/неfinite F и некорректных inlier masks/индексов. Ошибка пары отклоняет пару и не превращается в нулевую геометрическую ошибку или фиктивное соответствие.

[route_native_track_policy](../../../scripts/pilot/route_native_track_policy.py) удаляет целые tracks с повторным изображением или менее чем тремя разными зарегистрированными views на принадлежащем задаче клоне. Проверяются reciprocal associations, конечность, положительная глубина и фактические residuals. Порог поддержки камеры считается по **уникальным точным XY**, с худшим residual для общего пикселя; отдельные VIDEO/SIFT rows больше не удваивают физическое наблюдение. Синтетический регрессионный случай «20 rows / 10 уникальных пикселей» отвергается. Эта проверка не объединяет точки по ближайшему соседу и не меняет исходные pose/XY ради красивой траектории.

SQLite transaction context не использовался как доказательство закрытия connection: helpers переведены на явный `closing()`. Backup имеет callback; принадлежащие задаче базы закрываются и проходят WAL checkpoint до native handoff и хеширования main-file bytes. Pending-reader/WAL отказ не считается стабильным cache. Namespace descriptor SHA повторно сравнивается перед финальным asset receipt; тесты проверяют hash stability после GC/reopen. Оригинальная база не checkpoint/delete-ится ради исправления чужой пробы.

Поздняя ошибка sealing/cache hash/cancellation после предварительного выбора теперь очищает `accepted:false`. Это закрывает найденный audit-дефект, при котором функция уже возвращала baseline, но ещё записывала `accepted:true`. Отдельные регрессии проверяют поздний seal, descriptor mismatch и cancellation после выбора. Baseline и прежние terminal artifacts не переписываются как успешный новый результат.

Frozen-copy helper проверяет исходник, model hashes и полную фактическую native identity: K/позы, все XY, image→POINT3D_ID, XYZ и tracks. Если endpoint repair или последующий этап изменил модель, старый bundle не получает её identity; сериализуется настоящий выбранный результат. Даже точное совпадение здесь не является проверкой локализации.

Объявлены ограничения одного кандидата: до 240 views, 1024 SIFT features/view, 1800 pairs, 2 млн matches, workspace 384 MiB, общий этап 360 с. Native-процессы принадлежат задаче до resume, ограничены двумя CPU, отдельными deadline/log/RSS проверками; fixed-K BA не уточняет intrinsics. Host RAM/commit/disk/cancellation guards остаются независимыми. Эти ограничения описывают bounded offline processing, а не стоимость сотен игровых окон или realtime throughput.

[verification.json](unified-route-evidence/fused-implementation-verification.json) сохраняет hashes проверенной версии: 179 passed, 1 skipped, 10,39 с, Ruff/diff check passed. В receipt честно отмечено отсутствие отдельного raw console log. Дополнительный [combined backend console log](unified-route-evidence/backend-tests.txt): 171 passed, 1 skipped, 42 subtests, 7,39 с. Координатор отдельно подтвердил service-проверку 55 tests / 6,25 с и более раннюю HUD-integration проверку 12 tests; отдельные console receipts этих двух запусков здесь не приложены. Эти проверки не доказывают успешный настоящий global model; факт deployment подтверждается отдельным API reload receipt выше.

## Точный native 2D→3D export: provenance есть, улучшения runtime нет

[route_native_landmarks](../../../scripts/pilot/route_native_landmarks.py) проверяет точную связь source SIFT row → fused row → измеренный POINT3D_ID. Не выполняет ближайшее сопоставление признаков, новую триангуляцию или коррекцию XYZ/поз. Runtime-пиксель получается как `xy_colmap * target/source - 0.5`; дескриптор native q512 декодируется и L2-нормируется без повторного RootSIFT sqrt. Это отдельное экспериментальное reference-family ID, связанное с текущим query fingerprint; legacy ID не подставляется.

После двух сохранённых отказов admission/empty-WAL в [bounded binding v3](../../../.local-pilot/skuter1-native-binding-20261102-v3/result.json) использована только byte-exact копия 29,86 MB descriptor DB в собственной папке. Оригинальные DB/WAL/SHM не checkpoint/delete-ились. Из 20 556 native points получены **3756** landmarks на 173 views; min per-view support 21, min ±1-neighborhood support 55, все neighborhoods проходят существующий structural map-support порог. Worker: 4,625 с, sampled RSS 158,5 MiB, private 167,6 MiB, CPU2. Source hashes сохранены.

Однако [159-query probe](../../../.local-pilot/skuter1-native-probe-20261102-v1/comparison.json) дал **50 localized / 28 confirming / 81 unknown** против **66 / 29 / 64** у предыдущего guided-v3. Совпадают все 159 query indices, source RGB hashes, runtime masks/profile, K/позы и query extractor; все 173 reconstruction indices исключены. Native localized с ≥80 inliers — 16 против 44. Compute p50/p95/max — 121,84 / 203,13 / 343,01 ms; четыре samples превышают 250 ms, ни один из них не localized. Это compute-only измерение с offline media clock, без capture/HTTP/Android latency.

Первый native localized — 0,475 с, последний проверенный кадр 36,686 с localized. Длинные интервалы без localized: 3,119–15,466 и 20,361–31,728 с. Все 50 native localized входят в 66 guided localized. [Read-only diagnosis](../../../.local-pilot/skuter1-native-probe-20261102-v1/read-only-diagnosis.json) фиксирует 72 `route_pose_not_verified` и 9 `route_pose_discontinuity`; сохранённые отчёты не содержат raw ratio/match/PnP-stage counters, поэтому приписывать все отказы одной ratio-test причине нельзя. Нулевые inliers в unknown — sentinel отсутствующей принятой позы, не измерение нуля исходных matches.

Native source descriptors получены OpenCV SIFT full resolution, q512 и иной обработкой zero bins; query использует 960×540 RootSIFT. Совпадение ширины 128 не доказывает взаимозаменяемость extractor families. Историческая точная версия/producer identity не полностью доказана. Все queries относятся к той же записи, близко к reference frames по времени; это не второй независимый проезд и не spatial ground truth.

**Автоматического native promotion нет.** `prepare_route_workspace.py` сохраняет прежний exporter. Даже source-bound native cache с прошедшим map_support в текущем [RouteWorkspaces.status](../../../scripts/pilot/route_workspace.py) отвергается как `route_native_reference_unqualified`; подстановка `runtime_qualified:true` не является обходом контракта. [Implementation receipt](../../../.local-pilot/native-reference-implementation-20261102-v1/receipt.json): 105 tests + 42 subtests прошли; new files Ruff clean. Исходные trial receipts сохранены до позднейшего усиления контракта и не объявлены новыми live-ready artifacts.

## Общий core, HUD-профили и реальный FPS

Source validation, временной индекс, сохранение кадров, source-bound review и геометрические gates не должны требовать Black Russia HUD или записанных клавиш. [route_masks](../../../scripts/pilot/route_masks.py) применяет специализированные vehicle HUD/body/mirror rectangles только при явном профиле `black_russia_scooter_v1`. Неизвестная игра не получает этот профиль по внешнему сходству. Маски — статические исключения изображения, не segmentation, depth или доказательство проезжаемой дороги.

HUD speed/OCR — отдельная optional source-bound возможность. Black Russia speed profile описывает игровые HUD km/h; это не GPS, физическая калибровка масштаба или универсальный speedometer для любой игры. Отсутствие профиля не должно блокировать сохранение/просмотр/general image processing; vehicle speed control при этом не получает выдуманную скорость. См. [VEHICLE-TEACH-REPEAT.md](VEHICLE-TEACH-REPEAT.md) для строгих ограничений vehicle-mode, camera-follows-body и независимых freshness/ACK/quality gates.

В проверенной записи **857 source frames за 36,903 с**. Наблюдаемая средняя частота по интервалам `(857−1)/36.903` — **23,196 FPS**, а не 30 FPS. Настроенный/requested 30 FPS нельзя выдавать за измеренный FPS файла. UI и вычисления опираются на исходные PTS/ticks, а не равномерно придуманную сетку. Снижение разрешения feature analysis не меняет master H.264; в этом обновлении запись не перекодировалась и недостающие исходные кадры не синтезировались.

## Что остаётся неподтверждённым

Полный autonomous vehicle repeat, closed-loop следование дороге, безопасное прибытие, универсальная метрическая карта и независимая повторная локализация этим пакетом не доказаны. Диагностические 173 камеры не заменяют failed primary/nav state, а WebGL-картинка и низкий in-sample residual не дают authority на движение. Live vehicle HTTP open-loop evidence и ограничения приведены в отдельном vehicle audit; просмотр source recording не проверяет реакцию автомобиля на предложенные pedal/steering команды.

До финального утверждения frontend-доставки остаются успешная полная CI/admission, successful package/build, isolated candidate verification и reviewed UI-only install с protected-state proofs. Успех tests, отдельный API reload или ручная diagnostic publication не закрывают этот список. Работа с Windows migration, переустановка Windows, перенос/очистка Docker/WSL и изменение пользовательских приложений в этот scope не входили и не выполнялись.

## Первичные внешние основания

- [COLMAP 4.2.1 release/changelog](https://github.com/colmap/colmap/releases/tag/4.2.1) — версия pinned native инструмента; changelog отдельно описывает исправления global-mapper BA и отклонения degenerate two-view payloads. Наличие исправлений upstream не доказывает успех местного эксперимента.
- [Официальный COLMAP FAQ: OpenCV calibration и pixel convention](https://colmap.github.io/faq.html#using-calibration-from-opencv-kalibr-or-other-tools) — различие corner-centered COLMAP и integer-centered OpenCV координат. Точная resize/half-pixel реализация дополнительно проверяется локальными fixtures.
- [Официальный COLMAP FAQ: camera models / intrinsics](https://colmap.github.io/faq.html#choosing-the-right-camera-model) — выбор модели и self-calibration имеют ограничения; fixed-K не превращает выбранный фокус в физически измеренную калибровку.


## Уточнение после диагностики калибровки: измеренное начальное K

В `8f7c8bec` добавлен экспериментальный [route_intrinsics_prior.py](../../../scripts/pilot/route_intrinsics_prior.py). Первичная модель этой же записи даёт focal 606,098 px; отдельный аудит её фактических наблюдений подтвердил 144 ракурса, 69 591 наблюдение, минимум 86 уникальных пикселей на ракурс. Историческая удачная global-модель пришла к 604,476 px, но это наблюдение не зашито в код как число. Новый initializer берёт только проверенное K из текущей первичной модели той же записи: одинаковая проекция, разрешение, camera/image ID и имена, точный измеренный 2D-prefix, допустимая геометрия и повторный unique-pixel audit обязательны. Копируется только численная инициализация intrinsics; позиции камер и XYZ не копируются. Полная provenance связывает source/index/producer/assessment/измерения и камеры до/после. Focal в global mapper остаётся свободным; physical calibration остаётся `false`.

Координатор повторил 63 focused tests с фактическим pinned pycolmap 4.2.1: PASS, 2,74 с. Попытка [v5](../../../.local-pilot/skuter1-automatic-fused-20261102-v5/resource-refusal.json) остановлена ещё до копирования данных/детектора/solver: свежая RAM 5,835 ГиБ ниже неизменённого route CPU минимума 6 ГиБ. Новой модели нет; повтор не запускался. Поэтому этот initializer и весь fused engine по-прежнему экспериментальны, default OFF; ни основная карта, ни `skuter1` не заменены этим кодом.

## Отдельный бюджет замены UI

Для обновления одного ограниченного UI введён явный `--bounded-ui-resources` (`e83223cd`); default/global heavy-job guard 85% не менялся. Режим требует совпадения effective/resolved caps единственного UI: положительный RAM cap ≤1 ГиБ, RAM+swap ≤2 ГиБ и CPU ≤1; изменение остальных настроек запрещено. Свежие проверки требуют ≥4 ГиБ свободной RAM, ≥4 ГиБ absolute commit, commit <90%, ≥20 ГиБ диска и Healthy/OK. Он несовместим с degraded-volume exception. Три проверки с caps/profile сохраняются до планирования, загрузки и замены; 29 installer tests PASS. Это workload admission budget, а не hard limit памяти daemon-side Docker importer (`daemonImporterHardBound:false`).

Один [наблюдаемый предварительный import](../../../.local-pilot/unified-route-install-20261102-v1/image-import-receipt.json) выполнился без замены контейнеров: 75 samples, 11,703 с, максимальный commit 88,899%, минимум свободной RAM 6 104 453 120 bytes и absolute commit 11 107 475 456 bytes. 562 защищённых assets, все 46 контейнеров, API и OTA не изменились. Это измерение этой операции, а не универсальная оценка загрузки Docker. Исторические кэши/images оставлены: отдельный `--defer-cache-retention` пропускает только post-install cleanup; artifact/CI/OCI/resource проверки сохраняются.

## Последний фактический прогон measured-K

После появления достаточного свежего admission выполнена одна новая полная попытка [v6](../../../.local-pilot/skuter1-automatic-fused-20261102-v6/outcome.json). Она остановилась через 73,25 с во время нового SIFT extraction (около 75 из 173 кадров), до применения numerical prior, native verifier, calibrator, global mapper и BA. [Live refusal](../../../.local-pilot/skuter1-automatic-fused-20261102-v6/resource-refusal.json): RAM 5,918 ГиБ ниже неизменённого route CPU минимума 6; commit 89,077% ниже 90; disk 34,926 ГиБ, Healthy. Это отказ prescribed host reserve, не OOM и не геометрический отказ нового initializer. После этой попытки повтор не запускался.

В этой операции admission RAM была 6,737 ГиБ, затем 5,918; commit вырос лишь примерно на 0,050 ГиБ, paged/nonpaged kernel counters практически стабильны. По этим host counters нельзя приписать падение доступной RAM новой утечке ядра или только реконструкции. Все защищённые оригинальные hashes сохранены; принятой новой модели, изменения preferred scene или navigation admission нет. Measured-K остаётся проверенным кодом с неподтверждённым полным реальным результатом; default OFF сохранён.
