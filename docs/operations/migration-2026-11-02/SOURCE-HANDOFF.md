# Передача неотслеживаемых Python-исходников: 2 ноября 2026

Этот список — точечная проверка исходного рабочего дерева. Все 97 проверенных Python-файлов добавлены адресно в commit `06be4860`; прежние байты сохранены в закрытом архиве перед форматированием. Остальные локальные артефакты не считаются разрешёнными к публичной публикации. Не делайте `git add .`.

## Результат и границы

Найдено 97 неотслеживаемых `.py`: 6 в `motor_worker/`, 58 в `scripts/pilot/`, 33 в `tests/`. Все 97 разбираются Python AST; статические импорты `motor_worker.*` и `scripts.pilot.*` разрешаются в текущем дереве (динамический импорт и полноценная установка не проверялись). Регулярные выражения не выявили private-key blocks, очевидные литеральные присваивания паролей/токенов, абсолютные Windows Users/home paths; это не гарантия отсутствия секретов. `detect-secrets scan --all-files` на этих 97 файлах указал два high-entropy совпадения в одном файле: строки 112–113 вручную проверены и являются фрагментами путей, не credentials. Ещё 17 скриптов содержат идентификатор конкретной записи/эксперимента в локальных относительных путях или подписях; пользователь разрешил публиковать эти имена. Дополнительный поиск учётных данных, email, IP и персональных абсолютных путей в этих 17 файлах не дал совпадений. Два сигнала detect-secrets в `render_cross_session_pairs.py:112-113` вручную определены как фрагменты локальных путей к задачам, не credentials. Все 97 — кандидаты для адресного staging после финального diff; относительные пути к экспериментам останутся непереносимыми до предоставления данных. Ни поиск, ни ручная классификация не являются гарантией отсутствия всех секретов. Возможны зависимости тестов от файлов в группе review: переносить связанными наборами, а не по одному.

Префиксы `analyze_`, `audit_`, `compare_`, `diagnose_`, `filter_`, `replay_`, `render_`, `export_`, `reconstruct_` в `scripts/pilot` относятся к диагностике/экспериментам или визуализации, а не являются автоматически запускаемым production-сервисом. `windows_disk_scan.py` — отдельная host-диагностика. Шесть `motor_worker/visual_*.py` — код моторной/визуальной логики; тесты относятся к ней и к исследовательским скриптам. Названия показывают назначение, но не доказывают, что каждая функция используется в рабочем runtime.

## Проверки

- `.venv-audit` Python 3.12: запуск всех 33 новых тестовых файлов с локальной тестовой переменной JWT дошёл до сбора и завершился ошибкой: шесть файлов требуют отсутствующий `numpy`. Само наличие JWT в окружении теста не меняет установленную конфигурацию.
- Системный Python 3.13: `pytest --noconftest -q -o addopts=` для 32 файлов — **97 passed, 12 subtests passed**, одна конфигурационная warning (`asyncio_mode`, плагины были выключены). Версии: numpy 2.2.6, OpenCV 4.11.0, pytest 9.0.2, Pillow 11.2.1. Это обход общего `conftest.py`, не полная интеграционная проверка.
- `.local-pilot/motor-worker-venv` Python 3.12: `unittest discover` для `test_compare_independent_capture_places.py` — **3 passed**; использована уже имевшаяся среда с numpy/cv2/av. Вместе покрыты все 33 файла, но не одной воспроизводимой средой. Системный Python не имел `av` и потому исходный запуск всех 33 имел одну ошибку сбора.
- `requirements-motor-worker.txt` и `requirements-motor-vision.txt` фиксируют часть Python-зависимостей (в том числе numpy 2.4.4, av 17.1.0 и opencv-python-headless 4.13.0.92). Аналитические скрипты дополнительно импортируют `pycolmap`, `matplotlib`, иногда `torch`; полная совместимая lock-конфигурация для всех 58 исследований отдельно не доказана. На новом хосте создать окружение из фиксированных зависимостей и отдельно проверить платформенные wheels, модели, лицензии и контрольные суммы; имеющиеся `.local-pilot` venv не являются переносимым lockfile.

## Важное для чистого развёртывания

