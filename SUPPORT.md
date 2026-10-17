# 🧭 Помощь и диагностика

[Главная](README.md) · [Документация](docs/README.md) · [Runbooks](docs/runbooks/README.md)

## Выберите обращение

| Ситуация | Куда писать |
| --- | --- |
| Что-то работает неправильно | [Сообщить о баге](https://github.com/RootOne1337/sphere-platform/issues/new?template=bug_report.yml) |
| Краш, задержка, потеря связи или деградация под нагрузкой | [Сбой и производительность](https://github.com/RootOne1337/sphere-platform/issues/new?template=performance.yml) |
| Непонятная инструкция или устаревший пример | [Исправление документации](https://github.com/RootOne1337/sphere-platform/issues/new?template=documentation.yml) |
| Новый пользовательский сценарий | [Предложить функцию](https://github.com/RootOne1337/sphere-platform/issues/new?template=feature_request.yml) |
| Нужна помощь с настройкой | [Задать вопрос](https://github.com/RootOne1337/sphere-platform/issues/new?template=question.yml) |
| Уязвимость, утечка ключа или чужих данных | [Приватное сообщение](SECURITY.md) |

Формы GitHub появляются в меню после попадания в default branch. Пока изменения
находятся в draft PR, можно открыть обычный issue по структуре ниже.
Сначала проверьте [известные проблемы](docs/audits/2026-09-20/FLEET32-PREFLIGHT.md).

## Что позволит найти сбой

1. **Когда:** время начала и окончания с часовым поясом, например
   `2026-09-21 16:05:00 +05:00`. Отдельно — момент первого симптома и восстановления.
2. **Где:** backend/frontend revision, APK versionName/versionCode, Android version,
   root/no-root, модель или эмулятор, Compose project. Не прикладывайте секретные env.
3. **Какой сценарий:** сколько устройств, viewers и заданий; действовал ли VPN;
   что менялось в сети/сервере. Укажите task/pipeline/command ID и обезличенный device ID.
4. **Что ожидалось и получилось:** шаги, ошибка, длительность, повторяемость.
   Отдельно — что уже пробовали и какое действие восстановило работу.
5. **Короткое evidence:** очищенный фрагмент нужного временного окна, скриншот,
   terminal receipt, PID до/после или метрики. Миллионы строк без контекста не нужны.

Статус online, открытый WebSocket и картинка на экране проверяются отдельно:
последний кадр может оставаться видимым после потери доставки. Для видео фиксируйте
новые кадры, задержку и момент прекращения обновлений. Для задания — сохранённый
terminal result, а не только успешный HTTP submit.

## Что не публиковать

Репозиторий публичный. Не загружайте `.env`, `.admin-credentials`, access/refresh
tokens, enrollment keys, cookies, signing keys, полные DB dumps и необработанные
логи устройств. Удаляйте секреты также из URL, заголовков, скриншотов и вложений.
Приватные материалы храните отдельно; в issue достаточно обезличенного доказательства.

При подозрении на раскрытие секрета сначала отзовите его в своей установке;
удаление строки из issue не отменяет уже состоявшееся раскрытие.
[Security policy](SECURITY.md) описывает канал сообщения.

## Быстрые маршруты

- Веб/авторизация/первый APK: [Local pilot](docs/operations/LOCAL-PILOT.md).
- APK в другой сети: [Remote pilot](docs/operations/REMOTE-PILOT.md).
- Сервер, SQL, VPN, fleet offline: [Runbooks](docs/runbooks/README.md).
- Повторный запуск и readiness: [Startup](docs/operations/STARTUP.md).
- Длительный тест: [Soak](docs/operations/ANDROID-OVERNIGHT-SOAK.md).

Поддержка ведётся в репозитории по возможности владельца. Гарантированных SLA,
круглосуточного дежурства и отдельного support email сейчас нет.
