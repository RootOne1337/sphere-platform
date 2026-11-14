# Настройки teach-run, раскладка LDPlayer и границы3D

24 октября2026, worker0.8.1. Продолжение [проверки recorder0.8.0](MOTOR-TEACHING080.md).
[Квитанция](LDPLAYER-KEYMAP-READINESS081.json), SHA-256 normalized LF
`b0e9fc78c41ca0f434502011597a27dc780097cd2b4d6db2eef296ad845f76a9`.
303 motor tests/76,960с и Ruff passed; источник4 файлов связан digest-ами.
Новый компонент `motor_worker.keymap_inspect` — ограниченный **read-only inspector**,
не импортёр исполняемых макросов/не готовый keymapper. APK/API/установленный веб,
эмуляторы, игра и конфиги LDPlayer не изменялись. Нейронки/3D SDK не скачивались.

## Решение по разрешению, DPI и render scale

Для проверки клавиатуры сначала оставить960×540,160 DPI. Качественный teach-run
после готовности одновременного ввода:1920×1080, **320 DPI**,60FPS target и100%
внутреннего rendering игры. Фактические уникальные FPS/source bitrate надо измерить,
30 стабильных source FPS остаются допустимым первым baseline.120FPS не требуется.
Для последующего повторения вернуть рабочие960×540,160 DPI и50% game rendering,
затем проверить узнаваемость на независимом low-quality повторе.