`frontend/src/features/stream/reconstructionClient.ts` и `ReconstructedScene.tsx` обращаются к `http://127.0.0.1:3342` из браузера. Это **компьютер браузера**, не адрес удалённого сервера. `scripts/pilot/route_service_watchdog.py` — Windows-only helper, ожидающий локальную `.local-pilot/motor-worker-venv`; `reconstruction_service.py` по умолчанию также ожидает `.local-pilot/motor-amd-venv/Scripts/python.exe`, складывает jobs в `.local-pilot/reconstruction-jobs`. Compose-файлы в текущем поиске не поднимают этот loopback worker. Инструменты геометрии/рендера, pycolmap, модели и данные находятся в отдельном контуре, в том числе локальные tool paths в `reconstruct_route.py`/`reconstruct_surface.py`; их наличие, лицензии и работоспособность на новой машине не установлены. Базовое развёртывание с пустой БД и первым администратором должно работать независимо; локальная реконструкция — отдельно устанавливаемая и проверяемая возможность, а не автоматически работающая часть обычного Docker deploy. Нельзя просто перенаправить защищённый loopback наружу: сначала требуется отдельный дизайн аутентификации, изоляции и доступа.

Изменённый `docs/design/LONG-ROUTE-TEACH-REPEAT.md` ссылается на существующие, но неотслеживаемые `docs/audits/2026-10-27/VISUAL-REPEAT-AND-MOTOR-DIRECTION.md` и `FUFLO228-OVERLAP-RECONSTRUCTION-EXPERIMENT.md`. Локально ссылки обеих документов разрешаются, но документы дополнительно проверены detect-secrets (0 совпадений) и поиском email, IP, персональных абсолютных путей и литеральных учётных данных (0 совпадений); идентификаторы экспериментов пользователь разрешил публиковать. В обоих файлах нет Markdown-изображений; все локальные ссылки существуют, у первого целевые исходники и документы отслеживаются Git. Сканирование не гарантирует отсутствие всей чувствительной информации. При публикации design-файла добавить оба отчёта и убедиться в наличии всех их ссылок в итоговом коммите; иначе на новом clone ссылки будут отсутствовать.

## Проверенные записи с путями к экспериментам

- `scripts/pilot/compare_independent_capture_places.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/compare_sequence_dropout.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_cross_capture_audit.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_cross_session_pairs.py` — два сигнала detect-secrets, строки 112–113: вручную определены как пути
- `scripts/pilot/render_fuflo228_evidence_boards.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_lightglue_comparison.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_place_candidate_frames.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_place_sequence_comparison.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_reacquisition_faults.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_route_progress_comparison.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_sfm_klt_comparison.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_sfm_localization_diagnostic.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_sfm_orientation_overlap.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_sfm_overlap_comparison.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_sfm_pair_evidence.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_sfm_temporal_klt.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/render_visual_pose_crosscheck.py` — идентификатор локальной записи/эксперимента
- `scripts/pilot/replay_route_progress_capture.py` — идентификатор локальной записи/эксперимента

## Остальные кандидаты для адресного staging

