import { act, renderHook } from '@testing-library/react';
import { defaultFleetTablePreferences, FLEET_TABLE_KEY, parseFleetTablePreferences, useFleetTablePreferences } from '@/src/features/devices/fleetTablePreferences';

const storageGet = jest.mocked(window.localStorage.getItem).getMockImplementation();
const storageSet = jest.mocked(window.localStorage.setItem).getMockImplementation();
beforeEach(() => {
  jest.restoreAllMocks();
  jest.mocked(window.localStorage.getItem).mockImplementation(storageGet!);
  jest.mocked(window.localStorage.setItem).mockImplementation(storageSet!);
  window.localStorage.clear();
});

it.each(['{', 'null', '{"version":99}', 'x'.repeat(8193)])('falls back for damaged, unsupported or oversized preferences', (raw) => {
  expect(parseFleetTablePreferences(raw)).toEqual(defaultFleetTablePreferences());
});

it('drops unknown columns, invalid sort directions, duplicates and mandatory-column overrides', () => {
  const result = parseFleetTablePreferences(JSON.stringify({ version: 1, columnVisibility: { name: false, network: true, unknown: false, tags: 'false' },
    sorting: [{ id: 'unknown', desc: false }, { id: 'name', desc: false }, { id: 'name', desc: true }, { id: 'status', desc: 'true' }] }));
  expect(result.columnVisibility).toEqual({ ...defaultFleetTablePreferences().columnVisibility, network: true });
  expect(result.sorting).toEqual([{ id: 'name', desc: false }]);
});

it('hydrates without overwriting existing preferences and resets them explicitly', () => {
  window.localStorage.setItem(FLEET_TABLE_KEY, JSON.stringify({ version: 1, columnVisibility: { network: true }, sorting: [{ id: 'name', desc: true }] }));
  jest.mocked(window.localStorage.setItem).mockClear();
  const { result } = renderHook(useFleetTablePreferences);
  expect(result.current.columnVisibility.network).toBe(true);
  expect(window.localStorage.setItem).not.toHaveBeenCalled();
  act(() => result.current.reset());
  expect(result.current.sorting).toEqual([]);
  expect(result.current.columnVisibility.network).toBe(false);
});

it('keeps the table usable when localStorage is denied or full and reports temporary settings', () => {
  jest.spyOn(window.localStorage, 'getItem').mockImplementation(() => { throw new Error('denied'); });
  jest.spyOn(window.localStorage, 'setItem').mockImplementation(() => { throw new Error('quota'); });
  const { result } = renderHook(useFleetTablePreferences);
  expect(result.current.storageUnavailable).toBe(true);
  act(() => result.current.setColumnVisibility((previous) => ({ ...previous, network: true })));
  expect(result.current.columnVisibility.network).toBe(true);
  expect(result.current.storageUnavailable).toBe(true);
});

it('ignores storage events from other storage areas without writing them back', () => {
  const { result } = renderHook(useFleetTablePreferences);
  jest.mocked(window.localStorage.setItem).mockClear();
  act(() => window.dispatchEvent(new StorageEvent('storage', { key: FLEET_TABLE_KEY, newValue: JSON.stringify({ version: 1, columnVisibility: { tags: true } }) })));
  // jsdom cannot attach its mocked Storage as storageArea; null events do not alter state.
  expect(result.current.columnVisibility.tags).toBe(false);
  expect(window.localStorage.setItem).not.toHaveBeenCalled();
});

it('sanitizes column order, widths and pinning while migrating the old presentation shape', () => {
  const old = parseFleetTablePreferences('{"version":1,"columnVisibility":{"network":true},"sorting":[{"id":"name","desc":true}]}');
  expect(old.columnOrder[0]).toBe('name'); expect(old.columnPinning.name).toBe('left');
  const next = parseFleetTablePreferences(JSON.stringify({ version: 1, columnOrder: ['status', 'name', 'status', 'arbitrary'],
    columnSizing: { name: 320.4, agent_version: 10, status: 9999, android_id: '200', unknown: 200 },
    columnPinning: { status: 'right', name: null, android_id: 'bad' } }));
  expect(next.columnOrder.slice(0, 2)).toEqual(['status', 'name']);
  expect(new Set(next.columnOrder).size).toBe(next.columnOrder.length);
  expect(next.columnOrder).not.toContain('arbitrary');
  expect(next.columnSizing).toEqual({ name: 320 });
  expect(next.columnPinning).toEqual({ name: null, status: 'right' });
});

it('persists layout without overwriting current visibility and sorting', () => {
  const { result } = renderHook(useFleetTablePreferences);
  act(() => result.current.setSorting([{ id: 'name', desc: true }]));
  act(() => result.current.setColumnVisibility({ network: true }));
  act(() => result.current.setColumnLayout({ columnOrder: ['status', 'name'], columnSizing: { name: 280 }, columnPinning: { name: null } }));
  const saved = parseFleetTablePreferences(localStorage.getItem(FLEET_TABLE_KEY));
  expect(saved.sorting).toEqual([{ id: 'name', desc: true }]);
  expect(saved.columnVisibility.network).toBe(true);
  expect(saved.columnOrder.slice(0, 2)).toEqual(['status', 'name']);
  expect(saved.columnSizing.name).toBe(280);
});
