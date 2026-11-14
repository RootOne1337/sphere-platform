# Первый headless клиент APK: конечная проверка

16 октября 2026 · продолжение [единого AI-плана](../../design/MOTOR-AI-PLATFORM.md).

Реализован отдельный Python модуль `motor_worker`: прямой H.264 receiver без браузера,
выборка RGB и независимая проверка допуска управления. Инструкция —
[MOTOR-WORKER](../../operations/MOTOR-WORKER.md); данные — [JSON-квитанция](HEADLESS-MOTOR-WORKER.json).
Это часть P0-C/G02, не завершение всей AI-интеграции.

## Конечный результат на PH011

| Проверка | Результат |
| --- | --- |
| Основное окно финального прогона | 15,013 с |
| Decoder outputs за весь прогон | 867 |
| Decoder FPS в основном окне | 57,151 |
| RGB observations в основном окне | 75, измеренная частота 4,996 Гц |
| Shared native admission | READY подтверждён для точного участника/capture |
| Idle ALIVE | 49 receipts; последний actor RTT около 3,065 мс |
| Завершение | Свой participant подтвердил CLOSED; peer закрыт |
| Tap/swipe/key/text | 0 команд; native gameplay execution не проверялся |
| Путь | Выбранная host/prflx UDP pair, private address scopes |
| Начальные серверные encoded bytes | 411 770 B, подсчитаны и отброшены |
| Серверные media bytes после handover ACK | 0 |
| Server frames, декодированные worker | 0 |

Путь выбранного peer подтверждён guarded adapter для aiortc1.15. Это не доказательство физической
LAN или обхода VPN. Receiver age/PTS не равны source capture age/frame ID. Последний ACK показывает
APK actor liveness; физическое действие не исполнялось. Launcher на decoded PNG визуально проверен,
но соответствие native пикселей на всех устройствах этим не принято.

Отдельный более ранний прогон двух клиентов на PH011: окна 12 и 25 с, оба получили READY,
39/80 ALIVE, CLOSED своего участника. Более длинный поток продолжился после завершения короткого.
В этом прогоне ещё использовалась старая периодизация выборки; его FPS не выдаётся за финальную
реализацию cadence. Масштабирование на 10/50 устройств не выполнялось.

## Найденные проблемы и исправления клиента

1. REST start без viewer lifecycle недостаточен: direct offer опередил готовность capture,
   затем отсутствие presence позволило серверу остановить capture. Новый клиент сам регистрирует
   текущий viewer lifecycle, дожидается v2 packet, затем включает direct-copy suppression.
2. aiortc MAX_BUNDLE при создании SCTP до video оставлял transport без candidates в программном
   тесте. Video transceiver теперь создаётся первым; настоящий local media test проходит.
3. aiortc дополнительно объявляет SHA-384/512; текущий допуск Sphere принимает SHA-256.
   Сохранён настоящий SHA-256 fingerprint. Stock H.264 level3.1 заменён для constrained baseline
   на уровень4.2 pinned software receiver; иначе APK отказывал `receiver_level_insufficient`.
4. На PH011 зафиксирован SIGABRT в `libjingle_peerconnection_so.so` после remote SDP и до input OPEN:
   `front() called on an empty vector`. Пилот остановлен, агент восстановлен через SetupActivity,
   оставшийся диалог закрыт одним внешним ADB Back. После удаления объявления несуществующего
   sender SSRC/MSID из recvonly offer последующие конечные прогоны прошли на том же APK.
   C++ причина не символицирована; общая защита APK от иных SDP остаётся открытым P0.
5. Потеря control ALIVE сначала маскировалась вторичной ошибкой закрытия signaling. Теперь первичная
   причина сохраняется до выхода из WS context; отмена закрывает participant при ещё живом peer.
6. На Windows уточнены high-resolution timing и периодизация наблюдений без догоняющей очереди.
   Основное окно измеряется отдельно от setup; финальная выборка — 75/15,013 ≈4,996 Гц.

Отрицательные прогоны сохранены в квитанции; их не заменяет поздний положительный результат.
Экспериментальные предложения отправлялись только PH011. Другие эмуляторы и текущая UI/API/APK
поставка не обновлялись этим этапом; модуль работает с установленным APK76.

## Проверки и оставшийся объём

Локально: 18 protocol tests и 8 настоящих программных H.264/DTLS/SCTP integration tests прошли
в отдельном окружении. Они проверяют цвета, отсутствие команд ввода в video-only режиме,
capture identity, lost ALIVE, unconfirmed CLOSE, video stall, cancellation и lifecycle handover.
Ruff check/format и `pip check` прошли. Дополнительно прошли 41 documentation и 9 budget tests.
Это не GitHub-hosted GPU tests и не gameplay benchmark.

P0 остаётся: capture-only admission без начальной серверной копии; native SDP hardening;
source frame ID/clock/capture quality, включая PH025; profile executor с simultaneous controls;
atomic DAG→episode delegation. Затем model adapter и сравнение игровых baseline.

Application latest-frame slot и диагностический хвост ограничены; внутренние decoder/thread buffers
aiortc не проходили нагрузочную приёмку. Перед парком требуется оценить и ограничить их backlog,
память и decode load. Наличие двух прямых idle peers не доказывает production stability,
независимость от backend, реальное управление игрой или ёмкость 50×5 Гц.