- `motor_worker/visual_global_recovery.py`
- `motor_worker/visual_place.py`
- `motor_worker/visual_place_sequence.py`
- `motor_worker/visual_reacquisition.py`
- `motor_worker/visual_servo_diagnostic.py`
- `motor_worker/visual_servo_epipolar_diagnostic.py`
- `scripts/pilot/analyze_pnp_alternatives.py`
- `scripts/pilot/analyze_pnp_candidate_budget.py`
- `scripts/pilot/analyze_sfm_klt_regions.py`
- `scripts/pilot/audit_frame_reconstruction_coverage.py`
- `scripts/pilot/audit_graph_track_retention.py`
- `scripts/pilot/audit_graph_triangulation.py`
- `scripts/pilot/audit_pnp_inlier_distribution.py`
- `scripts/pilot/audit_saved_match_coverage.py`
- `scripts/pilot/audit_saved_sfm_coverage.py`
- `scripts/pilot/audit_sfm_orientation_overlap.py`
- `scripts/pilot/audit_sfm_pairs_lightweight.py`
- `scripts/pilot/compare_covisibility_jumps.py`
- `scripts/pilot/compare_landmark_selection.py`
- `scripts/pilot/compare_lightglue_sift_probe.py`
- `scripts/pilot/compare_remapped_sfm_correspondences.py`
- `scripts/pilot/compare_sfm_klt_consistency.py`
- `scripts/pilot/compare_sfm_overlap.py`
- `scripts/pilot/compare_visual_and_pose_diagnostics.py`
- `scripts/pilot/diagnose_covisibility_localization.py`
- `scripts/pilot/diagnose_keyframe_2d3d.py`
- `scripts/pilot/diagnose_lightglue_keyframes.py`
- `scripts/pilot/diagnose_sfm_self_pnp.py`
- `scripts/pilot/diagnose_visual_servo.py`
- `scripts/pilot/diagnose_visual_servo_temporal.py`
- `scripts/pilot/export_sfm_track_localization_trial.py`
- `scripts/pilot/filter_sfm_pair_graph.py`
- `scripts/pilot/filter_sfm_temporal_graph.py`
- `scripts/pilot/reconstruct_saved_graph_trial.py`
- `scripts/pilot/render_candidate_diversity_demo.py`
- `scripts/pilot/render_cross_session_candidates.py`
- `scripts/pilot/render_cross_session_localization.py`
- `scripts/pilot/render_offline_route_check.py`
- `scripts/pilot/render_pnp_inlier_frames.py`
- `scripts/pilot/render_route_architecture_boards.py`
- `scripts/pilot/replay_cross_session_streak.py`
- `scripts/pilot/replay_global_recovery.py`
- `scripts/pilot/replay_place_sequence.py`
- `scripts/pilot/replay_reacquisition_faults.py`
- `scripts/pilot/replay_saved_pnp_gate.py`
- `scripts/pilot/windows_disk_scan.py`
- `tests/test_analyze_pnp_alternatives.py`
- `tests/test_analyze_pnp_candidate_budget.py`
- `tests/test_audit_frame_reconstruction_coverage.py`
- `tests/test_audit_graph_track_retention.py`
- `tests/test_audit_graph_triangulation.py`
- `tests/test_audit_saved_match_coverage.py`
- `tests/test_audit_saved_sfm_coverage.py`
- `tests/test_audit_sfm_orientation_overlap.py`
- `tests/test_audit_sfm_pairs_lightweight.py`
- `tests/test_compare_covisibility_jumps.py`
- `tests/test_compare_independent_capture_places.py`
- `tests/test_compare_lightglue_sift_probe.py`
- `tests/test_compare_remapped_sfm_correspondences.py`
- `tests/test_compare_sequence_dropout.py`
- `tests/test_compare_sfm_klt_consistency.py`
- `tests/test_compare_sfm_overlap.py`
- `tests/test_compare_visual_and_pose_diagnostics.py`
- `tests/test_diagnose_covisibility_localization.py`
- `tests/test_diagnose_keyframe_2d3d.py`
- `tests/test_diagnose_lightglue_keyframes.py`
- `tests/test_export_sfm_track_localization_trial.py`
- `tests/test_filter_sfm_pair_graph.py`
- `tests/test_filter_sfm_temporal_graph.py`
- `tests/test_reconstruct_saved_graph_trial.py`
- `tests/test_render_offline_route_check.py`
- `tests/test_replay_cross_session_streak.py`
- `tests/test_visual_global_recovery.py`
- `tests/test_visual_place.py`
- `tests/test_visual_place_sequence.py`
- `tests/test_visual_reacquisition.py`
- `tests/test_visual_servo_diagnostic.py`
- `tests/test_visual_servo_epipolar_diagnostic.py`
- `tests/test_windows_disk_scan.py`

## Необязательная установка локального worker

Запустите в PowerShell **на компьютере, где открыт браузер**, из корня checkout:

```powershell
.\scripts\migration\setup-route-runtime.ps1 -Plan
.\scripts\migration\setup-route-runtime.ps1 -Install -PythonPath 'C:\Path\To\Python312\python.exe'
```

