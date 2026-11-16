import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ScooterFiveMapRoute, scooterFiveCatalogEntry } from '@/src/features/stream/ScooterFiveMapRoute';
import { TeachingRecordingCatalog } from '@/src/features/stream/TeachingRecordingCatalog';
import type { TeachingCatalogEntry } from '@/src/features/stream/teachingCatalog';

const scooter5 = {...scooterFiveCatalogEntry, preview: <ScooterFiveMapRoute/>};
const recording: TeachingCatalogEntry = {
  id: 'a'.repeat(32), title: 'skuter4 (no gui)', createdAt: scooter5.createdAt - 1000,
  frames: 829, durationSeconds: 31, sourceState: 'saved',
};

test('puts Scooter 5 in the same searchable catalog as recorded routes', () => {
  render(<TeachingRecordingCatalog entries={[recording]} mapRoutes={[scooter5]} selectedId={null} onSelect={jest.fn()}/>);
  const grid = screen.getByRole('list', {name: 'Маршруты'});
  const cards = within(grid).getAllByRole('listitem');
  expect(cards).toHaveLength(2);
  expect(within(cards[0]).getByRole('heading', {name: scooter5.title})).toBeVisible();
  expect(within(cards[1]).getByRole('heading', {name: recording.title})).toBeVisible();
  expect(screen.getAllByRole('heading', {name: scooter5.title})).toHaveLength(1);

  const search = screen.getByRole('searchbox', {name: 'Найти маршрут'});
  fireEvent.change(search, {target: {value: 'Ariane'}});
  expect(within(grid).getAllByRole('listitem')).toHaveLength(1);
  expect(within(grid).getByRole('heading', {name: scooter5.title})).toBeVisible();

  fireEvent.change(search, {target: {value: ''}});
  fireEvent.click(screen.getByRole('button', {name: /Видео сохранено 1/}));
  expect(within(grid).queryByRole('heading', {name: scooter5.title})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: /Карта для проверки 1/}));
  expect(within(grid).getByRole('heading', {name: scooter5.title})).toBeVisible();
});

test('opens the Ariane map from its card without selecting a video or launching control', async () => {
  const onSelect = jest.fn();
  const user = userEvent.setup();
  render(<TeachingRecordingCatalog entries={[recording]} mapRoutes={[scooter5]} selectedId={null} onSelect={onSelect}/>);
  const open = screen.getByRole('button', {name: `Открыть карту «${scooter5.title}»`});
  await user.click(open);
  const map = screen.getByRole('dialog', {name: scooter5.title});
  expect(within(map).getByRole('img', {name: /Контур Scooter 5/})).toBeVisible();
  expect(within(map).getByText(/Живой запуск ожидает проверки/)).toBeVisible();
  expect(within(map).queryByRole('button', {name: /запуск/i})).not.toBeInTheDocument();
  expect(onSelect).not.toHaveBeenCalled();
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(open).toHaveFocus();
});
