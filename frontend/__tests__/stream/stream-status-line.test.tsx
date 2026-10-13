import { render, screen } from '@testing-library/react';
import { StreamStatusLine } from '@/src/features/stream/StreamStatusLine';

const healthy = { direct: true, directInput: true, live: true, rtt: 1.5, width: 960, height: 540, fps: 59.94, bitrate: 12_345_678 };
test('compact line shows actual receive measurements and distinguishes network RTT from full video latency', () => {
  render(<StreamStatusLine {...healthy} />);
  const line = screen.getByLabelText('Сводка видеопотока');
  expect(line).toHaveTextContent('Прямой канал · видео и касания'); expect(line).toHaveTextContent('RTT 1.5 мс');
  expect(line).toHaveTextContent('960 × 540'); expect(line).toHaveTextContent('60 FPS'); expect(line).toHaveTextContent('12.3 Мбит/с');
  expect(screen.getByTitle(/не полная задержка/)).toBeInTheDocument();
  expect(screen.getByTitle(/не максимальная скорость/)).toBeInTheDocument();
});
test('paused presentation never displays historic bitrate or FPS as current', () => {
  render(<StreamStatusLine {...healthy} live={false} />);
  expect(screen.getByLabelText('Сводка видеопотока')).not.toHaveTextContent('60 FPS');
  expect(screen.getByLabelText('Сводка видеопотока')).not.toHaveTextContent('12.3 Мбит/с');
});
test('video direct alone does not imply direct input and invalid or missing rates remain unknown', () => {
  render(<StreamStatusLine {...healthy} directInput={false} fps={NaN} bitrate={Infinity} rtt={null} />);
  expect(screen.getByLabelText('Сводка видеопотока')).toHaveTextContent('Видео напрямую');
  expect(screen.getByLabelText('Сводка видеопотока')).not.toHaveTextContent('видео и касания');
  expect(screen.getByLabelText('Сводка видеопотока')).toHaveTextContent('— FPS');
});
test('server RTT is labelled as the server segment without borrowing the Android ACK', () => {
  render(<StreamStatusLine {...healthy} direct={false} directInput={false} live={false} rtt={250} />);
  expect(screen.getByLabelText('Сводка видеопотока')).toHaveTextContent('RTT сервера 250 мс');
  expect(screen.getByTitle(/не RTT до APK, не ACK/)).toBeInTheDocument();
});
