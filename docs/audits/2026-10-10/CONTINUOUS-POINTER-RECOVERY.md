# Неподтверждённый жест: освобождение Android и новая видеосессия

Дата: 10 октября 2026, UTC+5. Статус: **source correction**; для этой
коррекции доставка и фактическая проверка браузера фиксируются отдельным receipt.
[Предыдущая коррекция idle recovery](CONTINUOUS-AUTO-RECOVERY.md) ·
[Текущий статус](../../operations/CURRENT-STATE.md).

## Что показала реальная проверка предыдущего UI

На PH011, исходный APK1.2.49-dev, публичный домен, UIa513f7df/API369654a0:

| Наблюдение UTC 9 октября | Полученный результат |
| --- | --- |
| 23:48:50.618 | Только HEARTBEAT просрочен: возраст512мс, lastACK490мс, pointer/terminal отсутствуют, WS OPEN/буфер0; автоматическая попытка1, состояние probing |
| 23:48:59.478 | Новый native owner ready; receipt№30/490мс; ручной кнопки нет. Отдельное чтение Home застало новую паузу, поэтому готовность кнопки в этом срезе не принята |
| После трёх натуральных автоматических idle recovery | Безопасный жест мышью по пустой области launcher передал DOWN/MOVE/UP; новые видеокадры появились |
| 23:49:40.014 | Последний сбой MOVE: возраст512мс, tickgap16мс, lastACK501мс; offered31/ack25/pending6, terminal№30/432мс, WS OPEN/буфер0. Owner closed, ручная кнопка1, Home disabled |

Публичный жест **не принят как устойчивое управление**. Попытка нажать Home
была остановлена disabled UI, команда Android не отправлена. Видео в этом срезе:
44пакета/428657байт,34decoded/drawn, invalid/decode/render errors0. После перехода
в просмотр диагностировано66пакетов/44decoded/drawn без ошибок; наша вкладка закрыта.

Натуральные idle retry работают в конечном окне, но не решают потерю pointer ACK.
Пересечение500-мс deadline видно; виновный участок сети или Android не определён.
Эти наблюдения относятся к **a513**, до следующей коррекции, и не подтверждают её.

## Новый контракт восстановления

1. Controller различает idle-only timeout и unknown pointer receipt timeout.
   Классификация сохраняется до очистки held/terminal/pending. Она не делает
   неизвестный результат успешным и не превращает opening/injector errors в retry.
2. При DOWN/MOVE/UP/CANCEL timeout исходный жест больше не отправляется.
   Notice остаётся: «Предыдущий жест не подтверждён полностью. Он не повторяется;
   после восстановления оцените экран перед новым действием».
3. До **точного native RELEASE3**, stage release, sequence0, injector, с теми же
   session/owner/capture, новый ввод и automatic viewer restart заблокированы.
4. При полученном RELEASE3 после backoff закрывается только прежний viewer WS.
   Его replacement требует собственного нарисованного кадра, capability, новой
   owner identity и native STARTUP0. Старый UP и старые receipts не оживляют жест.
5. После новой готовности можно сделать **новое явное** действие. Notice прежнего
   неопределённого результата сохраняется до скрытия пользователем или смены устройства.
6. Missing/foreign/unknown RELEASE не заменяется timeout или свежим WS.
   Через3секунды ожидания сохраняется explicit recovery fence; нужна проверка экрана.
   Injector failures, неизвестный HTTP key/text и server denial также не повторяются.
7. Read-only, recorder, inspector, task handoff и blur приостанавливают automatic
   recovery. Возврат к Control сохраняет требование нового viewer; запись не обходит
   его и не продолжается автоматически. Нет replay сценария или его шага.

Используется прежний backoff750/1500/3000/6000/12000/15000мс с пределом15секунд.
Открытие WS/кадр не сбрасывают backoff; нужны30секунд успешных native receipts.
500-мс deadline не увеличен. Это восстановление доступности **следующего** ввода,
а не исправление задержки доставки или обещание безобрывного текущего жеста.

