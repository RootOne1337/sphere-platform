# NitroGen и Open Pixel2Play: локальный запуск на RX 9070 через Sphere

17 октября 2026 · worker0.4.1 · [машиночитаемые измерения](MOTOR-AMD-LOCAL41.json).

## Что выполнено

Обе модели действительно скачаны, загружены с настоящими весами и исполнили GPU inference
на AMD Radeon RX9070 под Windows. Кадры получены от APK PH011 через Sphere WebRTC;
не использованы desktop capture, ADB, Recap, Windows virtual gamepad или замедление игры.
Это локальный измерительный пилот. Он не означает принятую автономную игру или готовый production provider.

UI/API15ce2b62 и APK1.2.82-dev сохранены. В исходниках frontend отдельно исправлен фокус
аппаратной клавиатуры внутри модальной карточки устройства: предок `role=dialog` ошибочно
блокировал захват фокуса после нажатия canvas. Локальный frontend profile для667acb09 прошёл;
этот frontend ещё не установлен и статус GitHub не опубликован.

## Среда и происхождение

- Изолированные `.local-pilot/motor-amd-venv` и `.local-pilot/motor-worker-venv`.
- Python3.12.12; официальный AMD ROCm7.2.1 / torch2.9.1+rocm7.2.1 / torchvision0.24.1.
- GPU определён как RX9070, доступно около16GiB VRAM. FP32/FP16/BF16 matmul и SDPA дали конечные результаты.
- Драйвер32.0.31041.1004 сохранён; драйвер/WSL/защита Windows не менялись.
- NitroGen: code32608444, HF584c8dde, `ng.pt` SHA256
  `a266f5fb9c7dbdcdf97216558d2d82075a9a994b824cda69afa9fd3280260a81`.
- Open P2P150M: codea329d98c, HFde18b62b, checkpoint SHA256
  `2a3b43121144ca2d9c2b8aa605e313184c98ac5ef6d2c3b530c2d353d886c5bc`.
- Checkpoint scan: unsafe globals отсутствуют; загрузка `weights_only=True`, `mmap=True`, strict state dict.
- Полные веса vision towers взяты из checkpoint; повторная загрузка базовой vision-модели не нужна.
  Для NitroGen используется официальный Siglip2 config/processor787800c8.
- Private files и их хеши перечислены в JSON. Пароль/токены не включены в документацию и команды.

## Измеренные задержки

Исправленные конечные сеансы, default denoising16 у NitroGen, P2P без текста, batch1:

| Метрика | NitroGen | Open Pixel2Play150M |
| --- | ---: | ---: |
| Мониторинг транспорта | 20,008с | 45,001с |
| Ответов модели, включая setup | 86 | 233 |
| RGB→модель→ответ процесса, p50 | 215,817мс | 111,813мс |
| Декодированный receiver frame→ответ, p50 | 245,695мс | 145,566мс |
| RGB conversion, p50 | 2,31мс | 2,46мс |
| Последний direct echo RTT | 0,824мс | 0,839мс |
| RTP packetsLost | 0 | 0 |
| Server→worker video с запуска | 0байт | 0байт |

Это receiver timing, не Android capture→action→photon. Декодирование и сетевой участок до
receiver timestamp сюда не разложены по общему source frame ID. Процессный round trip содержит
preprocessing, GPU и сериализацию; его нельзя называть чистым временем GPU kernel.
Холодные первые статические проходы заняли7,45с у NitroGen и5,05с у P2P. Перед live admission
выполнен warmup. Оба GPU процесса завершены после конечных тестов, постоянно модель не работает.

Нельзя выводить50×5Hz из одиночного теста. NitroGen при текущих настройках около4 решений/с;
P2P быстрее и выдержал заданный sampling5Hz. Batch, sustained load, отдельная LAN GPU-станция,
полная очередь decode и CPU/VRAM headroom ещё не измерены.

## Найден и исправлен дефект high-quality H264 receiver

До исправления NitroGen получил73 ответа, затем `video_frame_deadline`. Два P2P-подключения
имели ICE/data echo и входящие RTP packets, но0 decoded frames. Отрицательные результаты сохранены.
В APK encoder продолжал выдавать кадры. Следовательно, успешный ICE не доказывал рабочий декодер.

aiortc1.15 по умолчанию выделяет128 RTP packet slots. Крупный IDR может не поместиться целиком.
Тест с300×1200B воспроизводит потерю access unit в stock buffer. Новый guarded adapter использует
2048 slots с prefetch0, до начала приёма и только для проверенной версии aiortc. Неподдержанная
версия/уже используемый receiver отклоняются. Адаптер не меняет SDP и не увеличивает prefetch.