Первый вызов выводит план и выполняет только чтение: определяет версии локальных Python, наличие модулей/части инструментов и опрашивает loopback health; без `-Install` данные не изменяются. Второй создаёт две новые venv и устанавливает зафиксированные пакеты, поэтому ему нужен доступ к реестру Python-пакетов; существующие venv скрипт не трогает и останавливается, если целевой путь занят. При наличии `py.exe` с Python 3.12 аргумент `-PythonPath` можно опустить. Для необязательной регистрации входа текущего пользователя добавьте `-InstallTask` к тому же вызову с `-Install`: задача `SphereRouteService` не перезаписывает одноимённую и при регистрации не запускается. Без этого флага запустите вручную после установки:

```powershell
.\.local-pilot\motor-worker-venv\Scripts\python.exe -m scripts.pilot.reconstruction_service
```

Worker слушает только `127.0.0.1:3342`, по умолчанию допускает origin `http://127.0.0.1:3015`; другой адрес веба требует согласованной отдельной конфигурации. Установка не получает модели, COLMAP/Brush и другие инструменты, не создаёт задания и не доказывает успех 3D или автономного маршрута. Пока worker и его необходимые инструменты не настроены, браузер честно показывает его недоступным. Проверены синтаксический разбор PowerShell и вызов `-Plan -InstallTask`; реальная чистая установка и регистрация задачи в этой проверке не выполнялись. `reconstruction_service --help` прошёл в ранее существовавшей среде; это не проверка нового окружения.

### Наличие реконструкционных инструментов и исходных материалов

На проверенном хосте 2 ноября loopback `3342/health` ответил HTTP 200 с `service=sphere-reconstruction-v1` и `one_active_job=true`; это идентификация живого процесса, не запуск или успешная реконструкция. Обе прежние venv содержат Python 3.12.12 и numpy/cv2; `av` обнаружен в motor-worker venv, но не обнаружен в прежней motor-amd venv. `-Plan` только проверяет наличие нескольких инструментов, а не исправность, версии каждой DLL или их происхождение.

В `.local-pilot/reconstruction-tools` имеются каталоги `pycolmap-4.2.1`, `openmvs-v2.4.0-cpu`, `brush-v0.3.0`, `brush-system-timing`, архив Brush и вспомогательные model/tool каталоги; runtime-файлы указывают точные пути в `scripts/pilot/reconstruct_route.py` и `reconstruct_surface.py`. `pinned-delivery.json` и `delivery.json` содержат сведения о pycolmap, av, Brush и SHA-256, `reconstruct_route.py` проверяет архив Brush и receipt локальной сборки; конкретные OpenMVS бинарники дополнительно проверяются кодом surface. Локальные модели/веса и среды могут быть большими, зависеть от Windows, GPU, лицензии и загрузок. Они не являются одним полным воспроизводимым lock для всего контура и новый установщик их не скачивает.

Для переноса фактических исследований отдельно сохранить в защищённый SSD-комплект с проверенными хешами и сверкой восстановления: выбранные важные исходные записи/OPFS-экспорты, `.local-pilot/reconstruction-jobs` и связанные map/reconstruction outputs, receipts, собственные заметки и конфиги; по согласованию — `.local-pilot/reconstruction-tools` и локальные venv как архив исходной машины. Venv не считать переносимой установкой. Веса и tool binaries, при наличии надёжного источника, лицензии и подтверждённых hashes, могут быть повторно получаемыми, но для этого конкретного набора происхождение и восстановление не проверены; до проверки не считать их воспроизводимыми. После переноса сверить хеши, платформу и зависимости и отдельно проверить реальные файлы/визуальную приёмку без запуска движения.

## Форматирование перед передачей

По согласованному списку 97 файлов выполнены `ruff format`, безопасные автоисправления `ruff check --fix` и локальная замена 16 font-лямбд на функции и неоднозначной переменной координаты. `ruff check` и `ruff format --check` прошли на всех 97 файлах. После форматирования профильные тесты повторены: 97 passed + 12 subtests (32 файла, системный Python, `--noconftest`) и 3 passed (оставшийся файл, motor-worker Python 3.12). Оригиналы до форматирования сохранены отдельно в приватном архиве; сами исходные данные не затрагивались.
