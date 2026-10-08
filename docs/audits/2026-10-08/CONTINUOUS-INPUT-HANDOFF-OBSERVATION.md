# Живая проверка automatic UI и неподтверждённый переход после Home

8 октября 2026, 06:08–06:16 Asia/Yekaterinburg. Reviewed UI `bc86752` установлен
на3015; API `28104f8` и APK10249 PH011 сохранены. Frontend hosted CI1837/137,
types/build/26 packaged pages/73 client assets и image admission прошли.
При UI install45 остальных контейнеров и OTA catalog сохранены.

Настоящий браузер автоматически получил READY после открытия видео, без
переключателя. Независимый Android View подтвердил drag deltaDOWN1/MOVE3/UP1/
CANCEL0. Wheel deltaDOWN1/MOVE1/UP1/CANCEL0; terminal191ms после DOWN.
Снимок интерфейса и bounded JSON snapshots сохранены в private pilot directory.

Первый Home с receiver на переднем плане исполнен: подтверждение824ms,
launcher независимо проверен через dumpsys. Затем native control оказался
fenced; UI потребовал явного восстановления. Точный внутренний код причины
в этом build не экспонировался; причина этого единичного перехода не установлена.
Нельзя записать такой прогон как безошибочный automatic resume.

В отдельном настоящем authenticated viewer без touch actions проверены
OPEN→STARTUP→CLOSE→RELEASE→подтверждённый HOME→OPEN→STARTUP→CLOSE→RELEASE.
Оба владельца получили STARTUP0 и RELEASE3; второй STARTUP751ms от probe.
Сырые owner/session/token не публикуются. Такой diagnostic probe не заменяет
браузерную приёмку и не устанавливает причину первоначального fencing.

Явное восстановление создало свежую видеосессию без replay. Второй Home на
уже неподвижном launcher подтверждён773ms и вернулся в continuous READY
автоматически. Отличие foreground receiver/launcher — наблюдение, не причина.

Source follow-up сохраняет последний bounded lifecycle failure code в
диагностике и DOM metadata: native timeout, scheduler gap, rejected receipt,
server rejection и unknown discrete completion больше не скрываются под
одной общей фразой. Это одна scalar запись, без growing traces или input replay.
Home regression теперь проверяет и второй owner STARTUP, и новый DOWN;
добавлен тест сохранения failure cause после known release. Нужны exact-source
CI/install и повторный браузерный переход receiver→launcher с этим readback.

Параллельный review обнаружил независимую подтверждённую гонку periodic auth:
после SQL/topology/Redis await владелец мог уже закрыться или смениться, а
прежняя проверка обращалась к mutable viewer.lease, включая None, или решала
судьбу нового owner. Шесть red cases воспроизвели проблему. Source сохраняет
точный lease snapshot на каждом await boundary; obsolete check не продлевает
и не отзывает новый owner. Новая periodic проверка всё ещё закрывает текущий
owner при denied/unavailable control. Эта гонка не объявляется доказанной
причиной первоначального браузерного fencing без точного reason readback.

SF26-05, latency/fleet qualification и storage incident остаются OPEN.
