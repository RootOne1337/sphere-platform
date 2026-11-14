import { getStreamAspectRatio } from '@/src/features/stream/streamAspectRatio';

describe('stream viewport aspect ratio', () => {
  it('uses a landscape 16:9 viewport until the first decoded frame arrives', () => {
    expect(getStreamAspectRatio()).toBe('16 / 9');
    expect(getStreamAspectRatio({ width: 0, height: 1080 })).toBe('16 / 9');
  });

  it('follows the actual decoded frame orientation', () => {
    expect(getStreamAspectRatio({ width: 1920, height: 1080 })).toBe('1920 / 1080');
    expect(getStreamAspectRatio({ width: 1080, height: 1920 })).toBe('1080 / 1920');
  });
});