После исправления на реальном PH011 зарегистрированы кадры по130 packets:20 превышений прежнего
предела у P2P и9 у NitroGen; emitted1231/514 кадров, PLI0, оба сеанса завершились успешно.
Это связывает наблюдаемый дефект с конкретным лимитом, а не с предполагаемой скоростью GPU.
2048 slots ограничены, но внутренние decoder queues и худшие burst profiles ещё требуют нагрузки.

В decoded NitroGen validator также исправлен предел action chunk: checkpoint выдаёт18 действий
на60Hz, а16 — число diffusion steps. Цифровые decoded button columns остаются0/1, включая
триггеры: так делает закреплённый upstream tokenizer. Не введены guessed axes или silent clipping.

Проверки:71 motor tests, включая реальный локальный H264/DTLS/SCTP fake APK; Ruff;18 targeted
keyboard tests и полный локальный frontend profile. Отрицательный pytest запуск без backend JWT
не является результатом этих unittest проверок.

## P2P Windows/AMD port: точные отличия

Upstream закрепляет Python3.13.2/CUDA и training pipeline. Его целиком не устанавливали.
В private source copy training-only Rust queue imports сделаны lazy; IPC shared authkey не меняется.
Gemma/SentenceTransformer не загружены: используется штатный zero text embedding с no-text imputation.
Текстовые инструкции в этом пилоте не проверены и не поддержаны.

Модель создана наGPU до инициализации служебных tensors. Используется eager mode и стандартный
SDPA с точной boolean mask исходного P2P, включая decode offset/history/sinks. Проверка на CPU FP32
совпала со scalar reference, max abs error<2e-6; проверено заполнение и rollover окна200 кадров
в live run. Bitwise/numerical parity с upstream CUDA/Triton целиком не утверждается.
P2P использует192×192 RGB; актуальный PIL bilinear pilot preprocessing ещё нужно сверить с
upstream canonical resize для входов другого размера. Результат не объявлен принятым model adapter.

## Игра, снимок и XPath

В Black Russia на PH011 успешно выполнен вход через прямую клавиатуру Sphere. Native PNG960×540
и XPath получены через API. Дерево содержит13 nodes, в том числе
`com.br.top:id/jniactivity_gl_surface_view`; дорога, мини-карта и игровые controls не представлены
как accessibility elements. Для них нужны pixels/detection/calibrated zones, не фиктивные XPath.

Native PNG занял6,288с, hierarchy3,774с. Это root diagnostic RPC с cleanup/SHA, не потоковый
observation API; использовать его на каждом motor tick нельзя. Live inference использовал RGB
из прямого H264. Позднее игра отключила персонажа за бездействие во время установки зависимостей.
Исправленные live benchmarks уже видели disconnect renderer. Поэтому они подтверждают transport/GPU,
но не управление живым персонажем. Отдельный3-point drag получил3/3 applied ACK и CLOSED, однако
также был в disconnected state и не доказывает работу виртуального стика.

Правило владельца: после game disconnect полностью закрыть и заново открыть игру; между
попытками подключения к game server выдерживать минимум20с. Это отдельный lifecycle от WebRTC:
не ломать здоровый APK direct peer из-за disconnect игрового сервера. Нельзя выдавать keepalive
или случайные касания за доказательство активного входа.

## Источники и вывод для следующего этапа

[AMD installation](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/windows/install-pytorch.html)
подтверждает официальный Windows ROCm/Python3.12 путь. [P2P repo](https://github.com/elefant-ai/open-p2p)
содержит real-time integration и tested NVIDIA hardware; это не AMD benchmark.
[P2P weights](https://huggingface.co/elefantai/open-p2p) имеют MIT metadata; права остальных компонентов
и сценария проверяются отдельно. [NitroGen source](https://github.com/MineDojo/NitroGen) остаётся
research baseline с ограничениями планирования и лицензии; успешная загрузка не снимает их.

[NitroGen#24](https://github.com/MineDojo/NitroGen/issues/24) содержит разные self-reported скорости
и сообщения о замедлении upstream runner. Они не заменяют наш unpaused измерительный контур.
[P2P issues](https://github.com/elefant-ai/open-p2p/issues) не дают готового проверенного AMD/Android
integration: отдельные вопросы касаются training initialization и IDM availability.

Следующий обязательный этап: восстановить активный game session, калибровать Android joystick,
сделать per-device held state и release watchdog, затем отдельный короткий supervised model→APK
input test. Нужны явная обработка unmapped outputs, multi-touch для одновременного движения/камеры,
source clock correlation и эпизодные reset/delegation. Цель A→B и production gameplay остаются открыты.
