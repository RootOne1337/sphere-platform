# VPN: подтверждённые CI-кандидаты пакетного импорта и телеметрии

22 октября 2026 · [машиночитаемая квитанция](VPN-BATCH-CI-VALIDATION.json).
Это проверка исходников и образов. Установка, браузер и физический Android VPN
принимаются отдельными наблюдениями; текущая установленная версия указана в
[status registry](../../operations/STATUS-REGISTRY.json).

| Компонент | Ревизия | Результат |
| --- | --- | --- |
| Backend | `4a6ada927e6297004b9f1b87faaf996fb282ff56` | [CI 39668292976](https://github.com/RootOne1337/sphere-platform/actions/runs/39668292976): 4422 passed, 107 skipped, 668 subtests; coverage 82,58% |
| Frontend | `46dd02fff711c1667b44520b85290226b7155287` | [CI 39670720957](https://github.com/RootOne1337/sphere-platform/actions/runs/39670720957): 2630 passed / 183 suites; types, build, 26 packaged pages / 72 client assets |

Backend workflow целиком завершён успешно: PostgreSQL/Redis, image bootstrap,
проверки нескольких HTTP workers, lint/types, security, RLS и Alembic head.
В JUnit отдельно проверены 25 batch/profile production cases: ошибок и пропусков
среди них нет. Пропуски остальных тестов не являются их успешной приёмкой.

Пакет до 100 `.conf` проверяется целиком до записи и повторно при сохранении.
Запись профилей и аудита атомарна; при позднем конфликте новые строки откатываются.
Порядок захвата уникальных request ID стабилен для пересекающихся пакетов.
Status возвращает метаданные по прежним ID; ненаблюдаемый запрос не объявляется
отменённым. Клиент не повторяет неизвестное сохранение и очищает raw config refs.
Известные ошибки переводятся в конкретные сообщения без вывода raw API/config text.

Скорость туннеля вычисляется по двум свежим native snapshots одной сессии,
revision, процесса и управляющего WebSocket. Смена identity, пауза, сброс
счётчиков, устаревание, новый account/filter/page или API error сбрасывают оценку.
Это средняя скорость всего туннеля по Android wall clock; малые коррекции часов
не выявляются текущим контрактом. Статистика отдельных приложений и история
расхода сюда не входят.

Образы связаны с независимыми image ID из GitHub job logs, SHA-256 скачанных
архивов и CI receipt. Проверка Docker-save поддерживает config ID и OCI
manifest/index с проверкой цепочки digest, sizes, config и layers. Проверки
безопасности архива и лимиты размера сохранены.

На этом этапе не приняты main-APK kill switch/fault matrix, server journal,
active client leases, массовое физическое назначение, прокси TUN и общая
UI/script/pipeline операция. [План развития с источниками](../../design/VPN-FLEET-CONTROL.md),
[операторский контракт и поставка](../../operations/VPN-PROFILES.md).
