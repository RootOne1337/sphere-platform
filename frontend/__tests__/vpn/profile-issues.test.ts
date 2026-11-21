import { profileIssueLabel } from '@/src/features/vpn/profileIssues';

it('explains known validation failures without echoing untrusted codes', () => {
  expect(profileIssueLabel('executable_or_routing_directive_forbidden')).toBe('Команды и ручные изменения маршрутов запрещены');
  expect(profileIssueLabel('missing_private_key')).toBe('Не хватает обязательного поля конфигурации');
  for (const code of ['private-sentinel', '__proto__', 'constructor', 'toString']) {
    expect(profileIssueLabel(code)).toBe('Некорректная конфигурация');
  }
});
