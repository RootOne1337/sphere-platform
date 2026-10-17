export type UserField = 'email' | 'password' | 'role';
export interface UserFailure { message: string; fields: Partial<Record<UserField, string>> }

const explanations: Record<string, string> = {
  'User with this email already exists': 'Учётная запись с этим адресом уже существует.',
  'Cannot assign this role': 'Нет права назначить выбранную роль.',
  'Cannot change this role': 'Нет права изменить эту роль.',
  'Cannot deactivate this role': 'Нет права отключить пользователя с этой ролью.',
  'Cannot deactivate yourself': 'Нельзя отключить собственную учётную запись.',
  'Cannot remove the last org_owner': 'Нельзя лишить организацию последнего владельца.',
  'User not found': 'Пользователь недоступен или удалён. Обновите список.',
};
export function describeUserFailure(error: unknown): UserFailure {
  const candidate = error as { response?: { status?: number; data?: { detail?: unknown } } } | null;
  const status = candidate?.response?.status;
  const detail = candidate?.response?.data?.detail;
  const fields: UserFailure['fields'] = {};
  if (status === 422 && Array.isArray(detail)) {
    for (const item of detail) {
      if (!item || typeof item !== 'object' || !Array.isArray(item.loc)) continue;
      const field = item.loc[0] === 'body' ? item.loc[1] : undefined;
      if (field === 'email') fields.email = 'Введите корректный адрес электронной почты.';
      if (field === 'password') fields.password = 'Пароль должен содержать от 8 до 128 символов.';
      if (field === 'role') fields.role = 'Выбранная роль не поддерживается сервером.';
    }
    return { message: 'Сервер отклонил данные формы. Исправьте отмеченные поля.', fields };
  }
  if (typeof detail === 'string' && explanations[detail]) {
    const message = explanations[detail];
    if (detail === 'User with this email already exists') fields.email = message;
    if (detail === 'Cannot assign this role') fields.role = message;
    return { message, fields };
  }
  if (status === 401) return { message: 'Сессия истекла. Войдите снова перед новой командой.', fields };
  if (status === 403) return { message: 'Сервер отказал в доступе. Проверьте действующую роль.', fields };
  if (status === 409) return { message: 'Конфликт данных. Обновите список перед повторной командой.', fields };
  if (status === 404) return { message: 'Пользователь недоступен. Обновите список.', fields };
  // Do not reflect validation inputs, passwords or arbitrary transport payloads into the UI.
  return { message: 'Результат команды не подтверждён. Обновите список перед повторной командой.', fields };
}
