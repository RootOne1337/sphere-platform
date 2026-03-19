/**
 * Тесты Zustand-стора useInspectorStore — боковая панель инспектора.
 */
import { useInspectorStore } from '@/src/features/inspector/inspectorStore';

describe('useInspectorStore', () => {
  beforeEach(() => {
    useInspectorStore.setState({
      isOpen: false,
      contentType: null,
      contentId: null,
      payload: null,
    });
  });

  describe('начальное состояние', () => {
    it('закрыт', () => expect(useInspectorStore.getState().isOpen).toBe(false));
    it('contentType = null', () => expect(useInspectorStore.getState().contentType).toBeNull());
    it('contentId = null', () => expect(useInspectorStore.getState().contentId).toBeNull());
    it('payload = null', () => expect(useInspectorStore.getState().payload).toBeNull());
  });

  describe('openInspector', () => {
    it('открывает с типом device', () => {
      useInspectorStore.getState().openInspector('device', 'dev-001');

      const state = useInspectorStore.getState();
      expect(state.isOpen).toBe(true);
      expect(state.contentType).toBe('device');
      expect(state.contentId).toBe('dev-001');
      expect(state.payload).toBeNull();
    });

    it('открывает с типом task и payload', () => {
      const payload = { status: 'running', progress: 0.5 };
      useInspectorStore.getState().openInspector('task', 'task-001', payload);

      const state = useInspectorStore.getState();
      expect(state.contentType).toBe('task');
      expect(state.payload).toEqual(payload);
    });

    it('поддерживает тип vpn', () => {
      useInspectorStore.getState().openInspector('vpn', 'vpn-001');
      expect(useInspectorStore.getState().contentType).toBe('vpn');
    });

    it('поддерживает тип script', () => {
      useInspectorStore.getState().openInspector('script', 'scr-001');
      expect(useInspectorStore.getState().contentType).toBe('script');
    });
  });

  describe('closeInspector', () => {
    it('закрывает панель (сохраняет contentType/contentId)', () => {
      useInspectorStore.getState().openInspector('device', 'dev-001');
      useInspectorStore.getState().closeInspector();

      expect(useInspectorStore.getState().isOpen).toBe(false);
      // contentType и contentId остаются для анимации закрытия
    });
  });

  describe('переключение между элементами', () => {
    it('заменяет контент при повторном openInspector', () => {
      useInspectorStore.getState().openInspector('device', 'dev-001');
      useInspectorStore.getState().openInspector('task', 'task-002', { status: 'done' });

      const state = useInspectorStore.getState();
      expect(state.isOpen).toBe(true);
      expect(state.contentType).toBe('task');
      expect(state.contentId).toBe('task-002');
    });
  });
});
