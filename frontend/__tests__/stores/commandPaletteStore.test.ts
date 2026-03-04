/**
 * Тесты Zustand-стора useCommandPaletteStore — управление палитрой команд.
 */
import { useCommandPaletteStore } from '@/src/features/navigation/commandPaletteStore';

describe('useCommandPaletteStore', () => {
  beforeEach(() => {
    useCommandPaletteStore.setState({ isOpen: false });
  });

  it('начальное состояние: закрыта', () => {
    expect(useCommandPaletteStore.getState().isOpen).toBe(false);
  });

  describe('open', () => {
    it('открывает палитру', () => {
      useCommandPaletteStore.getState().open();
      expect(useCommandPaletteStore.getState().isOpen).toBe(true);
    });
  });

  describe('close', () => {
    it('закрывает палитру', () => {
      useCommandPaletteStore.getState().open();
      useCommandPaletteStore.getState().close();
      expect(useCommandPaletteStore.getState().isOpen).toBe(false);
    });
  });

  describe('toggle', () => {
    it('переключает состояние', () => {
      useCommandPaletteStore.getState().toggle();
      expect(useCommandPaletteStore.getState().isOpen).toBe(true);

      useCommandPaletteStore.getState().toggle();
      expect(useCommandPaletteStore.getState().isOpen).toBe(false);
    });
  });
});
