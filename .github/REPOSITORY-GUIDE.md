# Устройство репозитория в GitHub

[Главная](../README.md) · [Contributing](../CONTRIBUTING.md) · [Support](../SUPPORT.md)

Этот служебный документ намеренно называется `REPOSITORY-GUIDE.md`.
GitHub выбирает главный README в порядке `.github/` → корень → `docs/`.
Файл `.github/README.md` перекрыл бы презентацию продукта в корне репозитория.
[Правило GitHub](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes).

| Элемент | Назначение |
| --- | --- |
| [README](../README.md) и [обложка](../docs/assets/sphere-cover.svg) | Главный вход, состояние продукта и маршруты по документации |
| [Issue forms](ISSUE_TEMPLATE/) | Баг, производительность/recovery, документация, функция и вопрос |
| [Issue chooser](ISSUE_TEMPLATE/config.yml) | Переходы к документации, приватному security report и известным проблемам |
| [PR template](pull_request_template.md) | Причина, итоговое поведение, evidence, rollout и residual risk |
| [CODEOWNERS](CODEOWNERS) | Текущий владелец кода; не настройка required approvals |
| [Workflows](workflows/) | Фактически исполняемые CI/deployment jobs |
| [Инструкции проекта](instructions/1337.instructions.md) | Соглашения разработки |
| [Архив описания первого PR](PR_develop_to_main.md) | Исторический контекст; не текущий template или readiness |

## Когда оформление становится доступно

GitHub использует issue forms из default branch. Изменение файлов в draft PR
не обновляет главное меню создания issues или главную страницу `main`.
До merge просматривайте README в ветке PR и используйте структуру форм вручную.
PR template также следует проверять после попадания в default branch.

Обновление CODEOWNERS не означает включение branch protection. Rulesets, review
requirements, workflows, релизы и публикация APK — отдельные операции.
Шаблоны не запускают deployment и не меняют роли пользователей Sphere.

## Поддержание форм

Используйте существующие labels, уникальные ASCII `id`, понятные обязательные
поля и короткие подсказки. У severity должна быть связь с наблюдаемым влиянием;
окончательный приоритет определяют после воспроизведения. Не просите загружать
секреты или полный диагностический архив в публичное обращение.

Сверяйтесь с официальной документацией GitHub:
[issue forms](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms),
[схема полей](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-githubs-form-schema),
[CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners).
