/**
 * Тесты Zustand-стора useStreamStore — настройки стриминга.
 */
import { useStreamStore } from '@/src/shared/store/useStreamStore';

describe('useStreamStore', () => {
  beforeEach(() => {
    useStreamStore.setState({
      gridSize: 4,
      objectFit: 'contain',
      quality: 'auto',
      showHUD: true,
      showStats: true,
    });
  });

  describe('начальное состояние', () => {
    it('gridSize = 4', () => expect(useStreamStore.getState().gridSize).toBe(4));
    it('objectFit = contain', () => expect(useStreamStore.getState().objectFit).toBe('contain'));
    it('quality = auto', () => expect(useStreamStore.getState().quality).toBe('auto'));
    it('showHUD = true', () => expect(useStreamStore.getState().showHUD).toBe(true));
    it('showStats = true', () => expect(useStreamStore.getState().showStats).toBe(true));
  });

  describe('setGridSize', () => {
    it.each([1, 4, 9, 16] as const)('устанавливает размер сетки %d', (size) => {
      useStreamStore.getState().setGridSize(size);
      expect(useStreamStore.getState().gridSize).toBe(size);
    });
  });

  describe('setObjectFit', () => {
    it.each(['contain', 'cover', 'fill'] as const)('устанавливает %s', (fit) => {
      useStreamStore.getState().setObjectFit(fit);
      expect(useStreamStore.getState().objectFit).toBe(fit);
    });
  });

  describe('setQuality', () => {
    it.each(['auto', '1080p', '720p', 'low'] as const)('устанавливает %s', (q) => {
      useStreamStore.getState().setQuality(q);
      expect(useStreamStore.getState().quality).toBe(q);
    });
  });

  describe('toggleHUD', () => {
    it('переключает HUD', () => {
      useStreamStore.getState().toggleHUD();
      expect(useStreamStore.getState().showHUD).toBe(false);

      useStreamStore.getState().toggleHUD();
      expect(useStreamStore.getState().showHUD).toBe(true);
    });
  });

  describe('toggleStats', () => {
    it('переключает статистику', () => {
      useStreamStore.getState().toggleStats();
      expect(useStreamStore.getState().showStats).toBe(false);
    });
  });
});
