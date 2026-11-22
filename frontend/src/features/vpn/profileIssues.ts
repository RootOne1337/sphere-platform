const issueLabels: Record<string, string> = {
  executable_or_routing_directive_forbidden: 'Команды и ручные изменения маршрутов запрещены',
  unsupported_field_for_protocol_version: 'Поле не поддерживается выбранной версией протокола',
  invalid_field_value: 'Некорректное значение поля',
  duplicate_field: 'Поле повторяется', duplicate_section: 'Секция повторяется',
  unknown_section: 'Неизвестная секция', invalid_entry: 'Некорректная строка',
  invalid_line: 'Недопустимая или слишком длинная строка',
  missing_awg_parameters: 'Не хватает обязательных параметров AWG',
  awg_header_ranges_overlap: 'Диапазоны заголовков AWG пересекаются',
  junk_size_range_inverted: 'Минимальный размер пакета больше максимального',
  header_protection_requires_four_prefixes: 'Header Protection требует S1–S4 не менее 12 байт',
  ipv6_config_conflicts_with_block_policy: 'IPv6 в конфигурации конфликтует с политикой блокировки',
  ipv6_tunnel_address_and_default_route_required: 'Для IPv6 нужны адрес туннеля и маршрут ::/0',
  selected_app_egress_requires_ipv4_default_route: 'Для выбранных приложений нужен маршрут IPv4 по умолчанию',
  ipv4_tunnel_address_required: 'Нужен IPv4-адрес туннеля', config_too_large: 'Конфигурация больше 64 КиБ',
};

/** Render only known codes, never untrusted API/config text. */
export function profileIssueLabel(code: string): string {
  return Object.prototype.hasOwnProperty.call(issueLabels, code) ? issueLabels[code]
    : code.startsWith('missing_') ? 'Не хватает обязательного поля конфигурации' : 'Некорректная конфигурация';
}
