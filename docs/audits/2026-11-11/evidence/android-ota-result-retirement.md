# OTA — контролируемый вызов обработчика позднего результата

В `.venv-audit` вызван `backend.api.ws.android.router.handle_command_result`. На входе один синтетический терминальный OTA-результат с `installed_version_code=25` и отметкой `ota_recovery_receipt`. Подменены `AsyncSessionLocal`, `is_persisted_ota_recovery_replay` (пустая история), `get_device_ota_grant` (совпадающий ID, другой ID или `None`), `persist_ota_recovery_result` (успех при вызове) и `manager.send_to_device`. Счётчики получены у `AsyncMock`. Эти случаи проверяют логику выбора ветки реального обработчика. Вызовов к PostgreSQL, Redis или установленному APK в этой проверке не было.

| Текущий grant | Вызовы сохранения | Вызовы отправки `result_ack` |
| --- | ---: | ---: |
| Совпадающий | 1 | 1 |
| Заменённый | 0 | 0 |
| Отозванный | 0 | 0 |

При совпадении обработчик записал `android_ws.ota_recovery_receipt_acked`, при замене или отзыве — `android_ws.ota_recovery_receipt_unrecognized`. [Ветка обработчика](../../../../backend/api/ws/android/router.py#L278-L334).
