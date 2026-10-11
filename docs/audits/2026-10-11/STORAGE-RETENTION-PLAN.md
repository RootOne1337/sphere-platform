# Рост Docker и план удаления только старых образов проекта

Срез10октября,23:47 UTC. Это read-only план, **удаление не выполнялось**.
[Фиксированный результат](STORAGE-RETENTION-PLAN-2347.json).
SHA-256 normalized LF: `d2c849552de839f1acd5f8e7590162e336a2b5b57aef365f6fb67f192df873e6`.

## Что подтверждено

Внутри Docker guest занято около198GiB. Это не только пустой раздутый VHDX:
в Docker инвентаризации237 images и768 build-cache records. `docker system df`
сообщил196.4GB images и84.42GB cache; **их нельзя складывать**, слои пересекаются.
Volumes составляют7.58GB, containers318.2MB в этом конкретном срезе.

План `scripts.pilot.plan_owned_image_retention` выявил53 неиспользуемых images
нашего source с разрешёнными repositories и проверяемыми Git commit tags:
38 `sphere-review-frontend`,15 `sphere-reviewed-backend`. Защищены зависимости
**всех46 containers**, включая stopped, текущий6ee и минимум два последних
образа на repository. Foreign/неподтверждённые/не-Git tags исключены.
Наличие остановленного container не делает его image безопасным кандидатом.

`docker system df --verbose` даёт около33.7362GB image-exclusive logical layers
у53 кандидатов. Значения Docker округлены. Слои ещё могут удерживаться build cache;
VHDX и NTFS allocation отличаются от logical image size. Поэтому предполагаемое
физическое освобождение C: остаётся **unknown**, не33.7GB обещанного результата.

## Что показал limited collector

163 завершённых samples18:22→23:46 UTC: free C: −835284992B (~0.78GiB),
Docker VHDX allocation +1342177280B (1.25GiB). Найдены два окна роста:

| UTC | VHDX allocation delta | Free C: delta в этом окне |
|---|---:|---:|
|21:28|+201326592B|−204951552B|
|22:28|+1140850688B|−1403080704B|

Второе окно совпадает по времени с API/UI6ee install22:27/22:28.
Это временная корреляция, а не per-process attribution каждого файла.
В предыдущем отдельном8h окне C: потерял12.3GiB при постоянном VHDX allocation.
Нельзя объяснить всю прежнюю потерю только Docker или только размером проекта.

Process IO включает другие виды обмена; он не доказывает persistent writes на C:.
VSS/CIM недоступен с initialization failure, privileged USN/kernel attribution
нет. Ограниченный collector отслеживает24 named files, а не все файлы SSD.
Полная причина расхода C: остаётся **UNDETERMINED**.

## Граница применения

Windows сообщает `Warning / Full Repair Needed` для C:, NTFS98 требует scan.
Read-only image plan не является разрешением обходить ресурсный installer gate.
Перед применением нужны результат filesystem scan, готовность volume и новая
проверка container/image identity. При любом изменении плана нельзя применять
устаревший список53 images. В этом этапе нет prune, volume deletion, restart,
изменения VPN или команд Android.

[Ресурсы хоста](../../operations/HOST-RESOURCES.md) ·
[Блокировка установки](DIRECT-INPUT-DELIVERY-BLOCKED.md) ·
[Read-only planner](../../../scripts/pilot/plan_owned_image_retention.py).
