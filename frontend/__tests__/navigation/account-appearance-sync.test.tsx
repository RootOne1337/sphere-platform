import { act, render, screen } from '@testing-library/react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { AccountAppearanceSync, useAccountAppearance } from '@/src/features/preferences/AccountAppearanceSync';
import { DEFAULT_APPEARANCE, type Appearance } from '@/src/features/preferences/accountAppearance';
import { useThemeStore } from '@/src/shared/store/themeStore';
import { useUIStore } from '@/src/shared/store/useUIStore';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), patch: jest.fn() } }));
const get = jest.mocked(api.get);
const patch = jest.mocked(api.patch);

function receipt(revision: number, appearance: Partial<Appearance> = {}, org = 'a', user = 'one') {
  return {
    data: {
      schema_version: 1, org_id: org, user_id: user, revision,
      appearance: { ...DEFAULT_APPEARANCE, ...appearance },
    },
    headers: { etag: '"ui-' + revision + '"' },
  };
}

function identify(org: string, id: string) {
  useAuthStore.getState().setUser({ id, org_id: org, email: id + '@example.org', role: 'viewer' });
}

function View() {
  const { status, reload } = useAccountAppearance();
  return <><output>{status}</output><button onClick={reload}>Load saved</button></>;
}

async function settle() {
  await act(async () => {});
}

async function debounce() {
  await act(async () => { jest.advanceTimersByTime(350); });
}

beforeEach(() => {
  localStorage.clear();
  get.mockReset();
  patch.mockReset();
  identify('a', 'one');
  jest.useFakeTimers();
});

afterEach(() => jest.useRealTimers());

it('hydrates the server profile and saves changes made during a pending request against its receipt', async () => {
  get.mockResolvedValue(receipt(2, { palette: 'light-corporate' }));
  let resolveFirst!: (value: ReturnType<typeof receipt>) => void;
  patch.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
    .mockResolvedValueOnce(receipt(4, { palette: 'light-corporate', accent_color: 'blue', font_size: 'lg' }));
  render(<AccountAppearanceSync><View /></AccountAppearanceSync>);
  await settle();
  expect(useThemeStore.getState().theme).toBe('light-corporate');

  act(() => useUIStore.getState().setAccentColor('blue'));
  await debounce();
  act(() => useUIStore.getState().setFontSize('lg'));
  await debounce();
  expect(patch).toHaveBeenCalledTimes(1);
  expect(patch).toHaveBeenLastCalledWith('/user-preferences/me', { accent_color: 'blue' },
    expect.objectContaining({ headers: { 'If-Match': '"ui-2"' } }));
  await act(async () => resolveFirst(receipt(3, { palette: 'light-corporate', accent_color: 'blue' })));
  expect(useUIStore.getState().fontSize).toBe('lg');
  await debounce();
  expect(patch).toHaveBeenLastCalledWith('/user-preferences/me', { font_size: 'lg' },
    expect.objectContaining({ headers: { 'If-Match': '"ui-3"' } }));
  expect(screen.getByRole('status')).toHaveTextContent('saved');
});

it.each([[412, 'conflict'], [503, 'offline']])(
  'keeps unsaved edits on %s until the user explicitly loads the saved profile', async (code, status) => {
    get.mockResolvedValueOnce(receipt(2)).mockResolvedValueOnce(receipt(3, { accent_color: 'emerald' }));
    patch.mockRejectedValueOnce({ response: { status: code } });
    render(<AccountAppearanceSync><View /></AccountAppearanceSync>);
    await settle();
    act(() => useUIStore.getState().setAccentColor('blue'));
    await debounce();
    expect(screen.getByRole('status')).toHaveTextContent(String(status));
    expect(useUIStore.getState().accentColor).toBe('blue');
    act(() => useUIStore.getState().setFontSize('lg'));
    await debounce();
    expect(patch).toHaveBeenCalledTimes(1);

    await act(async () => screen.getByRole('button', { name: 'Load saved' }).click());
    expect(useUIStore.getState()).toMatchObject({ accentColor: 'emerald', fontSize: 'base' });
    expect(screen.getByRole('status')).toHaveTextContent('saved');
  },
);

it('does not apply a foreign cache entry or a late receipt from the previous identity', async () => {
  localStorage.setItem('sphere-account-appearance:b:two', JSON.stringify(receipt(1, { palette: 'sandstone' }).data));
  let resolveFirst!: (value: ReturnType<typeof receipt>) => void;
  get.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
    .mockRejectedValueOnce({ response: { status: 503 } });
  render(<AccountAppearanceSync><View /></AccountAppearanceSync>);
  expect(useThemeStore.getState().theme).toBe('neo-dark');
  act(() => identify('b', 'two'));
  await act(async () => resolveFirst(receipt(1, { palette: 'light-corporate' })));
  expect(get.mock.calls[0][1]?.signal?.aborted).toBe(true);
  expect(useThemeStore.getState().theme).toBe('neo-dark');
  expect(screen.getByRole('status')).toHaveTextContent('offline');
  expect(patch).not.toHaveBeenCalled();
});
