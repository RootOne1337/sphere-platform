# Автоматическая публикация адреса Android-сервера

**12 сентября 2026 · host-side publisher для одного явно выбранного Quick Tunnel.**

[Подписанный contract](../architecture/ANDROID-SIGNED-DISCOVERY.md) ·
[Локальный стенд](LOCAL-PILOT.md) · [Открытая задержка GitHub](../audits/2026-09-05/DISCOVERY-CDN-FRESHNESS.md)

## Назначение и границы

[Publisher](../../scripts/discovery_publisher.py) обновляет существующий подписанный
документ, когда выбранный connector получил новый URL, и продлевает его до expiry.
Необходимы Python с `httpx`/`cryptography`, Docker CLI и авторизованный GitHub CLI
на том же host. Приватный signing key остаётся вне public gateway и APK. GitHub
credential используется через текущий `gh` context, не копируется в config/JSON.

В APK адрес управления не меняется: он прочитает новый подписанный version из
своего стабильного bootstrap URL. GitHub CDN и polling могут задержать обнаружение
на минуты; publisher не заменяет заранее доступный второй ingress. Публикуются
только маршруты APK. Backend env/CORS, old legacy APK, web origins и их provisioning
этот процесс не перестраивает; новый web origin требует отдельной приёмки.

Старый `sync-tunnel-url.sh` оперирует именами другой установки и не участвует в
этом процессе. Новый publisher **не выполняет** Docker restart/exec, Redis clear,
изменения `.env`, портов, VPN или signing/installation key rotation.

## Цикл работы

1. По точным Compose labels выбирается один running/healthy connector. Отсутствие,
   неоднозначность, paused/unhealthy или чужая label прекращают цикл.
2. URL читается только из logs после `StartedAt` текущего container ID. Private
   observation cache привязан к project/service/ID/start time и помогает после
   ротации startup logs. Новый connector invalidates этот cache.
3. Через HTTPS проверяются public installation ID и API readiness; credentials не
   передаются, redirects не допускаются. Перед публикацией источник проверяется ещё раз.
4. GitHub Contents API предоставляет signed document и текущий blob SHA. Проверяются
   подпись, installation/key, schema, durable version floor и часы publisher.
5. Изменённый route set или expiry менее чем через **7 дней** создают следующий
   version со сроком **30 дней**. Неизменившийся документ не создаёт remote commit.
6. Перед PUT сохраняется private pending journal с точными подписанными байтами.
   PUT содержит прежний blob SHA; конфликт не перезаписывается вслепую. После
   read-back API обновляется local public mirror и journal становится committed.

Используемый API и условие SHA описаны в
[GitHub Contents API](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents).
Ответ API ещё не означает, что все GitHub Raw CDN edges отдают новый документ.

## Сбои и восстановление

| Сбой | Поведение |
| --- | --- |
| Docker/connector/HTTPS/installation check не прошёл | Signed document и mirror остаются прежними; следующая итерация повторит проверку |
| GitHub недоступен или auth истёк | Не объявлять публикацию успешной; status содержит безопасный reason, API status при наличии |
| PUT не дошёл / его ответ потерян | Сверить remote/journal; повторить те же байты либо признать уже опубликованный version |
| Адрес сменился, пока запрос был pending | Новые проверенные routes получают version выше pending; старый номер не переиспользуется |
| Pending успел просрочиться | Выпустить свежий документ с большей version; не публиковать просроченный |
| Remote commit прошёл, mirror write упал | Следующий запуск восстановит mirror без ещё одного GitHub commit |
| Другой publisher записал тот же version иначе | Остановить публикацию; конфликт требует диагностики, не случайного выбора |
| Remote version ниже committed journal / повреждён journal | Fail closed; не сбрасывать version floor автоматически |
| Запусков несколько | Process lock и thread lock; Windows Task Scheduler также IgnoreNew |

Процесс с другой journal directory не считается тем же локальным writer: при нескольких
publisher hosts нужен единый владелец публикации. SHA CAS сохраняется, но conflicting
same-version signatures требуют ручного согласования. Не удаляйте journal ради retry.

## Конфигурация

Пример с **нерабочими placeholders**, без credentials:

