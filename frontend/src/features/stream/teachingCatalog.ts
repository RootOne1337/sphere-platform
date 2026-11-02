/** Presentation only. Callers own storage verification, capabilities and status reads. */
export type TeachingCatalogPreparationPhase = 'waiting' | 'persisting' | 'uploading' | 'processing' | 'ready' | 'failed' | 'cancelled' | 'stopped' | 'unavailable';
export type TeachingCatalogNavigationPhase = 'not_prepared' | 'pending_auto_prepare' | 'preparing' | 'features' | 'ready' | 'failed' | 'rejected' | 'cancelled' | 'unavailable';
export type TeachingCatalogEntry = {
  id: string;
  title: string;
  createdAt: number;
  frames: number;
  durationSeconds?: number | null;
  deviceId?: string | null;
  deviceName?: string | null;
  controlMode?: string | null;
  hudProfile?: string | null;
  hudHidden?: boolean;
  /** saved requires a caller-verified COMPLETE/manifest binding; it is not a video quality verdict. */
  sourceState: 'saved' | 'incomplete' | 'unverified' | 'unavailable';
  sourceFailure?: string | null;
  preparation?: {phase: TeachingCatalogPreparationPhase; reason?: string | null; updatedAt: number; jobId?: string} | null;
  navigation?: {phase: TeachingCatalogNavigationPhase; error?: string | null; updatedAt?: number} | null;
  /** Successful read time, not the last time a persistent job changed phase. */
  statusCheckedAt?: number | null;
};
export type TeachingCatalogSort = 'newest' | 'oldest' | 'title';
export type TeachingCatalogFilter = 'all' | 'saved' | 'processing' | 'map' | 'attention';
export type TeachingCatalogTone = 'neutral' | 'success' | 'working' | 'warning' | 'error';
export type TeachingCatalogBadge = {label: string; tone: TeachingCatalogTone};
export type TeachingCatalogPresentation = {
  source: TeachingCatalogBadge;
  reconstruction: TeachingCatalogBadge;
  navigation: TeachingCatalogBadge;
  freshness: 'none' | 'current' | 'stale' | 'unknown';
  processing: boolean;
  mapForReview: boolean;
  attention: boolean;
  action: {kind: 'prepare' | 'review'; label: string};
};
export const TEACHING_CATALOG_PAGE_SIZE = 12;
const processingPhases = new Set<TeachingCatalogPreparationPhase>(['waiting', 'persisting', 'uploading', 'processing']);
const navigationProcessing = new Set<TeachingCatalogNavigationPhase>(['pending_auto_prepare', 'preparing', 'features']);
const preparationLabels: Record<TeachingCatalogPreparationPhase, string> = {
  waiting: 'В очереди', persisting: 'Сохраняем задание', uploading: 'Передаём исходник', processing: 'Идёт обработка',
  ready: 'Расчёт завершён', failed: 'Обработка остановлена с ошибкой', cancelled: 'Обработка отменена',
  stopped: 'Автоподготовка остановлена', unavailable: 'Статус недоступен',
};
const navigationLabels: Record<TeachingCatalogNavigationPhase, string> = {
  not_prepared: 'Карта не подготовлена', pending_auto_prepare: 'Ожидает подготовки карты', preparing: 'Строим карту',
  features: 'Проверяем ориентиры', ready: 'Карта для проверки', failed: 'Ошибка подготовки карты',
  rejected: 'Карта не прошла проверку', cancelled: 'Подготовка карты отменена', unavailable: 'Состояние карты недоступно',
};
const sourceLabels: Record<TeachingCatalogEntry['sourceState'], TeachingCatalogBadge> = {
  saved: {label: 'Видео сохранено', tone: 'success'}, incomplete: {label: 'Неполная запись', tone: 'warning'},
  unverified: {label: 'Запись ещё не проверена', tone: 'neutral'}, unavailable: {label: 'Исходник недоступен', tone: 'error'},
};
const statusReasonLabels: Record<string, string> = {
  catalog_access_denied: 'Нет доступа к заданию',
  catalog_job_missing: 'Задание не найдено',
  catalog_source_unconfirmed: 'Источник не подтверждён',
  catalog_status_invalid: 'Ответ не подтверждён',
  catalog_status_unavailable: 'Статус недоступен',
};
const sourceReasonLabels: Record<string, string> = {
  teaching_library_complete_binding: 'Маркер сохранения не подтверждён',
  teaching_library_release_unconfirmed: 'Освобождение ввода не подтверждено',
  teaching_library_index_integrity: 'Индексы не прошли проверку',
  teaching_library_frame_index: 'Индекс кадров не подтверждён',
  teaching_library_input_index: 'Журнал ввода не подтверждён',
  teaching_library_video_size: 'Размер видео не совпадает с индексом',
  teaching_library_source_missing: 'Файлы исходника не найдены',
  teaching_library_source_invalid: 'Исходник не прошёл проверку',
  teaching_library_scan_budget: 'Проверка записи отложена',
  teaching_library_manifest_binding: 'Описание записи не подтверждено',
  teaching_library_file_quota: 'Файл превысил предел проверки',
};
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

