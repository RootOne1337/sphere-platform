# Ограниченный observer: обнаружен разрыв, сбор возобновлён

Срез: 9 октября21:14:26UTC /10 октября02:14:26UTC+5.
[Машинный receipt](STORAGE-OBSERVER-CONTINUITY.json).
EP-033/047 и CHAT-12 остаются OPEN; источник расхода всего C: UNKNOWN.

Прежний status.json продолжал сообщать running, но процесс PID26192 отсутствовал.
Последняя законченная запись20:06:57UTC; 223 samples /2953982 bytes сохранены.
Причина завершения не установлена. Host boot не изменился с8октября;
это не доказательство причины завершения helper. Поздний status сам по себе
не подтверждает работающий collector. Данные за разрыв не восстановлены.

Проверено отсутствие другого host_storage_watch; один новый hidden процесс
PID30568 запущен21:09:30UTC. Command binding и creation epoch сверены через CIM.
Тот же source SHA,24 named files, Windows RAM/commit/process IO и periodic
Docker/WSL metadata. Ограничение467×120s, до10октября12:41:30UTC;16MiB report,
128KiB sample, без full scan/cleanup/input/service restart/autostart.

Проверены три законченные записи0–2 и hash prefix. Последняя21:13:30UTC,
C: free52831019008B. Изменения свободного места в этом окне включают скачанный
CI artifact и его распаковку; приписывать всё изменение проектной утечке нельзя.
VSS/kernel evidence недоступны без administrator, IO включает сетевые операции.
Большой Docker VHDX и успешный запуск helper не устанавливают дискового writer.

На следующей проверке сверять PID/creation/command, latest complete sample и
deadline вместе. При новом разрыве или окончании окна coverage перестаёт быть
живым; не экстраполировать его на reboot или будущие часы.
[Resource runbook](../../operations/HOST-RESOURCES.md) ·
[Текущие работы](../../operations/WORK-STATUS.md).
