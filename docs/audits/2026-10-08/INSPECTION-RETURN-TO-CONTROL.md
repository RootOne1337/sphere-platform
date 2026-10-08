# Выход из XPath во время чтения дерева Android

8 октября 2026, около07:15 Asia/Yekaterinburg. Браузер3015, установленный
UI `29eecb8`, API `2225f73`, PH011 APK10249. На успешном дереве launcher
нажаты «Обновить дерево» и немедленно «Управление». Веб запустил новую
continuous negotiation, пока Android ещё выполнял root read. После перехода
управление стало недоступно; диагностика: `closed`,
`native_input_rejected_or_unknown`. Касание во время этого теста не отправлялось.
Это отдельная воспроизводимая гонка обратного перехода, а не объяснение всех
исторических ошибок UI Automator или потери кадров.

## Исправление

Смена режима сбрасывает tree generation и selection, но не отменяет текущий
HTTP запрос. Отмена HTTP не подтверждает отмену root SHELL на Android.
Пока запрос завершается, выбранное обычное управление остаётся read-only:
живые жесты, дискретные нажатия и навигация не отправляются, новый owner
не открывается. Веб показывает причину ожидания. После ответа/ошибки именно
этого запроса gate снимается; штатная capability/native STARTUP проверка
остаётся обязательной. Команды и жесты не повторяются.

Повторный вход в XPath во время ожидания не создаёт второй запрос. После
завершения старого чтения новый snapshot запрашивается для текущего режима;
устаревший ответ не публикуется. Device/token/permission/socket invalidation
сохраняет abort. Завершение старого aborted запроса не снимает gate другого
запроса: finally проверяет identity AbortController, а не только tree generation.

Frontend timeout50s, backend/native deadlines, ownership guards и явное
восстановление неизвестного ввода не увеличены. Сбой транспорта не доказывает
завершение root команды: subsequent native negotiation по-прежнему может
отклонить ввод и оставить явный recovery. Это не механизм таймерного обхода
APK ownership и не безусловная гарантия освобождения Android.

## Проверки

Четыре новых regression сначала получили4failed/15passed. После исправления
138 tests в single-device-inspection/pointer-control/continuous-pointer passed,
nonincremental TypeScript0errors. Проверены successful/failed drain без abort,
повторный вход без overlap и старый response другого устройства.
Exact-source hosted build/install и тот же быстрый браузерный переход ещё
требуются. SF26-05 остаётся OPEN; fleet rollout и latency SLO не подтверждены.

Связь: [переход к инспектору](INSPECTION-CONTROL-HANDOFF.md),
[ограниченное idle согласование](IDLE-RECEIPT-RECONCILIATION.md).
