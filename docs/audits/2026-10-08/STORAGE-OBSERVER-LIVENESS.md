# Повторная остановка ограниченного наблюдателя расхода диска

8 октября 2026, 06:01 Asia/Yekaterinburg. Это эксплуатационный checkpoint;
storage incident остаётся OPEN. Сборщик не является доказательством отсутствия
утечки и не предоставляет file-to-writer attribution.

В прежнем окне `.local-pilot/host-storage-limited-20261007T1824` последняя
complete JSONL строка имеет23:13:38UTC7October. Всего146samples/1344273B.
Процесса29648 нет, хотя status.json сохранил `running`; финального completion
нет. Причина прекращения не установлена. Пропуск после23:13 не восстановлен
из вымышленных samples. Старый status и исходный report не изменялись.

Измеренный интервал18:23:38–23:13:38UTC: C: свободно62510698496→58559352832B,
дельта−3951345664B. Docker VHD logical/allocated не изменились:
234731077632B. LDPlayer data0 вырос на299958272B, data1 на88932352B;
sdcard0/1 не выросли. Эти пять файлов не объясняют весь расход. VSS во всех
samples недоступен; нельзя объявить остаток потерей проекта или объяснить
его одной категорией. IO rates также включают иной трафик.

Перед заменой проверено отсутствие python процесса с точной command-line
identity сборщика. Проверен SHA-256 неизменённого source:
`d71e5c7a9fa028f91098d47c224ce53ba11723d06f03f0ee1b248dc4ce5c4bc6`.
Новый hidden process36664 стартовал01:01:25UTC8October и ограничен до
09:01:25UTC /14:01:25UTC+5. Private directory:
`.local-pilot/host-storage-limited-20261008T010125Z`.

241samples,120s interval, Docker metadata каждые8 циклов,16MiB report budget,
128KiB sample budget. Наблюдаются те же пять именованных файлов и доступные
host RAM/commit/process metadata. Первый фактический sample прочитан:
5files, host measured,22636B report, C: free53474902016B.
PID/creation epoch проверены независимо. Новый sample не заполняет прошлый gap.

Запуск без elevation: VSS/USN/ETW coverage не заявляется. Нет autostart,
очистки, Android commands, recursive scans или изменения Windows/VSS settings.
При следующем разборе необходимо снова проверить live process identity и
возраст последней JSONL строки, а не доверять одному `running`.

В06:41UTC+5 проверены creation epoch PID36664 и фактическая21-я строка
JSONL:01:41:25UTC, index20, C: свободно51972395008B. Docker VHD всё ещё
234731077632B logical/allocated. Этот endpoint snapshot не атрибутирует
разницу свободного места конкретному writer: в интервале также получались
reviewed CI archives и заменялись UI/API images. Сам `running` не является
достаточной проверкой. Финального completion этого окна пока нет.

В07:17UTC+5 отдельно подтверждён PID36664 с creation01:01:25.411362UTC,
прочитана39-я complete JSONL строка02:17:25.607301UTC, index38. Report357858B,
C: free50793803776B; Docker VHD logical/allocated234731077632B. Observer
работает, предыдущий gap остаётся. Ни quota-changing actor, ни неизвестный
остаток расхода этой проверкой не установлены.

В07:33UTC+5 снова подтверждена та же process creation identity и47-я complete
строка02:33:25.607445UTC,index46. Report430839B, C: free50641387520B;
Docker VHD234731077632B logical/allocated. Конечный сбор до14:01UTC+5
продолжается; этот наблюдатель не атрибутирует каждый файл конкретному процессу.

Связанные материалы: [ресурсы хоста](../../operations/HOST-RESOURCES.md),
[предыдущая остановка](../2026-10-07/STORAGE-COLLECTOR-INTERRUPTION.md).

## Readback 06:51 UTC /11:51 UTC+5

Same PID36664 and creation01:01:25.4113628UTC confirmed.176 complete samples,
last06:51:25.607337UTC; report1605618B, within16MiB cap. C: free48170102784B
versus53474902016B at first sample. Docker VHD remains234731077632B logical
and allocated. Legitimate CI archive downloads/image installations occurred
during this interval; this delta is not itself proof of a leak or its writer.
Collection continues until09:01UTC. Unprivileged bounded observer does not
provide universal process/file attribution; incident remains OPEN.
