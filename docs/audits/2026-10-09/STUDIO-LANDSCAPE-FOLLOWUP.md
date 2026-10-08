# Studio: установленный landscape нашёл вторую итерацию

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