## Проверка исходника

Красные component fixtures до коррекции получили manual-only fence после held
и terminal timeout. После коррекции **179 целевых тестов, 3 suites прошли**:

- DOWN/MOVE/UP/CANCEL classification сохраняет неизвестный результат после RELEASE;
  idle и admission/injector error не смешиваются с pointer loss;
- новый touch запрещён до RELEASE, собственного кадра и STARTUP0; старый UP
  игнорируется, legacy click/swipe и HTTP command не подставляются;
- missing/foreign/unknown RELEASE не создают новый WS и не принимают следующий DOWN;
- пять mode/focus locks останавливают recovery, recorder readyfalse, после возврата
  нужен fresh viewer; unmount оставляет ноль таймеров;
- предыдущие idle backoff, busy admission, ownership, capture и reconnect gates сохранены.

TypeScript и scoped ESLint прошли. Полный локальный frontend run:
**1994 tests /142 suites passed**. Exact-source CI и доставка будут связаны
с установкой отдельно. Это не fleet/soak, native input-to-picture SLA
или приёмка стабильной APK1.3.0.

## Следующий измеримый gate

Допустить exact-source production artifact, заменить только UI, проверить оба
адреса. На реальном PH011 проверить новый frame/owner/native receipt, безопасный
жест, доступность следующего действия после натурального pointer timeout/RELEASE.
Не подделывать receipt для живого Android. Если timeout не возникнет, отметить
fixture-only coverage этого случая. Явно сохранить отрицательные результаты.

Прямой browser↔APK transport остаётся отдельным gate: selected ICE pair, реальный
echo RTT, direct/relay profiles, затем media/input и resource soak. Диагностический
host-only canary ранее не открыл канал; эта UI коррекция не меняет этот результат.
Product9/41 и legacy7 здесь не закрываются.

## Реальная проверка UI344 и дополнительная коррекция согласования

UI34497f9b установлен отдельно от API369654a0 в00:04UTC10октября.
На публичном PH011 в00:05:31 controller READY, натуральных automatic idle
attempts2,12decoded/drawn без ошибок. В00:06:16 после четырёх попыток READY,
«Недавние» получили Android completion1247мс,80decoded/drawn без ошибок.
После «Домой» (completion666мс) и второго жеста в00:06:56 состояние осталось
IDLE; в00:07:50 оно всё ещё IDLE, хотя101кадр нарисован, ошибки0, ручной кнопки0.
Это отрицательный результат управления, а не успешная приёмка по одному видео.
Unknown pointer notice в этом окне не появлялся; натуральный pointer-loss recovery
этой версии не принят. Private UI records:344-public-*.json, без подделки receipts.

Исходник выявил две гонки. Подтверждённая навигационная команда во время capability
probe отменяла ожидание до появления controller, но не снимала метку «probe уже
выполнен» с WS. Повторная проверка теперь запускается после известного результата
команды и требует новых capability/session/STARTUP. Неизвестный HTTP result
сохраняет fence. Красный fixture до коррекции получил2probes вместо требуемых3.

Несовпадение capture epoch/геометрии capability и уже нарисованного кадра также
переводило UI в IDLE и отменяло ограниченный deadline. Теперь остаётся PROBING:
touch authority не выдана, ожидание ограничено прежними6секундами, после timeout
подтверждённый continuous path восстанавливает собственный viewer по backoff.
Случай не подменяется legacy swipe или искусственным успешным receipt.

Оба новых fixture прошли: ввод заблокирован до свежего STARTUP, старое согласование
не принимается во время HTTP команды, unmount убирает все таймеры. Promise microtasks
в fake-clock тесте явно завершены перед подсчётом таймеров. Полный frontend:
**1996tests/142suites passed**, TypeScript и scoped ESLint прошли. Это follow-up
source correction поверх344; его exact-source CI/установка/браузер проверяются
отдельно. Причина480–510мс native ACK и direct transport остаются OPEN.