export function teachingCatalogPresentation(entry: TeachingCatalogEntry, options: {nowMs: number; statusStaleAfterMs?: number; readOnly?: boolean}): TeachingCatalogPresentation {
  const hasStatus = !!(entry.preparation || entry.navigation);
  const ttl = options.statusStaleAfterMs ?? 30000;
  const checked = entry.statusCheckedAt;
  const freshness = !hasStatus ? 'none' : !finite(checked) || !finite(options.nowMs) || checked > options.nowMs || !finite(ttl) || ttl < 0
    ? 'unknown' : options.nowMs - checked > ttl ? 'stale' : 'current';
  const current = freshness === 'current';
  const processing = current && (!!entry.preparation && processingPhases.has(entry.preparation.phase)
    || !!entry.navigation && navigationProcessing.has(entry.navigation.phase));
  const mapForReview = current && entry.sourceState === 'saved' && entry.navigation?.phase === 'ready';
  const failed = current && (entry.preparation?.phase === 'failed' || entry.navigation?.phase === 'failed' || entry.navigation?.phase === 'rejected');
  const attention = entry.sourceState === 'incomplete' || entry.sourceState === 'unavailable' || failed;
  const historical = (label: string) => current ? label : `Ранее: ${label.toLocaleLowerCase('ru')}`;
  const reconstruction: TeachingCatalogBadge = entry.preparation
    ? {label: historical(entry.preparation.phase === 'unavailable' && entry.preparation.reason && statusReasonLabels[entry.preparation.reason]
      || preparationLabels[entry.preparation.phase]), tone: !current ? 'neutral' : entry.preparation.phase === 'failed' ? 'error'
      : processingPhases.has(entry.preparation.phase) ? 'working' : entry.preparation.phase === 'ready' ? 'success' : 'warning'}
    : {label: 'Обработка не запускалась', tone: 'neutral'};
  const navigation: TeachingCatalogBadge = entry.navigation
    ? {label: historical(entry.navigation.phase === 'unavailable' && entry.navigation.error && statusReasonLabels[entry.navigation.error]
      || navigationLabels[entry.navigation.phase]), tone: !current ? 'neutral' : entry.navigation.phase === 'ready' ? 'success'
      : navigationProcessing.has(entry.navigation.phase) ? 'working' : ['failed', 'rejected'].includes(entry.navigation.phase) ? 'error' : 'neutral'}
    : {label: 'Карта не подготовлена', tone: 'neutral'};
  if (current && entry.navigation?.phase === 'ready' && entry.sourceState !== 'saved') {
    navigation.label = 'Карта есть · исходник не подтверждён';
    navigation.tone = 'warning';
  }
  // A terminal error requires inspection. The catalog never retries it implicitly.
  const mayPrepare = entry.sourceState === 'saved' && !entry.preparation && !entry.navigation && !options.readOnly;
  const action = mayPrepare ? {kind: 'prepare' as const, label: 'Подготовить маршрут'}
    : {kind: 'review' as const, label: processing ? 'Открыть обработку' : mapForReview ? 'Открыть карту' : failed ? 'Открыть диагностику'
      : entry.sourceState === 'unverified' ? 'Проверить запись' : entry.sourceState === 'unavailable' ? 'Проверить исходник' : 'Открыть запись'};
  const source = {...sourceLabels[entry.sourceState]};
  const sourceReason = entry.sourceFailure && (sourceReasonLabels[entry.sourceFailure] || statusReasonLabels[entry.sourceFailure]);
  if (entry.sourceState !== 'saved' && sourceReason) source.label = sourceReason;
  return {source, reconstruction, navigation, freshness, processing, mapForReview, attention, action};
}