```json
{
  "repository": "OWNER/CONFIG-REPOSITORY",
  "branch": "codex/installation-bootstrap",
  "document_path": "pilots/installation/discovery.json",
  "installation_id": "04b8c5d2-c28e-4d12-a687-b3e211a9b6c7",
  "key_id": "installation-v1",
  "private_key": "C:/Sphere/private/signing-key.pem",
  "state_dir": "C:/Sphere/private/publisher-state",
  "mirror": "C:/Sphere/public/agent.signed.json",
  "compose_project": "sphere-own-pilot",
  "compose_service": "cloudflare-quick",
  "interval_seconds": 60,
  "gh": "C:/Program Files/GitHub CLI/gh.exe",
  "docker": "C:/Program Files/Docker/Docker/resources/bin/docker.exe"
}
```

Existing remote file создаётся отдельно через signer и проверяется перед включением
publisher. Paths должны быть absolute. `state_dir` и private key запрещено помещать
в public directory. `fallback_url` можно задать только для реально доступного адреса
той же установки: он тоже проходит readiness/installation check. Не указывайте
заглушку «для галочки»: это заблокирует публикацию.

```powershell
python -m scripts.discovery_publisher --config C:/Sphere/private/publisher.json --once
```

Без `--once` CLI работает циклически; встроенной установки system service для Linux
нет. Интервал регулирует паузу процесса; Windows scheduler ниже использует 60 s.

## Windows автозапуск

```powershell
./scripts/Install-DiscoveryPublisher.ps1 `
  -ConfigPath C:/Sphere/private/publisher.json `
  -PythonExecutable C:/Sphere/.venv/Scripts/python.exe `
  -TaskName Sphere-Publisher-own-pilot
```

Создаётся задача **текущего пользователя**, с ограниченными правами, без сохранённого
пароля: раз в минуту и при logon, скрытое окно, IgnoreNew, execution limit 3 min.
При совпавшем task name installer проверяет owner и точное действие перед заменой.
Нужны вход пользователя в Windows и работающий Docker Desktop. Работа до logon и
после host reboot в этом пилоте ещё не принята. Это не системная Windows-служба.

Новый стенд использует `Sphere-Publisher-pilot-20260911` и ignored config
`.local-pilot/remote/publisher/config.json`. Signing key хранится отдельно с ACL
в `.local-pilot/remote/discovery-private/`; исходные GitHub environment files не меняются.

## Диагностика и остановка

Смотрите `state_dir/status.json`: status/reason, проверенное время, последний успех,
version, URL, expiry, duration и точный publication scope. Проверяйте возраст status:
старый `ok` не доказывает, что scheduler продолжает работать. Private `journal.json`
содержит signed envelope/phase/base SHA; signing key/credentials туда не входят.

```powershell
Get-ScheduledTaskInfo -TaskName Sphere-Publisher-pilot-20260911
Get-Content .local-pilot/remote/publisher/state/status.json
Disable-ScheduledTask -TaskName Sphere-Publisher-pilot-20260911
```

Disable прекращает будущие запуски; уже выполняющийся one-shot закончит цикл.
Для ремонта signing/source parameters сначала выключите writer и согласуйте
новые параметры с APK. Не удаляйте bootstrap branch после merge config PR.

## Проверки

[Publisher regressions](../../tests/test_discovery_publisher.py) проверяют signing,
CAS conflict, два типа потерянного запроса, renewal, stale pending, mirror/journal
failure, rollback, чужую installation, actual OS lock и 32 конкурирующих вызова,
scope/log/source cache и HTTP readiness. Вместе с signer: **50 passed**.
Во время разработки stale/expired pending cases падали до исправления (2 failures).
Windows проверка также выявила кратковременный sharing conflict при разрешении
live journal path до блокировки; этот лишний filesystem read исключён.

Native приёмка: scheduler после restart своего connector опубликовал signed v8
через 39.97 s. APK автоматически приняла новый адрес и выполнила echo за 250.83 s,
сохранив PID/identity и не регистрируясь заново. Повторные циклы — unchanged v8.
[Сценарий и evidence](../audits/2026-09-05/AUTOMATIC-DISCOVERY-PUBLICATION.md).
Host reboot/logon trigger и многосуточный renewal drill пока не выполнены.
