# Studio: установленный landscape нашёл вторую итерацию

**Follow-up установлен:** ec3f2267 заменил b36adbb3 на3015 в21:43:08UTC.
Actual844×390: graph195px, main342px, horizontal overflow отсутствует.
390×844: header/menu не перекрываются, запись4/4confirmed показана без
внутреннего224px scroll. Node add/parameters/Undo и Back2132.5 проверены.
История ниже сохраняет наблюдение дефекта до исправления; полная запись
траектории и адаптивная читаемость overview остаются OPEN.
[Конечная установка и проверки](STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE.md).

9 октября 2026, Asia/Yekaterinburg. Responsive source b36adbb3 установлен
на3015 в21:28:11UTC8октября. CI frontend1936tests/139suites,26pages/73assets;
45other containers/API/schema/OTA/APK сохранены. Browser подтвердил revision.
Backend/Android CI ещё выполняются; общая приёмка checkpoint не завершена.

В реальном844×390 viewport схема получила около112px по высоте из-за
отдельной строки переключателей и высоких шапок. Картина подтверждена
[скриншотом](assets/responsive-workspace/landscape-before.jpg). Это не считать
приемлемой полной landscape приёмкой.

Следующая source итерация переносит4compact переключателя в общий toolbar.
При достаточной ширине они занимают одну строку с Graph/JSON/Undo/«Ещё»;
на узком экране переносятся целой группой, без горизонтального overflow.
При высоте≤500px общая шапка48px, Studio получает соответствующий остаток
viewport и уменьшает вертикальные отступы строки названия. Все контролы
остаются доступны; сохраняются те же mounted panels/guards/receipts.

Builder54regressions и nonincremental TypeScript прошли. Final reviewed image,
установка этой итерации и повторный screenshot ещё pending. Нельзя принимать
реальную компоновку только по viewport capability: на временных вкладках
фактические размеры отличались. На основной3015вкладке844×390 подтверждены.

На установленном b36adbb3 PH011 подтвердил реальную запись Home3/Recents187/
Back4/Menu82, все4 APK confirmed. Compact Actions→Device сохранил4строки и
остановленный recording; View выбран явно. Вторая визуальная проверка нашла
два компактных дефекта: badge сборки сжимал кнопку меню, а queue имела
дополнительную внутреннюю224px прокрутку. Последний CSS follow-up позволяет
правой части общей шапки сжиматься и оставляет один основной скролл workbench
для compact queue. На desktop queue остаётся bounded224px.
Новый screenshot после reviewed установки этих изменений ещё pending.
