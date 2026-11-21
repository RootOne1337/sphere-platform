# Согласование H.264 при восстановлении декодера

Подготовка исходников; это не приёмка нового установленного веба.

На вебе/API04cf101 и PH011 с APK76 два прогона десяти клиентов остановились
на девятом. Первые восемь получили прямое видео и готовность shared input.
Во втором прогоне безопасная инструментализация показала: у первых восьми
MediaCapabilities подтвердил H.26442e029 за0–1мс; девятый не вызывал проверку
и четыре раза предложил42e01f. APK записал receiver_level_insufficient.
Это не доказательство сетевого/NAT отказа. Все десять собственных контекстов
после каждого прогона закрыты. Отрицательные результаты сохранены отдельно.

DeviceStream читал lastRenderedProfileLevelId, который обнуляется вместе с
renderedCapture при восстановлении WebCodecs. При этом уже отображённый canvas
и его serverCaptureRef могли сохраниться. Новая попытка WebRTC использовала
этот capture, но теряла сведения о его кодеке и отправляла обычный receive level.

Исправление953b75f0 использует текущий SPS только для совпадающего captureEpoch.
Восстановление декодера не удаляет эти заголовки; reset, смена capture и destroy
делают прежний профиль недоступным. Знание SPS не считается отрисованным кадром
и не открывает ввод. Проверка MediaCapabilities, ограничение времени проверки,
проверка уровня в APK и проверка фактического прямого кадра сохранены.

Локально прошли2417 тестов в167 наборах и tsc. Новые регрессии проверяют, что
после recovery профиль известен, но lastRenderedCapture остаётся null, а смена
epoch/reset/destroy исключают использование прежних заголовков. Результат
Sphere Local / Frontend regressions опубликован на GitHub для точного953b75f0.

Cloud run38608809565 прошёл тесты, типы, Next build и packaged HTTP probe,
но не выпустил runtime image: docker вернул registry_rate_limit. Повторные
Android/backend jobs остановлены после проверки неизменности component trees;
отмена не обозначена как успешный тест.

Упаковка теперь допускает один переход между ECR Public Docker publisher и
Docker Hub official library только при отказе quota. Linux/amd64 manifest
Node24 в обоих registries прочитан и совпал по SHA-256:
d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20.
Mutable tag не используется; обычная ошибка build/context и timeout не вызывают
fallback. Два отказавших registry оставляют сборку неуспешной. Шесть тестов
ограничения/перехода/редактирования диагностики прошли.

[Правила согласования H.264](https://www.rfc-editor.org/rfc/rfc6184.html) ·
[WebRTC MediaCapabilities](https://www.w3.org/TR/media-capabilities/) ·
[ECR Public pull и quotas](https://docs.aws.amazon.com/AmazonECR/latest/public/docker-pull-ecr-image.html).

До установки нового веба, повторного теста десяти клиентов и восстановления
канала управления массовая OTA76 удержана. Уже принятый узкий keyboard scope76
на PH011 включает фактический Unicode, emoji delete, Ctrl+A, IME composition,
game key edges, fullscreen и два владельца IME с восстановлением прежней
клавиатуры. Это не приёмка20+, телефона/hotspot/WAN/TURN, server-fallback full
keyboard, audio, работы без broker или полного переноса hosted CI.

[Действующий статус](../../operations/WORK-STATUS.md).
