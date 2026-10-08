# Служебный ACK без касания: ограниченное согласование владельца

8 октября 2026, около06:48 Asia/Yekaterinburg. Установленные UI/API `2225f73`,
PH011 APK10249. После минут простоя обычное управление стало недоступно.
Диагностика показала `closed · причина: native_receipt_timeout`; прежний Home
остался подтверждён799ms. Нажатие «Назад» не отправилось: кнопка уже была
недоступна. В этой части прогона Android касания не выполнялись, шли только
служебные heartbeat. Видеодекодер показал0decode/render errors. Это точный
наблюдаемый guard failure, а не измерение input→picture latency или доказанный
сетевой/CPU root cause. Причина первого исторического Home fencing неизвестна.

## Решение

500ms deadline сохраняется. Controller перед очисткой pending scalar records
отмечает единственный узкий случай: native receipt timeout, нет удерживаемого
pointer, нет неполученного terminal receipt, все pending entries — heartbeat4.
После timeout owner закрывается. Только scoped native RELEASE3 этого controller
позволяет заново запросить capability и получить новый STARTUP0.
До этого ввод блокирует состояние controller; Redis expiry и успешный send
не открывают его. Никакое касание, MOVE/UP, клавиша или текст не повторяются.

Автоматическое согласование ограничено одним случаем на текущую video effect
session. Второй timeout требует явного восстановления. При missing/unknown
release автоматический новый owner не создаётся; recovery доступен вручную.
DOWN/MOVE/terminal UNKNOWN, scheduler gap, malformed receipt, transport failure
и server rejection сохраняют прежнее явное восстановление. В диагностике
выведен scalar count0/1; растущий trace и новые фоновые устройства не добавлены.

## Проверки

134 tests в трёх stream suites, TypeScript0errors. Consumer regression проверяет
сначала отсутствие второго probe до RELEASE3, затем новый scoped owner STARTUP,
отсутствие click/swipe и каких-либо touch actions кроме heartbeat, и запрет
третьего probe при повторном timeout. Controller tests отличают idle-only loss
от неотвеченного DOWN и неизвестного terminal outcome. Ни deadline, ни APK
watchdog/ownership bounds не ослаблены. Exact-source CI/install и конечная
браузерная проверка требуются отдельно; finite tests не являются fleet soak.

Связанные материалы: [передача инспектору](INSPECTION-CONTROL-HANDOFF.md),
[наблюдение Home](CONTINUOUS-INPUT-HANDOFF-OBSERVATION.md),
[контракт receipts](../../protocols/CONTINUOUS-INPUT-RECEIPTS.md).

## Установка и граница live evidence

Reviewed UI `29eecb8` установлен02:01:01UTC8October. Exact-source frontend CI
37715096698:1844passed/137suites, types/build,26packaged pages/73assets,
archive/image admission.45 других контейнеров, API `2225f73` и OTA сохранены.
Реальный drag/wheel и receiver→Home765ms→native READY прошли без явного recovery.
Это installed finite acceptance штатного пути; искусственный real-transport
idle timeout не вызывался. Автоматическая one-attempt branch подтверждена
regressions, а не выдана за испытанную при реальной сетевой потере.