export function teachingCatalogControlLabel(mode: string | null | undefined): string {
  return mode === 'vehicle_buttons' || mode === 'vehicle_stick' ? 'Транспорт' : mode === 'stick' ? 'Стик' : 'Управление не указано';
}
export function teachingCatalogHudLabel(entry: Pick<TeachingCatalogEntry, 'hudProfile' | 'hudHidden'>): string {
  if (entry.hudProfile === 'black_russia_scooter_v1') return 'HUD · Black Russia';
  if (entry.hudHidden === true) return 'HUD скрыт';
  if (entry.hudHidden === false) return 'HUD в кадре';
  return entry.hudProfile ? `HUD · ${entry.hudProfile}` : 'HUD не указан';
}
export function teachingCatalogDuration(seconds: number | null | undefined): string {
  if (!finite(seconds) || seconds < 0) return 'Длительность не определена';
  const value = Math.floor(seconds);
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
}
export function teachingCatalogDate(value: number): string {
  return finite(value) && value > 0 && !Number.isNaN(new Date(value).getTime())
    ? new Intl.DateTimeFormat('ru', {day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'}).format(new Date(value)) : 'Дата неизвестна';
}
export function teachingCatalogReason(code: string | null | undefined): string | null {
  if (!code) return null;
  const labels: Record<string, string> = {
    catalog_access_denied: 'Нет доступа к заданию. Проверьте вход в аккаунт и сохранённую ссылку на результат.',
    catalog_job_missing: 'Задание не найдено. Откройте запись и проверьте сохранённую попытку обработки.',
    catalog_source_unconfirmed: 'Источник задания не подтверждён для этой записи. Такой результат не используется как её карта.',
    catalog_status_invalid: 'Ответ о состоянии не прошёл проверку. Сохранённые материалы не изменены.',
    catalog_status_unavailable: 'Не удалось прочитать состояние задания. Это не подтверждает остановку локального обработчика.',
    teaching_library_complete_binding: 'Маркер завершения не соответствует описанию записи. Исходник не принят как подтверждённый.',
    teaching_library_release_unconfirmed: 'В записи нет подтверждения освобождения ввода. Её нужно проверить перед подготовкой.',
    teaching_library_index_integrity: 'Размер или контрольная сумма индекса не совпали с описанием записи.',
    teaching_library_frame_index: 'Порядок, время или расположение кадров в индексе не прошли проверку.',
    teaching_library_input_index: 'Журнал ввода не соответствует описанию записи.',
    teaching_library_video_size: 'Размер сохранённого видео не совпадает с описанием или индексом кадров.',
    teaching_library_source_missing: 'Не найдены один или несколько файлов исходной записи.',
    teaching_library_source_invalid: 'Не удалось подтвердить формат или содержимое исходной записи.',
    teaching_library_scan_budget: 'Достигнут предел проверки индексов за один просмотр библиотеки. Запись не удалена.',
    teaching_library_manifest_binding: 'Описание записи не соответствует её идентификатору или поддерживаемому формату.',
    teaching_library_file_quota: 'Один из файлов превышает предел проверки библиотеки. Запись не удалена.',
    recording_incomplete: 'Запись не получила подтверждение завершения. Сохранённая часть доступна для проверки.',
    resource_guard: 'Обработка остановлена проверкой ресурсов. Исходник сохранён.',
    route_map_has_unobserved_sections: 'На части пути недостаточно подтверждённых ориентиров.',
    route_camera_motion_requires_review: 'Восстановленную траекторию нужно проверить.',
    camera_geometry_degenerate: 'Геометрия камер не прошла проверку.',
    camera_quality_gate_failed: 'Часть камер не прошла проверку качества.',
    manifest_missing: 'Не удалось прочитать описание исходной записи.',
    source_missing: 'Файлы исходной записи не найдены.',
    worker_service_restarted: 'Обработчик был перезапущен; проверьте сохранённое задание.',
  };
  return labels[code] ?? 'Подробности доступны при открытии записи.';
}
export function selectTeachingCatalog(entries: readonly TeachingCatalogEntry[], options: {
  query?: string; sort?: TeachingCatalogSort; filter?: TeachingCatalogFilter; page?: number; nowMs: number; statusStaleAfterMs?: number;
}) {
  const query = (options.query ?? '').trim().toLocaleLowerCase('ru');
  const presented = entries.map(entry => ({entry, view: teachingCatalogPresentation(entry, options)}));
  const counts = {
    all: entries.length, saved: presented.filter(row => row.entry.sourceState === 'saved').length,
    processing: presented.filter(row => row.view.processing).length, map: presented.filter(row => row.view.mapForReview).length,
    attention: presented.filter(row => row.view.attention).length,
  };
  const rows = presented.filter(({entry, view}) => {
    const filter = options.filter ?? 'all';
    if (filter === 'saved' && entry.sourceState !== 'saved' || filter === 'processing' && !view.processing
      || filter === 'map' && !view.mapForReview || filter === 'attention' && !view.attention) return false;
    return !query || [entry.title, entry.id, entry.deviceId, entry.deviceName, teachingCatalogControlLabel(entry.controlMode), teachingCatalogHudLabel(entry)]
      .some(value => value?.toLocaleLowerCase('ru').includes(query));
  }).sort((a, b) => options.sort === 'title' ? a.entry.title.localeCompare(b.entry.title, 'ru') || a.entry.id.localeCompare(b.entry.id)
    : (options.sort === 'oldest' ? 1 : -1) * ((finite(a.entry.createdAt) ? a.entry.createdAt : 0) - (finite(b.entry.createdAt) ? b.entry.createdAt : 0)) || a.entry.id.localeCompare(b.entry.id));
  const pages = Math.max(1, Math.ceil(rows.length / TEACHING_CATALOG_PAGE_SIZE));
  const requested = finite(options.page) ? Math.floor(options.page) : 1;
  const page = Math.min(pages, Math.max(1, requested));
  return {counts, total: rows.length, pages, page, rows: rows.slice((page - 1) * TEACHING_CATALOG_PAGE_SIZE, page * TEACHING_CATALOG_PAGE_SIZE)};
}
