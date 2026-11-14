import React from 'react';
import {fireEvent, render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {TeachingRecordingCatalog} from '@/src/features/stream/TeachingRecordingCatalog';
import {selectTeachingCatalog, teachingCatalogDuration, teachingCatalogHudLabel, teachingCatalogPresentation, teachingCatalogReason,
  type TeachingCatalogEntry} from '@/src/features/stream/teachingCatalog';

const now = 1793610000000;
const saved = (overrides: Partial<TeachingCatalogEntry> = {}): TeachingCatalogEntry => ({id: 'a'.repeat(32), title: 'Спокойный заезд', createdAt: now - 1000,
  frames: 857, durationSeconds: 36.903, deviceId: 'emulator-11', deviceName: 'Эмулятор 11', controlMode: 'vehicle_buttons',
  hudProfile: 'black_russia_scooter_v1', sourceState: 'saved', ...overrides});
const fixture = [saved(), saved({id: 'b'.repeat(32), title: 'Пеший проход', deviceId: 'emulator-12', deviceName: 'Эмулятор 12', controlMode: 'stick', hudProfile: null, hudHidden: true,
  statusCheckedAt: now, preparation: {phase: 'failed', reason: 'resource_guard', updatedAt: now - 10000}, navigation: {phase: 'not_prepared'}}),
saved({id: 'c'.repeat(32), title: 'Карта квартала', statusCheckedAt: now, preparation: {phase: 'ready', updatedAt: now - 100000}, navigation: {phase: 'ready'}})];

describe('catalog state presentation', () => {
  test('a sealed recording is source saved, never navigation ready', () => {
    const view = teachingCatalogPresentation(saved(), {nowMs: now});
    expect(view.source.label).toBe('Видео сохранено');
    expect(view.navigation.label).toBe('Карта не подготовлена');
    expect(view.mapForReview).toBe(false);
    expect(view.action).toEqual({kind: 'prepare', label: 'Подготовить маршрут'});
  });
  test('completed processing and diagnostic geometry do not imply a navigation map', () => {
    const view = teachingCatalogPresentation(saved({statusCheckedAt: now, preparation: {phase: 'ready', updatedAt: now}}), {nowMs: now});
    expect(view.reconstruction.label).toBe('Расчёт завершён');
    expect(view.mapForReview).toBe(false);
  });
  test('current ready navigation means review only, and requires verified source', () => {
    const entry = fixture[2];
    expect(teachingCatalogPresentation(entry, {nowMs: now}).action).toEqual({kind: 'review', label: 'Открыть карту'});
    expect(teachingCatalogPresentation({...entry, sourceState: 'unverified'}, {nowMs: now}).mapForReview).toBe(false);
  });
  test.each(['failed', 'cancelled', 'stopped'] as const)('terminal %s is never automatically retried', phase => {
    const view = teachingCatalogPresentation(saved({statusCheckedAt: now, preparation: {phase, updatedAt: now}}), {nowMs: now});
    expect(view.action.kind).toBe('review');
    expect(view.processing).toBe(false);
  });
  test('fresh read time, not old phase-change time, establishes current state', () => {
    const entry = saved({statusCheckedAt: now, preparation: {phase: 'ready', updatedAt: now - 86400000}, navigation: {phase: 'ready'}});
    expect(teachingCatalogPresentation(entry, {nowMs: now}).mapForReview).toBe(true);
    expect(teachingCatalogPresentation({...entry, statusCheckedAt: undefined}, {nowMs: now}).freshness).toBe('unknown');
    expect(teachingCatalogPresentation({...entry, statusCheckedAt: now + 1}, {nowMs: now}).freshness).toBe('unknown');
  });
  test('stale ready and processing statuses cannot inflate current counters', () => {
    const entries = [saved({statusCheckedAt: now - 30001, preparation: {phase: 'processing', updatedAt: now}}),
      saved({id: 'b', statusCheckedAt: now - 30001, navigation: {phase: 'ready'}})];
    const result = selectTeachingCatalog(entries, {nowMs: now});
    expect(result.counts).toEqual({all: 2, saved: 2, processing: 0, map: 0, attention: 0});
    expect(result.rows[0].view.freshness).toBe('stale');
    expect(result.rows[0].view.reconstruction.label).toContain('Ранее:');
    expect(teachingCatalogPresentation({...entries[1], statusCheckedAt: now - 30000}, {nowMs: now}).mapForReview).toBe(true);
  });
  test('source failures and current map rejection are distinct attention states', () => {
    const entries = [saved({sourceState: 'incomplete'}), saved({id: 'b', statusCheckedAt: now, navigation: {phase: 'rejected'}})];
    expect(selectTeachingCatalog(entries, {nowMs: now, filter: 'attention'}).total).toBe(2);
  });
  test('read-only retains review but does not offer preparation', () => {
    expect(teachingCatalogPresentation(saved(), {nowMs: now, readOnly: true}).action).toEqual({kind: 'review', label: 'Открыть запись'});
  });
  test('search includes device, id and profile metadata without altering source order', () => {
    const entries = fixture.slice();
    expect(selectTeachingCatalog(entries, {nowMs: now, query: 'ЭМУЛЯТОР 12'}).rows.map(row => row.entry.id)).toEqual(['b'.repeat(32)]);
    expect(selectTeachingCatalog(entries, {nowMs: now, query: 'bbbbbbbb'}).total).toBe(1);
    expect(selectTeachingCatalog(entries, {nowMs: now, query: 'black russia'}).total).toBe(2);
    expect(entries.map(entry => entry.id)).toEqual(fixture.map(entry => entry.id));
  });
  test('sort and bounded 12-item paging cover all supplied recordings with stable ids', () => {
    const entries = Array.from({length: 27}, (_, i) => saved({id: String(i).padStart(4, '0'), title: `Проход ${i}`, createdAt: now + i}));
    const first = selectTeachingCatalog(entries, {nowMs: now});
    const last = selectTeachingCatalog(entries, {nowMs: now, page: 100});
    expect(first.rows).toHaveLength(12);
    expect(first.rows[0].entry.id).toBe('0026');
    expect(last.rows).toHaveLength(3);
    expect(last.page).toBe(3);
    expect(selectTeachingCatalog(entries, {nowMs: now, sort: 'oldest'}).rows[0].entry.id).toBe('0000');
    expect(selectTeachingCatalog(entries, {nowMs: now, query: 'Проход 26', page: 3}).page).toBe(1);
  });
  test('unknown and stationary duration/HUD metadata are explicit', () => {
    expect(teachingCatalogDuration(0)).toBe('0:00');
    expect(teachingCatalogDuration(36.903)).toBe('0:36');
    expect(teachingCatalogDuration(Number.NaN)).toBe('Длительность не определена');
    expect(teachingCatalogDuration(-1)).toBe('Длительность не определена');
    expect(teachingCatalogHudLabel({hudHidden: false})).toBe('HUD в кадре');
    expect(teachingCatalogHudLabel({hudHidden: true})).toBe('HUD скрыт');
  });
  test.each([
    ['catalog_access_denied', 'Нет доступа к заданию'], ['catalog_job_missing', 'Задание не найдено'],
    ['catalog_source_unconfirmed', 'Источник не подтверждён'], ['catalog_status_invalid', 'Ответ не подтверждён'],
    ['catalog_status_unavailable', 'Статус недоступен'],
  ])('typed unavailable reason %s is shown without claiming a stopped handler', (reason, label) => {
    const view = teachingCatalogPresentation(saved({statusCheckedAt: now, preparation: {phase: 'unavailable', reason, updatedAt: now},
      navigation: {phase: 'unavailable', error: reason}}), {nowMs: now});
    expect(view.reconstruction.label).toBe(label);
    expect(view.navigation.label).toBe(label);
    expect(teachingCatalogReason(reason)).not.toMatch(/запустите|должен быть запущен|обработчик недоступен/i);
    expect(view.mapForReview).toBe(false);
  });
  test.each([
    ['teaching_library_complete_binding', 'Маркер сохранения не подтверждён'],
    ['teaching_library_release_unconfirmed', 'Освобождение ввода не подтверждено'],
    ['teaching_library_index_integrity', 'Индексы не прошли проверку'],
    ['teaching_library_frame_index', 'Индекс кадров не подтверждён'],
    ['teaching_library_video_size', 'Размер видео не совпадает с индексом'],
    ['teaching_library_source_missing', 'Файлы исходника не найдены'],
    ['teaching_library_source_invalid', 'Исходник не прошёл проверку'],
    ['teaching_library_scan_budget', 'Проверка записи отложена'],
  ])('source verification reason %s has a readable independent badge and caption', (code, label) => {
    const view = teachingCatalogPresentation(saved({sourceState: 'unverified', sourceFailure: code}), {nowMs: now});
    expect(view.source.label).toBe(label);
    expect(teachingCatalogReason(code)).not.toContain(code);
    expect(view.mapForReview).toBe(false);
  });
  test('unavailable without a typed reason remains status unknown, not worker health', () => {
    const view = teachingCatalogPresentation(saved({statusCheckedAt: now, preparation: {phase: 'unavailable', updatedAt: now}}), {nowMs: now});
    expect(view.reconstruction.label).toBe('Статус недоступен');
  });
  test('a source access failure is not mislabeled as worker availability or a saved video', () => {
    const view = teachingCatalogPresentation(saved({sourceState: 'unavailable', sourceFailure: 'catalog_access_denied'}), {nowMs: now});
    expect(view.source.label).toBe('Нет доступа к заданию');
    expect(view.source.tone).toBe('error');
    expect(view.action.kind).toBe('review');
  });
});

describe('recording catalog interaction', () => {
  test('realistic source/device/failed-map/ready-for-review cards remain independent', () => {
    render(<TeachingRecordingCatalog entries={fixture} selectedId={fixture[0].id} onSelect={jest.fn()} nowMs={now}/>);
    expect(screen.getAllByText('Эмулятор 11')).toHaveLength(2);
    expect(screen.getByText('Эмулятор 12')).toBeInTheDocument();
    expect(screen.getAllByText('0:36')).toHaveLength(3);
    expect(screen.getByText('Обработка остановлена с ошибкой')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Открыть диагностику'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Открыть карту'})).toBeInTheDocument();
    expect(screen.getByText('Выбрана')).toBeInTheDocument();
    expect(screen.queryByText(/^Готов$/)).not.toBeInTheDocument();
    expect(screen.getByText(/Карта допущена к проверке; автоматический проезд этим не подтверждён/)).toBeInTheDocument();
  });
  test('only explicit preparation click invokes that callback; selection and rerender do not', () => {
    const select = jest.fn(), prepare = jest.fn();
    const props = {entries: fixture, selectedId: null, onSelect: select, onPrepare: prepare, nowMs: now};
    const view = render(<TeachingRecordingCatalog {...props}/>);
    expect(prepare).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', {name: 'Открыть запись «Спокойный заезд»'}));
    expect(select).toHaveBeenCalledWith(fixture[0].id);
    expect(prepare).not.toHaveBeenCalled();
    view.rerender(<TeachingRecordingCatalog {...props} selectedId={fixture[0].id}/>);
    expect(prepare).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', {name: 'Подготовить маршрут'}));
    expect(prepare).toHaveBeenCalledTimes(1);
    expect(prepare).toHaveBeenCalledWith(fixture[0].id);
  });
  test('search and paging keep selected recording identity instead of selecting another', () => {
    const entries = Array.from({length: 25}, (_, i) => saved({id: String(i), title: `Запись ${i}`, createdAt: now + i}));
    const select = jest.fn();
    render(<TeachingRecordingCatalog entries={entries} selectedId="24" onSelect={select} nowMs={now}/>);
    expect(within(screen.getByRole('list', {name: 'Сохранённые записи'})).getAllByRole('listitem')).toHaveLength(12);
    fireEvent.click(screen.getByRole('button', {name: 'Далее'}));
    expect(screen.getByText(/страница 2 из 3/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Найти запись'), {target: {value: 'Запись 24'}});
    expect(screen.getByText(/страница 1 из 1/)).toBeInTheDocument();
    expect(screen.getByText('Выбрана')).toBeInTheDocument();
    expect(select).not.toHaveBeenCalled();
  });
  test('native keyboard activation opens the intended recording', async () => {
    const user = userEvent.setup(), select = jest.fn();
    render(<TeachingRecordingCatalog entries={[fixture[0]]} selectedId={null} onSelect={select} nowMs={now}/>);
    const button = screen.getByRole('button', {name: 'Открыть запись «Спокойный заезд»'});
    button.focus();
    await user.keyboard('{Enter}');
    expect(select).toHaveBeenCalledTimes(1);
    expect(select).toHaveBeenCalledWith(fixture[0].id);
  });
  test('read-only preserves inspection while unavailable selection is separately disabled', () => {
    const select = jest.fn(), prepare = jest.fn();
    const view = render(<TeachingRecordingCatalog entries={[fixture[0]]} selectedId={null} onSelect={select} onPrepare={prepare} readOnly nowMs={now}/>);
    expect(screen.queryByRole('button', {name: 'Подготовить маршрут'})).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: 'Открыть запись «Спокойный заезд»'}));
    expect(select).toHaveBeenCalledTimes(1);
    view.rerender(<TeachingRecordingCatalog entries={[fixture[0]]} selectedId={null} onSelect={select} onPrepare={prepare} disabled nowMs={now}/>);
    expect(screen.getByRole('button', {name: 'Открыть запись «Спокойный заезд»'})).toBeDisabled();
    expect(prepare).not.toHaveBeenCalled();
  });
  test('loading differs from empty; reload is explicit and search misses are reversible', () => {
    const reload = jest.fn(), select = jest.fn();
    const view = render(<TeachingRecordingCatalog entries={[]} selectedId={null} onSelect={select} onReload={reload} loading nowMs={now}/>);
    expect(screen.getByText('Читаем сохранённые записи…')).toBeInTheDocument();
    expect(screen.queryByText('Записей пока нет')).not.toBeInTheDocument();
    view.rerender(<TeachingRecordingCatalog entries={[]} selectedId={null} onSelect={select} onReload={reload} nowMs={now}/>);
    expect(screen.getByText('Записей пока нет')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: 'Обновить библиотеку'}));
    expect(reload).toHaveBeenCalledTimes(1);
    view.rerender(<TeachingRecordingCatalog entries={fixture} selectedId={null} onSelect={select} nowMs={now}/>);
    fireEvent.change(screen.getByLabelText('Найти запись'), {target: {value: 'Совсем другой маршрут'}});
    expect(screen.getByText('Записи не найдены')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: 'Сбросить поиск и фильтр'}));
    expect(screen.getByRole('button', {name: 'Открыть запись «Спокойный заезд»'})).toBeInTheDocument();
  });
  test('stale statuses and truncated scan are clearly labelled', () => {
    render(<TeachingRecordingCatalog entries={[{...fixture[2], statusCheckedAt: now - 30001}]} selectedId={null} onSelect={jest.fn()} truncated nowMs={now}/>);
    expect(screen.getByText('Ранее: карта для проверки')).toBeInTheDocument();
    expect(screen.getByText(/Состояние обработки устарело/)).toBeInTheDocument();
    expect(screen.getByText(/достигнут предел безопасного чтения/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: /Карта для проверки 0/}));
    expect(screen.getByText('Записи не найдены')).toBeInTheDocument();
  });
  test('long titles and metadata use wrapping and a single-column mobile grid', () => {
    render(<TeachingRecordingCatalog entries={[saved({title: 'ОченьДлинноеНазвание'.repeat(20), deviceName: 'ДлинноеУстройство'.repeat(20)})]} selectedId={null} onSelect={jest.fn()} nowMs={now}/>);
    const grid = screen.getByRole('list', {name: 'Сохранённые записи'});
    expect(grid).toHaveClass('grid', 'min-w-0', 'md:grid-cols-2');
    expect(grid).not.toHaveClass('grid-cols-2');
    expect(screen.getByRole('heading', {level: 4})).toHaveClass('break-words');
  });
});
