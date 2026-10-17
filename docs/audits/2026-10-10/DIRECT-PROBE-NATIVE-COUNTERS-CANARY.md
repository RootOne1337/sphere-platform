# Browser и Android ICE: конечная проверка native counters

Дата: 10 октября 2026, UTC+5. Source `8447c907`, один PH011, один host-only
эксперимент. [Машинное доказательство](DIRECT-PROBE-NATIVE-COUNTERS-CANARY.json) ·
[Действующие работы](../../operations/WORK-STATUS.md) ·
[Предыдущий browser-only срез](DIRECT-PROBE-NETWORK-CANARY.md).

## Результат

Новая ограниченная Android диагностика **реально выполнила JNI callback**:
12 отчётов, возраст каждого 0–1 мс. Во всех отчётах отсутствуют удалённые
ICE-кандидаты и пары; DTLS остаётся `new`. Браузер установил Android answer,
проверял две пары и показал 177 requestsSent / 0 responsesReceived. За 12 секунд
DataChannel не открылся; echo и RTT не измерены.

| Измерение | Browser, последний срез | Android, 12 отчётов |
| --- | --- | --- |
| Local / remote candidates | 4 / 2 | 4 / 0 |
| Pairs | 2 | 0 |
| Checking / failed / succeeded | 2 / 0 / 0 | 0 / 0 / 0 |
| DTLS | connecting | new |
| requestsSent / responsesReceived | 177 / 0 | unknown / unknown |
| requestsReceived / responsesSent | Здесь не измерены | unknown / unknown |
| Возраст среза | 279 мс при остановке | 0–1 мс при обработке actor |

При отсутствии pair rows native reducer возвращает `null` для всех четырёх
packet counters. **Это не доказательство нулевого числа полученных UDP-пакетов.**
Количество remote candidates и pairs относится к фактическому native stats
report; оно не выводится из SDP или количества кандидатов в answer.

Отказ сужен до обработки/разрешения кандидатов и установки сетевого пути.
Offer содержит один host mDNS candidate, answer — два host candidates без mDNS.
Конкретная причина mDNS/firewall/NAT/VPN ещё не установлена: packet capture
и контролируемого сравнения ICE profiles в этом окне не было.

## Допуск сборки

Предыдущий `0abe15ce` был отклонён Android Lint до установки: API31-only
`BigInteger.longValueExact` при minimum26. В `8447c907` используется точный
range check без повышения minimum SDK или подавления Lint.
[Отказ и исправление](DIRECT-PROBE-ANDROID-COMPATIBILITY.md).

Все четыре exact-source workflow `8447c907` — success:
[Android](https://github.com/RootOne1337/sphere-platform/actions/runs/38000574521),
[Backend](https://github.com/RootOne1337/sphere-platform/actions/runs/38000574533),
[Frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/38000574514),
[Preview](https://github.com/RootOne1337/sphere-platform/actions/runs/38000574536).
Обычные APK исключают экспериментальный JNI; отдельный canary проверен CI.
Release signing smoke и запрет canary release прошли.

Локальный signed candidate собран из `git archive 8447c907`: оба canary profiles
по 990 tests / 85 suites, 0 failures/errors, 3 skipped; оба Android Lint —
0 errors / 37 warnings. Подпись совпала с исходной pilot APK; package, version
и versionCode не менялись. Все четыре JNI ABI проверены.

Gradle завершился успешно за 6m 1s. Чтение одного XML через обычный Windows path
длиной 262 символа дало FileNotFoundError; расширенный путь позволил прочитать
тот же XML и все 85 отчётов. Сборка не повторялась. Это подтверждённая граница
сборщика отчёта, **не новое доказательство повреждения файловой системы**.

## Границы эксперимента

- Только PH011 / `414ce0e9-4b93-4f96-b9ca-ee675f53835e`, Android 9 / API 28.
- Только diagnostic DataChannel, SDP `m=application`; нового media/input пути нет.
- Host ICE без STUN/TURN. 35-секундный read-only signaling observer увидел
  один offer, один answer и close. Publication gap 566 мс — не direct RTT.
- Legacy viewer переведён в «Просмотр». Касания, клавиши, текст и сценарии
  не отправлялись. Открытие viewer может согласовать обычную control-сессию;
  это не утверждение об отсутствии любых protocol messages.
- Native getStats: один pending callback, 1 Hz, максимум 32 запроса, до 256 rows.
  В этом окне записано 12 фиксированных local logcat aggregates. Сырые stats,
  адреса, SDP, сертификаты и credentials не опубликованы.
- Три RSS среза одного canary PID: 121040 → 132432 → 137900 KiB;
  threads 42 → 44 → 41. Они включают JNI initialization и legacy capture.
  Это не подтверждение CPU/RSS plateau или отсутствия утечки.

Read-only routing показал default route Android в interface policy table;
одного main table было бы недостаточно. Windows выбирал VPN default route
`0.0.0.0/0` для внутреннего адреса guest. Это факт выбранного маршрута, а не
доказательство конкретной потери пакетов. VPN, firewall и routes не менялись.
Сырые адреса остаются в private evidence.

## Возврат рабочего стенда

Исходный APK восстановлен 9 октября 23:00:42 UTC; SHA-256 совпал с сохранённым
оригиналом. App data не очищались, OTA и остальные устройства не обновлялись.
UI/API остаются `369654a0`; после отключения probe API container `aaf5b22a`.
Allowlist пуст, временные 3016/3017 остановлены, agent-created tabs закрыты.
Schema, OTA hash и 45 соседних контейнеров сохранены при обеих установках API.

После возврата обычный публичный viewer декодировал и нарисовал **662 кадра**,
invalid/decode/render errors — 0. Экспериментальная панель в стандартном UI
выключена. На обоих адресах health200, PH011 online и безопасный negative
broadcast404 без Android execution; отключённый probe вернул4003 до JWT.
Это конечная проверка возврата видео, не steady FPS или control latency SLA.

Удаление двух owned temporary build directories отклонила автоматическая
проверка с причиной `blocked by policy`. Команда не выполнялась; каталоги
сохранены. APK, backup, XML, Lint и build logs сохранены отдельно.

## Следующий проверяемый шаг

Сравнить явные ICE profiles на одном peer contract: host-only baseline уже
измерен; далее контролируемый STUN с известным endpoint и проверкой числовых
кандидатов, затем TURN при необходимости. Сравнить native remote/pair counts,
selected pair и реальный echo RTT. Секреты и адреса не публиковать; short relay
не называть прямым соединением. Не подменять этот gate увеличением input timeout.

Native callback принят только в конечном диагностическом scope. Direct channel,
public idle reliability, media/control ownership, network matrix, resource soak
и stable APK1.3.0 остаются открытыми. Product **9 accepted / 41 open**, legacy
**7 unclosed**; новых продуктовых пунктов не закрыто.
