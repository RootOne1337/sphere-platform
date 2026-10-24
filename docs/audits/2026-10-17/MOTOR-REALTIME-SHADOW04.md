# Игра в реальном времени: проверка проектов и shadow policy

17 октября 2026 · worker `0.4.0` · реализация `60f02683`.

**Добавлен ограниченный асинхронный контур policy без физического ввода. Обученная
модель и автономная игра ещё не запущены.** Он принимает настоящий исходный RGB из
прямого APK-потока, связывает запрос и результат с observation/capture, ограничивает
очередь и отбрасывает запоздавшие результаты. Нейтральная заглушка — средство проверки
контракта, а не моторная нейросеть. [Хеши и результаты](MOTOR-REALTIME-SHADOW04.json).

## Что проверено в настоящих проектах

Исходники прочитаны как данные; чужие setup/скрипты не запускались, веса не скачивались.
Зафиксированы ревизии, а не только ссылки на изменяемый `main`.

| Проект и источник | Что видно в реализации | Применение и ограничение для Sphere |
| --- | --- | --- |
| [NitroGen game environment](https://github.com/MineDojo/NitroGen/blob/32608444660950ffda95e1e57c79632ad65bea10/nitrogen/game_env.py), [play loop](https://github.com/MineDojo/NitroGen/blob/32608444660950ffda95e1e57c79632ad65bea10/scripts/play.py) | Официальный цикл приостанавливает игру между шагами и синхронно получает prediction | Это не доказательство работы в непрерывной онлайн-игре. Не переносим pause/speedhack в Android. Нужны независимые observation, inference и execution clocks |
| [NitroGen response schema](https://github.com/MineDojo/NitroGen/blob/32608444660950ffda95e1e57c79632ad65bea10/nitrogen/mm_tokenizers.py), [порядок controls](https://github.com/MineDojo/NitroGen/blob/32608444660950ffda95e1e57c79632ad65bea10/nitrogen/shared.py) | Два двумерных стика и 21 button column; decoder ограничивает стики и выдаёт бинарные кнопки | Реализована независимая проверка декодированной формы. Названия вроде RIGHT_BOTTOM сохранены буквально; их нельзя самовольно сливать с DPAD |
| [NitroGen-Full play loop](https://github.com/subbon/NitroGen-Full/blob/a42921a39e44331a800f7d5d53fc3ce5a5680191/play.py) | Есть оптимизации и ограничение числа действий, но чтение prediction и исполнение chunk остаются последовательными | Скорость отдельного inference ещё не доказывает качество игры без пауз. Это кандидат для будущего benchmark, не готовый Android adapter |
| [Nexto bot](https://github.com/Rolv-Arild/Necto/blob/2e6ed7d6ed2b352e8ff529d4a12a0c9c70c28cca/rlbot-support/Nexto/bot.py) | Обновление действий привязано к игровым тикам, `tick_skip=8`; между решениями сохраняется controller state | Полезен принцип удерживаемого состояния. Вход — структурированный GameState; его скорость/качество нельзя переносить на pixel-only GTA policy |
| [MineStudio rollout worker](https://github.com/CraftJarvis/MineStudio/blob/278aa8553668d591339dbf30d281594ed06ee882/minestudio/online/rollout/rollout_worker.py) | Отдельные среды, polling, inference batches, адресованные ответы и hidden states | Полезное разделение env/policy lifecycle. Ожидание полного batch неприемлемо без latency deadline в живой игре; Ray пока не требуется для нашего одного worker |
| [VPT runner](https://github.com/openai/Video-Pre-Training/blob/095519fbd4ee0e9281d19f19601e45629de9ac3f/run_agent.py) | Есть исполняемый learned-policy цикл Minecraft: get_action → env.step | Доказан открытый программный путь запуска специализированной policy. Это не универсальная Android/GTA модель и не испытание нашей сети |

На дату чтения NitroGen main всё ещё указывает на `32608444`, совпадающий с предыдущим
исследованием. Это повторная проверка этих исходников, не заявление о неизменности всех
весов, форков или публикаций. Локальные копии и хеши перечислены в JSON-квитанции.

### Что пишут пользователи

В [обсуждении NitroGen #24](https://github.com/MineDojo/NitroGen/issues/24)
есть сообщение об игре Rocket League без speedhack и последующее уточнение автора:
результат преимущественно ограничивался движением, а не устойчивой игрой.
Другие участники сообщают сильно разные скорости на своих GPU. Это полезные
наблюдения, но не воспроизводимый benchmark Black Russia или нашего оборудования.
В документе не выдаются чужие FPS/VRAM за измеренную ёмкость Sphere.

## Решения для нашего контура

1. Игровое время не останавливается на inference. Камера, policy и будущий executor
   работают независимо; результат не ждёт в неограниченной FIFO.
2. На устройство разрешены один активный запрос и один последний ожидающий кадр.
   Промежуточные ожидающие наблюдения заменяются; выполняющийся запрос не размножается.
3. Ответ связан с request ID, receiver sequence, capture epoch и локальным поколением.
   Старый ответ отклоняется и после A→B→A смены capture identity.
4. Частота наблюдений не задаёт длительность кнопки. Chunk имеет явную частоту
   состояний; удержание — состояние между тиками. Просроченный chunk не запускается
   с начала. Реальное исполнение/согласование префикса chunk пока отсутствует.
5. Возраст принимается по локальным часам receiver. Это временная защита, не заменяющая
   source frame IDs и cross-host clock mapping. Числа perf_counter нельзя напрямую
   сравнивать между APK и будущим GPU-хостом.

5 Гц означают только выбранную частоту наблюдений. Достаточность для вождения
определяется скоростью игры, общей задержкой и качеством policy; она ещё не доказана.
Для будущего GPU-теста отдельно измеряются inference latency, p95 возраста результата,
частота просрочек и успешность маршрута. Короткий выигрыш в FPS не закрывает эти пункты.

## Что реализовано

[policy.py](../../../motor_worker/policy.py) содержит:

- Immutable original RGB frame с ограничением геометрии и объёма; без pickle и импорта Torch.
- Нормализованные состояния двух стиков/21 кнопки и chunk до 16 состояний/2 секунд.
  Частота states задаётся явно. Неверные формы, NaN, boolean numbers и выход за диапазон
  отклоняются; неизвестные столбцы не пропускаются молча.
- Read-only preview по прошедшему времени. Он показывает удержание и neutral по окончании,
  но не отправляет команды Android и не является native scheduler.
- Shadow loop: ограниченная очередь, проверка lineage, deadline, отмена и bounded telemetry.
  По умолчанию timeout 250 мс и предел receiver age 500 мс — тестовые budgets,
  не утверждённые игровые SLA.
- Если provider не завершает coroutine после отмены, loop закрывается с
  `policy_cleanup_unconfirmed`; следующий inference не запускается. Отмена coroutine
  сама по себе не доказывает остановку CUDA. Настоящему GPU-provider нужен управляемый
  процесс/сервис с собственной изоляцией и остановкой.

`ActionChunk.from_nitrogen` принимает уже декодированные bounded plain matrices.
Это не drop-in клиент upstream ZeroMQ/pickle и не поддержка checkpoint loader.
При одиночном действии upstream использует squeeze; будущий bridge обязан явно
восстановить матричную форму N×2/N×21, не угадывая её по длине плоского вектора.
Model preprocessing и точная частота из checkpoint metadata ещё требуют реализации.

### Запуск на настоящих кадрах без физических действий

```powershell
.local-pilot/motor-worker-venv/Scripts/python.exe -m motor_worker `
  --base-url http://127.0.0.1:3015 `
  --device 414ce0e9-4b93-4f96-b9ca-ee675f53835e `
  --seconds 15 --observation-hz 5 --shadow-policy neutral `
  --output .local-pilot/my-policy-shadow.json
```

Токен передаётся существующим способом через окружение. Этот пример не открывает
native input participant. Shadow и физический `--pointer-probe` вместе запрещены.
Отчёт содержит counters и timings, а не изображения или предсказанные кнопки.
Shadow получает исходный RGB размера capture; прежний RGB256 pilot hash считается
отдельно и не становится входом NitroGen автоматически.
RGB сохраняет размер декодированного H.264-кадра; потери видеокодека сохраняются.

## Проверки и обнаруженный дефект закрытия

68 тестов прошли в отдельном motor runtime, без skips. Помимо real H.264/DTLS/SCTP
проверены исходный RGB и его цвета, медленный provider при продолжающемся видео,
overload/latest replacement, неверный request ID, смена epoch, deadlines, зависшая отмена
и отсутствие физических команд в shadow. Ruff check/format прошли.

Повторный полный прогон выявил `unexpected_control_receipt` на завершении idle сеанса:
после отправки close ещё мог прийти точный ACK последнего heartbeat. Отдельный тест
воспроизвёл отказ до исправления. Теперь уже отправленный pending ALIVE/APPLIED может
быть принят до CLOSED без возврата READY. Чужой sequence, повтор и ACK после CLOSED
по-прежнему отклоняются; новых команд в closing нет. Отрицательные логи сохранены.

Результаты живых прогонов и привязка к окончательным исходникам находятся в JSON.
На PH011 локальный и Tuna shadow-прогоны приняли по75 ответов за15 секунд:
863/853 decoder outputs и4,995/4,999 RGB observations/с. Native input participant
в этих двух случаях не открывался; server→worker video с запуска0байт.
Отдельный pointer-прогон0.4 подтвердил6/6 точек и закрытие participant,
последний action ACK RTT6,234мс. Это конечные наблюдения, не GPU benchmark или SLA.
UI/API15ce и APK82 этим этапом не меняются; новая локальная версия worker — 0.4.0.
Существующая проверка конечного физического ввода описана отдельно в
[готовности0.3](MOTOR-WORKER03-READINESS.md).

## Открытый следующий этап

Нужны отдельные GPU-provider/preprocessing, сквозные source clocks/IDs, калиброванный
игровой профиль, capability-negotiated multi-touch или подходящий gamepad adapter,
подтверждённый native release, episode lease и atomic DAG delegation. Затем — один
supervised маршрут с измерениями, после него нагрузочные ступени.

Реальный model inference, отдельный GPU/LAN, успешная навигация и ёмкость 50 устройств
не приняты. Исследование реальных проектов помогает спроектировать проверяемые границы,
но не заменяет испытания нашей игры и железа.