Выбор320 — расчётная исходная точка для сохранения Android logical layout:
`dp=px*160/dpi`.960×540/160 и1920×1080/320 дают960×540dp;1920×1080/280 дают примерно
1097×617dp. DPI влияет на layout, а не добавляет деталей3D-сцене. Источник:
[Android grids/units](https://developer.android.com/design/ui/mobile/guides/layout-and-content/grids-and-units).
Игровой HUD может масштабироваться собственным кодом, поэтому равенствоdp не
является доказательством неизменных кнопок; нужна свежая проверка source geometry/HUD.

Render50% — отдельный от DPI параметр. Для качественной демонстрации его поставить
на штатные100%, не оставлять50%. Семантика конкретного игрового slider отдельно
не измерена; нельзя обещать точные480×270 для low-render, если движок использует
свой pipeline. Повышение выходного разрешения не возвращает потерянные внутри
игрового renderer детали. Одна запись не квалифицирует все настройки и ракурсы.

## Что реально содержат переданные файлы

| Файл | Результат чтения |
| --- | --- |
| `customizeConfigs/com.br.top_960x540.kmp` |843B; `keyboardMappings=[]`. Внутренний `resolutionPattern=1600×900`, несмотря на имя960×540. По имени нельзя определять координатную систему. |
| `customizeConfigs/com.br.top.smp` |485B;960×540 keyboardId=`Black Russia.kmp`, joystickId пуст. Это выбор профиля и UI flags, не сами bindings. |
| `customizeConfigs/com.android.vending.smp` |477B; оба references пусты. Не профиль игрового управления. |
| `recommendConfigs/Black Russia.kmp` |20160B; найден по ссылке из `.smp`, прочитан явно.26 mappings:1 Disc,16 Curve,1 MouseTrigger,7 Macros,1 MouseDrag. |

Disc содержит VK65/87/68/83 (A/W/D/S), origin1503/8172, radius772. Camera MouseDrag
содержит key18 и origin5600/3667. Эти значения лежат в наблюдаемом диапазоне0…10000;
публичный wire spec LDPlayer для этой структуры не найден. Units radius/sensitivity/
curve timing не квалифицированы, преобразование в actual Android coordinates
остаётся кандидатом до проверки кадром и тестом. Snapshot сам по себе не доказывает
весь runtime выбор LDPlayer: это подтверждённая ссылка `.smp` и совпадающий layout.

У7 macros есть ключи66/77/32/17/39/37/101. По данным файла Space32 описан как
прыжок с двумя `touch` и `wait`; Ctrl17 — приседание с аналогичной конструкцией.
Здесь содержимое только исследовано как данные, **не исполнялось**. Внешние
`switch-mouse`, `press/release` и другие команды нельзя считать готовыми Sphere
операциями или без проверки переносить в сервер/Android shell.

[Документация LDPlayer](https://de.ldplayer.net/support/keymapping-on-emulator.html)
подтверждает отдельные WASD movement и view controls. Это источник пользовательской
семантики; он не делает проприетарный `.kmp` публичным стабильным wire protocol.

## Какой режим записи нужен

Для полного teach-run предпочтителен Sphere keymapper: клавиатура и мышь→профиль
управления→общий native multi-contact actor; recorder пишет actual Android-bound
state changes/receipts и original video. Эти события могут потом использоваться
исполнителем без зависимости от LDPlayer. Рисунок клавиш в вебе не равен этому actor.

**Сейчас этот режим ещё не реализован.** Console0.8.0 умеет один pointer. В APK
`ContinuousInputController` явно объявляет `max_pointers=1`, а shared wire принимает
только `sequence/gesture/action/x/y`. Прежние14 APPLIED/3-с hold доказывают запись
одного жеста, не одновременные WASD+camera+jump. Добавить JS keydown поверх этого
wire недостаточно: второй tap либо потребует отпускания стика, либо будет отказан.
Нельзя выдавать такой режим за полноценное управление двумя руками.

Можно играть непосредственно в LDPlayer и снимать видео через Sphere. Но нынешний
own-input journal не увидит события его host keymapper. Такая запись имеет статус
`video_only`, полезна для ориентиров/геометрии и не является полным input demo.
Запись произвольной внешней клавиатуры/Android MotionEvents — отдельный adapter,
не неявная функция screen capture. Приоритет текущего проекта — общий Sphere actor.

## Следующая реализация одновременного ввода

1. Версионированный capability contract: отдельный native multi-contact режим,
   фактический лимит contacts и явный отказ на старом APK. Старые single-pointer
   клиенты остаются совместимы; никаких скрытых downgrade с отпусканием стика.
2. Android/native actor хранит стабильные pointer IDs и общий gesture downTime.
   MOVE не пересоздаёт контакт; добавление/снятие второго/третьего пальца использует
   корректные POINTER_DOWN/POINTER_UP и индекс Android. Один pending APPLIED;
   потеря/неопределённость означает cancel-all и подтверждённый release.
3. Для первого игрового профиля достаточно трёх одновременно активных ролей:
   movement stick, camera drag, action button. Это целевой MVP, не текущий capability.
   Очереди, число контактов, частота MOVE и длительность действий ограничены.
   Владение одним физическим gesture set не раздаётся независимым writer-ам.
4. Browser keydown/up подавляет autorepeat и хранит held set. WASD формирует один
   аналоговый вектор с нормализацией диагонали/нейтрали; смена направления вызывает
   MOVE без повторного DOWN. Противоположные клавиши определены профилем.
   Камера получает отдельный контакт; jump/action не снимает movement.
5. Blur/hidden/focus loss/автоматизация/timeout/capture epoch смена освобождают
   **все** contacts. Открытый чат/текстовое поле отключает игровой keyboard mode.
   На пробел/Alt/Ctrl нельзя полагаться без обработки browser shortcuts/focus.
6. Профиль хранит package/layout/density/render/camera revisions и normalized
   bindings. `.kmp` служит источником кандидата; opaque macros требуют явного
   преобразования в ограниченные declarative операции. Python/shell/macro text
   не исполняется. Возврат с1080p320 на540p160 требует проверки HUD/profile binding.
7. Journal получает multi-contact state transitions, IDs, submitted/applied times
   и terminal cancel/release. Старый single-pointer dataset не переименовывается
   в multi-touch demo. Shared clock mapping остаётся отдельной задачей.
8. Допуск: neutral→W hold→W+A→W+camera→W+jump→release, unknown/lost receipt,
   reconnect/epoch/blur/AFK, no game world и отказ старого APK. Сначала стенд,
   затем конечные реальные жесты; только потом человеческий маршрут.

До этого полного прохода с клавиатурой не начинать. Прежняя готовность recorder
к controlled capture trial сохраняется в своей узкой области; она не означала
готовность всех способов ручного управления.

## Визуализация: что будет видно и где требуется3D

Первый полезный viewer — синхронные панели original frame/preview, найденные
landmarks/masks, mini-map path/goal, выбранный checkpoint, uncertainty, input state
и gaps/stop reasons. Линии, вычисленные из того же кадра, можно честно наложить на
него без заявления о world pose. Для trajectory projection в3D-вид нужны
camera intrinsics/extrinsics/pose и согласованный path frame.

Для такого viewer подходит [Rerun](https://github.com/rerun-io/rerun-docs/blob/main/docs/getting-started/viewer-walkthrough.md):
он связывает2D images/keypoints, camera model,3D points/transforms и временные
метрики. Он **показывает** переданные данные; сам не восстанавливает карту из
нашего H.264. Связать worker receive/submitted clock можно с явной погрешностью;
native uptime и source capture clock нельзя объявить идеально синхронными.

Для3D есть отдельные offline варианты:

- [COLMAP SfM/MVS](https://colmap.github.io/tutorial.html): camera poses/sparse
  scene, затем dense depth/point cloud. Нужны перекрывающиеся ракурсы и перенос
  камеры; одного вращения на месте недостаточно для хорошего baseline. Автор
  рекомендует downsample видео, а не использовать без разбора все60FPS.
- [ABot-Recon](https://github.com/amap-cvlab/ABot-Recon): актуальный2026 streaming
  monocular reconstruction; опубликованы camera trajectory, point maps и confidence,
  а14 октября добавлена3D/BEV визуализация. В авторском efficiency benchmark
  504×280/H100:24,45FPS/6,71GiB, A100 release environment. Это не RX9070/3070M
  benchmark и не обещание нашей скорости. Рассматривать после получения teach video.

Наш raw capture пока не содержит depth, odometry или game world pose, а current
route bundle хранит признаки видов. Поэтому3D LiDAR-подобная сцена **не получается
автоматически**. Monocular reconstruction может иметь drift, неверный масштаб
и дыры; HUD/avatar/другие игроки нужно исключать. Сходство картинки не доказывает
проходимость, свободное пространство и метровую точность. Координатные anchors
игры могут помочь проверить масштаб; generic pipeline не должен требовать их.

Реконструкцию разумно выполнить один раз offline для общих изученных маршрутов,
не на каждом из50 runtime emulators. Runtime остаётся latest-frame/3–5Гц correction
с ограниченным состоянием/остановкой. Гарантии fleet throughput этим не появляются.
Красивый overlay также не доказывает, что NitroGen/P2P научились принимать его
как цель; нужны opposite-goal тесты и реальные повторные достижения.

## Как проверить inspector

```powershell
python -m motor_worker.keymap_inspect --file "C:/LDPlayer/LDPlayer9/vms/customizeConfigs/com.br.top.smp"
python -m motor_worker.keymap_inspect --file "C:/LDPlayer/LDPlayer9/vms/recommendConfigs/Black Russia.kmp" --output C:/reports/black-russia-keymap.json
```

Output должен отсутствовать, его parent должен существовать. Inspector читает
UTF-8/BOM до256KiB,≤128 mappings,≤1024 curve points и≤16KiB macro text; JSON duplicates,
вне диапазона coords, boolean geometry, bad/регрессирующий timing отклоняются.
`.smp` references автоматически не открываются, traversal/не-basename запрещены.
Macro output содержит только размер/digest, исходный текст не печатается.
У всех entries `executable=false`; `complete_for_execution=false` независимо от
узнанного класса. Ни UDP/native control, ни UI, ни LDPlayer settings он не меняет.
