# Web → backend → APK: аудит callbacks и установленный canary

Дата: **1 октября 2026**, Asia/Yekaterinburg (UTC+5).
[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Readiness](../../operations/READINESS.md) ·
[JSON evidence](CALLBACK-LIFECYCLE-CANARY-EVIDENCE.json) ·
[PR #19](https://github.com/RootOne1337/sphere-platform/pull/19).

## Исправленные подтверждённые проблемы

| Слой | До исправления | Исправление и проверка |
| --- | --- | --- |
| Web | При смене устройства/auth отображался прежний APK report; медленные polls перекрывались; возраст отчёта застывал | Владение device/session, AbortSignal, один запрос в полёте, monotonic age и восстановление после failure. Три сценария падают на прежнем коде; полный frontend **582 passed**. [Контракт](STREAM-DIAGNOSTIC-OWNERSHIP.md) |
| Backend | Heartbeat отменял worker после собственного terminal commit во время закрытия SQL session | RENEWED / FINISHED / LOST с сохранением owner/generation fencing. Два реальных SQL reproductions падают до исправления; локальные recovery/cancel/admission/RLS **71 passed**. [Контракт](PIPELINE-TERMINAL-HEARTBEAT.md) |
| APK | Старые output/error callbacks обращались к остановленному codec; output возвращался после внешнего потребителя и мог остаться занят при exception | Владение codec, read/release под lifecycle lock, собственная копия до внешнего consumer, ограниченное уведомление ошибки. **13 regressions**, полный Dev/Enterprise **783 tests каждый, 782 passed / 1 skipped**. [Контракт](ENCODER-CALLBACK-OWNERSHIP.md) |

Эти дефекты воспроизведены в source tests. Они не объявляются единственной причиной
удалённых video gaps. Исправления не изменяют wire format, tenant policy или схему БД.

Изменённые runtime модули:
[DeviceStream.tsx](../../../frontend/components/sphere/DeviceStream.tsx),
[pipeline_recovery.py](../../../backend/services/orchestrator/pipeline_recovery.py),
[H264Encoder.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/H264Encoder.kt).

## Установленные версии и OTA

- Compiled frontend **8f615c6** установлен в **17:28:52 UTC+5**:
  `3015 → UI 3023 / API 18080`. Предыдущий Next 3022 сохранён для rollback.
- Backend **8d64ca4** установлен в **18:04:04**, healthy / build / readiness
  подтверждены. Image ID:
  `sha256:2cd185cf39a91cb753416384663a1d0b17741ca43932b4e9b688c112934e5025`.
  Database head `20260921_watchdog_stop`, соседние containers, public frontend,
  tunnel processes и OTA catalog/artifacts при этой замене не менялись.
- APK source **68155c1**, **1.2.40-dev / 10240**, **8465471 bytes**, SHA256
  `c612fba1e4a537ab1a0d9951e520bbd4063c3548308a4ebc31b72b59fa735a70`.
  Прежний pilot signer/package подтверждён; planar=true / GPU=false только в
  configured debug artifact, default flags false.
- По одному адресному OTA PH010 и remote PH025: **completed**, installed 10240,
  **recovered_after_process_restart=true**, свежая online version подтверждена.
  Использован android-canary catalog. Normal/global OTA и GitHub latest aliases
  не продвигались; production release и обновление всего парка не объявляются.

UI 8f615c6 и APK 68155c1 имеют те же соответствующие source trees, что принятый
code head 8d64ca4. Разные SHA исходников, artifact и installed runtime здесь
показаны явно; одинаковый номер версии не заменяет проверку SHA и signer.

## Фазово согласованный native video trial

Один собственный debug workload с auto-finish через 30 s, один metadata viewer
44 s, API diagnostics на 10/25/40 s. Перед запуском подтверждены idle launcher,
online 10240 и отсутствие capture. Input events, reboot/settings и global stop
не отправлялись. Сохранены только bounded packet metadata; Android pixel data
из этого прогона не публикуется. После закрытия собственного viewer последующий
readback подтвердил launcher и `not_streaming` на обеих машинках.

| Показатель | PH010, local | PH025, remote |
| --- | ---: | ---: |
| Native display / resolution | ~60 Hz / 960×540 | **5 Hz / 960×540** |
| Первый wire picture от начала подключения viewer | **0.860 s** | **9.844 s** |
| Pictures за окно 3..13 s | **299 / 10 s** | **4 / 10 s**, включая startup |
| Все pictures за 44 s viewer | 868 | 43 |
| Post-encoding API read около 25 s | capture60 / render30 / encode29 | capture4 / render5 / encode5 |
| Captured / rendered / encoded totals того snapshot | 1252 / 630 / 629 | 21 / 20 / 20 |
| Raw throttled / codec input drops | 622 / 0 | 1 / 0 |
| WS attempted / rejected, encoder errors | 631 / 0, 0 | 22 / 0, 0 |

Не интерпретируйте 4/10 s на PH025 как steady-state 0.4 FPS. Следующее окно
13..23 s содержит 21 picture. Позже arrival gaps **3.125/3.094/5.063 s** близки
producer PTS gaps **3.110/3.090/5.060 s**. Это сужает следующий поиск до
source/capture/encoder admission и полного picture transport; не исключает
потерю целых pictures и не измеряет абсолютную сетевую задержку.

На 10 s API ещё не содержал APK report, хотя viewer уже получил picture.
На 25 s получен post-encoding heartbeat. На 40 s это тот же snapshot с возрастом
около 18 s local / 20 s remote. Поэтому нулевые drops/errors относятся к
зафиксированной части workload, а не ко всему trial. Новая UI показывает возраст
между polls и не превращает старый snapshot в текущий frame telemetry.

## Backend recovery после замены

Первый readback **18:05:42**: 19 records / **13 online / 6 offline**, PH010/PH025
online 10240, launcher и `not_streaming`. Отличие от pre-rollout — PH028/10232.
Логи фиксируют heartbeat в **18:03:59**, disconnect code 1005 в **18:04:39**,
новую auth session и heartbeat в **18:05:46**. Предыдущий client failure code 1012
совпадает с заменой backend; причина последующего code 1005 не установлена.

Три GET-only среза **18:10:41 / 18:10:51 / 18:11:01**: **14 online / 5 offline**,
тот же набор online устройств, что до rollout. Это finite recovery evidence,
не uptime SLA и не подтверждение всех ожидаемых оператором 23 устройств.
Краткий offline не удалён из отчёта. PH028 не обновлялся и остаётся на 10232.

## CI и контрпримеры

Принятый code head **8d64ca4**:

- [Backend 36864314898](https://github.com/RootOne1337/sphere-platform/actions/runs/36864314898):
  **2140 passed / 15 skipped**, OpenAPI, runtime RLS, Alembic single-head,
  lint/types, security, production bootstrap, metrics replacement и Redis
  pressure/restart passed.
- [Frontend 36864314913](https://github.com/RootOne1337/sphere-platform/actions/runs/36864314913):
  tests/types/build passed; локально **73 suites / 582 tests**, isolated compile passed.
- [Android 36864314903](https://github.com/RootOne1337/sphere-platform/actions/runs/36864314903):
  все предусмотренные variants/tests и signed release smoke build passed.
  Canary artifact отдельно проверен полными configured debug suites.

Первый backend CI 68155c1 дал **2139 passed / 15 skipped / 1 failed**:
RLS test наблюдал прежний bool hook вместо нового internal heartbeat result.
Обновлён test hook с проверкой двух RENEWED и запретом LOST. Production RLS
не ослаблена, timeout не увеличен. Failed run и исходные terminal race
reproductions сохраняются в [pipeline audit](PIPELINE-TERMINAL-HEARTBEAT.md).

Public JSON проверен на соответствие receipts и packet counts: **911 metadata
entries**, два terminal completed 10240/restart-recovered. Тексты source tests
и raw logs не заменяют эти installed measurements. В документах проверены
**732 relative targets / 22 anchors в 17 документах, missing0**; результаты
проверки не являются browser visual QA.

## Следующие проблемы по приоритету

1. **Remote capture progress.** Planar listener отбрасывает повторный/обратный
   Image timestamp до `recordCapturedFrame()`. Эти skips пока не входят в
   опубликованные raw counters. Следующий canary должен учитывать source callback
   progress и timestamp rejection отдельно; текущие 21 captured не доказывают,
   что ImageReader callback был вызван всего 21 раз.
2. **Applied source limit и startup.** PH025 по-прежнему 5 Hz; установка оператором
   10 FPS на другую/эту машину не подтверждена readback. Не обещать target10–15
   при source 5, не дублировать кадры для повышения счётчика. Длинный first picture
   9.844 s остаётся открытым даже при допустимом host limit.
3. **Browser и input.** Receive/draw FPS, motion quality, static-input/navigation
   и абсолютная input-to-visible latency требуют отдельной приёмки. Текущая CUA
   review заблокирована URL policy и не обходилась; native pictures не являются
   browser screenshots или доказательством визуального отклика.
4. **Android 14+ recovery.** Повторное создание VirtualDisplay на старой
   MediaProjection требует отдельного native contract; lifecycle fix codec
   callbacks этот gate не закрывает.
5. **Sustained/fleet.** CPU/RAM/queues, snapshot demand arbitration,
   combined stream+autonomous scripts на 20–30 distinct устройств,
   production signer/OTA, clone/cold-host-boot остаются открытыми.

PR остаётся draft. Массовая установка и окончательная production-приёмка
не выводятся из зелёного CI или двух успешных OTA.
