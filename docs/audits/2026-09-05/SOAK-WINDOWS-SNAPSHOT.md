# AUD-118: читатель status.json прерывает прогон на Windows

**Severity: Medium / P2 · воспроизведён локальный дефект harness · исправлен в исходниках.**

[Evidence до/после](evidence/windows-snapshot-regression.json) ·
[Исходная остановка](ANDROID-SOAK-TERMINAL.md)

`write_json` записывал временный файл и один раз вызывал `Path.replace`. Открытый
в Windows читатель без `FILE_SHARE_DELETE` запрещает замену, хотя запись нового
файла разрешена. Изолированный `CreateFileW` на новом тестовом файле воспроизвёл
`PermissionError`, errno 13 / winerror 5, именно на replace. Старый JSON остался
целым; после закрытия handle замена прошла.

Это доказывает дефект записи снимков, **но не устанавливает причину исходного
ночного PermissionError**: у того события нет traceback/OS code. Исходный failed
run не исправляется задним числом.

Общий [atomic_json.py](../../../scripts/pilot/atomic_json.py) используется runner
и summarizer. Только replace повторяется при Windows codes 5/32/33: максимум
шесть попыток, суммарная пауза до 310 ms. Старый целый JSON остаётся доступным.
Постоянный запрет и остальные ошибки по-прежнему выходят наружу; задания, HTTP,
команды Android и append событий не повторяются.

[Регрессии](../../../tests/test_scripts/test_soak_atomic_json.py): настоящий reader
закрывается через 75 ms; постоянный запрет остаётся ошибкой с сохранением старого
JSON; PermissionError без Windows sharing code не повторяется. До: **2 failures,
1 control pass**. После вместе с harness: **18 pass**, Ruff pass. Настоящий
Windows case в Linux CI пропускается явно; остальные проверки переносимы.

Residual risk: нет гарантии записи при полном отказе диска, долгой блокировке или
антивирусном запрете. Новый восьмичасовой прогон после исправления ещё не принят.
