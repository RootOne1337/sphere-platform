import { create } from 'zustand';

export type InspectorContentType = 'device' | 'task' | 'vpn' | 'script' | null;

interface InspectorState {
    isOpen: boolean;
    contentType: InspectorContentType;
    contentId: string | null;
    payload: unknown | null;

    openInspector: (type: InspectorContentType, id: string, payload?: unknown) => void;
    closeInspector: () => void;
}

export const useInspectorStore = create<InspectorState>((set) => ({
    isOpen: false,
    contentType: null,
    contentId: null,
    payload: null,

    openInspector: (type, id, payload = null) =>
        set({ isOpen: true, contentType: type, contentId: id, payload }),

    closeInspector: () =>
        set({ isOpen: false, payload: null }),
}));
