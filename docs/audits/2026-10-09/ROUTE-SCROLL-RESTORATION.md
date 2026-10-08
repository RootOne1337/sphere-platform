# Возврат и сохранение позиции страницы

9 октября 2026, Asia/Yekaterinburg. UIec3f2267 установлен на3015,
APIbe803773 сохранён. Историческая source preview проверка ниже отделена
от конечной: browser Back и общая кнопка на actual1440×900 вернули каталог
2132.5→2132.5px после route commit, без публикации/запуска сценария.
[Installed acceptance](STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE.md).

## Контракт

Общая кнопка «Вернуться на предыдущую страницу» возвращает на известную
внутреннюю предыдущую страницу этой вкладки. При прямом входе используется
родительский раздел; неизвестная история внешнего сайта не вызывается.
Кнопка конструктора возвращает в каталог `/scripts` через существующий
диалог сохранности. Отказ этого диалога не запускает переход.

Каждый посещённый history entry имеет собственные координаты основного
скролла. Повторные посещения одного URL не делят один слот. Query-параметры
нормализуются, разные фильтры сохраняют разные позиции. Back/Forward
восстанавливают координаты конкретного entry; новый раздел начинается сверху.
Именованные `data-route-scroll` области Studio поддерживаются отдельно.

Сохранение происходит до принятого перехода. App Router может отрисовать
более короткую страницу до записи history; такое ограничение scrollTop
не должно перезаписывать исходную позицию. Восстановление отложено до
кадра после route commit и обработки history listeners. Если данные ещё
загружаются, ResizeObserver повторяет попытку не более10секунд.
Прокрутка/касание/клавиши прокрутки оператора прекращают отложенный возврат.

## Ограничения хранения

- Только память вкладки: максимум80entries и12именованных областей на entry.
- History state получает только собственный scalar ID; поля Next сохраняются.
- Нет токенов, API-ответов, пикселей, текста сценария или DOM references в history.
- Смена session/user/org/role очищает координаты; refresh token той же identity
  не создаёт новую область хранения.
- Cleanup снимает listeners/RAF/observer/timers и не заменяет чужую позднюю
  обёртку history.
- F5/новая вкладка не восстанавливают прежнюю память. Это не durable draft.
- Browser Back/Forward не приобрели диалог сохранности dirty Studio:
  существующее ограничение navigation guard остаётся OPEN.
- Новая геометрия после поворота/изменения размера может изменить видимую строку
  при той же координате. Поиск логического якоря строки здесь не реализован.

## Проверки

10 regressions проверяют Back/Forward, повторный URL, фильтры, внутренние
области, сохранение framework state, ранний render clamp, поздний рост данных,
приоритет ввода пользователя, лимиты/cleanup и смену identity.
TypeScript без incremental cache прошёл.

В source preview3026 фактический coordinate click из каталога при main884px,
переход в сохранённый сценарий и browser Back вернули ровно884px.
Ранние semantic-click попытки вернули800px: browser automation перед кликом
изменила scroll; диагностический departure был затем проверен coordinate
click. Временный диагностический logger удалён из исходника.
Это историческое preview evidence; отдельная установленная приёмка приведена выше.

## Исходники и связанные документы

[Controller](../../../frontend/src/features/navigation/routeScrollRestoration.ts),
[shell integration](../../../frontend/src/features/navigation/ShellScrollRestoration.tsx),
[leave guard](../../../frontend/src/features/navigation/workspaceNavigationGuard.ts),
[tests](../../../frontend/__tests__/navigation/routeScrollRestoration.test.ts),
[previous guard limits](../2026-10-07/STUDIO-NAVIGATION-PRESERVATION.md).
