# PH030: APK прямого видео установлен через адресный OTA

10 октября 2026 в 12:46:57 UTC установлен **1.2.51-dev / 10251** из исходников
`ee0d8e6f`. В 12:47:03 UTC фактический SHA-256 установленного Android package
совпал с подписанным артефактом: `4f3687e7…c1984c`. Это новая запись после
[предыдущего среза UI/API](DIRECT-VIDEO-API-INSTALLED.md); предыдущий JSON не изменён.

[Машиночитаемое подтверждение](DIRECT-VIDEO-READONLY-INSTALLED.json) ·
[Текущая работа](../../operations/WORK-STATUS.md).

Один адресный command завершён штатным completed receipt после перезапуска APK.
Canary grant очищен, package data и ID сохранены, ADB install и clear не использовались.
Обычный Android release channel не менялся. Публикация относится только к canary,
а не к fleet rollout или stable 1.3.0.

На 3015 и публичном туннеле после свежего heartbeat получен
`readonly_video_enabled=true` для PH030. Anonymous401, private/no-store и отсутствие
допуска PH011 сохранены. Разрешены конечные echo и read-only video проверки до30s.

Для настоящей видеопроверки в диагностике нужно выбрать «Видеокадры с APK по WebRTC»,
затем «Проверить видео с APK». Обмен20/20 из режима «Связь браузера с APK» подтверждает
только DataChannel echo. Он не подтверждает получение/отрисовку RTP-видео, localhost,
задержку изображения или прямое управление.

**Открыто:** реальные native JNI/RTP frames на ноутбуке, основной direct viewer/input,
TURN/WAN, ABR/pacing, reconnect/ownership, ресурсы и стабильный1.3.0. Основное видео
и ввод продолжают идти через серверный WebSocket. Product9/41 и legacy7 не меняются.
