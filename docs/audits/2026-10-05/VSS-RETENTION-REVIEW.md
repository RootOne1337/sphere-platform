# VSS и текущая потеря свободного места: проверка и выбор retention

**Дата:** 5 октября 2026, Asia/Yekaterinburg; замеры UTC 4 октября.
**Статус:** текущий рост allocation подтверждён; оператор одобрил изменение,
лимит C:→C:8GiB применён22:58:31 UTC. API/UI c1a6e79, APK10244 сохраняются.

[Writer audit](DISK-WRITER-ATTRIBUTION.md) ·
[Sanitized evidence](DISK-WRITER-ATTRIBUTION-EVIDENCE.json) ·
[Current state](../../operations/CURRENT-STATE.md).

## Два точных среза

| Counter | 21:38:30 UTC | 22:52:24 UTC | Delta |
|---|---:|---:|---:|
| Free C: | 47 047 684 096 bytes | 44 864 716 800 bytes | −2 182 967 296 bytes /−2,033 GiB |
| VSS AllocatedSpace | 16 360 038 400 bytes | 18 473 967 616 bytes | +2 113 929 216 bytes /+1,969 GiB |

Приращение VSS составляет около96,8% наблюдаемого net free-drop между этими
двумя срезами. Это сопоставление измеренных allocation counters, не утверждение,
что каждый скопированный блок принадлежит Docker. Другие записи/удаления и запись
самого сохранённого ETL тоже входят в free C:. Length VHDX остаётся
234 731 077 632 bytes; неизменная длина файла не исключает VSS copy-on-write.

## Короткое окно с kernel trace

22:42:22–22:43:50 UTC, 10 samples; плановый600s предел остановлен раньше по
`free_drop_trigger`. Free C: −236 806 144 bytes; exact VSS UsedSpace
+287 535 104 bytes, AllocatedSpace **+234 881 024 bytes /224 MiB**.
FileIO пишет в Docker VHDX: `vmmemWSL`166 641 664bytes и `System`83 046 400bytes.
Это logical writes, не прирост файла и не отдельные уникальные disk bytes.
EventsLost0; compressed ETL36 790 868bytes. Разбор исключает stop/rundown после
последнего volume sample. Captured retained FileIO начинается22:42:20, немного
раньше первого sample; ни один полный600s soak здесь не заявлен.

Windows Microsoft Software Shadow Copy provider1.0 использует copy-on-write:
старые блоки сохраняются перед изменением исходного тома. Поэтому перезапись
существующего большого VHD может расходовать additional C: space.
Это объяснение механизма и inference из совпадающих замеров, а не трасса каждого
VSS block до конкретной Android-команды.
[Microsoft VSS mechanism](https://learn.microsoft.com/en-us/windows-server/storage/file-server/volume-shadow-copy-service).

## Что реально существует

Elevated read-only query22:52:24 UTC:

- Provider: Microsoft Software Shadow Copy provider1.0 /version1.0.0.7.
- Две persistent/client-accessible shadow copies C:, created
  03:03:29 UTC и18:28:09 UTC 4 октября.
- Get-ComputerRestorePoint показывает одну scheduled checkpoint /sequence292,
  created03:03:21 UTC. Она не объявляется доказательством назначения второй copy.
- UsedSpace18 135 015 424bytes; AllocatedSpace18 473 967 616bytes /17,205 GiB.
- MaxSpace20 461 912 064bytes /19,057 GiB; remaining allocation около1,851 GiB.
- No native query error, administrator=true; systemChangesPerformed=false.

Это bounded maximum, не бесконечный лог. VSS может удалять старые copies при
исчерпании capacity. Сам по себе этот19GiB максимум не объясняет всю историческую
потерю150GiB или весь Docker218,6GiB. Image accumulation доказана отдельно.

## Проверенный и одобренный вариант изменения

Можно уменьшить только association **C: → C:** до8GiB, сохранив VSS включённым:

```powershell
vssadmin resize shadowstorage /for=C: /on=C: /maxsize=8589934592
```

Текущее allocation превышает предложенный максимум примерно на9,205GiB.
Это потенциальный scope reclamation, а не обещанный exact free gain. Снижение
максимума может необратимо удалить существующие shadow copies; число/даты
оставшихся копий нельзя обещать заранее. Возврат старого max не вернёт удалённые
копии. Поэтому выполнить только после прямого согласия оператора на потерю этой
истории восстановления. Это ограничение связано с реальными двумя copies,
а не с инструкцией skill или блокировкой auto-review.
[Microsoft resize warning](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/vssadmin-resize-shadowstorage).

При одобрении: повторить exact volume/provider/storage inventory, сохранить before;
изменить только эту association, записать native exit и after Used/Allocated/Max,
free C: и список copies. При ошибке не выполнять fallback delete/disable.
Проверить API/UI/fleet после действия и отдельно observe обычные Docker writes.
Docker/WSL stopping, VHD compaction и отключение System Restore сюда не входят.

### Фактическое применение22:58:31 UTC

Оператор ответил «делай как считаешь нужнеым» на конкретный вариант8GiB с
предупреждением об удалении существующих copies. После повторной проверки volume,
association, provider и прежнего MaxSpace выполнена ровно приведённая команда.
Native exit0; прочитанный после операции MaxSpace=8 589 934 592bytes.

| Counter | Before | After |
|---|---:|---:|
| Free C: | 44 851 392 512bytes | 63 325 396 992bytes |
| VSS UsedSpace | 18 151 464 960bytes | 0 |
| VSS AllocatedSpace | 18 473 967 616bytes | 0 |
| Shadow copies C: | 2 | 0 |
| MaxSpace | 20 461 912 064bytes | 8 589 934 592bytes |

Наблюдаемый gain **18 474 004 480bytes /17,205GiB**: обе прежние copies
удалены Windows при resize. Это результат, не обещание сохранить последнюю copy.
Мы не отключали VSS/System Restore, не делали fallback delete, не меняли registry
и не выполняли Docker/WSL restart. Возврат max не восстановит прежние copies.

Postchange22:59:21 UTC: API ready/PostgreSQL/Redis ok,19 catalog devices,
14 online10244; все46 container identities/image/start epochs прежние.
Android-команд0. Будущие restore points могут вновь использовать место до8GiB;
это ограничение не ограничивает Docker images/cache, которые наблюдаются отдельно.

## Предотвращение build accumulation

Source `c89594a` добавляет
[`plan_owned_image_retention.py`](../../../scripts/pilot/plan_owned_image_retention.py):
только четыре явно attested repositories, all-tags ownership, hex tag → local Git
commit, current installed source, не менее двух newest rollback images и все
running/stopped container dependencies. Container identity/epoch сверяется повторно
до записи плана. Unknown/dangling/foreign aliases не попадают в candidates.

```powershell
& '.venv-audit/Scripts/python.exe' -X utf8 scripts/pilot/plan_owned_image_retention.py --current-commit c1a6e79
```

14 regressions passed /Ruff passed. Actual read-only inventory22:52 UTC:
**0 additional candidates /46 containers** после предыдущей адресной cleanup.
Инструмент не удаляет образы и не устанавливает scheduled task. Перед любым later
apply повторить guards: plan является snapshot, не постоянным разрешением.
Logical sizes не называются reclaimable physical bytes.

Прочие shared images/cache пока не получили ownership proof для удаления.
Global prune и изменение общего Docker GC budget этим этапом не выполнялись.
VHD physical compaction, global server log quota и long RAM soak OPEN.
