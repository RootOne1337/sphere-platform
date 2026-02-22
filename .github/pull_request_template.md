<!-- .github/pull_request_template.md -->
## Описание
<!-- Краткое описание изменений -->

## Тип изменения
- [ ] ✨ feat: новая функция
- [ ] 🐛 fix: исправление бага
- [ ] 🔒 security: исправление безопасности
- [ ] ♻️ refactor: рефакторинг
- [ ] 📝 docs: документация
- [ ] ⚡ perf: оптимизация

## Связано с
<!-- SPHERE-XXX или ссылка на issue -->

## Checklist
- [ ] Тесты написаны и проходят
- [ ] `ruff check` проходит без ошибок
- [ ] `mypy` проходит без ошибок
- [ ] Нет секретов в коде (detect-secrets clean)
- [ ] Миграции обратимы (downgrade работает)
- [ ] API backward-compatible (или отмечено BREAKING CHANGE)

## Security Checklist
- [ ] Нет SQL injection (используем ORM/параметризованные запросы)
- [ ] Нет XSS (шаблоны экранируются)
- [ ] Нет IDOR (проверка org_id/user_id)
- [ ] RBAC проверки на всех endpoints
- [ ] Rate limiting на публичных endpoints
